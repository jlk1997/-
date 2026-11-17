"""Turn dashboard rows into settlement-grade snapshots and auto-confirm harvest batches."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, DistributionDelivery, PlatformMetricSnapshot, Release, User, Work
from app.services.distribution.catalog import DISPLAY_ONLY_SOURCES, HARVEST_SOURCES
from app.services.harvest.account_split import expand_account_total_rows
from app.services.harvest.playbooks import estimate_revenue_minor
from app.services.harvest.unmatched import persist_unmatched
from app.services.royalty.ingest import _norm_isrc, draft_settlements_for_periods
from app.services.royalty.snapshots import upsert_metric_snapshot


def _serialize_optional_seat(seat: CreatorSeat | None) -> dict | None:
    if not seat:
        return None
    from app.services.seats.service import serialize_seat

    return serialize_seat(seat)


def _row_confidence(raw: dict, *, seated: bool) -> float:
    explicit = raw.get("confidence")
    if explicit is None:
        explicit = (raw.get("raw") or {}).get("confidence")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    # DOM scrape is not high-confidence. Official CSV stamps 0.95 and may auto-confirm.
    return 0.75 if seated else 0.55


def harvest_source_for_seat(seat: CreatorSeat | None) -> str:
    if seat and seat.ownership == "platform":
        return "seat_harvest"
    if seat and seat.ownership == "user":
        return "seat_harvest"
    return "seat_harvest"


def match_harvest_row(db: Session, row: dict, *, default_user_id: uuid.UUID | None = None) -> tuple[Work | None, Release | None, str]:
    from app.services.distribution.track_code import extract_track_code, work_id_for_code
    from app.services.royalty.ingest import resolve_work_match
    from app.services.royalty.settlement import prefer_label_release

    raw_id = row.get("work_id")
    if raw_id:
        try:
            work = db.query(Work).filter(Work.id == uuid.UUID(str(raw_id))).first()
            if work:
                return work, prefer_label_release(db, work.id), "work_id"
        except (TypeError, ValueError):
            pass
    content_hash = (row.get("content_hash") or "").strip()
    if content_hash:
        work = db.query(Work).filter(Work.content_hash == content_hash).first()
        if work:
            return work, prefer_label_release(db, work.id), "content_hash"
    code = row.get("isrc") or row.get("track_code") or extract_track_code(row.get("title"))
    mapped = work_id_for_code(db, code)
    if mapped:
        work = db.query(Work).filter(Work.id == mapped).first()
        if work:
            return work, prefer_label_release(db, work.id), "isrc"
    external = (row.get("external_track_id") or "").strip()
    if external:
        delivery = db.query(DistributionDelivery).filter(DistributionDelivery.external_id == external).first()
        if delivery:
            work = db.query(Work).filter(Work.id == delivery.work_id).first()
            release = db.query(Release).filter(Release.id == delivery.release_id).first()
            if work:
                return work, release or prefer_label_release(db, work.id), "external_id"
    work, release, kind = resolve_work_match(db, row, default_user_id)
    return work, release, kind


def ingest_harvest_rows(
    db: Session,
    rows: list[dict],
    *,
    seat: CreatorSeat | None = None,
    actor: User | None = None,
    source: str | None = None,
    settle: bool = True,
) -> dict:
    if not rows:
        raise HTTPException(400, "rows required")
    if settle and seat and seat.ownership == "user":
        from app.services.seats.consent import require_scope, require_settle_license

        owner = actor
        if owner is None and seat.user_id:
            owner = db.query(User).filter(User.id == seat.user_id).first()
        if actor is not None:
            require_scope(seat, "settle")
        require_settle_license(db, owner, seat)
    if not settle and seat and seat.ownership == "user" and actor is not None:
        from app.services.seats.consent import require_scope

        require_scope(seat, "metrics")
    if seat and seat.ownership == "user" and actor is not None:
        from app.services.seats.consent import log_connector_consent, seat_scopes

        log_connector_consent(
            db,
            actor,
            channel_code=seat.channel_code,
            scopes=seat_scopes(seat),
            action="settle" if settle else "sync",
        )
    src = source or harvest_source_for_seat(seat)
    if not settle:
        src = source or "connector_sync"
    if settle and src not in HARVEST_SOURCES:
        src = "seat_harvest"
    if not settle and src not in DISPLAY_ONLY_SOURCES:
        src = "connector_sync"
    default_period = datetime.utcnow().strftime("%Y-%m")
    default_owner = seat.user_id if seat and seat.ownership == "user" else (actor.id if actor and not getattr(actor, "is_admin", False) else None)
    prepared = []
    for raw in rows[:500]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.setdefault("channel_code", (seat.channel_code if seat else "") or "")
        item.setdefault("period_key", default_period)
        prepared.append(item)
    expanded, leftover_totals = expand_account_total_rows(db, prepared, seat)
    stored = 0
    matched = 0
    unmatched: list[dict] = []
    periods: set[str] = set()
    adjustments: list[dict] = []
    from app.services.royalty.settlement import write_harvest_adjustment

    for raw in expanded:
        channel = (raw.get("channel_code") or (seat.channel_code if seat else "") or "").strip()
        period = (raw.get("period_key") or default_period)[:32]
        if not channel:
            continue
        work, release, match_kind = match_harvest_row(db, raw, default_user_id=default_owner)
        if seat and seat.ownership == "user" and work and work.owner_id != seat.user_id:
            work = None
            release = None
            match_kind = ""
        streams = int(raw.get("streams") or 0)
        reported_revenue = estimate_revenue_minor(channel, streams, int(raw.get("revenue_minor") or 0))
        currency = (raw.get("currency") or "CNY").upper()
        stored += 1
        from app.services.royalty.predict import historical_rate, normalize_geo, owner_share, predict_revenue

        geo = normalize_geo((raw.get("raw") or {}).get("geo") or raw.get("geo"))
        prediction = predict_revenue(
            channel,
            streams,
            currency=currency,
            geo=geo,
            share=owner_share(db, work.id if work else None, default_owner),
            history_rate=historical_rate(db, user_id=default_owner, channel_code=channel),
        )
        if settle and reported_revenue <= 0:
            unmatched.append(
                {
                    "title": raw.get("title"),
                    "isrc": raw.get("isrc"),
                    "channel_code": channel,
                    "period_key": period,
                    "streams": streams,
                    "revenue_minor": 0,
                    "content_hash": raw.get("content_hash"),
                    "external_track_id": raw.get("external_track_id"),
                    "currency": currency,
                    "reason": "no_revenue",
                }
            )
            continue
        if not work:
            unmatched.append(
                {
                    "title": raw.get("title"),
                    "isrc": raw.get("isrc"),
                    "channel_code": channel,
                    "period_key": period,
                    "streams": streams,
                    "revenue_minor": reported_revenue,
                    "content_hash": raw.get("content_hash"),
                    "external_track_id": raw.get("external_track_id"),
                    "currency": currency,
                }
            )
            if settle or not default_owner or streams <= 0:
                continue
            owner_id = default_owner
        else:
            owner_id = work.owner_id
        extra = {
            "match_kind": match_kind,
            "seat_id": str(seat.id) if seat else None,
            "ownership": seat.ownership if seat else None,
            "harvested": settle,
            "synced": not settle,
            "title": raw.get("title"),
            "isrc": _norm_isrc(raw.get("isrc") or raw.get("track_code") or (work.isrc if work else None)),
            "external_track_id": raw.get("external_track_id"),
            "content_hash": raw.get("content_hash") or (work.content_hash if work else None),
            "account_split": bool((raw.get("raw") or {}).get("account_split")),
            "confidence": _row_confidence(raw, seated=bool(seat)),
            "extractor_version": raw.get("extractor_version") or (raw.get("raw") or {}).get("extractor_version"),
            "reported_revenue_minor": reported_revenue,
            "prediction": prediction,
        }
        existing = (
            db.query(PlatformMetricSnapshot)
            .filter(
                PlatformMetricSnapshot.user_id == owner_id,
                PlatformMetricSnapshot.work_id == (work.id if work else None),
                PlatformMetricSnapshot.channel_code == channel,
                PlatformMetricSnapshot.period_key == period,
                PlatformMetricSnapshot.source == src,
            )
            .first()
        )
        already = int(dict(existing.raw or {}).get("settled_revenue_minor") or 0) if existing else 0
        snap_revenue = reported_revenue if settle else 0
        if settle and existing and already and reported_revenue > already and (existing.settled or already):
            existing.settled = False
            extra["settled_revenue_minor"] = already
            extra.setdefault("settled_commission_rate", dict(existing.raw or {}).get("settled_commission_rate"))
        upsert_metric_snapshot(
            db,
            user_id=owner_id,
            channel_code=channel,
            period_key=period,
            source=src,
            streams=streams,
            revenue_minor=snap_revenue,
            currency=currency,
            work_id=work.id if work else None,
            release_id=release.id if release else None,
            raw={**(existing.raw if existing else {}), **extra, **(raw.get("raw") or {})},
            usable=settle,
        )
        if work:
            matched += 1
        if settle and already and reported_revenue < already and work:
            snap = (
                db.query(PlatformMetricSnapshot)
                .filter(
                    PlatformMetricSnapshot.user_id == owner_id,
                    PlatformMetricSnapshot.work_id == work.id,
                    PlatformMetricSnapshot.channel_code == channel,
                    PlatformMetricSnapshot.period_key == period,
                    PlatformMetricSnapshot.source == src,
                )
                .first()
            )
            if snap:
                adjusted = write_harvest_adjustment(db, snap, reported_revenue)
                if adjusted:
                    adjustments.append(adjusted)
        elif settle and work:
            periods.add(period)
    for raw in leftover_totals:
        unmatched.append(
            {
                "title": raw.get("title") or "账户合计",
                "isrc": raw.get("isrc"),
                "channel_code": raw.get("channel_code") or (seat.channel_code if seat else ""),
                "period_key": (raw.get("period_key") or default_period)[:32],
                "streams": int(raw.get("streams") or 0),
                "revenue_minor": int(raw.get("revenue_minor") or 0),
                "account_total": True,
                "currency": (raw.get("currency") or "CNY").upper(),
            }
        )
        stored += 1
    persisted = persist_unmatched(db, unmatched, seat=seat) if unmatched else []
    db.commit()
    drafts = settle_harvest_periods(db, periods) if settle and periods else []
    return {
        "source": src,
        "stored": stored,
        "matched": matched,
        "unmatched": persisted or unmatched,
        "unmatched_count": len(persisted or unmatched),
        "usable_for_settlement": bool(settle),
        "periods": sorted(periods),
        "settlements": drafts,
        "adjustments": adjustments,
        "seat": _serialize_optional_seat(seat),
    }


def settle_harvest_periods(db: Session, periods) -> list[dict]:
    from app.services.royalty.settlement import confirm_settlement, should_auto_confirm_harvest_batch

    drafts = draft_settlements_for_periods(db, periods, isolate_auto_confirm=True)
    out = []
    for item in drafts:
        batch_id = item.get("batch_id")
        if batch_id and should_auto_confirm_harvest_batch(db, batch_id):
            confirmed = confirm_settlement(db, str(batch_id))
            item = {**item, "status": confirmed.get("status"), "auto_confirmed": True, "needs_confirm": False}
        out.append(item)
    return out
