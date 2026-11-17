from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.schemas import (
    CommissionRule,
    ConnectorIngestBatch,
    DistributionLicense,
    FeatureFlag,
    PlatformMetricSnapshot,
    Release,
    SettlementBatch,
    SettlementLine,
    User,
    Work,
)
from app.services.distribution.catalog import HARVEST_SOURCES, SETTLEMENT_SOURCES
from app.services.royalty.subjects import AUTO_CONFIRM_SOURCES, EXTERNAL_ROYALTY_SOURCES
from app.services.notifications import create_notification
from app.services.royalty.priority import filter_settlement_snapshots
from app.services.royalty.wallet import add_ledger, get_or_create_wallet

ALLOWED_RATES = (10, 20, 30)


def split_amounts(gross_minor: int, rate_percent: int) -> tuple[int, int]:
    gross = max(0, int(gross_minor or 0))
    rate = int(rate_percent or 0)
    commission = int(round(gross * rate / 100))
    commission = min(gross, max(0, commission))
    return commission, gross - commission


def pick_commission_rate(license_rate: int | None, rule_rate: int | None) -> int:
    if license_rate in ALLOWED_RATES:
        return int(license_rate)
    if rule_rate in ALLOWED_RATES:
        return int(rule_rate)
    return 20


def allowed_label_rates(db: Session, user) -> list[int]:
    level = (getattr(user, "creator_level", None) or "standard")
    floor = commission_rate(db, mode="label", channel_code="spotify", user_level=level)
    if floor not in ALLOWED_RATES:
        floor = 20
    return [rate for rate in ALLOWED_RATES if rate >= floor]


def confirmable_status(status: str) -> str:
    if status == "confirmed":
        return "already"
    if status == "draft":
        return "ok"
    return "blocked"


def line_dedupe_key(user_id, work_id, channel_code) -> tuple:
    return (str(user_id or ""), str(work_id or ""), str(channel_code or ""))


def settlement_config(db: Session) -> dict:
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    cfg = (flag.config if flag and flag.config else {}) or {}
    return {
        "min_settlement_minor": max(0, int(cfg.get("min_settlement_minor") or 0)),
        "period": cfg.get("period") or "monthly",
    }


def commission_rate(db: Session, *, mode: str, channel_code: str, user_level: str) -> int:
    rules = db.query(CommissionRule).filter(CommissionRule.enabled.is_(True)).all()
    best = None
    best_score = -1
    for rule in rules:
        if rule.mode not in (mode, "*"):
            continue
        if rule.channel_code not in (channel_code, "*"):
            continue
        if rule.user_level not in (user_level, "*"):
            continue
        score = (2 if rule.mode == mode else 0) + (2 if rule.channel_code == channel_code else 0) + (
            2 if rule.user_level == user_level else 0
        )
        if score > best_score:
            best = rule
            best_score = score
    return pick_commission_rate(None, best.rate_percent if best else 20)


def current_period(db: Session, now: datetime | None = None) -> tuple[str, date, date]:
    now = now or datetime.utcnow()
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    period = ((flag.config or {}) if flag else {}).get("period") or "monthly"
    if period == "weekly":
        start = (now - timedelta(days=now.weekday())).date()
        end = start + timedelta(days=6)
        key = f"{start.isoformat()}_w"
    else:
        start = now.date().replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        key = start.strftime("%Y-%m")
    return key, start, end


def bounds_for_period_key(key: str, fallback_start: date, fallback_end: date) -> tuple[date, date]:
    raw = (key or "").strip()
    if raw.endswith("_w") and len(raw) >= 12:
        try:
            start = date.fromisoformat(raw[:10])
            return start, start + timedelta(days=6)
        except ValueError:
            return fallback_start, fallback_end
    if len(raw) >= 7 and raw[4] == "-":
        try:
            year, month = int(raw[:4]), int(raw[5:7])
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(year, month + 1, 1) - timedelta(days=1)
            return start, end
        except ValueError:
            return fallback_start, fallback_end
    return fallback_start, fallback_end


def summarize_unsettled_periods(snaps) -> list[dict]:
    by: dict[str, dict] = {}
    for snap in snaps:
        key = snap.period_key or ""
        row = by.setdefault(key, {"period_key": key, "count": 0, "revenue_minor": 0})
        row["count"] += 1
        row["revenue_minor"] += snap.revenue_minor or 0
    return sorted(by.values(), key=lambda item: item["period_key"] or "", reverse=True)


def prefer_label_release(db: Session, work_id, current: Release | None = None) -> Release | None:
    if not work_id:
        return current
    label = (
        db.query(Release)
        .filter(Release.work_id == work_id, Release.mode == "label")
        .order_by(Release.created_at.desc())
        .first()
    )
    if label:
        return label
    if current:
        return current
    return (
        db.query(Release)
        .filter(Release.work_id == work_id)
        .order_by(Release.created_at.desc())
        .first()
    )


def resolve_release_for_snap(db: Session, snap) -> Release | None:
    current = None
    if snap.release_id:
        current = db.query(Release).filter(Release.id == snap.release_id).first()
        if current and current.mode == "label":
            return current
    return prefer_label_release(db, snap.work_id, current)


def license_rate_for_release(db: Session, release: Release | None) -> int | None:
    if not release:
        return None
    lic = (
        db.query(DistributionLicense)
        .filter(DistributionLicense.release_id == release.id)
        .order_by(DistributionLicense.signed_at.desc())
        .first()
    )
    return lic.commission_rate if lic else None


def promotional_label_rate(db: Session, user: User | None) -> int | None:
    if not user:
        return None
    from sqlalchemy import func

    count = (
        db.query(func.count(func.distinct(Release.work_id)))
        .filter(
            Release.owner_id == user.id,
            Release.mode == "label",
            Release.status.in_(("queued", "delivering", "live")),
        )
        .scalar()
        or 0
    )
    if int(count) <= 3:
        return 10
    return None


