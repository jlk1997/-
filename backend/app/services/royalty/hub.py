"""Creator hub and per-work ledger — settlement vs display, alerts, period split."""

from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.schemas import (
    DistributionDelivery,
    FeatureFlag,
    PayoutAccount,
    PlatformMetricSnapshot,
    Release,
    SettlementBatch,
    SettlementLine,
    User,
    Work,
    WorkEngagementStats,
)
from app.services.distribution.passport import live_store_count
from app.services.distribution.service import SLA_HOURS, serialize_delivery, serialize_release
from app.services.ecosystem import get_creator_wallet
from app.services.royalty.connector import unclaimed_count
from app.services.royalty.settlement import current_period
from app.services.royalty.subjects import SUBJECT_WARMUP, accounting_subject
from app.services.royalty.sync_desk import listing_enabled
from app.services.royalty.wallet import wallet_overview


def _flag_on(db: Session, key: str, default: bool = True) -> bool:
    row = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    return row.enabled if row else default


def _automation_status(publishing_rows, session_wait_count: int) -> dict:
    from app.services.distribution.adapters import CnLabelAdapter, DistroKidAdapter, RouteNoteAdapter, TuneCoreAdapter
    from app.services.seats.service import farm_can_navigate

    return {
        "farm_navigate": farm_can_navigate(),
        "partners_configured": any(
            cls().configured() for cls in (DistroKidAdapter, TuneCoreAdapter, RouteNoteAdapter, CnLabelAdapter)
        ),
        "ops_queue": sum(1 for row in publishing_rows if getattr(row, "status", None) == "ops_queue"),
        "session_wait": session_wait_count,
        "handed_to_extension": sum(
            1
            for row in publishing_rows
            if getattr(row, "status", None) == "handed_to_extension"
            or bool((getattr(row, "attempt_meta", None) or {}).get("handed_to_extension"))
        ),
        "payout_mode": "manual_only",
    }


def display_work_level_keys(snaps) -> set[tuple]:
    return {
        (s.channel_code, s.source, s.period_key)
        for s in snaps
        if s.work_id and not s.usable_for_settlement
    }


def include_display_snapshot(s, work_level_keys: set[tuple]) -> bool:
    if s.usable_for_settlement:
        return False
    if s.work_id is None and (s.channel_code, s.source, s.period_key) in work_level_keys:
        return False
    return True


def _release_calendar(db: Session, user: User) -> list[dict]:
    from app.services.distribution.automation import weekly_release_suggestions

    return weekly_release_suggestions(db, user, limit=3)


_ACTIVE_SHIP = frozenset({"queued", "delivering", "live"})


def is_workbench_master(work: Work) -> bool:
    pps = work.post_process_status if isinstance(getattr(work, "post_process_status", None), dict) else {}
    return bool(pps.get("workbench"))


def prefer_workbench_masters(works: list[Work]) -> list[Work]:
    """If Work B (beautify bounce) exists unpublished, hide the superseded parent A."""
    bounced_parents = {
        work.parent_work_id
        for work in works
        if work.parent_work_id and is_workbench_master(work)
    }
    if not bounced_parents:
        return works
    return [work for work in works if work.id not in bounced_parents]


def count_needs_beautify(works: list[Work]) -> int:
    """Unpublished songs that are still Work A — next door is beautify, not store release."""
    return sum(1 for work in works if not is_workbench_master(work))


def unpublished_workbench_successor(db: Session, work: Work) -> Work | None:
    """Return the unpublished beautify master that should ship instead of this work."""
    if getattr(work, "release_status", None) in _ACTIVE_SHIP:
        return None
    if is_workbench_master(work):
        return None
    rows = (
        db.query(Work)
        .filter(Work.parent_work_id == work.id, Work.owner_id == work.owner_id)
        .order_by(Work.created_at.desc())
        .all()
    )
    for row in rows:
        if is_workbench_master(row) and getattr(row, "release_status", None) not in _ACTIVE_SHIP:
            return row
    return None


def work_version_family(db: Session, work: Work) -> list[dict]:
    """Original take plus beautify versions, so release can name which one ships."""
    from sqlalchemy import or_

    root_id = work.parent_work_id or work.id
    rows = (
        db.query(Work)
        .filter(Work.owner_id == work.owner_id)
        .filter(or_(Work.id == root_id, Work.parent_work_id == root_id))
        .order_by(Work.created_at.asc())
        .all()
    )
    out = []
    for index, row in enumerate(rows, start=1):
        beautified = bool(row.parent_work_id and is_workbench_master(row))
        out.append(
            {
                "id": str(row.id),
                "title": row.title,
                "label": "美化版" if beautified else "原版",
                "version": index,
                "current": row.id == work.id,
            }
        )
    return out


def resolve_release_work(db: Session, work: Work) -> tuple[Work, Work | None]:
    child = unpublished_workbench_successor(db, work)
    if child is None:
        return work, None
    return child, work


