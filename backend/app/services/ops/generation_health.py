"""Generation health for the ops console. Figures come from ApiUsageLog, not from vendor dashboards."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.schemas import ApiUsageLog
from app.services.queue_metrics import celery_queue_depths


def _percentile(values: list[float], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return int(ordered[index])


def generation_snapshot(db: Session, *, hours: int = 24) -> dict:
    since = datetime.utcnow() - timedelta(hours=max(1, hours))
    rows = (
        db.query(ApiUsageLog)
        .filter(ApiUsageLog.endpoint == "/music_generation", ApiUsageLog.created_at >= since)
        .all()
    )
    elapsed: list[float] = []
    kinds: dict[str, int] = {}
    tokens = 0
    fallback = 0
    failures = 0
    for row in rows:
        extra = row.extra_data if isinstance(row.extra_data, dict) else {}
        kind = extra.get("error_kind")
        if kind:
            failures += 1
            kinds[str(kind)] = kinds.get(str(kind), 0) + 1
        else:
            ms = extra.get("elapsed_ms")
            if isinstance(ms, (int, float)) and ms > 0:
                elapsed.append(float(ms) / 1000.0)
            if extra.get("fallback"):
                fallback += 1
        tokens += int(row.tokens_used or 0)
    total = len(rows)
    success = max(0, total - failures)
    depths = celery_queue_depths()
    rate = (success / total) if total else None
    return {
        "hours": hours,
        "attempts": total,
        "success": success,
        "success_rate": round(rate, 4) if rate is not None else None,
        "p50_seconds": _percentile(elapsed, 0.5),
        "p95_seconds": _percentile(elapsed, 0.95),
        "error_kinds": kinds,
        "fallback_count": fallback,
        "fallback_rate": round(fallback / success, 4) if success else None,
        "tokens": tokens,
        "alerts": _alerts(rate, _percentile(elapsed, 0.95), kinds, depths.get("stems", 0)),
        "queues": {"stems": depths.get("stems", 0), "generation": depths.get("celery", 0) + depths.get("priority", 0)},
    }


def _alerts(rate: float | None, p95: int | None, kinds: dict[str, int], stem_depth: int) -> list[str]:
    alerts: list[str] = []
    if rate is not None and rate < 0.9:
        alerts.append("generation_success_below_90")
    if p95 is not None and p95 > 360:
        alerts.append("generation_p95_over_6m")
    if kinds.get("auth"):
        alerts.append("provider_auth")
    if stem_depth > 10:
        alerts.append("stem_queue_over_10")
    return alerts