def locked_or_resolve_rate(db: Session, snap, release: Release | None, user: User | None) -> int | None:
    raw = snap.raw if isinstance(getattr(snap, "raw", None), dict) else {}
    stored = raw.get("settled_commission_rate")
    if stored in ALLOWED_RATES:
        return int(stored)
    if getattr(snap, "id", None):
        line = (
            db.query(SettlementLine)
            .filter(
                SettlementLine.snapshot_id == snap.id,
                SettlementLine.commission_rate.in_(ALLOWED_RATES),
            )
            .order_by(SettlementLine.id.desc())
            .first()
        )
        if line and line.commission_rate in ALLOWED_RATES:
            return int(line.commission_rate)
    return resolve_commission_for_snap(db, snap, release, user)


def resolve_commission_for_snap(db: Session, snap, release: Release | None, user: User | None) -> int | None:
    from app.services.distribution.catalog import HARVEST_SOURCES
    from app.services.royalty.subjects import EXTERNAL_ROYALTY_SOURCES

    source = getattr(snap, "source", None)
    level = (user.creator_level if user else "standard") or "standard"
    ownership = ((getattr(snap, "raw", None) or {}) or {}).get("ownership")
    harvest = source in HARVEST_SOURCES
    self_mode = (release and release.mode == "self_release") or ownership == "user" or source == "user_connector"
    if harvest or self_mode:
        mode = "self_release" if self_mode else "label"
        rule = commission_rate(db, mode=mode, channel_code=snap.channel_code, user_level=level)
        license_rate = license_rate_for_release(db, release) if mode == "label" else None
        rate = pick_commission_rate(license_rate, rule)
        if mode == "label":
            promo = promotional_label_rate(db, user)
            if promo and (license_rate not in ALLOWED_RATES):
                rate = min(rate, promo)
        return rate
    rule = commission_rate(db, mode="label", channel_code=snap.channel_code, user_level=level)
    license_rate = license_rate_for_release(db, release)
    if source in EXTERNAL_ROYALTY_SOURCES and license_rate is None:
        return None
    return pick_commission_rate(license_rate, rule)


def _add_money(bucket: dict, currency: str, *, gross: int, commission: int, net: int) -> None:
    row = bucket.setdefault(currency, {"currency": currency, "gross_minor": 0, "commission_minor": 0, "net_minor": 0})
    row["gross_minor"] += gross
    row["commission_minor"] += commission
    row["net_minor"] += net


def _effective_rate(line) -> int:
    gross = line.gross_minor or 0
    commission = line.commission_minor or 0
    stored = getattr(line, "commission_rate", None)
    if stored in ALLOWED_RATES:
        return int(stored)
    return int(round(commission * 100 / gross)) if gross else 0


def plan_settlement_lines(db: Session, snaps, *, min_settlement_minor: int | None = None) -> dict:
    snaps = filter_settlement_snapshots(snaps)
    if min_settlement_minor is None:
        min_settlement_minor = settlement_config(db)["min_settlement_minor"]
    planned = []
    skipped = {
        "self_release": 0,
        "no_user": 0,
        "no_rate": 0,
        "no_license": 0,
        "non_positive": 0,
        "below_minimum": 0,
        "already_in_batch": 0,
    }
    by_currency: dict[str, dict] = {}
    by_rate: dict[int, dict] = {}
    gross_total = commission_total = net_total = 0
    for snap in snaps:
        if not snap.user_id:
            skipped["no_user"] += 1
            continue
        gross = int(snap.revenue_minor or 0)
        if gross <= 0:
            skipped["non_positive"] += 1
            continue
        user = db.query(User).filter(User.id == snap.user_id).first()
        release = resolve_release_for_snap(db, snap)
        if getattr(snap, "settled", False):
            skipped["already_in_batch"] += 1
            continue
        already = int(((snap.raw or {}) if isinstance(snap.raw, dict) else {}).get("settled_revenue_minor") or 0)
        if already:
            gross = max(0, gross - already)
        if gross <= 0:
            skipped["already_in_batch"] += 1
            continue
        rate = locked_or_resolve_rate(db, snap, release, user) if already else resolve_commission_for_snap(db, snap, release, user)
        if rate is None:
            from app.services.royalty.subjects import EXTERNAL_ROYALTY_SOURCES

            if release and release.mode == "self_release":
                skipped["self_release"] += 1
            elif getattr(snap, "source", None) in EXTERNAL_ROYALTY_SOURCES:
                skipped["no_license"] += 1
            else:
                skipped["no_rate"] += 1
            continue
        commission, net = split_amounts(gross, rate)
        if min_settlement_minor > 0 and net < min_settlement_minor:
            skipped["below_minimum"] += 1
            continue
        currency = (snap.currency or "CNY").upper()
        from app.services.royalty.splits import expand_split_lines

        for part in expand_split_lines(db, snap.work_id, snap.user_id, gross, commission, net):
            planned.append(
                {
                    "snap": snap,
                    "user_id": part["user_id"],
                    "work_id": snap.work_id,
                    "release_id": release.id if release else snap.release_id,
                    "channel_code": snap.channel_code,
                    "source": snap.source,
                    "rate": rate,
                    "gross_minor": part["gross_minor"],
                    "commission_minor": part["commission_minor"],
                    "net_minor": part["net_minor"],
                    "currency": currency,
                    "share_role": part.get("role"),
                }
            )
            gross_total += part["gross_minor"]
            commission_total += part["commission_minor"]
            net_total += part["net_minor"]
            _add_money(by_currency, currency, gross=part["gross_minor"], commission=part["commission_minor"], net=part["net_minor"])
            rate_row = by_rate.setdefault(rate, {"rate": rate, "count": 0, "gross_minor": 0, "commission_minor": 0, "net_minor": 0})
            rate_row["count"] += 1
            rate_row["gross_minor"] += part["gross_minor"]
            rate_row["commission_minor"] += part["commission_minor"]
            rate_row["net_minor"] += part["net_minor"]
    return {
        "lines": planned,
        "skipped": skipped,
        "gross_minor": gross_total,
        "commission_minor": commission_total,
        "net_minor": net_total,
        "by_currency": list(by_currency.values()),
        "by_rate": sorted(by_rate.values(), key=lambda item: item["rate"]),
        "platform_take": list(by_currency.values()),
    }


