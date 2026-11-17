"""Creator-desk connection cards: user-authorized stores vs platform seats."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import Release, User
from app.services.distribution.catalog import CHANNEL_SPECS, CHANNEL_PORTALS, channel_automation_level, channel_delivery_mode, channel_display_name
from app.services.distribution.telemetry import channel_telemetry, hydrate_telemetry
from app.services.harvest.playbooks import channel_playbook, heal_candidates


SESSION_ASSIST = frozenset(
    spec["code"] for spec in CHANNEL_SPECS if spec.get("delivery_mode") == "session_assist"
)


def _status_for(seat: dict | None, scopes: dict) -> str:
    if not seat:
        return "disconnected"
    if seat.get("needs_challenge") or seat.get("status") in {"needs_challenge", "expired", "needs_session"}:
        return "needs_login"
    if seat.get("status") in {"connecting", "disconnected"} or not seat.get("has_session"):
        if seat.get("status") == "disconnected":
            return "disconnected"
        return "needs_login"
    if scopes.get("settle"):
        return "settle"
    if scopes.get("metrics"):
        return "metrics"
    return "needs_login"


def _suggest_install(*, has_self_release: bool, channel_code: str) -> bool:
    from app.services.distribution.catalog import LAUNCH_HANDOFF_CHANNELS, STARTER_VOLUME_CHANNELS

    del has_self_release
    if channel_code in LAUNCH_HANDOFF_CHANNELS or channel_code in STARTER_VOLUME_CHANNELS:
        return True
    return False


def build_connections(db: Session, user: User, seats: list[dict] | None = None) -> list[dict]:
    rows = list(seats or [])
    by_user: dict[str, dict] = {}
    by_platform: dict[str, dict] = {}
    for seat in rows:
        code = seat.get("channel_code") or ""
        if seat.get("ownership") == "user":
            by_user[code] = seat
        elif seat.get("ownership") == "platform":
            by_platform.setdefault(code, seat)

    has_self_release = (
        db.query(Release.id).filter(Release.owner_id == user.id, Release.mode == "self_release").first() is not None
    )
    from app.services.seats.consent import user_has_distribution_license

    has_license = user_has_distribution_license(db, user)
    hydrate_telemetry(db)
    out = []
    for spec in CHANNEL_SPECS:
        code = spec["code"]
        user_seat = by_user.get(code)
        platform_seat = by_platform.get(code)
        assist = channel_delivery_mode(code) == "session_assist"
        scopes = (user_seat or {}).get("scopes") if user_seat else None
        status = _status_for(user_seat, scopes or {})
        if not user_seat and platform_seat and not assist:
            status = "platform"
            if platform_seat.get("needs_challenge"):
                status = "needs_login"
        suggest = _suggest_install(has_self_release=has_self_release, channel_code=code)
        if status == "platform":
            suggest = False
        chosen = user_seat or (platform_seat if status == "platform" else None)
        book = channel_playbook(code)
        first_page = book.get("stats_url") or book.get("harvest_url") or CHANNEL_PORTALS.get(code)
        tel = channel_telemetry(db, code)
        level = channel_automation_level(code)
        permissions = ["login", "metrics"]
        if level in {"connector_full", "connector_assist"}:
            permissions.append("upload")
        out.append(
            {
                "channel_code": code,
                "name": channel_display_name(code) or spec.get("name"),
                "region": spec.get("region"),
                "delivery_mode": spec.get("delivery_mode"),
                "automation_level": level,
                "degraded": bool(tel.get("degraded_to")),
                "degraded_to": tel.get("degraded_to"),
                "portal": CHANNEL_PORTALS.get(code),
                "first_page": first_page,
                "permissions": permissions,
                "heal_candidates": heal_candidates(code),
                "status": status,
                "scopes": scopes,
                "suggest_connector": suggest,
                "seat_id": (chosen or {}).get("id"),
                "ownership": (chosen or {}).get("ownership"),
                "has_license": has_license,
                "last_sync_at": (chosen or {}).get("last_sync_at"),
                "last_harvest_at": (chosen or {}).get("last_harvest_at"),
                "relogin_due": bool((chosen or {}).get("relogin_due")),
                "session_expires_at": (chosen or {}).get("session_expires_at"),
                "farm_health": (chosen or {}).get("farm_health"),
                "seat": serialize_seat_lite(chosen),
            }
        )
    return out


def serialize_seat_lite(seat: dict | None) -> dict | None:
    if not seat:
        return None
    return {
        "id": seat.get("id"),
        "ownership": seat.get("ownership"),
        "status": seat.get("status"),
        "has_session": seat.get("has_session"),
        "needs_challenge": seat.get("needs_challenge"),
        "last_harvest_at": seat.get("last_harvest_at"),
        "last_sync_at": seat.get("last_sync_at"),
        "relogin_due": seat.get("relogin_due"),
        "session_expires_at": seat.get("session_expires_at"),
        "scopes": seat.get("scopes"),
        "farm_health": seat.get("farm_health"),
    }
