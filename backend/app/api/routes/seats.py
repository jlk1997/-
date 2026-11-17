from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_or_connector as get_current_user
from app.api.surface import require_h5_desk
from app.database import get_db
from app.models.schemas import User
from app.services.harvest.ingest import ingest_harvest_rows
from app.services.harvest.playbooks import list_playbooks
from app.services.harvest.unmatched import attach_unmatched, list_unmatched
from app.services.seats import farm as farm_svc
from app.services.seats.service import (
    ack_remote_login,
    complete_job,
    connect_user_seat,
    disconnect_user_seat,
    dispatch_seat_command,
    enqueue_job,
    ensure_platform_seats,
    find_actor_seat,
    get_seat,
    heal_seat_runtime,
    lease_jobs,
    list_pending_jobs,
    list_seats,
    mark_challenge,
    save_seat_session,
    serialize_remote,
    serialize_seat,
    stamp_seat_harvest,
    start_remote_login,
)

router = APIRouter(prefix="/seats", tags=["seats"])


class ConnectBody(BaseModel):
    channel_code: str
    scopes: dict | None = None


class SessionBody(BaseModel):
    cookies: list | dict | None = None
    storage_state: dict | None = None
    credentials: dict | None = None


class HarvestBody(BaseModel):
    seat_id: str | None = None
    channel_code: str | None = None
    period_key: str | None = None
    extension_version: str | None = None
    rows: list[dict] = Field(default_factory=list)


class ScopesBody(BaseModel):
    metrics: bool | None = None
    export_csv: bool | None = None
    upload: bool | None = None
    settle: bool | None = None
    keep_sync: bool | None = None
    auto_submit: bool | None = None


class CommandBody(BaseModel):
    kind: str
    payload: dict | None = None


class JobCompleteBody(BaseModel):
    ok: bool = True
    result: dict | None = None


class ChallengeBody(BaseModel):
    code: str | None = None
    note: str | None = None


class AttachBody(BaseModel):
    work_id: str


@router.get("")
def seats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_platform_seats(db)
    db.commit()
    return {"seats": list_seats(db, user), "playbooks": list_playbooks()}


@router.get("/connections")
def connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.seats.connections import build_connections

    ensure_platform_seats(db)
    db.commit()
    seats = list_seats(db, user)
    return {"connections": build_connections(db, user, seats)}


@router.get("/connector-config")
def connector_config():
    from app.config import settings
    from app.services.distribution.catalog import CHANNEL_HOSTS, CHANNEL_PORTALS

    return {
        "origins": settings.connector_trusted_origins(),
        "hosts": CHANNEL_HOSTS,
        "portals": CHANNEL_PORTALS,
        "web_base": settings.frontend_base_url.rstrip("/"),
        "api_base": settings.api_public_url.rstrip("/"),
    }


