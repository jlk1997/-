"""Persist Demucs-grade stems for CN originality packs; ffmpeg stays preview-only."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.schemas import GenerationJob, ProvenanceRecord, Work
from app.services.distribution.asset_profiles import REVIEW_STEMS_QUALITY, stems_meta
from app.services.media import transcode_audio
from app.services.stem_separator import DemucsSeparator, separate_stems
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)

STEM_NAMES = ("vocal", "drums", "bass", "other", "accompaniment", "guitar", "piano")
MAX_REVIEW_STEMS = 10
PREVIEW_ISOLATIONS = frozenset({"ffmpeg_bands", "mid_side", "full_mix_proxy", "unavailable"})
# full_mix_proxy copies the master into every "stem" — charging for it would sell the same file twice.
UNSELLABLE_ISOLATIONS = frozenset({"full_mix_proxy", "unavailable", ""})


def isolation_is_sellable(isolation: str | None) -> bool:
    """An unnamed isolation counts as unsellable: we only charge for separation we can name."""
    return (isolation or "").strip().lower() not in UNSELLABLE_ISOLATIONS

ORIGINALITY_README = """比特音原创证明包 / originality evidence
========================================

本压缩包不是正片，也不是 DistroKid / TuneCore / Spotify 的多轨上架文件。

正片上架：只传一条立体声母带（kit 内 audio/master.wav）。
审核用途：国内音乐人后台「原创证明 / 分轨 / 版权证明」补件（电音入驻或被拒后）。

诚实边界：
- 分轨来自 Demucs htdemucs 听感隔离，不是 Logic / Cubase / FL Studio 工程导出。
- AI 没有 .logicx / .flp。请用 provenance.json 里的生成记录代替假工程。
- ffmpeg 频段拆分禁止作为电音原创证明。