def preview_settlement(db: Session) -> dict:
    key, start, end = current_period(db)
    snaps = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
            PlatformMetricSnapshot.settled.is_(False),
            PlatformMetricSnapshot.source.in_(tuple(SETTLEMENT_SOURCES)),
        )
        .all()
    )
    snaps = filter_settlement_snapshots(snaps)
    current_snaps = [s for s in snaps if (s.period_key or "") == key]
    planned = plan_settlement_lines(db, current_snaps)
    periods = summarize_unsettled_periods(snaps)
    draft = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.period_key == key, SettlementBatch.status == "draft")
        .first()
    )
    confirmed = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.period_key == key, SettlementBatch.status == "confirmed")
        .first()
    )
    pending_ops = (
        db.query(ConnectorIngestBatch)
        .filter(ConnectorIngestBatch.source == "ops_connector", ConnectorIngestBatch.status == "pending_review")
        .count()
    )
    pending_user = (
        db.query(ConnectorIngestBatch)
        .filter(ConnectorIngestBatch.source == "user_connector", ConnectorIngestBatch.status == "pending_review")
        .count()
    )
    return {
        "period_key": key,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "unsettled_for_period": len(planned["lines"]),
        "revenue_minor_for_period": planned["gross_minor"],
        "unsettled_other_periods": [p for p in periods if p["period_key"] != key],
        "needs_confirm": bool(draft),
        "draft_batch_id": str(draft.id) if draft else None,
        "has_confirmed_batch": bool(confirmed),
        "supplemental": bool(confirmed and planned["lines"]),
        "pending_ops_connector_batches": pending_ops,
        "pending_user_connector_batches": pending_user,
        "gross_minor_for_period": planned["gross_minor"],
        "commission_minor_for_period": planned["commission_minor"],
        "net_minor_for_period": planned["net_minor"],
        "platform_take_minor_for_period": planned["commission_minor"],
        "by_currency": planned["by_currency"],
        "by_rate": planned["by_rate"],
        "skipped": planned["skipped"],
        "planned_lines": len(planned["lines"]),
    }


def _existing_line_index(db: Session, batch_id) -> tuple[set, set]:
    rows = db.query(SettlementLine).filter(SettlementLine.batch_id == batch_id).all()
    snap_ids = {(row.snapshot_id, row.user_id) for row in rows if row.snapshot_id}
    keys = {line_dedupe_key(row.user_id, row.work_id, row.channel_code) for row in rows}
    return snap_ids, keys


def _batch_line_sources(db: Session, batch_id) -> set[str]:
    return {
        row[0]
        for row in db.query(SettlementLine.source).filter(SettlementLine.batch_id == batch_id).all()
        if row[0]
    }


def _snapshot_confidence(snap) -> float:
    raw_conf = (snap.raw or {}).get("confidence") if snap else None
    if raw_conf is None:
        return 0.0
    try:
        return float(raw_conf)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_auto_confirmable(snap) -> bool:
    from app.services.distribution.automation import AUTO_CONFIRM_MIN_CONFIDENCE
    from app.services.royalty.subjects import HARVEST_AUTO_CONFIRM_SOURCES

    # First-party radio / sync / embed are platform-written and skip the DOM confidence floor.
    # Harvest scrapes must still prove ≥ 0.9 before isolate_auto_confirm will pick them up.
    if getattr(snap, "source", None) not in HARVEST_AUTO_CONFIRM_SOURCES:
        return True
    return _snapshot_confidence(snap) >= AUTO_CONFIRM_MIN_CONFIDENCE


def _select_draft_batch(db: Session, key: str, *, isolate_auto_confirm: bool) -> SettlementBatch | None:
    drafts = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.period_key == key, SettlementBatch.status == "draft")
        .order_by(SettlementBatch.created_at.asc())
        .all()
    )
    if not isolate_auto_confirm:
        return drafts[0] if drafts else None
    for batch in drafts:
        if _batch_line_sources(db, batch.id) <= AUTO_CONFIRM_SOURCES and should_auto_confirm_harvest_batch(db, batch.id):
            return batch
    return None