@router.post("/connect")
def connect(
    payload: ConnectBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.seats.consent import require_settle_license, set_seat_scopes

    seat = connect_user_seat(db, user, payload.channel_code)
    if payload.scopes:
        from app.services.seats.consent import SCOPE_KEYS, seat_scopes

        current = seat_scopes(seat)
        incoming = {key: bool(value) for key, value in payload.scopes.items() if key in SCOPE_KEYS}
        if isinstance((seat.extra or {}).get("scopes"), dict):
            incoming = {key: value for key, value in incoming.items() if value}
        merged = {**current, **incoming}
        if merged.get("settle"):
            require_settle_license(db, user, seat)
        set_seat_scopes(db, seat, merged, actor=user, action="connect")
    db.commit()
    return serialize_seat(seat)


@router.post("/{seat_id}/disconnect")
def disconnect(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return disconnect_user_seat(db, user, seat_id)


@router.post("/{seat_id}/session")
def bind_session(
    seat_id: str,
    payload: SessionBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    session = payload.storage_state or ({"cookies": payload.cookies} if payload.cookies is not None else {})
    save_seat_session(db, seat, session=session, credentials=payload.credentials, mark_live=True)
    db.commit()
    return serialize_seat(seat)


@router.post("/{seat_id}/challenge")
def challenge(
    seat_id: str,
    payload: ChallengeBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    extra = dict(seat.extra or {})
    extra["challenge_code"] = payload.code
    seat.extra = extra
    if payload.code:
        seat.status = "live"
        seat.last_error = None
    else:
        mark_challenge(db, seat, note=payload.note)
    db.commit()
    return serialize_seat(seat)


@router.get("/unmatched")
def unmatched_rows(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"rows": list_unmatched(db, user, admin=bool(getattr(user, "is_admin", False)))}


@router.post("/unmatched/{unmatched_id}/attach")
def attach_row(
    unmatched_id: str,
    payload: AttachBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return attach_unmatched(db, user, unmatched_id, payload.work_id, admin=bool(getattr(user, "is_admin", False)))


@router.post("/{seat_id}/remote-login")
def remote_login_start(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    payload = start_remote_login(db, user, seat)
    db.commit()
    return payload


@router.get("/{seat_id}/remote")
def remote_login_status(seat_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    seat = get_seat(db, seat_id, user, write=True)
    return serialize_remote(seat)


@router.post("/{seat_id}/remote/ack")
def remote_login_ack(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    payload = ack_remote_login(db, seat)
    db.commit()
    return payload


@router.post("/{seat_id}/runtime-kick")
def runtime_kick(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    healed = heal_seat_runtime(db, seat_id=str(seat.id))
    db.commit()
    from app.services.seats.runtime import kick_seat_runtime

    kicked = kick_seat_runtime(enqueue_due_harvest=True)
    return {"ok": True, "kicked": kicked, **healed}


@router.patch("/{seat_id}/scopes")
def update_scopes(
    seat_id: str,
    payload: ScopesBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.seats.consent import require_settle_license, seat_scopes, set_seat_scopes

    seat = get_seat(db, seat_id, user, write=True)
    current = seat_scopes(seat)
    incoming = {key: value for key, value in payload.model_dump().items() if value is not None}
    if incoming.get("settle"):
        require_settle_license(db, user, seat)
    scopes = set_seat_scopes(db, seat, {**current, **incoming}, actor=user, action="patch")
    db.commit()
    return {"seat": serialize_seat(seat), "scopes": scopes}


@router.post("/{seat_id}/scopes/revoke")
def revoke_scopes(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.seats.consent import revoke_optional_scopes

    seat = get_seat(db, seat_id, user, write=True)
    scopes = revoke_optional_scopes(db, seat, actor=user)
    db.commit()
    return {"seat": serialize_seat(seat), "scopes": scopes}


@router.post("/{seat_id}/command")
def seat_command(
    seat_id: str,
    payload: CommandBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, seat_id, user, write=True)
    return dispatch_seat_command(db, user, seat, payload.kind, payload.payload)


@router.post("/{seat_id}/harvest")
def harvest_now(
    seat_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.seats.consent import require_scope, require_settle_license

    seat = get_seat(db, seat_id, user, write=True)
    require_scope(seat, "settle")
    require_settle_license(db, user, seat)
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    from app.models.schemas import SeatJob

    row = db.query(SeatJob).filter(SeatJob.id == job.id).first()
    return farm_svc.run_job(db, row)


@router.post("/harvest")
def harvest_rows(
    payload: HarvestBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, payload.seat_id, user, write=True) if payload.seat_id else None
    if seat is None and payload.channel_code:
        seat = find_actor_seat(db, user, payload.channel_code)
    if seat is None and not getattr(user, "is_admin", False):
        raise HTTPException(403, "Seat required")
    from app.services.seats.consent import require_scope, require_settle_license

    if seat is not None:
        require_scope(seat, "export_csv")
        require_scope(seat, "settle")
    require_settle_license(db, user, seat)
    rows = list(payload.rows or [])
    if payload.channel_code:
        for row in rows:
            row.setdefault("channel_code", payload.channel_code)
    if payload.period_key:
        for row in rows:
            row.setdefault("period_key", payload.period_key)
    result = ingest_harvest_rows(db, rows, seat=seat, actor=user, settle=True)
    if seat is not None:
        periods = result.get("periods") or []
        stamp_seat_harvest(
            seat,
            rows=len(rows),
            matched=result.get("matched"),
            unclaimed=result.get("unmatched_count"),
            source="extension",
            period_key=payload.period_key or (periods[0] if periods else None),
            reason="seat_harvest",
            extension_version=payload.extension_version,
        )
        db.commit()
        result["seat"] = serialize_seat(seat)
        from app.services.distribution.assist import connector_sync_state, last_harvest_from_seats

        result["last_harvest"] = last_harvest_from_seats([result["seat"]])
        result["sync"] = connector_sync_state(db, user, online=True)
        result["period_key"] = result["sync"].get("period_key")
    return result


@router.post("/sync")
def sync_rows(
    payload: HarvestBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    seat = get_seat(db, payload.seat_id, user, write=True) if payload.seat_id else None
    if seat is None and payload.channel_code:
        seat = find_actor_seat(db, user, payload.channel_code)
    if seat is None and not getattr(user, "is_admin", False):
        raise HTTPException(403, "Seat required")
    from app.services.seats.consent import require_scope

    if seat is not None:
        require_scope(seat, "metrics")
    rows = list(payload.rows or [])
    if payload.channel_code:
        for row in rows:
            row.setdefault("channel_code", payload.channel_code)
    if payload.period_key:
        for row in rows:
            row.setdefault("period_key", payload.period_key)
    result = ingest_harvest_rows(db, rows, seat=seat, actor=user, settle=False, source="connector_sync")
    if seat is not None:
        periods = result.get("periods") or []
        stamp_seat_harvest(
            seat,
            rows=len(rows),
            matched=result.get("matched"),
            unclaimed=result.get("unmatched_count"),
            source="extension",
            period_key=payload.period_key or (periods[0] if periods else None),
            reason="seat_sync",
            extension_version=payload.extension_version,
            synced=True,
        )
        db.commit()
        result["seat"] = serialize_seat(seat)
        from app.services.distribution.assist import connector_sync_state, last_harvest_from_seats

        result["last_harvest"] = last_harvest_from_seats([result["seat"]])
        result["sync"] = connector_sync_state(db, user, online=True)
        result["period_key"] = result["sync"].get("period_key")
    return result


@router.get("/jobs")
def jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    channel_code: str | None = None,
):
    owner = f"user:{user.id}"
    return {"jobs": lease_jobs(db, owner=owner, channel_code=channel_code, runtime="extension", actor=user)}


@router.get("/queue")
def queue(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"jobs": list_pending_jobs(db, actor=user)}


@router.post("/jobs/{job_id}/complete")
def finish_job(
    job_id: str,
    payload: JobCompleteBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return complete_job(db, job_id, ok=payload.ok, result=payload.result, actor=user)


@router.post("/farm/drain")
def drain_farm(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "Admin only")
    return farm_svc.drain_queued(db)
