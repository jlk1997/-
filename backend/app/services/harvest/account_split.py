"""Split account-total dashboard rows by play share on the harvesting seat."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, DistributionDelivery, PlatformMetricSnapshot, Release, Work

ACCOUNT_TOTAL_TITLES = {
    "account total",
    "账户合计",
    "账户总收益",
    "合计",
    "total",
    "totals",
    "汇总",
}


def is_account_total_row(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("account_total") or row.get("is_account_total"):
        return True
    title = (row.get("title") or "").strip().lower()
    if title in ACCOUNT_TOTAL_TITLES:
        return True
    if row.get("work_id") or row.get("isrc") or row.get("track_code") or row.get("external_track_id") or row.get("content_hash"):
        return False
    if title:
        return False
    return int(row.get("revenue_minor") or 0) > 0 or int(row.get("streams") or 0) > 0


def works_on_seat(db: Session, seat: CreatorSeat, channel: str) -> list[Work]:
    explicit: dict = {}
    inferred: dict = {}
    for work, delivery in (
        db.query(Work, DistributionDelivery)
        .join(DistributionDelivery, DistributionDelivery.work_id == Work.id)
        .filter(DistributionDelivery.channel_code == channel)
        .filter(
            DistributionDelivery.status.in_(
                ("live", "queued", "delivering", "session_wait", "session_running", "submitting")
            )
        )
        .all()
    ):
        if seat.ownership == "user" and work.owner_id != seat.user_id:
            continue
        meta = dict(delivery.attempt_meta or {})
        stamped = str(meta.get("seat_id") or "")
        if stamped == str(seat.id):
            explicit[work.id] = work
            continue
        if stamped:
            continue
        if seat.ownership == "platform":
            release = db.query(Release).filter(Release.id == delivery.release_id).first()
            if not release or release.mode != "label":
                continue
            from app.services.seats.service import pick_platform_seat

            picked = pick_platform_seat(db, channel, work.id)
            if picked and picked.id == seat.id:
                inferred[work.id] = work
            continue
        inferred[work.id] = work
    return list(explicit.values() or inferred.values())


def _play_weight(db: Session, work: Work, channel: str, period: str) -> int:
    snaps = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.work_id == work.id,
            PlatformMetricSnapshot.channel_code == channel,
            PlatformMetricSnapshot.period_key == period,
        )
        .all()
    )
    streams = sum(int(row.streams or 0) for row in snaps)
    return max(streams, 1)


def split_account_total(
    db: Session,
    seat: CreatorSeat,
    *,
    period_key: str,
    channel: str,
    total_revenue: int,
    total_streams: int,
    currency: str = "CNY",
) -> list[dict]:
    works = works_on_seat(db, seat, channel)
    if not works:
        return []
    weights = [(work, _play_weight(db, work, channel, period_key)) for work in works]
    total_w = sum(weight for _, weight in weights) or len(weights)
    leftover_rev = int(total_revenue or 0)
    leftover_st = int(total_streams or 0)
    rows: list[dict] = []
    for index, (work, weight) in enumerate(weights):
        if index == len(weights) - 1:
            rev, streams = leftover_rev, leftover_st
        else:
            rev = int(int(total_revenue or 0) * weight / total_w)
            streams = int(int(total_streams or 0) * weight / total_w)
            leftover_rev -= rev
            leftover_st -= streams
        rows.append(
            {
                "work_id": str(work.id),
                "channel_code": channel,
                "period_key": period_key,
                "title": work.title,
                "isrc": work.isrc,
                "streams": streams,
                "revenue_minor": rev,
                "currency": currency,
                "raw": {"account_split": True, "weight": weight, "account_total": True},
            }
        )
    return rows


def expand_account_total_rows(db: Session, rows: list[dict], seat: CreatorSeat | None) -> tuple[list[dict], list[dict]]:
    """Return (expanded_or_passthrough, leftover_account_totals_without_works)."""
    if not seat:
        return list(rows), []
    out: list[dict] = []
    leftover: list[dict] = []
    for raw in rows:
        if not is_account_total_row(raw):
            out.append(raw)
            continue
        channel = (raw.get("channel_code") or seat.channel_code or "").strip()
        period = (raw.get("period_key") or "")[:32]
        parts = split_account_total(
            db,
            seat,
            period_key=period,
            channel=channel,
            total_revenue=int(raw.get("revenue_minor") or 0),
            total_streams=int(raw.get("streams") or 0),
            currency=(raw.get("currency") or "CNY").upper(),
        )
        if parts:
            out.extend(parts)
        else:
            leftover.append(raw)
    return out, leftover
