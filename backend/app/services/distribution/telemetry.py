"""Per-store connector success. Degrade to assist when attach/selectors fail — never fake success."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

DEGRADE_AFTER = 8
DEGRADE_SUCCESS_RATE = 0.35
RECOVER_SUCCESS_RATE = 0.6

_STATS: dict[str, dict] = {}
_OVERRIDE: dict[str, str] = {}
_HYDRATED = False


def hydrate_telemetry(db: Session | None) -> None:
    """Reload degrade flags from seat farm_health after process restart."""
    global _HYDRATED
    if _HYDRATED or db is None:
        return
    _HYDRATED = True
    try:
        from app.models.schemas import CreatorSeat

        seats = db.query(CreatorSeat).filter(CreatorSeat.extra.isnot(None)).limit(80).all()
    except Exception:
        return
    for seat in seats:
        tel = ((seat.extra or {}).get("farm_health") or {}).get("connector_telemetry") or {}
        code = str(seat.channel_code or "").strip()
        if not code or not isinstance(tel, dict) or not tel:
            continue
        current = dict(_STATS.get(code) or {})
        if str(tel.get("updated_at") or "") >= str(current.get("updated_at") or ""):
            _STATS[code] = {**current, **tel}
        if tel.get("degraded_to"):
            _OVERRIDE[code] = str(tel["degraded_to"])


def effective_automation_level(code: str, base: str) -> str:
    forced = _OVERRIDE.get(code)
    if forced:
        return forced
    return base


def record_channel_event(db: Session | None, channel_code: str | None, *, event: str, ok: bool) -> dict:
    code = str(channel_code or "").strip()
    if not code:
        return {}
    extra = dict(_STATS.get(code) or {})
    bucket = dict(extra.get(event) or {})
    bucket["n"] = int(bucket.get("n") or 0) + 1
    bucket["ok"] = int(bucket.get("ok") or 0) + (1 if ok else 0)
    bucket["at"] = datetime.utcnow().isoformat()
    extra[event] = bucket
    extra["updated_at"] = bucket["at"]
    if event in {"attach", "selector"} and bucket["n"] >= DEGRADE_AFTER:
        rate = bucket["ok"] / max(1, bucket["n"])
        if rate < DEGRADE_SUCCESS_RATE:
            _OVERRIDE[code] = "connector_assist"
            extra["degraded_to"] = "connector_assist"
            extra["degrade_reason"] = f"{event}_rate_{rate:.2f}"
        elif rate >= RECOVER_SUCCESS_RATE and extra.get("degraded_to"):
            extra.pop("degraded_to", None)
            extra.pop("degrade_reason", None)
            _OVERRIDE.pop(code, None)
    _STATS[code] = extra
    _stamp_seat_health(db, code, extra)
    return extra


def channel_telemetry(db: Session | None, channel_code: str | None) -> dict:
    del db
    return dict(_STATS.get(str(channel_code or "").strip()) or {})


def reset_telemetry() -> None:
    global _HYDRATED
    _STATS.clear()
    _OVERRIDE.clear()
    _HYDRATED = False


def _stamp_seat_health(db: Session | None, code: str, extra: dict) -> None:
    if db is None:
        return
    try:
        from app.models.schemas import CreatorSeat

        seats = (
            db.query(CreatorSeat)
            .filter(CreatorSeat.channel_code == code)
            .limit(20)
            .all()
        )
        for seat in seats:
            health = dict((seat.extra or {}).get("farm_health") or {})
            health["connector_telemetry"] = extra
            payload = dict(seat.extra or {})
            payload["farm_health"] = health
            seat.extra = payload
            try:
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(seat, "extra")
            except Exception:
                pass
    except Exception:
        return
