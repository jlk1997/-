import asyncio
import hashlib
import logging
import os
import time
import uuid
from types import SimpleNamespace

import httpx
from app.celery_app import celery_app
from app.config import settings
from app.core.emotion_engine import emotion_engine
from app.core.music_prompt_builder import estimate_av_from_moods
from app.core.music_spec_resolver import infer_moods_genres_from_spec, resolve_creative_spec
from app.core.playlist_orchestrator import PlaylistOrchestrator
from app.database import SessionLocal
from app.integrations.vendors.router import generate_music as routed_generate_music
from app.integrations.minimax.music_response import compose_music_prompt
from app.models.schemas import GenerationJob, ProvenanceRecord, User, Work
from app.services.post_process import post_process_work
from app.services.job_progress import (
    composing_progress_heartbeat,
    update_job_phase,
)
from app.services.job_state import (
    complete_at_audio_ready,
    fail_job,
    on_post_process_finished,
    start_running,
    verify_worker_job,
)
from app.services.storage import get_storage_service
from app.services.reference_track import apply_reference_emotion
from app.services.work_access import can_use_work_as_seed
from app.workers.errors import PartialPlaylistError, friendly_generation_error, friendly_generation_error_with_code
from app.services.job_errors import FORBIDDEN, GENERATION_FAILED, NOT_FOUND, PARTIAL_PLAYLIST, VALIDATION
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

_GENERATION_AUTORETRY = {
    "autoretry_for": (OperationalError, ConnectionError, OSError),
    "retry_backoff": True,
    "max_retries": 2,
}


def _fail_from_exception(db, job_id: str, exc: Exception, *, partial_result: dict | None = None) -> None:
    if isinstance(exc, (OperationalError, ConnectionError, OSError)):
        raise exc
    code, msg = friendly_generation_error_with_code(exc, partial=partial_result is not None)
    fail_job(db, job_id, error_message=msg, error_code=code, partial_result=partial_result)


def is_job_cancelled(job_id: str) -> bool:
    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
        return bool(job and job.status == "cancelled")
    finally:
        db.close()


def run_async(coro):
    from app.workers.worker_runtime import run_async as _run_async

    return _run_async(coro)


def notify_job_terminal_state(job_id: str) -> None:
    """Notify user webhooks and in-app notifications after terminal job state."""
    from app.services.generation_gate import refund_job_credits_if_needed
    from app.services.job_webhooks import dispatch_job_webhooks
    from app.services.notifications import notify_job_terminal

    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
        if job and job.status in ("completed", "failed", "cancelled"):
            from app.observability.structured_logging import log_generation_job

            charged = (job.config or {}).get("credits_charged")
            log_generation_job(
                job_id=job_id,
                user_id=str(job.owner_id),
                job_type=job.job_type,
                status=job.status,
                credits_charged=int(charged) if charged is not None else None,
                error=job.error_message,
            )
            if job.status in ("failed", "cancelled"):
                refund_job_credits_if_needed(db, job)
                db.refresh(job)
            dispatch_job_webhooks(db, job)
            notify_job_terminal(db, job)
    except Exception:
        logger.exception("Terminal job notification failed for job %s", job_id)
    finally:
        db.close()


def _heartbeat_age_seconds(job: GenerationJob, now) -> float:
    from datetime import datetime

    raw = (job.config or {}).get("_heartbeat_at")
    stamp = None
    if isinstance(raw, str):
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            stamp = None
    if stamp is None:
        stamp = job.updated_at or job.created_at
    if stamp is None:
        return 0.0
    return max(0.0, (now - stamp).total_seconds())


def reconcile_stale_jobs(db) -> dict:
    """Close jobs the worker stopped touching.

    Pending with no celery id is a queue miss. Running with no audio is a dead worker.
    audio_ready / post_processing that already saved audio complete instead of failing.
    """
    from datetime import datetime

    from app.services.job_errors import QUEUE_TIMEOUT, WORKER_LOST
    from app.services.job_state import (
        STALE_COMPLETE,
        STALE_FAIL,
        complete_at_audio_ready,
        fail_job,
        job_has_audio,
        stale_job_action,
    )

    now = datetime.utcnow()
    pending_limit = settings.stale_pending_minutes * 60
    running_limit = settings.stale_running_minutes * 60
    audio_limit = settings.stale_audio_ready_minutes * 60
    post_limit = settings.stale_post_process_minutes * 60
    summary = {"pending_failed": 0, "failed": 0, "completed": 0}

    pending = (
        db.query(GenerationJob)
        .filter(GenerationJob.status == "pending")
        .order_by(GenerationJob.created_at.asc())
        .limit(100)
        .all()
    )
    for job in pending:
        age = (now - job.created_at).total_seconds() if job.created_at else 0
        action = stale_job_action(
            status="pending",
            age_seconds=age,
            has_audio=False,
            has_celery_task=bool((job.config or {}).get("_celery_task_id")),
            pending_limit_s=pending_limit,
            running_limit_s=running_limit,
            audio_ready_limit_s=audio_limit,
            post_process_limit_s=post_limit,
        )
        if action != STALE_FAIL:
            continue
        fail_job(db, str(job.id), error_message="任务排队超时，请重试", error_code=QUEUE_TIMEOUT)
        summary["pending_failed"] += 1

    active = (
        db.query(GenerationJob)
        .filter(GenerationJob.status.in_(("running", "audio_ready", "post_processing")))
        .order_by(GenerationJob.updated_at.asc())
        .limit(200)
        .all()
    )
    for job in active:
        has_audio = job_has_audio(dict(job.result or {}))
        action = stale_job_action(
            status=job.status,
            age_seconds=_heartbeat_age_seconds(job, now),
            has_audio=has_audio,
            has_celery_task=True,
            pending_limit_s=pending_limit,
            running_limit_s=running_limit,
            audio_ready_limit_s=audio_limit,
            post_process_limit_s=post_limit,
        )
        if action == STALE_FAIL:
            fail_job(
                db,
                str(job.id),
                error_message="生成中断了，次数已退回，请重试",
                error_code=WORKER_LOST,
            )
            summary["failed"] += 1
        elif action == STALE_COMPLETE:
            result = dict(job.result or {})
            result.setdefault("post_process_warning", "后处理超时，歌曲可以先听")
            complete_at_audio_ready(db, str(job.id), result=result, status_message="炼成完成")
            summary["completed"] += 1
    return summary


@celery_app.task(name="reconcile_stale_pending_jobs_task")
def reconcile_stale_pending_jobs_task():
    """Fail undispatched pending jobs and close active jobs whose worker went quiet."""
    db = SessionLocal()
    try:
        summary = reconcile_stale_jobs(db)
        summary["reconciled"] = summary["pending_failed"]
        return summary
    finally:
        db.close()


@celery_app.task(name="pending_jobs_heartbeat_task")
def pending_jobs_heartbeat_task():
    """Refresh queue wait messages for pending jobs."""
    from app.services.job_progress import update_job_pending_heartbeat

    db = SessionLocal()
    try:
        pending = (
            db.query(GenerationJob)
            .filter(GenerationJob.status == "pending")
            .order_by(GenerationJob.created_at.asc())
            .limit(200)
            .all()
        )
        updated = 0
        for job in pending:
            before = job.status_message
            update_job_pending_heartbeat(db, job)
            db.refresh(job)
            if job.status_message != before:
                updated += 1
        return {"checked": len(pending), "updated": updated}
    finally:
        db.close()


@celery_app.task(name="renew_subscriptions_task")
def renew_subscriptions_task():
    from app.services.subscriptions import process_mock_subscription_renewals, remind_expiring_subscriptions

    db = SessionLocal()
    try:
        renewed = process_mock_subscription_renewals(db)
        reminded = remind_expiring_subscriptions(db)
        return {"renewed": renewed, "reminded": reminded}
    finally:
        db.close()


