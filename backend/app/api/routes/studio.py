from typing import Literal
import uuid

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_scope
from app.config import settings
from app.api.rate_limits import check_generation_rate_limit
from app.services.legal import require_ai_notice
from app.api.schemas import ApplyPresetRequest
from app.core.style_presets import apply_preset, get_preset
from app.database import get_db
from app.core.music_intent_parser import parse_music_intent
from app.core.music_prompt_builder import MusicCreativeSpec, build_minimax_prompt
from app.core.music_spec_resolver import resolve_creative_spec
from app.core.sound_recipe_options import SOUND_RECIPE_OPTIONS
from app.integrations.minimax.cover import cover_client
from app.models.schemas import GenerationJob, User, Work
from app.services.credits import COVER_COST, LYRICS_COST
from app.services.generation_gate import charge_generation_credits, refund_charged_credits, with_credits_charged
from app.services.generation_jobs import create_generation_job, lookup_idempotent_job
from app.services.job_dispatch import dispatch_cover
from app.services.work_access import get_owned_work
from app.workers.tasks import post_process_work_task

router = APIRouter(prefix="/studio", tags=["studio"])


class JourneyPlanRequest(BaseModel):
    text_intent: str = Field(min_length=3, max_length=2000)
    steps: int = Field(default=6, ge=3, le=12)


class JourneyWaypoint(BaseModel):
    step: int
    arousal: float = Field(ge=1, le=9)
    valence: float = Field(ge=1, le=9)
    description: str = ""


class CustomJourneyRequest(BaseModel):
    title: str = "Custom Journey"
    waypoints: list[JourneyWaypoint] = Field(min_length=2, max_length=12)
    instrumental: bool = True


class LyricsGenerateRequest(BaseModel):
    theme: str
    moods: list[str] = []
    language: str = "zh"


class LyricsReviseRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=8000)
    instruction: str = Field(min_length=1, max_length=500)
    line_index: int | None = None
    language: str = "zh"


class IntentPolishRequest(BaseModel):
    text_intent: str = Field(min_length=3, max_length=300)


class IntentParseRequest(BaseModel):
    text_intent: str = Field(min_length=1, max_length=2000)
    language: str = "zh"


class PromptPreviewRequest(BaseModel):
    creative_spec: MusicCreativeSpec | None = None
    text_intent: str | None = None
    style_tags: str | None = None
    moods: list[str] = []
    genres: list[str] = []
    bpm: int | None = None
    key: str | None = None


class MusicCoverRequest(BaseModel):
    work_id: str
    prompt: str = Field(min_length=3, max_length=2000)
    lyrics: str | None = Field(default=None, max_length=8000)
    cover_mode: Literal["one_step", "two_step"] = "one_step"
    modified_lyrics: str | None = Field(default=None, max_length=3500)
    style_lock: bool = False


class CoverImageRequest(BaseModel):
    work_id: str
    prompt: str | None = None


