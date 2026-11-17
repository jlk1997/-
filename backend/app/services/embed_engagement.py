"""Certified embed completes. Anonymous plays stay display-only."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import EmbedListenEvent, User, Work
from app.services.listen_engagement import MIN_LISTEN_RATIO

EMBED_CHANNEL = "embed_player"
EMBED_SOURCE = "first_party_embed"
EMBED_DISPLAY_SOURCE = "first_party_embed_uncertified"
EMBED_PAYOUT_MINOR = 1


def visitor_key(*, user: User | None, visitor: str | None, host: str | None) -> str:
    if user:
        return f"user:{user.id}"
    raw = (visitor or "").strip() or (host or "anon")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def is_certified(user: User | None) -> bool:
    return bool(user)


def record_embed_complete(
    db: Session,
    *,
    work_id: str,
    listen_ratio: float,
    user: User | None,
    visitor: str | None = None,
    host: str | None = None,
) -> dict:
    if listen_ratio < MIN_LISTEN_RATIO:
        raise HTTPException(400, "Complete requires 80% listened")
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(404, "Work not found")
    key = visitor_key(user=user, visitor=visitor, host=host)
    today = date.today()
    existing = (
        db.query(EmbedListenEvent)
        .filter(
            EmbedListenEvent.work_id == work.id,
            EmbedListenEvent.visitor_key == key,
            EmbedListenEvent.entry_date == today,
        )
        .first()
    )
    if existing:
        return {
            "duplicate": True,
            "certified": existing.certified,
            "usable_for_settlement": existing.usable_for_settlement,
        }
    certified = is_certified(user) and (not user or user.id != work.owner_id)
    usable = certified
    row = EmbedListenEvent(
        work_id=work.id,
        visitor_key=key,
        entry_date=today,
        listen_ratio=listen_ratio,
        certified=certified,
        usable_for_settlement=usable,
    )
    db.add(row)
    raw = {"listen_ratio": listen_ratio, "rule": "min_80_complete", "certified": certified}
    if usable:
        from app.services.royalty.settlement import prefer_label_release
        from app.services.royalty.snapshots import increment_settlement_snapshot

        release = prefer_label_release(db, work.id)
        increment_settlement_snapshot(
            db,
            user_id=work.owner_id,
            channel_code=EMBED_CHANNEL,
            period_key=today.strftime("%Y-%m"),
            source=EMBED_SOURCE,
            streams=1,
            revenue_minor=EMBED_PAYOUT_MINOR,
            currency="CNY",
            work_id=work.id,
            release_id=release.id if release else None,
            raw=raw,
        )
    else:
        from app.services.royalty.snapshots import increment_display_snapshot

        increment_display_snapshot(
            db,
            user_id=work.owner_id,
            channel_code=EMBED_CHANNEL,
            period_key=today.strftime("%Y-%m"),
            source=EMBED_DISPLAY_SOURCE,
            streams=1,
            work_id=work.id,
            raw={**raw, "self_listen": bool(user and user.id == work.owner_id)},
        )
    db.commit()
    return {"duplicate": False, "certified": certified, "usable_for_settlement": usable}
