"""Idempotent official catalog so Discover / radio / search are not empty."""

from __future__ import annotations

import hashlib
import io
import math
import secrets
import wave
from typing import Any

from sqlalchemy.orm import Session

from app.models.schemas import Challenge, ChallengeEntry, EffectPack, Post, User, Work

OFFICIAL_EMAIL = "hello@bittune.local"
OFFICIAL_USERNAME = "bittune"
CATALOG_AUDIO_PREFIX = "/api/v1/catalog/audio"
SEED_SECONDS = 20
SEED_RATE = 22050

OFFICIAL_TRACKS: list[dict[str, Any]] = [
    {
        "slug": "calm-focus",
        "title": "平静专注",
        "caption": "官方种子 · 学习与写作",
        "moods": ["calm", "focus", "peaceful"],
        "genres": ["ambient"],
        "arousal": 2.0,
        "valence": 5.0,
        "hz": 196.0,
        "stations": ["focus", "calm", "daily"],
        "challenge": False,
    },
    {
        "slug": "night-lofi",
        "title": "深夜 lo-fi",
        "caption": "官方种子 · 夜间循环",
        "moods": ["night", "lofi", "calm", "nostalgic"],
        "genres": ["lofi"],
        "arousal": 2.5,
        "valence": 4.5,
        "hz": 220.0,
        "stations": ["night", "daily"],
        "challenge": False,
    },
    {
        "slug": "commute-rise",
        "title": "通勤升起",
        "caption": "官方种子 · 路上听完记完播",
        "moods": ["energetic", "hopeful", "city"],
        "genres": ["electronic"],
        "arousal": 6.5,
        "valence": 6.5,
        "hz": 261.63,
        "stations": ["commute", "daily", "weekend"],
        "challenge": True,
    },
    {
        "slug": "calm-to-hope",
        "title": "从紧到松",
        "caption": "官方种子 · 焦虑到平静",
        "moods": ["calm", "healing", "hopeful"],
        "genres": ["ambient"],
        "arousal": 3.0,
        "valence": 6.0,
        "hz": 174.61,
        "stations": ["calm", "daily"],
        "challenge": True,
    },
    {
        "slug": "folk-guitar",
        "title": "民谣吉他",
        "caption": "官方种子 · 原声怀旧",
        "moods": ["nostalgic"],
        "genres": ["folk"],
        "arousal": 4.0,
        "valence": 5.5,
        "hz": 146.83,
        "stations": ["daily", "weekend"],
        "challenge": False,
    },
    {
        "slug": "cinematic-strings",
        "title": "电影感弦乐",
        "caption": "官方种子 · 预告与希望",
        "moods": ["hopeful", "cinematic"],
        "genres": ["cinematic"],
        "arousal": 5.0,
        "valence": 6.0,
        "hz": 329.63,
        "stations": ["weekend", "daily"],
        "challenge": False,
    },
    {
        "slug": "night-space",
        "title": "夜空",
        "caption": "官方种子 · 混响与短延迟",
        "moods": ["night", "dream", "ambient"],
        "genres": ["ambient"],
        "arousal": 2.0,
        "valence": 5.0,
        "hz": 130.81,
        "stations": ["night", "focus"],
        "challenge": False,
    },
    {
        "slug": "weekend-push",
        "title": "周末推新",
        "caption": "官方种子 · 发行前试验田",
        "moods": ["energetic", "joy"],
        "genres": ["pop"],
        "arousal": 7.0,
        "valence": 7.0,
        "hz": 293.66,
        "stations": ["weekend", "commute"],
        "challenge": False,
    },
]


def catalog_audio_path(slug: str) -> str:
    return f"{CATALOG_AUDIO_PREFIX}/{slug}.wav"


def synth_loop_wav(*, hz: float, seconds: int = SEED_SECONDS, rate: int = SEED_RATE) -> bytes:
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        chunks = bytearray()
        for i in range(frames):
            t = i / rate
            env = min(1.0, i / (rate * 0.08)) * min(1.0, (frames - i) / (rate * 0.2))
            sample = math.sin(2 * math.pi * hz * t) * 0.28 * env
            overtone = math.sin(4 * math.pi * hz * t) * 0.06 * env
            value = int(max(-1.0, min(1.0, sample + overtone)) * 32767)
            chunks.extend(int(value).to_bytes(2, "little", signed=True))
        wav.writeframes(bytes(chunks))
    return buf.getvalue()


def official_track_by_slug(slug: str) -> dict[str, Any] | None:
    clean = (slug or "").replace(".wav", "").strip().lower()
    return next((row for row in OFFICIAL_TRACKS if row["slug"] == clean), None)


