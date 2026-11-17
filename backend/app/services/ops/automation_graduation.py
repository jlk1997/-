"""A channel leaves the manual queue only after a measured streak."""

from __future__ import annotations

GRADUATION_DAYS = 30
GRADUATION_MIN_ORDERS = 50
GRADUATION_FILL_RATE = 0.95
GRADUATION_RECEIPT_RATE = 0.90
GRADUATION_MATCH_RATE = 0.98


def graduation_verdict(
    *,
    channel_code: str,
    days: int,
    orders: int,
    fill_rate: float,
    receipt_rate: float,
    match_rate: float,
) -> dict:
    reasons = []
    if days < GRADUATION_DAYS:
        reasons.append("days")
    if orders < GRADUATION_MIN_ORDERS:
        reasons.append("orders")
    if fill_rate < GRADUATION_FILL_RATE:
        reasons.append("fill")
    if receipt_rate < GRADUATION_RECEIPT_RATE:
        reasons.append("receipt")
    if match_rate < GRADUATION_MATCH_RATE:
        reasons.append("match")
    return {
        "channel_code": channel_code,
        "graduated": not reasons,
        "reasons": reasons,
        "ops_mode": "spot_check" if not reasons else "manual",
    }
