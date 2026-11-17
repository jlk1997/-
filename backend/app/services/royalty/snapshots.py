from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.schemas import PlatformMetricSnapshot
from app.services.distribution.catalog import CONNECTOR_SOURCES, HARVEST_SOURCES, OFFICIAL_SOURCES, SETTLEMENT_SOURCES


def demote_connector_snapshots(
    db: Session,
    *,
    user_id: uuid.UUID,
    channel_code: str,
    period_key: str,
    work_id: uuid.UUID | None,
) -> int:
    q = db.query(PlatformMetricSnapshot).filter(
        PlatformMetricSnapshot.user_id == user_id,
        PlatformMetricSnapshot.channel_code == channel_code,
        PlatformMetricSnapshot.period_key == period_key,
        PlatformMetricSnapshot.source.in_(tuple(CONNECTOR_SOURCES)),
        PlatformMetricSnapshot.settled.is_(False),
    )
    if work_id:
        q = q.filter(PlatformMetricSnapshot.work_id == work_id)
    else:
        q = q.filter(PlatformMetricSnapshot.work_id.is_(None))
    updated = 0
    for row in q.all():
        if row.usable_for_settlement:
            row.usable_for_settlement = False
            raw = dict(row.raw or {})
            raw["overridden_by"] = "official_source"
            row.raw = raw
            updated += 1
    return updated


def upsert_metric_snapshot(
    db: Session,
    *,
    user_id: uuid.UUID,
    channel_code: str,
    period_key: str,
    source: str,
    streams: int = 0,
    saves: int = 0,
    comments: int = 0,
    revenue_minor: int = 0,
    currency: str = "CNY",
    work_id: uuid.UUID | None = None,
    release_id: uuid.UUID | None = None,
    distributor_code: str | None = None,
    raw: dict | None = None,
    usable: bool | None = None,
) -> bool:
    if not channel_code:
        return False
    if usable is None:
        usable = source in SETTLEMENT_SOURCES or source in HARVEST_SOURCES
    elif source in CONNECTOR_SOURCES and usable is False:
        usable = False
    q = db.query(PlatformMetricSnapshot).filter(
        PlatformMetricSnapshot.channel_code == channel_code,
        PlatformMetricSnapshot.period_key == period_key,
        PlatformMetricSnapshot.source == source,
        PlatformMetricSnapshot.user_id == user_id,
    )
    if work_id:
        q = q.filter(PlatformMetricSnapshot.work_id == work_id)
    else:
        q = q.filter(PlatformMetricSnapshot.work_id.is_(None))
    existing = q.first()
    if existing:
        existing.streams = streams
        existing.saves = saves
        existing.comments = comments
        existing.revenue_minor = revenue_minor
        existing.currency = currency
        existing.usable_for_settlement = usable
        existing.release_id = release_id or existing.release_id
        existing.distributor_code = distributor_code or existing.distributor_code
        existing.raw = raw or existing.raw
        if usable and source in OFFICIAL_SOURCES:
            demote_connector_snapshots(
                db,
                user_id=user_id,
                channel_code=channel_code,
                period_key=period_key,
                work_id=work_id,
            )
        return True
    db.add(
        PlatformMetricSnapshot(
            work_id=work_id,
            release_id=release_id,
            user_id=user_id,
            channel_code=channel_code,
            distributor_code=distributor_code,
            source=source,
            usable_for_settlement=usable,
            period_key=period_key,
            streams=streams,
            saves=saves,
            comments=comments,
            revenue_minor=revenue_minor,
            currency=currency,
            raw=raw or {},
        )
    )
    if usable and source in OFFICIAL_SOURCES:
        demote_connector_snapshots(
            db,
            user_id=user_id,
            channel_code=channel_code,
            period_key=period_key,
            work_id=work_id,
        )
    return True


def increment_display_snapshot(
    db: Session,
    *,
    user_id: uuid.UUID,
    channel_code: str,
    period_key: str,
    source: str,
    streams: int = 1,
    work_id: uuid.UUID | None = None,
    release_id: uuid.UUID | None = None,
    raw: dict | None = None,
) -> PlatformMetricSnapshot | None:
    """Add display-only streams. Never marks the row usable for settlement."""
    if not channel_code or streams <= 0:
        return None
    q = db.query(PlatformMetricSnapshot).filter(
        PlatformMetricSnapshot.channel_code == channel_code,
        PlatformMetricSnapshot.period_key == period_key,
        PlatformMetricSnapshot.source == source,
        PlatformMetricSnapshot.user_id == user_id,
    )
    if work_id:
        q = q.filter(PlatformMetricSnapshot.work_id == work_id)
    else:
        q = q.filter(PlatformMetricSnapshot.work_id.is_(None))
    existing = q.first()
    extra = dict(raw or {})
    extra["display_only"] = True
    if existing:
        existing.streams = (existing.streams or 0) + streams
        existing.usable_for_settlement = False
        existing.revenue_minor = existing.revenue_minor or 0
        existing.release_id = release_id or existing.release_id
        existing.raw = {**(existing.raw or {}), **extra}
        return existing
    row = PlatformMetricSnapshot(
        work_id=work_id,
        release_id=release_id,
        user_id=user_id,
        channel_code=channel_code,
        source=source,
        usable_for_settlement=False,
        period_key=period_key,
        streams=streams,
        revenue_minor=0,
        raw=extra,
    )
    db.add(row)
    return row


def increment_settlement_snapshot(
    db: Session,
    *,
    user_id: uuid.UUID,
    channel_code: str,
    period_key: str,
    source: str,
    streams: int = 1,
    revenue_minor: int = 0,
    currency: str = "CNY",
    work_id: uuid.UUID | None = None,
    release_id: uuid.UUID | None = None,
    raw: dict | None = None,
) -> PlatformMetricSnapshot | None:
    """Increment a first-party settlable snapshot (valid completes only)."""
    if source in CONNECTOR_SOURCES:
        return None
    if not channel_code or streams <= 0:
        return None
    q = db.query(PlatformMetricSnapshot).filter(
        PlatformMetricSnapshot.channel_code == channel_code,
        PlatformMetricSnapshot.period_key == period_key,
        PlatformMetricSnapshot.source == source,
        PlatformMetricSnapshot.user_id == user_id,
    )
    if work_id:
        q = q.filter(PlatformMetricSnapshot.work_id == work_id)
    else:
        q = q.filter(PlatformMetricSnapshot.work_id.is_(None))
    existing = q.first()
    extra = dict(raw or {})
    if existing:
        existing.streams = (existing.streams or 0) + streams
        existing.revenue_minor = (existing.revenue_minor or 0) + int(revenue_minor or 0)
        existing.usable_for_settlement = True
        existing.currency = currency or existing.currency or "CNY"
        existing.release_id = release_id or existing.release_id
        existing.raw = {**(existing.raw or {}), **extra}
        return existing
    row = PlatformMetricSnapshot(
        work_id=work_id,
        release_id=release_id,
        user_id=user_id,
        channel_code=channel_code,
        source=source,
        usable_for_settlement=True,
        period_key=period_key,
        streams=streams,
        revenue_minor=int(revenue_minor or 0),
        currency=currency,
        raw=extra,
    )
    db.add(row)
    return row