def _serialize_unpublished(db: Session, works: list[Work]) -> list[dict]:
    if not works:
        return []
    from app.services.distribution.automation import release_hint_for_work, release_priority_payload
    from app.services.distribution.channel_suggest import suggest_channels_for_work

    ids = [work.id for work in works]
    stats = {
        row.work_id: row
        for row in db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id.in_(ids)).all()
    }
    rows = []
    for work in works:
        stat = stats.get(work.id)
        listen = int((stat.listen_completes if stat else 0) or 0)
        suggestion = suggest_channels_for_work(db, work)
        hint = release_hint_for_work(
            work=work,
            listen_completes=listen,
            unpublished=True,
            channel_suggestion=suggestion,
        )
        pri = release_priority_payload(work)
        pps = work.post_process_status if isinstance(work.post_process_status, dict) else {}
        successor = unpublished_workbench_successor(db, work)
        rows.append(
            {
                "work_id": str(work.id),
                "title": work.title,
                "cover_url": work.cover_url,
                "qc_ready": bool((work.post_process_status or {}).get("release_qc") or work.release_status == "qc_ready"),
                "listen_completes": listen,
                "hint": hint,
                "priority": pri,
                "channel_suggestion": suggestion,
                "from_workbench": bool(pps.get("workbench")),
                "parent_work_id": str(work.parent_work_id) if work.parent_work_id else None,
                "release_status": getattr(work, "release_status", None),
                "degraded": str(pps.get("state") or "") == "degraded",
                "superseded_by_work_id": str(successor.id) if successor else None,
            }
        )
    rows.sort(key=lambda item: (int((item.get("priority") or {}).get("score") or 0), item.get("listen_completes") or 0), reverse=True)
    return rows


def _fx_summary(revenue_by_currency: dict[str, int]) -> dict:
    from app.services.fx import convert_map

    converted = convert_map(revenue_by_currency)
    return {
        "payout_currency": converted["currency"],
        "revenue_payout_minor": converted["amount_minor"],
        "skipped": converted["skipped"],
    }


def build_hub_alerts(
    *,
    unpublished_count: int = 0,
    publishing_count: int = 0,
    rejected_count: int = 0,
    unclaimed_count: int = 0,
    unmatched_count: int = 0,
    isrc_blocked_count: int = 0,
    pending_confirm_count: int = 0,
    missing_payout: bool = False,
    kyc_none: bool = False,
    available_minor: int = 0,
    trial_ending_count: int = 0,
    clip_drop_count: int = 0,
    sla_overdue_count: int = 0,
    payout_today: bool = False,
    session_wait_count: int = 0,
    connector_online: bool = True,
) -> list[dict]:
    alerts: list[dict] = []
    if unpublished_count:
        alerts.append({"id": "unpublished", "level": "info", "count": unpublished_count})
    if publishing_count:
        alerts.append({"id": "publishing", "level": "info", "count": publishing_count})
    if session_wait_count and not connector_online:
        alerts.append({"id": "connector_offline", "level": "warning", "count": session_wait_count})
    if sla_overdue_count:
        alerts.append({"id": "sla_overdue", "level": "warning", "count": sla_overdue_count})
    if rejected_count:
        alerts.append({"id": "rejected", "level": "warning", "count": rejected_count})
    if pending_confirm_count:
        alerts.append({"id": "pending_confirm", "level": "info", "count": pending_confirm_count})
    if available_minor > 0 and payout_today:
        alerts.append({"id": "payout_today", "level": "info", "count": 1})
    if available_minor > 0 and missing_payout:
        alerts.append({"id": "no_payout", "level": "warning", "count": 1})
    if available_minor > 0 and kyc_none:
        alerts.append({"id": "kyc", "level": "info", "count": 1})
    if trial_ending_count:
        alerts.append({"id": "trial_ending", "level": "info", "count": trial_ending_count})
    if clip_drop_count:
        alerts.append({"id": "clip_inbox", "level": "info", "count": clip_drop_count})
    return alerts


def _empty_channel(code: str) -> dict:
    return {
        "channel_code": code,
        "streams": 0,
        "display_streams": 0,
        "revenue_minor": 0,
        "warmup_revenue_minor": 0,
        "label_revenue_minor": 0,
        "period_streams": 0,
        "period_display_streams": 0,
        "period_revenue_minor": 0,
        "has_real": False,
        "sources": [],
        "predicted_revenue": None,
    }


def _empty_work(work_id: str) -> dict:
    return {
        "work_id": work_id,
        "streams": 0,
        "display_streams": 0,
        "revenue_minor": 0,
        "warmup_revenue_minor": 0,
        "label_revenue_minor": 0,
        "period_streams": 0,
        "period_display_streams": 0,
        "period_revenue_minor": 0,
        "has_real": False,
        "predicted_revenue": None,
    }


def _is_label_statement(snap) -> bool:
    from app.services.royalty.subjects import money_bucket

    return bool(snap.usable_for_settlement and money_bucket(snap.source) == "dsp")


def _accumulate(target: dict, snap, *, in_period: bool, work_level: set[tuple], settlement_winners: list | None = None) -> None:
    if snap.usable_for_settlement:
        amount = snap.revenue_minor or 0
        subject = accounting_subject(snap.source)
        if subject == SUBJECT_WARMUP:
            target["warmup_revenue_minor"] = int(target.get("warmup_revenue_minor") or 0) + amount
            return
        if _is_label_statement(snap):
            if settlement_winners is not None and snap not in settlement_winners:
                return
            target["streams"] += snap.streams or 0
            target["revenue_minor"] += amount
            target["has_real"] = True
            target["label_revenue_minor"] = int(target.get("label_revenue_minor") or 0) + amount
            if in_period:
                target["period_streams"] += snap.streams or 0
                target["period_revenue_minor"] += amount
            return
        target["display_streams"] += snap.streams or 0
        if in_period:
            target["period_display_streams"] += snap.streams or 0
        return
    if not include_display_snapshot(snap, work_level):
        return
    target["display_streams"] += snap.streams or 0
    if in_period:
        target["period_display_streams"] += snap.streams or 0


