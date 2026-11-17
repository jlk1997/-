"""Session-assist jobs: connector or ops completes the official portal with the same kit."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import ConnectorIngestToken, DistributionDelivery, Release, ReleaseMetadata, User, Work
from app.services.distribution.catalog import (
    channel_delivery_mode,
    channel_hosts,
    channel_upload_url,
    clip_windows,
    delivery_has_live_receipt,
    extract_store_ref,
    looks_like_store_page,
    volume_rank,
)

HEARTBEAT_SECONDS = 180
LEASE_WAIT_NOTE = "farm_or_extension_lease_wait"
SESSION_STATUSES = {"session_wait", "session_running"}
ASSIST_LIST_STATUSES = SESSION_STATUSES | {"ops_queue", "awaiting_manual"}


def is_lease_wait_error(err: str | None) -> bool:
    return bool(err) and LEASE_WAIT_NOTE in str(err)


def seat_has_session(seat) -> bool:
    return bool(seat and (getattr(seat, "extra", None) or {}).get("has_session") is True)


def resolve_delivery_seat(db: Session, delivery: DistributionDelivery):
    from app.models.schemas import CreatorSeat

    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    if not seat_id:
        return None
    try:
        return db.query(CreatorSeat).filter(CreatorSeat.id == _as_uuid(seat_id)).first()
    except (ValueError, TypeError):
        return None


def delivery_has_active_upload_job(db: Session, delivery: DistributionDelivery) -> bool:
    from app.models.schemas import SeatJob

    wanted = str(delivery.id)
    q = db.query(SeatJob.id).filter(
        SeatJob.kind == "upload",
        SeatJob.status.in_(("queued", "leased")),
        SeatJob.payload["delivery_id"].astext == wanted,
    )
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    if seat_id:
        try:
            q = q.filter(SeatJob.seat_id == _as_uuid(seat_id))
        except (ValueError, TypeError):
            pass
    return q.first() is not None


def delivery_machine_pending(db: Session, delivery: DistributionDelivery) -> bool:
    if delivery_has_active_upload_job(db, delivery):
        return True
    return delivery_has_live_session(db, delivery)


def delivery_has_live_session(db: Session, delivery: DistributionDelivery) -> bool:
    return seat_has_session(resolve_delivery_seat(db, delivery))


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def assist_ttl() -> timedelta:
    return timedelta(minutes=max(5, int(getattr(settings, "assist_job_ttl_minutes", 45) or 45)))


def has_connector_heartbeat(db: Session, user_id) -> bool:
    cutoff = datetime.utcnow() - timedelta(seconds=HEARTBEAT_SECONDS)
    row = (
        db.query(ConnectorIngestToken)
        .filter(
            ConnectorIngestToken.user_id == user_id,
            ConnectorIngestToken.revoked_at.is_(None),
            ConnectorIngestToken.last_used_at.isnot(None),
            ConnectorIngestToken.last_used_at >= cutoff,
        )
        .first()
    )
    return bool(row)


def promote_session_if_online(db: Session, user: User) -> int:
    if not has_connector_heartbeat(db, user.id):
        return 0
    q = db.query(DistributionDelivery).filter(DistributionDelivery.status == "session_wait")
    if not getattr(user, "is_admin", False):
        q = q.filter(DistributionDelivery.owner_id == user.id)
    rows = q.limit(80).all()
    moved = 0
    for row in rows:
        if not delivery_machine_pending(db, row):
            continue
        row.status = "session_running"
        row.last_error = None
        moved += 1
    return moved


def pick_last_delivery_event(rows, heartbeat_progress: dict | None = None) -> dict | None:
    """Newest connector submission, else the heartbeat progress line."""
    best = None
    best_at = ""
    for row in rows or []:
        meta = getattr(row, "attempt_meta", None) if not isinstance(row, dict) else row.get("attempt_meta")
        events = list((meta or {}).get("submissions") or [])
        if not events:
            continue
        last = events[-1] if isinstance(events[-1], dict) else {}
        stamp = str(last.get("at") or "")
        if stamp < best_at:
            continue
        best_at = stamp
        channel = getattr(row, "channel_code", None) if not isinstance(row, dict) else row.get("channel_code")
        status = getattr(row, "status", None) if not isinstance(row, dict) else row.get("status")
        delivery_id = getattr(row, "id", None) if not isinstance(row, dict) else row.get("id")
        live = delivery_has_live_receipt(row) if not isinstance(row, dict) else bool(row.get("has_live_receipt") or row.get("live"))
        best = {
            "channel_code": last.get("channel_code") or channel,
            "event": last.get("event"),
            "message": last.get("message") or "",
            "at": stamp,
            "status": status,
            "delivery_id": str(delivery_id) if delivery_id else None,
            "live": live,
            "source": "submission",
        }
    if best:
        return best
    lp = heartbeat_progress or {}
    if not (lp.get("title") or lp.get("channel") or lp.get("hint")):
        return None
    return {
        "channel_code": lp.get("channel"),
        "event": "progress",
        "message": str(lp.get("title") or lp.get("hint") or "")[:160],
        "at": lp.get("at"),
        "status": "session_running" if lp.get("busy") else None,
        "delivery_id": None,
        "live": False,
        "source": "heartbeat",
    }


def last_delivery_event(db: Session, user: User, heartbeat_progress: dict | None = None) -> dict | None:
    rows = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id)
        .order_by(DistributionDelivery.updated_at.desc())
        .limit(20)
        .all()
    )
    return pick_last_delivery_event(rows, heartbeat_progress)


def pending_upload_queue(db: Session, user: User, *, limit: int = 8) -> dict:
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.seats.service import actor_can_operate_seat

    rows = (
        db.query(SeatJob, CreatorSeat)
        .join(CreatorSeat, CreatorSeat.id == SeatJob.seat_id)
        .filter(SeatJob.status.in_(("queued", "leased")), SeatJob.kind == "upload")
        .all()
    )
    owned = [(job, seat) for job, seat in rows if actor_can_operate_seat(seat, user)]
    owned.sort(key=lambda pair: pair[0].created_at or datetime.min)
    items = []
    for job, seat in owned[: max(1, min(limit, 20))]:
        payload = dict(job.payload or {})
        items.append(
            {
                "id": str(job.id),
                "channel_code": seat.channel_code,
                "status": job.status,
                "title": payload.get("title_with_code") or payload.get("title") or "",
                "delivery_id": payload.get("delivery_id"),
            }
        )
    return {"count": len(owned), "items": items}


def last_harvest_from_seats(seats: list[dict] | None) -> dict | None:
    best = None
    for seat in seats or []:
        health = seat.get("farm_health") or {}
        at = seat.get("last_harvest_at") or health.get("at")
        if not at and health.get("rows") is None:
            continue
        cand = {
            "at": at,
            "channel": seat.get("channel_code"),
            "count": int(health.get("rows") or 0),
            "matched": health.get("matched"),
            "unclaimed": health.get("unclaimed"),
            "source": health.get("source"),
            "period_key": health.get("period_key"),
            "reason": health.get("reason"),
            "ok": bool(health.get("ok", (health.get("rows") or 0) > 0)),
            "seat_id": seat.get("id"),
        }
        if best is None or str(cand["at"] or "") > str(best.get("at") or ""):
            best = cand
    return best


def _connector_agent(db: Session, user: User) -> dict:
    from app.models.schemas import UserPreference

    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    settings = dict((pref.settings if pref else None) or {})
    return dict(settings.get("connector") or {})


def remember_connector_agent(db: Session, user: User, report: dict | None) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.schemas import UserPreference

    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id, settings={})
        db.add(pref)
        db.flush()
    settings = dict(pref.settings or {})
    agent = dict(settings.get("connector") or {})
    payload = report or {}
    if payload.get("extension_version"):
        agent["version"] = str(payload["extension_version"])[:32]
    if payload.get("channel"):
        agent["channel"] = str(payload["channel"])[:32]
    if payload.get("period_key"):
        agent["client_period"] = str(payload["period_key"])[:32]
    if isinstance(payload.get("last_progress"), dict):
        lp = payload["last_progress"]
        agent["last_progress"] = {
            "title": str(lp.get("title") or "")[:120],
            "hint": str(lp.get("hint") or "")[:160],
            "channel": str(lp.get("channel") or "")[:32],
            "busy": bool(lp.get("busy")),
            "at": str(lp.get("at") or datetime.utcnow().isoformat())[:40],
        }
    agent["at"] = datetime.utcnow().isoformat()
    settings["connector"] = agent
    pref.settings = settings
    flag_modified(pref, "settings")
    return agent


def connector_sync_state(db: Session, user: User, *, online: bool | None = None) -> dict:
    from app.services.royalty.connector import MIN_EXTENSION_VERSION
    from app.services.royalty.settlement import current_period
    from app.services.seats.consent import user_has_distribution_license
    from app.services.seats.service import list_seats
    from app.services.distribution.telemetry import hydrate_telemetry

    hydrate_telemetry(db)
    period_key, _, _ = current_period(db)
    seats = list_seats(db, user)
    tokens = (
        db.query(ConnectorIngestToken)
        .filter(ConnectorIngestToken.user_id == user.id, ConnectorIngestToken.revoked_at.is_(None))
        .order_by(ConnectorIngestToken.created_at.desc())
        .all()
    )
    live = next((row for row in tokens if not row.expires_at or row.expires_at > datetime.utcnow()), None)
    agent = _connector_agent(db, user)
    is_online = has_connector_heartbeat(db, user.id) if online is None else online
    wait = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id, DistributionDelivery.status == "session_wait")
        .count()
    )
    queue = pending_upload_queue(db, user)
    last_delivery = last_delivery_event(db, user, agent.get("last_progress") if isinstance(agent.get("last_progress"), dict) else None)
    from app.services.distribution.catalog import CHANNEL_SPECS
    from app.services.distribution.telemetry import channel_telemetry

    degraded = [spec["code"] for spec in CHANNEL_SPECS if channel_telemetry(db, spec["code"]).get("degraded_to")]
    return {
        "ok": True,
        "online": bool(is_online),
        "at": datetime.utcnow().isoformat(),
        "period_key": period_key,
        "token_expires_at": live.expires_at.isoformat() if live and live.expires_at else None,
        "role": "ops" if getattr(user, "is_admin", False) else "user",
        "min_extension_version": MIN_EXTENSION_VERSION,
        "extension_version": agent.get("version"),
        "last_seen_at": agent.get("at"),
        "last_harvest": last_harvest_from_seats(seats),
        "last_delivery": last_delivery,
        "queue_count": int(queue["count"]),
        "upload_queue": queue["items"],
        "session_wait_count": wait,
        "degraded_channels": degraded,
        "degraded_count": len(degraded),
        "seats": seats,
        "has_distribution_license": user_has_distribution_license(db, user),
    }


def connector_public_state(db: Session, user: User) -> dict:
    sync = connector_sync_state(db, user)
    return {
        "online": sync["online"],
        "version": sync.get("extension_version"),
        "last_seen_at": sync.get("last_seen_at"),
        "last_harvest": sync.get("last_harvest"),
        "last_delivery": sync.get("last_delivery"),
        "queue_count": sync.get("queue_count") or 0,
        "upload_queue": sync.get("upload_queue") or [],
        "degraded_count": sync.get("degraded_count") or 0,
        "degraded_channels": sync.get("degraded_channels") or [],
        "period_key": sync.get("period_key"),
        "token_expires_at": sync.get("token_expires_at"),
        "min_extension_version": sync.get("min_extension_version"),
        "session_wait_count": sync.get("session_wait_count"),
    }


def touch_heartbeat(db: Session, user: User, report: dict | None = None) -> dict:
    now = datetime.utcnow()
    rows = (
        db.query(ConnectorIngestToken)
        .filter(ConnectorIngestToken.user_id == user.id, ConnectorIngestToken.revoked_at.is_(None))
        .all()
    )
    touched = 0
    for row in rows:
        if row.expires_at and row.expires_at < now:
            continue
        row.last_used_at = now
        touched += 1
    if not touched:
        sync = connector_sync_state(db, user, online=False)
        sync.update({"ok": False, "online": False, "reason": "no_token"})
        return sync
    if report:
        remember_connector_agent(db, user, report)
        from app.services.royalty.connector import MIN_EXTENSION_VERSION, version_less

        version = str(report.get("extension_version") or "")
        if version and version_less(version, MIN_EXTENSION_VERSION):
            sync = connector_sync_state(db, user, online=True)
            sync.update(
                {
                    "ok": False,
                    "reason": "stale_extension",
                    "upgrade_required": True,
                    "min_extension_version": MIN_EXTENSION_VERSION,
                }
            )
            db.commit()
            return sync
    promoted = promote_session_if_online(db, user)
    linked = _link_directs_for_user(db, user)
    db.commit()
    sync = connector_sync_state(db, user, online=True)
    sync.update({"ok": True, "promoted": promoted, "direct_linked": linked})
    return sync


def _link_directs_for_user(db: Session, user: User) -> int:
    from app.services.distribution.direct import maybe_link_direct_binding
    from app.services.distribution.pipeline import refresh_release_progress

    q = db.query(DistributionDelivery).filter(
        DistributionDelivery.status.in_(tuple(ASSIST_LIST_STATUSES)),
        DistributionDelivery.channel_code.in_(("youtube_music", "soundcloud")),
        DistributionDelivery.store_url.is_(None),
    )
    if not getattr(user, "is_admin", False):
        q = q.filter(DistributionDelivery.owner_id == user.id)
    linked = 0
    for row in q.limit(5).all():
        release = db.query(Release).filter(Release.id == row.release_id).first()
        if maybe_link_direct_binding(db, row, release):
            linked += 1
            if release:
                refresh_release_progress(db, release)
    return linked


def build_assist_job(db: Session, delivery: DistributionDelivery, release: Release) -> dict:
    work = db.query(Work).filter(Work.id == delivery.work_id).first()
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    from app.services.distribution.direct import list_owner_bindings
    from app.services.distribution.service import _fresh_kit_url

    from app.services.distribution.track_code import ensure_track_code, title_with_code

    from app.services.distribution.asset_profiles import listing_master_ref

    from app.services.distribution.catalog import channel_automation_level, preview_delivery_route

    raw_title = (meta.title if meta else None) or (work.title if work else None)
    track_code = ensure_track_code(db, work, release) if work else ((meta.isrc if meta else None) or (work.isrc if work else None))
    stems = ((work.post_process_status or {}).get("stems") if work else None) or {}
    listing = listing_master_ref(work) if work else {}
    return {
        "delivery_id": str(delivery.id),
        "release_id": str(release.id),
        "work_id": str(delivery.work_id),
        "channel_code": delivery.channel_code,
        "playbook": delivery.channel_code,
        "delivery_mode": channel_delivery_mode(delivery.channel_code),
        "title": raw_title,
        "title_with_code": title_with_code(raw_title, track_code),
        "track_code": track_code,
        "artist_name": (meta.artist_name if meta else None) or (getattr(work, "title", None)),
        "isrc": (meta.isrc if meta else None) or (work.isrc if work else None),
        "cover_url": (meta.cover_url if meta else None) or (work.cover_url if work else None),
        "kit_url": _fresh_kit_url(release),
        "audio_url": listing.get("audio_url"),
        "master_storage_key": listing.get("storage_key"),
        "master_wav_key": listing.get("wav_key"),
        "master_wav_url": listing.get("wav_url"),
        "originality_zip_url": stems.get("originality_zip_url") if stems.get("quality") == "demucs" else None,
        "originality_zip_key": stems.get("originality_zip_key") if stems.get("quality") == "demucs" else None,
        "listing_asset": "master",
        "upload_url": channel_upload_url(delivery.channel_code),
        "hosts": channel_hosts(delivery.channel_code),
        "clip_windows": clip_windows(getattr(work, "duration", None)),
        "bindings": list_owner_bindings(db, delivery.owner_id),
        "priority_score": int((delivery.attempt_meta or {}).get("priority_score") or 0),
        "automation_level": channel_automation_level(delivery.channel_code),
        "route_preview": preview_delivery_route(delivery.channel_code),
        "parked_at": datetime.utcnow().isoformat(),
    }


def hydrate_assist_meta(db: Session, delivery: DistributionDelivery, release: Release | None = None) -> dict:
    release = release or db.query(Release).filter(Release.id == delivery.release_id).first()
    meta = dict(delivery.attempt_meta or {})
    existing = dict(meta.get("assist_job") or {})
    if release:
        job = build_assist_job(db, delivery, release)
        if existing.get("parked_at"):
            job["parked_at"] = existing["parked_at"]
        if existing.get("priority_score") and not job.get("priority_score"):
            job["priority_score"] = existing["priority_score"]
        meta["assist_job"] = job
        meta.setdefault("route", "session_assist")
        delivery.attempt_meta = meta
        return job
    return existing


def refresh_assist_jobs(db: Session, *, limit: int = 80) -> int:
    rows = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.status.in_(tuple(ASSIST_LIST_STATUSES)))
        .limit(limit)
        .all()
    )
    refreshed = 0
    for row in rows:
        before = (row.attempt_meta or {}).get("assist_job") or {}
        job = hydrate_assist_meta(db, row)
        if job and job != before:
            refreshed += 1
    return refreshed


def park_for_session(db: Session, delivery: DistributionDelivery, release: Release, *, kick: bool = True) -> str:
    meta = dict(delivery.attempt_meta or {})
    meta["assist_job"] = build_assist_job(db, delivery, release)
    meta["route"] = "session_assist"
    delivery.next_retry_at = None
    delivery.reject_reason = None
    delivery.attempt_meta = meta
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(
        delivery,
        event="portal_queued",
        actor="connector",
        message="连接器队列已建，等待开官方后台",
    )
    from app.services.seats.service import (
        enqueue_delivery_upload,
        resolve_runtime_seat,
        seat_ownership_for,
        seat_session_ready,
    )

    user_seat = resolve_runtime_seat(
        db,
        channel_code=delivery.channel_code,
        user_id=delivery.owner_id,
        work_id=delivery.work_id,
        ownership="user",
    )
    ownership = seat_ownership_for(
        mode=getattr(release, "mode", None),
        channel_code=delivery.channel_code,
        user_session_ready=seat_session_ready(user_seat),
    )
    job = meta.get("assist_job") or {}
    job = enqueue_delivery_upload(
        db,
        channel_code=delivery.channel_code,
        user_id=delivery.owner_id,
        work_id=delivery.work_id,
        ownership=ownership,
        payload={
            "delivery_id": str(delivery.id),
            "work_id": str(delivery.work_id),
            "title": job.get("title"),
            "title_with_code": job.get("title_with_code"),
            "track_code": job.get("track_code"),
            "artist_name": job.get("artist_name"),
            "isrc": job.get("isrc"),
            "kit_url": job.get("kit_url"),
            "upload_url": job.get("upload_url"),
            "audio_url": job.get("master_wav_url") or job.get("audio_url"),
            "master_storage_key": job.get("master_storage_key"),
            "master_wav_key": job.get("master_wav_key"),
            "master_wav_url": job.get("master_wav_url"),
            "originality_zip_url": job.get("originality_zip_url"),
            "originality_zip_key": job.get("originality_zip_key"),
            "listing_asset": "master",
            "priority_score": int((delivery.attempt_meta or {}).get("priority_score") or job.get("priority_score") or 0),
            "automation_level": job.get("automation_level"),
        },
    )
    seat = resolve_runtime_seat(
        db,
        channel_code=delivery.channel_code,
        user_id=delivery.owner_id,
        work_id=delivery.work_id,
        ownership=ownership,
    )
    if seat:
        meta["seat_id"] = str(seat.id)
    if job:
        assist = dict(meta.get("assist_job") or {})
        assist["seat_job_id"] = str(job.id)
        meta["assist_job"] = assist
        if getattr(job, "lease_owner", None):
            meta["lease_owner"] = job.lease_owner
    delivery.attempt_meta = meta
    online = has_connector_heartbeat(db, delivery.owner_id)
    has_session = seat_has_session(seat)
    platform = bool(seat and getattr(seat, "ownership", None) == "platform")
    machine_ready = has_session or platform
    job_leased = bool(job and getattr(job, "status", None) == "leased")
    if job_leased or (online and machine_ready):
        delivery.status = "session_running"
        delivery.last_error = None
    elif job and machine_ready:
        delivery.status = "session_wait"
        delivery.last_error = LEASE_WAIT_NOTE
    else:
        delivery.status = "session_wait"
        delivery.last_error = None
    if kick:
        from app.services.seats.runtime import kick_seat_runtime

        kick_seat_runtime()
    return delivery.status


def route_delivery(delivery: DistributionDelivery) -> str:
    from app.services.distribution.catalog import pick_configured_aggregator, preview_delivery_route

    preview = preview_delivery_route(delivery.channel_code)
    route = preview.get("route")
    pipeline = preview.get("pipeline")
    if pipeline == "partner" or route == "partner":
        picked = pick_configured_aggregator(delivery.channel_code)
        if picked and delivery.distributor_code != picked:
            delivery.distributor_code = picked
        return "partner"
    if pipeline == "ops" or route == "ops":
        return "ops"
    if pipeline == "metrics_only" or route == "metrics":
        return "metrics"
    return "session_assist"


def serialize_assist_job(delivery: DistributionDelivery) -> dict:
    meta = dict(delivery.attempt_meta or {})
    job = dict(meta.get("assist_job") or {})
    job.update(
        {
            "delivery_id": str(delivery.id),
            "channel_code": delivery.channel_code,
            "status": delivery.status,
            "store_url": delivery.store_url,
            "upload_url": job.get("upload_url") or channel_upload_url(delivery.channel_code),
            "hosts": job.get("hosts") or channel_hosts(delivery.channel_code),
            "priority_score": int(job.get("priority_score") or (delivery.attempt_meta or {}).get("priority_score") or 0),
        }
    )
    return job


def _assist_sort_key(delivery: DistributionDelivery) -> tuple:
    score = int((delivery.attempt_meta or {}).get("priority_score") or 0)
    return (-score, volume_rank(delivery.channel_code))


def list_assist_jobs(db: Session, user: User, *, limit: int = 40) -> list[dict]:
    if has_connector_heartbeat(db, user.id) or getattr(user, "is_admin", False):
        promote_session_if_online(db, user)
        db.flush()
    from app.models.schemas import CreatorSeat
    from app.services.seats.consent import has_scope

    upload_ok: dict[str, bool] | None = None
    if not getattr(user, "is_admin", False):
        seats = (
            db.query(CreatorSeat)
            .filter(CreatorSeat.user_id == user.id, CreatorSeat.ownership == "user")
            .all()
        )
        upload_ok = {seat.channel_code: has_scope(seat, "upload") for seat in seats}
    q = db.query(DistributionDelivery).filter(DistributionDelivery.status.in_(tuple(ASSIST_LIST_STATUSES)))
    if not getattr(user, "is_admin", False):
        q = q.filter(DistributionDelivery.owner_id == user.id)
        rows = q.all()
    else:
        rows = q.limit(max(int(limit) * 20, 200)).all()
    rows.sort(key=_assist_sort_key)
    out = []
    dirty = False
    for row in rows:
        if upload_ok is not None and not upload_ok.get(row.channel_code):
            continue
        before = (row.attempt_meta or {}).get("assist_job")
        hydrate_assist_meta(db, row)
        if (row.attempt_meta or {}).get("assist_job") != before:
            dirty = True
        out.append(serialize_assist_job(row))
        if len(out) >= limit:
            break
    if dirty:
        db.commit()
    return out


def _owned_or_ops(db: Session, user: User, delivery_id: str) -> DistributionDelivery:
    try:
        did = _as_uuid(delivery_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid delivery id") from exc
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == did).first()
    if not row:
        raise HTTPException(404, "Delivery not found")
    if row.owner_id != user.id and not getattr(user, "is_admin", False):
        raise HTTPException(403, "Not your delivery")
    return row


def claim_assist_job(db: Session, user: User, delivery_id: str) -> dict:
    """Read-only for old extensions. Execution lives on GET /seats/jobs."""
    row = _owned_or_ops(db, user, delivery_id)
    if row.status not in SESSION_STATUSES | {"ops_queue", "awaiting_manual"}:
        raise HTTPException(400, "Delivery is not waiting for session assist")
    from app.services.seats.consent import user_has_upload_scope

    if not user_has_upload_scope(db, user, row.channel_code):
        raise HTTPException(403, "upload scope not granted")
    return serialize_assist_job(row)


def apply_store_receipt(db: Session, delivery: DistributionDelivery, store_url: str, *, external_id: str | None = None) -> bool:
    from app.services.distribution.service import normalize_store_url, should_autolive_from_ops_receipt
    from app.services.distribution.pipeline import notify_distribution_status, refresh_release_progress

    url = normalize_store_url(store_url)
    if not looks_like_store_page(url, delivery.channel_code):
        return False
    previous = delivery.status
    delivery.store_url = url
    ref = external_id or extract_store_ref(url, delivery.channel_code)
    if ref:
        delivery.external_id = str(ref)[:128]
    if should_autolive_from_ops_receipt(delivery.status, url, delivery.channel_code):
        delivery.status = "live"
        delivery.last_error = None
        delivery.reject_reason = None
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(
        delivery,
        event="receipt",
        actor="connector",
        receipt_url=url,
        external_id=delivery.external_id,
        message="已记下真实歌曲页",
    )
    release = db.query(Release).filter(Release.id == delivery.release_id).first()
    if previous != "live" and delivery.status == "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, delivery)
    if release:
        refresh_release_progress(db, release)
        if previous != delivery.status:
            notify_distribution_status(
                db,
                delivery.owner_id,
                release_id=str(delivery.release_id),
                status=delivery.status,
                channel_code=delivery.channel_code,
                message=f"{delivery.channel_code} 席位投递完成：{delivery.status}",
            )
    return True


def note_assist_progress(db: Session, user: User, delivery_id: str, *, event: str, message: str | None = None) -> dict:
    from app.services.distribution.service import serialize_delivery
    from app.services.distribution.submit_log import append_delivery_event

    row = _owned_or_ops(db, user, delivery_id)
    kind = str(event or "").strip()[:48] or "note"
    append_delivery_event(row, event=kind, actor="connector", message=message or kind)
    if kind == "submitted" and row.status in SESSION_STATUSES:
        row.status = "in_review"
        row.last_error = None
    if kind == "needs_challenge":
        row.last_error = "needs_challenge"
    if kind == "fill_incomplete":
        row.last_error = "fill_incomplete"
    db.commit()
    return serialize_delivery(row)


def complete_assist_job(db: Session, user: User, delivery_id: str, *, store_url: str, external_id: str | None = None) -> dict:
    from app.services.distribution.service import serialize_delivery

    row = _owned_or_ops(db, user, delivery_id)
    if not apply_store_receipt(db, row, store_url, external_id=external_id):
        raise HTTPException(400, "not a store page")
    db.commit()
    return serialize_delivery(row)


def _stale_session_reason(db: Session, row: DistributionDelivery, *, now: datetime) -> str | None:
    """Same predicates as expire. waiting_login stays with the user, not ops."""
    cutoff = now - assist_ttl()
    stamp = row.last_attempt_at or row.updated_at or row.created_at
    if delivery_machine_pending(db, row):
        return None
    waiting_login = row.status == "session_wait" and not is_lease_wait_error(row.last_error)
    if waiting_login:
        return None
    ttl_expired = not stamp or stamp <= cutoff
    offline = (
        row.status == "session_running"
        and not has_connector_heartbeat(db, row.owner_id)
        and not delivery_has_live_session(db, row)
    )
    heartbeat_expired = offline and (not stamp or stamp <= now - timedelta(minutes=10))
    if heartbeat_expired and not ttl_expired:
        return "heartbeat"
    if ttl_expired:
        return "ttl"
    return None


def count_stale_session_jobs(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    cutoff = now - assist_ttl()
    rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.status.in_(tuple(SESSION_STATUSES)),
            or_(
                DistributionDelivery.last_attempt_at.is_(None),
                DistributionDelivery.last_attempt_at <= cutoff,
            ),
        )
        .limit(80)
        .all()
    )
    return sum(1 for row in rows if _stale_session_reason(db, row, now=now))


def expire_stale_session_jobs(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    cutoff = now - assist_ttl()
    rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.status.in_(tuple(SESSION_STATUSES)),
            or_(
                DistributionDelivery.last_attempt_at.is_(None),
                DistributionDelivery.last_attempt_at <= cutoff,
            ),
        )
        .order_by(DistributionDelivery.updated_at.asc())
        .limit(80)
        .all()
    )
    moved = 0
    for row in rows:
        reason = _stale_session_reason(db, row, now=now)
        if not reason:
            continue
        row.status = "ops_queue"
        meta = dict(row.attempt_meta or {})
        meta["assist_expired_at"] = now.isoformat()
        meta["assist_expire_reason"] = reason
        row.attempt_meta = meta
        row.last_error = "会话助手超时，已转入运营同 kit 队列"
        moved += 1
        if row.owner_id:
            from app.services.distribution.pipeline import notify_distribution_status

            notify_distribution_status(
                db,
                row.owner_id,
                release_id=str(row.release_id),
                status="ops_queue",
                channel_code=row.channel_code,
                message=f"{row.channel_code} 连接器超时，已交运营继续发，不是已上架",
            )
    if moved:
        db.flush()
    return moved


def assist_kit_payload(db: Session, user: User, delivery_id: str) -> dict:
    row = _owned_or_ops(db, user, delivery_id)
    release = db.query(Release).filter(Release.id == row.release_id).first()
    job = hydrate_assist_meta(db, row, release)
    from app.services.distribution.service import _fresh_kit_url, ensure_release_kit

    kit_url = (job or {}).get("kit_url") or (_fresh_kit_url(release) if release else None)
    if release and not kit_url:
        try:
            _data, kit_url = ensure_release_kit(db, user, str(release.id))
        except HTTPException:
            kit_url = None
    clip_pack_url = None
    work = db.query(Work).filter(Work.id == row.work_id).first()
    if work and ((job or {}).get("clip_windows") or clip_windows(getattr(work, "duration", None))):
        try:
            from app.services.distribution.kit import ensure_work_clip_pack

            _data, clip_pack_url = ensure_work_clip_pack(work)
        except HTTPException:
            clip_pack_url = None
    db.commit()
    return {
        "delivery_id": str(row.id),
        "release_id": str(row.release_id),
        "channel_code": row.channel_code,
        "title": (job or {}).get("title"),
        "kit_url": kit_url,
        "cover_url": (job or {}).get("cover_url"),
        "clip_pack_url": clip_pack_url,
        "clip_windows": (job or {}).get("clip_windows") or [],
        "master_audio_url": (job or {}).get("audio_url"),
        "master_wav_url": (job or {}).get("master_wav_url"),
        "originality_zip_url": (job or {}).get("originality_zip_url"),
        "listing_asset": "master",
    }


def assist_asset_bytes(db: Session, user: User, delivery_id: str, kind: str = "master") -> dict:
    """Stream listing master / originality zip from API host. No presigned foreign domain."""
    import hashlib

    row = _owned_or_ops(db, user, delivery_id)
    release = db.query(Release).filter(Release.id == row.release_id).first()
    job = hydrate_assist_meta(db, row, release) or {}
    if kind == "originality":
        key = job.get("originality_zip_key")
        filename = "originality.zip"
        content_type = "application/zip"
    else:
        key = job.get("master_wav_key") or job.get("master_storage_key")
        filename = "master.wav"
        content_type = "audio/wav"
    if not key:
        raise HTTPException(404, "asset missing")
    from app.services.storage import get_storage_service

    data = get_storage_service().get_object_bytes(str(key))
    etag = hashlib.sha1(data).hexdigest()
    return {
        "bytes": data,
        "filename": filename,
        "content_type": content_type,
        "etag": etag,
        "delivery_id": str(row.id),
        "kind": kind,
        "listing_asset": "master",
    }
