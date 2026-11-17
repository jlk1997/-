"""Creator seats: platform pool + user-connected dashboards."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, SeatJob, SeatSecret, User
from app.services.harvest.playbooks import PLATFORM_SEAT_CHANNELS, PLAYBOOKS, channel_playbook
from app.services.seats.secrets import decrypt_blob, encrypt_blob

LEASE_SECONDS = 180
logger = logging.getLogger(__name__)


def account_key(*, ownership: str, channel_code: str, user_id=None, pool_index: int = 0) -> str:
    if ownership == "platform":
        return f"platform:{channel_code}:{pool_index}"
    return f"user:{user_id}:{channel_code}"


def serialize_seat(row: CreatorSeat) -> dict:
    extra = dict(row.extra or {})
    remote = dict(extra.get("remote") or {})
    playbook = channel_playbook(row.channel_code)
    from app.services.seats.consent import seat_scopes

    scopes = seat_scopes(row)
    return {
        "id": str(row.id),
        "ownership": row.ownership,
        "channel_code": row.channel_code,
        "user_id": str(row.user_id) if row.user_id else None,
        "pool_index": row.pool_index or 0,
        "status": row.status,
        "runtime": row.runtime,
        "profile_id": row.profile_id,
        "external_account_id": row.external_account_id,
        "last_harvest_at": row.last_harvest_at.isoformat() if row.last_harvest_at else None,
        "last_upload_at": row.last_upload_at.isoformat() if row.last_upload_at else None,
        "last_sync_at": extra.get("last_sync_at"),
        "last_error": row.last_error,
        "has_session": extra.get("has_session") is True,
        "needs_challenge": row.status == "needs_challenge",
        "remote_status": remote.get("status"),
        "login_url": remote.get("login_url") or playbook.get("portal") or playbook.get("harvest_url"),
        "playbook": playbook,
        "farm_health": extra.get("farm_health"),
        "scopes": scopes,
        "session_expires_at": extra.get("session_expires_at"),
        "relogin_due": seat_relogin_due(row),
    }


def serialize_remote(row: CreatorSeat) -> dict:
    extra = dict(row.extra or {})
    remote = dict(extra.get("remote") or {})
    return {
        "seat": serialize_seat(row),
        "status": remote.get("status") or ("ready" if extra.get("has_session") else "idle"),
        "login_url": remote.get("login_url") or (PLAYBOOKS.get(row.channel_code) or {}).get("portal"),
        "screenshot": remote.get("screenshot"),
        "has_session": extra.get("has_session") is True,
        "started_at": remote.get("started_at"),
        "note": remote.get("note"),
    }


def _profile_id(channel_code: str, *, ownership: str, user_id=None, pool_index: int = 0) -> str:
    tail = str(user_id or f"p{pool_index}")
    return f"{ownership}-{channel_code}-{tail}"[:120]


def ensure_platform_seats(db: Session, *, channels: list[str] | None = None, pool_size: int = 1) -> list[CreatorSeat]:
    size = max(1, min(int(pool_size or 1), 16))
    out: list[CreatorSeat] = []
    for code in channels or PLATFORM_SEAT_CHANNELS:
        if code not in PLAYBOOKS:
            continue
        for index in range(size):
            key = account_key(ownership="platform", channel_code=code, pool_index=index)
            row = db.query(CreatorSeat).filter(CreatorSeat.account_key == key).first()
            if not row:
                row = CreatorSeat(
                    account_key=key,
                    ownership="platform",
                    channel_code=code,
                    pool_index=index,
                    status="connecting",
                    runtime="farm",
                    profile_id=_profile_id(code, ownership="platform", pool_index=index),
                    extra={"has_session": False},
                )
                db.add(row)
                db.flush()
            out.append(row)
    return out


def warmup_platform_pool(db: Session) -> dict:
    """Stamp connecting platform seats as not-ready. Never invents a settlement amount."""
    seats = ensure_platform_seats(db)
    stamped = 0
    ready = 0
    now = datetime.utcnow().isoformat()
    for seat in seats:
        extra = dict(seat.extra or {})
        has_session = extra.get("has_session") is True
        if has_session and seat.status == "live":
            ready += 1
            continue
        extra["farm_health"] = {
            "ok": False,
            "warmup": True,
            "invented_money": False,
            "zero_rows_success": False,
            "rows": 0,
            "reason": "needs_session" if not has_session else f"status_{seat.status}",
            "at": now,
        }
        seat.extra = extra
        stamped += 1
    return {
        "ensured": len(seats),
        "stamped": stamped,
        "ready": ready,
        "queued": 0,
        "invented_money": False,
    }


def pick_platform_seat(db: Session, channel_code: str, work_id=None) -> CreatorSeat | None:
    ensure_platform_seats(db, channels=[channel_code])
    rows = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "platform", CreatorSeat.channel_code == channel_code)
        .order_by(CreatorSeat.pool_index.asc())
        .all()
    )
    if not rows:
        return None
    if work_id and len(rows) > 1:
        digest = hashlib.sha1(str(work_id).encode()).digest()
        return rows[int.from_bytes(digest[:2], "big") % len(rows)]
    live = [row for row in rows if row.status == "live"]
    return (live or rows)[0]


def find_actor_seat(db: Session, user: User | None, channel_code: str | None) -> CreatorSeat | None:
    if not user or not channel_code:
        return None
    key = account_key(ownership="user", channel_code=channel_code, user_id=user.id)
    return db.query(CreatorSeat).filter(CreatorSeat.account_key == key).first()


def stamp_seat_harvest(
    seat: CreatorSeat,
    *,
    rows: int,
    matched: int | None = None,
    unclaimed: int | None = None,
    source: str = "extension",
    period_key: str | None = None,
    reason: str | None = None,
    extension_version: str | None = None,
    synced: bool = False,
) -> None:
    now = datetime.utcnow()
    if synced:
        extra = dict(seat.extra or {})
        extra["last_sync_at"] = now.isoformat()
        extra["farm_health"] = {
            "ok": rows > 0,
            "rows": rows,
            "matched": matched,
            "unclaimed": unclaimed,
            "source": source,
            "period_key": period_key,
            "reason": reason or "seat_sync",
            "official_csv": bool(reason and "csv" in str(reason)),
            "extension_version": extension_version,
            "at": now.isoformat(),
        }
        seat.extra = extra
        return
    seat.last_harvest_at = now
    seat.last_error = None
    extra = dict(seat.extra or {})
    extra["farm_health"] = {
        "ok": rows > 0,
        "rows": rows,
        "matched": matched,
        "unclaimed": unclaimed,
        "source": source,
        "period_key": period_key,
        "reason": reason,
        "official_csv": bool(reason and "csv" in str(reason)),
        "extension_version": extension_version,
        "at": datetime.utcnow().isoformat(),
    }
    seat.extra = extra


def disconnect_user_seat(db: Session, user: User, seat_id: str) -> dict:
    seat = get_seat(db, seat_id, user, write=True)
    if seat.ownership != "user":
        raise HTTPException(400, "Only your own store can be disconnected")
    secret = db.query(SeatSecret).filter(SeatSecret.seat_id == seat.id).first()
    if secret:
        db.delete(secret)
    extra = dict(seat.extra or {})
    extra["has_session"] = False
    extra.pop("remote", None)
    extra["disconnected_at"] = datetime.utcnow().isoformat()
    seat.extra = extra
    seat.status = "disconnected"
    seat.last_error = None
    open_jobs = (
        db.query(SeatJob)
        .filter(SeatJob.seat_id == seat.id, SeatJob.status.in_(("queued", "leased")))
        .all()
    )
    for job in open_jobs:
        job.status = "failed"
        job.result = {"error": "disconnected", "ok": False}
    db.commit()
    return serialize_seat(seat)


def connect_user_seat(db: Session, user: User, channel_code: str) -> CreatorSeat:
    from app.services.seats.consent import default_scopes_for

    if channel_code not in PLAYBOOKS:
        raise HTTPException(400, "Unknown channel")
    key = account_key(ownership="user", channel_code=channel_code, user_id=user.id)
    row = db.query(CreatorSeat).filter(CreatorSeat.account_key == key).first()
    if not row:
        row = CreatorSeat(
            account_key=key,
            ownership="user",
            channel_code=channel_code,
            user_id=user.id,
            status="connecting",
            runtime="either",
            profile_id=_profile_id(channel_code, ownership="user", user_id=user.id),
            extra={"has_session": False, "scopes": default_scopes_for(channel_code)},
        )
        db.add(row)
        db.flush()
    from app.services.seats.consent import ensure_default_scopes

    ensure_default_scopes(row)
    return row


def save_seat_session(
    db: Session,
    seat: CreatorSeat,
    *,
    session: dict | None = None,
    credentials: dict | None = None,
    mark_live: bool = True,
) -> CreatorSeat:
    payload = {"session": session or {}, "credentials": credentials or {}}
    blob = encrypt_blob(payload)
    secret = db.query(SeatSecret).filter(SeatSecret.seat_id == seat.id).first()
    if secret:
        secret.ciphertext = blob
        secret.kind = "cookie_jar" if session else "password"
        secret.updated_at = datetime.utcnow()
    else:
        db.add(SeatSecret(seat_id=seat.id, kind="cookie_jar" if session else "password", ciphertext=blob))
    extra = dict(seat.extra or {})
    extra["has_session"] = True
    extra["secret_kind"] = "cookie_jar" if session else "password"
    extra["session_saved_at"] = datetime.utcnow().isoformat()
    expires = predict_session_expiry(session)
    if expires:
        extra["session_expires_at"] = expires.isoformat()
    remote = dict(extra.get("remote") or {})
    if remote:
        remote["status"] = "ready"
        extra["remote"] = remote
    seat.extra = extra
    if mark_live:
        seat.status = "live"
        seat.last_error = None
    db.flush()
    from app.services.seats.consent import due_job_kind, ensure_default_scopes, grant_handoff_upload
    from app.services.seats.runtime import kick_seat_runtime

    grant_handoff_upload(seat)
    resume_waiting_uploads(db, seat)
    if seat.ownership == "user" and seat.user_id:
        owner = db.query(User).filter(User.id == seat.user_id).first()
        if owner:
            try:
                from app.services.distribution.handoff import resume_auth_held_releases

                resume_auth_held_releases(db, owner)
            except Exception:
                logger.exception("auth-hold resume failed after handing %s", seat.channel_code)
    db.flush()

    ensure_default_scopes(seat)
    kind = due_job_kind(seat)
    if kind:
        enqueue_job(db, seat, kind, {})
    kick_seat_runtime(enqueue_due_harvest=False)
    return seat


def load_seat_session(db: Session, seat: CreatorSeat) -> dict:
    secret = db.query(SeatSecret).filter(SeatSecret.seat_id == seat.id).first()
    if not secret:
        return {}
    return decrypt_blob(secret.ciphertext)


def list_seats(db: Session, user: User | None = None, *, include_platform: bool = True) -> list[dict]:
    ensure_platform_seats(db)
    q = db.query(CreatorSeat)
    if user and not getattr(user, "is_admin", False):
        if include_platform:
            q = q.filter((CreatorSeat.ownership == "platform") | (CreatorSeat.user_id == user.id))
        else:
            q = q.filter(CreatorSeat.user_id == user.id)
    elif not include_platform and user:
        q = q.filter(CreatorSeat.user_id == user.id)
    rows = q.order_by(CreatorSeat.ownership.asc(), CreatorSeat.channel_code.asc(), CreatorSeat.pool_index.asc()).all()
    if user and not getattr(user, "is_admin", False):
        rows = [row for row in rows if row.ownership == "platform" or row.user_id == user.id]
    return [serialize_seat(row) for row in rows]


def playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def farm_navigate_requested() -> bool:
    raw = (os.getenv("VIBE_FARM_NAVIGATE") or "0").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def farm_can_navigate() -> bool:
    return farm_navigate_requested() and playwright_available()


def farm_can_run_job(job: SeatJob) -> bool:
    navigate = farm_can_navigate()
    payload = job.payload or {}
    if job.kind in {"open_portal"}:
        return False
    if job.kind == "sync_metrics":
        return bool(payload.get("rows"))
    if job.kind == "harvest":
        return bool(payload.get("rows")) or navigate
    if job.kind == "upload":
        return navigate or bool(payload.get("store_url"))
    if job.kind == "remote_login":
        return navigate or bool(payload.get("cookies") or payload.get("session"))
    return True


HARVEST_STALE_HOURS = 6


def enqueue_due_harvests(
    db: Session,
    *,
    force: bool = False,
    stale_after_hours: float = HARVEST_STALE_HOURS,
    seat_id: str | None = None,
    user_id=None,
) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=max(1.0, float(stale_after_hours or HARVEST_STALE_HOURS)))
    q = db.query(CreatorSeat).filter(CreatorSeat.status == "live")
    sid = _as_uuid(seat_id) if seat_id else None
    if sid:
        q = q.filter(CreatorSeat.id == sid)
    if user_id is not None:
        q = q.filter(CreatorSeat.user_id == user_id)
    queued = 0
    from app.services.seats.consent import due_job_kind

    for seat in q.all():
        if not (seat.extra or {}).get("has_session"):
            continue
        kind = due_job_kind(seat)
        if not kind:
            continue
        if not force:
            if kind == "harvest" and seat.last_harvest_at and seat.last_harvest_at > cutoff:
                continue
            if kind != "harvest":
                last_sync = (seat.extra or {}).get("last_sync_at")
                if last_sync:
                    try:
                        synced = datetime.fromisoformat(str(last_sync).replace("Z", ""))
                        if synced > cutoff:
                            continue
                    except ValueError:
                        pass
        enqueue_job(db, seat, kind, {})
        queued += 1
    return queued


def queue_copy_after_live(db: Session, delivery) -> str | None:
    """A new store-page receipt can be copied now. A queue failure does not undo the receipt."""
    try:
        return _queue_copy_after_live(db, delivery)
    except Exception:
        logger.exception("copy after live skipped for %s", getattr(delivery, "id", None))
        return None


def _queue_copy_after_live(db: Session, delivery) -> str | None:
    from app.services.distribution.catalog import delivery_has_live_receipt
    from app.services.seats.consent import due_job_kind, has_scope, user_has_distribution_license
    from app.services.seats.runtime import kick_seat_runtime

    if getattr(delivery, "status", None) != "live" or not delivery_has_live_receipt(delivery):
        return None
    owner_id = getattr(delivery, "owner_id", None)
    channel = getattr(delivery, "channel_code", None)
    if not owner_id or not channel:
        return None
    seat = (
        db.query(CreatorSeat)
        .filter(
            CreatorSeat.user_id == owner_id,
            CreatorSeat.channel_code == channel,
            CreatorSeat.ownership == "user",
            CreatorSeat.status == "live",
        )
        .order_by(CreatorSeat.updated_at.desc())
        .first()
    )
    if not seat or not (seat.extra or {}).get("has_session"):
        return None
    kind = due_job_kind(seat)
    if kind == "harvest":
        owner = db.query(User).filter(User.id == owner_id).first()
        if not user_has_distribution_license(db, owner):
            kind = "sync_metrics" if has_scope(seat, "keep_sync") and has_scope(seat, "metrics") else None
    if kind not in {"harvest", "sync_metrics"}:
        return None
    enqueue_job(
        db,
        seat,
        kind,
        {"reason": "live_receipt", "delivery_id": str(delivery.id), "channel_code": channel},
    )
    kick_seat_runtime(enqueue_due_harvest=False)
    return kind


def kick_user_due_harvests(db: Session, user) -> int:
    """Queue this user's stale harvests in an isolated commit so GET /hub cannot roll them back."""
    from app.database import SessionLocal
    from app.services.seats.runtime import kick_seat_runtime

    uid = getattr(user, "id", user)
    queued = 0
    slot = SessionLocal()
    try:
        queued = enqueue_due_harvests(slot, user_id=uid)
        if queued:
            slot.commit()
        else:
            slot.rollback()
    except Exception:
        slot.rollback()
        raise
    finally:
        slot.close()
    if queued:
        kick_seat_runtime(enqueue_due_harvest=False)
    return queued


