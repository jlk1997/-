"""Encrypted vendor API key pool. Logs never include plaintext."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.schemas import VendorKey
from app.services.seats.secrets import decrypt_blob, encrypt_blob

MUSIC_VENDORS = ("tokenhub", "minimax", "mureka", "lyria", "fun_music", "elevenlabs")
INSTRUMENTAL_VENDORS = ("stability",)
LYRICS_VENDORS = ("qwen", "minimax")
CHAT_VENDORS = ("qwen", "minimax")

DEFAULT_MODELS = {
    ("tokenhub", "music"): "minimax-music-v3.0",
    ("tokenhub", "instrumental"): "minimax-music-v3.0",
    ("minimax", "music"): "music-2.6",
    ("minimax", "cover"): "music-cover",
    ("minimax", "lyrics"): "lyrics-generation",
    ("minimax", "chat"): "MiniMax-M3",
    ("minimax", "image"): "image-01",
    ("mureka", "music"): "auto",
    ("lyria", "music"): "lyria-3-pro-preview",
    ("lyria", "instrumental"): "lyria-3-clip-preview",
    ("qwen", "lyrics"): "qwen-plus",
    ("qwen", "chat"): "qwen-plus",
    ("qwen", "image"): "qwen-image-plus",
    ("fun_music", "music"): "fun-music-v1",
    ("elevenlabs", "music"): "music-v1",
    ("stability", "instrumental"): "stable-audio-3",
}

INFLIGHT_STALE = timedelta(minutes=20)


def _prefix(secret: str) -> str:
    cleaned = (secret or "").strip()
    return cleaned[:6] if cleaned else "******"


def _bind_session(db: Session) -> Session:
    """Short session on the same engine — never commits the caller's unit of work."""
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False, expire_on_commit=False)()


def _default_max_inflight(vendor: str) -> int:
    if vendor == "tokenhub":
        return max(1, int(getattr(settings, "tokenhub_max_inflight", 4) or 4))
    if vendor == "minimax":
        return max(1, int(getattr(settings, "minimax_max_inflight", 2) or 2))
    return 2


def key_plaintext(row: VendorKey) -> str:
    blob = decrypt_blob(row.ciphertext)
    return str(blob.get("api_key") or blob.get("value") or "")


def public_row(row: VendorKey) -> dict:
    return {
        "id": str(row.id),
        "vendor": row.vendor,
        "capability": row.capability,
        "key_prefix": row.key_prefix,
        "base_url": row.base_url,
        "model": row.model,
        "weight": row.weight or 10,
        "daily_quota": row.daily_quota,
        "daily_used": row.daily_used or 0,
        "max_inflight": row.max_inflight,
        "inflight": row.inflight or 0,
        "enabled": bool(row.enabled),
        "last_error": row.last_error,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "cooldown_until": row.cooldown_until.isoformat() if row.cooldown_until else None,
    }


def add_key(
    db: Session,
    *,
    vendor: str,
    capability: str,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    weight: int = 10,
    enabled: bool = True,
    max_inflight: int | None = None,
    daily_quota: int | None = None,
) -> VendorKey:
    vendor = vendor.strip().lower()
    capability = capability.strip().lower()
    secret = api_key.strip()
    prefix = _prefix(secret)
    row = VendorKey(
        vendor=vendor,
        capability=capability,
        ciphertext=encrypt_blob({"api_key": secret}),
        key_prefix=prefix,
        base_url=(base_url or "").strip() or None,
        model=model or DEFAULT_MODELS.get((vendor, capability)),
        weight=weight,
        enabled=enabled,
        max_inflight=max_inflight if max_inflight is not None else _default_max_inflight(vendor),
        daily_quota=daily_quota,
        inflight=0,
        daily_used=0,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(VendorKey)
            .filter(
                VendorKey.vendor == vendor,
                VendorKey.capability == capability,
                VendorKey.key_prefix == prefix,
            )
            .first()
        )
        if existing:
            return existing
        raise


