from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.schemas import OriginalityCheck, ProvenanceRecord, Release, ReleaseMetadata, User, Work
from app.services.distribution.catalog import DEFAULT_REQUIREMENTS
from app.services.distribution.asset_profiles import cn_originality_qc_note
from app.services.media import analyze_loudness, probe_audio, transcode_audio
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


def run_originality_check(db: Session, work: Work) -> OriginalityCheck:
    collisions = 0
    if work.content_hash:
        collisions = (
            db.query(Work)
            .filter(Work.content_hash == work.content_hash, Work.id != work.id)
            .count()
        )
    score = min(100, collisions * 40)
    vendor = _vendor_fingerprint(work)
    if vendor.get("risk_score") is not None:
        score = max(score, int(vendor["risk_score"]))
    row = OriginalityCheck(
        work_id=work.id,
        content_hash=work.content_hash,
        collision_count=collisions,
        risk_score=score,
        detail={
            "note": "站内哈希撞库，不当作法律鉴定",
            "vendor": vendor or None,
        },
    )
    db.add(row)
    db.flush()
    return row


def _vendor_fingerprint(work: Work) -> dict:
    from app.config import settings

    url = (settings.fingerprint_api_url or "").strip()
    if not url or not work.content_hash:
        return {}
    try:
        import httpx

        headers = {"Accept": "application/json"}
        if settings.fingerprint_api_key:
            headers["Authorization"] = f"Bearer {settings.fingerprint_api_key}"
        resp = httpx.post(
            url,
            json={"content_hash": work.content_hash, "work_id": str(work.id)},
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
        if not isinstance(body, dict):
            return {"ok": False}
        risk = body.get("risk_score")
        return {
            "ok": True,
            "provider": body.get("provider") or "fingerprint",
            "risk_score": int(risk) if risk is not None else None,
            "match_count": body.get("match_count"),
        }
    except Exception as exc:
        logger.warning("fingerprint vendor failed for %s: %s", work.id, exc)
        return {"ok": False, "error": str(exc)[:200]}


def draft_metadata(db: Session, work: Work, user: User) -> dict:
    lyrics = None
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    if prov and isinstance(prov.music_request, dict):
        lyrics = prov.music_request.get("lyrics")
    return {
        "title": work.title,
        "artist_name": user.display_name or user.username,
        "lyrics": lyrics,
        "genres": work.genres or [],
        "language": "zh",
        "copyright_year": datetime.utcnow().year,
        "ai_disclosed": False,
        "cover_url": work.cover_url,
        "isrc": work.isrc,
    }


def infer_qc_artist(meta: ReleaseMetadata | None, work: Work | None, user: User | None) -> str:
    if meta and str(meta.artist_name or "").strip():
        return str(meta.artist_name).strip()
    if user and str(user.display_name or user.username or "").strip():
        return str(user.display_name or user.username).strip()
    return ""


def run_release_qc(
    db: Session,
    work: Work,
    audio_bytes: bytes | None = None,
    release: Release | None = None,
    user: User | None = None,
) -> dict:
    storage = get_storage_service()
    payload = audio_bytes
    if payload is None and work.storage_key:
        try:
            payload = storage.get_object_bytes(work.storage_key)
        except Exception as exc:
            logger.warning("QC download failed for %s: %s", work.id, exc)
            payload = None

    meta = None
    if release:
        meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    title = (meta.title if meta else None) or work.title
    artist = infer_qc_artist(meta, work, user)
    cover = (meta.cover_url if meta else None) or work.cover_url

    probe = probe_audio(payload) if payload else {}
    loudness = analyze_loudness(payload) if payload else {"ok": False}
    originality = run_originality_check(db, work)
    req = DEFAULT_REQUIREMENTS
    duration = probe.get("duration") or work.duration
    from app.core.lyrics_structure import contains_structure_tags, lyrics_body_length
    from app.services.distribution.channel_fields import listing_from_metadata

    listing = listing_from_metadata(meta) if meta is not None else {}
    raw_lyrics = (meta.lyrics if meta and meta.lyrics else "") or ""
    instrumental = listing.get("instrumental") is True or raw_lyrics.strip() == "纯音乐"
    sample_rate = probe.get("sample_rate")
    channels = probe.get("channels")
    true_peak = loudness.get("input_tp")
    checks = {
        "has_audio": bool(payload),
        "duration_ok": duration is None or req["min_duration"] <= float(duration) <= req["max_duration"],
        "loudness_ok": (not loudness.get("ok")) or (loudness.get("input_i") is None) or loudness.get("input_i") <= -9,
        "true_peak_ok": true_peak is None or float(true_peak) <= -0.1,
        "audio_format_ok": (sample_rate in (None, 44100, 48000)) and (channels in (None, 1, 2)),
        "originality_ok": originality.risk_score < 80,
        "has_title": bool(title and str(title).strip()),
        "has_artist": bool(artist and str(artist).strip()),
        "has_cover": bool(cover),
        "ai_disclosed": bool(meta.ai_disclosed) if meta is not None else release is None,
        "lyrics_ready": instrumental
        or listing.get("instrumental") is not False
        or lyrics_body_length(raw_lyrics) > 0,
        "lyrics_plain": not contains_structure_tags(raw_lyrics),
    }
    from app.services.distribution.channel_fields import missing_release_fields

    metadata_gaps = missing_release_fields(meta, list(release.selected_channels or []) if release else None)
    skip = {"has_cover"}
    if release is None:
        skip.add("ai_disclosed")
    required = {key: value for key, value in checks.items() if key not in skip}
    passed = all(required.values())
    assets: dict = {}
    if payload:
        from app.services.stem_assets import persist_master_wav

        master = persist_master_wav(work, payload)
        if master:
            assets["wav"] = {"key": master.get("key"), "url": master.get("url")}
        mp3 = transcode_audio(payload, fmt="mp3", bitrate="320k")
        if mp3:
            key, url = storage.upload_bytes(mp3, f"works/{work.id}/master_320.mp3", "audio/mpeg")
            assets["mp3_320"] = {"key": key, "url": url}

    result = {
        "passed": passed,
        "checks": checks,
        "probe": probe,
        "loudness": {k: v for k, v in loudness.items() if k != "raw"},
        "originality": {
            "risk_score": originality.risk_score,
            "collision_count": originality.collision_count,
        },
        "assets": assets,
        "cn_originality": cn_originality_qc_note(
            work,
            list(release.selected_channels or []) if release else None,
        ),
        "metadata_gaps": metadata_gaps,
        "metadata_ready": not metadata_gaps,
    }
    return result


def run_generation_preflight(work: Work, audio_bytes: bytes | None = None) -> dict:
    """Loudness + duration only — run right after generate, before the release wizard."""
    probe = probe_audio(audio_bytes) if audio_bytes else {}
    loudness = analyze_loudness(audio_bytes) if audio_bytes else {"ok": False}
    req = DEFAULT_REQUIREMENTS
    duration = probe.get("duration") or work.duration
    duration_ok = duration is None or req["min_duration"] <= float(duration) <= req["max_duration"]
    loudness_ok = (not loudness.get("ok")) or (loudness.get("input_i") is None) or loudness.get("input_i") <= -9
    return {
        "passed": bool(duration_ok and loudness_ok),
        "duration_ok": bool(duration_ok),
        "loudness_ok": bool(loudness_ok),
        "has_cover": bool(work.cover_url),
        "duration": duration,
        "lufs": loudness.get("input_i"),
    }


def preflight_from_qc(work: Work, qc: dict | None) -> dict:
    checks = (qc or {}).get("checks") if isinstance(qc, dict) else None
    if not isinstance(checks, dict):
        return run_generation_preflight(work, None)
    loudness = (qc or {}).get("loudness") if isinstance(qc, dict) else {}
    probe = (qc or {}).get("probe") if isinstance(qc, dict) else {}
    orig = (qc or {}).get("originality") if isinstance(qc, dict) else {}
    return {
        "passed": bool(checks.get("duration_ok") and checks.get("loudness_ok")),
        "duration_ok": bool(checks.get("duration_ok")),
        "loudness_ok": bool(checks.get("loudness_ok")),
        "has_cover": bool(checks.get("has_cover") or work.cover_url),
        "duration": (probe or {}).get("duration") or work.duration,
        "lufs": (loudness or {}).get("input_i"),
        "originality_risk": int((orig or {}).get("risk_score") or 0),
    }


def ensure_release_draft(db: Session, work: Work, user: User) -> Release:
    locked = db.query(Work).filter(Work.id == work.id).with_for_update().first()
    if locked:
        work = locked
    existing = (
        db.query(Release)
        .filter(Release.work_id == work.id, Release.owner_id == user.id)
        .order_by(Release.created_at.desc())
        .first()
    )
    if existing and existing.status in ("draft", "qc", "pending_license", "queued", "delivering", "live"):
        release = existing
    else:
        release = Release(work_id=work.id, owner_id=user.id, mode="label", status="draft")
        db.add(release)
        db.flush()
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    draft = draft_metadata(db, work, user)
    if not meta:
        meta = ReleaseMetadata(release_id=release.id, **{k: v for k, v in draft.items() if k != "isrc"})
        meta.isrc = draft.get("isrc")
        db.add(meta)
        db.flush()
    from app.services.distribution.automation import prepare_release_automation

    prepare_release_automation(db, work, user, release)
    return release