@celery_app.task(name="subscription_expiry_reminder_task")
def subscription_expiry_reminder_task():
    from app.services.subscriptions import remind_subscription_expiry

    db = SessionLocal()
    try:
        sent = remind_subscription_expiry(db, days_before=3)
        return {"reminders_sent": sent}
    finally:
        db.close()


@celery_app.task(name="finalize_pending_deletions_task")
def finalize_pending_deletions_task():
    from app.services.account_deletion import finalize_pending_deletions

    db = SessionLocal()
    try:
        count = finalize_pending_deletions(db)
        return {"finalized": count}
    finally:
        db.close()


@celery_app.task(name="expire_stale_payment_orders_task")
def expire_stale_payment_orders_task():
    from app.services.payment_orders import expire_stale_pending_orders

    db = SessionLocal()
    try:
        count = expire_stale_pending_orders(db)
        return {"expired": count}
    finally:
        db.close()


@celery_app.task(name="deactivate_expired_subscriptions_task")
def deactivate_expired_subscriptions_task():
    from app.services.subscriptions import deactivate_expired_subscriptions

    db = SessionLocal()
    try:
        count = deactivate_expired_subscriptions(db)
        return {"deactivated": count}
    finally:
        db.close()


@celery_app.task(name="finalize_challenges_task")
def finalize_challenges_task():
    from app.services.challenge_awards import finalize_ended_challenges

    db = SessionLocal()
    try:
        count = finalize_ended_challenges(db)
        return {"finalized": count}
    finally:
        db.close()


@celery_app.task(name="settle_duels_task")
def settle_duels_task():
    from app.services.duels import settle_expired_duels

    db = SessionLocal()
    try:
        count = settle_expired_duels(db)
        return {"settled": count}
    finally:
        db.close()


@celery_app.task(name="snapshot_leaderboards_task")
def snapshot_leaderboards_task():
    from app.services.leaderboards import snapshot_all_charts

    db = SessionLocal()
    try:
        count = snapshot_all_charts(db)
        return {"charts": count}
    finally:
        db.close()


@celery_app.task(name="payout_day_nudge_task")
def payout_day_nudge_task():
    from app.services.royalty.payout_calendar import send_payout_day_nudges

    db = SessionLocal()
    try:
        return send_payout_day_nudges(db)
    finally:
        db.close()


@celery_app.task(name="creator_weekly_digest_task")
def creator_weekly_digest_task():
    from app.services.creator_weekly_digest import send_creator_weekly_digests

    db = SessionLocal()
    try:
        sent = send_creator_weekly_digests(db)
        return {"sent": sent}
    finally:
        db.close()


@celery_app.task(name="radio_network_tick_task")
def radio_network_tick_task():
    from app.services.radio.network import radio_network_tick

    db = SessionLocal()
    try:
        return radio_network_tick(db)
    finally:
        db.close()


@celery_app.task(name="lapsed_user_recall_task")
def lapsed_user_recall_task():
    """Send recall notifications to lapsed users at 7/14/30 day intervals."""
    db = SessionLocal()
    try:
        from app.services.growth import find_lapsed_users
        from app.services.notifications import notify_key_event
        import asyncio

        for days in (7, 14, 30):
            users = find_lapsed_users(db, days)
            for user in users:
                try:
                    asyncio.run(notify_key_event(
                        db,
                        user.id,
                        f"recall_{days}d",
                        title="我们想念你的音乐 🎵" if days <= 7 else "你的创作灵感还在吗？",
                        body=f"已经 {days} 天没有创作了，来看看社区有什么新鲜事吧",
                    ))
                except Exception:
                    pass
    finally:
        db.close()


@celery_app.task(name="remind_ending_challenges_task")
def remind_ending_challenges_task():
    from app.services.challenge_reminders import remind_ending_challenges

    db = SessionLocal()
    try:
        sent = remind_ending_challenges(db)
        return {"sent": sent}
    finally:
        db.close()


@celery_app.task(name="deliver_webhook_task")
def deliver_webhook_task(webhook_id: str, job_id: str, event: str):
    from app.services.job_webhooks import deliver_webhook

    return deliver_webhook(webhook_id, job_id, event)


def _fan_out_post_process(
    db,
    job_id: str,
    owner_id: uuid.UUID,
    work_ids: list[str],
    *,
    result: dict | None = None,
    audio_staging: dict[str, str] | None = None,
) -> None:
    """Transition job to post_processing; complete only after critical artifacts land."""
    from app.services.job_state import begin_post_processing, mark_audio_ready

    merged = dict(result or {})
    merged["post_process_state"] = "pending"

    # Let the user listen immediately (audio_ready phase) but hold the terminal state
    mark_audio_ready(db, job_id, result=merged)

    if not work_ids:
        # Nothing to post-process — mark completed immediately
        from app.services.job_state import on_post_process_finished
        on_post_process_finished(db, job_id, failed=False)
        return

    # Start the counter-based completion: one count per work
    begin_post_processing(db, job_id, pending_count=len(work_ids), result=merged)

    for wid in work_ids:
        staging_key = (audio_staging or {}).get(wid)
        post_process_work_task.apply_async(
            args=[wid, str(owner_id)],
            kwargs={"staging_key": staging_key, "job_id": job_id},
            queue="post_process",
        )


def _enqueue_release_assets(work_id: str, user_id: str) -> None:
    prepare_release_assets_task.apply_async(args=[work_id, str(user_id)], queue="stems")