RELOGIN_STATUSES = frozenset({"expired", "needs_challenge", "needs_session"})
RELOGIN_COOLDOWN = timedelta(minutes=5)
SESSION_STALE_AFTER = timedelta(days=10)


def next_friday_noon(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    days = (4 - now.weekday()) % 7
    if days == 0:
        days = 7
    return (now + timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)


def predict_session_expiry(session: dict | None, *, now: datetime | None = None) -> datetime | None:
    """Earliest cookie expiry. Session-only jars get a conservative 12-day guess. Never stores passwords."""
    now = now or datetime.utcnow()
    payload = session or {}
    cookies = payload.get("cookies") if isinstance(payload.get("cookies"), list) else None
    if cookies is None and isinstance(payload.get("session"), dict):
        inner = payload.get("session") or {}
        cookies = inner.get("cookies") if isinstance(inner.get("cookies"), list) else []
    stamps: list[datetime] = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        raw = cookie.get("expirationDate") if cookie.get("expirationDate") is not None else cookie.get("expires")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if value > 1e12:
            value /= 1000.0
        try:
            exp = datetime.utcfromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            continue
        if exp > now:
            stamps.append(exp)
    if stamps:
        return min(stamps)
    if cookies:
        return now + timedelta(days=12)
    return None


def seat_relogin_due(seat, *, now: datetime | None = None) -> bool:
    extra = dict(getattr(seat, "extra", None) or {})
    now = now or datetime.utcnow()
    if extra.get("has_session") is not True:
        return getattr(seat, "status", None) in RELOGIN_STATUSES
    raw = extra.get("session_expires_at")
    if raw:
        try:
            exp = datetime.fromisoformat(str(raw).replace("Z", ""))
            if exp <= next_friday_noon(now):
                return True
        except ValueError:
            pass
    saved = extra.get("session_saved_at")
    if saved:
        try:
            saved_at = datetime.fromisoformat(str(saved).replace("Z", ""))
            if saved_at <= now - SESSION_STALE_AFTER:
                return True
        except ValueError:
            pass
    return False


def _seat_has_waiting_deliveries(db: Session, seat: CreatorSeat) -> bool:
    from app.models.schemas import DistributionDelivery, Release

    q = db.query(DistributionDelivery.id).filter(
        DistributionDelivery.channel_code == seat.channel_code,
        DistributionDelivery.status.in_(("session_wait", "session_running")),
        DistributionDelivery.store_url.is_(None),
    )
    if seat.ownership == "user":
        if not seat.user_id:
            return False
        q = q.filter(DistributionDelivery.owner_id == seat.user_id)
    else:
        q = q.join(Release, Release.id == DistributionDelivery.release_id).filter(Release.mode == "label")
    return q.first() is not None


def release_stale_leases(db: Session, *, seat_id: str | None = None) -> int:
    stale = datetime.utcnow() - timedelta(seconds=LEASE_SECONDS)
    q = db.query(SeatJob).filter(
        SeatJob.status == "leased",
        SeatJob.leased_at.isnot(None),
        SeatJob.leased_at <= stale,
    )
    sid = _as_uuid(seat_id) if seat_id else None
    if sid:
        q = q.filter(SeatJob.seat_id == sid)
    released = 0
    for job in q.limit(40).all():
        job.status = "queued"
        job.lease_owner = None
        job.leased_at = None
        job.result = {**(job.result or {}), "handed_to_runtime": True, "reason": "stale_lease"}
        released += 1
    if released:
        db.flush()
    return released


def enqueue_due_relogins(db: Session, *, seat_id: str | None = None, limit: int = 20) -> int:
    q = db.query(CreatorSeat).filter(CreatorSeat.status.in_(tuple(RELOGIN_STATUSES | {"connecting", "live"})))
    sid = _as_uuid(seat_id) if seat_id else None
    if sid:
        q = q.filter(CreatorSeat.id == sid)
    seats = q.order_by(CreatorSeat.updated_at.asc()).limit(120).all()
    queued = 0
    cutoff = datetime.utcnow() - RELOGIN_COOLDOWN
    for seat in seats:
        if queued >= limit:
            break
        waiting = _seat_has_waiting_deliveries(db, seat)
        due = seat_relogin_due(seat) or waiting or seat.status in RELOGIN_STATUSES
        if seat.status == "connecting" and not waiting and not seat_relogin_due(seat):
            continue
        if not due:
            continue
        open_job = (
            db.query(SeatJob)
            .filter(
                SeatJob.seat_id == seat.id,
                SeatJob.kind == "remote_login",
                SeatJob.status.in_(("queued", "leased")),
            )
            .first()
        )
        if open_job:
            continue
        recent = (
            db.query(SeatJob)
            .filter(
                SeatJob.seat_id == seat.id,
                SeatJob.kind == "remote_login",
                SeatJob.status == "done",
                SeatJob.finished_at.isnot(None),
                SeatJob.finished_at > cutoff,
            )
            .first()
        )
        if recent:
            continue
        playbook = PLAYBOOKS.get(seat.channel_code) or {}
        login_url = playbook.get("portal") or playbook.get("harvest_url") or playbook.get("upload_url")
        extra = dict(seat.extra or {})
        remote = dict(extra.get("remote") or {})
        if remote.get("status") not in {"waiting_login", "awaiting_user", "user_finished", "ready"}:
            extra["remote"] = {
                "status": "waiting_login",
                "login_url": login_url,
                "started_at": datetime.utcnow().isoformat(),
                "note": "auto_relogin",
            }
            seat.extra = extra
        if seat.status == "connecting":
            seat.status = "needs_session"
        enqueue_job(db, seat, "remote_login", {"login_url": login_url, "capture_session": True})
        queued += 1
    if queued:
        db.flush()
    return queued


def repair_orphaned_session_deliveries(db: Session, *, seat_id: str | None = None, limit: int = 40) -> int:
    from app.models.schemas import DistributionDelivery, Release
    from app.services.distribution.assist import delivery_has_active_upload_job, park_for_session

    seat = None
    sid = _as_uuid(seat_id) if seat_id else None
    if sid:
        seat = db.query(CreatorSeat).filter(CreatorSeat.id == sid).first()
        if not seat:
            return 0
    q = db.query(DistributionDelivery).filter(
        DistributionDelivery.status.in_(("session_wait", "session_running")),
        DistributionDelivery.store_url.is_(None),
    )
    if seat:
        q = q.filter(DistributionDelivery.channel_code == seat.channel_code)
        if seat.ownership == "user" and seat.user_id:
            q = q.filter(DistributionDelivery.owner_id == seat.user_id)
    rows = q.order_by(DistributionDelivery.updated_at.asc()).limit(max(limit * 2, 80)).all()
    moved = 0
    for row in rows:
        if moved >= limit:
            break
        if not should_resume_session_delivery(row, has_active_job=delivery_has_active_upload_job(db, row)):
            continue
        bound = str((row.attempt_meta or {}).get("seat_id") or "")
        if seat and bound != str(seat.id):
            continue
        release = db.query(Release).filter(Release.id == row.release_id).first()
        if not release:
            continue
        user_ready = bool(seat and seat.ownership == "user" and seat_session_ready(seat))
        if not seat:
            target = resolve_runtime_seat(
                db,
                channel_code=row.channel_code,
                user_id=row.owner_id,
                work_id=row.work_id,
                ownership="user",
            )
            user_ready = seat_session_ready(target)
        want = seat_ownership_for(
            mode=release.mode,
            channel_code=row.channel_code,
            user_session_ready=user_ready,
        )
        if seat and seat.ownership != want:
            continue
        if want == "user":
            target = seat if seat and seat.ownership == "user" else resolve_runtime_seat(
                db,
                channel_code=row.channel_code,
                user_id=row.owner_id,
                work_id=row.work_id,
                ownership="user",
            )
            if not seat_session_ready(target):
                continue
        park_for_session(db, row, release, kick=False)
        moved += 1
    if moved:
        db.flush()
    return moved


def heal_seat_runtime(db: Session, *, seat_id: str | None = None, limit: int = 40) -> dict:
    released = release_stale_leases(db, seat_id=seat_id)
    relogins = enqueue_due_relogins(db, seat_id=seat_id)
    repaired = repair_orphaned_session_deliveries(db, seat_id=seat_id, limit=limit)
    return {"released": released, "relogins": relogins, "repaired": repaired}


def _merge_open_job(job: SeatJob, kind: str, incoming: dict) -> bool:
    if job.status not in ("queued", "leased"):
        return False
    current = dict(job.payload or {})
    if kind == "upload" and str(current.get("delivery_id") or "") != str(incoming.get("delivery_id") or ""):
        return False
    job.payload = {**current, **incoming}
    return True


def enqueue_job(db: Session, seat: CreatorSeat, kind: str, payload: dict | None = None) -> SeatJob:
    incoming = dict(payload or {})
    existing = (
        db.query(SeatJob)
        .filter(SeatJob.seat_id == seat.id, SeatJob.kind == kind, SeatJob.status.in_(("queued", "leased")))
        .order_by(SeatJob.created_at.asc())
        .all()
    )
    for job in existing:
        if _merge_open_job(job, kind, incoming):
            db.flush()
            return job
    job = SeatJob(seat_id=seat.id, kind=kind, status="queued", payload=incoming)
    nested = db.begin_nested()
    try:
        db.add(job)
        db.flush()
        nested.commit()
        return job
    except IntegrityError:
        nested.rollback()
        raced = (
            db.query(SeatJob)
            .filter(SeatJob.seat_id == seat.id, SeatJob.kind == kind, SeatJob.status.in_(("queued", "leased")))
            .order_by(SeatJob.created_at.asc())
            .all()
        )
        for open_job in raced:
            if _merge_open_job(open_job, kind, incoming):
                db.flush()
                return open_job
        raise


def release_job(db: Session, job: SeatJob, *, reason: str | None = None) -> dict:
    job.status = "queued"
    job.lease_owner = None
    job.leased_at = None
    if reason:
        job.result = {"handed_to_runtime": True, "reason": reason}
    db.commit()
    return {"id": str(job.id), "status": "queued", "handed_to_runtime": True, "result": job.result or {}}


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def seat_session_ready(seat: CreatorSeat | None) -> bool:
    return bool(seat and (getattr(seat, "extra", None) or {}).get("has_session") is True)


def actor_can_operate_seat(seat: CreatorSeat | None, actor: User | None) -> bool:
    if actor is None:
        return True
    if getattr(actor, "is_admin", False):
        return True
    if not seat:
        return False
    return seat.ownership == "user" and seat.user_id == actor.id


def get_seat(db: Session, seat_id: str, user: User | None = None, *, write: bool = False) -> CreatorSeat:
    sid = _as_uuid(seat_id)
    if not sid:
        raise HTTPException(400, "Invalid seat id")
    seat = db.query(CreatorSeat).filter(CreatorSeat.id == sid).first()
    if not seat:
        raise HTTPException(404, "Seat not found")
    if user and write and not actor_can_operate_seat(seat, user):
        raise HTTPException(403, "Seat not owned")
    if user and not write and not getattr(user, "is_admin", False):
        if seat.ownership == "user" and seat.user_id != user.id:
            raise HTTPException(403, "Seat not owned")
    return seat


def lease_jobs(
    db: Session,
    *,
    owner: str,
    kinds: list[str] | None = None,
    channel_code: str | None = None,
    seat_id: str | None = None,
    runtime: str | None = None,
    limit: int = 8,
    actor: User | None = None,
) -> list[dict]:
    now = datetime.utcnow()
    stale = now - timedelta(seconds=LEASE_SECONDS)
    from app.services.distribution.telemetry import hydrate_telemetry

    hydrate_telemetry(db)
    q = db.query(SeatJob).filter(SeatJob.status.in_(("queued", "leased")))
    if kinds:
        q = q.filter(SeatJob.kind.in_(tuple(kinds)))
    sid = _as_uuid(seat_id) if seat_id else None
    if sid:
        q = q.filter(SeatJob.seat_id == sid)
    rows = q.limit(400).all()
    rows.sort(
        key=lambda job: (
            -int((job.payload or {}).get("priority_score") or 0),
            job.created_at or datetime.min,
        )
    )
    out = []
    for job in rows:
        if len(out) >= max(1, min(limit, 20)):
            break
        if job.status == "leased" and job.leased_at and job.leased_at > stale:
            continue
        seat = db.query(CreatorSeat).filter(CreatorSeat.id == job.seat_id).first()
        if not seat:
            continue
        if channel_code and seat.channel_code != channel_code:
            continue
        if sid and seat.id != sid:
            continue
        if not actor_can_operate_seat(seat, actor):
            continue
        from app.services.seats.consent import job_matches_scopes

        if not job_matches_scopes(seat, job.kind):
            job.status = "failed"
            job.finished_at = now
            job.result = {**(job.result or {}), "error": "scope_revoked"}
            continue
        if runtime == "farm":
            if seat.runtime not in {"farm", "either"}:
                continue
            if not farm_can_run_job(job):
                continue
        elif runtime == "extension":
            if seat.runtime == "farm" and farm_can_run_job(job):
                continue
            if seat.runtime not in {"extension", "either", "farm"}:
                continue
        elif runtime and seat.runtime not in {runtime, "either"}:
            continue
        locked = (
            db.query(SeatJob)
            .filter(SeatJob.id == job.id, SeatJob.status.in_(("queued", "leased")))
            .with_for_update(skip_locked=True)
            .first()
        )
        if not locked:
            continue
        if locked.status == "leased" and locked.leased_at and locked.leased_at > stale:
            continue
        job = locked
        job.status = "leased"
        job.lease_owner = owner
        job.leased_at = now
        if job.kind == "upload":
            from app.services.distribution.catalog import channel_automation_level, preview_delivery_route

            preview = preview_delivery_route(seat.channel_code)
            level = str(preview.get("automation_level") or channel_automation_level(seat.channel_code))
            payload = dict(job.payload or {})
            payload["automation_level"] = level
            payload["degraded"] = bool(preview.get("degraded"))
            job.payload = payload
            if level == "metrics_only":
                job.status = "failed"
                job.finished_at = now
                job.result = {**(job.result or {}), "error": "metrics_only"}
                continue
            delivery_id = payload.get("delivery_id")
            if delivery_id:
                from app.models.schemas import DistributionDelivery

                delivery = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
                if delivery and delivery.status == "session_wait":
                    delivery.status = "session_running"
                    delivery.last_error = None
        playbook = channel_playbook(seat.channel_code)
        payload = job.payload or {}
        out.append(
            {
                "id": str(job.id),
                "kind": job.kind,
                "seat": serialize_seat(seat),
                "payload": payload,
                "playbook": playbook,
                "harvest_url": playbook.get("stats_url") or playbook.get("harvest_url"),
                "upload_url": payload.get("upload_url") or playbook.get("upload_url"),
            }
        )
    db.commit()
    return out


def list_pending_jobs(db: Session, *, actor: User | None, limit: int = 20) -> list[dict]:
    """Read-only queue for the desk. Does not lease."""
    rows = db.query(SeatJob).filter(SeatJob.status.in_(("queued", "leased"))).limit(400).all()
    rows.sort(
        key=lambda job: (
            -int((job.payload or {}).get("priority_score") or 0),
            job.created_at or datetime.min,
        )
    )
    out = []
    for job in rows:
        seat = db.query(CreatorSeat).filter(CreatorSeat.id == job.seat_id).first()
        if not actor_can_operate_seat(seat, actor):
            continue
        playbook = channel_playbook(seat.channel_code)
        payload = job.payload or {}
        out.append(
            {
                "id": str(job.id),
                "kind": job.kind,
                "status": job.status,
                "channel_code": seat.channel_code,
                "priority_score": int(payload.get("priority_score") or 0),
                "automation_level": payload.get("automation_level"),
                "degraded": bool(payload.get("degraded")),
                "title": payload.get("title_with_code") or payload.get("title"),
                "delivery_id": payload.get("delivery_id"),
                "upload_url": payload.get("upload_url") or playbook.get("upload_url") or playbook.get("portal"),
                "leased": job.status == "leased",
            }
        )
        if len(out) >= max(1, min(limit, 40)):
            break
    return out


def complete_job(db: Session, job_id: str, *, ok: bool, result: dict | None = None, actor: User | None = None) -> dict:
    jid = _as_uuid(job_id)
    if not jid:
        raise HTTPException(400, "Invalid job id")
    job = db.query(SeatJob).filter(SeatJob.id == jid).first()
    if not job:
        raise HTTPException(404, "Job not found")
    seat = db.query(CreatorSeat).filter(CreatorSeat.id == job.seat_id).first()
    if not actor_can_operate_seat(seat, actor):
        raise HTTPException(403, "Seat not owned")
    raw = dict(result or {})
    if (
        not ok
        and raw.get("needs_runtime")
        and not raw.get("expired")
        and not raw.get("needs_challenge")
    ):
        return release_job(db, job, reason=str(raw.get("error") or "needs_runtime"))
    cookies = raw.pop("cookies", None)
    session = raw.pop("session", None)
    job.status = "done" if ok else "failed"
    job.finished_at = datetime.utcnow()
    job.result = raw
    if seat:
        if ok and job.kind == "harvest":
            seat.last_harvest_at = datetime.utcnow()
            seat.last_error = None
        elif ok and job.kind == "sync_metrics":
            extra = dict(seat.extra or {})
            extra["last_sync_at"] = datetime.utcnow().isoformat()
            seat.extra = extra
            seat.last_error = None
        elif job.kind == "upload":
            _note_upload_steps(db, job, raw)
            applied = False
            if ok:
                applied = _apply_upload_receipt(db, job, raw)
                if not applied:
                    _mark_upload_waiting_receipt(db, job, raw)
                if applied or raw.get("filled") or raw.get("attached") or raw.get("submitted"):
                    seat.last_upload_at = datetime.utcnow()
                    seat.last_error = None
            else:
                seat.last_error = str((result or {}).get("error") or "job_failed")[:500]
                if (result or {}).get("needs_challenge"):
                    mark_challenge(db, seat, note=str((result or {}).get("error") or "challenge"))
            level = str((job.payload or {}).get("automation_level") or "")
            if not level:
                from app.services.distribution.catalog import channel_automation_level

                level = channel_automation_level(seat.channel_code)
            if (
                level == "connector_full"
                and not raw.get("needs_challenge")
                and str(raw.get("error") or "") not in {"metrics_only", "needs_runtime"}
            ):
                from app.services.distribution.telemetry import record_channel_event

                record_channel_event(db, seat.channel_code, event="attach", ok=bool(ok and (raw.get("attached") or applied)))
        elif not ok and job.kind in {"harvest", "sync_metrics"}:
            from app.services.distribution.telemetry import record_channel_event

            record_channel_event(
                db,
                seat.channel_code if seat else None,
                event="selector",
                ok=False,
            )
        elif ok and job.kind == "remote_login":
            _apply_remote_session(db, seat, {"cookies": cookies, "session": session, **raw})
        elif not ok:
            seat.last_error = str((result or {}).get("error") or "job_failed")[:500]
            if (result or {}).get("needs_challenge"):
                mark_challenge(db, seat, note=str((result or {}).get("error") or "challenge"))
            elif (result or {}).get("expired"):
                seat.status = "expired"
                extra = dict(seat.extra or {})
                extra["has_session"] = False
                seat.extra = extra
    db.commit()
    return {"id": str(job.id), "status": job.status, "result": job.result}


_RESUME_HOLD_EVENTS = {"fields_filled", "master_attached", "submitted", "receipt", "planted"}


def should_resume_session_delivery(row, *, has_active_job: bool) -> bool:
    """Re-queue only when no live seat job exists. Successful fills keep waiting for a receipt."""
    if has_active_job:
        return False
    events = list(((getattr(row, "attempt_meta", None) or {}).get("submissions") or []))
    last = events[-1] if events and isinstance(events[-1], dict) else {}
    if str(last.get("event") or "") in _RESUME_HOLD_EVENTS:
        return False
    return True


def resume_waiting_uploads(db: Session, seat: CreatorSeat) -> int:
    if (seat.extra or {}).get("has_session") is not True:
        return 0
    from app.models.schemas import DistributionDelivery, Release
    from app.services.distribution.assist import delivery_has_active_upload_job, park_for_session

    q = db.query(DistributionDelivery).filter(
        DistributionDelivery.channel_code == seat.channel_code,
        DistributionDelivery.status.in_(("session_wait", "session_running")),
    )
    if seat.ownership == "user":
        if not seat.user_id:
            return 0
        q = q.filter(DistributionDelivery.owner_id == seat.user_id)
    else:
        q = q.join(Release, Release.id == DistributionDelivery.release_id).filter(Release.mode == "label")
    moved = 0
    for row in q.with_for_update().limit(40).all():
        if not should_resume_session_delivery(row, has_active_job=delivery_has_active_upload_job(db, row)):
            continue
        release = db.query(Release).filter(Release.id == row.release_id).first()
        if not release:
            continue
        want = seat_ownership_for(
            mode=release.mode,
            channel_code=row.channel_code,
            user_session_ready=seat.ownership == "user" and seat_session_ready(seat),
        )
        if want != seat.ownership:
            continue
        park_for_session(db, row, release, kick=False)
        moved += 1
    return moved


def seat_ownership_for(
    *,
    mode: str | None,
    channel_code: str | None,
    user_session_ready: bool = False,
) -> str:
    if (mode or "") == "self_release":
        return "user"
    from app.services.distribution.catalog import channel_delivery_mode

    if channel_delivery_mode(channel_code) == "session_assist":
        return "user"
    if user_session_ready:
        return "user"
    return "platform"


def resolve_runtime_seat(
    db: Session,
    *,
    channel_code: str,
    user_id=None,
    work_id=None,
    ownership: str | None = None,
) -> CreatorSeat | None:
    want = ownership or "platform"
    if want == "user":
        if not user_id:
            return None
        key = account_key(ownership="user", channel_code=channel_code, user_id=user_id)
        return db.query(CreatorSeat).filter(CreatorSeat.account_key == key).first()
    return pick_platform_seat(db, channel_code, work_id)


def ensure_user_seat(db: Session, *, channel_code: str, user_id) -> CreatorSeat | None:
    if not user_id or channel_code not in PLAYBOOKS:
        return None
    uid = _as_uuid(user_id) or user_id
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return None
    return connect_user_seat(db, user, channel_code)


COMMAND_KINDS = frozenset({"sync_metrics", "open_portal", "upload", "harvest_settle"})


def dispatch_seat_command(db: Session, user: User, seat: CreatorSeat, kind: str, payload: dict | None = None) -> dict:
    from app.services.harvest.playbooks import PLAYBOOKS
    from app.services.seats.consent import require_scope
    from app.services.seats.runtime import kick_seat_runtime

    command = (kind or "").strip()
    if command == "harvest":
        command = "harvest_settle"
    if command not in COMMAND_KINDS:
        raise HTTPException(400, "Unknown command")
    playbook = PLAYBOOKS.get(seat.channel_code) or {}
    incoming = dict(payload or {})
    if command == "open_portal":
        url = incoming.get("login_url") or playbook.get("portal") or playbook.get("harvest_url")
        job = enqueue_job(db, seat, "open_portal", {"login_url": url})
    elif command == "sync_metrics":
        require_scope(seat, "metrics")
        job = enqueue_job(db, seat, "sync_metrics", incoming)
    elif command == "harvest_settle":
        require_scope(seat, "settle")
        job = enqueue_job(db, seat, "harvest", incoming)
    else:
        require_scope(seat, "upload")
        job = enqueue_job(db, seat, "upload", incoming)
    db.commit()
    kick_seat_runtime(enqueue_due_harvest=False)
    return {"ok": True, "kind": command, "job_id": str(job.id), "seat": serialize_seat(seat)}



def _bind_delivery_seat(db: Session, payload: dict | None, seat: CreatorSeat) -> None:
    delivery_id = str((payload or {}).get("delivery_id") or "")
    if not delivery_id:
        return
    from app.models.schemas import DistributionDelivery

    delivery = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
    if not delivery:
        return
    meta = dict(delivery.attempt_meta or {})
    meta["seat_id"] = str(seat.id)
    delivery.attempt_meta = meta


TRACKS_PER_SEAT = 80


def maybe_expand_platform_pool(db: Session, channel_code: str, *, track_cap: int = TRACKS_PER_SEAT) -> int:
    from app.models.schemas import DistributionDelivery, Release

    cap = max(1, int(track_cap or TRACKS_PER_SEAT))
    n = (
        db.query(DistributionDelivery)
        .join(Release, Release.id == DistributionDelivery.release_id)
        .filter(
            DistributionDelivery.channel_code == channel_code,
            DistributionDelivery.status.in_(("live", "queued", "delivering", "session_wait", "session_running")),
            Release.mode == "label",
        )
        .count()
    )
    seats = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "platform", CreatorSeat.channel_code == channel_code)
        .all()
    )
    needed = max(1, (int(n) + cap - 1) // cap)
    if needed > len(seats):
        ensure_platform_seats(db, channels=[channel_code], pool_size=needed)
        return needed - len(seats)
    return 0


def enqueue_delivery_upload(
    db: Session,
    *,
    channel_code: str,
    user_id=None,
    work_id=None,
    payload: dict | None = None,
    ownership: str | None = None,
) -> SeatJob | None:
    want = ownership or "platform"
    if want == "user":
        seat = resolve_runtime_seat(db, channel_code=channel_code, user_id=user_id, work_id=work_id, ownership="user")
        if not seat:
            seat = ensure_user_seat(db, channel_code=channel_code, user_id=user_id)
        if not seat:
            return None
        _bind_delivery_seat(db, payload, seat)
        if not seat_session_ready(seat):
            return None
    else:
        maybe_expand_platform_pool(db, channel_code)
        seat = resolve_runtime_seat(db, channel_code=channel_code, user_id=user_id, work_id=work_id, ownership=want)
        if not seat:
            return None
        _bind_delivery_seat(db, payload, seat)
    delivery_id = str((payload or {}).get("delivery_id") or "")
    if delivery_id:
        existing = (
            db.query(SeatJob)
            .filter(
                SeatJob.seat_id == seat.id,
                SeatJob.kind == "upload",
                SeatJob.status.in_(("queued", "leased")),
            )
            .all()
        )
        for job in existing:
            if str((job.payload or {}).get("delivery_id") or "") == delivery_id:
                return job
    return enqueue_job(db, seat, "upload", payload or {})


def notify_seat_challenge(db: Session, seat: CreatorSeat, note: str | None = None) -> None:
    from app.services.notifications import create_notification

    payload = {
        "seat_id": str(seat.id),
        "channel_code": seat.channel_code,
        "ownership": seat.ownership,
        "note": note,
        "message": "席位需要二次确认。微信请开远程登录窗，电脑可用连接器继续。",
    }
    if seat.ownership == "user" and seat.user_id:
        create_notification(db, seat.user_id, "seat_challenge", payload, commit=False)
        return
    admins = db.query(User).filter(User.is_admin.is_(True)).limit(12).all()
    for admin in admins:
        create_notification(db, admin.id, "seat_challenge", payload, commit=False)


def mark_challenge(db: Session, seat: CreatorSeat, *, note: str | None = None) -> CreatorSeat:
    seat.status = "needs_challenge"
    seat.last_error = (note or "challenge")[:500]
    notify_seat_challenge(db, seat, note)
    db.flush()
    return seat


def start_remote_login(db: Session, user: User, seat: CreatorSeat) -> dict:
    playbook = PLAYBOOKS.get(seat.channel_code) or {}
    extra = dict(seat.extra or {})
    login_url = playbook.get("portal") or playbook.get("harvest_url") or playbook.get("upload_url")
    remote = dict(extra.get("remote") or {})
    if extra.get("has_session"):
        remote["status"] = "ready"
        remote.setdefault("login_url", login_url)
        extra["remote"] = remote
        seat.extra = extra
        db.flush()
        return serialize_remote(seat)
    if remote.get("status") in {"waiting_login", "awaiting_user", "user_finished"}:
        remote.setdefault("login_url", login_url)
        extra["remote"] = remote
        seat.extra = extra
        enqueue_job(
            db,
            seat,
            "remote_login",
            {"login_url": remote.get("login_url") or login_url, "capture_session": True},
        )
        db.flush()
        from app.services.seats.runtime import kick_seat_runtime

        kick_seat_runtime()
        return serialize_remote(seat)
    extra["remote"] = {
        "status": "waiting_login",
        "login_url": login_url,
        "started_at": datetime.utcnow().isoformat(),
        "screenshot": remote.get("screenshot"),
        "note": "farm_or_extension_lease_wait",
    }
    seat.extra = extra
    if seat.status not in {"live", "needs_challenge"}:
        seat.status = "needs_session"
    enqueue_job(db, seat, "remote_login", {"login_url": login_url, "capture_session": True})
    db.flush()
    from app.services.seats.runtime import kick_seat_runtime

    kick_seat_runtime()
    return serialize_remote(seat)


def _apply_remote_session(db: Session, seat: CreatorSeat, result: dict) -> None:
    cookies = result.get("cookies")
    session = result.get("session") or ({"cookies": cookies} if cookies else None)
    if not session:
        return
    save_seat_session(db, seat, session=session, mark_live=True)


def _note_upload_steps(db: Session, job: SeatJob, result: dict) -> None:
    delivery_id = str((job.payload or {}).get("delivery_id") or "")
    if not delivery_id:
        return
    from app.models.schemas import DistributionDelivery
    from app.services.distribution.submit_log import append_delivery_event

    delivery = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
    if not delivery:
        return
    events = list(result.get("events") or [])
    if result.get("filled") and "fields_filled" not in events:
        events.append("fields_filled")
    if result.get("attached") and "master_attached" not in events:
        events.append("master_attached")
    if result.get("submitted") and "submitted" not in events:
        events.append("submitted")
    for event in events:
        append_delivery_event(delivery, event=str(event), actor="connector", message=str(result.get("note") or event))


def _mark_upload_waiting_receipt(db: Session, job: SeatJob, result: dict) -> None:
    delivery_id = str((job.payload or {}).get("delivery_id") or "")
    if not delivery_id:
        return
    from app.models.schemas import DistributionDelivery

    delivery = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
    if not delivery or delivery.status in {"live", "taken_down", "rejected"}:
        return
    if result.get("needs_challenge"):
        delivery.last_error = "needs_challenge"
        return
    if result.get("submitted") and not result.get("store_url"):
        delivery.status = "in_review"
        delivery.last_error = None


def _apply_upload_receipt(db: Session, job: SeatJob, result: dict) -> bool:
    delivery_id = str((job.payload or {}).get("delivery_id") or "")
    store_url = str((result or {}).get("store_url") or "")
    if not delivery_id or not store_url:
        return False
    from app.models.schemas import DistributionDelivery
    from app.services.distribution.assist import apply_store_receipt

    delivery = db.query(DistributionDelivery).filter(DistributionDelivery.id == _as_uuid(delivery_id)).first()
    if not delivery:
        return False
    return apply_store_receipt(db, delivery, store_url, external_id=(result or {}).get("external_id"))


def ack_remote_login(db: Session, seat: CreatorSeat) -> dict:
    extra = dict(seat.extra or {})
    remote = dict(extra.get("remote") or {})
    remote["status"] = "ready" if extra.get("has_session") else "user_finished"
    extra["remote"] = remote
    seat.extra = extra
    if extra.get("has_session"):
        seat.status = "live"
        seat.last_error = None
        enqueue_job(db, seat, "harvest", {})
        resume_waiting_uploads(db, seat)
        heal_seat_runtime(db, seat_id=str(seat.id))
    else:
        enqueue_job(db, seat, "remote_login", {"capture_session": True, "login_url": remote.get("login_url")})
    db.flush()
    from app.services.seats.runtime import kick_seat_runtime

    kick_seat_runtime(enqueue_due_harvest=bool(extra.get("has_session")))
    return serialize_remote(seat)
