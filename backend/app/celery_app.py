from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "vibe_sorcery",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    worker_pool=settings.celery_worker_pool,
    worker_concurrency=settings.celery_worker_concurrency,
    imports=("app.workers.tasks", "app.workers.distribution_tasks", "app.workers.harvest_tasks"),
    task_queues={
        "celery": {"exchange": "celery", "routing_key": "celery"},
        "priority": {"exchange": "priority", "routing_key": "priority"},
        "post_process": {"exchange": "post_process", "routing_key": "post_process"},
        "stems": {"exchange": "stems", "routing_key": "stems"},
        "distribution": {"exchange": "distribution", "routing_key": "distribution"},
        "analytics": {"exchange": "analytics", "routing_key": "analytics"},
        "settlement": {"exchange": "settlement", "routing_key": "settlement"},
    },
    task_routes={
        "post_process_work_task": {"queue": "post_process"},
        "prepare_release_assets_task": {"queue": "stems"},
        "lane_separate_task": {"queue": "stems"},
        "submit_release_task": {"queue": "distribution"},
        "process_delivery_task": {"queue": "distribution"},
        "reconcile_distribution_task": {"queue": "distribution"},
        "sync_distribution_status_task": {"queue": "distribution"},
        "sweep_auto_release_task": {"queue": "distribution"},
        "ingest_pending_reports_task": {"queue": "analytics"},
        "run_settlement_task": {"queue": "settlement"},
        "payout_day_nudge_task": {"queue": "settlement"},
        "harvest_seats_task": {"queue": "analytics"},
        "drain_seat_jobs_task": {"queue": "analytics"},
        "rematch_unattached_daily_task": {"queue": "analytics"},
        "ops_daily_digest_task": {"queue": "analytics"},
        "auto_payout_task": {"queue": "settlement"},
    },
    beat_schedule={
        "renew-mock-subscriptions-daily": {
            "task": "renew_subscriptions_task",
            "schedule": crontab(hour=0, minute=15),
        },
        "subscription-expiry-reminder-daily": {
            "task": "subscription_expiry_reminder_task",
            "schedule": crontab(hour=9, minute=0),
        },
        "reconcile-stale-pending-jobs": {
            "task": "reconcile_stale_pending_jobs_task",
            "schedule": 120.0,
        },
        "pending-jobs-heartbeat": {
            "task": "pending_jobs_heartbeat_task",
            "schedule": 30.0,
        },
        "finalize-pending-deletions-daily": {
            "task": "finalize_pending_deletions_task",
            "schedule": crontab(hour=2, minute=30),
        },
        "expire-stale-payment-orders-hourly": {
            "task": "expire_stale_payment_orders_task",
            "schedule": crontab(minute=30),
        },
        "deactivate-expired-subscriptions-daily": {
            "task": "deactivate_expired_subscriptions_task",
            "schedule": crontab(hour=0, minute=45),
        },
        "finalize-ended-challenges-hourly": {
            "task": "finalize_challenges_task",
            "schedule": crontab(minute=15),
        },
        "settle-expired-duels-hourly": {
            "task": "settle_duels_task",
            "schedule": crontab(minute=45),
        },
        "snapshot-leaderboards-daily": {
            "task": "snapshot_leaderboards_task",
            "schedule": crontab(hour=1, minute=0),
        },
        "creator-weekly-digest": {
            "task": "creator_weekly_digest_task",
            "schedule": crontab(hour=10, minute=0, day_of_week=1),
        },
        "radio-network-tick-daily": {
            "task": "radio_network_tick_task",
            "schedule": crontab(hour=1, minute=20),
        },
        "remind-ending-challenges-daily": {
            "task": "remind_ending_challenges_task",
            "schedule": crontab(hour=8, minute=0),
        },
        "reconcile-distribution-every-2m": {
            "task": "reconcile_distribution_task",
            "schedule": 120.0,
        },
        "sync-distribution-status-every-3m": {
            "task": "sync_distribution_status_task",
            "schedule": 180.0,
        },
        "sweep-auto-release-every-10m": {
            "task": "sweep_auto_release_task",
            "schedule": 600.0,
        },
        "ingest-pending-reports-daily": {
            "task": "ingest_pending_reports_task",
            "schedule": crontab(hour=3, minute=30),
        },
        "run-settlement-monthly": {
            "task": "run_settlement_task",
            "schedule": crontab(hour=4, minute=0, day_of_month=1),
        },
        "payout-day-nudge-friday": {
            "task": "payout_day_nudge_task",
            "schedule": crontab(hour=1, minute=0, day_of_week="fri"),
        },
        "harvest-seats-every-6h": {
            "task": "harvest_seats_task",
            "schedule": crontab(minute=20, hour="*/6"),
        },
        "drain-seat-jobs-every-1m": {
            "task": "drain_seat_jobs_task",
            "schedule": 60.0,
            "kwargs": {"enqueue_due_harvest": True},
        },
        "manual-payout-friday-audit": {
            "task": "auto_payout_task",
            "schedule": crontab(hour=2, minute=0, day_of_week="fri"),
        },
        "lapsed-user-recall-daily": {
            "task": "lapsed_user_recall_task",
            "schedule": crontab(hour=10, minute=30),
        },
        "rematch-unattached-daily": {
            "task": "rematch_unattached_daily_task",
            "schedule": crontab(hour=4, minute=20),
        },
        "ops-daily-digest": {
            "task": "ops_daily_digest_task",
            "schedule": crontab(hour=4, minute=40),
        },
    },
)
from celery.signals import worker_shutdown


@worker_shutdown.connect
def _close_minimax_http_on_worker_shutdown(**_kwargs):
    from app.integrations.minimax.http_utils import close_minimax_http_pool_sync

    close_minimax_http_pool_sync()
