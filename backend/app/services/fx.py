"""FX conversion for multi-currency wallets and payouts.

Rates are quoted as units of quote currency per 1 USD. Conversion goes
source -> USD -> target. When no live feed is configured, fall back to
the last cached snapshot or a conservative static table.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Units of currency per 1 USD. Conservative mid-market defaults, not for trading.
_STATIC_USD: dict[str, float] = {
    "USD": 1.0,
    "CNY": 7.2,
    "EUR": 0.92,
    "GBP": 0.78,
    "JPY": 150.0,
    "HKD": 7.8,
}

_CACHE: dict[str, Any] = {"rates": None, "fetched_at": 0.0}
_CACHE_TTL = 3600


def _usd_table() -> dict[str, float]:
    cached = _CACHE.get("rates")
    if isinstance(cached, dict) and cached:
        return cached
    return dict(_STATIC_USD)


def refresh_rates() -> dict[str, float]:
    """Pull live rates if configured; always merge onto the static table."""
    table = dict(_STATIC_USD)
    url = (settings.fx_api_url or "").strip()
    if url:
        try:
            import httpx

            headers = {}
            if settings.fx_api_key:
                headers["Authorization"] = f"Bearer {settings.fx_api_key}"
            resp = httpx.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
            incoming = body.get("rates") if isinstance(body, dict) else None
            if isinstance(incoming, dict):
                for code, value in incoming.items():
                    try:
                        table[str(code).upper()] = float(value)
                    except (TypeError, ValueError):
                        continue
        except Exception as exc:
            logger.warning("FX feed failed, using cache/static: %s", exc)
    table["USD"] = 1.0
    _CACHE["rates"] = table
    _CACHE["fetched_at"] = time.time()
    return table


def get_rates() -> dict[str, float]:
    now = time.time()
    if _CACHE.get("rates") and now - float(_CACHE.get("fetched_at") or 0) < _CACHE_TTL:
        return dict(_CACHE["rates"])
    return refresh_rates()


def convert_minor(amount_minor: int, source: str, target: str) -> int:
    """Convert integer minor units between currencies (banker's rounding)."""
    src = (source or "USD").upper()
    dst = (target or settings.default_payout_currency or "CNY").upper()
    if src == dst:
        return int(amount_minor)
    rates = get_rates()
    src_per_usd = rates.get(src)
    dst_per_usd = rates.get(dst)
    if not src_per_usd or not dst_per_usd:
        raise ValueError(f"unsupported_fx_pair:{src}->{dst}")
    usd = amount_minor / src_per_usd
    return int(round(usd * dst_per_usd))


def convert_map(by_currency: dict[str, int], target: str | None = None) -> dict[str, Any]:
    dst = (target or settings.default_payout_currency or "CNY").upper()
    total = 0
    skipped: list[str] = []
    for code, amount in (by_currency or {}).items():
        try:
            total += convert_minor(int(amount or 0), str(code), dst)
        except ValueError:
            skipped.append(str(code).upper())
    return {
        "currency": dst,
        "amount_minor": total,
        "skipped": skipped,
        "rates": get_rates(),
    }