网易云：作品管理 → 原创证明。优先走「AI 音乐人」身份并披露，不要假装真人录音棚。
腾讯音乐人 / 酷狗：歌曲信息处分轨，或邮件 TME_tmemusicians@tencentmusic.com。
伴奏商品（K 歌 / BGM）请发行独立曲目，不要和本证明包混用。
"""

MISSING_REVIEW_STEMS_NOTE = (
    "本包无审核级分轨，请勿当作电音原创证明。"
    "ffmpeg 频段隔离只可用于预览，不能打进 originality.zip。"
)

INSTRUMENTAL_TITLE_SUFFIX = "伴奏 / Instrumental"


def _cache_profile(two_stems: bool) -> str:
    from app.config import settings

    model = (getattr(settings, "stem_model", "") or "htdemucs").strip() or "htdemucs"
    if two_stems:
        return f"{model}-vocals2"
    if "6s" in model:
        return f"{model}-6"
    return f"{model}-4"


def load_cached_stems(content_hash: str, profile: str) -> dict[str, bytes] | None:
    storage = get_storage_service()
    manifest_key = f"stems-cache/{content_hash}/{profile}.json"
    try:
        manifest = json.loads(storage.get_object_bytes(manifest_key))
    except Exception:
        return None
    keys = manifest.get("keys") if isinstance(manifest, dict) else None
    if not isinstance(keys, dict) or not keys:
        return None
    stems: dict[str, bytes] = {}
    for name, key in keys.items():
        try:
            stems[str(name)] = storage.get_object_bytes(str(key))
        except Exception:
            return None
    return stems or None


def store_cached_stems(content_hash: str, profile: str, stems: dict[str, bytes]) -> None:
    storage = get_storage_service()
    keys: dict[str, str] = {}
    for name, blob in stems.items():
        key = f"stems-cache/{content_hash}/{profile}/{name}.wav"
        storage.upload_bytes(blob, key, "audio/wav")
        keys[name] = key
    storage.upload_bytes(
        json.dumps({"keys": keys, "profile": profile}).encode("utf-8"),
        f"stems-cache/{content_hash}/{profile}.json",
        "application/json",
    )


def separate_demucs_cached(source_bytes: bytes, *, two_stems: bool = False) -> tuple[dict[str, bytes], str]:
    """Demucs output cached by audio hash. A second open of the same song does not separate again."""
    if not source_bytes:
        return {}, "preview"
    profile = _cache_profile(two_stems)
    digest = hashlib.sha256(source_bytes).hexdigest()
    cached = load_cached_stems(digest, profile)
    if cached:
        return cached, REVIEW_STEMS_QUALITY
    try:
        from app.config import settings

        stems = DemucsSeparator(two_stems=two_stems, model=settings.stem_model).separate(source_bytes)
    except RuntimeError as exc:
        logger.info("Demucs stems unavailable: %s", exc)
        return {}, "preview"
    cleaned = {name: blob for name, blob in (stems or {}).items() if name in STEM_NAMES and blob}
    if not cleaned:
        return {}, "preview"
    try:
        store_cached_stems(digest, profile, cleaned)
    except Exception:
        logger.warning("stem cache write failed")
    return cleaned, REVIEW_STEMS_QUALITY


def try_demucs_stems(source_bytes: bytes) -> tuple[dict[str, bytes], str]:
    """Review path: Demucs or empty. Never silently substitute ffmpeg bands."""
    return separate_demucs_cached(source_bytes, two_stems=False)


def preview_stems(source_bytes: bytes) -> tuple[dict[str, bytes], str]:
    stems, isolation = separate_stems(source_bytes)
    quality = REVIEW_STEMS_QUALITY if isolation == DemucsSeparator.name else "preview"
    return stems, quality


def preview_stems_ffmpeg(source_bytes: bytes) -> tuple[dict[str, bytes], str]:
    stems, isolation = separate_stems(source_bytes, preferred="ffmpeg_bands", allow_ffmpeg_fallback=True)
    return stems, isolation


def isolation_quality(isolation: str | None) -> str:
    name = (isolation or "").strip().lower()
    if name == DemucsSeparator.name:
        return REVIEW_STEMS_QUALITY
    return "preview"


def stamp_post_process(work: Work, **fields) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    pps = dict(work.post_process_status or {})
    for key, value in fields.items():
        if isinstance(value, dict) and isinstance(pps.get(key), dict):
            merged = dict(pps[key])
            merged.update(value)
            pps[key] = merged
        else:
            pps[key] = value
    work.post_process_status = pps
    try:
        flag_modified(work, "post_process_status")
    except Exception:
        pass
    return pps


def persist_master_wav(work: Work, audio_bytes: bytes) -> dict:
    """44.1kHz 16-bit stereo WAV — the listing file stores actually want."""
    pps = dict(work.post_process_status or {})
    existing = pps.get("master") if isinstance(pps.get("master"), dict) else {}
    if existing.get("key") and existing.get("url"):
        stamp_post_process(work, master=existing)
        return existing
    if not audio_bytes:
        return {}
    wav = transcode_audio(audio_bytes, fmt="wav")
    if not wav:
        return {}
    key, url = get_storage_service().upload_bytes(wav, f"works/{work.id}/master.wav", "audio/wav")
    result = {"key": key, "url": url, "sample_rate": 44100, "bit_depth": 16, "channels": 2}
    stamp_post_process(work, master=result)
    return result


def persist_work_stems(
    db: Session,
    work: Work,
    audio_bytes: bytes,
    *,
    review_grade: bool = True,
) -> dict:
    pps = dict(work.post_process_status or {})
    existing = dict(pps.get("stems") or {}) if isinstance(pps.get("stems"), dict) else {}
    if existing.get("quality") == REVIEW_STEMS_QUALITY and existing.get("keys"):
        return existing
    sku = str(pps.get("sku_kind") or existing.get("sku_kind") or "")
    if sku == "instrumental":
        existing.setdefault("quality", "preview")
        existing["skipped"] = "instrumental_sku"
        stamp_post_process(work, stems=existing)
        db.add(work)
        db.commit()
        return existing

    storage = get_storage_service()
    stems: dict[str, bytes] = {}
    quality = "preview"
    model = None
    if review_grade:
        stems, quality = try_demucs_stems(audio_bytes)
        model = "htdemucs" if quality == REVIEW_STEMS_QUALITY else None
    if quality != REVIEW_STEMS_QUALITY:
        preview, isolation = preview_stems_ffmpeg(audio_bytes)
        stems = preview
        quality = "preview"
        model = isolation

    prefix = f"works/{work.id}/stems" if quality == REVIEW_STEMS_QUALITY else f"works/{work.id}/stems-preview"
    keys: dict[str, str] = {}
    urls: dict[str, str] = {}
    for name, blob in list(stems.items())[:MAX_REVIEW_STEMS]:
        ext = "wav" if blob[:4] == b"RIFF" else "mp3"
        key = f"{prefix}/{name}.{ext}"
        mime = "audio/wav" if ext == "wav" else "audio/mpeg"
        try:
            stored_key, url = storage.upload_bytes(blob, key, mime)
        except Exception:
            logger.warning("stem upload failed for %s/%s", work.id, name)
            continue
        keys[name] = stored_key
        urls[name] = url

    label = "分轨" if quality == REVIEW_STEMS_QUALITY else "预览近似"
    meta = {
        "version": "stems_v2",
        "quality": quality,
        "model": model,
        "label": label,
        "grade": "review" if quality == REVIEW_STEMS_QUALITY else "preview",
        "keys": keys,
        "wav_keys": keys,
        "urls": urls,
        "stems": list(keys.keys()),
        "demucs_attempted": True,
        "not_daw_stems": True,
        "content_hash": hashlib.sha256(audio_bytes).hexdigest() if audio_bytes else "",
        "updated_at": datetime.utcnow().isoformat(),
    }
    if quality != REVIEW_STEMS_QUALITY:
        meta["review_blocked_reason"] = "demucs_unavailable_or_failed"
    stamp_post_process(work, stems=meta)
    db.add(work)
    db.flush()
    if quality == REVIEW_STEMS_QUALITY:
        _store_originality_zip(db, work, stems)
    db.commit()
    return stems_meta(work)


def prepare_release_assets(db: Session, work: Work, audio_bytes: bytes) -> dict:
    """Post-mix release prep: master WAV, Demucs stems, originality zip, clip pack, rebuild kits."""
    master = persist_master_wav(work, audio_bytes)
    if master:
        db.add(work)
        db.commit()
    stems = persist_work_stems(db, work, audio_bytes, review_grade=True)
    clip_ok = False
    try:
        from app.services.distribution.kit import ensure_work_clip_pack

        ensure_work_clip_pack(work)
        db.add(work)
        db.commit()
        clip_ok = True
    except Exception:
        logger.warning("clip pack persist skipped for work %s", getattr(work, "id", None))
    rebuilt = rebuild_kits_for_work(db, work)
    return {
        "master": bool(master),
        "stems_quality": stems.get("quality"),
        "originality_zip": bool(stems.get("originality_zip_key")),
        "clip_pack": clip_ok,
        "kits_rebuilt": rebuilt,
    }


def rebuild_kits_for_work(db: Session, work: Work) -> int:
    from app.models.schemas import Release
    from app.services.distribution.pipeline import ensure_kit_for_release

    rows = db.query(Release).filter(Release.work_id == work.id).all()
    rebuilt = 0
    for release in rows:
        try:
            if ensure_kit_for_release(db, release, force=True):
                rebuilt += 1
        except Exception:
            logger.warning("kit rebuild skipped for release %s", getattr(release, "id", None))
    if rebuilt:
        db.commit()
    return rebuilt


def load_review_stem_bytes(work: Work) -> dict[str, bytes]:
    meta = stems_meta(work)
    if meta.get("quality") != REVIEW_STEMS_QUALITY:
        return {}
    storage = get_storage_service()
    out: dict[str, bytes] = {}
    for name, key in list((meta.get("keys") or {}).items())[:MAX_REVIEW_STEMS]:
        if name not in STEM_NAMES or not key:
            continue
        try:
            blob = storage.get_object_bytes(key)
        except Exception:
            blob = None
        if blob:
            out[name] = blob
    return out


def originality_pack_ref(work: Work) -> dict:
    meta = stems_meta(work)
    quality = str(meta.get("quality") or "").strip().lower()
    url = meta.get("originality_zip_url")
    key = meta.get("originality_zip_key")
    ready = quality == REVIEW_STEMS_QUALITY and bool(url or key)
    return {
        "ready": ready,
        "quality": quality or "none",
        "url": url if ready else None,
        "key": key if ready else None,
        "listing_asset": "master",
        "note": "CN originality evidence only. Do not upload as the listing audio.",
    }


def ensure_work_originality_pack(work: Work) -> tuple[bytes, str]:
    from fastapi import HTTPException

    ref = originality_pack_ref(work)
    if not ref["ready"]:
        raise HTTPException(409, "Review-grade originality pack is not ready")
    data = None
    if ref.get("key"):
        try:
            data = get_storage_service().get_object_bytes(ref["key"])
        except Exception:
            data = None
    if not data:
        raise HTTPException(502, "Originality pack storage unavailable")
    return data, str(ref.get("url") or "")


def provenance_payload(db: Session | None, work: Work, *, extra: dict | None = None) -> dict:
    prov = None
    job = None
    if db is not None:
        prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
        if prov and prov.job_id:
            job = db.query(GenerationJob).filter(GenerationJob.id == prov.job_id).first()
    music = (prov.music_request if prov and isinstance(prov.music_request, dict) else {}) or {}
    output = (prov.output_meta if prov and isinstance(prov.output_meta, dict) else {}) or {}
    job_cfg = job.config if job and isinstance(job.config, dict) else {}
    model = music.get("vendor_id") or job_cfg.get("model") or job_cfg.get("vendor_id")
    pps = dict(work.post_process_status or {})
    stems = stems_meta(work)
    payload = {
        "work_id": str(work.id),
        "job_id": str(prov.job_id) if prov and prov.job_id else None,
        "model": model,
        "prompt": music.get("prompt") or music.get("text_intent"),
        "lyrics": music.get("lyrics") or pps.get("lyrics"),
        "created_at": (prov.created_at.isoformat() if prov and prov.created_at else None),
        "c2pa": bool(pps.get("c2pa_done") or pps.get("c2pa") or (prov.c2pa_manifest if prov else None)),
        "minimax_request_id": music.get("request_id") or output.get("request_id") or output.get("minimax_request_id"),
        "pipeline_version": getattr(prov, "pipeline_version", None),
        "isolation": stems.get("model") or stems.get("quality"),
        "stems_quality": stems.get("quality"),
        "not_daw_stems": True,
        "ai_generated": bool(getattr(work, "is_ai_generated", True)),
        "content_hash": getattr(work, "content_hash", None),
    }
    if extra:
        payload.update(extra)
    return payload


def build_originality_archive(
    *,
    stem_bytes: dict[str, bytes],
    provenance: dict,
    include_instrumental: bool = True,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_originality_tree(zf, stem_bytes=stem_bytes, provenance=provenance, include_instrumental=include_instrumental)
    return buf.getvalue()


def _write_originality_tree(
    zf: zipfile.ZipFile,
    *,
    stem_bytes: dict[str, bytes],
    provenance: dict,
    include_instrumental: bool,
) -> list[str]:
    written: list[str] = []
    zf.writestr("originality/README-网易-腾讯.txt", ORIGINALITY_README)
    written.append("originality/README-网易-腾讯.txt")
    zf.writestr("originality/provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2))
    written.append("originality/provenance.json")
    count = 0
    for name in STEM_NAMES:
        blob = stem_bytes.get(name)
        if not blob or count >= MAX_REVIEW_STEMS:
            continue
        if name == "accompaniment":
            continue
        mp3 = blob if blob[:3] == b"ID3" or blob[:2] == b"\xff\xfb" else transcode_audio(blob, fmt="mp3", bitrate="192k")
        if not mp3:
            continue
        path = f"originality/stems/{name}.mp3"
        zf.writestr(path, mp3)
        written.append(path)
        count += 1
    if include_instrumental and stem_bytes.get("accompaniment"):
        wav = transcode_audio(stem_bytes["accompaniment"], fmt="wav") or stem_bytes["accompaniment"]
        zf.writestr("originality/accompaniment.wav", wav)
        written.append("originality/accompaniment.wav")
    return written


def write_originality_into_kit(
    zf: zipfile.ZipFile,
    *,
    stem_bytes: dict[str, bytes],
    provenance: dict,
    include_instrumental: bool,
) -> list[str]:
    return _write_originality_tree(
        zf,
        stem_bytes=stem_bytes,
        provenance=provenance,
        include_instrumental=include_instrumental,
    )


def _store_originality_zip(db: Session, work: Work, stem_bytes: dict[str, bytes]) -> None:
    archive = build_originality_archive(
        stem_bytes=stem_bytes,
        provenance=provenance_payload(db, work),
        include_instrumental=True,
    )
    key, url = get_storage_service().upload_bytes(
        archive,
        f"works/{work.id}/originality.zip",
        "application/zip",
    )
    stamp_post_process(work, stems={"originality_zip_key": key, "originality_zip_url": url})


def find_instrumental_sku(db: Session, work: Work) -> Work | None:
    pps = work.post_process_status or {}
    ref = pps.get("instrumental_sku") if isinstance(pps, dict) else None
    if isinstance(ref, dict) and ref.get("work_id"):
        try:
            wid = uuid.UUID(str(ref["work_id"]))
        except ValueError:
            wid = None
        if wid:
            row = db.query(Work).filter(Work.id == wid, Work.owner_id == work.owner_id).first()
            if row:
                return row
    for child in db.query(Work).filter(Work.parent_work_id == work.id).all():
        if str((child.post_process_status or {}).get("sku_kind") or "") == "instrumental":
            return child
    return None


def _instrumental_bed(blobs: dict[str, bytes]) -> bytes | None:
    """Drums + bass + other is the accompaniment. A single other-stem is the fallback."""
    parts = [blobs[name] for name in ("drums", "bass", "accompaniment") if blobs.get(name)]
    if len(parts) >= 2:
        from app.services.workbench_render import _ffmpeg_amix

        mixed = _ffmpeg_amix([(blob, 1.0) for blob in parts])
        if mixed:
            return mixed
    return blobs.get("accompaniment") or blobs.get("drums")


def spawn_instrumental_sku(db: Session, work: Work) -> Work:
    """Accompaniment as a separate listing SKU — not an extra DistroKid track of the vocal mix."""
    from app.config import settings
    from app.services.distribution.catalog import clip_windows
    from app.services.media import probe_audio

    if str((work.post_process_status or {}).get("sku_kind") or "") == "instrumental":
        raise ValueError("already_instrumental_sku")
    existing = find_instrumental_sku(db, work)
    if existing:
        stamp_post_process(work, instrumental_sku={"work_id": str(existing.id), "title": existing.title})
        db.add(work)
        db.commit()
        return existing
    blobs = load_review_stem_bytes(work)
    accomp = _instrumental_bed(blobs)
    if not accomp:
        raise ValueError("demucs_accompaniment_required")
    audio = transcode_audio(accomp, fmt="mp3", bitrate="320k") or accomp
    content_hash = __import__("hashlib").sha256(audio).hexdigest()
    storage = get_storage_service()
    key = storage.generate_work_key(str(work.owner_id), "mp3")
    storage_key, url = storage.upload_bytes(audio, key, "audio/mpeg")
    probed = probe_audio(audio) or {}
    title = _instrumental_title(work.title)
    new_work = Work(
        owner_id=work.owner_id,
        title=title,
        audio_url=url,
        storage_key=storage_key,
        cover_url=work.cover_url,
        cover_storage_key=work.cover_storage_key,
        parent_work_id=work.id,
        content_hash=content_hash,
        moods=work.moods,
        genres=work.genres,
        arousal=work.arousal,
        valence=work.valence,
        visibility="private",
        duration=probed.get("duration") or work.duration,
        is_ai_generated=True,
        post_process_status={
            "sku_kind": "instrumental",
            "clip_windows": clip_windows(probed.get("duration") or work.duration),
            "stems": {"quality": "preview", "skipped": "instrumental_sku", "parent_work_id": str(work.id)},
        },
    )
    db.add(new_work)
    db.flush()
    db.add(
        ProvenanceRecord(
            work_id=new_work.id,
            parent_work_id=work.id,
            pipeline_version=settings.pipeline_version,
            step_index=0,
            record_type="instrumental_sku",
            music_request={"source_work_id": str(work.id), "isolation": "demucs_accompaniment"},
            output_meta={"sha256": content_hash, "sku": "instrumental"},
        )
    )
    stamp_post_process(work, instrumental_sku={"work_id": str(new_work.id), "title": new_work.title})
    db.add(work)
    db.commit()
    return new_work


def spawn_vocal_sku(db: Session, work: Work) -> Work:
    """Dry vocal as its own private work for a collaborator. Not a store listing by itself."""
    from app.config import settings
    from app.services.media import probe_audio

    existing_id = ((work.post_process_status or {}).get("vocal_sku") or {}).get("work_id")
    if existing_id:
        found = db.query(Work).filter(Work.id == uuid.UUID(str(existing_id))).first()
        if found:
            return found
    blobs = load_review_stem_bytes(work)
    vocal = blobs.get("vocal")
    if not vocal:
        raise ValueError("demucs_vocal_required")
    audio = transcode_audio(vocal, fmt="wav") or vocal
    content_hash = hashlib.sha256(audio).hexdigest()
    storage = get_storage_service()
    key = storage.generate_work_key(str(work.owner_id), "wav")
    storage_key, url = storage.upload_bytes(audio, key, "audio/wav")
    probed = probe_audio(audio) or {}
    new_work = Work(
        owner_id=work.owner_id,
        title=f"{(work.title or 'Untitled').strip()}（清唱）",
        audio_url=url,
        storage_key=storage_key,
        cover_url=work.cover_url,
        parent_work_id=work.id,
        content_hash=content_hash,
        visibility="private",
        duration=probed.get("duration") or work.duration,
        is_ai_generated=True,
        post_process_status={"sku_kind": "vocal", "parent_work_id": str(work.id)},
    )
    db.add(new_work)
    db.flush()
    db.add(
        ProvenanceRecord(
            work_id=new_work.id,
            parent_work_id=work.id,
            pipeline_version=settings.pipeline_version,
            step_index=0,
            record_type="vocal_sku",
            music_request={"source_work_id": str(work.id), "isolation": "demucs_vocal"},
            output_meta={"sha256": content_hash, "sku": "vocal"},
        )
    )
    stamp_post_process(work, vocal_sku={"work_id": str(new_work.id), "title": new_work.title})
    db.add(work)
    db.commit()
    return new_work


def stem_pack_zip(work: Work) -> bytes:
    """WAV zip of review stems for a collaborator. Preview bands are refused."""
    blobs = load_review_stem_bytes(work)
    if not blobs:
        raise ValueError("demucs_stems_required")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in blobs.items():
            archive.writestr(f"{name}.wav", blob)
        archive.writestr(
            "README.txt",
            "这些是听感分轨，不是宿主工程导出。请在合作协议里写明使用权。\n",
        )
    return buf.getvalue()


def _instrumental_title(title: str | None) -> str:
    base = (title or "Untitled").strip() or "Untitled"
    if INSTRUMENTAL_TITLE_SUFFIX in base or base.lower().endswith("instrumental"):
        return base
    return f"{base} ({INSTRUMENTAL_TITLE_SUFFIX})"
