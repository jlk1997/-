"""Ops maturity: SLA snapshot, monthly money tie-out, what we keep."""

from __future__ import annotations

from datetime import datetime, timedelta

RETAIN_RELEASE_PACK_DAYS = 365 * 3
RETAIN_AUDIT_DAYS = 365 * 2


def sla_snapshot(rows: list[dict], *, now: datetime | None = None, hours: int = 48) -> dict:
    now = now or datetime.utcnow()
    overdue = []
    waiting_receipt = 0
    for row in rows:
        status = str(row.get("status") or "")
        if status in {"ops_queue", "awaiting_manual", "session_wait"} and not row.get("store_url"):
            waiting_receipt += 1
        stamp = row.get("created_at")
        if isinstance(stamp, datetime) and status in {"ops_queue", "awaiting_manual"} and stamp <= now - timedelta(hours=hours):
            overdue.append(str(row.get("id") or ""))
    return {
        "waiting_receipt": waiting_receipt,
        "overdue_ids": overdue,
        "overdue_count": len(overdue),
        "sla_hours": hours,
    }


def reconciliation_row(*, user_id: str, available_minor: int, pending_minor: int, ledger_net_minor: int, withdrawal_paid_minor: int) -> dict:
    expected = int(ledger_net_minor) - int(withdrawal_paid_minor)
    held = int(available_minor) + int(pending_minor)
    return {
        "user_id": user_id,
        "available_minor": int(available_minor),
        "pending_minor": int(pending_minor),
        "ties": held == expected,
        "delta_minor": held - expected,
    }


def sla_alert(rows: list[dict], *, now: datetime | None = None, hours: int = 48) -> dict:
    snap = sla_snapshot(rows, now=now, hours=hours)
    count = int(snap["overdue_count"])
    return {
        **snap,
        "alert": count > 0,
        "message": f"{count} 单超过 {hours} 小时还没有商店页回执" if count else "",
    }


def wallet_tie(
    *,
    user_id: str,
    available_minor: int,
    pending_minor: int,
    frozen_minor: int,
    lifetime_earned_minor: int,
    paid_minor: int,
) -> dict:
    held = int(available_minor) + int(pending_minor) + int(frozen_minor)
    expected = int(lifetime_earned_minor) - int(paid_minor)
    return {
        "user_id": user_id,
        "held_minor": held,
        "expected_minor": expected,
        "ties": held == expected,
        "delta_minor": held - expected,
        "payout": "paid_manual",
    }


def retention_policy() -> dict:
    return {
        "release_pack_days": RETAIN_RELEASE_PACK_DAYS,
        "audit_days": RETAIN_AUDIT_DAYS,
        "deletes_money_records": False,
    }