def list_official_tracks(*, station: str | None = None) -> list[dict[str, Any]]:
    """Public listen list. No database — works even before seed_official_catalog runs."""
    needle = (station or "").strip().lower()
    matched = [item for item in OFFICIAL_TRACKS if not needle or needle in item["stations"]]
    source = matched or list(OFFICIAL_TRACKS)
    return [
        {
            "id": f"catalog:{item['slug']}",
            "slug": item["slug"],
            "title": item["title"],
            "caption": item["caption"],
            "moods": list(item["moods"]),
            "genres": list(item["genres"]),
            "stations": list(item["stations"]),
            "audio_url": f"/catalog/audio/{item['slug']}",
            "official": True,
            "author": "比特音",
            "discovery_only": True,
        }
        for item in source
    ]


def ensure_official_artist(db: Session) -> User:
    user = (
        db.query(User).filter(User.username == OFFICIAL_USERNAME).first()
        or db.query(User).filter(User.email == OFFICIAL_EMAIL).first()
    )
    if user:
        if not user.display_name:
            user.display_name = "比特音"
        return user
    from app.services.auth import hash_password

    user = User(
        email=OFFICIAL_EMAIL,
        username=OFFICIAL_USERNAME,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        display_name="比特音",
        bio="官方种子曲与电台示范",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    db.flush()
    return user


def _upload_or_fallback(slug: str, payload: bytes) -> tuple[str, str]:
    key = f"catalog/{slug}.wav"
    try:
        from app.services.storage import get_storage_service

        stored_key, url = get_storage_service().upload_bytes(payload, key, "audio/wav")
        if url:
            return stored_key, url
    except Exception:
        pass
    return key, catalog_audio_path(slug)


def seed_official_catalog(db: Session) -> dict[str, int]:
    owner = ensure_official_artist(db)
    created_works = 0
    created_posts = 0
    created_entries = 0
    preview_url = ""
    challenge = db.query(Challenge).filter(Challenge.slug == "calm-to-chaos").first()

    for item in OFFICIAL_TRACKS:
        slug = item["slug"]
        existing = db.query(Work).filter(Work.owner_id == owner.id, Work.title == item["title"]).first()
        audio = synth_loop_wav(hz=float(item["hz"]))
        digest = hashlib.sha256(audio).hexdigest()
        storage_key, audio_url = _upload_or_fallback(slug, audio)
        if not preview_url:
            preview_url = audio_url
        if existing is None:
            existing = Work(
                owner_id=owner.id,
                title=item["title"],
                description=item["caption"],
                audio_url=audio_url,
                storage_key=storage_key,
                duration=float(SEED_SECONDS),
                visibility="public",
                moods=list(item["moods"]),
                genres=list(item["genres"]),
                arousal=item["arousal"],
                valence=item["valence"],
                content_hash=digest,
                allow_remix=True,
                is_ai_generated=True,
                post_process_status={"catalog_slug": slug, "catalog": True},
            )
            db.add(existing)
            db.flush()
            created_works += 1
        else:
            existing.audio_url = existing.audio_url or audio_url
            existing.storage_key = existing.storage_key or storage_key
            existing.visibility = "public"
            existing.moods = list(item["moods"])
            existing.genres = list(item["genres"])
            pps = dict(existing.post_process_status or {})
            pps["catalog_slug"] = slug
            pps["catalog"] = True
            existing.post_process_status = pps
        from app.services.radio.network import stamp_radio_feature

        stamp_radio_feature(existing, reason="official_catalog", rank=1, stations=list(item["stations"]), days=400)
        post = db.query(Post).filter(Post.work_id == existing.id, Post.author_id == owner.id).first()
        if post is None:
            db.add(
                Post(
                    author_id=owner.id,
                    work_id=existing.id,
                    caption=item["caption"],
                    tags=list(item["moods"]),
                    visibility="public",
                    challenge_id=challenge.id if challenge and item["challenge"] else None,
                )
            )
            created_posts += 1
        if challenge and item["challenge"]:
            entry = (
                db.query(ChallengeEntry)
                .filter(ChallengeEntry.challenge_id == challenge.id, ChallengeEntry.work_id == existing.id)
                .first()
            )
            if entry is None:
                db.add(ChallengeEntry(challenge_id=challenge.id, work_id=existing.id, user_id=owner.id))
                created_entries += 1
                challenge.participant_count = int(challenge.participant_count or 0) + 1

    pack_audio = synth_loop_wav(hz=196.0, seconds=6)
    _, pack_preview = _upload_or_fallback("pack-preview-6s", pack_audio)
    for pack in db.query(EffectPack).filter(EffectPack.is_official.is_(True)).all():
        current = (pack.preview_url or "").strip()
        if not current or "/catalog/audio/" in current:
            pack.preview_url = pack_preview

    return {"works": created_works, "posts": created_posts, "entries": created_entries}