def _label_economy(db: Session, user: User, snaps, period_key: str) -> dict:
    from app.services.royalty.payout_calendar import expected_harvest_window
    from app.services.royalty.settlement import plan_settlement_lines

    from app.services.distribution.catalog import delivery_has_live_receipt

    live_row = next(
        (
            row
            for row in (
                db.query(DistributionDelivery)
                .filter(DistributionDelivery.owner_id == user.id, DistributionDelivery.status == "live")
                .order_by(DistributionDelivery.updated_at.asc())
                .limit(48)
                .all()
            )
            if delivery_has_live_receipt(row)
        ),
        None,
    )
    has_live = live_row is not None
    has_label_release = (
        db.query(Release.id).filter(Release.owner_id == user.id, Release.mode == "label").first() is not None
    )
    official = [s for s in snaps if _is_label_statement(s)]
    has_label_statement = bool(official)
    window = expected_harvest_window()
    period_snaps = [s for s in official if (s.period_key or "") == period_key] or official
    planned = plan_settlement_lines(db, period_snaps) if period_snaps else {}
    currency = "CNY"
    if planned.get("by_currency"):
        currency = planned["by_currency"][0].get("currency") or "CNY"
    return {
        "has_live": has_live,
        "has_label_release": has_label_release,
        "has_label_statement": has_label_statement,
        "waiting_for_statement": bool(has_live and has_label_release and not has_label_statement),
        "label_period": {
            "period_key": period_key,
            "waiting": has_live and has_label_release and not has_label_statement,
            "expected_earliest": window.get("earliest"),
            "expected_latest": window.get("latest"),
            "gross_minor": planned.get("gross_minor") or 0,
            "commission_minor": planned.get("commission_minor") or 0,
            "net_minor": planned.get("net_minor") or 0,
            "currency": currency,
            "mode": "seat_harvest",
        },
    }


_HUB_TTL_S = 12.0
_HUB_CACHE: dict[str, tuple[float, dict]] = {}


def invalidate_creator_hub(user_id: object | None = None) -> None:
    if user_id is None:
        _HUB_CACHE.clear()
        return
    _HUB_CACHE.pop(str(user_id), None)


def build_creator_hub(db: Session, user: User, *, force: bool = False) -> dict:
    key = str(user.id)
    now = time.monotonic()
    if not force:
        hit = _HUB_CACHE.get(key)
        if hit and now - hit[0] < _HUB_TTL_S:
            return copy.deepcopy(hit[1])
    data = _compute_creator_hub(db, user)
    _HUB_CACHE[key] = (now, copy.deepcopy(data))
    return data


