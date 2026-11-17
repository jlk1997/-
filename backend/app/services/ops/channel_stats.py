"""Measured channel results. A channel is not graduated until match data exists."""

from __future__ import annotations

from app.services.ops.automation_graduation import graduation_verdict


def match_rates_from_snapshots(rows: list[dict]) -> dict[str, float | None]:
    """Share of statement rows that landed on a work. None when a channel has no rows."""
    from app.services.distribution.catalog import SETTLEMENT_SOURCES

    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        source = str(row.get("source") or "")
        if source not in SETTLEMENT_SOURCES:
            continue
        code = str(row.get("channel_code") or "unknown")
        bucket = grouped.setdefault(code, {"n": 0, "hit": 0})
        bucket["n"] += 1
        if row.get("work_id") or row.get("usable_for_settlement"):
            bucket["hit"] += 1
    return {code: None if bucket["n"] == 0 else round(bucket["hit"] / bucket["n"], 4) for code, bucket in grouped.items()}


def channel_automation_rows(rows: list[dict], *, match_rates: dict[str, float | None] | None = None, days: int = 0) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        code = str(row.get("channel_code") or "unknown")
        bucket = grouped.setdefault(code, {"orders": 0, "fill_failed": 0, "receipts": 0, "closed": 0})
        bucket["orders"] += 1
        status = str(row.get("status") or "")
        error = str(row.get("last_error") or "")
        if "fill_incomplete" in error:
            bucket["fill_failed"] += 1
        if status == "live" and row.get("store_url"):
            bucket["receipts"] += 1
        if status in {"live", "in_review", "rejected", "taken_down", "ops_queue"} or "fill_incomplete" in error:
            bucket["closed"] += 1
    out = []
    for code, bucket in sorted(grouped.items()):
        closed = int(bucket["closed"])
        orders = int(bucket["orders"])
        fill_rate = None if closed == 0 else round((closed - int(bucket["fill_failed"])) / closed, 4)
        receipt_rate = None if orders == 0 else round(int(bucket["receipts"]) / orders, 4)
        rate = None if match_rates is None else match_rates.get(code)
        verdict = graduation_verdict(
            channel_code=code,
            days=days,
            orders=orders,
            fill_rate=fill_rate or 0,
            receipt_rate=receipt_rate or 0,
            match_rate=0 if rate is None else rate,
        )
        graduated = bool(verdict["graduated"]) if rate is not None else False
        note = (
            "对账匹配率还没算进来，这一家继续人工。"
            if rate is None
            else ("达到转正线，可以抽查。" if graduated else "对账匹配率还没到转正线，这一家继续人工。")
        )
        out.append(
            {
                "channel_code": code,
                "orders": orders,
                "fill_failed": int(bucket["fill_failed"]),
                "receipts": int(bucket["receipts"]),
                "fill_rate": fill_rate,
                "receipt_rate": receipt_rate,
                "match_rate": rate,
                "graduated": graduated,
                "reasons": verdict["reasons"],
                "note": note,
            }
        )
    return out
