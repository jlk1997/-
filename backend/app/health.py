"""Extended health checks for load balancers and ops."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.database import engine

_ESSENTIA_MODEL_HINTS = (
    "discogs-effnet-bs64-1.pb",
    "mtg_jamendo_moodtheme-discogs-effnet-1.pb",
)


def _check_database() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        detail = str(exc)[:200] if settings.debug else "unavailable"
        return {"status": "error", "detail": detail}


def _check_redis() -> dict:
    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return {"status": "ok"}
    except Exception as exc:
        detail = str(exc)[:200] if settings.debug else "unavailable"
        return {"status": "error", "detail": detail}


def _check_essentia_models() -> dict:
    models_dir = Path(settings.models_dir)
    if not models_dir.is_dir():
        return {"status": "degraded", "detail": "models_dir missing — emotion analysis may fallback"}
    found = [name for name in _ESSENTIA_MODEL_HINTS if (models_dir / name).exists()]
    if len(found) >= 2:
        return {"status": "ok", "models_found": len(found)}
    return {
        "status": "degraded",
        "detail": "Essentia models incomplete — install per README",
        "models_found": len(found),
    }


def _check_seat_runtime() -> dict:
    try:
        from app.database import SessionLocal
        from app.models.schemas import CreatorSeat, SeatJob
        from app.services.seats.service import farm_can_navigate

        db = SessionLocal()
        try:
            queued = int(db.query(SeatJob).filter(SeatJob.status == "queued").count() or 0)
            leased = int(db.query(SeatJob).filter(SeatJob.status == "leased").count() or 0)
            session_holds = int(
                db.query(CreatorSeat)
                .filter(CreatorSeat.status.in_(("expired", "needs_challenge", "needs_session")))
                .count()
                or 0
            )
        finally:
            db.close()
        status = "degraded" if queued > 40 else "ok"
        return {
            "status": status,
            "queued": queued,
            "leased": leased,
            "session_holds": session_holds,
            "farm_navigate": farm_can_navigate(),
        }
    except Exception as exc:
        detail = str(exc)[:200] if settings.debug else "unavailable"
        return {"status": "degraded", "detail": detail}


def _check_seat_vault() -> dict:
    raw = (getattr(settings, "seat_vault_key", "") or "").strip()
    if raw:
        return {"status": "ok"}
    return {"status": "degraded", "detail": "SEAT_VAULT_KEY unset — derived from JWT_SECRET"}


def collect_health() -> dict:
    checks = {
        "database": _check_database(),
        "redis": _check_redis(),
        "essentia_models": _check_essentia_models(),
        "seat_runtime": _check_seat_runtime(),
        "seat_vault": _check_seat_vault(),
    }
    critical = {checks["database"]["status"], checks["redis"]["status"]}
    if "error" in critical:
        overall = "error"
    else:
        overall = "ok"
    return {
        "status": overall,
        "version": settings.app_version,
        **({"debug": settings.debug} if settings.debug else {}),
        "checks": checks,
    }


def collect_worker_health() -> dict:
    """Celery worker + queue depth probe for ops and local dev diagnostics."""
    from app.services.queue_metrics import (
        active_worker_count,
        celery_queue_depths,
        generation_capacity_snapshot,
    )

    depths = celery_queue_depths()
    workers = active_worker_count()
    total_depth = sum(int(depths.get(name, 0) or 0) for name in ("celery", "priority", "post_process", "distribution", "analytics", "settlement"))
    capacity = generation_capacity_snapshot()
    if workers <= 0:
        status = "error"
        detail = "No Celery workers detected — start run-worker.ps1 locally"
    elif total_depth > 50:
        status = "degraded"
        detail = f"Queue backlog: {total_depth} tasks waiting"
    else:
        status = "ok"
        detail = None
    return {
        "status": status,
        "active_workers": workers,
        "total_broker_depth": total_depth,
        **capacity,
        **({"detail": detail} if detail else {}),
    }