@celery_app.task(
    name="post_process_work_task",
    queue="post_process",
    bind=True,
    autoretry_for=(ConnectionError, OSError, httpx.HTTPError),
    retry_backoff=True,
    max_retries=3,
    retry_backoff_max=300,
)
def post_process_work_task(
    self,
    work_id: str,
    user_id: str,
    job_id: str | None = None,
    staging_key: str | None = None,
):
    db = SessionLocal()
    try:
        work = db.query(Work).filter(Work.id == uuid.UUID(work_id)).first()
        if not work:
            return
        if str(work.owner_id) != user_id:
            return
        if staging_key:
            content = get_storage_service().get_object_bytes(staging_key)
        else:
            url = work.audio_url
            if work.storage_key:
                url = get_storage_service().get_presigned_url(work.storage_key)
            resp = httpx.get(url, timeout=60)
            resp.raise_for_status()
            content = resp.content
        job_uuid = uuid.UUID(job_id) if job_id else None
        result = run_async(post_process_work(db, work.id, content, job_uuid))
        if staging_key:
            get_storage_service().delete_object(staging_key)
        db.refresh(work)
        if job_id:
            from app.services.job_progress import patch_completed_job_artifacts

            patch_completed_job_artifacts(db, job_id, work)
        if job_id:
            db.refresh(work)
            on_post_process_finished(
                db,
                job_id,
                work_patch={
                    "work_id": str(work.id),
                    "audio_url": work.audio_url,
                    "title": work.title,
                    "cover_url": work.cover_url,
                    "hls_url": work.hls_url,
                },
            )
        _enqueue_release_assets(work_id, user_id)
        return result
    except Exception as exc:
        logger.warning(
            "Post-process failed for work %s (music is still saved): %s",
            work_id,
            friendly_generation_error(exc),
        )
        try:
            work = db.query(Work).filter(Work.id == uuid.UUID(work_id)).first()
            if work:
                pps = dict(work.post_process_status or {})
                pps["state"] = "degraded"
                work.post_process_status = pps
                db.commit()
                if job_id:
                    from app.services.job_progress import patch_completed_job_artifacts

                    patch_completed_job_artifacts(db, job_id, work)
        except Exception:
            db.rollback()
        if job_id:
            db2 = SessionLocal()
            try:
                work = db2.query(Work).filter(Work.id == uuid.UUID(work_id)).first()
                patch = {}
                if work:
                    patch = {
                        "work_id": str(work.id),
                        "audio_url": work.audio_url,
                        "title": work.title,
                    }
                on_post_process_finished(db2, job_id, work_patch=patch or None, failed=True,
                                        error_message="Post-processing degraded")
            finally:
                db2.close()
        _enqueue_release_assets(work_id, user_id)
        return {"error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="generate_playlist_task", **_GENERATION_AUTORETRY)
def generate_playlist_task(job_id: str, config: dict):
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        if is_job_cancelled(job_id):
            return {"cancelled": True}

        seed_bytes = None
        seed_filename = config.get("seed_filename", "seed.wav")

        if config.get("seed_storage_key"):
            url = get_storage_service().get_presigned_url(config["seed_storage_key"])
            resp = httpx.get(url, timeout=60)
            resp.raise_for_status()
            seed_bytes = resp.content
        elif config.get("seed_work_id"):
            work = db.query(Work).filter(Work.id == uuid.UUID(config["seed_work_id"])).first()
            if not work:
                fail_job(db, job_id, error_message="Seed work not found", error_code=NOT_FOUND)
                return
            if not can_use_work_as_seed(work, job.owner_id, db):
                fail_job(db, job_id, error_message="Forbidden seed work", error_code=FORBIDDEN)
                return
            url = work.audio_url
            if work.storage_key:
                url = get_storage_service().get_presigned_url(work.storage_key)
            resp = httpx.get(url, timeout=60)
            resp.raise_for_status()
            seed_bytes = resp.content
            seed_filename = "seed.mp3"

        generation_mode = config.get("generation_mode") or config.get("journey", {}).get("mode", "prompt_journey")
        if seed_bytes is not None:
            if journey := config.get("journey"):
                journey = dict(journey)
                journey["mode"] = "audio_anchor" if generation_mode != "markov" else "markov"
                config = {**config, "journey": journey}
        elif generation_mode in ("markov", "audio_anchor"):
            fail_job(db, job_id, error_message="audio_anchor mode requires seed audio", error_code=VALIDATION)
            return

        creative_spec = run_async(resolve_creative_spec(config, db=db, user_id=str(job.owner_id)))
        anchor_context = {
            "text_intent": config.get("text_intent"),
            "preset_id": config.get("preset_id"),
            "moods": config.get("moods") or creative_spec.moods,
            "genres": config.get("genres") or creative_spec.genres,
            "creative_spec": creative_spec.model_dump(),
        }
        journey = config.get("journey") or {}
        if journey.get("reference"):
            anchor_context["reference_work_id"] = journey["reference"].get("work_id")

        if seed_bytes and generation_mode == "prompt_journey":
            analysis = emotion_engine.analyze_bytes(seed_bytes, suffix=os.path.splitext(seed_filename)[1] or ".wav")
            if not anchor_context["moods"]:
                anchor_context["moods"] = analysis.get("moods") or []
            if not anchor_context["genres"]:
                anchor_context["genres"] = analysis.get("genres") or []

        orchestrator = PlaylistOrchestrator(db)
        result = run_async(
            orchestrator.generate_playlist(
                job=job,
                owner_id=job.owner_id,
                journey_config=config.get("journey", {}),
                music_params=config.get("music_params", {}),
                seed_audio_bytes=seed_bytes if seed_bytes and generation_mode in ("markov", "audio_anchor") else None,
                seed_filename=seed_filename,
                anchor_context=anchor_context,
            )
        )
        if result and result.get("work_ids"):
            _fan_out_post_process(db, job_id, job.owner_id, result["work_ids"], result=result)
        elif not result or not result.get("work_ids"):
            fail_job(db, job_id, error_message="Playlist generation produced no tracks", error_code=GENERATION_FAILED)
        return result
    except PartialPlaylistError as e:
        db.rollback()
        db.expire_all()
        job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
        partial = dict(job.result or {}) if job else {}
        for wid in partial.get("work_ids") or []:
            post_process_work_task.apply_async(args=[wid, str(job.owner_id)], queue="post_process")
        # Settle partial credits BEFORE fail_job, so credits_settled flag prevents
        # the full refund that fail_job → notify_job_terminal_state would trigger.
        from app.services.generation_gate import settle_partial_credits
        if job:
            total_steps = int((job.config or {}).get("total_steps") or config.get("count", 3))
            delivered = len(partial.get("work_ids") or [])
            settle_partial_credits(db, job, total_expected=total_steps, total_delivered=delivered)
        fail_job(
            db,
            job_id,
            error_message=friendly_generation_error(e),
            error_code=PARTIAL_PLAYLIST,
            partial_result=partial or None,
        )
        return partial
    except Exception as e:
        db.rollback()
        job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
        partial = dict(job.result or {}) if job and (job.result or {}).get("partial") else None
        if partial and partial.get("work_ids"):
            for wid in partial["work_ids"]:
                post_process_work_task.apply_async(args=[wid, str(job.owner_id)], queue="post_process")
        _fail_from_exception(db, job_id, e, partial_result=partial)
        raise
    finally:
        db.close()


@celery_app.task(name="generate_single_task", **_GENERATION_AUTORETRY)
def generate_single_task(job_id: str, config: dict):
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        if is_job_cancelled(job_id):
            return {"cancelled": True}
        if job.status in ("audio_ready", "post_processing", "completed") or (job.result or {}).get("work_id"):
            return dict(job.result or {})

        start_running(db, job)
        db.refresh(job)
        update_job_phase(
            db,
            job,
            progress=0.05,
            status_message="任务已排队，准备开始…",
            phase="queued",
        )

        async def _run():
            text_intent = (config.get("text_intent") or "").strip()
            moods = list(config.get("moods") or [])
            genres = list(config.get("genres") or [])
            reference_work_uuid = None
            mock_bytes = b""
            bpm_override = config.get("bpm")
            key_override = config.get("key") or "auto"
            bpm_range = (
                (bpm_override, bpm_override)
                if bpm_override
                else (80, 120)
            )

            if config.get("seed_work_id"):
                work = db.query(Work).filter(Work.id == uuid.UUID(config["seed_work_id"])).first()
                if not work or not can_use_work_as_seed(work, job.owner_id, db):
                    raise RuntimeError("Forbidden or missing seed work")
                audio_url = work.audio_url
                if work.storage_key:
                    audio_url = get_storage_service().get_presigned_url(work.storage_key)
                resp = httpx.get(audio_url, timeout=60)
                mock_bytes = resp.content
                analysis = emotion_engine.analyze_bytes(mock_bytes, ".mp3")
                if not moods:
                    moods = analysis["moods"]
                if not genres:
                    genres = analysis["genres"]
                if not config.get("text_intent"):
                    text_intent = f"{', '.join(moods)} {', '.join(genres)}"

            if config.get("remix_intent"):
                prov = (
                    db.query(ProvenanceRecord)
                    .filter(ProvenanceRecord.work_id == uuid.UUID(config["seed_work_id"]))
                    .first()
                )
                original_prompt = ""
                if prov and prov.music_request:
                    original_prompt = prov.music_request.get("prompt", "")
                remix_intent = (config.get("remix_intent") or "").strip()
                if len(remix_intent) < 30:
                    text_intent = f"{original_prompt or text_intent}, {remix_intent}".strip(", ")
                else:
                    from app.integrations.vendors.router import remix_prompt as routed_remix_prompt

                    remix_data = await routed_remix_prompt(
                        original_prompt=original_prompt or text_intent,
                        user_intent=remix_intent,
                        db=db,
                        user_id=str(job.owner_id),
                    )
                    text_intent = remix_data.get("prompt", text_intent)
                    if remix_data.get("bpm"):
                        bpm_override = remix_data["bpm"]
                        bpm_range = (bpm_override, bpm_override)
                    if remix_data.get("key"):
                        key_override = remix_data["key"]

            ref_cfg = config.get("reference")
            ref_merged: dict = {}
            if ref_cfg and ref_cfg.get("work_id"):
                owner = db.query(User).filter(User.id == job.owner_id).first()
                ref_merged, reference_work_uuid = apply_reference_emotion(
                    db,
                    {"moods": moods, "genres": genres},
                    ref_cfg["work_id"],
                    av_offset=ref_cfg.get("av_offset"),
                    user=owner,
                )
                moods = ref_merged.get("moods") or moods
                genres = ref_merged.get("genres") or genres

            if not moods and not genres:
                inferred = emotion_engine.infer_from_intent(text_intent)
                moods = inferred.get("moods") or []
                genres = inferred.get("genres") or []

            creative_spec = await resolve_creative_spec(config, db=db, user_id=str(job.owner_id))
            moods, genres = infer_moods_genres_from_spec(creative_spec, moods, genres)

            if bpm_override:
                creative_spec = creative_spec.model_copy(update={"bpm": bpm_override})
            if key_override and key_override != "auto":
                creative_spec = creative_spec.model_copy(update={"key": key_override})
            if not creative_spec.bpm_range and bpm_range:
                creative_spec = creative_spec.model_copy(update={"bpm_range": [bpm_range[0], bpm_range[1]]})

            from app.services.generation_contract import prepare_generation_inputs

            prepared = await prepare_generation_inputs(
                config,
                creative_spec,
                db=db,
                user_id=str(job.owner_id),
            )
            creative_spec = prepared["spec"]
            text_intent = prepared["text_intent"] or text_intent
            prepared_lyrics = prepared["lyrics"]
            prepared_instrumental = prepared["is_instrumental"]
            prepared_optimizer = prepared["lyrics_optimizer"]
            prepared_audio = prepared["audio_setting"]

            update_job_phase(
                db,
                job,
                progress=0.15,
                status_message="正在理解你的创作意图…",
                phase="intent",
            )
            from app.integrations.vendors.router import build_music_prompt as routed_build_music_prompt

            prompt_data = await routed_build_music_prompt(
                moods=moods,
                genres=genres,
                step=1,
                total_steps=1,
                bpm_range=bpm_range,
                key=key_override,
                instrumental=prepared_instrumental,
                text_intent=text_intent,
                creative_spec=creative_spec,
                db=db,
                user_id=str(job.owner_id),
            )

            if bpm_override and prompt_data.get("bpm") != bpm_override:
                prompt_data["bpm"] = bpm_override
            if key_override != "auto" and prompt_data.get("key") != key_override:
                prompt_data["key"] = key_override

            lyrics = prepared_lyrics
            style_tags = config.get("style_tags") or creative_spec.style_tags
            is_instrumental = prepared_instrumental
            lyrics_optimizer = prepared_optimizer
            user_seed = config.get("seed")
            gen_seed = user_seed if user_seed is not None else hash(f"{job.id}") % 1_000_000
            avoid_vendor = None
            if config.get("remelt") and config.get("seed_work_id"):
                source_prov = (
                    db.query(ProvenanceRecord)
                    .filter(ProvenanceRecord.work_id == uuid.UUID(config["seed_work_id"]))
                    .first()
                )
                if source_prov and isinstance(source_prov.music_request, dict):
                    avoid_vendor = source_prov.music_request.get("provider") or source_prov.music_request.get("vendor")

            music_prompt = compose_music_prompt(
                style_tags=style_tags,
                built_prompt=prompt_data.get("prompt") if prompt_data.get("source") == "m3_journey" else None,
                text_intent=text_intent,
                bpm=prompt_data.get("bpm"),
                key=prompt_data.get("key"),
                creative_spec=creative_spec,
            )

            from datetime import datetime

            cfg = dict(job.config or {})
            cfg["compose_started_at"] = datetime.utcnow().isoformat()
            job.config = cfg
            db.commit()

            update_job_phase(
                db,
                job,
                progress=0.25,
                status_message="AI 正在作曲，请稍候（约 1–3 分钟）…",
                phase="composing",
            )
            from app.services.provider_checkpoint import guarded_generate_music

            heartbeat_stop = asyncio.Event()
            heartbeat_task = asyncio.create_task(composing_progress_heartbeat(job.id, heartbeat_stop))
            try:
                result = await guarded_generate_music(
                    db,
                    job,
                    prompt=music_prompt,
                    lyrics=lyrics,
                    is_instrumental=is_instrumental,
                    lyrics_optimizer=lyrics_optimizer,
                    seed=gen_seed,
                    user_id=str(job.owner_id),
                    mock_audio_bytes=mock_bytes or None,
                    remelt=bool(config.get("remelt")),
                    avoid_vendor=avoid_vendor,
                    skip_vendors=list(config.get("skip_vendors") or []),
                    capability="instrumental" if is_instrumental and not lyrics else "music",
                    audio_setting=prepared_audio,
                    prompt_context={
                        "prompt": music_prompt,
                        "lyrics": lyrics,
                        "seed": gen_seed,
                        "moods": moods,
                        "genres": genres,
                        "text_intent": text_intent,
                        "style_tags": style_tags,
                        "bpm": prompt_data.get("bpm"),
                        "key": prompt_data.get("key"),
                    },
                )
            finally:
                heartbeat_stop.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            if not result.audio_bytes:
                base = (result.metadata.get("response") or {}).get("base_resp") or {}
                detail = base.get("status_msg") or "未返回音频数据"
                raise RuntimeError(f"生成失败：{detail}")

            content_hash = hashlib.sha256(result.audio_bytes).hexdigest()
            update_job_phase(
                db,
                job,
                progress=0.85,
                status_message="正在保存你的作品…",
                phase="saving",
            )
            from app.services.provider_checkpoint import read_slot, write_slot

            saved_call = read_slot(job)
            if saved_call.get("state") == "stored" and saved_call.get("storage_key"):
                storage_key = str(saved_call["storage_key"])
                url = saved_call.get("public_url") or get_storage_service().get_presigned_url(storage_key)
            else:
                key = get_storage_service().generate_work_key(str(job.owner_id))
                storage_key, url = get_storage_service().upload_bytes(result.audio_bytes, key)
                write_slot(
                    db,
                    job,
                    "main",
                    {"state": "stored", "storage_key": storage_key, "public_url": url},
                )
            parent_id = None
            if config.get("seed_work_id") and (
                config.get("remix_intent")
                or config.get("extend")
                or config.get("remelt")
                or config.get("workbench_session_id")
                or config.get("record_type") in ("extend", "cover", "remelt", "same_style", "workbench")
            ):
                parent_id = uuid.UUID(config["seed_work_id"])

            owner = db.query(User).filter(User.id == job.owner_id).first()
            owner_tenant = owner.tenant_id if owner else settings.default_tenant_id

            work_arousal = creative_spec.arousal
            work_valence = creative_spec.valence
            if ref_merged.get("arousal") is not None:
                work_arousal = ref_merged["arousal"]
            if ref_merged.get("valence") is not None:
                work_valence = ref_merged["valence"]
            if work_arousal is None or work_valence is None:
                est_a, est_v = estimate_av_from_moods(moods)
                if work_arousal is None:
                    work_arousal = est_a
                if work_valence is None:
                    work_valence = est_v

            from app.services.audio_distance import remelt_record
            from app.services.distribution.catalog import clip_windows
            from app.services.media import probe_audio

            probed = probe_audio(result.audio_bytes)
            parent_work = db.query(Work).filter(Work.id == parent_id).first() if parent_id else None
            duration = probed.get("duration")
            work = Work(
                owner_id=job.owner_id,
                title=config.get("title") or config.get("song_title") or "Generated Track",
                audio_url=url,
                storage_key=storage_key,
                visibility="private",
                content_hash=content_hash,
                parent_work_id=parent_id,
                reference_work_id=reference_work_uuid,
                moods=moods,
                genres=genres,
                arousal=work_arousal,
                valence=work_valence,
                tenant_id=owner_tenant,
                duration=duration,
                post_process_status={
                    "clip_windows": clip_windows(duration),
                    "lyrics": lyrics or None,
                    **(
                        {
                            "remelt": remelt_record(
                                parent_work,
                                SimpleNamespace(
                                    arousal=work_arousal,
                                    valence=work_valence,
                                ),
                                (config.get("reference") or {}).get("av_offset"),
                            )
                        }
                        if config.get("remelt") or config.get("distance_nudge")
                        else {}
                    ),
                    **(
                        {
                            "reference": {
                                "work_id": str(reference_work_uuid),
                                "embedding": bool(ref_merged.get("reference_embedding_ready")),
                            }
                        }
                        if reference_work_uuid
                        else {}
                    ),
                },
            )
            db.add(work)
            db.flush()
            try:
                from app.services.reference_track import ensure_reference_embedding

                ensure_reference_embedding(db, work)
            except Exception:
                logger.warning("embedding stamp failed for %s", work.id)
            db.add(
                ProvenanceRecord(
                    work_id=work.id,
                    parent_work_id=parent_id,
                    pipeline_version=settings.pipeline_version,
                    step_index=0,
                    record_type=config.get("record_type") or "generated",
                    music_request={
                        "prompt": music_prompt,
                        "style_tags": style_tags,
                        "lyrics": lyrics,
                        "seed": gen_seed,
                        "bpm": prompt_data.get("bpm", bpm_override),
                        "key": prompt_data.get("key", key_override),
                        "text_intent": text_intent,
                        "moods": moods,
                        "genres": genres,
                        "vendor_id": (result.metadata or {}).get("vendor_id"),
                        "provider": (result.metadata or {}).get("vendor"),
                        "model": result.model,
                        "trace_id": (result.metadata or {}).get("trace_id") or result.task_id,
                        "request_id": (result.metadata or {}).get("request_id"),
                        "tokens": (result.metadata or {}).get("tokens"),
                        "mode": (result.metadata or {}).get("mode"),
                        "fallback": bool((result.metadata or {}).get("fallback")),
                    },
                    output_meta={"sha256": content_hash},
                    job_id=job.id,
                )
            )
            partial_result = {
                "work_id": str(work.id),
                "audio_url": url,
                "title": work.title,
            }
            staging_key = f"staging/post/{work.id}.mp3"
            get_storage_service().upload_bytes(result.audio_bytes, staging_key)
            db.refresh(job)

            if config.get("workbench_session_id"):
                from app.services.workbench import attach_regen_take, attach_render_result

                if config.get("workbench_take") or config.get("record_type") in {"extend", "remelt", "same_style"}:
                    attach_regen_take(db, str(config["workbench_session_id"]), work, job.id, config)
                else:
                    attach_render_result(
                        db,
                        str(config["workbench_session_id"]),
                        work.id,
                        job.id,
                    )
            if config.get("remix_intent") and config.get("seed_work_id"):
                from app.services.notifications import notify_remix_done

                source = db.query(Work).filter(Work.id == uuid.UUID(config["seed_work_id"])).first()
                remixer = db.query(User).filter(User.id == job.owner_id).first()
                if source and remixer:
                    notify_remix_done(
                        db,
                        source.owner_id,
                        job.owner_id,
                        config["seed_work_id"],
                        str(work.id),
                        remixer.username,
                    )

            _fan_out_post_process(
                db,
                job_id,
                job.owner_id,
                [str(work.id)],
                result=partial_result,
                audio_staging={str(work.id): staging_key},
            )
            return partial_result

        return run_async(_run())
    except Exception as e:
        from app.services.provider_checkpoint import ProviderAudioPending

        if isinstance(e, ProviderAudioPending):
            return {"recovering": True}
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()


@celery_app.task(name="recover_provider_audio_task")
def recover_provider_audio_task(job_id: str):
    """Download a provider URL that was already paid for, then finish the single-song job."""
    from datetime import datetime

    from app.services.provider_checkpoint import (
        call_expired,
        download_provider_audio,
        read_slot,
        schedule_audio_recover,
        write_slot,
    )

    db = SessionLocal()
    try:
        job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
        if not job or job.status in ("completed", "failed", "cancelled"):
            return {"skipped": True}
        call = read_slot(job)
        if call.get("state") == "stored" and call.get("storage_key"):
            generate_single_task.run(job_id, dict(job.config or {}))
            return {"stored": True}
        url = str(call.get("audio_url") or "")
        if call.get("state") != "ready" or not url:
            return {"skipped": True}
        if call_expired(call):
            fail_job(db, job_id, error_message="音频链接已过期，请重新生成", error_code="GENERATION_FAILED")
            notify_job_terminal_state(job_id)
            return {"expired": True}
        try:
            audio = run_async(download_provider_audio(url, attempts=2))
        except Exception:
            attempts = int(call.get("recover_attempts") or 0) + 1
            write_slot(db, job, "main", {"recover_attempts": attempts})
            if attempts >= 8:
                fail_job(db, job_id, error_message="音频转存失败，请重新生成", error_code="NETWORK_TIMEOUT")
                notify_job_terminal_state(job_id)
                return {"failed": True}
            delay = min(3600, 30 * (2 ** (attempts - 1)))
            remaining = 0
            if call.get("expires_at"):
                try:
                    remaining = int((datetime.fromisoformat(str(call["expires_at"])) - datetime.utcnow()).total_seconds())
                except ValueError:
                    remaining = 3600
            if remaining < delay + 30:
                fail_job(db, job_id, error_message="音频链接即将过期，转存未完成，请重新生成", error_code="NETWORK_TIMEOUT")
                notify_job_terminal_state(job_id)
                return {"expired": True}
            schedule_audio_recover(job_id, countdown=delay)
            return {"retry_in": delay}
        key = str(call.get("storage_key") or get_storage_service().generate_work_key(str(job.owner_id)))
        storage_key, public_url = get_storage_service().upload_bytes(audio, key)
        write_slot(db, job, "main", {"state": "stored", "storage_key": storage_key, "public_url": public_url})
        generate_single_task.run(job_id, dict(job.config or {}))
        return {"stored": True}
    finally:
        db.close()


@celery_app.task(name="generate_cover_task", **_GENERATION_AUTORETRY)
def generate_cover_task(job_id: str, config: dict):
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        start_running(db, job)
        db.refresh(job)

        async def _run():
            work = db.query(Work).filter(Work.id == uuid.UUID(config["work_id"])).first()
            if not work or work.owner_id != job.owner_id:
                raise RuntimeError("Work not found or forbidden")
            ref_url = work.audio_url
            if work.storage_key:
                ref_url = get_storage_service().get_presigned_url(work.storage_key)

            from app.integrations.vendors.router import generate_cover as routed_generate_cover

            cover_result = await routed_generate_cover(
                reference_audio_url=ref_url,
                prompt=config["prompt"],
                lyrics=config.get("lyrics"),
                cover_mode=config.get("cover_mode"),
                modified_lyrics=config.get("modified_lyrics"),
                db=db,
                user_id=str(job.owner_id),
            )

            audio_url = cover_result.get("audio_url") or ref_url
            if cover_result.get("audio_bytes"):
                content = cover_result["audio_bytes"]
            else:
                resp = httpx.get(audio_url, timeout=120)
                resp.raise_for_status()
                content = resp.content
            content_hash = hashlib.sha256(content).hexdigest()
            key = get_storage_service().generate_work_key(str(job.owner_id))
            storage_key, url = get_storage_service().upload_bytes(content, key)
            from app.services.distribution.catalog import clip_windows
            from app.services.media import probe_audio

            probed = probe_audio(content)
            new_work = Work(
                owner_id=job.owner_id,
                title=f"Cover: {work.title}",
                audio_url=url,
                storage_key=storage_key,
                parent_work_id=work.id,
                content_hash=content_hash,
                moods=work.moods,
                genres=work.genres,
                arousal=work.arousal,
                valence=work.valence,
                visibility="private",
                duration=probed.get("duration"),
                post_process_status={"clip_windows": clip_windows(probed.get("duration"))},
            )
            db.add(new_work)
            db.flush()
            db.add(
                ProvenanceRecord(
                    work_id=new_work.id,
                    parent_work_id=work.id,
                    pipeline_version=settings.pipeline_version,
                    step_index=0,
                    record_type="cover",
                    music_request={"prompt": config["prompt"]},
                    output_meta={"sha256": content_hash},
                    job_id=job.id,
                )
            )
            cover_result_payload = {
                "work_id": str(new_work.id),
                "source_work_id": str(work.id),
                "audio_url": url,
                "title": new_work.title,
            }
            staging_key = f"staging/post/{new_work.id}.mp3"
            get_storage_service().upload_bytes(content, staging_key)
            _fan_out_post_process(
                db,
                job_id,
                job.owner_id,
                [str(new_work.id)],
                result=cover_result_payload,
                audio_staging={str(new_work.id): staging_key},
            )
            return cover_result_payload

        return run_async(_run())
    except Exception as e:
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()


VARIATION_SUB_READY = frozenset({"audio_ready", "post_processing", "completed"})


def variation_sub_payload(sub, celery_payload=None) -> dict | None:
    """A take is usable once audio is saved. Post-process keeps the job out of completed."""
    result = getattr(sub, "result", None) if sub is not None else None
    status = getattr(sub, "status", None) if sub is not None else None
    if status in VARIATION_SUB_READY and isinstance(result, dict) and result.get("work_id"):
        return result
    if isinstance(celery_payload, dict) and celery_payload.get("work_id"):
        return celery_payload
    return None


def _ingest_variation_sub_result(
    db,
    *,
    config: dict,
    sub_id: str,
    work_ids: list[str],
    completed_steps: list[dict],
    celery_payload: dict | None = None,
) -> tuple[list[str], list[dict], bool]:
    """Merge a finished variation sub-job into parent aggregates."""
    db.expire_all()
    sub = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(sub_id)).first()
    payload = variation_sub_payload(sub, celery_payload)
    if not payload:
        return work_ids, completed_steps, False

    wid = payload["work_id"]
    if wid in work_ids:
        return work_ids, completed_steps, False

    work_ids = list(work_ids)
    completed_steps = list(completed_steps)
    work_ids.append(wid)
    step_idx = len(work_ids)
    completed_steps.append({
        "work_id": wid,
        "step": step_idx,
        "audio_url": payload.get("audio_url"),
        "title": payload.get("title") or f"变体 #{step_idx}",
    })
    if config.get("seed_work_id"):
        variant = db.query(Work).filter(Work.id == uuid.UUID(wid)).first()
        if variant and not variant.parent_work_id:
            variant.parent_work_id = uuid.UUID(config["seed_work_id"])
            db.commit()
    return work_ids, completed_steps, True