def _compute_creator_hub(db: Session, user: User) -> dict:
    works = db.query(Work).filter(Work.owner_id == user.id).count()
    releases = db.query(Release).filter(Release.owner_id == user.id).count()
    snaps = db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.user_id == user.id).all()
    work_level = display_work_level_keys(snaps)
    period_key, _, _ = current_period(db)
    from app.services.royalty.priority import filter_settlement_snapshots

    settlement_winners = filter_settlement_snapshots(snaps)

    total_streams = 0
    display_streams = 0
    total_revenue = 0
    display_revenue = 0
    period_streams = 0
    period_display_streams = 0
    period_revenue = 0
    warmup_revenue = 0
    period_warmup_revenue = 0
    by_channel: dict[str, dict] = {}
    by_work: dict[str, dict] = {}

    for snap in snaps:
        in_period = (snap.period_key or "") == period_key
        if snap.usable_for_settlement:
            subject = accounting_subject(snap.source)
            amount = snap.revenue_minor or 0
            if subject == SUBJECT_WARMUP:
                warmup_revenue += amount
                if in_period:
                    period_warmup_revenue += amount
            elif _is_label_statement(snap) and snap in settlement_winners:
                total_streams += snap.streams or 0
                total_revenue += amount
                if in_period:
                    period_streams += snap.streams or 0
                    period_revenue += amount
            elif not _is_label_statement(snap):
                display_streams += snap.streams or 0
                display_revenue += amount
                if in_period:
                    period_display_streams += snap.streams or 0
        elif include_display_snapshot(snap, work_level):
            display_streams += snap.streams or 0
            display_revenue += snap.revenue_minor or 0
            if in_period:
                period_display_streams += snap.streams or 0

        ch = by_channel.setdefault(snap.channel_code, _empty_channel(snap.channel_code))
        _accumulate(ch, snap, in_period=in_period, work_level=work_level, settlement_winners=settlement_winners)
        if snap.source not in ch["sources"]:
            ch["sources"].append(snap.source)
        if snap.work_id:
            wk = by_work.setdefault(str(snap.work_id), _empty_work(str(snap.work_id)))
            _accumulate(wk, snap, in_period=in_period, work_level=work_level, settlement_winners=settlement_winners)

    latest = (
        db.query(func.max(PlatformMetricSnapshot.created_at))
        .filter(PlatformMetricSnapshot.user_id == user.id)
        .scalar()
    )
    credits = get_creator_wallet(db, user.id)
    fiat = wallet_overview(db, user)
    work_ids = [uuid.UUID(k) for k in by_work.keys()]
    work_rows = {str(w.id): w.title for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    from app.services.distribution.passport import live_store_counts

    store_counts = live_store_counts(db, work_ids)
    from app.services.royalty.predict import attach_prediction, load_geo_index, merge_predictions, store_compare

    geo_index = load_geo_index(db, user.id)
    for key, wk in by_work.items():
        wk["title"] = work_rows.get(key)
        wk["live_stores"] = int(store_counts.get(uuid.UUID(key), store_counts.get(key, 0))) if key else 0

    for ch in by_channel.values():
        attach_prediction(
            ch,
            ch.get("channel_code"),
            int(ch.get("display_streams") or 0) + int(ch.get("streams") or 0),
            db=db,
            user_id=user.id,
            geo_index=geo_index,
        )
    compare = store_compare(list(by_channel.values()))

    wallets = fiat.get("wallets") or []
    wallet_rows = [
        {
            "currency": (w.get("currency") or "CNY").upper(),
            "available_minor": int(w.get("available_minor") or 0),
            "pending_minor": int(w.get("pending_minor") or 0),
            "lifetime_earned_minor": int(w.get("lifetime_earned_minor") or 0),
        }
        for w in wallets
    ]
    primary = next((w for w in wallet_rows if w["currency"] == "CNY"), wallet_rows[0] if wallet_rows else None)
    available_minor = primary["available_minor"] if primary else 0
    pending_minor = primary["pending_minor"] if primary else 0
    lifetime_earned_minor = primary["lifetime_earned_minor"] if primary else 0
    has_available = any(w["available_minor"] > 0 for w in wallet_rows)
    revenue_by_currency: dict[str, int] = {}
    for snap in snaps:
        if not _is_label_statement(snap):
            continue
        currency = (getattr(snap, "currency", None) or "CNY").upper()
        revenue_by_currency[currency] = revenue_by_currency.get(currency, 0) + int(snap.revenue_minor or 0)

    active_work_ids = {
        r.work_id
        for r in db.query(Release)
        .filter(Release.owner_id == user.id, Release.status.in_(("queued", "delivering", "live")))
        .all()
    }
    unpublished = []
    for work in (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(40)
        .all()
    ):
        if work.id in active_work_ids:
            continue
        if not (work.audio_url or work.storage_key):
            continue
        unpublished.append(work)
    unpublished = prefer_workbench_masters(unpublished)

    degraded_count = 0
    qc_pending_count = 0
    for work in (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(80)
        .all()
    ):
        pps = dict(work.post_process_status or {})
        state = str(pps.get("state") or "")
        if state == "degraded":
            degraded_count += 1
        qc = pps.get("release_qc_result") or {}
        if state in ("ready", "completed") and not qc:
            qc_pending_count += 1

    publishing_rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.owner_id == user.id,
            DistributionDelivery.status.in_(
                ("submitting", "ops_queue", "awaiting_manual", "session_wait", "session_running", "needs_upload", "in_review")
            ),
        )
        .all()
    )
    publishing_count = len(publishing_rows)
    from app.services.distribution.assist import LEASE_WAIT_NOTE

    session_wait_count = sum(
        1
        for row in publishing_rows
        if row.status == "session_wait" and LEASE_WAIT_NOTE not in str(row.last_error or "")
    )
    upload_wait_count = sum(1 for row in publishing_rows if row.status in {"awaiting_manual", "needs_upload"})
    from app.services.distribution.assist import connector_public_state, has_connector_heartbeat

    connector = connector_public_state(db, user)
    connector_online = bool(connector.get("online") if connector else has_connector_heartbeat(db, user.id))
    from app.services.distribution.catalog import connected_channel_codes, default_upload_channels

    auto_ship_count = len(default_upload_channels(connected=connected_channel_codes(db, user)))
    now = datetime.utcnow()
    sla_overdue_count = sum(
        1
        for row in publishing_rows
        if now > (row.created_at or now) + timedelta(hours=SLA_HOURS)
        or bool((row.attempt_meta or {}).get("sla_escalated_at"))
    )
    rejected_count = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id, DistributionDelivery.status == "rejected")
        .count()
    )
    pending_confirm_count = (
        db.query(SettlementLine)
        .join(SettlementBatch, SettlementLine.batch_id == SettlementBatch.id)
        .filter(SettlementLine.user_id == user.id, SettlementBatch.status == "draft")
        .count()
    )
    missing_payout = db.query(PayoutAccount).filter(PayoutAccount.user_id == user.id).first() is None
    claimed = unclaimed_count(db, user.id)
    from app.services.harvest.unmatched import count_unmatched

    unmatched = count_unmatched(db, user)
    from app.services.royalty.ingest import list_isrc_unmatched_snapshots

    isrc_blocked = list_isrc_unmatched_snapshots(db, user_id=user.id, limit=8)
    isrc_blocked_count = len(isrc_blocked)
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from app.services.distribution.automation import auto_release_status
    from app.services.creator.commune import commune_overview
    from app.services.emotion_calendar import week_drop_plan
    from app.services.radio.network import compute_lineage_seed, list_owner_clip_drops, list_owner_radio_trials
    from app.services.royalty.payout_calendar import payout_calendar

    auto_release = auto_release_status(db, user)
    kyc_status = getattr(user, "kyc_status", None) or "none"
    try:
        commune = commune_overview(db, user)
    except (OperationalError, ProgrammingError):
        db.rollback()
        commune = {"commune": None}
    calendar = payout_calendar(period=(fiat.get("withdraw_config") or {}).get("period") or "weekly")
    try:
        week_drop = week_drop_plan(db, user)
    except (OperationalError, ProgrammingError):
        db.rollback()
        week_drop = None
    try:
        clip_drops = list_owner_clip_drops(db, user, limit=6)
        radio_trials = list_owner_radio_trials(db, user, limit=4)
        lineage_seed = compute_lineage_seed(db)
    except (OperationalError, ProgrammingError):
        db.rollback()
        clip_drops = []
        radio_trials = []
        lineage_seed = None
    trial_ending = sum(1 for row in radio_trials if row.get("live"))
    from app.services.seats.service import list_seats

    seats = list_seats(db, user)
    from app.services.seats.connections import build_connections

    connections = build_connections(db, user, seats)

    has_real_data = any(_is_label_statement(s) for s in snaps)
    show_prediction = has_real_data
    predicted_holder: dict = {}
    if show_prediction:
        predicted_holder["predicted_revenue"] = merge_predictions(
            [ch.get("predicted_revenue") for ch in by_channel.values() if ch.get("predicted_revenue")]
        )
    else:
        for wk in by_work.values():
            wk.pop("predicted_revenue", None)
        for ch in by_channel.values():
            ch.pop("predicted_revenue", None)
    predicted_total = predicted_holder.get("predicted_revenue") if show_prediction else None
    from app.services.creator_next import primary_creator_step

    label_bits = _label_economy(db, user, snaps, period_key)
    primary_next = primary_creator_step(
        works=works,
        releases=releases,
        unpublished_count=len(unpublished),
        degraded_count=degraded_count,
        needs_beautify_count=count_needs_beautify(unpublished),
        qc_pending_count=qc_pending_count,
        session_wait_count=session_wait_count,
        upload_wait_count=upload_wait_count,
        unmatched_count=unmatched,
        has_live=bool(label_bits.get("has_live")),
        delivering=bool(publishing_rows),
        has_available=available_minor > 0,
        has_pending=pending_minor > 0,
        pending_confirm_count=pending_confirm_count,
    )

    return {
        "works": works,
        "releases": releases,
        "total_streams": total_streams,
        "display_streams": display_streams,
        "settlement_revenue_minor": total_revenue,
        "display_revenue_minor": display_revenue,
        "warmup_revenue_minor": warmup_revenue,
        "label_revenue_minor": total_revenue,
        "period_key": period_key,
        "period_streams": period_streams,
        "period_display_streams": period_display_streams,
        "period_revenue_minor": period_revenue,
        "period_warmup_revenue_minor": period_warmup_revenue,
        "synced_at": latest.isoformat() if latest else None,
        "has_real_data": has_real_data,
        **label_bits,
        "distribution_enabled": _flag_on(db, "dsp_distribution"),
        "wallet_enabled": _flag_on(db, "royalty_wallet"),
        "by_channel": list(by_channel.values()),
        "by_work": list(by_work.values()),
        "credit_wallet": credits,
        "fiat_wallet": fiat,
        "seats": seats,
        "connections": connections,
        "harvest_health": harvest_health(
            connections=connections,
            unmatched_count=unmatched,
            pending_minor=pending_minor,
            available_minor=available_minor,
            pending_confirm_count=pending_confirm_count,
            seats=seats,
        ),
        "predicted_revenue": predicted_total,
        "store_compare": compare,
        "unclaimed_count": claimed,
        "unmatched_count": unmatched,
        "isrc_blocked_count": isrc_blocked_count,
        "isrc_blocked": isrc_blocked,
        "auto_release": auto_release,
        "available_minor": available_minor,
        "pending_minor": pending_minor,
        "lifetime_earned_minor": lifetime_earned_minor,
        "available_currency": primary["currency"] if primary else "CNY",
        "available_by_currency": wallet_rows,
        "revenue_by_currency": [
            {"currency": currency, "revenue_minor": amount} for currency, amount in revenue_by_currency.items()
        ],
        "fx": _fx_summary(revenue_by_currency),
        "unpublished_works": _serialize_unpublished(db, unpublished[:8]),
        "unpublished_count": len(unpublished),
        "auto_ship_count": auto_ship_count,
        "needs_beautify_count": count_needs_beautify(unpublished),
        "degraded_count": degraded_count,
        "qc_pending_count": qc_pending_count,
        "release_calendar": _release_calendar(db, user),
        "publishing_count": publishing_count,
        "rejected_count": rejected_count,
        "pending_confirm_count": pending_confirm_count,
        "kyc_status": kyc_status,
        "alerts": build_hub_alerts(
            unpublished_count=len(unpublished),
            publishing_count=publishing_count,
            rejected_count=rejected_count,
            unclaimed_count=claimed,
            unmatched_count=unmatched,
            isrc_blocked_count=isrc_blocked_count,
            pending_confirm_count=pending_confirm_count,
            missing_payout=missing_payout,
            kyc_none=kyc_status != "verified",
            available_minor=1 if has_available else 0,
            trial_ending_count=trial_ending,
            clip_drop_count=len(clip_drops),
            sla_overdue_count=sla_overdue_count,
            payout_today=bool(calendar.get("is_payout_day")),
            session_wait_count=session_wait_count,
            connector_online=connector_online,
        ),
        "connector_online": connector_online,
        "connector": connector,
        "session_wait_count": session_wait_count,
        "upload_wait_count": upload_wait_count,
        "automation": _automation_status(publishing_rows, session_wait_count),
        "week_drop": week_drop,
        "clip_drops": clip_drops,
        "radio_trials": radio_trials,
        "lineage_seed": lineage_seed,
        "payout_calendar": calendar,
        "wallet_split": {
            "credits": {
                "balance": int((credits or {}).get("balance_credits") or 0),
                "lifetime": int((credits or {}).get("lifetime_earned") or 0),
            },
            "fiat": {
                "available_minor": available_minor,
                "pending_minor": pending_minor,
                "lifetime_earned_minor": lifetime_earned_minor,
                "currency": primary["currency"] if primary else "CNY",
            },
            "sources": fiat.get("source_split") or {},
        },
        "commune": commune.get("commune"),
        "radio_chart": _hub_radio_chart(db),
        "publishing_rights": {
            "enabled": _flag_on(db, "publishing_rights_product", False),
            "status": "separate_line",
        },
        "next_action": hub_connector_next_action(connector, session_wait_count, upload_wait_count),
        "primary_next": primary_next,
        "has_distribution_license": _hub_has_distribution_license(db, user),
    }


