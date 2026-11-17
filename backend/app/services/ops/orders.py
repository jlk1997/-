"""The delivery row is the release order for one channel."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, Release, ReleaseMetadata, User, Work
from app.services.admin_audit import log_admin_action
from app.services.distribution.channel_fields import handoff_lines, missing_release_fields, paste_sheet


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise HTTPException(400, "Invalid id") from exc


def order_brief(row: DistributionDelivery) -> dict:
    return {
        "id": str(row.id),
        "release_id": str(row.release_id),
        "work_id": str(row.work_id),
        "owner_id": str(row.owner_id),
        "channel_code": row.channel_code,
        "status": row.status,
        "store_url": row.store_url,
        "assignee_id": str(row.ops_assignee_id) if getattr(row, "ops_assignee_id", None) else None,
        "claimed_at": row.ops_claimed_at.isoformat() if getattr(row, "ops_claimed_at", None) else None,
        "note": getattr(row, "ops_note", None) or "",
        "info_status": str((row.attempt_meta or {}).get("info_status") or ""),
        "requested_fields": list((row.attempt_meta or {}).get("requested_fields") or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_orders(db: Session, *, status: str | None = None, channel_code: str | None = None, limit: int = 50) -> list[dict]:
    query = db.query(DistributionDelivery).order_by(DistributionDelivery.updated_at.desc())
    if status:
        query = query.filter(DistributionDelivery.status == status)
    if channel_code:
        query = query.filter(DistributionDelivery.channel_code == channel_code)
    return [order_brief(row) for row in query.limit(min(max(limit, 1), 100)).all()]


def order_detail(db: Session, delivery_id: str) -> dict:
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == _uuid(delivery_id)).first()
    if not row:
        raise HTTPException(404, "Order not found")
    release = db.query(Release).filter(Release.id == row.release_id).first()
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == row.release_id).first() if release else None
    work = db.query(Work).filter(Work.id == row.work_id).first()
    owner = db.query(User).filter(User.id == row.owner_id).first()
    channels = list(release.selected_channels or []) if release else [row.channel_code]
    return {
        **order_brief(row),
        "mode": release.mode if release else None,
        "owner_email": owner.email if owner else None,
        "title": (meta.title if meta else None) or (work.title if work else None),
        "artist_name": meta.artist_name if meta else None,
        "lyrics": meta.lyrics if meta else None,
        "isrc": meta.isrc if meta else None,
        "upc": meta.upc if meta else None,
        "language": meta.language if meta else None,
        "genres": meta.genres if meta else [],
        "cover_url": (meta.cover_url if meta else None) or (work.cover_url if work else None),
        "audio_url": work.audio_url if work else None,
        "ai_disclosed": bool(meta.ai_disclosed) if meta else None,
        "listing": (meta.extra or {}).get("listing") if meta and isinstance(meta.extra, dict) else {},
        "kit_url": release.kit_url if release else None,
        "missing_fields": missing_release_fields(meta, [row.channel_code]),
        "handoff": handoff_lines(meta, [row.channel_code]),
        "paste_sheet": paste_sheet(handoff_lines(meta, [row.channel_code])),
        "field_status": "draft_needs_ops_check",
    }


def claim_order(db: Session, actor: User, delivery_id: str) -> dict:
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == _uuid(delivery_id)).first()
    if not row:
        raise HTTPException(404, "Order not found")
    row.ops_assignee_id = actor.id
    row.ops_claimed_at = datetime.utcnow()
    db.commit()
    log_admin_action(db, admin_id=actor.id, action="claim_release_order", target=str(row.id))
    return order_brief(row)


def note_order(db: Session, actor: User, delivery_id: str, note: str) -> dict:
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == _uuid(delivery_id)).first()
    if not row:
        raise HTTPException(404, "Order not found")
    row.ops_note = (note or "")[:2000]
    db.commit()
    log_admin_action(db, admin_id=actor.id, action="note_release_order", target=str(row.id), detail={"note": row.ops_note})
    return order_brief(row)


def inbox_counts(db: Session) -> dict:
    rows = db.query(DistributionDelivery).all()
    waiting = 0
    errors = 0
    waiting_user = 0
    for row in rows:
        status = row.status
        if status in {"ops_queue", "awaiting_manual", "session_wait"} and not row.store_url:
            waiting += 1
        if row.last_error and ("fill_incomplete" in str(row.last_error) or "selector_broke" in str(row.last_error)):
            errors += 1
        if str((row.attempt_meta or {}).get("info_status") or "") == "waiting_user" or status == "needs_creator":
            waiting_user += 1
    return {"waiting_receipt": waiting, "extension_errors": errors, "waiting_user": waiting_user}


def request_creator_fields(db: Session, actor: User, delivery_id: str, fields: list[str]) -> dict:
    """Ask the creator for missing store fields. The order leaves the active queue until they reply."""
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == _uuid(delivery_id)).first()
    if not row:
        raise HTTPException(404, "Order not found")
    asked = [str(field) for field in fields if str(field).strip()]
    if not asked:
        raise HTTPException(400, "Pick at least one field")
    blob = dict(row.attempt_meta or {})
    blob["requested_fields"] = asked
    blob["info_status"] = "waiting_user"
    blob["requested_at"] = datetime.utcnow().isoformat()
    row.attempt_meta = blob
    if row.status in {"ops_queue", "awaiting_manual", "submitting"}:
        row.status = "needs_creator"
    from app.services.notifications import create_notification

    create_notification(
        db,
        row.owner_id,
        "release_fields",
        {
            "delivery_id": str(row.id),
            "work_id": str(row.work_id),
            "fields": asked,
            "message": "发行还差几项资料，补上后我们继续帮你交歌。",
        },
        commit=False,
    )
    db.commit()
    log_admin_action(
        db,
        admin_id=actor.id,
        action="request_release_fields",
        target=str(row.id),
        detail={"fields": asked},
    )
    try:
        from app.services.wechat_subscribe import try_notify_release_fields

        try_notify_release_fields(db, row.owner_id, fields=asked)
    except Exception:
        pass
    return order_detail(db, delivery_id)


def settle_field_requests(db: Session, release) -> int:
    """When the creator fills what ops asked for, the order returns to the manual queue."""
    from app.services.distribution.channel_fields import missing_release_fields

    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    returned = 0
    for row in rows:
        blob = dict(row.attempt_meta or {})
        if blob.get("info_status") != "waiting_user":
            continue
        asked = [str(field) for field in (blob.get("requested_fields") or [])]
        gaps = {item["field"] for item in missing_release_fields(meta, [row.channel_code])}
        if any(field in gaps for field in asked):
            continue
        blob["info_status"] = "returned"
        blob["returned_at"] = datetime.utcnow().isoformat()
        row.attempt_meta = blob
        if row.status == "needs_creator":
            row.status = "ops_queue"
        returned += 1
    return returned


def list_label_accounts(db: Session) -> list[dict]:
    from app.models.schemas import DistributorAccount

    rows = (
        db.query(DistributorAccount)
        .filter(DistributorAccount.ownership == "platform")
        .order_by(DistributorAccount.provider.asc())
        .all()
    )
    return [
        {
            "id": str(row.id),
            "provider": row.provider,
            "display_name": row.display_name,
            "enabled": bool(row.enabled),
            "has_token": bool(row.official_token),
        }
        for row in rows
    ]