def run_settlement(db: Session, *, period_key: str | None = None, isolate_auto_confirm: bool = False) -> dict:
    default_key, start, end = current_period(db)
    key = period_key or default_key
    start, end = bounds_for_period_key(key, start, end)
    draft = _select_draft_batch(db, key, isolate_auto_confirm=isolate_auto_confirm)
    confirmed = (
        db.query(SettlementBatch)
        .filter(SettlementBatch.period_key == key, SettlementBatch.status == "confirmed")
        .first()
    )

    snaps = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
            PlatformMetricSnapshot.settled.is_(False),
            PlatformMetricSnapshot.source.in_(tuple(SETTLEMENT_SOURCES)),
            PlatformMetricSnapshot.period_key == key,
        )
        .all()
    )
    if isolate_auto_confirm:
        snaps = [
            row
            for row in snaps
            if row.source in AUTO_CONFIRM_SOURCES and _snapshot_auto_confirmable(row)
        ]
    else:
        blockers = (
            db.query(PlatformMetricSnapshot)
            .filter(
                PlatformMetricSnapshot.usable_for_settlement.is_(True),
                PlatformMetricSnapshot.settled.is_(True),
                PlatformMetricSnapshot.source.in_(tuple(HARVEST_SOURCES)),
                PlatformMetricSnapshot.period_key == key,
            )
            .all()
        )
        snaps = list(snaps) + list(blockers)
    planned = plan_settlement_lines(db, snaps)
    if not planned["lines"] and not draft:
        leftover = _leftover_snaps(db, key)
        return {
            "batch_id": None,
            "period_key": key,
            "lines": 0,
            "status": "empty",
            "needs_confirm": False,
            "reason": "already_confirmed" if confirmed else "no_unsettled_for_period",
            "skipped": planned["skipped"],
            "unsettled_other_periods": summarize_unsettled_periods(leftover),
            "supplemental": False,
        }

    created_batch = draft is None
    batch = draft or SettlementBatch(period_key=key, period_start=start, period_end=end, status="draft")
    if created_batch:
        db.add(batch)
        db.flush()

    existing_snaps, existing_keys = _existing_line_index(db, batch.id)
    created = 0
    for item in planned["lines"]:
        snap = item["snap"]
        key_row = line_dedupe_key(item["user_id"], item["work_id"], item["channel_code"])
        snap_user = (snap.id, item["user_id"])
        if snap_user in existing_snaps or key_row in existing_keys:
            planned["skipped"]["already_in_batch"] += 1
            continue
        line = SettlementLine(
            batch_id=batch.id,
            user_id=item["user_id"],
            work_id=item["work_id"],
            release_id=item["release_id"],
            channel_code=item["channel_code"],
            source=item["source"],
            gross_minor=item["gross_minor"],
            commission_minor=item["commission_minor"],
            net_minor=item["net_minor"],
            commission_rate=item["rate"],
            currency=item["currency"],
            snapshot_id=snap.id,
        )
        try:
            with db.begin_nested():
                db.add(line)
                db.flush()
        except IntegrityError:
            planned["skipped"]["already_in_batch"] += 1
            continue
        existing_snaps.add(snap_user)
        existing_keys.add(key_row)
        wallet = get_or_create_wallet(db, item["user_id"], item["currency"])
        wallet.pending_minor = (wallet.pending_minor or 0) + item["net_minor"]
        from app.services.royalty.subjects import prefixed_ledger_note

        role = item.get("share_role")
        role_bit = f" · {role}" if role and role != "owner" else ""
        add_ledger(
            db,
            user_id=item["user_id"],
            wallet=wallet,
            entry_type="settlement_pending",
            amount_minor=item["net_minor"],
            currency=item["currency"],
            source=item["source"],
            ref_id=str(batch.id),
            note=prefixed_ledger_note(
                f"{item['channel_code']} {key} · {item['rate']}%{role_bit}",
                source=item["source"],
                entry_type="settlement_pending",
            ),
        )
        snap.settled = True
        created += 1

    leftover = _leftover_snaps(db, key)
    if created == 0 and created_batch:
        db.delete(batch)
        db.commit()
        return {
            "batch_id": None,
            "period_key": key,
            "lines": 0,
            "status": "empty",
            "needs_confirm": False,
            "reason": "already_confirmed" if confirmed else "no_unsettled_for_period",
            "skipped": planned["skipped"],
            "unsettled_other_periods": summarize_unsettled_periods(leftover),
            "supplemental": False,
        }
    if created > 0:
        _notify_settlement_draft(db, batch)
    db.commit()
    reason = "pending_confirm" if created else "no_unsettled_for_period"
    if created and confirmed:
        reason = "supplemental_pending_confirm"
    return {
        "batch_id": str(batch.id),
        "period_key": key,
        "lines": created,
        "status": batch.status,
        "needs_confirm": created > 0 or batch.status == "draft",
        "reason": reason,
        "gross_minor": planned["gross_minor"],
        "commission_minor": planned["commission_minor"],
        "net_minor": planned["net_minor"],
        "by_currency": planned["by_currency"],
        "by_rate": planned["by_rate"],
        "skipped": planned["skipped"],
        "unsettled_other_periods": summarize_unsettled_periods(leftover),
        "supplemental": bool(confirmed and created > 0),
    }


def _notify_settlement_draft(db: Session, batch: SettlementBatch) -> None:
    lines = db.query(SettlementLine).filter(SettlementLine.batch_id == batch.id).all()
    by_user: dict[uuid.UUID, list[SettlementLine]] = {}
    for line in lines:
        by_user.setdefault(line.user_id, []).append(line)
    for user_id, user_lines in by_user.items():
        totals: dict[str, int] = {}
        for line in user_lines:
            currency = (line.currency or "CNY").upper()
            totals[currency] = totals.get(currency, 0) + (line.net_minor or 0)
        if not totals:
            continue
        primary_currency, primary_amount = max(totals.items(), key=lambda kv: kv[1])
        create_notification(
            db,
            user_id,
            "settlement_draft",
            {
                "batch_id": str(batch.id),
                "period_key": batch.period_key,
                "amount_minor": primary_amount,
                "currency": primary_currency,
                "amounts": [{"currency": cur, "amount_minor": amt} for cur, amt in totals.items()],
                "message": "本期结算草稿已出，待运营确认后可提现",
            },
        )
        from app.services.notifications import notify_key_event_sync

        notify_key_event_sync(
            db,
            user_id,
            "settlement_draft",
            title="结算草稿已出",
            body="本期结算草稿已出，待运营确认后可提现。不是已到账，也不会自动打款。",
            data={"batch_id": str(batch.id), "ref": str(batch.id)},
            skip_in_app=True,
        )


def _leftover_snaps(db: Session, key: str):
    leftover = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
            PlatformMetricSnapshot.settled.is_(False),
            PlatformMetricSnapshot.source.in_(tuple(SETTLEMENT_SOURCES)),
            PlatformMetricSnapshot.period_key != key,
        )
        .all()
    )
    return filter_settlement_snapshots(leftover)


