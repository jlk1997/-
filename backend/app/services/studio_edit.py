"""In-place light-studio edits: transform, master, undo, provenance notes."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import ProvenanceRecord, User, Work
from app.services.media import analyze_loudness, probe_audio
from app.services.storage import get_storage_service


def _load_audio(work: Work) -> bytes:
    if not work.storage_key:
        raise HTTPException(status_code=400, detail="no_audio")
    try:
        return get_storage_service().get_object_bytes(work.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="audio_unavailable") from exc


def _append_edit(db: Session, work: Work, entry: dict) -> list:
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    if not prov:
        prov = ProvenanceRecord(
            work_id=work.id,
            pipeline_version=settings.pipeline_version,
            record_type="human_edit",
            output_meta={"human_edits": [entry], "audio_history": []},
        )
        db.add(prov)
        return [entry]
    meta = dict(prov.output_meta or {})
    edits = list(meta.get("human_edits") or [])
    edits.append(entry)
    meta["human_edits"] = edits[-20:]
    prov.output_meta = meta
    return meta["human_edits"]


def replace_work_audio(db: Session, user: User, work: Work, audio_bytes: bytes, *, edit: dict) -> dict:
    storage = get_storage_service()
    prev_key = work.storage_key
    prev_url = work.audio_url
    key = storage.generate_work_key(str(user.id))
    storage_key, url = storage.upload_bytes(audio_bytes, key)
    work.storage_key = storage_key
    work.audio_url = url
    probed = probe_audio(audio_bytes)
    if probed.get("duration"):
        work.duration = probed["duration"]
    from app.services.distribution.release_ready import run_generation_preflight

    preflight = run_generation_preflight(work, audio_bytes)
    pps = dict(work.post_process_status or {})
    pps["generation_preflight"] = preflight
    work.post_process_status = pps

    entry = {
        **edit,
        "at": datetime.utcnow().isoformat(),
        "prev_storage_key": prev_key,
        "prev_audio_url": prev_url,
    }
    _append_edit(db, work, entry)
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    if prov:
        meta = dict(prov.output_meta or {})
        history = list(meta.get("audio_history") or [])
        if prev_key:
            history.append({"storage_key": prev_key, "audio_url": prev_url})
        meta["audio_history"] = history[-5:]
        prov.output_meta = meta
    db.commit()
    db.refresh(work)
    return {
        "ok": True,
        "work_id": str(work.id),
        "audio_url": url,
        "preflight": preflight,
        "loudness": analyze_loudness(audio_bytes) if audio_bytes else {},
        "edit": entry,
    }


def apply_transform(db: Session, user: User, work: Work, *, semitones: float, tempo: float) -> dict:
    from app.services.media import transform_audio

    source = _load_audio(work)
    out = transform_audio(source, semitones=semitones, tempo=tempo)
    if not out:
        raise HTTPException(status_code=503, detail="transform_unavailable")
    result = replace_work_audio(
        db,
        user,
        work,
        out,
        edit={"kind": "transform", "semitones": semitones, "tempo": tempo},
    )
    try:
        from app.services.workbench import sync_light_editor

        sync_light_editor(db, user, str(work.id), semitones=semitones, tempo=tempo)
    except Exception:
        pass
    return result


def apply_master(db: Session, user: User, work: Work) -> dict:
    from app.services.media import normalize_loudness

    source = _load_audio(work)
    out = normalize_loudness(source)
    if not out:
        raise HTTPException(status_code=503, detail="master_unavailable")
    result = replace_work_audio(db, user, work, out, edit={"kind": "master", "target_lufs": -14})
    try:
        from app.services.workbench import sync_light_editor

        sync_light_editor(db, user, str(work.id), master=True)
    except Exception:
        pass
    return result


def undo_last_audio_edit(db: Session, user: User, work: Work) -> dict:
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    meta = dict(prov.output_meta or {}) if prov else {}
    history = list(meta.get("audio_history") or [])
    if not history:
        raise HTTPException(status_code=400, detail="nothing_to_undo")
    prev = history.pop()
    key = prev.get("storage_key")
    if not key:
        raise HTTPException(status_code=400, detail="nothing_to_undo")
    try:
        audio = get_storage_service().get_object_bytes(key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="history_unavailable") from exc
    if prov:
        meta["audio_history"] = history
        prov.output_meta = meta
    return replace_work_audio(
        db,
        user,
        work,
        audio,
        edit={"kind": "undo", "restored_key": key},
    )
