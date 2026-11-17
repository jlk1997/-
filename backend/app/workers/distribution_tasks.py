import logging
import uuid

from app.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="submit_release_task", autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={"max_retries": 5})
def submit_release_task(release_id: str) -> dict:
    from app.services.distribution.pipeline import process_release_submit

    db = SessionLocal()
    try:
        return process_release_submit(db, release_id)
    except Exception:
        logger.exception("submit_release_task failed for %s", release_id)
        raise
    finally:
        db.close()


@celery_app.task(name="process_delivery_task", autoretry_for=(Exception,), retry_backoff=20, retry_kwargs={"max_retries": 5})
def process_delivery_task(delivery_id: str) -> dict:
    from app.models.schemas import DistributionDelivery
    from app.services.distribution.pipeline import process_one_delivery

    db = SessionLocal()
    try:
        row = db.query(DistributionDelivery).filter(DistributionDelivery.id == uuid.UUID(str(delivery_id))).first()
        if not row:
            return {"skipped": True}
        return process_one_delivery(db, row, force=True, commit=True)
    except Exception:
        logger.exception("process_delivery_task failed for %s", delivery_id)
        raise
    finally:
        db.close()


@celery_app.task(name="reconcile_distribution_task")
def reconcile_distribution_task() -> dict:
    from app.services.distribution.pipeline import reconcile_distribution

    db = SessionLocal()
    try:
        return reconcile_distribution(db)
    except Exception:
        logger.exception("reconcile_distribution_task failed")
        raise
    finally:
        db.close()


@celery_app.task(name="ingest_pending_reports_task")
def ingest_pending_reports_task() -> dict:
    from app.services.royalty.ingest import fetch_licensed_analytics, fetch_youtube_analytics

    db = SessionLocal()
    try:
        from app.services.royalty.sync import sync_platform_partner_earnings

        return {
            "licensed": fetch_licensed_analytics(db),
            "youtube": fetch_youtube_analytics(db),
            "partners": sync_platform_partner_earnings(db),
        }
    finally:
        db.close()


@celery_app.task(name="run_settlement_task")
def run_settlement_task() -> dict:
    from app.services.royalty.settlement import run_settlement

    db = SessionLocal()
    try:
        return run_settlement(db)
    finally:
        db.close()


@celery_app.task(name="sweep_auto_release_task")
def sweep_auto_release_task() -> dict:
    from app.services.distribution.automation import sweep_auto_releases

    db = SessionLocal()
    try:
        return sweep_auto_releases(db)
    except Exception:
        logger.exception("sweep_auto_release_task failed")
        raise
    finally:
        db.close()


@celery_app.task(name="sync_distribution_status_task")
def sync_distribution_status_task() -> dict:
    from app.models.schemas import DistributionDelivery, Release
    from app.services.distribution.adapters import get_adapter
    from app.services.distribution.pipeline import (
        apply_query_result,
        notify_distribution_status,
        process_one_delivery,
        refresh_release_progress,
    )

    db = SessionLocal()
    try:
        rows = (
            db.query(DistributionDelivery)
            .filter(DistributionDelivery.status.in_(["submitting", "in_review"]))
            .limit(200)
            .all()
        )
        updated = 0
        for row in rows:
            try:
                if row.status == "submitting":
                    process_one_delivery(db, row, force=False, notify=False, commit=False)
                    updated += 1
                    continue
                adapter = get_adapter(row.distributor_code)
                if not adapter.configured():
                    continue
                result = adapter.query_status(row.external_id)
                previous = row.status
                if not apply_query_result(row, result):
                    continue
                if previous != "live" and row.status == "live":
                    from app.services.seats.service import queue_copy_after_live

                    queue_copy_after_live(db, row)
                updated += 1
                release = db.query(Release).filter(Release.id == row.release_id).first()
                if release:
                    refresh_release_progress(db, release)
                    if previous != row.status:
                        notify_distribution_status(
                            db,
                            row.owner_id,
                            release_id=str(release.id),
                            status=row.status,
                            channel_code=row.channel_code,
                            message=result.message or f"{row.channel_code} 状态更新为 {row.status}",
                        )
            except Exception:
                logger.exception("sync_distribution_status isolated failure for %s", row.id)
        db.commit()
        return {"checked": len(rows), "updated": updated}
    finally:
        db.close()