def _publish_variation_parent_progress(
    db,
    *,
    job_id: str,
    job: GenerationJob,
    work_ids: list[str],
    completed_steps: list[dict],
    total: int,
    progress_label: str,
    phase: str = "composing",
    current_step: int | None = None,
) -> GenerationJob | None:
    done_count = len(work_ids)
    job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
    if not job:
        return None
    job.progress = done_count / total if total else 1.0
    job.current_step = current_step if current_step is not None else done_count
    job.status_message = f"{progress_label} {done_count}/{total}"
    job.result = {"work_ids": work_ids, "completed_steps": completed_steps}
    job.phase = phase
    db.commit()
    try:
        from app.services.job_events import publish_job_update

        publish_job_update(job)
    except Exception:
        pass
    return job


def _cancel_variation_parent(db, job_id: str) -> dict:
    from app.services.job_state import transition_job

    transition_job(
        db,
        job_id,
        ("running", "pending"),
        "cancelled",
        error_message="Cancelled by user",
        status_message="已取消",
        phase="cancelled",
    )
    notify_job_terminal_state(job_id)
    return {"cancelled": True}


def _fail_variation_parent_from_sub(db, parent_id: str, sub_id: str, fallback) -> None:
    """Parent job fails with the child error code and phase failed."""
    from app.services.job_errors import classify_error_message

    sub = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(sub_id)).first()
    code = sub.error_code if sub and sub.error_code else None
    msg = (sub.error_message if sub and sub.error_message else None) or str(fallback)
    if not code or code == GENERATION_FAILED:
        code = classify_error_message(msg)
    fail_job(db, parent_id, error_message=msg[:500], error_code=code)


