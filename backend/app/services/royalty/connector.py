"""Authorized connector ingest: account-holder session data only, no stored passwords."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import (
    ConnectorClaim,
    ConnectorIngestBatch,
    ConnectorIngestToken,
    DistributionDelivery,
    PlatformMetricSnapshot,
    Release,
    ReleaseMetadata,
    User,
    Work,
)
from app.services.auth import decode_token

TOKEN_PREFIX = "vsc_"
MIN_EXTENSION_VERSION = "0.14.0"


def version_less(left: str | None, right: str | None) -> bool:
    def parts(raw: str | None) -> list[int]:
        out = []
        for chunk in str(raw or "0").split("."):
            digits = "".join(ch for ch in chunk if ch.isdigit())
            out.append(int(digits or 0))
        return out or [0]

    a, b = parts(left), parts(right)
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a < b
CONNECTOR_SCHEMA = {
    "type": "object",
    "required": ["rows"],
    "properties": {
        "channel_code": {"type": "string"},
        "period_key": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["channel_code", "period_key"],
                "properties": {
                    "channel_code": {"type": "string"},
                    "period_key": {"type": "string"},
                    "external_track_id": {"type": "string"},
                    "work_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "title": {"type": "string"},
                    "isrc": {"type": "string"},
                    "streams": {"type": "integer"},
                    "saves": {"type": "integer"},
                    "comments": {"type": "integer"},
                    "revenue_minor": {"type": "integer"},
                    "currency": {"type": "string"},
                    "confidence": {"type": "number"},
                    "raw": {"type": "object"},
                },
            },
        },
    },
}


@dataclass
class ConnectorActor:
    user: User
    role: str
    via: str


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_ingest_token(db: Session, user: User, *, days: int = 30) -> dict:
    now = datetime.utcnow()
    for old in (
        db.query(ConnectorIngestToken)
        .filter(ConnectorIngestToken.user_id == user.id, ConnectorIngestToken.revoked_at.is_(None))
        .all()
    ):
        old.revoked_at = now
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    role = "ops" if getattr(user, "is_admin", False) else "user"
    row = ConnectorIngestToken(
        user_id=user.id,
        token_hash=_hash_token(raw),
        role=role,
        expires_at=now + timedelta(days=days),
    )
    db.add(row)
    db.commit()
    from app.config import settings
    from app.services.royalty.settlement import current_period

    api_base = (settings.api_public_url or "").rstrip("/") or "http://localhost:8000/api/v1"
    period_key, _, _ = current_period(db)
    pair = {
        "vibePair": 1,
        "apiBase": api_base,
        "token": raw,
        "role": role,
        "period": period_key,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "minVersion": MIN_EXTENSION_VERSION,
        "user_id": str(user.id),
        "webBase": (settings.frontend_base_url or "").rstrip("/"),
    }
    return {
        "token": raw,
        "role": role,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "period_key": period_key,
        "min_extension_version": MIN_EXTENSION_VERSION,
        "prefix": TOKEN_PREFIX,
        "api_base": api_base,
        "web_base": pair["webBase"],
        "pair": pair,
        "pair_text": "BITTUNE_PAIR:" + __import__("json").dumps(pair, separators=(",", ":")),
    }


def revoke_connector_tokens(db: Session, user: User) -> dict:
    now = datetime.utcnow()
    rows = (
        db.query(ConnectorIngestToken)
        .filter(ConnectorIngestToken.user_id == user.id, ConnectorIngestToken.revoked_at.is_(None))
        .all()
    )
    for row in rows:
        row.revoked_at = now
    db.commit()
    return {"ok": True, "revoked": len(rows)}


def resolve_connector_actor(db: Session, token: str) -> ConnectorActor | None:
    if not token:
        return None
    if token.startswith(TOKEN_PREFIX):
        row = (
            db.query(ConnectorIngestToken)
            .filter(
                ConnectorIngestToken.token_hash == _hash_token(token),
                ConnectorIngestToken.revoked_at.is_(None),
            )
            .first()
        )
        if not row:
            return None
        if row.expires_at and row.expires_at < datetime.utcnow():
            return None
        user = db.query(User).filter(User.id == row.user_id).first()
        if not user or not user.is_active:
            return None
        row.last_used_at = datetime.utcnow()
        db.commit()
        role = "ops" if row.role == "ops" and getattr(user, "is_admin", False) else "user"
        return ConnectorActor(user=user, role=role, via="token")
    user_id = decode_token(token)
    if not user_id:
        return None
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        return None
    return ConnectorActor(user=user, role="ops" if getattr(user, "is_admin", False) else "user", via="jwt")


def _as_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def match_row(db: Session, row: dict, *, default_user_id: uuid.UUID | None) -> tuple[Work | None, Release | None, uuid.UUID | None]:
    work = None
    release = None
    owner_id = _as_uuid(row.get("user_id")) or default_user_id
    work_id = _as_uuid(row.get("work_id"))
    if work_id:
        work = db.query(Work).filter(Work.id == work_id).first()
    external = (row.get("external_track_id") or "").strip()
    if not work and external:
        delivery = (
            db.query(DistributionDelivery)
            .filter(DistributionDelivery.external_id == external)
            .first()
        )
        if delivery:
            work = db.query(Work).filter(Work.id == delivery.work_id).first()
            release = db.query(Release).filter(Release.id == delivery.release_id).first()
    isrc = (row.get("isrc") or "").replace("-", "").replace(" ", "")
    raw_isrc = row.get("isrc")
    if not work and raw_isrc:
        work = db.query(Work).filter(Work.isrc.in_([raw_isrc, isrc])).first()
        if not work:
            meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.isrc.in_([raw_isrc, isrc])).first()
            if meta:
                release = db.query(Release).filter(Release.id == meta.release_id).first()
                if release:
                    work = db.query(Work).filter(Work.id == release.work_id).first()
    title = (row.get("title") or "").strip()
    if not work and title and owner_id:
        work = (
            db.query(Work)
            .filter(Work.owner_id == owner_id, Work.title.ilike(title))
            .order_by(Work.created_at.desc())
            .first()
        )
    if work and not release:
        release = (
            db.query(Release)
            .filter(Release.work_id == work.id)
            .order_by(Release.created_at.desc())
            .first()
        )
    if work:
        owner_id = work.owner_id
    return work, release, owner_id


def _serialize_claim(row: ConnectorClaim) -> dict:
    return {
        "id": str(row.id),
        "batch_id": str(row.batch_id),
        "user_id": str(row.user_id) if row.user_id else None,
        "work_id": str(row.work_id) if row.work_id else None,
        "release_id": str(row.release_id) if row.release_id else None,
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "channel_code": row.channel_code,
        "period_key": row.period_key,
        "external_track_id": row.external_track_id,
        "title": row.title,
        "isrc": row.isrc,
        "streams": row.streams or 0,
        "revenue_minor": row.revenue_minor or 0,
        "currency": row.currency or "CNY",
        "confidence": row.confidence or 0,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_batch(row: ConnectorIngestBatch) -> dict:
    return {
        "id": str(row.id),
        "source": row.source,
        "status": row.status,
        "row_count": row.row_count or 0,
        "matched_count": row.matched_count or 0,
        "unmatched_count": row.unmatched_count or 0,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
    }


def ingest_connector_rows(db: Session, actor: ConnectorActor, payload: dict) -> dict:
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows required")
    source = "ops_connector" if actor.role == "ops" else "user_connector"
    default_channel = payload.get("channel_code")
    default_period = payload.get("period_key") or datetime.utcnow().strftime("%Y-%m")
    batch = ConnectorIngestBatch(uploaded_by=actor.user.id, source=source, status="pending_review")
    db.add(batch)
    db.flush()
    matched = 0
    unmatched = 0
    stored = 0
    default_owner = None if actor.role == "ops" else actor.user.id
    for raw in rows[:500]:
        if not isinstance(raw, dict):
            continue
        channel = (raw.get("channel_code") or default_channel or "").strip()
        period = (raw.get("period_key") or default_period or "")[:32]
        if not channel:
            continue
        work, release, owner_id = match_row(db, raw, default_user_id=default_owner)
        if actor.role == "user" and work and work.owner_id != actor.user.id:
            work = None
            release = None
            owner_id = actor.user.id
        confidence = float(raw.get("confidence") or 0.5)
        streams = int(raw.get("streams") or 0)
        revenue = int(raw.get("revenue_minor") or 0)
        currency = (raw.get("currency") or "CNY").upper()
        claim = ConnectorClaim(
            batch_id=batch.id,
            user_id=owner_id,
            work_id=work.id if work else None,
            release_id=release.id if release else None,
            channel_code=channel,
            period_key=period,
            external_track_id=(raw.get("external_track_id") or None),
            title=raw.get("title"),
            isrc=raw.get("isrc"),
            streams=streams,
            saves=int(raw.get("saves") or 0),
            comments=int(raw.get("comments") or 0),
            revenue_minor=revenue,
            currency=currency,
            confidence=confidence,
            raw=raw.get("raw") or raw,
            status="matched" if work and owner_id else "unclaimed",
        )
        db.add(claim)
        db.flush()
        if work and owner_id:
            matched += 1
        else:
            unmatched += 1
        stored += 1
    batch.row_count = stored
    batch.matched_count = matched
    batch.unmatched_count = unmatched
    db.commit()
    return {
        "batch": _serialize_batch(batch),
        "source": source,
        "usable_for_settlement": False,
        "matched": matched,
        "unclaimed": unmatched,
        "auto_confirmed": False,
        "note": "connector_claims_only_use_seats_harvest",
    }


def confirm_batch(db: Session, batch_id: str) -> dict:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch id") from exc
    batch = db.query(ConnectorIngestBatch).filter(ConnectorIngestBatch.id == bid).first()
    if not batch:
        raise HTTPException(404, "Batch not found")
    if batch.source != "ops_connector":
        raise HTTPException(400, "Only ops_connector batches can be confirmed for display review")
    claims = db.query(ConnectorClaim).filter(ConnectorClaim.batch_id == batch.id, ConnectorClaim.status == "matched").all()
    updated = 0
    for claim in claims:
        snap = None
        if claim.snapshot_id:
            snap = db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.id == claim.snapshot_id).first()
        if not snap and claim.work_id and claim.user_id:
            snap = (
                db.query(PlatformMetricSnapshot)
                .filter(
                    PlatformMetricSnapshot.work_id == claim.work_id,
                    PlatformMetricSnapshot.user_id == claim.user_id,
                    PlatformMetricSnapshot.channel_code == claim.channel_code,
                    PlatformMetricSnapshot.period_key == claim.period_key,
                    PlatformMetricSnapshot.source == batch.source,
                )
                .first()
            )
        if not snap:
            continue
        claim.snapshot_id = snap.id
        snap.usable_for_settlement = True
        raw = dict(snap.raw or {})
        raw["ops_reviewed"] = True
        snap.raw = raw
        updated += 1
    batch.status = "confirmed"
    batch.confirmed_at = datetime.utcnow()
    db.commit()
    return {"batch": _serialize_batch(batch), "confirmed_snapshots": updated, "usable_for_settlement": True}


def match_claim(db: Session, claim_id: str, work_id: str, actor: User, *, admin: bool = False) -> dict:
    try:
        cid = uuid.UUID(claim_id)
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid id") from exc
    claim = db.query(ConnectorClaim).filter(ConnectorClaim.id == cid).first()
    if not claim:
        raise HTTPException(404, "Claim not found")
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(404, "Work not found")
    if not admin and work.owner_id != actor.id:
        raise HTTPException(403, "Work not owned")
    from app.services.royalty.settlement import prefer_label_release

    release = prefer_label_release(db, work.id)
    batch = db.query(ConnectorIngestBatch).filter(ConnectorIngestBatch.id == claim.batch_id).first()
    claim.work_id = work.id
    claim.release_id = release.id if release else None
    claim.user_id = work.owner_id
    claim.status = "matched"
    claim.snapshot_id = None
    if batch:
        batch.matched_count = (batch.matched_count or 0) + 1
        batch.unmatched_count = max(0, (batch.unmatched_count or 0) - 1)
    db.commit()
    return _serialize_claim(claim)


def list_batches(db: Session, *, source: str | None = None) -> list[dict]:
    q = db.query(ConnectorIngestBatch).order_by(ConnectorIngestBatch.created_at.desc())
    if source:
        q = q.filter(ConnectorIngestBatch.source == source)
    return [_serialize_batch(r) for r in q.limit(100).all()]


def list_claims(db: Session, *, status: str = "unclaimed", user_id: uuid.UUID | None = None) -> list[dict]:
    q = db.query(ConnectorClaim).order_by(ConnectorClaim.created_at.desc())
    if status:
        q = q.filter(ConnectorClaim.status == status)
    if user_id:
        q = q.filter(ConnectorClaim.user_id == user_id)
    return [_serialize_claim(r) for r in q.limit(200).all()]


def unclaimed_count(db: Session, user_id: uuid.UUID | None = None) -> int:
    q = db.query(ConnectorClaim).filter(ConnectorClaim.status == "unclaimed")
    if user_id:
        q = q.filter(ConnectorClaim.user_id == user_id)
    return q.count()