@router.post("/apply-preset")
def apply_style_preset(
    payload: ApplyPresetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return apply_preset(
            payload.preset_id,
            steps=payload.steps,
            overrides={
                "text_intent": payload.text_intent,
                "target_curve": payload.target_curve,
                "instrumental": payload.instrumental,
                "title": payload.title,
            },
            db=db,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/presets/{preset_id}")
def get_style_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = get_preset(preset_id, db=db)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.post("/journey/plan")
async def plan_journey(
    payload: JourneyPlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.integrations.vendors.router import plan_journey as routed_plan_journey

    return await routed_plan_journey(
        db=db, text_intent=payload.text_intent, steps=payload.steps, user_id=str(user.id)
    )


@router.post("/journey/custom")
async def custom_journey(
    payload: CustomJourneyRequest,
    user: User = Depends(get_current_user),
):
    """Translate AV waypoints into a journey config for playlist generation."""
    waypoints = sorted(payload.waypoints, key=lambda w: w.step)
    start = waypoints[0]
    end = waypoints[-1]

    if end.arousal > start.arousal + 1:
        curve = "calm_to_energy"
    elif end.valence > start.valence + 1:
        curve = "sad_to_hope"
    elif start.arousal > end.arousal + 1:
        curve = "chaos_to_order"
    else:
        curve = "neutral"

    return {
        "title": payload.title,
        "journey": {
            "mode": "markov",
            "steps": len(waypoints),
            "target_curve": curve,
            "instrumental": payload.instrumental,
            "waypoints": [w.model_dump() for w in waypoints],
        },
        "music_params": {"bpm_range": [80, 120], "key": "auto", "duration_preference": "medium"},
    }


@router.post("/lyrics/generate")
async def lyrics_generate(
    payload: LyricsGenerateRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    from app.services.content_moderation import check_content_moderation

    err = check_content_moderation(payload.theme)
    if err:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=err)
    charged = charge_generation_credits(db, user.id, cost=LYRICS_COST)
    try:
        from app.integrations.vendors.router import generate_lyrics as routed_generate_lyrics

        result = await routed_generate_lyrics(
            db=db,
            theme=payload.theme,
            moods=payload.moods,
            language=payload.language,
            user_id=str(user.id),
        )
    except Exception:
        refund_charged_credits(db, user.id, charged)
        raise
    from app.services.credits import credits_snapshot

    return {
        "lyrics": result.lyrics,
        "style_tags": result.style_tags,
        "song_title": result.song_title,
        **credits_snapshot(db, user.id),
    }


@router.post("/lyrics/revise")
async def lyrics_revise(
    payload: LyricsReviseRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
):
    require_ai_notice(user)
    lines = payload.lyrics.splitlines()
    focus = ""
    if payload.line_index is not None and 0 <= payload.line_index < len(lines):
        focus = lines[payload.line_index]
    system = (
        "You revise song lyrics. Keep structure tags like [Verse]/[Chorus]. "
        "Return plain lyrics only, no commentary."
    )
    user_msg = (
        f"Language: {payload.language}\nInstruction: {payload.instruction}\n"
        f"{'Focus line: ' + focus + chr(10) if focus else ''}"
        f"Current lyrics:\n{payload.lyrics}"
    )
    from app.integrations.vendors.router import chat as routed_chat

    revised = await routed_chat(
        db=db,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        user_id=str(user.id),
    )
    return {"lyrics": revised.strip() or payload.lyrics}


@router.post("/intent/polish")
async def polish_intent(
    payload: IntentPolishRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.integrations.vendors.router import polish_text_intent as routed_polish

    polished = await routed_polish(
        db=db,
        text_intent=payload.text_intent,
        user_id=str(user.id),
    )
    return {"text_intent": polished}


@router.post("/intent/parse")
async def parse_intent(
    payload: IntentParseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parsed = await parse_music_intent(
        payload.text_intent,
        language=payload.language,
        db=db,
        user_id=str(user.id),
    )
    preview_prompt = build_minimax_prompt(parsed)
    return {
        "creative_spec": parsed.model_dump(),
        "preview_prompt": preview_prompt,
    }


@router.post("/prompt/preview")
async def preview_prompt(
    payload: PromptPreviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = payload.model_dump(exclude_none=True)
    if payload.creative_spec:
        cfg["creative_spec"] = payload.creative_spec.model_dump()
    manual = payload.creative_spec
    has_chips = bool(
        manual
        and (
            manual.instruments
            or manual.genres
            or manual.moods
            or manual.tempo_feel
            or manual.texture
            or manual.meter
            or manual.era
            or manual.bpm
            or manual.bpm_range
        )
    )
    spec = await resolve_creative_spec(
        cfg,
        parse_if_sparse=bool(payload.text_intent) and not has_chips,
        db=db,
        user_id=str(user.id),
    )
    return {
        "creative_spec": spec.model_dump(),
        "preview_prompt": build_minimax_prompt(spec),
    }


@router.get("/sound-recipe/options")
def sound_recipe_options():
    return SOUND_RECIPE_OPTIONS


@router.post("/music-cover/preprocess")
async def music_cover_preprocess(
    payload: MusicCoverRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """两步翻唱步骤1：提取 cover_feature_id 与 formatted_lyrics（免费）。"""
    work = get_owned_work(db, payload.work_id, user)
    ref_url = work.audio_url
    if work.storage_key:
        from app.services.storage import get_storage_service
        ref_url = get_storage_service().get_presigned_url(work.storage_key)
    result = await cover_client.preprocess_cover(ref_url, db=db, user_id=str(user.id))
    return result


@router.post("/music-cover")
async def music_cover(
    payload: MusicCoverRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        from app.services.credits import credits_snapshot

        return {"job_id": str(existing.id), **credits_snapshot(db, user.id)}

    check_generation_rate_limit(user)
    require_ai_notice(user)
    work = get_owned_work(db, payload.work_id, user)

    charged = charge_generation_credits(db, user.id, cost=COVER_COST, defer_commit=True)

    job = create_generation_job(
        db,
        user,
        job_type="music_cover",
        config=with_credits_charged(
            {
                "work_id": str(work.id),
                "prompt": payload.prompt,
                "lyrics": payload.lyrics,
                "cover_mode": payload.cover_mode,
                "modified_lyrics": payload.modified_lyrics,
                "style_lock": payload.style_lock,
            },
            charged,
        ),
        idempotency_key=idempotency_key,
    )
    from app.services.credits import credits_snapshot

    dispatch_cover(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return {"job_id": str(job.id), **credits_snapshot(db, user.id)}


@router.post("/cover-image")
async def cover_image(
    payload: CoverImageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services import ecosystem as eco
    from app.services.credits import credits_snapshot

    work = get_owned_work(db, payload.work_id, user)
    cost = eco.charge_ai_cover(db, user)

    prompt = payload.prompt or f"Album cover, {', '.join((work.moods or [])[:3])}, emotional abstract art"
    from app.integrations.vendors.router import generate_image as routed_generate_image

    result = await routed_generate_image(prompt=prompt, db=db, user_id=str(user.id))

    if result.get("image_bytes"):
        from app.services.storage import get_storage_service
        key = f"covers/{work.id}.png"
        storage_key, url = get_storage_service().upload_bytes(result["image_bytes"], key, "image/png")
        work.cover_url = url
        work.cover_storage_key = storage_key
        eco.record_ai_cover(db, user, work, cost=cost)

    return {"cover_url": work.cover_url, "prompt": prompt, **credits_snapshot(db, user.id)}


_COVER_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
_COVER_EXTENSIONS = {"png": "png", "jpg": "jpg", "jpeg": "jpg", "webp": "webp"}
_COVER_STORE_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_MAX_COVER_BYTES = 8 * 1024 * 1024


def _sniff_image_ext(data: bytes) -> str | None:
    """Detect image type from magic bytes (WeChat often sends octet-stream)."""
    if data[:8].startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/cover-upload")
async def cover_upload(
    work_id: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
):
    """Upload a custom album cover image for a work the caller owns."""
    work = get_owned_work(db, work_id, user)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(data) > _MAX_COVER_BYTES:
        raise HTTPException(status_code=413, detail="图片过大（上限 8MB）")

    # Resolve extension: prefer content-type, then filename, then magic bytes.
    # Real devices frequently upload as application/octet-stream, so never trust
    # content-type alone.
    content_type = (file.content_type or "").lower()
    ext = _COVER_CONTENT_TYPES.get(content_type)
    if not ext and file.filename and "." in file.filename:
        ext = _COVER_EXTENSIONS.get(file.filename.rsplit(".", 1)[-1].lower())
    if not ext:
        ext = _sniff_image_ext(data)
    if not ext:
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPEG / WEBP 图片")

    store_mime = _COVER_STORE_MIME[ext]

    from app.services.storage import get_storage_service

    key = f"covers/{work.id}.{ext}"
    storage_key, url = get_storage_service().upload_bytes(data, key, store_mime)
    work.cover_url = url
    work.cover_storage_key = storage_key
    db.commit()
    db.refresh(work)
    return {"cover_url": work.cover_url}


@router.get("/works/{work_id}/mood-visual")
def mood_visual_manifest(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.mood_visual import build_mood_visual_manifest

    work = get_owned_work(db, work_id, user)
    return build_mood_visual_manifest(db, work)


@router.post("/works/{work_id}/mood-visual/export")
def export_mood_visual(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.mood_visual_export import export_mood_visual_video

    work = get_owned_work(db, work_id, user)
    return export_mood_visual_video(db, user, work)


@router.post("/works/{work_id}/post-process")
def trigger_post_process(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_work(db, work_id, user)
    post_process_work_task.apply_async(args=[work_id, str(user.id)], queue="post_process")
    return {"status": "queued", "work_id": work_id}


def _apply_section_edits(sections: list[dict], human_edits: list) -> list[dict]:
    overlay = {row["id"]: dict(row) for row in sections}
    for edit in human_edits:
        if not isinstance(edit, dict) or edit.get("kind") not in (None, "section"):
            continue
        sid = edit.get("section")
        if not sid or sid not in overlay:
            continue
        if edit.get("start") is not None:
            overlay[sid]["start"] = float(edit["start"])
        if edit.get("end") is not None:
            overlay[sid]["end"] = float(edit["end"])
    return list(overlay.values())


@router.get("/works/{work_id}/refine-hints")
def work_refine_hints(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.schemas import ProvenanceRecord

    work = get_owned_work(db, work_id, user)
    bpm: int | None = None
    music_key: str | None = None
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    if prov:
        for blob in (prov.music_request, prov.m3_request, prov.output_meta):
            if not isinstance(blob, dict):
                continue
            if bpm is None and blob.get("bpm") is not None:
                try:
                    bpm = int(blob["bpm"])
                except (TypeError, ValueError):
                    pass
            if music_key is None and blob.get("key"):
                music_key = str(blob["key"])
    from app.services.distribution.catalog import clip_windows
    from app.services.lyrics_timeline import sections_from_lyrics

    suggested_intent = f"在《{work.title}》基础上微调节奏与情绪"
    human_edits = []
    if prov and isinstance(prov.output_meta, dict):
        human_edits = list(prov.output_meta.get("human_edits") or [])
    pps = work.post_process_status if isinstance(work.post_process_status, dict) else {}
    lyrics = pps.get("lyrics")
    if not lyrics and prov and isinstance(prov.music_request, dict):
        lyrics = prov.music_request.get("lyrics")
    return {
        "work_id": str(work.id),
        "title": work.title,
        "bpm": bpm,
        "key": music_key,
        "arousal": work.arousal,
        "valence": work.valence,
        "moods": work.moods or [],
        "suggested_intent": suggested_intent,
        "sections": _apply_section_edits(
            sections_from_lyrics(lyrics, getattr(work, "duration", None)),
            human_edits,
        ),
        "clip_windows": clip_windows(getattr(work, "duration", None)),
        "human_edits": human_edits,
        "duration": getattr(work, "duration", None),
        "waveform_url": pps.get("waveform_url"),
        "audio_url": work.audio_url,
        "remelt_explain": (pps.get("remelt") or {}).get("explain") if isinstance(pps.get("remelt"), dict) else None,
        "stems": pps.get("stems") if isinstance(pps.get("stems"), dict) else {},
        "sku_kind": pps.get("sku_kind"),
    }


class HumanEditBody(BaseModel):
    kind: str = Field(default="section", max_length=32)
    section: str | None = None
    note: str | None = Field(default=None, max_length=200)
    start: float | None = None
    end: float | None = None


class TransformBody(BaseModel):
    semitones: float = Field(default=0, ge=-12, le=12)
    tempo: float = Field(default=1.0, ge=0.5, le=2.0)


class ExtendBody(BaseModel):
    duration: int = Field(default=15, ge=15, le=30)


@router.post("/works/{work_id}/human-edit")
def record_human_edit(
    work_id: str,
    payload: HumanEditBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime

    from app.models.schemas import ProvenanceRecord

    work = get_owned_work(db, work_id, user)
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    entry = {
        "kind": payload.kind,
        "section": payload.section,
        "note": payload.note,
        "start": payload.start,
        "end": payload.end,
        "at": datetime.utcnow().isoformat(),
    }
    if not prov:
        prov = ProvenanceRecord(
            work_id=work.id,
            pipeline_version=settings.pipeline_version,
            record_type="human_edit",
            output_meta={"human_edits": [entry]},
        )
        db.add(prov)
    else:
        meta = dict(prov.output_meta or {})
        edits = list(meta.get("human_edits") or [])
        edits.append(entry)
        meta["human_edits"] = edits[-20:]
        prov.output_meta = meta
    db.commit()
    return {"ok": True, "edit": entry}


@router.post("/works/{work_id}/transform")
def transform_work(
    work_id: str,
    payload: TransformBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.studio_edit import apply_transform

    work = get_owned_work(db, work_id, user)
    return apply_transform(db, user, work, semitones=payload.semitones, tempo=payload.tempo)


@router.post("/works/{work_id}/master")
def master_work(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.studio_edit import apply_master

    work = get_owned_work(db, work_id, user)
    return apply_master(db, user, work)


@router.post("/works/{work_id}/undo-edit")
def undo_work_edit(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.studio_edit import undo_last_audio_edit

    work = get_owned_work(db, work_id, user)
    return undo_last_audio_edit(db, user, work)


@router.post("/works/{work_id}/extend")
def extend_work(
    work_id: str,
    payload: ExtendBody,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    from app.services.credits import GENERATION_COST, credits_snapshot
    from app.services.job_dispatch import dispatch_single

    check_generation_rate_limit(user)
    require_ai_notice(user)
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        return {"job_id": str(existing.id), **credits_snapshot(db, user.id)}

    work = get_owned_work(db, work_id, user)
    charged = charge_generation_credits(db, user.id, cost=GENERATION_COST, defer_commit=True)
    seconds = 15 if payload.duration < 23 else 30
    job_config = with_credits_charged(
        {
            "text_intent": (
                f"Continue the song “{work.title}” from the ending for about {seconds} seconds. "
                "Keep the same melody, mood, and vocal timbre. Do not restart the arrangement."
            ),
            "seed_work_id": str(work.id),
            "title": f"{work.title} · +{seconds}s",
            "record_type": "extend",
            "extend": True,
            "extend_seconds": seconds,
            "reference": {"work_id": str(work.id)},
            "instrumental": False,
        },
        charged,
    )
    job = create_generation_job(
        db,
        user,
        job_type="single",
        config=job_config,
        idempotency_key=idempotency_key,
        status_message="续写中…",
    )
    dispatch_single(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return {"job_id": str(job.id), "work_id": str(work.id), **credits_snapshot(db, user.id)}


@router.post("/works/{work_id}/vocal-sku")
def spawn_vocal_sku_route(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi import HTTPException

    from app.services.stem_assets import spawn_vocal_sku

    work = get_owned_work(db, work_id, user)
    try:
        new_work = spawn_vocal_sku(db, work)
    except ValueError as exc:
        raise HTTPException(409, "需要先完成真分轨，才能导出清唱") from exc
    return {"work_id": str(new_work.id), "parent_work_id": str(work.id), "title": new_work.title}


@router.get("/works/{work_id}/stem-pack")
def download_stem_pack(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi import HTTPException
    from fastapi.responses import Response

    from app.services.stem_assets import stem_pack_zip

    work = get_owned_work(db, work_id, user)
    try:
        payload = stem_pack_zip(work)
    except ValueError as exc:
        raise HTTPException(409, "需要先完成真分轨，才能下载分轨包") from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{work_id}-stems.zip"'},
    )


@router.post("/works/{work_id}/instrumental-sku")
def spawn_instrumental_sku_route(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accompaniment as its own listing — not mixed into the originality zip."""
    from fastapi import HTTPException

    from app.services.stem_assets import spawn_instrumental_sku
    from app.workers.tasks import post_process_work_task

    work = get_owned_work(db, work_id, user)
    try:
        new_work = spawn_instrumental_sku(db, work)
    except ValueError as exc:
        code = str(exc)
        if code == "already_instrumental_sku":
            raise HTTPException(409, "This work is already an instrumental SKU") from exc
        raise HTTPException(409, "Demucs accompaniment is required before releasing an instrumental SKU") from exc
    post_process_work_task.apply_async(args=[str(new_work.id), str(user.id)], queue="post_process")
    return {
        "work_id": str(new_work.id),
        "parent_work_id": str(work.id),
        "title": new_work.title,
        "sku": "instrumental",
        "audio_url": new_work.audio_url,
    }


class RemixPreviewRequest(BaseModel):
    work_id: str
    remix_intent: str = Field(min_length=3, max_length=500)


@router.post("/remix/preview")
async def remix_preview(
    payload: RemixPreviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.schemas import ProvenanceRecord
    from app.services.work_access import can_remix_work, get_seed_work

    source = get_seed_work(db, payload.work_id, user)
    if not can_remix_work(source):
        raise HTTPException(status_code=403, detail="Remix not allowed for this work")
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == source.id).first()
    original_prompt = ""
    if prov and prov.music_request:
        original_prompt = prov.music_request.get("prompt", "")
    from app.integrations.vendors.router import remix_prompt as routed_remix_prompt

    remix_data = await routed_remix_prompt(
        db=db,
        original_prompt=original_prompt or source.title,
        user_intent=payload.remix_intent,
        user_id=str(user.id),
    )
    return {
        "original_prompt": original_prompt,
        "prompt": remix_data.get("prompt"),
        "bpm": remix_data.get("bpm"),
        "key": remix_data.get("key"),
    }


class StructureApplyRequest(BaseModel):
    template_id: str
    steps: int = Field(default=6, ge=2, le=12)


@router.get("/structure-templates")
def structure_templates():
    from app.core.structure_template import list_structure_templates

    return list_structure_templates()


@router.post("/structure/apply")
def apply_structure(payload: StructureApplyRequest):
    from app.core.structure_template import apply_structure_template

    try:
        waypoints = apply_structure_template(payload.template_id, payload.steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"waypoints": waypoints, "steps": payload.steps}


class DraftSaveRequest(BaseModel):
    draft_id: str | None = None
    expected_version: int | None = None
    title: str = "未命名草稿"
    mode: str = "quickTrack"
    payload: dict = {}


@router.get("/drafts")
def list_drafts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.schemas import StudioDraft

    rows = (
        db.query(StudioDraft)
        .filter(StudioDraft.user_id == user.id)
        .order_by(StudioDraft.updated_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": str(d.id),
            "title": d.title,
            "mode": d.mode,
            "payload": d.payload or {},
            "version": getattr(d, "version", 1) or 1,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in rows
    ]


@router.post("/drafts")
def save_draft(
    body: DraftSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime

    from app.models.schemas import StudioDraft

    draft = None
    if body.draft_id:
        try:
            draft = (
                db.query(StudioDraft)
                .filter(StudioDraft.id == uuid.UUID(body.draft_id), StudioDraft.user_id == user.id)
                .first()
            )
        except ValueError:
            draft = None
    if not draft:
        draft = (
            db.query(StudioDraft)
            .filter(
                StudioDraft.user_id == user.id,
                StudioDraft.mode == body.mode,
                StudioDraft.archived.is_(False),
            )
            .order_by(StudioDraft.updated_at.desc())
            .first()
        )
    if draft:
        if body.expected_version is not None and int(draft.version or 1) != body.expected_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DRAFT_VERSION_CONFLICT",
                    "message": "草稿已在其他窗口更新，请刷新后重试",
                    "current_version": int(draft.version or 1),
                },
            )
        draft.title = body.title
        draft.mode = body.mode
        draft.payload = body.payload
        draft.archived = False
        draft.version = int(draft.version or 1) + 1
        draft.updated_at = datetime.utcnow()
    else:
        draft = StudioDraft(
            user_id=user.id,
            title=body.title,
            mode=body.mode,
            payload=body.payload,
            archived=False,
            version=1,
        )
        db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"id": str(draft.id), "version": int(draft.version or 1)}


@router.delete("/drafts/{draft_id}")
def delete_draft(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.schemas import StudioDraft

    draft = (
        db.query(StudioDraft)
        .filter(StudioDraft.id == uuid.UUID(draft_id), StudioDraft.user_id == user.id)
        .first()
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    db.delete(draft)
    db.commit()
    return {"deleted": True}
