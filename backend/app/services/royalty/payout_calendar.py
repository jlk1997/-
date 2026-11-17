"""Weekly payout day helpers. Bank-like receipts, not a new money pool."""

from __future__ import annotations

from datetime import date, datetime, timedelta

PAYOUT_WEEKDAY = 4  # Friday
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def expected_harvest_window(today: date | None = None) -> dict:
    """Seat harvest can settle the same day or next day. Not T+45."""
    today = today or datetime.utcnow().date()
    return {
        "earliest": today.isoformat(),
        "latest": (today + timedelta(days=1)).isoformat(),
        "weeks_min": 0,
        "weeks_max": 1,
        "waiting": False,
        "mode": "seat_harvest",
    }


def expected_statement_window(live_on: date | None = None, today: date | None = None) -> dict:
    """Ops side path only. Official CSV/API windows are T+45–T+90 after first live."""
    today = today or datetime.utcnow().date()
    start = live_on or today
    earliest = start + timedelta(days=45)
    latest = start + timedelta(days=90)
    return {
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "weeks_min": 6,
        "weeks_max": 13,
        "waiting": today < earliest,
    }


def next_payout_date(today: date | None = None) -> date:
    today = today or datetime.utcnow().date()
    delta = (PAYOUT_WEEKDAY - today.weekday()) % 7
    return today + timedelta(days=delta)


def days_until_payout(today: date | None = None) -> int:
    today = today or datetime.utcnow().date()
    return (next_payout_date(today) - today).days


def statement_receipt_no(user_id, period_key: str | None = None) -> str:
    stamp = (period_key or "ALL").replace("-", "").replace("/", "")[:12].upper() or "ALL"
    short = str(user_id or "").replace("-", "")[:8].upper() or "XXXXXXXX"
    return f"VS-S-{stamp}-{short}"


def receipt_no_for(withdrawal) -> str:
    stored = getattr(withdrawal, "receipt_no", None)
    if stored:
        return str(stored)
    created = getattr(withdrawal, "created_at", None) or datetime.utcnow()
    day = created.strftime("%Y%m%d")
    short = str(getattr(withdrawal, "id", "") or "xxxxxxxx").replace("-", "")[:8].upper()
    return f"VS-W-{day}-{short}"


def payout_calendar(*, period: str = "weekly", today: date | None = None) -> dict:
    today = today or datetime.utcnow().date()
    nxt = next_payout_date(today)
    days = (nxt - today).days
    return {
        "period": period or "weekly",
        "weekday": PAYOUT_WEEKDAY,
        "weekday_label": WEEKDAY_LABELS[PAYOUT_WEEKDAY],
        "next_payout_date": nxt.isoformat(),
        "days_until_payout": days,
        "is_payout_day": days == 0,
        "note": "每周五为申请提现日。系统不会自动打款；财务打款后再人工标已付。额度不能提现。",
    }


def send_payout_day_nudges(db, *, today: date | None = None, limit: int = 400) -> dict:
    """Remind creators with available fiat to request a withdrawal. Never auto-pays."""
    from app.models.schemas import Notification, RoyaltyWallet
    from app.services.notifications import create_notification

    cal = payout_calendar(today=today)
    if not cal.get("is_payout_day"):
        return {"sent": 0, "skipped": "not_payout_day", "next_payout_date": cal.get("next_payout_date")}

    today = today or datetime.utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    wallets = db.query(RoyaltyWallet).filter(RoyaltyWallet.available_minor > 0).all()
    best: dict = {}
    for wallet in wallets:
        prev = best.get(wallet.user_id)
        if not prev or (wallet.available_minor or 0) > (prev.available_minor or 0):
            best[wallet.user_id] = wallet

    sent = 0
    for user_id, wallet in best.items():
        if sent >= limit:
            break
        exists = (
            db.query(Notification.id)
            .filter(
                Notification.user_id == user_id,
                Notification.type == "payout_day",
                Notification.created_at >= start,
            )
            .first()
        )
        if exists:
            continue
        create_notification(
            db,
            user_id,
            "payout_day",
            {
                "next_payout_date": cal["next_payout_date"],
                "available_minor": int(wallet.available_minor or 0),
                "currency": wallet.currency,
                "is_payout_day": True,
                "manual_payout": True,
                "message": "今天周五申请日。请手动申请提现；财务打款后才会标已付，系统不会自动汇出。",
            },
            commit=False,
        )
        from app.services.notifications import notify_key_event_sync

        notify_key_event_sync(
            db,
            user_id,
            "payout_day",
            title="周五申请日",
            body="今天可以申请提现。财务打款后才会标已付，系统不会自动汇出。",
            data={"ref": cal["next_payout_date"], "available_minor": int(wallet.available_minor or 0)},
            skip_in_app=True,
        )
        sent += 1
    if sent:
        db.commit()
    return {"sent": sent, "next_payout_date": cal["next_payout_date"]}