def variation_sub_config(config: dict, index: int, seed_val: int) -> dict:
    """Second+ takes remelt so two versions are not the same vendor roll."""
    from app.services.audio_distance import remelt_av_nudge

    sub = {**config, "seed": seed_val, "title": f"{config.get('title', '变体')} #{index + 1}"}
    for key in (
        "variation_count",
        "seeds",
        "credits_charged",
        "credits_refunded",
        "credits_settled",
        "credits_partial_refund",
    ):
        sub.pop(key, None)
    if index > 0:
        sub["remelt"] = True
        sub["freedom_variant"] = index
        sub["seed"] = (int(seed_val) + 7919 * index) % 1_000_000
        ref = dict(config.get("reference") or {})
        ref["av_offset"] = remelt_av_nudge(index)
        sub["reference"] = ref
        sub["distance_nudge"] = True
    return sub


@celery_app.task(name="generate_variations_task", **_GENERATION_AUTORETRY)
def generate_variations_task(job_id: str, config: dict):
    """Generate variation sub-jobs; parallel apply_async when worker concurrency > 1."""
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        if is_job_cancelled(job_id):
            return {"cancelled": True}

        start_running(db, job)
        db.refresh(job)

        seeds = config.get("seeds") or [hash(str(job.id) + str(i)) % 1_000_000 for i in range(3)]
        sub_jobs: list[tuple[str, dict]] = []

        for i, seed_val in enumerate(seeds):
            sub_id = str(uuid.uuid4())
            sub_config = variation_sub_config(config, i, seed_val)

            sub_job = GenerationJob(
                id=uuid.UUID(sub_id),
                owner_id=job.owner_id,
                job_type="single",
                status="pending",
                total_steps=1,
                config=sub_config,
            )
            db.add(sub_job)
            sub_jobs.append((sub_id, sub_config))
        db.commit()

        from app.services.job_dispatch import store_variation_sub_task
        from app.workers.worker_runtime import can_parallel_variation_dispatch

        total = len(sub_jobs)
        work_ids: list[str] = []
        completed_steps: list[dict] = []
        preview_pick = bool(config.get("preview_pick_mode"))
        progress_label = "预览方案" if preview_pick else "变体"
        parallel = can_parallel_variation_dispatch()

        update_job_phase(
            db,
            job,
            progress=0.02,
            status_message=f"{progress_label} 0/{total}",
            phase="queued",
            current_step=0,
        )

        if parallel:
            pending: list[tuple[str, dict, object]] = []
            for sub_id, sub_config in sub_jobs:
                async_result = generate_single_task.apply_async(args=[sub_id, sub_config])
                store_variation_sub_task(db, job_id, sub_id, async_result.id)
                pending.append((sub_id, sub_config, async_result))

            while pending:
                if is_job_cancelled(job_id):
                    return _cancel_variation_parent(db, job_id)

                still_pending: list[tuple[str, dict, object]] = []
                for sub_id, sub_config, async_result in pending:
                    if not async_result.ready():
                        still_pending.append((sub_id, sub_config, async_result))
                        continue
                    if not async_result.successful():
                        err = async_result.result
                        _fail_variation_parent_from_sub(db, job_id, sub_id, err)
                        return {"failed": True, "sub_id": sub_id}
                    payload = async_result.result if isinstance(async_result.result, dict) else None
                    work_ids, completed_steps, _ = _ingest_variation_sub_result(
                        db,
                        config=config,
                        sub_id=sub_id,
                        work_ids=work_ids,
                        completed_steps=completed_steps,
                        celery_payload=payload,
                    )

                pending = still_pending
                job = _publish_variation_parent_progress(
                    db,
                    job_id=job_id,
                    job=job,
                    work_ids=work_ids,
                    completed_steps=completed_steps,
                    total=total,
                    progress_label=progress_label,
                    phase="composing",
                )
                if not job:
                    break
                if pending:
                    time.sleep(2.0)
        else:
            for idx, (sub_id, sub_config) in enumerate(sub_jobs):
                if is_job_cancelled(job_id):
                    return _cancel_variation_parent(db, job_id)

                update_job_phase(
                    db,
                    job,
                    progress=min(0.95, idx / total if total else 0),
                    status_message=f"{progress_label} {idx}/{total} 生成中…",
                    phase="composing",
                    current_step=idx,
                )

                # `.apply()` runs inline on this worker — avoids deadlock when concurrency=1.
                async_result = generate_single_task.apply(args=[sub_id, sub_config], throw=False)
                store_variation_sub_task(db, job_id, sub_id, async_result.id)
                if not async_result.successful():
                    _fail_variation_parent_from_sub(db, job_id, sub_id, async_result.result)
                    return {"failed": True, "sub_id": sub_id}

                payload = async_result.result if isinstance(async_result.result, dict) else None
                work_ids, completed_steps, _ = _ingest_variation_sub_result(
                    db,
                    config=config,
                    sub_id=sub_id,
                    work_ids=work_ids,
                    completed_steps=completed_steps,
                    celery_payload=payload,
                )
                job = _publish_variation_parent_progress(
                    db,
                    job_id=job_id,
                    job=job,
                    work_ids=work_ids,
                    completed_steps=completed_steps,
                    total=total,
                    progress_label=progress_label,
                    phase="composing",
                    current_step=idx + 1,
                )
                if not job:
                    break

        if work_ids:
            job = db.query(GenerationJob).filter(GenerationJob.id == uuid.UUID(job_id)).first()
            if job:
                final_result = {
                    "work_ids": work_ids,
                    "completed_steps": completed_steps,
                    "partial": len(work_ids) < total,
                }
                complete_at_audio_ready(
                    db,
                    job_id,
                    result=final_result,
                    status_message="变体生成完成",
                )
                if final_result.get("partial"):
                    from app.services.generation_gate import settle_partial_credits
                    settle_partial_credits(db, job, total_expected=total, total_delivered=len(work_ids))
        else:
            fail_job(
                db,
                job_id,
                error_message="变体生成失败",
                error_code=GENERATION_FAILED,
            )
        return {"work_ids": work_ids, "completed_steps": completed_steps}
    except Exception as e:
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()