def _work_radio_trial(db: Session, work: Work) -> dict:
    from app.services.radio.network import describe_radio_trial_for_work

    return describe_radio_trial_for_work(db, work)


def _work_clip_drops(db: Session, user: User, work: Work) -> list[dict]:
    from app.services.radio.network import list_clip_drops

    try:
        return list_clip_drops(db, user, str(work.id))
    except Exception:
        return []


def _work_clip_windows(work: Work) -> list[dict]:
    from app.services.distribution.catalog import clip_windows

    return clip_windows(getattr(work, "duration", None))


def _work_channel_suggestion(db: Session, work: Work) -> dict:
    from app.services.distribution.channel_suggest import suggest_channels_for_work

    return suggest_channels_for_work(db, work)


def _hub_radio_chart(db: Session) -> list[dict]:
    from app.services.radio.network import weekly_radio_chart

    return weekly_radio_chart(db, limit=3)


def _work_statement_window(deliveries, *, has_harvest: bool = False) -> dict:
    from app.services.royalty.payout_calendar import expected_harvest_window

    from app.services.distribution.catalog import delivery_has_live_receipt

    live_row = next(
        (
            d
            for d in deliveries
            if d.status == "live" and delivery_has_live_receipt(d) and getattr(d, "updated_at", None)
        ),
        None,
    )
    window = expected_harvest_window()
    return {
        "expected_earliest": window.get("earliest"),
        "expected_latest": window.get("latest"),
        "waiting": bool(live_row) and not has_harvest,
        "mode": "seat_harvest",
    }