def confirm_settlement(db: Session, batch_id: str) -> dict:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch id") from exc
    batch = db.query(SettlementBatch).filter(SettlementBatch.id == bid).first()
    if not batch:
        raise HTTPException(404, "Settlement batch not found")
    gate = confirmable_status(batch.status)
    if gate == "already":
        return {"batch_id": str(batch.id), "status": "confirmed", "reason": "already_confirmed"}
    if gate != "ok":
        raise HTTPException(400, f"Cannot confirm settlement in status {batch.status}")
    lines = db.query(SettlementLine).filter(SettlementLine.batch_id == batch.id).all()
    if not lines:
        raise HTTPException(400, "Empty draft cannot be confirmed")
    by_user: dict[uuid.UUID, list[SettlementLine]] = {}
    for line in lines:
        by_user.setdefault(line.user_id, []).append(line)
    platform_take: dict[str, dict] = {}
    for user_id, user_lines in by_user.items():
        totals: dict[str, int] = {}
        for line in user_lines:
            currency = (line.currency or "CNY").upper()
            totals[currency] = totals.get(currency, 0) + (line.net_minor or 0)
            _add_money(
                platform_take,
                currency,
                gross=line.gross_minor or 0,
                commission=line.commission_minor or 0,
                net=line.net_minor or 0,
            )
        for currency, amount in totals.items():
            wallet = get_or_create_wallet(db, user_id, currency)
            wallet.pending_minor = max(0, (wallet.pending_minor or 0) - amount)
            wallet.available_minor = (wallet.available_minor or 0) + amount
            wallet.lifetime_earned_minor = (wallet.lifetime_earned_minor or 0) + amount
            from app.services.royalty.subjects import prefixed_ledger_note

            add_ledger(
                db,
                user_id=user_id,
                wallet=wallet,
                entry_type="settlement_available",
                amount_minor=amount,
                currency=currency,
                source=user_lines[0].source if user_lines else None,
                ref_id=str(batch.id),
                note=prefixed_ledger_note(
                    "结算确认，转入可提现",
                    source=user_lines[0].source if user_lines else None,
                    entry_type="settlement_available",
                ),
            )
        primary_currency, primary_amount = max(totals.items(), key=lambda kv: kv[1]) if totals else ("CNY", 0)
        from app.services.royalty.payout_calendar import statement_receipt_no

        create_notification(
            db,
            user_id,
            "settlement_ready",
            {
                "batch_id": str(batch.id),
                "period_key": batch.period_key,
                "amount_minor": primary_amount,
                "currency": primary_currency,
                "receipt_no": statement_receipt_no(user_id, batch.period_key),
                "amounts": [{"currency": cur, "amount_minor": amt} for cur, amt in totals.items()],
                "message": "本期结算已入账，可申请提现",
            },
        )
        from app.services.notifications import notify_key_event_sync

        notify_key_event_sync(
            db,
            user_id,
            "settlement_ready",
            title="结算已入账",
            body="有金额的收割已进法币钱包，可申请提现。额度与电台数字不变。",
            data={"batch_id": str(batch.id), "ref": str(batch.id)},
            skip_in_app=True,
        )
    batch.status = "confirmed"
    batch.confirmed_at = datetime.utcnow()
    snap_ids = [line.snapshot_id for line in lines if line.snapshot_id]
    if snap_ids:
        snaps = {
            row.id: row
            for row in db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.id.in_(snap_ids)).all()
        }
        for line in lines:
            snap = snaps.get(line.snapshot_id) if line.snapshot_id else None
            if not snap:
                continue
            raw = dict(snap.raw or {})
            raw["settled_revenue_minor"] = int(snap.revenue_minor or 0)
            if line.commission_rate in ALLOWED_RATES:
                raw["settled_commission_rate"] = int(line.commission_rate)
            snap.raw = raw
    db.commit()
    return {
        "batch_id": str(batch.id),
        "status": "confirmed",
        "users": len(by_user),
        "platform_take": list(platform_take.values()),
    }


def write_harvest_adjustment(db: Session, snap: PlatformMetricSnapshot, new_revenue: int) -> dict | None:
    """Claw back each split share when a later harvest is lower. Keep the period; do not void."""
    from app.services.royalty.splits import expand_split_lines
    from app.services.royalty.subjects import prefixed_ledger_note

    raw = dict(snap.raw or {})
    already = int(raw.get("settled_revenue_minor") or 0)
    delta = int(new_revenue) - already
    if delta >= 0 or not snap.user_id:
        return None
    work = db.query(Work).filter(Work.id == snap.work_id).first() if snap.work_id else None
    user = db.query(User).filter(User.id == snap.user_id).first()
    release = resolve_release_for_snap(db, snap)
    rate = locked_or_resolve_rate(db, snap, release, user) or 20
    commission, net = split_amounts(abs(delta), rate)
    parts = expand_split_lines(db, snap.work_id, snap.user_id, abs(delta), commission, net)
    _, fallback_start, fallback_end = current_period(db)
    start, end = bounds_for_period_key(snap.period_key, fallback_start, fallback_end)
    batch = SettlementBatch(
        period_key=snap.period_key,
        period_start=start,
        period_end=end,
        status="confirmed",
        confirmed_at=datetime.utcnow(),
    )
    db.add(batch)
    db.flush()
    currency = (snap.currency or "CNY").upper()
    clawback_net = 0
    for part in parts:
        part_net = -int(part["net_minor"] or 0)
        clawback_net += part_net
        db.add(
            SettlementLine(
                batch_id=batch.id,
                user_id=part["user_id"],
                work_id=snap.work_id,
                release_id=release.id if release else snap.release_id,
                channel_code=snap.channel_code,
                source=snap.source,
                gross_minor=-int(part["gross_minor"] or 0),
                commission_minor=-int(part["commission_minor"] or 0),
                net_minor=part_net,
                commission_rate=rate,
                currency=currency,
                snapshot_id=snap.id,
            )
        )
        wallet = get_or_create_wallet(db, part["user_id"], currency)
        wallet.available_minor = max(0, (wallet.available_minor or 0) + part_net)
        wallet.lifetime_earned_minor = max(0, (wallet.lifetime_earned_minor or 0) + part_net)
        add_ledger(
            db,
            user_id=part["user_id"],
            wallet=wallet,
            entry_type="harvest_adjustment",
            amount_minor=part_net,
            currency=currency,
            source=snap.source,
            ref_id=str(batch.id),
            note=prefixed_ledger_note("收割下调，冲回多结", source=snap.source, entry_type="harvest_adjustment"),
        )
    raw["settled_revenue_minor"] = int(new_revenue)
    raw["settled_commission_rate"] = rate
    raw["last_adjustment_minor"] = clawback_net
    snap.raw = raw
    snap.revenue_minor = int(new_revenue)
    snap.settled = True
    return {
        "adjusted": True,
        "batch_id": str(batch.id),
        "delta_revenue": delta,
        "net_minor": clawback_net,
        "work_id": str(work.id) if work else None,
    }