@celery_app.task(
    name="prepare_release_assets_task",
    queue="post_process",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    max_retries=2,
    retry_backoff_max=300,
    time_limit=900,
    soft_time_limit=840,
)
def prepare_release_assets_task(self, work_id: str, user_id: str):
    """Persist listing WAV + Demucs review stems after mix post-process. ffmpeg is preview-only."""
    from app.services.stem_assets import prepare_release_assets

    db = SessionLocal()
    try:
        work = db.query(Work).filter(Work.id == uuid.UUID(work_id)).first()
        if not work or str(work.owner_id) != str(user_id):
            return {"skipped": True}
        storage = get_storage_service()
        content = None
        if work.storage_key:
            try:
                content = storage.get_object_bytes(work.storage_key)
            except Exception:
                content = None
        if not content:
            return {"error": "audio_missing"}
        meta = prepare_release_assets(db, work, content)
        return {"work_id": work_id, **(meta or {})}
    except Exception as exc:
        logger.warning("release assets failed for %s: %s", work_id, exc)
        return {"error": str(exc)[:300]}
    finally:
        db.close()


def _load_work_audio_bytes(work: Work) -> bytes:
    storage = get_storage_service()
    if work.storage_key:
        try:
            return storage.get_object_bytes(work.storage_key)
        except Exception:
            pass
    url = work.audio_url
    if work.storage_key:
        url = storage.get_presigned_url(work.storage_key)
    resp = httpx.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def _lane_bytes_from_session(session) -> dict[str, bytes]:
    lanes = session.edit_lanes if isinstance(session.edit_lanes, dict) else {}
    keys = lanes.get("keys") if isinstance(lanes.get("keys"), dict) else {}
    out: dict[str, bytes] = {}
    storage = get_storage_service()
    for name, key in keys.items():
        try:
            out[str(name)] = storage.get_object_bytes(str(key))
        except Exception:
            continue
    return out


