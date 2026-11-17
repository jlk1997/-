"""Reliable one-click delivery: isolate channels, retry with backoff, reconcile stuck rows."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, Release, ReleaseMetadata, User, Work
from app.services.distribution.adapters import AdapterResult, get_adapter
from app.services.distribution.kit import build_self_release_kit
from app.services.notifications import create_notification
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


PENDING_STATUSES = {"submitting"}
HOLD_STATUSES = {"ops_queue", "awaiting_manual", "in_review", "session_wait", "session_running", "metrics_only"}
TERMINAL_STATUSES = {"live", "taken_down", "rejected"}
PUBLISHING_STATUSES = PENDING_STATUSES | HOLD_STATUSES
SESSION_STATUSES = {"session_wait", "session_running"}
HOLD_RETRY_STATUSES = ("ops_queue", "awaiting_manual", "session_wait", "session_running")
EDITABLE_RELEASE = {"draft", "qc", "pending_license"}
ACTIVE_RELEASE = {"queued", "delivering", "live"}
MAX_AUTO_RETRIES = 8
STALE_SUBMITTING_SECONDS = 90


def _receipt_live(row) -> bool:
    from app.services.distribution.catalog import delivery_has_live_receipt

    return getattr(row, "status", None) == "live" and delivery_has_live_receipt(row)


def delivery_progress(rows) -> dict:
    rows = list(rows or [])
    live = sum(1 for row in rows if _receipt_live(row))
    rejected = sum(1 for row in rows if row.status == "rejected")
    taken_down = sum(1 for row in rows if row.status == "taken_down")
    publishing = sum(
        1
        for row in rows
        if row.status in PUBLISHING_STATUSES or (row.status == "live" and not _receipt_live(row))
    )
    active = [row for row in rows if row.status != "taken_down"]
    if not rows:
        release_status = None
    elif not active:
        release_status = "taken_down"
    elif publishing:
        release_status = "delivering"
    elif live:
        release_status = "live"
    elif active and all(row.status == "rejected" for row in active):
        release_status = "rejected"
    else:
        release_status = "queued"
    return {
        "release_status": release_status,
        "total": len(rows),
        "live": live,
        "publishing": publishing,
        "rejected": rejected,
        "taken_down": taken_down,
        "can_takedown": live > 0 or publishing > 0,
        "can_retry": rejected > 0 or publishing > 0,
    }


def backoff_delta(retry_count: int) -> timedelta:
    steps = max(0, int(retry_count) - 1)
    return timedelta(seconds=min(3600, 30 * (2**steps)))


def replay_plan(row: DistributionDelivery, now: datetime | None = None) -> tuple[bool, bool]:
    """Whether a submitting row should be processed, and whether to ignore backoff."""
    now = now or datetime.utcnow()
    due = not row.next_retry_at or row.next_retry_at <= now
    stale = not row.last_attempt_at or row.last_attempt_at <= now - timedelta(seconds=STALE_SUBMITTING_SECONDS)
    if stale:
        return True, True
    if due:
        return True, False
    return False, False


def _lock_delivery(db: Session, delivery_id) -> DistributionDelivery | None:
    query = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id))
    try:
        return query.with_for_update(skip_locked=True).first()
    except Exception:
        logger.warning("skip_locked unavailable, falling back to unlocked read")
        return query.first()


def adapter_submit_safe(provider: str, payload: dict) -> AdapterResult:
    adapter = get_adapter(provider)
    try:
        return adapter.submit(payload)
    except Exception as exc:
        logger.exception("adapter %s submit failed", provider)
        return AdapterResult(ok=False, status="submitting", message=str(exc)[:500])


def ensure_kit_for_release(db: Session, release: Release, *, force: bool = False) -> bool:
    if not force and release.kit_storage_key:
        try:
            data = get_storage_service().get_object_bytes(release.kit_storage_key)
            if data:
                return True
        except Exception:
            logger.warning("kit missing for %s, rebuilding", release.id)
    work = db.query(Work).filter(Work.id == release.work_id).first()
    if not work:
        return False
    audio = None
    if work.storage_key:
        try:
            audio = get_storage_service().get_object_bytes(work.storage_key)
        except Exception:
            audio = None
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    try:
        kit = build_self_release_kit(work=work, release=release, meta=meta, audio_bytes=audio, db=db)
    except Exception:
        logger.exception("kit build failed for %s", release.id)
        return False
    release.kit_storage_key = kit["key"]
    release.kit_url = kit["url"]
    return True


def refresh_release_progress(db: Session, release: Release) -> None:
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    work = db.query(Work).filter(Work.id == release.work_id).first()
    plan = delivery_progress(rows)
    if not plan["release_status"]:
        return
    release.status = plan["release_status"]
    if work:
        work.release_status = plan["release_status"]
        if plan["release_status"] == "live" and not work.commercial_cleared_at:
            work.commercial_cleared_at = datetime.utcnow()
    if plan["rejected"] and plan["live"] == 0 and plan["publishing"] == 0:
        release.error_message = release.error_message or "all_channels_rejected"


def apply_query_result(delivery: DistributionDelivery, result: AdapterResult) -> bool:
    """Copy partner query fields onto a delivery. Returns True if anything changed."""
    from app.services.distribution.catalog import extract_store_ref, has_live_receipt, looks_like_store_page

    changed = False
    if result.store_url and result.store_url != delivery.store_url:
        if looks_like_store_page(result.store_url, getattr(delivery, "channel_code", None)):
            delivery.store_url = result.store_url
            changed = True
    external_id = result.external_id or delivery.external_id
    if not external_id and (result.store_url or delivery.store_url):
        external_id = extract_store_ref(result.store_url or delivery.store_url, getattr(delivery, "channel_code", None))
    if external_id and external_id != delivery.external_id:
        delivery.external_id = external_id
        changed = True
    new_status = result.status
    if new_status == "live" and not has_live_receipt(store_url=delivery.store_url, external_id=delivery.external_id, channel_code=getattr(delivery, "channel_code", None)):
        new_status = None
    allowed = PENDING_STATUSES | HOLD_STATUSES | TERMINAL_STATUSES
    if new_status and new_status in allowed and new_status != delivery.status:
        delivery.status = new_status
        changed = True
    return changed


def notify_distribution_status(
    db: Session,
    owner_id,
    *,
    release_id: str,
    status: str,
    channel_code: str | None = None,
    message: str | None = None,
    commit: bool = False,
) -> None:
    body = message or f"{channel_code or ''} 状态更新为 {status}".strip()
    create_notification(
        db,
        owner_id,
        "distribution_status",
        {
            "release_id": release_id,
            "channel_code": channel_code,
            "status": status,
            "message": body,
        },
        commit=commit,
    )
    from app.services.notifications import notify_key_event_sync

    titles = {
        "live": "店页已回执上架",
        "ops_queue": "已交运营继续发",
        "session_wait": "待连接器交店",
        "session_running": "连接器代交中",
        "rejected": "发行被拒",
        "takedown": "已下架",
    }
    notify_key_event_sync(
        db,
        owner_id,
        "distribution_status",
        title=titles.get(status, "发行状态更新"),
        body=body,
        data={"release_id": release_id, "ref": release_id, "status": status, "channel_code": channel_code},
        skip_in_app=True,
    )


def partner_work_payload(work: Work | None, meta: ReleaseMetadata | None, delivery: DistributionDelivery) -> dict:
    from app.services.distribution.asset_profiles import listing_master_ref

    if not work:
        return {}
    ref = listing_master_ref(work)
    pps = dict(work.post_process_status or {})
    duration = getattr(work, "duration", None)
    duration_ms = int(float(duration) * 1000) if duration else None
    return {
        "title": (meta.title if meta else None) or work.title,
        "artist_name": meta.artist_name if meta else None,
        "isrc": (meta.isrc if meta else None) or work.isrc,
        "audio_url": ref.get("audio_url"),
        "master_wav_url": ref.get("wav_url"),
        "cover_url": (meta.cover_url if meta else None) or work.cover_url,
        "genres": (meta.genres if meta else None) or (work.genres or []),
        "language": (meta.language if meta else None) or "zh",
        "duration_ms": duration_ms,
        "explicit": False,
        "ai_generated": bool(getattr(work, "is_ai_generated", True)),
        "ai_disclosed": bool(meta.ai_disclosed) if meta is not None else True,
        "instrumental": str(pps.get("sku_kind") or "") == "instrumental",
        "sku_kind": pps.get("sku_kind"),
    }


def _delivery_payload(db: Session, delivery: DistributionDelivery, release: Release) -> dict:
    from app.config import settings

    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    work = db.query(Work).filter(Work.id == release.work_id).first()
    callback = ""
    base = (getattr(settings, "api_public_url", "") or "").rstrip("/")
    if base:
        callback = f"{base}/distribution/partner/webhook"
    work_payload = partner_work_payload(work, meta, delivery)
    extra = (meta.extra if meta and isinstance(meta.extra, dict) else {}) or {}
    return {
        "release_id": str(release.id),
        "delivery_id": str(delivery.id),
        "channel": delivery.channel_code,
        "mode": release.mode,
        "title": work_payload.get("title"),
        "artist_name": work_payload.get("artist_name"),
        "isrc": work_payload.get("isrc"),
        "has_kit": bool(release.kit_storage_key),
        "kit_url": release.kit_url,
        "external_id": delivery.external_id,
        "callback_url": callback,
        "listing_asset": "master",
        "release": {
            "id": str(release.id),
            "upc": (meta.upc if meta else None) or getattr(release, "upc", None),
            "release_date": extra.get("release_date"),
            "territories": extra.get("territories") or ["worldwide"],
        },
        "delivery": {
            "id": str(delivery.id),
            "track_code": delivery.external_id or work_payload.get("isrc"),
            "channel_code": delivery.channel_code,
        },
        "work": work_payload,
    }


def process_one_delivery(
    db: Session,
    delivery: DistributionDelivery,
    *,
    force: bool = False,
    notify: bool = True,
    commit: bool = False,
) -> dict:
    release = db.query(Release).filter(Release.id == delivery.release_id).first()
    if not release:
        return {"id": str(delivery.id), "skipped": True, "reason": "release_missing"}
    if delivery.status in TERMINAL_STATUSES and not force:
        return {"id": str(delivery.id), "skipped": True, "reason": "terminal", "status": delivery.status}
    if delivery.status in HOLD_STATUSES and not force:
        return {"id": str(delivery.id), "skipped": True, "reason": "holding", "status": delivery.status}
    now = datetime.utcnow()
    if (
        not force
        and delivery.next_retry_at
        and delivery.next_retry_at > now
        and delivery.status == "submitting"
    ):
        return {"id": str(delivery.id), "skipped": True, "reason": "backoff"}

    previous = delivery.status
    delivery.last_attempt_at = now
    delivery.retry_count = (delivery.retry_count or 0) + 1
    kit_ok = ensure_kit_for_release(db, release)
    from app.services.distribution.catalog import pick_configured_aggregator
    from app.services.distribution.assist import park_for_session, route_delivery

    picked = pick_configured_aggregator(delivery.channel_code)
    if picked:
        delivery.distributor_code = picked
    meta = dict(delivery.attempt_meta or {})
    meta.update({
        "kit_ready": kit_ok,
        "attempted_at": now.isoformat(),
        "channel": delivery.channel_code,
        "distributor": delivery.distributor_code,
    })
    delivery.attempt_meta = meta
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(
        delivery,
        event="platform_submit",
        actor="platform",
        message=f"平台主体交歌 · {delivery.distributor_code}",
    )

    route = route_delivery(delivery)
    # Set trust tier
    if route == "partner":
        delivery.delivery_tier = "api_verified"
    elif route in {"session_assist", "connector"}:
        delivery.delivery_tier = "assisted"
    else:
        delivery.delivery_tier = "ops_pending"

    if route == "partner":
        adapter = get_adapter(delivery.distributor_code)
        if adapter.configured():
            work = db.query(Work).filter(Work.id == release.work_id).first()
            from app.services.distribution.asset_profiles import listing_master_ref

            ref = listing_master_ref(work) if work else {}
            if work and not ref.get("wav_key"):
                audio = None
                if work.storage_key:
                    try:
                        audio = get_storage_service().get_object_bytes(work.storage_key)
                    except Exception:
                        audio = None
                if audio:
                    try:
                        from app.services.stem_assets import persist_master_wav

                        persist_master_wav(work, audio)
                        db.add(work)
                        db.flush()
                        ref = listing_master_ref(work)
                    except Exception:
                        logger.warning("master wav persist failed for work %s", work.id)
                if not ref.get("wav_key"):
                    delivery.status = "submitting"
                    delivery.last_error = "waiting_master_wav"
                    delivery.next_retry_at = now + timedelta(seconds=45)
                    delivery.retry_count = max(0, (delivery.retry_count or 1) - 1)
                    meta["waiting_master_wav"] = True
                    delivery.attempt_meta = meta
                    refresh_release_progress(db, release)
                    if commit:
                        db.commit()
                    return {
                        "id": str(delivery.id),
                        "status": delivery.status,
                        "previous": previous,
                        "retry_count": delivery.retry_count,
                        "last_error": delivery.last_error,
                        "reason": "waiting_master_wav",
                    }

    if route == "metrics":
        delivery.status = "metrics_only"
        delivery.last_error = None
        delivery.delivery_tier = "assisted"
        from app.services.distribution.assist import hydrate_assist_meta

        hydrate_assist_meta(db, delivery, release)
        append_delivery_event(
            delivery,
            event="metrics_only",
            actor="platform",
            message="这家店不接受个人直传。连接器只收播放与收益，不代交母带。",
        )
        refresh_release_progress(db, release)
        if notify and previous != delivery.status:
            notify_distribution_status(
                db,
                release.owner_id,
                release_id=str(release.id),
                status=delivery.status,
                channel_code=delivery.channel_code,
                message=f"{delivery.channel_code} 只收数据，不能个人直传",
            )
        if commit:
            db.commit()
        return {
            "id": str(delivery.id),
            "status": delivery.status,
            "previous": previous,
            "retry_count": delivery.retry_count,
            "last_error": delivery.last_error,
            "route": "metrics",
        }

    if route == "ops":
        delivery.status = "ops_queue"
        delivery.last_error = None
        from app.services.distribution.assist import hydrate_assist_meta

        hydrate_assist_meta(db, delivery, release)
        refresh_release_progress(db, release)
        if notify and previous != delivery.status:
            notify_distribution_status(
                db,
                release.owner_id,
                release_id=str(release.id),
                status=delivery.status,
                channel_code=delivery.channel_code,
                message=f"{delivery.channel_code} 进运营队列，不是故障",
            )
        if commit:
            db.commit()
        return {
            "id": str(delivery.id),
            "status": delivery.status,
            "previous": previous,
            "retry_count": delivery.retry_count,
            "last_error": delivery.last_error,
            "route": "ops",
        }

    if route in {"session_assist", "connector"}:
        park_for_session(db, delivery, release)
        from app.services.distribution.direct import maybe_link_direct_binding

        maybe_link_direct_binding(db, delivery, release)
        refresh_release_progress(db, release)
        if notify and previous != delivery.status:
            notify_distribution_status(
                db,
                release.owner_id,
                release_id=str(release.id),
                status=delivery.status,
                channel_code=delivery.channel_code,
                message=f"{delivery.channel_code} 已排队一键投递：{delivery.status}",
            )
        if commit:
            db.commit()
        return {
            "id": str(delivery.id),
            "status": delivery.status,
            "previous": previous,
            "retry_count": delivery.retry_count,
            "last_error": delivery.last_error,
            "route": "session_assist",
        }

    result = adapter_submit_safe(
        delivery.distributor_code,
        _delivery_payload(db, delivery, release),
    )
    adapter = get_adapter(delivery.distributor_code)
    if result.ok and adapter.configured() and not result.kit_required:
        from app.services.distribution.catalog import extract_store_ref, has_live_receipt, looks_like_store_page

        incoming = result.status if result.status in {"in_review", "live", "ops_queue", "submitting"} else "in_review"
        delivery.external_id = result.external_id or delivery.external_id
        if result.store_url and looks_like_store_page(result.store_url, delivery.channel_code):
            delivery.store_url = result.store_url
        if not delivery.external_id and delivery.store_url:
            delivery.external_id = extract_store_ref(delivery.store_url, delivery.channel_code)
        if incoming == "live" and not has_live_receipt(store_url=delivery.store_url, external_id=delivery.external_id, channel_code=delivery.channel_code):
            incoming = "in_review"
        delivery.status = incoming
        delivery.last_error = None
        delivery.next_retry_at = None
        delivery.reject_reason = result.message
        from app.services.distribution.reject import writeback_catalog_codes

        writeback_catalog_codes(db, delivery, isrc=getattr(result, "isrc", None), upc=getattr(result, "upc", None))
    elif result.ok:
        park_for_session(db, delivery, release)
        delivery.reject_reason = result.message
    elif (delivery.retry_count or 0) >= MAX_AUTO_RETRIES:
        delivery.status = "ops_queue" if release.mode == "label" else "rejected"
        delivery.last_error = result.message or "auto retries exhausted"
        delivery.next_retry_at = None
        delivery.reject_reason = delivery.last_error
    else:
        delivery.status = "submitting"
        delivery.last_error = result.message or "adapter submit failed"
        delivery.next_retry_at = now + backoff_delta(delivery.retry_count)
        delivery.reject_reason = delivery.last_error

    if delivery.status in {"ops_queue", "awaiting_manual"}:
        from app.services.distribution.assist import hydrate_assist_meta

        hydrate_assist_meta(db, delivery, release)

    refresh_release_progress(db, release)
    if previous != "live" and delivery.status == "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, delivery)
    if notify and previous != delivery.status:
        notify_distribution_status(
            db,
            release.owner_id,
            release_id=str(release.id),
            status=delivery.status,
            channel_code=delivery.channel_code,
            message=f"{delivery.channel_code} 已提交：{delivery.status}",
        )
    if commit:
        db.commit()
    return {
        "id": str(delivery.id),
        "status": delivery.status,
        "previous": previous,
        "retry_count": delivery.retry_count,
        "last_error": delivery.last_error,
    }


def process_release_submit(db: Session, release_id: str, *, force: bool = False, commit: bool = True) -> dict:
    release = db.query(Release).filter(Release.id == _as_uuid(release_id)).first()
    if not release:
        return {"release_id": str(release_id), "processed": 0}
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    processed = []
    for row in rows:
        try:
            with db.begin_nested():
                locked = _lock_delivery(db, row.id)
                if not locked:
                    processed.append({"id": str(row.id), "skipped": True, "reason": "locked"})
                    continue
                processed.append(process_one_delivery(db, locked, force=force, notify=True, commit=False))
        except Exception as exc:
            logger.exception("isolated delivery %s failed", row.id)
            try:
                fresh = db.query(DistributionDelivery).filter(DistributionDelivery.id == row.id).first()
                if fresh and fresh.status not in TERMINAL_STATUSES:
                    fresh.status = "submitting"
                    fresh.last_error = str(exc)[:500]
                    fresh.next_retry_at = datetime.utcnow() + backoff_delta(fresh.retry_count or 1)
                processed.append({"id": str(row.id), "status": "submitting", "error": str(exc)[:200]})
            except Exception:
                logger.exception("could not persist isolated failure for %s", row.id)
                processed.append({"id": str(row.id), "error": str(exc)[:200]})
    refresh_release_progress(db, release)
    if commit:
        db.commit()
        from app.services.seats.runtime import kick_seat_runtime

        kick_seat_runtime()
    return {"release_id": str(release.id), "processed": len(processed), "deliveries": processed}


def dispatch_release_submit(release_id: str, *, process_now: bool = True) -> dict:
    from app.database import SessionLocal

    sync_result = None
    if process_now:
        db = SessionLocal()
        try:
            sync_result = process_release_submit(db, release_id)
        finally:
            db.close()
    queued = False
    try:
        from app.workers.distribution_tasks import submit_release_task

        submit_release_task.apply_async(args=[str(release_id)], queue="distribution")
        queued = True
    except Exception as exc:
        logger.warning("Could not enqueue submit_release_task: %s", exc)
        if not process_now:
            db = SessionLocal()
            try:
                sync_result = process_release_submit(db, release_id)
            finally:
                db.close()
    return {"queued": queued, "sync": sync_result}


def dispatch_delivery(delivery_id: str, release_id: str, *, process_now: bool = True) -> None:
    from app.database import SessionLocal

    if process_now:
        db = SessionLocal()
        try:
            row = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
            if row:
                process_one_delivery(db, row, force=True, commit=True)
        finally:
            db.close()
    try:
        from app.workers.distribution_tasks import process_delivery_task

        process_delivery_task.apply_async(args=[str(delivery_id)], queue="distribution")
    except Exception:
        logger.warning("Could not enqueue process_delivery_task for %s", delivery_id)


def reconcile_distribution(db: Session) -> dict:
    from app.services.distribution.catalog import (
        connected_channel_codes,
        default_upload_channels,
        distributor_for_code,
        seed_distribution_catalog,
    )

    seed_distribution_catalog(db)
    now = datetime.utcnow()
    submitting = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.status == "submitting")
        .limit(200)
        .all()
    )
    replayed = 0
    isolated_errors = 0
    for row in submitting:
        should_run, force = replay_plan(row, now)
        if not should_run:
            continue
        try:
            with db.begin_nested():
                locked = _lock_delivery(db, row.id)
                if not locked:
                    continue
                process_one_delivery(db, locked, force=force, notify=False, commit=False)
                replayed += 1
        except Exception:
            isolated_errors += 1
            logger.exception("reconcile replay failed for %s", row.id)

    queued_empty = (
        db.query(Release)
        .filter(Release.status.in_(("queued", "delivering")))
        .limit(100)
        .all()
    )
    repaired = 0
    for release in queued_empty:
        count = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).count()
        if count:
            if not release.kit_storage_key:
                ensure_kit_for_release(db, release)
            refresh_release_progress(db, release)
            continue
        owner = db.query(User).filter(User.id == release.owner_id).first()
        codes = release.selected_channels or default_upload_channels(
            connected=connected_channel_codes(db, owner)
        )
        for code in codes:
            distributor = distributor_for_code(db, code)
            if not distributor:
                continue
            db.add(
                DistributionDelivery(
                    release_id=release.id,
                    work_id=release.work_id,
                    owner_id=release.owner_id,
                    channel_code=code,
                    distributor_code=distributor,
                    status="submitting",
                )
            )
            repaired += 1
        db.flush()
        try:
            process_release_submit(db, str(release.id), commit=False)
        except Exception:
            isolated_errors += 1
            logger.exception("reconcile repair process failed for %s", release.id)

    kits = 0
    holds = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.status.in_(HOLD_RETRY_STATUSES))
        .limit(100)
        .all()
    )
    seen = set()
    for row in holds:
        if row.release_id in seen:
            continue
        seen.add(row.release_id)
        release = db.query(Release).filter(Release.id == row.release_id).first()
        if release and ensure_kit_for_release(db, release):
            kits += 1
        if release:
            work = db.query(Work).filter(Work.id == release.work_id).first()
            if work:
                from app.services.distribution.automation import copy_priority_to_deliveries

                copy_priority_to_deliveries(db, work, release)

    from app.services.distribution.assist import expire_stale_session_jobs, refresh_assist_jobs
    from app.services.seats.service import heal_seat_runtime

    healed = heal_seat_runtime(db)
    assist_refreshed = refresh_assist_jobs(db, limit=80)

    session_expired = expire_stale_session_jobs(db, now=now)
    from app.services.distribution.direct import link_session_directs

    direct_linked = link_session_directs(db, limit=20)
    partner_retried = retry_configured_partner_holds(db, limit=40)

    from app.services.distribution.automation import remind_stale_deliveries

    sla_reminded = remind_stale_deliveries(db, now=now)
    from app.services.distribution.automation import escalate_overdue_deliveries

    sla_escalated = escalate_overdue_deliveries(db, now=now)

    db.commit()
    from app.services.seats.runtime import kick_seat_runtime

    kick_seat_runtime(enqueue_due_harvest=True)
    return {
        "replayed": replayed,
        "repaired_deliveries": repaired,
        "kits_ensured": kits,
        "checked_submitting": len(submitting),
        "isolated_errors": isolated_errors,
        "partner_retried": partner_retried,
        "session_expired": session_expired,
        "healed": healed,
        "assist_refreshed": assist_refreshed,
        "direct_linked": direct_linked,
        "sla_reminded": sla_reminded,
        "sla_escalated": sla_escalated,
    }


def retry_configured_partner_holds(db: Session, *, limit: int = 40) -> int:
    """If a signed partner endpoint appears after a hold, submit once without ops paste."""
    from app.services.distribution.catalog import pick_configured_aggregator

    rows = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.status.in_(HOLD_RETRY_STATUSES))
        .order_by(DistributionDelivery.updated_at.desc(), DistributionDelivery.created_at.desc())
        .limit(min(max(limit, 1), 80))
        .all()
    )
    retried = 0
    for row in rows:
        picked = pick_configured_aggregator(row.channel_code)
        adapter = get_adapter(picked or row.distributor_code)
        if not adapter.configured():
            continue
        meta = dict(row.attempt_meta or {})
        if row.status in {"session_wait", "session_running"} and meta.get("route") == "session_assist":
            continue
        raw = meta.get("partner_auto_retried_at")
        if raw:
            try:
                if datetime.fromisoformat(str(raw)) > datetime.utcnow() - timedelta(minutes=15):
                    continue
            except ValueError:
                pass
        if picked:
            row.distributor_code = picked
        row.status = "submitting"
        row.next_retry_at = None
        meta["partner_auto_retried_at"] = datetime.utcnow().isoformat()
        meta["route"] = "partner"
        row.attempt_meta = meta
        process_one_delivery(db, row, force=True, commit=False)
        retried += 1
    return retried


def distribution_health(db: Session) -> dict:
    from sqlalchemy import func

    def _count(*statuses: str) -> int:
        return (
            db.query(func.count(DistributionDelivery.id))
            .filter(DistributionDelivery.status.in_(statuses))
            .scalar()
            or 0
        )

    from sqlalchemy import exists

    stale = (
        db.query(func.count(DistributionDelivery.id))
        .filter(
            DistributionDelivery.status == "submitting",
            DistributionDelivery.updated_at < datetime.utcnow() - timedelta(minutes=5),
        )
        .scalar()
        or 0
    )
    empty_queued = (
        db.query(func.count(Release.id))
        .filter(Release.status.in_(("queued", "delivering")))
        .filter(~exists().where(DistributionDelivery.release_id == Release.id))
        .scalar()
        or 0
    )
    submitting = _count("submitting")
    from app.services.distribution.service import SLA_HOURS

    sla_cutoff = datetime.utcnow() - timedelta(hours=SLA_HOURS)
    sla_overdue = (
        db.query(func.count(DistributionDelivery.id))
        .filter(
            DistributionDelivery.status.in_(
                ("ops_queue", "awaiting_manual", "in_review", "submitting", "session_wait", "session_running")
            ),
            DistributionDelivery.created_at <= sla_cutoff,
        )
        .scalar()
        or 0
    )
    from app.services.distribution.adapters import ADAPTERS

    partner_ready = [name for name, adapter in ADAPTERS.items() if name != "session" and adapter.configured()]
    return {
        "submitting": submitting,
        "ops_queue": _count("ops_queue"),
        "awaiting_manual": _count("awaiting_manual"),
        "session_wait": _count("session_wait"),
        "session_running": _count("session_running"),
        "in_review": _count("in_review"),
        "live": _count("live"),
        "rejected": _count("rejected"),
        "stale_submitting": stale,
        "queued_without_deliveries": empty_queued,
        "sla_overdue": sla_overdue,
        "partner_ready": partner_ready,
        "partner_count": len(partner_ready),
        "healthy": stale == 0 and empty_queued == 0 and sla_overdue == 0,
    }