def should_auto_confirm_harvest_batch(db: Session, batch_id) -> bool:
    try:
        bid = batch_id if isinstance(batch_id, uuid.UUID) else uuid.UUID(str(batch_id))
    except (TypeError, ValueError):
        return False
    batch = db.query(SettlementBatch).filter(SettlementBatch.id == bid).first()
    if not batch or batch.status != "draft":
        return False
    lines = db.query(SettlementLine).filter(SettlementLine.batch_id == batch.id).all()
    if not lines:
        return False
    from app.models.schemas import PlatformMetricSnapshot
    from app.services.distribution.automation import AUTO_CONFIRM_MAX_NET_MINOR, AUTO_CONFIRM_MIN_CONFIDENCE
    from app.services.royalty.subjects import AUTO_CONFIRM_SOURCES, HARVEST_AUTO_CONFIRM_SOURCES

    for line in lines:
        if (line.net_minor or 0) > AUTO_CONFIRM_MAX_NET_MINOR:
            return False
        if line.source not in AUTO_CONFIRM_SOURCES:
            return False
        if line.source not in HARVEST_AUTO_CONFIRM_SOURCES:
            continue
        snap = None
        if line.snapshot_id:
            snap = db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.id == line.snapshot_id).first()
        if snap is None and line.work_id:
            snap = (
                db.query(PlatformMetricSnapshot)
                .filter(
                    PlatformMetricSnapshot.user_id == line.user_id,
                    PlatformMetricSnapshot.work_id == line.work_id,
                    PlatformMetricSnapshot.channel_code == line.channel_code,
                    PlatformMetricSnapshot.source == line.source,
                )
                .order_by(PlatformMetricSnapshot.created_at.desc())
                .first()
            )
        if snap is None or _snapshot_confidence(snap) < AUTO_CONFIRM_MIN_CONFIDENCE:
            return False
    return True


def void_settlement(db: Session, batch_id: str) -> dict:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch id") from exc
    batch = db.query(SettlementBatch).filter(SettlementBatch.id == bid).first()
    if not batch:
        raise HTTPException(404, "Settlement batch not found")
    if batch.status != "draft":
        raise HTTPException(400, "Only draft batches can be voided")
    lines = db.query(SettlementLine).filter(SettlementLine.batch_id == batch.id).all()
    snap_ids = [line.snapshot_id for line in lines if line.snapshot_id]
    snaps = {
        s.id: s
        for s in db.query(PlatformMetricSnapshot).filter(PlatformMetricSnapshot.id.in_(snap_ids)).all()
    } if snap_ids else {}
    by_wallet: dict[tuple, int] = {}
    for line in lines:
        by_wallet[(line.user_id, (line.currency or "CNY").upper())] = (
            by_wallet.get((line.user_id, (line.currency or "CNY").upper()), 0) + (line.net_minor or 0)
        )
        snap = snaps.get(line.snapshot_id) if line.snapshot_id else None
        if snap:
            snap.settled = False
    for (user_id, currency), amount in by_wallet.items():
        wallet = get_or_create_wallet(db, user_id, currency)
        wallet.pending_minor = max(0, (wallet.pending_minor or 0) - amount)
        add_ledger(
            db,
            user_id=user_id,
            wallet=wallet,
            entry_type="settlement_void",
            amount_minor=-amount,
            currency=currency,
            ref_id=str(batch.id),
            note="草稿结算作废，退回待结算",
        )
    batch.status = "voided"
    db.commit()
    return {"batch_id": str(batch.id), "status": "voided", "lines": len(lines)}


def _line_subject(source: str | None) -> str:
    from app.services.royalty.subjects import accounting_subject

    return accounting_subject(source)


def _share_roles(lines: list[SettlementLine]) -> dict[tuple, str]:
    from sqlalchemy.orm import object_session

    from app.models.schemas import WorkSplitShare

    work_ids = {line.work_id for line in lines if line.work_id}
    if not work_ids or not lines:
        return {}
    db = object_session(lines[0])
    if db is None:
        return {}
    rows = db.query(WorkSplitShare).filter(WorkSplitShare.work_id.in_(work_ids)).all()
    return {(row.work_id, row.user_id): row.role for row in rows}


def _serialize_user_batch(
    batch: SettlementBatch | None,
    lines: list[SettlementLine],
    works: dict,
    share_roles: dict | None = None,
) -> dict:
    share_roles = share_roles if share_roles is not None else _share_roles(lines)
    grouped = {
        "batch_id": str(lines[0].batch_id) if lines else None,
        "period_key": batch.period_key if batch else None,
        "status": batch.status if batch else "draft",
        "withdrawable": (batch.status if batch else "draft") == "confirmed",
        "lines": [],
        "gross_minor": 0,
        "commission_minor": 0,
        "net_minor": 0,
        "currency": (lines[0].currency if lines else "CNY") or "CNY",
        "by_currency": {},
        "by_rate": {},
        "mixed_currency": False,
    }
    for line in lines:
        work = works.get(line.work_id) if line.work_id else None
        gross = line.gross_minor or 0
        commission = line.commission_minor or 0
        rate = _effective_rate(line)
        currency = (line.currency or "CNY").upper()
        grouped["lines"].append(
            {
                "work_id": str(line.work_id) if line.work_id else None,
                "work_title": work.title if work else None,
                "channel_code": line.channel_code,
                "source": line.source,
                "accounting_subject": _line_subject(line.source),
                "share_role": (share_roles or {}).get((line.work_id, line.user_id)),
                "gross_minor": gross,
                "commission_minor": commission,
                "commission_rate": rate,
                "net_minor": line.net_minor,
                "currency": currency,
            }
        )
        grouped["gross_minor"] += gross
        grouped["commission_minor"] += commission
        grouped["net_minor"] += line.net_minor
        _add_money(grouped["by_currency"], currency, gross=gross, commission=commission, net=line.net_minor)
        rate_row = grouped["by_rate"].setdefault(
            rate, {"rate": rate, "count": 0, "gross_minor": 0, "commission_minor": 0, "net_minor": 0}
        )
        rate_row["count"] += 1
        rate_row["gross_minor"] += gross
        rate_row["commission_minor"] += commission
        rate_row["net_minor"] += line.net_minor
    grouped["by_currency"] = list(grouped["by_currency"].values())
    grouped["by_rate"] = sorted(grouped["by_rate"].values(), key=lambda item: item["rate"])
    grouped["mixed_currency"] = len(grouped["by_currency"]) > 1
    if len(grouped["by_currency"]) == 1:
        grouped["currency"] = grouped["by_currency"][0]["currency"]
    return grouped