def hub_connector_next_action(
    connector: dict | None,
    session_wait_count: int = 0,
    upload_wait_count: int = 0,
) -> str:
    last = (connector or {}).get("last_delivery") if isinstance(connector, dict) else None
    last = last if isinstance(last, dict) else {}
    for key in (str(last.get("status") or ""), str(last.get("event") or "")):
        if key in {
            "needs_challenge",
            "assisting",
            "session_running",
            "session_wait",
            "wait_connector",
            "fill_incomplete",
            "needs_upload",
            "publishing",
        }:
            return key
    if session_wait_count:
        return "session_wait"
    if upload_wait_count:
        return "needs_upload"
    return str(last.get("status") or last.get("event") or "")


def _hub_has_distribution_license(db: Session, user: User | None) -> bool:
    from app.services.seats.consent import user_has_distribution_license

    return user_has_distribution_license(db, user)


def harvest_health(
    *,
    connections: list | None = None,
    unmatched_count: int = 0,
    pending_minor: int = 0,
    available_minor: int = 0,
    pending_confirm_count: int = 0,
    seats: list | None = None,
) -> dict:
    connections = connections or []
    seats = seats or []
    unmatched = int(unmatched_count or 0)
    needs_login = sum(1 for row in connections if row.get("status") == "needs_login")
    can_harvest = sum(1 for row in connections if row.get("status") in {"settle", "metrics", "platform"})
    farm_rows = 0
    farm_ok = False
    for seat in seats:
        health = seat.get("farm_health") if isinstance(seat, dict) else None
        health = health if isinstance(health, dict) else {}
        farm_rows += int(health.get("rows") or 0)
        if health.get("ok") or int(health.get("matched") or 0) > 0:
            farm_ok = True
    if unmatched > 0:
        state, cta = "unmatched", "attach"
    elif needs_login and can_harvest == 0:
        state, cta = "needs_login", "accounts"
    elif int(available_minor or 0) > 0:
        state, cta = "withdrawable", "wallet"
    elif int(pending_confirm_count or 0) > 0:
        state, cta = "draft", "settlements"
    elif int(pending_minor or 0) > 0:
        state, cta = "pending", "settlements"
    elif can_harvest:
        state, cta = "ready", None
    else:
        state, cta = "idle", None
    return {
        "state": state,
        "cta": cta,
        "unmatched_count": unmatched,
        "needs_login": needs_login,
        "can_harvest": can_harvest,
        "farm_ok": farm_ok,
        "farm_rows": farm_rows,
        "pending_minor": int(pending_minor or 0),
        "available_minor": int(available_minor or 0),
        "pending_confirm_count": int(pending_confirm_count or 0),
        "zero_rows_success": False,
    }


def money_source_split(
    *,
    settlement_lines: list | None = None,
    warmup_minor: int = 0,
    label_minor: int = 0,
) -> dict:
    from app.services.distribution.catalog import HARVEST_SOURCES
    from app.services.royalty.subjects import money_bucket

    radio = sync = embed = dsp = harvest = 0
    lines = list(settlement_lines or [])
    for row in lines:
        amount = int(row.get("net_minor") or row.get("gross_minor") or 0)
        source = row.get("source")
        bucket = money_bucket(source)
        if bucket == "radio":
            radio += amount
        elif bucket == "sync":
            sync += amount
        elif bucket == "embed":
            embed += amount
        elif bucket == "dsp":
            dsp += amount
            if (source or "") in HARVEST_SOURCES:
                harvest += amount
    if radio == 0:
        radio = int(warmup_minor or 0)
    if dsp == 0:
        dsp = int(label_minor or 0)
    return {
        "radio_minor": radio,
        "sync_minor": sync,
        "embed_minor": embed,
        "dsp_minor": dsp,
        "harvest_minor": harvest,
    }


