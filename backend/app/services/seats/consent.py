"""User-authorized connector scopes. Stored on seat.extra, logged to UserConsentLog."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import CreatorSeat, User, UserConsentLog

SCOPE_KEYS = ("metrics", "export_csv", "upload", "settle", "keep_sync", "auto_submit")
OPTIONAL_SCOPES = ("upload", "settle", "keep_sync", "auto_submit")
DEFAULT_USER_SCOPES = {
    "metrics": True,
    "export_csv": True,
    "upload": True,
    "settle": False,
    "keep_sync": False,
    "auto_submit": False,
}
# Platform seats patrol metrics only. They never upload or settle on a user's behalf.
PLATFORM_SCOPES = {
    "metrics": True,
    "export_csv": True,
    "upload": False,
    "settle": False,
    "keep_sync": True,
    "auto_submit": False,
}
CONNECTOR_CONSENT_VERSION = "2026-09-02"
CONSENT_TYPE = "connector_scopes"


def apply_channel_scope_limits(scopes: dict, channel_code: str | None) -> dict:
    """metrics_only stores never get upload/auto_submit — they cannot take artist drops."""
    out = dict(scopes)
    try:
        from app.services.distribution.catalog import channel_automation_level

        if channel_automation_level(channel_code) == "metrics_only":
            out["upload"] = False
            out["auto_submit"] = False
    except Exception:
        return out
    return out


def default_scopes_for(channel_code: str | None, *, ownership: str = "user") -> dict:
    base = dict(PLATFORM_SCOPES if ownership == "platform" else DEFAULT_USER_SCOPES)
    return apply_channel_scope_limits(base, channel_code)


def normalize_scopes(raw: dict | None, *, ownership: str = "user") -> dict:
    if ownership == "platform":
        return dict(PLATFORM_SCOPES)
    base = dict(DEFAULT_USER_SCOPES)
    incoming = raw if isinstance(raw, dict) else {}
    for key in SCOPE_KEYS:
        if key in incoming:
            base[key] = bool(incoming[key])
    if base["settle"] or base["upload"] or base["keep_sync"] or base.get("auto_submit"):
        base["metrics"] = True
    if base.get("auto_submit"):
        base["upload"] = True
    if base["settle"]:
        base["export_csv"] = True
    return base


def seat_scopes(seat: CreatorSeat | None) -> dict:
    if seat is None:
        return dict(DEFAULT_USER_SCOPES)
    extra = dict(seat.extra or {})
    stored = extra.get("scopes") if isinstance(extra.get("scopes"), dict) else {}
    return apply_channel_scope_limits(
        normalize_scopes(stored, ownership=seat.ownership or "user"),
        getattr(seat, "channel_code", None),
    )


def has_scope(seat: CreatorSeat | None, name: str) -> bool:
    if name not in SCOPE_KEYS:
        return False
    return bool(seat_scopes(seat).get(name))


def require_scope(seat: CreatorSeat | None, name: str) -> None:
    if seat is None or seat.ownership != "user":
        return
    if not has_scope(seat, name):
        raise HTTPException(403, f"{name} scope not granted")


def user_has_upload_scope(db: Session, user: User | None, channel_code: str) -> bool:
    """Second grant for session-assist fill. Admins skip. No user seat = no."""
    if user is None:
        return False
    if getattr(user, "is_admin", False):
        return True
    seat = (
        db.query(CreatorSeat)
        .filter(
            CreatorSeat.user_id == user.id,
            CreatorSeat.channel_code == channel_code,
            CreatorSeat.ownership == "user",
        )
        .first()
    )
    return has_scope(seat, "upload")


def log_connector_consent(
    db: Session,
    user: User | None,
    *,
    channel_code: str,
    scopes: dict | None = None,
    action: str,
) -> None:
    if user is None:
        return
    channel = (channel_code or "none").strip()[:24]
    kind = f"connector_{action}:{channel}"[:64]
    db.add(
        UserConsentLog(
            user_id=user.id,
            consent_type=kind,
            version=CONNECTOR_CONSENT_VERSION,
        )
    )


def set_seat_scopes(
    db: Session,
    seat: CreatorSeat,
    incoming: dict | None,
    *,
    actor: User | None = None,
    action: str = "update",
) -> dict:
    if seat.ownership != "user":
        raise HTTPException(400, "Only your own store scopes can be changed")
    scopes = apply_channel_scope_limits(normalize_scopes(incoming, ownership="user"), seat.channel_code)
    extra = dict(seat.extra or {})
    extra["scopes"] = scopes
    extra["scopes_updated_at"] = datetime.utcnow().isoformat()
    seat.extra = extra
    log_connector_consent(db, actor, channel_code=seat.channel_code, scopes=scopes, action=action)
    db.flush()
    return scopes


def revoke_optional_scopes(
    db: Session,
    seat: CreatorSeat,
    *,
    actor: User | None = None,
    keys: tuple[str, ...] | None = None,
) -> dict:
    """Turn off settle/upload/keep_sync (or listed keys) without disconnecting the store."""
    current = seat_scopes(seat)
    for key in keys or OPTIONAL_SCOPES:
        if key in current:
            current[key] = False
    return set_seat_scopes(db, seat, current, actor=actor, action="revoke")


def grant_handoff_upload(seat: CreatorSeat) -> dict:
    """Handing a logged-in store implies BitTune may submit the stereo master."""
    if (seat.ownership or "user") != "user":
        return seat_scopes(seat)
    extra = dict(seat.extra or {})
    stored = extra.get("scopes") if isinstance(extra.get("scopes"), dict) else None
    code = getattr(seat, "channel_code", None)
    scopes = apply_channel_scope_limits(normalize_scopes(stored, ownership="user"), code)
    if channel_allows_upload(code):
        scopes["upload"] = True
    scopes["metrics"] = True
    extra["scopes"] = scopes
    seat.extra = extra
    return scopes


def channel_allows_upload(channel_code: str | None) -> bool:
    from app.services.distribution.catalog import channel_automation_level

    if not channel_code:
        return True
    return channel_automation_level(channel_code) in {"connector_full", "connector_assist"}


def ensure_default_scopes(seat: CreatorSeat) -> dict:
    extra = dict(seat.extra or {})
    if seat.ownership != "user":
        extra["scopes"] = dict(PLATFORM_SCOPES)
        seat.extra = extra
        return extra["scopes"]
    if not isinstance(extra.get("scopes"), dict):
        extra["scopes"] = default_scopes_for(seat.channel_code, ownership="user")
        seat.extra = extra
    return seat_scopes(seat)


def user_has_distribution_license(db: Session, user: User | None) -> bool:
    if user is None:
        return False
    from app.models.schemas import DistributionLicense

    return (
        db.query(DistributionLicense.id).filter(DistributionLicense.user_id == user.id).first() is not None
    )


def require_settle_license(db: Session, user: User | None, seat: CreatorSeat | None = None) -> None:
    if seat is not None and (seat.ownership or "user") != "user":
        return
    if user is None:
        raise HTTPException(403, "distribution license required to settle")
    if getattr(user, "is_admin", False):
        return
    if not user_has_distribution_license(db, user):
        raise HTTPException(403, "distribution license required to settle")


def due_job_kind(seat: CreatorSeat | None) -> str | None:
    """What the scheduler may enqueue. None = wait for an explicit tap."""
    if seat is None:
        return None
    if (seat.ownership or "user") == "platform" or has_scope(seat, "settle"):
        return "harvest"
    if has_scope(seat, "keep_sync") and has_scope(seat, "metrics"):
        return "sync_metrics"
    return None


def job_matches_scopes(seat: CreatorSeat | None, kind: str) -> bool:
    if seat is None:
        return False
    if (seat.ownership or "user") != "user":
        return True
    if kind == "harvest":
        return has_scope(seat, "settle")
    if kind == "sync_metrics":
        return has_scope(seat, "metrics")
    if kind == "upload":
        return has_scope(seat, "upload")
    return True