def list_user_settlements(db: Session, user: User, period_key: str | None = None) -> list[dict]:
    lines = (
        db.query(SettlementLine)
        .filter(SettlementLine.user_id == user.id)
        .order_by(SettlementLine.id.desc())
        .limit(200)
        .all()
    )
    batch_ids = {line.batch_id for line in lines}
    work_ids = {line.work_id for line in lines if line.work_id}
    batches = {
        b.id: b
        for b in db.query(SettlementBatch).filter(SettlementBatch.id.in_(batch_ids)).all()
    } if batch_ids else {}
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    grouped: dict[str, list[SettlementLine]] = {}
    for line in lines:
        batch = batches.get(line.batch_id)
        if batch and batch.status == "voided":
            continue
        grouped.setdefault(str(line.batch_id), []).append(line)
    rows = [_serialize_user_batch(batches.get(uuid.UUID(key)), items, works) for key, items in grouped.items()]
    if period_key:
        rows = [row for row in rows if row.get("period_key") == period_key]
    return rows


def get_user_settlement(db: Session, user: User, batch_id: str) -> dict:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch id") from exc
    lines = (
        db.query(SettlementLine)
        .filter(SettlementLine.batch_id == bid, SettlementLine.user_id == user.id)
        .all()
    )
    if not lines:
        raise HTTPException(404, "Settlement batch not found")
    batch = db.query(SettlementBatch).filter(SettlementBatch.id == bid).first()
    work_ids = {line.work_id for line in lines if line.work_id}
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    return _serialize_user_batch(batch, lines, works)


def render_statement_csv(batches: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["period", "status", "work", "channel", "source", "rate_percent", "currency", "gross_minor", "commission_minor", "net_minor"]
    )
    for batch in batches:
        for line in batch.get("lines") or []:
            writer.writerow(
                [
                    batch.get("period_key") or "",
                    batch.get("status") or "",
                    line.get("work_title") or "",
                    line.get("channel_code") or "",
                    line.get("source") or "",
                    line.get("commission_rate") or "",
                    line.get("currency") or "CNY",
                    line.get("gross_minor") or 0,
                    line.get("commission_minor") or 0,
                    line.get("net_minor") or 0,
                ]
            )
    return buf.getvalue()


def _statement_source_split(batches: list[dict]) -> dict:
    from app.services.distribution.catalog import HARVEST_SOURCES
    from app.services.royalty.subjects import money_bucket

    radio = sync = embed = dsp = harvest = 0
    for batch in batches:
        for line in batch.get("lines") or []:
            net = int(line.get("net_minor") or 0)
            source = line.get("source") or ""
            bucket = money_bucket(source)
            if bucket == "radio":
                radio += net
            elif bucket == "sync":
                sync += net
            elif bucket == "embed":
                embed += net
            elif bucket == "dsp":
                dsp += net
                if source in HARVEST_SOURCES:
                    harvest += net
    return {
        "radio_minor": radio,
        "sync_minor": sync,
        "embed_minor": embed,
        "dsp_minor": dsp,
        "harvest_minor": harvest,
        "net_minor": radio + sync + embed + dsp,
        "note": "电台预热是站内科目；席位收割是厂牌版税主路。积分打赏不在此列。",
    }


def _fen_yuan(minor: int, currency: str = "CNY") -> str:
    symbol = "$" if (currency or "CNY").upper() == "USD" else "¥"
    return f"{symbol}{int(minor or 0) / 100:.2f}"


def render_statement_receipt(
    *,
    receipt_no: str,
    period_key: str | None,
    by_currency: list[dict],
    source_split: dict,
    next_payout_date: str | None,
) -> str:
    lines = [
        "比特音对账单 / Vibe Sorcery statement",
        f"回单号 {receipt_no}",
        f"账期 {period_key or '全部'}",
        "--------------------------------",
        "发现预热（不可提现，不进合计）",
        f"  电台预热 { _fen_yuan(source_split.get('radio_minor') or 0) }",
        "--------------------------------",
        "可结算法币净额（不含积分打赏、不含电台预热）",
        f"  同步授权 { _fen_yuan(source_split.get('sync_minor') or 0) }",
        f"  嵌入完播 { _fen_yuan(source_split.get('embed_minor') or 0) }",
        f"  厂牌版税 { _fen_yuan(source_split.get('dsp_minor') or 0) }",
        f"  其中席位收割 { _fen_yuan(source_split.get('harvest_minor') or 0) }",
    ]
    for row in by_currency:
        currency = (row.get("currency") or "CNY").upper()
        lines.append(
            f"  合计 {currency} 毛 {_fen_yuan(row.get('gross_minor') or 0, currency)} / "
            f"抽成 {_fen_yuan(row.get('commission_minor') or 0, currency)} / "
            f"净 {_fen_yuan(row.get('net_minor') or 0, currency)}"
        )
    if next_payout_date:
        lines.append(f"下个打款日 {next_payout_date}（周五）")
    lines.append("积分钱包不在此列。未确认批次不可提现。")
    return "\n".join(lines)


def export_user_statement(db: Session, user: User, period_key: str | None = None) -> dict:
    from app.services.royalty.payout_calendar import payout_calendar, statement_receipt_no

    batches = list_user_settlements(db, user, period_key=period_key)
    by_currency: dict[str, dict] = {}
    for batch in batches:
        for row in batch.get("by_currency") or []:
            _add_money(
                by_currency,
                row["currency"],
                gross=row.get("gross_minor") or 0,
                commission=row.get("commission_minor") or 0,
                net=row.get("net_minor") or 0,
            )
    stamp = period_key or "all"
    split = _statement_source_split(batches)
    calendar = payout_calendar()
    receipt_no = statement_receipt_no(user.id, period_key)
    currency_rows = list(by_currency.values())
    receipt_text = render_statement_receipt(
        receipt_no=receipt_no,
        period_key=period_key,
        by_currency=currency_rows,
        source_split=split,
        next_payout_date=calendar.get("next_payout_date"),
    )
    return {
        "filename": f"vibe-statement-{stamp}.csv",
        "csv": render_statement_csv(batches),
        "receipt_text": receipt_text,
        "receipt_no": receipt_no,
        "period_key": period_key,
        "batches": len(batches),
        "by_currency": currency_rows,
        "source_split": split,
        "next_payout_date": calendar.get("next_payout_date"),
        "days_until_payout": calendar.get("days_until_payout"),
        "credits_excluded": True,
        "note": "本对账单只含可结算法币净额。积分打赏不在此列。",
    }


