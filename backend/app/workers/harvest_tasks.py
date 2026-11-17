import logging

from app.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def run_seat_runtime(
    db=None,
    *,
    enqueue_due_harvest: bool = False,
    force_harvest: bool = False,
    seat_id: str | None = None,
) -> dict:
    from app.services.seats.farm import drain_queued
    from app.services.seats.service import enqueue_due_harvests, ensure_platform_seats, heal_seat_runtime, warmup_platform_pool

    own = db is None
    db = db or SessionLocal()
    try:
        ensure_platform_seats(db)
        warmup = warmup_platform_pool(db)
        healed = heal_seat_runtime(db, seat_id=seat_id)
        queued = 0
        if enqueue_due_harvest or force_harvest:
            queued = enqueue_due_harvests(db, force=force_harvest, seat_id=seat_id)
        db.flush()
        if own:
            db.commit()
        drained = drain_queued(db, seat_id=seat_id)
        return {"queued": queued, "warmup": warmup, **healed, **drained}
    except Exception:
        logger.exception("seat runtime failed")
        raise
    finally:
        if own:
            db.close()


@celery_app.task(name="harvest_seats_task")
def harvest_seats_task() -> dict:
    return run_seat_runtime(enqueue_due_harvest=True, force_harvest=True)


@celery_app.task(name="drain_seat_jobs_task")
def drain_seat_jobs_task(enqueue_due_harvest: bool = False) -> dict:
    return run_seat_runtime(enqueue_due_harvest=enqueue_due_harvest, force_harvest=False)


@celery_app.task(name="ops_daily_digest_task")
def ops_daily_digest_task() -> dict:
    """Page ops even if nobody opens the admin digest. Webhook is deduped per day."""
    from app.services.ops_dashboard import ops_daily_digest

    db = SessionLocal()
    try:
        return ops_daily_digest(db)
    except Exception:
        logger.exception("ops_daily_digest_task failed")
        raise
    finally:
        db.close()


@celery_app.task(name="rematch_unattached_daily_task")
def rematch_unattached_daily_task() -> dict:
    """Daily rematch of unattached snapshots and ISRC-certain harvest rows. Never invents a match."""
    from app.services.harvest.unmatched import rematch_unmatched_harvest
    from app.services.royalty.ingest import rematch_unattached_snapshots

    db = SessionLocal()
    try:
        snapshots = rematch_unattached_snapshots(db, None)
        harvest = rematch_unmatched_harvest(db)
        return {"snapshots": snapshots, "harvest_unmatched": harvest}
    except Exception:
        logger.exception("rematch_unattached_daily_task failed")
        raise
    finally:
        db.close()


@celery_app.task(name="auto_payout_task")
def auto_payout_task() -> dict:
    """Friday audit only. Never pays; wallet.run_auto_payouts stays manual_payout_only."""
    from app.services.royalty.wallet import run_auto_payouts

    db = SessionLocal()
    try:
        return run_auto_payouts(db)
    except Exception:
        logger.exception("auto_payout_task failed")
        raise
    finally:
        db.close()
