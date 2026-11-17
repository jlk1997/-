"""Creator commune: up to 10 people share a label queue and display board.

Does not share wallets, DSP passwords, or settlement cash.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import CreatorCommune, CreatorCommuneMember, DistributionDelivery, Release, User, Work
from app.services.distribution.automation import weekly_release_suggestions
from app.services.distribution.passport import live_store_counts

COMMUNE_MAX = 10
QUEUE_STATUSES = ("ops_queue", "awaiting_manual", "session_wait", "session_running", "submitting", "in_review")


def _invite_code() -> str:
    return secrets.token_hex(4).upper()


def _member_row(db: Session, user_id) -> CreatorCommuneMember | None:
    return db.query(CreatorCommuneMember).filter(CreatorCommuneMember.user_id == user_id).first()


def get_commune(db: Session, user: User) -> CreatorCommune | None:
    row = _member_row(db, user.id)
    if not row:
        return None
    return db.query(CreatorCommune).filter(CreatorCommune.id == row.commune_id).first()


def _serialize_commune(db: Session, commune: CreatorCommune, user: User) -> dict:
    members = (
        db.query(CreatorCommuneMember)
        .filter(CreatorCommuneMember.commune_id == commune.id)
        .all()
    )
    users = {u.id: u for u in db.query(User).filter(User.id.in_([m.user_id for m in members])).all()}
    return {
        "id": str(commune.id),
        "name": commune.name,
        "invite_code": commune.invite_code if any(m.user_id == user.id for m in members) else None,
        "member_count": len(members),
        "max_members": COMMUNE_MAX,
        "is_owner": commune.owner_id == user.id,
        "members": [
            {
                "user_id": str(m.user_id),
                "username": (users.get(m.user_id).username if users.get(m.user_id) else None),
                "display_name": (users.get(m.user_id).display_name if users.get(m.user_id) else None),
                "role": m.role,
                "mine": m.user_id == user.id,
            }
            for m in members
        ],
    }


def create_commune(db: Session, user: User, name: str) -> dict:
    if _member_row(db, user.id):
        raise HTTPException(400, "Already in a commune")
    title = (name or "").strip() or f"{user.display_name or user.username} 的公社"
    if len(title) > 80:
        raise HTTPException(400, "Name too long")
    commune = CreatorCommune(name=title, owner_id=user.id, invite_code=_invite_code())
    db.add(commune)
    db.flush()
    db.add(CreatorCommuneMember(commune_id=commune.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(commune)
    return _serialize_commune(db, commune, user)


def join_commune(db: Session, user: User, invite_code: str) -> dict:
    if _member_row(db, user.id):
        raise HTTPException(400, "Already in a commune")
    code = (invite_code or "").strip().upper()
    commune = db.query(CreatorCommune).filter(CreatorCommune.invite_code == code).first()
    if not commune:
        raise HTTPException(404, "Invite code not found")
    count = db.query(CreatorCommuneMember).filter(CreatorCommuneMember.commune_id == commune.id).count()
    if count >= COMMUNE_MAX:
        raise HTTPException(400, "Commune is full")
    db.add(CreatorCommuneMember(commune_id=commune.id, user_id=user.id, role="member"))
    db.commit()
    return _serialize_commune(db, commune, user)


def invite_username(db: Session, user: User, username: str) -> dict:
    commune = get_commune(db, user)
    if not commune:
        raise HTTPException(404, "Commune not found")
    if commune.owner_id != user.id:
        raise HTTPException(403, "Only the owner can invite")
    target = db.query(User).filter(User.username == (username or "").strip()).first()
    if not target:
        raise HTTPException(404, "User not found")
    if _member_row(db, target.id):
        raise HTTPException(400, "User already in a commune")
    count = db.query(CreatorCommuneMember).filter(CreatorCommuneMember.commune_id == commune.id).count()
    if count >= COMMUNE_MAX:
        raise HTTPException(400, "Commune is full")
    db.add(CreatorCommuneMember(commune_id=commune.id, user_id=target.id, role="member"))
    db.commit()
    return _serialize_commune(db, commune, user)


def leave_commune(db: Session, user: User) -> dict:
    row = _member_row(db, user.id)
    if not row:
        return {"left": True, "commune": None}
    commune = db.query(CreatorCommune).filter(CreatorCommune.id == row.commune_id).first()
    if commune and commune.owner_id == user.id:
        others = (
            db.query(CreatorCommuneMember)
            .filter(CreatorCommuneMember.commune_id == commune.id, CreatorCommuneMember.user_id != user.id)
            .count()
        )
        if others:
            raise HTTPException(400, "Owner must transfer or empty the commune first")
        db.delete(row)
        db.delete(commune)
        db.commit()
        return {"left": True, "commune": None, "dissolved": True}
    db.delete(row)
    db.commit()
    return {"left": True, "commune": None}


def commune_overview(db: Session, user: User) -> dict:
    commune = get_commune(db, user)
    if not commune:
        return {"commune": None, "max_members": COMMUNE_MAX}
    return {"commune": _serialize_commune(db, commune, user), "max_members": COMMUNE_MAX}


def commune_board(db: Session, user: User) -> dict:
    commune = get_commune(db, user)
    if not commune:
        return {"commune": None, "queue": [], "members": [], "calendar": []}
    payload = _serialize_commune(db, commune, user)
    member_ids = [uuid.UUID(row["user_id"]) for row in payload["members"]]
    deliveries = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.owner_id.in_(member_ids),
            DistributionDelivery.status.in_(QUEUE_STATUSES),
        )
        .order_by(DistributionDelivery.created_at.asc())
        .limit(40)
        .all()
    )
    work_ids = list({row.work_id for row in deliveries if row.work_id})
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(member_ids)).all()}
    queue = []
    for row in deliveries:
        meta = dict(row.attempt_meta or {})
        work = works.get(row.work_id)
        owner = users.get(row.owner_id)
        queue.append(
            {
                "delivery_id": str(row.id),
                "work_id": str(row.work_id) if row.work_id else None,
                "title": work.title if work else None,
                "channel_code": row.channel_code,
                "status": row.status,
                "priority_score": int(meta.get("priority_score") or 0),
                "owner_username": owner.username if owner else None,
                "mine": row.owner_id == user.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    member_stats = []
    for member in payload["members"]:
        uid = uuid.UUID(member["user_id"])
        member_user = users.get(uid)
        unpublished = 0
        publishing = 0
        live_total = 0
        if member_user:
            active = {
                r.work_id
                for r in db.query(Release)
                .filter(Release.owner_id == uid, Release.status.in_(("queued", "delivering", "live")))
                .all()
            }
            owned = (
                db.query(Work)
                .filter(Work.owner_id == uid)
                .order_by(Work.created_at.desc())
                .limit(40)
                .all()
            )
            unpublished = sum(1 for work in owned if work.id not in active and (work.audio_url or work.storage_key))
            publishing = (
                db.query(DistributionDelivery)
                .filter(
                    DistributionDelivery.owner_id == uid,
                    DistributionDelivery.status.in_(QUEUE_STATUSES),
                )
                .count()
            )
            counts = live_store_counts(db, [work.id for work in owned[:20]])
            live_total = sum(int(counts.get(work.id, counts.get(str(work.id), 0))) for work in owned[:20])
        member_stats.append({**member, "unpublished": unpublished, "publishing": publishing, "live_stores": live_total})
    calendar = weekly_release_suggestions(db, user, limit=3)
    return {
        "commune": payload,
        "queue": queue,
        "members": member_stats,
        "calendar": calendar,
        "wallet_shared": False,
        "note": "公社只共享厂牌代发队列与看板，不共享钱包、对账单和第三方账号。",
    }
