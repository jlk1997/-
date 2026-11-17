"""Work split sheet — owner + remix parent + collaborators, sums to 100."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import User, Work, WorkSplitShare

PARENT_PERCENT = 20
MAX_SHARES = 4


def _raw_shares(db: Session, work: Work) -> list[dict]:
    rows = (
        db.query(WorkSplitShare)
        .filter(WorkSplitShare.work_id == work.id)
        .order_by(WorkSplitShare.created_at.asc())
        .all()
    )
    if rows:
        return [{"user_id": row.user_id, "role": row.role, "percent": row.percent} for row in rows]
    shares = [{"user_id": work.owner_id, "role": "owner", "percent": 100}]
    if work.parent_work_id:
        parent = db.query(Work).filter(Work.id == work.parent_work_id).first()
        if parent and parent.owner_id != work.owner_id:
            shares = [
                {"user_id": work.owner_id, "role": "owner", "percent": 100 - PARENT_PERCENT},
                {"user_id": parent.owner_id, "role": "parent", "percent": PARENT_PERCENT},
            ]
    return shares


def default_shares(db: Session, work: Work) -> list[dict]:
    return _with_usernames(db, _raw_shares(db, work))


def list_splits(db: Session, work: Work) -> list[dict]:
    return _with_usernames(db, _raw_shares(db, work))


def replace_splits(db: Session, work: Work, items: list[dict], *, actor: User) -> list[dict]:
    if actor.id != work.owner_id and not getattr(actor, "is_admin", False):
        raise HTTPException(403, "Only the work owner can edit splits")
    if not items or len(items) > MAX_SHARES:
        raise HTTPException(400, f"Split sheet needs 1–{MAX_SHARES} people")
    cleaned = []
    seen = set()
    total = 0
    for item in items:
        raw_id = item.get("user_id")
        username = str(item.get("username") or "").strip()
        if not raw_id and username:
            found = db.query(User).filter(User.username == username).first()
            if not found:
                raise HTTPException(400, "Collaborator not found")
            raw_id = found.id
        try:
            uid = uuid.UUID(str(raw_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Invalid collaborator") from exc
        if uid in seen:
            raise HTTPException(400, "Duplicate collaborator")
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise HTTPException(400, "Collaborator not found")
        percent = int(item.get("percent") or 0)
        if percent <= 0 or percent > 100:
            raise HTTPException(400, "Each share must be 1–100")
        role = str(item.get("role") or "collaborator")
        if role not in {"owner", "parent", "collaborator"}:
            role = "collaborator"
        seen.add(uid)
        total += percent
        cleaned.append(WorkSplitShare(work_id=work.id, user_id=uid, role=role, percent=percent))
    if total != 100:
        raise HTTPException(400, "Shares must add up to 100")
    db.query(WorkSplitShare).filter(WorkSplitShare.work_id == work.id).delete()
    for row in cleaned:
        db.add(row)
    db.commit()
    return list_splits(db, work)


def expand_split_lines(db: Session, work_id, owner_id, gross: int, commission: int, net: int) -> list[dict]:
    work = db.query(Work).filter(Work.id == work_id).first() if work_id else None
    shares = _raw_shares(db, work) if work else [{"user_id": owner_id, "role": "owner", "percent": 100}]
    if not shares:
        shares = [{"user_id": owner_id, "role": "owner", "percent": 100}]
    parts = []
    used_g = used_c = used_n = 0
    for i, share in enumerate(shares):
        last = i == len(shares) - 1
        if last:
            g, c, n = gross - used_g, commission - used_c, net - used_n
        else:
            pct = int(share.get("percent") or 0)
            g = gross * pct // 100
            c = commission * pct // 100
            n = net * pct // 100
            used_g += g
            used_c += c
            used_n += n
        parts.append(
            {
                "user_id": share["user_id"],
                "role": share.get("role") or "owner",
                "percent": share.get("percent"),
                "gross_minor": g,
                "commission_minor": c,
                "net_minor": n,
            }
        )
    return parts


def _with_usernames(db: Session, shares: list[dict]) -> list[dict]:
    ids = [row["user_id"] for row in shares]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    out = []
    for row in shares:
        user = users.get(row["user_id"])
        out.append(
            {
                "user_id": str(row["user_id"]),
                "role": row["role"],
                "percent": row["percent"],
                "username": user.username if user else None,
            }
        )
    return out
