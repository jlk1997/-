"""Per-user notification channel preferences stored on UserPreference.settings."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.schemas import UserPreference

DEFAULT_NOTIFY = {
    "in_app": True,
    "wechat": True,
    "email": True,
    "recall": True,
}


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def get_notify_prefs(db: Session, user_id: uuid.UUID) -> dict[str, bool]:
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    stored = {}
    if pref and isinstance(pref.settings, dict):
        stored = pref.settings.get("notify") or {}
    if not isinstance(stored, dict):
        stored = {}
    return {key: _coerce_bool(stored.get(key), default) for key, default in DEFAULT_NOTIFY.items()}


def set_notify_prefs(db: Session, user_id: uuid.UUID, notify: dict | None) -> dict[str, bool]:
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id, mood_tags=[], genre_tags=[], settings={})
        db.add(pref)
    settings = dict(pref.settings or {})
    merged = get_notify_prefs(db, user_id)
    if isinstance(notify, dict):
        for key in DEFAULT_NOTIFY:
            if key in notify:
                merged[key] = _coerce_bool(notify.get(key), DEFAULT_NOTIFY[key])
    settings["notify"] = merged
    pref.settings = settings
    db.commit()
    return merged