def _has_prefix(db: Session, vendor: str, capability: str, prefix: str) -> bool:
    return (
        db.query(VendorKey)
        .filter(
            VendorKey.vendor == vendor,
            VendorKey.capability == capability,
            VendorKey.key_prefix == prefix,
        )
        .first()
        is not None
    )


def ensure_env_keys(db: Session) -> int:
    """Import env keys once so a fresh deploy still has MiniMax."""
    seeds: list[tuple[str, str, str, str | None, int]] = []
    if settings.tokenhub_api_key:
        seeds.extend(
            [
                ("tokenhub", "music", settings.tokenhub_api_key, settings.tokenhub_api_base, 100),
                ("tokenhub", "instrumental", settings.tokenhub_api_key, settings.tokenhub_api_base, 100),
            ]
        )
    if settings.minimax_api_key:
        seeds.extend(
            [
                ("minimax", "music", settings.minimax_api_key, settings.minimax_api_base, 10),
                ("minimax", "cover", settings.minimax_api_key, settings.minimax_api_base, 10),
                ("minimax", "lyrics", settings.minimax_api_key, settings.minimax_api_base, 10),
                ("minimax", "chat", settings.minimax_api_key, settings.minimax_api_base, 10),
                ("minimax", "image", settings.minimax_api_key, settings.minimax_api_base, 10),
            ]
        )
    if getattr(settings, "mureka_api_key", ""):
        seeds.append(("mureka", "music", settings.mureka_api_key, "https://api.mureka.ai", 10))
    if getattr(settings, "gemini_api_key", ""):
        seeds.append(("lyria", "music", settings.gemini_api_key, "https://generativelanguage.googleapis.com", 10))
        seeds.append(("lyria", "instrumental", settings.gemini_api_key, "https://generativelanguage.googleapis.com", 10))
    if getattr(settings, "dashscope_api_key", ""):
        seeds.append(("qwen", "lyrics", settings.dashscope_api_key, "https://dashscope.aliyuncs.com", 10))
        seeds.append(("qwen", "chat", settings.dashscope_api_key, "https://dashscope.aliyuncs.com", 10))
        seeds.append(("qwen", "image", settings.dashscope_api_key, "https://dashscope.aliyuncs.com", 10))
    if getattr(settings, "elevenlabs_api_key", ""):
        seeds.append(("elevenlabs", "music", settings.elevenlabs_api_key, "https://api.elevenlabs.io", 10))
    if getattr(settings, "stability_api_key", ""):
        seeds.append(("stability", "instrumental", settings.stability_api_key, "https://api.stability.ai", 10))
    slot = _bind_session(db)
    created = 0
    try:
        for vendor, capability, secret, base_url, weight in seeds:
            prefix = _prefix(secret)
            if _has_prefix(slot, vendor, capability, prefix):
                continue
            add_key(
                slot,
                vendor=vendor,
                capability=capability,
                api_key=secret,
                base_url=base_url,
                weight=weight,
            )
            created += 1
        return created
    finally:
        slot.close()


def _lock_candidate(session: Session, key_id) -> VendorKey | None:
    return (
        session.query(VendorKey)
        .filter(VendorKey.id == key_id)
        .with_for_update(skip_locked=True)
        .first()
    )


def _drop_inflight(row: VendorKey) -> None:
    row.inflight = max(0, int(row.inflight or 0) - 1)


def _reclaim_stale(row: VendorKey, now: datetime) -> None:
    if int(row.inflight or 0) <= 0:
        return
    used = row.last_used_at
    if used and now - used > INFLIGHT_STALE:
        row.inflight = 0


def _quota_ok(row: VendorKey, today: date) -> bool:
    if (row.quota_date or today) != today:
        row.daily_used = 0
        row.quota_date = today
    if row.daily_quota is None:
        return True
    return int(row.daily_used or 0) < int(row.daily_quota)


