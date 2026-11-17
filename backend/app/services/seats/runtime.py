"""Kick the seat farm without blocking the request that enqueued work."""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

KICK_GAP_SECONDS = 20.0
_last_kick_mono = 0.0


def runtime_kick_allowed(gap_seconds: float = KICK_GAP_SECONDS, *, now: float | None = None, stamp: bool = True) -> bool:
    """Process-local debounce so hub refreshes do not stampede Celery."""
    global _last_kick_mono
    current = time.monotonic() if now is None else now
    if current - _last_kick_mono < gap_seconds:
        return False
    if stamp:
        _last_kick_mono = current
    return True


def kick_seat_runtime(*, enqueue_due_harvest: bool = False, countdown: int = 2) -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if not runtime_kick_allowed():
        return False
    try:
        from app.workers.harvest_tasks import drain_seat_jobs_task

        drain_seat_jobs_task.apply_async(
            kwargs={"enqueue_due_harvest": enqueue_due_harvest},
            queue="analytics",
            countdown=max(0, int(countdown or 0)),
        )
        return True
    except Exception:
        logger.debug("seat runtime kick skipped", exc_info=True)
        return False