def money_timeline(
    *,
    live: bool = False,
    revenue_minor: int = 0,
    settlement_lines: list | None = None,
    predicted: dict | None = None,
    paid: bool = False,
    warmup_minor: int = 0,
    label_minor: int = 0,
) -> dict:
    lines = list(settlement_lines or [])
    has_amount = int(revenue_minor or 0) > 0 or any(int(row.get("gross_minor") or 0) > 0 for row in lines)
    has_commission = any(int(row.get("commission_minor") or 0) > 0 or row.get("commission_rate") for row in lines)
    withdrawable = any(bool(row.get("withdrawable")) for row in lines)
    stages = [
        {"id": "live", "done": bool(live)},
        {"id": "amount", "done": has_amount, "minor": int(revenue_minor or 0)},
        {"id": "commission", "done": has_commission},
        {"id": "withdrawable", "done": withdrawable},
        {"id": "paid", "done": bool(paid)},
    ]
    current = 0
    for index, stage in enumerate(stages):
        if not stage["done"]:
            current = index
            break
        current = min(index + 1, len(stages) - 1)
    return {
        "stages": stages,
        "current": current,
        "predicted": predicted if isinstance(predicted, dict) else None,
        "display_only_prediction": True,
        "sources": money_source_split(
            settlement_lines=lines,
            warmup_minor=warmup_minor,
            label_minor=label_minor if label_minor else revenue_minor,
        ),
    }


def work_next_action(
    *,
    has_active_release: bool,
    delivering: bool,
    live: bool,
    has_real: bool,
    has_available: bool,
    label: bool | None = None,
    unmatched_count: int = 0,
    trial_live: bool = False,
    trial_status: str | None = None,
    sync_open: bool = False,
    needs_store_action: bool = False,
) -> str:
    if trial_live:
        return "watch_trial"
    if trial_status == "ended" and not has_active_release:
        return "release"
    if not has_active_release:
        return "release"
    if needs_store_action or not live:
        return "stores"
    if not has_available:
        return "sync"
    return "wallet"


def _work_asset_status(db: Session, work: Work, releases: list) -> dict:
    from app.services.distribution.asset_profiles import release_asset_status

    channels: list[str] = []
    for row in releases or []:
        for code in row.selected_channels or []:
            if code and code not in channels:
                channels.append(code)
    return release_asset_status(work, channels)


