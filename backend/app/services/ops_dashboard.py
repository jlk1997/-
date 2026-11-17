"""Ops daily dashboard — all actionable queues in one view."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.schemas import (
    CreatorSeat,
    DistributionDelivery,
    SeatJob,
    User,
)

logger = logging.getLogger(__name__)


def count_unmatched_claims(db: Session) -> int:
    """Count unmatched connector claims."""
    try:
        from app.models.schemas import ConnectorClaim
        return db.query(func.count(ConnectorClaim.id)).filter(ConnectorClaim.status == "unmatched").scalar() or 0
    except Exception:
        return 0


def ops_daily_digest(db: Session) -> dict[str, Any]:
    """One-screen actionable digest for ops team."""
    now = datetime.utcnow()

    # 1. Unmatched harvest rows (connector claims + harvest_unmatched + unattached snapshots)
    try:
        unmatched = count_unmatched_claims(db)
    except Exception:
        unmatched = 0
    try:
        from app.services.harvest.unmatched import count_unmatched

        harvest_unmatched = int(count_unmatched(db, admin=True) or 0)
    except Exception:
        harvest_unmatched = 0
    try:
        from app.models.schemas import PlatformMetricSnapshot

        unattached_snapshots = (
            db.query(func.count(PlatformMetricSnapshot.id))
            .filter(PlatformMetricSnapshot.work_id.is_(None))
            .scalar()
            or 0
        )
    except Exception:
        unattached_snapshots = 0

    # 2. Selector broke seats
    selector_broke = (
        db.query(func.count(SeatJob.id))
        .filter(SeatJob.status == "failed", SeatJob.result.cast(str).contains("selector_broke"))
        .scalar() or 0
    )

    # 3. Login wall seats
    login_wall = (
        db.query(func.count(CreatorSeat.id))
        .filter(CreatorSeat.status == "needs_challenge")
        .scalar() or 0
    )

    # 4. SLA overdue deliveries (session_wait/session_running/ops_queue > 48h)
    sla_cutoff = now - timedelta(hours=48)
    sla_overdue = (
        db.query(func.count(DistributionDelivery.id))
        .filter(
            DistributionDelivery.status.in_(["session_wait", "session_running", "ops_queue"]),
            DistributionDelivery.updated_at < sla_cutoff,
        )
        .scalar() or 0
    )
    from app.services.distribution.assist import count_stale_session_jobs

    session_expired = count_stale_session_jobs(db, now=now)
    harvest_failed = (
        db.query(func.count(SeatJob.id))
        .filter(SeatJob.kind == "harvest", SeatJob.status == "failed")
        .scalar() or 0
    )
    patrol_failed = 0
    for seat in db.query(CreatorSeat).filter(CreatorSeat.ownership == "platform").all():
        extra = seat.extra if isinstance(seat.extra, dict) else {}
        health = extra.get("farm_health") if isinstance(extra.get("farm_health"), dict) else {}
        if extra.get("patrol_error") or health.get("error") or health.get("ok") is False:
            patrol_failed += 1

    # 5. Pending payouts
    try:
        from app.models.schemas import Withdrawal

        pending_payouts = (
            db.query(func.count(Withdrawal.id))
            .filter(Withdrawal.status == "pending")
            .scalar() or 0
        )
    except Exception:
        pending_payouts = 0

    # 6. Pending KYC
    pending_kyc = (
        db.query(func.count(User.id))
        .filter(User.kyc_status == "pending")
        .scalar() or 0
    )

    # 6b. Money that only moves when a human acts: draft settlements ops must confirm,
    # bank transfers ops must reconcile. None of this is ever auto-paid.
    try:
        from app.models.schemas import SettlementBatch

        settlement_drafts = (
            db.query(func.count(SettlementBatch.id))
            .filter(SettlementBatch.status == "draft")
            .scalar() or 0
        )
    except Exception:
        settlement_drafts = 0
    try:
        from app.models.schemas import SyncLicenseOrder

        pending_invoices = (
            db.query(func.count(SyncLicenseOrder.id))
            .filter(SyncLicenseOrder.status == "pending_invoice")
            .scalar() or 0
        )
    except Exception:
        pending_invoices = 0

    # 7. Delivery queue breakdown
    delivery_queue = (
        db.query(DistributionDelivery.status, func.count(DistributionDelivery.id))
        .filter(DistributionDelivery.status.in_(["ops_queue", "awaiting_manual", "session_wait", "session_running"]))
        .group_by(DistributionDelivery.status)
        .all()
    )

    actionable = {
        "unmatched_claims": int(unmatched),
        "harvest_unmatched": int(harvest_unmatched),
        "unattached_snapshots": int(unattached_snapshots),
        "selector_broke": int(selector_broke),
        "login_wall_seats": int(login_wall),
        "sla_overdue": int(sla_overdue),
        "session_expired": int(session_expired),
        "harvest_failed": int(harvest_failed),
        "patrol_failed": int(patrol_failed),
        "pending_payouts": int(pending_payouts),
        "pending_kyc": int(pending_kyc),
        "settlement_drafts": int(settlement_drafts),
        "pending_invoices": int(pending_invoices),
    }
    total_actionable = int(sum(actionable.values()))
    if total_actionable > 0:
        from app.services.alerting import alert

        alert(
            "ops_daily_digest",
            f"运营日清还有 {total_actionable} 条待处理",
            severity="warning" if total_actionable < 20 else "error",
            context=actionable,
            dedupe_key=now.strftime("%Y-%m-%d"),
            dedupe_seconds=20 * 3600,
        )
    # Friday is an application day, not a payout day: every row below waits on a person.
    friday_queue = {
        "settlement_drafts": int(settlement_drafts),
        "pending_invoices": int(pending_invoices),
        "pending_kyc": int(pending_kyc),
        "pending_payouts": int(pending_payouts),
        "auto_payout": False,
    }
    return {
        "timestamp": now.isoformat(),
        "actionable": actionable,
        "delivery_queue": {str(status): int(count) for status, count in delivery_queue},
        "total_actionable": total_actionable,
        "friday_queue": friday_queue,
        "friday_total": int(settlement_drafts + pending_invoices + pending_kyc + pending_payouts),
    }