@celery_app.task(name="workbench_render_task", **_GENERATION_AUTORETRY)
def workbench_render_task(job_id: str, config: dict):
    """Bounce MixGraph to Work B. One stereo master; DistroKid tracks stay 1."""
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        start_running(db, job)
        db.refresh(job)
        from app.models.schemas import WorkbenchSession
        from app.services.media import probe_audio
        from app.services.workbench import attach_render_result
        from app.services.workbench_render import delivery_masters, render_mix_graph

        session_id = str(config.get("session_id") or "")
        source_id = str(config.get("source_work_id") or "")
        source = db.query(Work).filter(Work.id == uuid.UUID(source_id)).first()
        if not source or source.owner_id != job.owner_id:
            raise RuntimeError("Forbidden or missing source work")
        session = None
        if session_id:
            session = (
                db.query(WorkbenchSession)
                .filter(WorkbenchSession.id == uuid.UUID(session_id), WorkbenchSession.owner_id == job.owner_id)
                .first()
            )
        audio = _load_work_audio_bytes(source)
        update_job_phase(db, job, progress=0.25, status_message="正在套效果链…", phase="rendering")
        take_bytes: dict[str, bytes] = {}
        from app.core.mix_graph import clip_take_work_ids

        for token in clip_take_work_ids(config.get("mix_graph") or {}):
            try:
                take_work = db.query(Work).filter(Work.id == uuid.UUID(token), Work.owner_id == job.owner_id).first()
            except ValueError:
                continue
            if take_work:
                blob = _load_work_audio_bytes(take_work)
                if blob:
                    take_bytes[token] = blob
                    take_bytes[str(take_work.id)] = blob
        wav_mix = render_mix_graph(
            audio,
            config.get("mix_graph") or {},
            lane_bytes=_lane_bytes_from_session(session) if session else None,
            take_bytes=take_bytes or None,
            encode="wav",
        )
        masters = delivery_masters(wav_mix, target=str(config.get("loudness_target") or "stream")) if wav_mix else None
        bounced = (masters or {}).get("mp3") or wav_mix
        if not bounced:
            raise RuntimeError("workbench_render_failed")
        if config.get("pack_id"):
            from app.models.schemas import EffectPack
            from app.services.workbench_render import trim_preview

            pack_row = db.query(EffectPack).filter(EffectPack.id == uuid.UUID(str(config["pack_id"]))).first()
            if pack_row and pack_row.is_official and not pack_row.preview_url:
                snippet = trim_preview(bounced, 6.0)
                if snippet:
                    _, preview = get_storage_service().upload_bytes(snippet, f"packs/{pack_row.id}/preview.mp3", "audio/mpeg")
                    pack_row.preview_url = preview
                    db.add(pack_row)
        content_hash = hashlib.sha256(bounced).hexdigest()
        key = get_storage_service().generate_work_key(str(job.owner_id))
        storage_key, url = get_storage_service().upload_bytes(bounced, key)
        owner = db.query(User).filter(User.id == job.owner_id).first()
        probed = probe_audio(bounced)
        from app.services.distribution.catalog import clip_windows

        parent_pps = source.post_process_status if isinstance(source.post_process_status, dict) else {}
        windows = parent_pps.get("clip_windows")
        if not isinstance(windows, list) or not windows:
            windows = clip_windows(probed.get("duration") or source.duration)
        work = Work(
            owner_id=job.owner_id,
            title=config.get("title") or f"{source.title} · 美化",
            audio_url=url,
            storage_key=storage_key,
            cover_url=source.cover_url,
            visibility="private",
            content_hash=content_hash,
            parent_work_id=source.id,
            moods=list(source.moods or []),
            genres=list(source.genres or []),
            arousal=source.arousal,
            valence=source.valence,
            tenant_id=owner.tenant_id if owner else source.tenant_id,
            duration=probed.get("duration") or source.duration,
            preset_id=source.preset_id,
            allow_remix=source.allow_remix,
            license=source.license,
            post_process_status={
                "workbench": True,
                "parent_work_id": str(source.id),
                "clip_windows": windows,
                "sku_kind": parent_pps.get("sku_kind") or "master",
                "tracks": 1,
                "pack_id": config.get("pack_id"),
                "need_tag": ((config.get("mix_graph") or {}).get("need_tags") or [None])[0],
                "graph_hash": config.get("graph_hash"),
                "loudness_target": str(config.get("loudness_target") or "stream"),
            },
        )
        db.add(work)
        db.flush()
        if masters and masters.get("wav"):
            wav_key, wav_url = get_storage_service().upload_bytes(
                masters["wav"], f"works/{work.id}/master.wav", "audio/wav"
            )
            stamped = dict(work.post_process_status or {})
            stamped["master"] = {
                "key": wav_key,
                "url": wav_url,
                "sample_rate": 44100,
                "bit_depth": 24,
                "channels": 2,
            }
            work.post_process_status = stamped
        db.add(
            ProvenanceRecord(
                work_id=work.id,
                parent_work_id=source.id,
                pipeline_version=settings.pipeline_version,
                step_index=0,
                record_type="workbench",
                music_request={
                    "parent_work_id": str(source.id),
                    "pack_id": config.get("pack_id"),
                    "graph_hash": config.get("graph_hash"),
                    "session_id": session_id,
                    "intensity": config.get("intensity"),
                    "mix_graph": config.get("mix_graph"),
                    "edit_lanes": bool(session and isinstance(session.edit_lanes, dict) and session.edit_lanes.get("urls")),
                    "not_store_multitrack": True,
                    "exit": "stereo_master",
                },
                output_meta={
                    "sha256": content_hash,
                    "tracks": 1,
                    "human_edits": [
                        {
                            "kind": "workbench",
                            "section": "master",
                            "note": "beautify_master",
                            "graph_hash": config.get("graph_hash"),
                            "pack_id": config.get("pack_id"),
                            "exit": "stereo_master",
                        }
                    ],
                },
                job_id=job.id,
            )
        )
        if session_id:
            attach_render_result(db, session_id, work.id, job.id)
        staging_key = f"staging/post/{work.id}.mp3"
        get_storage_service().upload_bytes(bounced, staging_key)
        partial = {
            "work_id": str(work.id),
            "work_ids": [str(work.id)],
            "audio_url": url,
            "title": work.title,
            "parent_work_id": str(source.id),
        }
        _fan_out_post_process(
            db,
            job_id,
            job.owner_id,
            [str(work.id)],
            result=partial,
            audio_staging={str(work.id): staging_key},
        )
        return partial
    except Exception as e:
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()