def _inflight_ok(row: VendorKey) -> bool:
    cap = row.max_inflight if row.max_inflight is not None else 2
    if cap <= 0:
        return False
    return int(row.inflight or 0) < cap


def _mutate_key(db: Session, row: VendorKey, mutator: Callable[[VendorKey], None]) -> None:
    slot = _bind_session(db)
    try:
        locked = (
            slot.query(VendorKey)
            .filter(VendorKey.id == row.id)
            .with_for_update()
            .first()
        )
        if not locked:
            return
        mutator(locked)
        slot.commit()
    except Exception:
        slot.rollback()
        raise
    finally:
        slot.close()


def pick_key(
    db: Session,
    capability: str,
    *,
    skip_vendors: Iterable[str] | None = None,
    skip_ids: Iterable[str] | None = None,
    remelt: bool = False,
    avoid_vendor: str | None = None,
) -> VendorKey | None:
    ensure_env_keys(db)
    now = datetime.utcnow()
    today = date.today()
    skip = {v.strip().lower() for v in (skip_vendors or []) if v}
    skip_id = {str(i) for i in (skip_ids or []) if i}
    slot = _bind_session(db)
    try:
        # Remelt means "a different engine than the one that made the source", not "skip MiniMax".
        source_vendor = (avoid_vendor or "").strip().lower()
        if remelt and source_vendor and capability in {"music", "instrumental"} and source_vendor not in skip:
            others = (
                slot.query(VendorKey)
                .filter(
                    VendorKey.capability == capability,
                    VendorKey.enabled.is_(True),
                    VendorKey.vendor != source_vendor,
                )
                .all()
            )
            usable = [
                row
                for row in others
                if str(row.id) not in skip_id and (not row.cooldown_until or row.cooldown_until <= now)
            ]
            if usable:
                skip.add(source_vendor)
        candidates = (
            slot.query(VendorKey)
            .filter(VendorKey.capability == capability, VendorKey.enabled.is_(True))
            .order_by(VendorKey.weight.desc(), VendorKey.last_used_at.asc().nullsfirst())
            .all()
        )
        for candidate in candidates:
            cid = candidate.id
            if str(cid) in skip_id or candidate.vendor in skip:
                continue
            locked = _lock_candidate(slot, cid)
            if locked is None:
                continue
            if str(locked.id) in skip_id or locked.vendor in skip:
                slot.rollback()
                continue
            if not locked.enabled:
                slot.rollback()
                continue
            if locked.cooldown_until and locked.cooldown_until > now:
                slot.rollback()
                continue
            _reclaim_stale(locked, now)
            if not _quota_ok(locked, today) or not _inflight_ok(locked):
                slot.rollback()
                continue
            locked.inflight = int(locked.inflight or 0) + 1
            locked.daily_used = int(locked.daily_used or 0) + 1
            locked.quota_date = today
            locked.last_used_at = now
            slot.commit()
            slot.refresh(locked)
            slot.expunge(locked)
            return locked
        return None
    finally:
        slot.close()


def release_key(db: Session, row: VendorKey) -> None:
    _mutate_key(db, row, _drop_inflight)


def mark_error(db: Session, row: VendorKey, message: str, *, cooldown_seconds: int = 120) -> None:
    def _apply(locked: VendorKey) -> None:
        _drop_inflight(locked)
        locked.last_error = (message or "error")[:255]
        locked.cooldown_until = datetime.utcnow() + timedelta(seconds=cooldown_seconds)

    _mutate_key(db, row, _apply)


def mark_ok(db: Session, row: VendorKey) -> None:
    def _apply(locked: VendorKey) -> None:
        _drop_inflight(locked)
        locked.last_error = None
        locked.cooldown_until = None
        locked.last_used_at = datetime.utcnow()

    _mutate_key(db, row, _apply)