def _batch_aggregates(db: Session, ids: list) -> dict:
    from sqlalchemy import func

    if not ids:
        return {}
    totals = {
        bid: {
            "gross_minor": int(gross or 0),
            "commission_minor": int(commission or 0),
            "net_minor": int(net or 0),
            "line_count": int(cnt or 0),
            "user_count": int(users or 0),
            "by_currency": [],
        }
        for bid, gross, commission, net, cnt, users in (
            db.query(
                SettlementLine.batch_id,
                func.coalesce(func.sum(SettlementLine.gross_minor), 0),
                func.coalesce(func.sum(SettlementLine.commission_minor), 0),
                func.coalesce(func.sum(SettlementLine.net_minor), 0),
                func.count(SettlementLine.id),
                func.count(func.distinct(SettlementLine.user_id)),
            )
            .filter(SettlementLine.batch_id.in_(ids))
            .group_by(SettlementLine.batch_id)
            .all()
        )
    }
    currency_rows = (
        db.query(
            SettlementLine.batch_id,
            SettlementLine.currency,
            func.coalesce(func.sum(SettlementLine.gross_minor), 0),
            func.coalesce(func.sum(SettlementLine.commission_minor), 0),
            func.coalesce(func.sum(SettlementLine.net_minor), 0),
        )
        .filter(SettlementLine.batch_id.in_(ids))
        .group_by(SettlementLine.batch_id, SettlementLine.currency)
        .all()
    )
    for bid, currency, gross, commission, net in currency_rows:
        row = totals.setdefault(
            bid,
            {"gross_minor": 0, "commission_minor": 0, "net_minor": 0, "line_count": 0, "user_count": 0, "by_currency": []},
        )
        row["by_currency"].append(
            {
                "currency": (currency or "CNY").upper(),
                "gross_minor": int(gross or 0),
                "commission_minor": int(commission or 0),
                "net_minor": int(net or 0),
            }
        )
    return totals


def list_batches(db: Session) -> list[dict]:
    rows = db.query(SettlementBatch).order_by(SettlementBatch.created_at.desc()).limit(50).all()
    if not rows:
        return []
    ids = [b.id for b in rows]
    agg = _batch_aggregates(db, ids)
    return [
        {
            "id": str(b.id),
            "batch_id": str(b.id),
            "period_key": b.period_key,
            "status": b.status,
            "gross_minor": agg.get(b.id, {}).get("gross_minor", 0),
            "commission_minor": agg.get(b.id, {}).get("commission_minor", 0),
            "net_minor": agg.get(b.id, {}).get("net_minor", 0),
            "platform_take_minor": agg.get(b.id, {}).get("commission_minor", 0),
            "line_count": agg.get(b.id, {}).get("line_count", 0),
            "user_count": agg.get(b.id, {}).get("user_count", 0),
            "by_currency": agg.get(b.id, {}).get("by_currency", []),
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "confirmed_at": b.confirmed_at.isoformat() if b.confirmed_at else None,
        }
        for b in rows
    ]


def get_batch_detail(db: Session, batch_id: str) -> dict:
    try:
        bid = uuid.UUID(batch_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch id") from exc
    batch = db.query(SettlementBatch).filter(SettlementBatch.id == bid).first()
    if not batch:
        raise HTTPException(404, "Settlement batch not found")
    lines = db.query(SettlementLine).filter(SettlementLine.batch_id == batch.id).all()
    user_ids = {line.user_id for line in lines}
    work_ids = {line.work_id for line in lines if line.work_id}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    by_currency: dict[str, dict] = {}
    by_rate: dict[int, dict] = {}
    by_user: dict[str, dict] = {}
    serialized = []
    roles = _share_roles(lines)
    for line in lines:
        user = users.get(line.user_id)
        work = works.get(line.work_id) if line.work_id else None
        rate = _effective_rate(line)
        currency = (line.currency or "CNY").upper()
        gross = line.gross_minor or 0
        commission = line.commission_minor or 0
        net = line.net_minor or 0
        serialized.append(
            {
                "id": str(line.id),
                "user_id": str(line.user_id),
                "user_email": user.email if user else None,
                "user_username": user.username if user else None,
                "work_id": str(line.work_id) if line.work_id else None,
                "work_title": work.title if work else None,
                "channel_code": line.channel_code,
                "source": line.source,
                "accounting_subject": _line_subject(line.source),
                "share_role": roles.get((line.work_id, line.user_id)) if line.work_id else None,
                "commission_rate": rate,
                "currency": currency,
                "gross_minor": gross,
                "commission_minor": commission,
                "net_minor": net,
            }
        )
        _add_money(by_currency, currency, gross=gross, commission=commission, net=net)
        rate_row = by_rate.setdefault(rate, {"rate": rate, "count": 0, "gross_minor": 0, "commission_minor": 0, "net_minor": 0})
        rate_row["count"] += 1
        rate_row["gross_minor"] += gross
        rate_row["commission_minor"] += commission
        rate_row["net_minor"] += net
        uid = str(line.user_id)
        user_row = by_user.setdefault(
            uid,
            {
                "user_id": uid,
                "user_email": user.email if user else None,
                "user_username": user.username if user else None,
                "line_count": 0,
                "gross_minor": 0,
                "commission_minor": 0,
                "net_minor": 0,
                "by_currency": {},
            },
        )
        user_row["line_count"] += 1
        user_row["gross_minor"] += gross
        user_row["commission_minor"] += commission
        user_row["net_minor"] += net
        _add_money(user_row["by_currency"], currency, gross=gross, commission=commission, net=net)
    for row in by_user.values():
        row["by_currency"] = list(row["by_currency"].values())
    return {
        "id": str(batch.id),
        "batch_id": str(batch.id),
        "period_key": batch.period_key,
        "status": batch.status,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "confirmed_at": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        "line_count": len(serialized),
        "user_count": len(by_user),
        "gross_minor": sum(row["gross_minor"] for row in by_currency.values()),
        "commission_minor": sum(row["commission_minor"] for row in by_currency.values()),
        "net_minor": sum(row["net_minor"] for row in by_currency.values()),
        "platform_take": list(by_currency.values()),
        "by_currency": list(by_currency.values()),
        "by_rate": sorted(by_rate.values(), key=lambda item: item["rate"]),
        "by_user": list(by_user.values()),
        "lines": serialized,
    }
