"""Persist unmatched harvest rows so ops can claim them without touching wallets."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, HarvestUnmatched, User, Work
from app.services.royalty.ingest import _norm_isrc, _norm_title


def row_fingerprint(row: dict, *, channel: str, period: str) -> str:
    key = "|".join(
        [
            (channel or "").strip().lower(),
            (period or "").strip(),
            _norm_title(row.get("title")),
            _norm_isrc(row.get("isrc") or row.get("track_code")),
            str(row.get("external_track_id") or "").strip(),
            str(row.get("content_hash") or "").strip().lower(),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def serialize_unmatched(row: HarvestUnmatched) -> dict:
    return {
        "id": str(row.id),
        "seat_id": str(row.seat_id) if row.seat_id else None,
        "channel_code": row.channel_code,
        "period_key": row.period_key,
        "title": row.title,
        "isrc": row.isrc,
        "streams": row.streams or 0,
        "revenue_minor": row.revenue_minor or 0,
        "currency": row.currency or "CNY",
        "fingerprint": row.fingerprint,
        "status": row.status,
        "matched_work_id": str(row.matched_work_id) if row.matched_work_id else None,
        "raw": row.raw or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def persist_unmatched(
    db: Session,
    rows: list[dict],
    *,
    seat: CreatorSeat | None = None,
) -> list[dict]:
    stored: list[HarvestUnmatched] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        channel = (raw.get("channel_code") or (seat.channel_code if seat else "") or "").strip()
        period = (raw.get("period_key") or "")[:32]
        if not channel or not period:
            continue
        fp = row_fingerprint(raw, channel=channel, period=period)
        existing = (
            db.query(HarvestUnmatched)
            .filter(HarvestUnmatched.fingerprint == fp, HarvestUnmatched.status == "unclaimed")
            .first()
        )
        if existing:
            existing.streams = int(raw.get("streams") or 0)
            existing.revenue_minor = int(raw.get("revenue_minor") or 0)
            existing.title = raw.get("title") or existing.title
            existing.isrc = _norm_isrc(raw.get("isrc") or raw.get("track_code")) or existing.isrc
            existing.updated_at = datetime.utcnow()
            stored.append(existing)
            continue
        rec = HarvestUnmatched(
            seat_id=seat.id if seat else None,
            channel_code=channel,
            period_key=period,
            title=raw.get("title"),
            isrc=_norm_isrc(raw.get("isrc") or raw.get("track_code")) or None,
            streams=int(raw.get("streams") or 0),
            revenue_minor=int(raw.get("revenue_minor") or 0),
            currency=(raw.get("currency") or "CNY").upper(),
            fingerprint=fp,
            status="unclaimed",
            raw=dict(raw),
        )
        db.add(rec)
        stored.append(rec)
    db.flush()
    return [serialize_unmatched(row) for row in stored]


def unmatched_scope_for_user(db: Session, user: User) -> dict:
    user_ids = [
        row.id
        for row in db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "user", CreatorSeat.user_id == user.id)
        .all()
    ]
    platform_ids = [
        row.id
        for row in db.query(CreatorSeat).filter(CreatorSeat.ownership == "platform").all()
    ]
    return {"user": user_ids, "platform": platform_ids}


def _user_match_keys(db: Session, user: User) -> tuple[set[str], set[str]]:
    from app.models.schemas import TrackCodeAlias
    from app.services.distribution.track_code import extract_track_code, mint_track_code

    works = db.query(Work).filter(Work.owner_id == user.id).all()
    titles = {_norm_title(work.title) for work in works if work.title}
    codes: set[str] = set()
    for work in works:
        codes.add(mint_track_code(work.id))
        extracted = extract_track_code(work.title or "")
        if extracted:
            codes.add(extracted)
    if works:
        for alias in db.query(TrackCodeAlias).filter(TrackCodeAlias.work_id.in_([work.id for work in works])).all():
            if getattr(alias, "code", None):
                codes.add(str(alias.code).upper())
    return titles, {code.upper() for code in codes if code}


def _unmatched_belongs(row: HarvestUnmatched, keys: tuple[set[str], set[str]]) -> bool:
    from app.services.distribution.track_code import extract_track_code

    titles, codes = keys
    if _norm_title(row.title) in titles:
        return True
    blob = f"{row.title or ''} {row.isrc or ''}"
    code = extract_track_code(blob)
    if code and code.upper() in codes:
        return True
    isrc = _norm_isrc(row.isrc)
    return bool(isrc and isrc.upper() in codes)


def _visible_unmatched(db: Session, user: User, rows: list[HarvestUnmatched]) -> list[HarvestUnmatched]:
    scope = unmatched_scope_for_user(db, user)
    user_ids = set(scope["user"])
    return [row for row in rows if row.seat_id in user_ids]


def list_unmatched(
    db: Session,
    user: User | None = None,
    *,
    admin: bool = False,
    status: str = "unclaimed",
    limit: int = 80,
) -> list[dict]:
    cap = max(1, min(int(limit or 80), 200))
    q = db.query(HarvestUnmatched)
    if status:
        q = q.filter(HarvestUnmatched.status == status)
    rows = q.order_by(HarvestUnmatched.created_at.desc()).limit(200 if user and not admin else cap).all()
    if user and not admin and not getattr(user, "is_admin", False):
        rows = _visible_unmatched(db, user, rows)[:cap]
    else:
        rows = rows[:cap]
    return [serialize_unmatched(row) for row in rows]


def count_unmatched(db: Session, user: User | None = None, *, admin: bool = False) -> int:
    q = db.query(HarvestUnmatched).filter(HarvestUnmatched.status == "unclaimed")
    if user and not admin and not getattr(user, "is_admin", False):
        rows = q.order_by(HarvestUnmatched.created_at.desc()).limit(200).all()
        return len(_visible_unmatched(db, user, rows))
    return int(q.count() or 0)


def rematch_unmatched_harvest(db: Session, *, limit: int = 80) -> dict:
    """Attach unclaimed harvest rows only when ISRC uniquely matches a work. Never invent a match."""
    from app.services.royalty.ingest import resolve_work_match

    cap = min(max(int(limit or 80), 1), 200)
    rows = (
        db.query(HarvestUnmatched)
        .filter(HarvestUnmatched.status == "unclaimed")
        .order_by(HarvestUnmatched.created_at.desc())
        .with_for_update()
        .limit(cap)
        .all()
    )
    matched = 0
    for rec in rows:
        raw = dict(rec.raw or {})
        raw.setdefault("title", rec.title)
        raw.setdefault("isrc", rec.isrc)
        raw.setdefault("channel_code", rec.channel_code)
        if not raw.get("isrc"):
            continue
        seat = db.query(CreatorSeat).filter(CreatorSeat.id == rec.seat_id).first() if rec.seat_id else None
        owner_id = seat.user_id if seat and seat.ownership == "user" else None
        work, _release, kind = resolve_work_match(db, raw, owner_id)
        if not work or kind != "isrc":
            continue
        owner = db.query(User).filter(User.id == work.owner_id).first()
        if not owner:
            continue
        try:
            attach_unmatched(db, owner, str(rec.id), str(work.id), admin=True)
            matched += 1
        except Exception:
            continue
    return {"checked": len(rows), "matched": matched}


def attach_unmatched(db: Session, user: User, unmatched_id: str, work_id: str, *, admin: bool = False) -> dict:
    try:
        uid = uuid.UUID(str(unmatched_id))
        wid = uuid.UUID(str(work_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid id") from exc
    rec = (
        db.query(HarvestUnmatched)
        .filter(HarvestUnmatched.id == uid)
        .with_for_update()
        .first()
    )
    if not rec:
        raise HTTPException(404, "Unmatched harvest row not found")
    if rec.status == "matched":
        return {"id": str(rec.id), "status": "matched", "reason": "already_matched"}
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(404, "Work not found")
    if not admin and not getattr(user, "is_admin", False) and work.owner_id != user.id:
        raise HTTPException(403, "Work not owned")
    seat = db.query(CreatorSeat).filter(CreatorSeat.id == rec.seat_id).first() if rec.seat_id else None
    if not admin and not getattr(user, "is_admin", False):
        if not seat or seat.ownership != "user" or seat.user_id != user.id:
            raise HTTPException(403, "Unmatched row is ops-only")
    raw = dict(rec.raw or {})
    raw.update(
        {
            "work_id": str(work.id),
            "channel_code": rec.channel_code,
            "period_key": rec.period_key,
            "title": rec.title or raw.get("title"),
            "isrc": rec.isrc or raw.get("isrc"),
            "streams": rec.streams,
            "revenue_minor": rec.revenue_minor,
            "currency": rec.currency,
        }
    )
    from app.services.harvest.ingest import ingest_harvest_rows

    result = ingest_harvest_rows(db, [raw], seat=seat, actor=user, settle=True)
    rec.status = "matched"
    rec.matched_work_id = work.id
    rec.updated_at = datetime.utcnow()
    db.commit()
    return {"id": str(rec.id), "status": "matched", "ingest": result}