def build_work_ledger(db: Session, user: User, work_id: str) -> dict:
    try:
        wid = uuid.UUID(str(work_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")

    snaps = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.user_id == user.id, PlatformMetricSnapshot.work_id == work.id)
        .all()
    )
    work_level = display_work_level_keys(snaps)
    period_key, _, _ = current_period(db)
    from app.services.royalty.priority import filter_settlement_snapshots

    settlement_winners = filter_settlement_snapshots(snaps)
    by_channel: dict[str, dict] = {}
    streams = display_streams = revenue = warmup_revenue = label_revenue = 0

    for snap in snaps:
        in_period = (snap.period_key or "") == period_key
        ch = by_channel.setdefault(snap.channel_code, _empty_channel(snap.channel_code))
        _accumulate(ch, snap, in_period=in_period, work_level=work_level, settlement_winners=settlement_winners)
        if snap.source not in ch["sources"]:
            ch["sources"].append(snap.source)
        if snap.usable_for_settlement:
            amount = snap.revenue_minor or 0
            subject = accounting_subject(snap.source)
            if subject == SUBJECT_WARMUP:
                warmup_revenue += amount
            elif _is_label_statement(snap) and snap in settlement_winners:
                streams += snap.streams or 0
                revenue += amount
                label_revenue += amount
            elif not _is_label_statement(snap):
                display_streams += snap.streams or 0
        elif include_display_snapshot(snap, work_level):
            display_streams += snap.streams or 0

    releases = (
        db.query(Release)
        .filter(Release.owner_id == user.id, Release.work_id == work.id)
        .order_by(Release.created_at.desc())
        .all()
    )
    deliveries = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id, DistributionDelivery.work_id == work.id)
        .order_by(DistributionDelivery.updated_at.desc())
        .all()
    )
    lines = (
        db.query(SettlementLine)
        .filter(SettlementLine.user_id == user.id, SettlementLine.work_id == work.id)
        .order_by(SettlementLine.id.desc())
        .limit(80)
        .all()
    )
    batch_ids = {line.batch_id for line in lines}
    batches = {
        b.id: b for b in db.query(SettlementBatch).filter(SettlementBatch.id.in_(batch_ids)).all()
    } if batch_ids else {}
    settlement_lines = []
    for line in lines:
        batch = batches.get(line.batch_id)
        if batch and batch.status == "voided":
            continue
        gross = line.gross_minor or 0
        commission = line.commission_minor or 0
        stored_rate = getattr(line, "commission_rate", None)
        settlement_lines.append(
            {
                "batch_id": str(line.batch_id),
                "period_key": batch.period_key if batch else None,
                "status": batch.status if batch else "draft",
                "withdrawable": (batch.status if batch else "draft") == "confirmed",
                "channel_code": line.channel_code,
                "source": line.source,
                "accounting_subject": accounting_subject(line.source),
                "gross_minor": gross,
                "commission_minor": commission,
                "commission_rate": stored_rate if stored_rate in (10, 20, 30) else (int(round(commission * 100 / gross)) if gross else 0),
                "net_minor": line.net_minor,
                "currency": line.currency,
            }
        )

    from app.services.distribution.catalog import delivery_has_live_receipt

    live = any(d.status == "live" and delivery_has_live_receipt(d) for d in deliveries)
    delivering = any(
        d.status in {"submitting", "ops_queue", "awaiting_manual", "session_wait", "session_running", "needs_upload", "in_review"}
        or (d.status == "live" and not delivery_has_live_receipt(d))
        for d in deliveries
    )
    needs_store_action = any(
        d.status in {"session_wait", "session_running", "waiting_login", "assisting", "needs_upload"}
        for d in deliveries
    )
    has_active = any(r.status in {"queued", "delivering", "live"} for r in releases)
    fiat = wallet_overview(db, user)
    has_available = any(int(w.get("available_minor") or 0) > 0 for w in (fiat.get("wallets") or []))
    has_label = any(getattr(r, "mode", None) == "label" for r in releases)
    has_label_statement = any(_is_label_statement(s) for s in snaps)
    from app.services.harvest.unmatched import count_unmatched

    unmatched_count = count_unmatched(db, user)
    clip_drops = _work_clip_drops(db, user, work)
    clip_window_rows = _work_clip_windows(work)
    radio_trial = _work_radio_trial(db, work)
    from app.services.royalty.predict import attach_prediction, load_geo_index, merge_predictions, store_compare

    geo_index = load_geo_index(db, user.id)
    work_pred = {}
    show_prediction = has_label_statement
    if show_prediction:
        for ch in by_channel.values():
            attach_prediction(
                ch,
                ch.get("channel_code"),
                int(ch.get("display_streams") or 0) + int(ch.get("streams") or 0),
                db=db,
                user_id=user.id,
                work_id=work.id,
                geo_index=geo_index,
            )
        merged = merge_predictions(
            [ch.get("predicted_revenue") for ch in by_channel.values() if ch.get("predicted_revenue")]
        )
        if merged:
            work_pred["predicted_revenue"] = merged
    from app.models.schemas import Withdrawal

    paid = False
    if any(line.get("withdrawable") for line in settlement_lines):
        paid = (
            db.query(Withdrawal.id)
            .filter(Withdrawal.user_id == user.id, Withdrawal.status.in_(("paid", "paid_manual")))
            .first()
            is not None
        )

    requested_fields: list[str] = []
    for delivery in deliveries:
        blob = delivery.attempt_meta or {}
        if str(blob.get("info_status") or "") != "waiting_user":
            continue
        for field in blob.get("requested_fields") or []:
            token = str(field)
            if token and token not in requested_fields:
                requested_fields.append(token)
    successor = unpublished_workbench_successor(db, work)
    from app.services.creator_next import next_for_work

    song_next = next_for_work(
        has_audio=bool(work.audio_url),
        degraded=str((work.post_process_status if isinstance(work.post_process_status, dict) else {}).get("state") or "") == "degraded",
        needs_beautify=bool(work.audio_url) and not is_workbench_master(work) and successor is None,
        has_release=bool(releases),
        delivering=delivering,
        live=live,
        has_revenue=has_label_statement,
        pending_confirm=any(line.get("status") == "draft" for line in settlement_lines),
        requested_fields=requested_fields,
    )
    return {
        "work": {
            "id": str(work.id),
            "title": work.title,
            "cover_url": work.cover_url,
            "release_status": getattr(work, "release_status", None),
            "isrc": getattr(work, "isrc", None),
            "audio_url": work.audio_url,
            "live_stores": live_store_count(db, work.id),
            "from_workbench": is_workbench_master(work),
            "superseded_by_work_id": str(successor.id) if successor else None,
        },
        "asset_status": _work_asset_status(db, work, releases),
        "period_key": period_key,
        "streams": streams,
        "display_streams": display_streams,
        "revenue_minor": revenue,
        "predicted_revenue": work_pred.get("predicted_revenue") if show_prediction else None,
        "store_compare": store_compare(list(by_channel.values())),
        "warmup_revenue_minor": warmup_revenue,
        "label_revenue_minor": label_revenue,
        "has_real_data": has_label_statement,
        "has_label_statement": has_label_statement,
        "has_label_release": has_label,
        "waiting_for_statement": bool(live and not has_label_statement),
        "label_period": _work_statement_window(deliveries, has_harvest=has_label_statement),
        "by_channel": list(by_channel.values()),
        "releases": [serialize_release(db, row) for row in releases],
        "deliveries": [serialize_delivery(d) for d in deliveries],
        "settlement_lines": settlement_lines,
        "versions": work_version_family(db, work),
        "requested_fields": requested_fields,
        "next_for_work": song_next,
        "next_action": work_next_action(
            has_active_release=has_active,
            delivering=delivering,
            live=live,
            has_real=has_label_statement,
            has_available=has_available,
            label=has_label if releases else None,
            unmatched_count=unmatched_count,
            trial_live=bool(radio_trial.get("live")),
            trial_status=str(radio_trial.get("status") or "") or None,
            sync_open=listing_enabled(work),
            needs_store_action=needs_store_action,
        ),
        "unmatched_count": unmatched_count,
        "radio_trial": radio_trial,
        "channel_suggestion": _work_channel_suggestion(db, work),
        "clip_drops": clip_drops,
        "clip_windows": clip_window_rows,
        "money_timeline": money_timeline(
            live=live,
            revenue_minor=revenue,
            settlement_lines=settlement_lines,
            predicted=work_pred.get("predicted_revenue") if show_prediction else None,
            paid=paid,
            warmup_minor=warmup_revenue,
            label_minor=label_revenue,
        ),
        "by_clip": [
            {
                "length": clip.get("length"),
                "start": clip.get("start"),
                "end": clip.get("end"),
                "drops": sum(1 for drop in clip_drops if int(drop.get("clip_length") or 0) == int(clip.get("length") or 0)),
                "revenue_minor": 0,
                "display_only": True,
            }
            for clip in clip_window_rows
        ],
    }