@celery_app.task(name="lane_separate_task", **_GENERATION_AUTORETRY)
def lane_separate_task(job_id: str, config: dict):
    """Demucs → edit_lanes bucket only. Never writes originality.zip."""
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        start_running(db, job)
        from app.core.lyrics_structure import tag_sequence
        from app.models.schemas import WorkbenchSession
        from app.services.form_marks import estimate_sections
        from app.services.media import transcode_audio
        from app.services.stem_assets import preview_stems_ffmpeg, separate_demucs_cached
        from app.services.workbench import persist_edit_lanes

        session = db.query(WorkbenchSession).filter(WorkbenchSession.id == uuid.UUID(config["session_id"])).first()
        source = db.query(Work).filter(Work.id == uuid.UUID(config["source_work_id"])).first()
        if not session or not source or source.owner_id != job.owner_id:
            raise RuntimeError("Forbidden or missing session")
        audio = _load_work_audio_bytes(source)
        two = str(config.get("profile") or "") == "vocals2"
        stems, quality = separate_demucs_cached(audio, two_stems=two)
        if not stems:
            stems, _isolation = preview_stems_ffmpeg(audio)
            quality = "preview"
        if not stems:
            raise RuntimeError("edit_lanes_unavailable")
        storage = get_storage_service()
        keys: dict[str, str] = {}
        urls: dict[str, str] = {}
        flac_urls: dict[str, str] = {}
        for name, blob in stems.items():
            wav_key = f"sessions/{session.id}/edit_lanes/{name}.wav"
            stored, _wav_url = storage.upload_bytes(blob, wav_key, "audio/wav")
            keys[name] = stored
            flac = transcode_audio(blob, fmt="flac")
            if flac:
                _flac_key, flac_url = storage.upload_bytes(flac, f"sessions/{session.id}/edit_lanes/{name}.flac", "audio/flac")
                flac_urls[name] = flac_url
            proxy = transcode_audio(blob, fmt="mp3", bitrate="128k") or blob
            _proxy_key, url = storage.upload_bytes(proxy, f"sessions/{session.id}/edit_lanes/{name}.mp3", "audio/mpeg")
            urls[name] = url
        lyrics = ""
        pps = source.post_process_status if isinstance(source.post_process_status, dict) else {}
        if isinstance(pps.get("lyrics"), str):
            lyrics = pps["lyrics"]
        marks = estimate_sections(audio, lyrics, duration_hint=source.duration)
        label = "分轨" if quality == "demucs" else "预览近似"
        persist_edit_lanes(db, session, urls, keys, quality=quality, marks=marks, label=label, flac_urls=flac_urls)
        db.commit()
        result = {
            "session_id": str(session.id),
            "edit_lanes": list(urls.keys()),
            "label": label,
            "marks": len(marks),
            "tags": tag_sequence(lyrics),
            "grade": "edit",
            "not_review_stems": True,
            "not_store_tracks": True,
        }
        from app.services.job_state import complete_at_audio_ready

        complete_at_audio_ready(db, job_id, result=result, status_message="编辑分轨已就绪")
        return result
    except Exception as e:
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()


@celery_app.task(name="pack_preview_task", **_GENERATION_AUTORETRY)
def pack_preview_task(job_id: str, config: dict):
    db = SessionLocal()
    try:
        job = verify_worker_job(db, job_id, config)
        start_running(db, job)
        from app.models.schemas import EffectPack
        from app.services.workbench_render import render_mix_graph, trim_preview

        pack = db.query(EffectPack).filter(EffectPack.id == uuid.UUID(config["pack_id"])).first()
        source = db.query(Work).filter(Work.id == uuid.UUID(config["source_work_id"])).first()
        from app.services.ecosystem import ensure_catalog_owner
        from app.services.workbench import preview_source_allowed

        catalog = ensure_catalog_owner(db)
        if not pack or not source or not preview_source_allowed(
            job_owner_id=job.owner_id,
            source_owner_id=source.owner_id,
            official=bool(pack.is_official),
            catalog_owner_id=catalog.id,
        ):
            raise RuntimeError("Forbidden or missing pack preview source")
        audio = _load_work_audio_bytes(source)
        snippet = trim_preview(audio, 6.0) or audio
        bounced = render_mix_graph(snippet, pack.mix_graph or {})
        if not bounced:
            raise RuntimeError("pack_preview_failed")
        key = f"packs/{pack.id}/preview.mp3"
        _, url = get_storage_service().upload_bytes(bounced, key, "audio/mpeg")
        pack.preview_url = url
        db.add(pack)
        db.commit()
        result = {"pack_id": str(pack.id), "preview_url": url}
        from app.services.job_state import complete_at_audio_ready

        complete_at_audio_ready(db, job_id, result=result, status_message="预听已就绪")
        return result
    except Exception as e:
        db.rollback()
        _fail_from_exception(db, job_id, e)
        raise
    finally:
        db.close()
