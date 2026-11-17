import json
import uuid

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import authenticate_token, get_current_user, get_optional_user, require_scope, security
from app.api.rate_limits import check_generation_rate_limit
from app.services.legal import require_ai_notice
from app.config import settings
from app.api.schemas import (
    JobResponse,
    JourneyConfig,
    MusicCreativeSpecSchema,
    MusicParams,
    PlaylistGenerateRequest,
    SingleGenerateRequest,
    Waypoint,
    WorkResponse,
    WorkUpdateRequest,
    WorkUpdateResponse,
)
from app.core.playlist_orchestrator import resolve_playlist_title
from app.database import get_db
from app.models.schemas import GenerationJob, Post, User, Work
from app.services.workbench import detach_work_from_sessions
from app.services.community_sync import sync_post_caption_for_work_rename
from app.services.credit_estimates import variation_credit_cost
from app.services.credits import GENERATION_COST, PLAYLIST_COST
from app.services.generation_gate import charge_generation_credits, with_credits_charged
from app.services.generation_jobs import create_generation_job, lookup_idempotent_job
from app.services.job_progress import job_response_with_credits, job_to_response
from app.services.tenant import scope_by_tenant
from app.services.hls import hls_prefix_from_work
from app.services.media_playback import (
    is_safe_segment_name,
    protected_hls_playlist_url,
    protected_stream_url,
    rewrite_hls_playlist_for_gateway,
    validate_playback_access,
    work_audio_storage_key,
)
from app.services.storage import get_storage_service
from app.services.work_access import (
    MAX_UPLOAD_BYTES,
    assert_seed_rights,
    can_view_work,
    get_viewable_work,
    get_viewable_work_optional,
    get_work_or_404,
    parse_uuid,
    validate_audio_upload,
)
from app.services.job_dispatch import dispatch_playlist, dispatch_single, dispatch_variations

router = APIRouter(prefix="/works", tags=["works"])


def _resolve_audio_url(work: Work, user: User | None = None) -> str:
    return protected_stream_url(work, user)


def _resolve_hls_url(work: Work, user: User | None = None) -> str | None:
    return protected_hls_playlist_url(work, user)


def work_to_response(
    work: Work,
    *,
    parent_title: str | None = None,
    lyrics: str | None = None,
    lyrics_timeline: list | None = None,
    user: User | None = None,
    live_stores: int | None = None,
    artist_name: str | None = None,
    owner_username: str | None = None,
    community_post_id: str | None = None,
    community_caption: str | None = None,
    superseded_by_work_id: str | None = None,
) -> WorkResponse:
    cover = work.cover_url
    if work.cover_storage_key:
        try:
            cover = get_storage_service().get_presigned_url(work.cover_storage_key)
        except Exception:
            pass
    from app.services.c2pa import c2pa_state as _c2pa_state

    pps = work.post_process_status or {}
    state = _c2pa_state(pps)
    return WorkResponse(
        id=str(work.id),
        title=work.title,
        description=work.description,
        audio_url=_resolve_audio_url(work, user),
        hls_url=_resolve_hls_url(work, user),
        cover_url=cover,
        duration=work.duration,
        moods=work.moods or [],
        genres=work.genres or [],
        arousal=work.arousal,
        valence=work.valence,
        visibility=work.visibility,
        parent_work_id=str(work.parent_work_id) if work.parent_work_id else None,
        parent_work_title=parent_title,
        allow_remix=work.allow_remix if work.allow_remix is not None else True,
        license=work.license or "allow_remix",
        post_process_status=work.post_process_status or {},
        c2pa_verified=state == "embedded",
        c2pa_state=state,
        version=getattr(work, "version", 1) or 1,
        is_ai_generated=getattr(work, "is_ai_generated", True),
        lyrics=lyrics,
        lyrics_timeline=lyrics_timeline,
        release_status=getattr(work, "release_status", None),
        isrc=getattr(work, "isrc", None),
        is_owner=bool(user is not None and getattr(user, "id", None) == work.owner_id),
        live_stores=int(live_stores or 0),
        commercial=bool(getattr(work, "commercial_cleared_at", None)),
        artist_name=artist_name,
        owner_username=owner_username,
        community_post_id=community_post_id,
        community_caption=community_caption,
        from_workbench=bool(pps.get("workbench")),
        superseded_by_work_id=superseded_by_work_id,
    )


def works_to_responses(db: Session, works: list[Work], user: User | None = None) -> list[WorkResponse]:
    from app.services.distribution.passport import live_store_counts

    ids = [w.id for w in works]
    counts = live_store_counts(db, ids)
    post_by_work: dict[str, Post] = {}
    owners = {w.id: w.owner_id for w in works}
    if ids:
        for post in (
            db.query(Post)
            .filter(Post.work_id.in_(ids))
            .order_by(Post.created_at.desc())
            .all()
        ):
            if owners.get(post.work_id) != post.author_id:
                continue
            key = str(post.work_id)
            if key not in post_by_work:
                post_by_work[key] = post
    successor = {
        w.parent_work_id: str(w.id)
        for w in works
        if w.parent_work_id
        and isinstance(w.post_process_status, dict)
        and w.post_process_status.get("workbench")
    }
    return [
        work_to_response(
            w,
            user=user,
            live_stores=counts.get(w.id, counts.get(str(w.id), 0)),
            community_post_id=str(post_by_work[str(w.id)].id) if str(w.id) in post_by_work else None,
            community_caption=post_by_work[str(w.id)].caption if str(w.id) in post_by_work else None,
            superseded_by_work_id=successor.get(w.id),
        )
        for w in works
    ]


def _extract_lyrics(db: Session, work: Work) -> tuple[str | None, list[dict] | None]:
    from app.models.schemas import GenerationJob, ProvenanceRecord
    from app.services.lyrics_timeline import build_lyrics_timeline

    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    lyrics = None
    embedded_timeline = None
    if prov:
        for blob in (prov.music_request, prov.m3_request, prov.output_meta):
            if isinstance(blob, dict):
                raw = blob.get("lyrics") or blob.get("formatted_lyrics") or blob.get("lrc")
                if raw:
                    lyrics = str(raw)
                raw_timeline = blob.get("lyrics_timeline") or blob.get("lrc_timeline")
                if isinstance(raw_timeline, list):
                    embedded_timeline = raw_timeline
                if lyrics:
                    break
        if not lyrics and prov.job_id:
            job = db.query(GenerationJob).filter(GenerationJob.id == prov.job_id).first()
            if job and isinstance(job.config, dict):
                lyrics = job.config.get("lyrics")
                if lyrics:
                    lyrics = str(lyrics)
    return build_lyrics_timeline(
        lyrics,
        duration=float(work.duration) if work.duration else None,
        embedded_timeline=embedded_timeline,
    )


def _parse_json_form(raw: str | None, model_cls):
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return model_cls.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON for {model_cls.__name__}") from exc


def _build_playlist_job_config(
    *,
    journey_config: dict,
    music_params: dict,
    text_intent: str | None,
    preset_id: str | None,
    generation_mode: str,
    seed_storage_key: str | None,
    seed_work_id: str | None,
    seed_filename: str,
    moods: list | None = None,
    genres: list | None = None,
    creative_spec: dict | None = None,
    db: Session | None = None,
) -> dict:
    if preset_id and not text_intent:
        preset = get_preset(preset_id, db=db)
        if preset:
            text_intent = preset.get("example_intent")

    has_seed = bool(seed_storage_key or seed_work_id)
    mode = generation_mode or "prompt_journey"
    if has_seed and mode == "prompt_journey":
        mode = "audio_anchor"
        journey_config = {**journey_config, "mode": "audio_anchor"}
    elif has_seed:
        journey_config = {**journey_config, "mode": mode}
    else:
        journey_config = {**journey_config, "mode": "prompt_journey"}

    if mode in ("markov", "audio_anchor") and not has_seed:
        raise HTTPException(status_code=400, detail="audio_anchor mode requires seed audio")

    if not has_seed and not text_intent and not preset_id:
        raise HTTPException(
            status_code=400,
            detail="Provide text_intent, preset_id, or seed audio",
        )

    journey_config = {**journey_config, "title": resolve_playlist_title(journey_config)}

    job_config = {
        "journey": journey_config,
        "music_params": music_params,
        "text_intent": text_intent,
        "preset_id": preset_id,
        "generation_mode": mode,
        "seed_work_id": seed_work_id,
        "seed_filename": seed_filename,
        "moods": moods or [],
        "genres": genres or [],
    }
    if creative_spec:
        job_config["creative_spec"] = creative_spec
    if seed_storage_key:
        job_config["seed_storage_key"] = seed_storage_key
    return job_config


@router.get("", response_model=list[WorkResponse])
def list_works(
    sort: str = "newest",
    mood: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = scope_by_tenant(db.query(Work).filter(Work.owner_id == user.id), Work, user, db)
    if mood:
        query = query.filter(Work.moods.contains([mood]))
    if sort == "title":
        query = query.order_by(Work.title.asc())
    elif sort == "oldest":
        query = query.order_by(Work.created_at.asc())
    else:
        query = query.order_by(Work.created_at.desc())
    works = query.limit(min(max(limit, 1), 200)).all()
    return works_to_responses(db, works, user)


@router.get("/search")
def search_works(
    q: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not q.strip():
        return []
    pattern = f"%{q.strip()}%"
    works = (
        scope_by_tenant(
            db.query(Work).filter(Work.owner_id == user.id, Work.title.ilike(pattern)),
            Work,
            user,
            db,
        )
        .order_by(Work.created_at.desc())
        .limit(30)
        .all()
    )
    return works_to_responses(db, works, user)


@router.get("/{work_id}/passport")
def get_work_passport(
    work_id: str,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.distribution.passport import reveal_passport

    return reveal_passport(db, work_id=work_id, viewer=user)


@router.get("/{work_id}", response_model=WorkResponse)
def get_work(
    work_id: str,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.distribution.passport import live_store_count

    work = get_viewable_work_optional(db, work_id, user)
    lyrics, timeline = _extract_lyrics(db, work)
    owner = getattr(work, "owner", None)
    owner_username = getattr(owner, "username", None) if owner is not None else None
    artist_name = (getattr(owner, "display_name", None) or owner_username) if owner is not None else None
    post = (
        db.query(Post)
        .filter(Post.work_id == work.id)
        .order_by(Post.created_at.desc())
        .first()
        if user is not None and getattr(user, "id", None) == work.owner_id
        else None
    )
    successor_id = None
    if user is not None and getattr(user, "id", None) == work.owner_id:
        from app.services.royalty.hub import unpublished_workbench_successor

        child = unpublished_workbench_successor(db, work)
        successor_id = str(child.id) if child else None
    return work_to_response(
        work,
        lyrics=lyrics,
        lyrics_timeline=timeline,
        user=user,
        live_stores=live_store_count(db, work.id),
        artist_name=artist_name,
        owner_username=owner_username,
        community_post_id=str(post.id) if post else None,
        community_caption=post.caption if post else None,
        superseded_by_work_id=successor_id,
    )


@router.get("/{work_id}/quality")
def get_work_quality(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.schemas import ProvenanceRecord
    from app.services.work_quality import compute_work_quality

    work = get_viewable_work(db, work_id, user)
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    return compute_work_quality(work, prov)


@router.patch("/{work_id}", response_model=WorkUpdateResponse)
def update_work(
    work_id: str,
    payload: WorkUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    if_match: str | None = Header(None, alias="If-Match"),
):
    work = get_viewable_work(db, work_id, user)
    if work.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can update this work")

    expected = payload.expected_version
    if expected is None and if_match:
        try:
            expected = int(if_match.strip('"'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid If-Match header") from None

    current_version = int(getattr(work, "version", 1) or 1)
    if expected is not None and expected != current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORK_VERSION_CONFLICT",
                "message": "作品已在其他地方更新，请刷新后重试",
                "current_version": current_version,
            },
        )

    old_title = work.title
    post_caption_synced = False
    if payload.title is not None:
        work.title = payload.title.strip()
        if work.title != old_title:
            post_caption_synced = sync_post_caption_for_work_rename(
                db,
                work.id,
                old_title=old_title,
                new_title=work.title,
                force=payload.sync_community_caption,
            )
            if post_caption_synced:
                from app.services.cache import cache_clear

                cache_clear("feed:")
                cache_clear("rising_creators:")

    work.version = current_version + 1
    db.commit()
    db.refresh(work)
    base = work_to_response(work, user=user)
    return WorkUpdateResponse(**base.model_dump(), post_caption_synced=post_caption_synced)


def _auth_user_optional(
    credentials: HTTPAuthorizationCredentials | None,
    access_token: str | None,
    db: Session,
) -> User | None:
    if credentials:
        return authenticate_token(credentials.credentials, db)
    if access_token:
        return authenticate_token(access_token, db)
    return None


def _stream_storage_object(key: str, range_header: str | None = None):
    storage = get_storage_service()
    kwargs = {"Bucket": storage.bucket, "Key": key}
    if range_header:
        kwargs["Range"] = range_header
    resp = storage.client.get_object(**kwargs)
    body = resp["Body"]

    def _iter():
        try:
            while True:
                chunk = body.read(1024 * 256)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    headers = {
        "Cache-Control": "private, no-store, max-age=0",
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        # Media bytes must reach the client uncompressed. GZipMiddleware skips any
        # response that already declares Content-Encoding; browsers auto-inflate
        # gzip but WeChat InnerAudioContext does not, so compressed audio fails to
        # decode ("errCode:26 data error" / "Unable to decode audio data").
        "Content-Encoding": "identity",
    }
    if resp.get("ContentRange"):
        headers["Content-Range"] = resp["ContentRange"]
    if resp.get("ContentLength") is not None:
        headers["Content-Length"] = str(resp["ContentLength"])
    content_type = resp.get("ContentType") or "audio/mpeg"
    status = 206 if range_header and resp.get("ContentRange") else 200
    return _iter(), headers, content_type, status


@router.get("/{work_id}/stream")
def stream_work_audio(
    work_id: str,
    request: Request,
    ticket: str | None = Query(None),
    access_token: str | None = Query(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    """Proxied audio stream — requires short-lived ticket or authenticated viewer."""
    user = _auth_user_optional(credentials, access_token, db)
    work = get_work_or_404(db, work_id)
    validate_playback_access(db, work, ticket=ticket, user=user)

    range_header = request.headers.get("range") or request.headers.get("Range")
    key = work_audio_storage_key(work)
    if key:
        iterator, headers, content_type, status = _stream_storage_object(key, range_header)
        return StreamingResponse(iterator, status_code=status, media_type=content_type, headers=headers)

    if work.audio_url:
        import httpx

        headers_out = {
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            # Keep the proxied audio uncompressed (see _stream_storage_object).
            "Content-Encoding": "identity",
        }
        req_headers = {}
        if range_header:
            req_headers["Range"] = range_header
        with httpx.stream("GET", work.audio_url, headers=req_headers, timeout=120.0) as remote:
            if remote.status_code >= 400:
                raise HTTPException(status_code=502, detail="Upstream audio unavailable")
            for k, v in remote.headers.items():
                if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges"):
                    headers_out[k] = v

            def _proxy():
                for chunk in remote.iter_bytes(1024 * 256):
                    yield chunk

            return StreamingResponse(_proxy(), status_code=remote.status_code, headers=headers_out)

    raise HTTPException(status_code=404, detail="Audio not available")


@router.get("/{work_id}/hls/playlist.m3u8")
def get_hls_playlist(
    work_id: str,
    ticket: str | None = Query(None),
    access_token: str | None = Query(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    """Serve HLS playlist with same-origin proxied segment URLs (no long-lived S3 links)."""
    user = _auth_user_optional(credentials, access_token, db)
    work = get_work_or_404(db, work_id)
    validate_playback_access(db, work, ticket=ticket, user=user)
    prefix = hls_prefix_from_work(
        hls_storage_prefix=work.hls_storage_prefix,
        hls_url=work.hls_url,
    )
    if not prefix:
        raise HTTPException(status_code=404, detail="HLS not available")
    play_ticket = ticket
    if not play_ticket:
        if user is None or not can_view_work(work, user):
            raise HTTPException(status_code=403, detail="Playback ticket required")
        from app.services.media_playback import issue_playback_ticket

        play_ticket = issue_playback_ticket(str(work.id), user.id)
    try:
        key = f"{prefix.rstrip('/')}/index.m3u8"
        raw = get_storage_service().get_object_bytes(key).decode("utf-8")
        playlist = rewrite_hls_playlist_for_gateway(raw, work_id=str(work.id), ticket=play_ticket)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="HLS playlist not found") from exc
    return Response(
        content=playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@router.get("/{work_id}/hls/segments/{segment_name}")
def get_hls_segment(
    work_id: str,
    segment_name: str,
    ticket: str | None = Query(None),
    access_token: str | None = Query(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    if not is_safe_segment_name(segment_name):
        raise HTTPException(status_code=400, detail="Invalid segment")
    user = _auth_user_optional(credentials, access_token, db)
    work = get_work_or_404(db, work_id)
    validate_playback_access(db, work, ticket=ticket, user=user)
    prefix = hls_prefix_from_work(
        hls_storage_prefix=work.hls_storage_prefix,
        hls_url=work.hls_url,
    )
    if not prefix:
        raise HTTPException(status_code=404, detail="HLS not available")
    key = f"{prefix.rstrip('/')}/{segment_name}"
    iterator, headers, content_type, status = _stream_storage_object(key)
    headers["Content-Type"] = "video/mp2t"
    return StreamingResponse(iterator, status_code=status, media_type="video/mp2t", headers=headers)


def _preflight_or_400(payload) -> None:
    from app.services.generation_preflight import GenerationPreflightError, preflight_music_request

    spec = getattr(payload, "creative_spec", None)
    override = ""
    if spec is not None:
        override = getattr(spec, "custom_prompt_override", None)
        if override is None and isinstance(spec, dict):
            override = spec.get("custom_prompt_override") or ""
    try:
        preflight_music_request(
            lyrics=getattr(payload, "lyrics", None),
            instrumental=bool(getattr(payload, "instrumental", True)),
            lyrics_optimizer=getattr(payload, "lyrics_optimizer", None),
            prompt=str(override or ""),
            text_intent=getattr(payload, "text_intent", None),
            mode=getattr(payload, "mode", None),
        )
    except GenerationPreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_reference_work(db: Session, reference: dict | None, user: User) -> None:
    if not reference or not reference.get("work_id"):
        return
    from app.services.reference_track import assert_reference_rights

    assert_reference_rights(db, reference["work_id"], user)


@router.post("/generate/single", response_model=JobResponse)
async def generate_single(
    payload: SingleGenerateRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        return job_response_with_credits(db, existing, user.id)

    if payload.seed_work_id:
        assert_seed_rights(db, payload.seed_work_id, user)
    _validate_reference_work(db, payload.reference, user)

    preview_count = payload.preview_pick_count or 0
    if preview_count > 1:
        raise HTTPException(
            status_code=400,
            detail="每次生成仅支持 1 个预览，多版本请使用变体实验室并按额度计费",
        )
    _preflight_or_400(payload)

    charged = charge_generation_credits(db, user.id, cost=GENERATION_COST, defer_commit=True)

    job_config = with_credits_charged(payload.model_dump(), charged)

    job = create_generation_job(
        db,
        user,
        job_type="single",
        config=job_config,
        idempotency_key=idempotency_key,
    )
    dispatch_single(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return job_response_with_credits(db, job, user.id)


@router.post("/generate/playlist", response_model=JobResponse)
async def generate_playlist(
    file: UploadFile | None = File(None),
    seed_work_id: str | None = Form(None),
    text_intent: str | None = Form(None),
    preset_id: str | None = Form(None),
    generation_mode: str = Form("prompt_journey"),
    steps: int = Form(6),
    target_curve: str = Form("calm_to_energy"),
    instrumental: bool = Form(True),
    title: str | None = Form(None),
    waypoints_json: str | None = Form(None),
    journey_json: str | None = Form(None),
    music_params_json: str | None = Form(None),
    bpm_min: int | None = Form(None),
    bpm_max: int | None = Form(None),
    key: str | None = Form(None),
    duration_preference: str | None = Form(None),
    creative_spec_json: str | None = Form(None),
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        return job_response_with_credits(db, existing, user.id)

    journey_override = _parse_json_form(journey_json, JourneyConfig)
    music_override = _parse_json_form(music_params_json, MusicParams)

    journey_config: dict
    music_params: dict
    resolved_text_intent = text_intent

    if preset_id and not journey_override:
        try:
            applied = apply_preset(
                preset_id,
                steps=steps,
                overrides={
                    "text_intent": text_intent,
                    "target_curve": target_curve,
                    "instrumental": instrumental,
                    "title": title,
                },
                db=db,
                user_id=user.id,
            )
            journey_config = applied["journey"]
            music_params = applied["music_params"] if not music_override else music_override.model_dump()
            resolved_text_intent = applied.get("text_intent") or text_intent
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif journey_override:
        journey_config = journey_override.model_dump()
        music_params = music_override.model_dump() if music_override else {
            "bpm_range": [bpm_min or 80, bpm_max or 120],
            "key": key or "auto",
            "duration_preference": duration_preference or "medium",
        }
    else:
        waypoints = []
        if waypoints_json:
            try:
                raw_wps = json.loads(waypoints_json)
                if not isinstance(raw_wps, list):
                    raise ValueError("waypoints must be a list")
                waypoints = [Waypoint.model_validate(w).model_dump() for w in raw_wps]
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Invalid waypoints_json") from exc

        if steps < 1 or steps > 12:
            raise HTTPException(status_code=400, detail="steps must be between 1 and 12")

        journey_config = {
            "mode": "prompt_journey",
            "steps": steps,
            "target_curve": target_curve,
            "instrumental": instrumental,
            "title": title,
            "waypoints": waypoints,
        }
        music_params = music_override.model_dump() if music_override else {
            "bpm_range": [bpm_min if bpm_min is not None else 80, bpm_max if bpm_max is not None else 120],
            "key": key or "auto",
            "duration_preference": duration_preference or "medium",
        }

    seed_filename = "seed.wav"
    seed_storage_key = None
    resolved_seed_work_id = seed_work_id

    if file:
        seed_bytes = await file.read()
        upload_err = validate_audio_upload(seed_bytes, file.content_type)
        if upload_err:
            raise HTTPException(status_code=400, detail=upload_err)
        seed_filename = file.filename or seed_filename
        storage_key = f"seeds/{user.id}/{uuid.uuid4()}_{seed_filename}"
        seed_storage_key, _ = get_storage_service().upload_bytes(seed_bytes, storage_key)

    if resolved_seed_work_id:
        from app.services.work_access import assert_seed_rights

        assert_seed_rights(db, resolved_seed_work_id, user)

    creative_spec = _parse_json_form(creative_spec_json, MusicCreativeSpecSchema) if creative_spec_json else None

    _validate_reference_work(db, journey_config.get("reference"), user)

    charged = charge_generation_credits(db, user.id, cost=PLAYLIST_COST, defer_commit=True)

    job_config = with_credits_charged(
        _build_playlist_job_config(
        journey_config=journey_config,
        music_params=music_params,
        text_intent=resolved_text_intent,
        preset_id=preset_id,
        generation_mode=generation_mode,
        seed_storage_key=seed_storage_key,
        seed_work_id=resolved_seed_work_id,
        seed_filename=seed_filename,
        creative_spec=creative_spec.model_dump() if creative_spec else None,
        db=db,
        ),
        charged,
    )

    job = create_generation_job(
        db,
        user,
        job_type="playlist",
        total_steps=journey_config.get("steps", 6),
        config=job_config,
        idempotency_key=idempotency_key,
    )

    dispatch_playlist(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return job_response_with_credits(db, job, user.id)


@router.post("/generate/playlist/body", response_model=JobResponse)
async def generate_playlist_body(
    payload: PlaylistGenerateRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        return job_response_with_credits(db, existing, user.id)

    journey_config = payload.journey.model_dump()
    music_params = payload.music_params.model_dump()

    if payload.preset_id:
        try:
            applied = apply_preset(
                payload.preset_id,
                steps=payload.journey.steps,
                overrides={
                    "text_intent": payload.text_intent,
                    "target_curve": payload.journey.target_curve,
                    "instrumental": payload.journey.instrumental,
                    "title": payload.journey.title,
                },
                db=db,
                user_id=user.id,
            )
            journey_config = applied["journey"]
            music_params = applied["music_params"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.seed_work_id:
        assert_seed_rights(db, payload.seed_work_id, user)
    _validate_reference_work(db, journey_config.get("reference"), user)

    charged = charge_generation_credits(db, user.id, cost=PLAYLIST_COST, defer_commit=True)

    job_config = with_credits_charged(
        _build_playlist_job_config(
        journey_config=journey_config,
        music_params=music_params,
        text_intent=payload.text_intent,
        preset_id=payload.preset_id,
        generation_mode=payload.generation_mode,
        seed_storage_key=None,
        seed_work_id=payload.seed_work_id,
        seed_filename="seed.mp3",
        moods=payload.moods,
        genres=payload.genres,
        creative_spec=payload.creative_spec.model_dump() if payload.creative_spec else None,
        db=db,
        ),
        charged,
    )

    job = create_generation_job(
        db,
        user,
        job_type="playlist",
        total_steps=journey_config.get("steps", 6),
        config=job_config,
        idempotency_key=idempotency_key,
    )

    dispatch_playlist(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return job_response_with_credits(db, job, user.id)


class VariationsRequest(BaseModel):
    text_intent: str | None = None
    seed_work_id: str | None = None
    title: str = "变体"
    count: int = Field(default=2, ge=1, le=5)
    instrumental: bool = True
    moods: list[str] = []
    genres: list[str] = []
    bpm: int | None = None
    key: str | None = None
    lyrics: str | None = Field(default=None, max_length=8000)
    style_tags: str | None = Field(default=None, max_length=2000)
    creative_spec: dict | None = None
    reference: dict | None = None
    remelt: bool = False
    mode: str | None = None
    freedom: str | None = None
    quality: str | None = None
    quick: bool = False
    vocal: dict | None = None


class BatchDeleteRequest(BaseModel):
    work_ids: list[str] = Field(min_length=1, max_length=50)


@router.get("/{work_id}/remix-tree")
def get_remix_tree(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.derivative import build_remix_tree

    get_viewable_work(db, work_id, user)
    tree = build_remix_tree(db, uuid.UUID(work_id))
    if not tree:
        raise HTTPException(status_code=404, detail="Work not found")
    return tree


@router.get("/{work_id}/similar")
def get_similar_works(
    work_id: str,
    limit: int = 6,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.recommendation import list_similar_works
    from app.services.work_access import get_viewable_work_optional

    work = get_viewable_work_optional(db, work_id, user)
    return {"works": list_similar_works(db, work, limit=min(max(limit, 1), 12))}


@router.get("/{work_id}/derivatives")
def get_derivatives(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.derivative import list_derivatives

    get_viewable_work(db, work_id, user)
    return list_derivatives(db, uuid.UUID(work_id))


@router.post("/generate/variations", response_model=JobResponse)
async def generate_variations(
    payload: VariationsRequest,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    existing = lookup_idempotent_job(db, user, idempotency_key)
    if existing:
        return job_response_with_credits(db, existing, user.id)

    count = payload.count
    if payload.seed_work_id:
        assert_seed_rights(db, payload.seed_work_id, user)
    _validate_reference_work(db, payload.reference, user)
    _preflight_or_400(payload)

    charged = charge_generation_credits(db, user.id, cost=variation_credit_cost(count), defer_commit=True)

    job = create_generation_job(
        db,
        user,
        job_type="variations",
        total_steps=count,
        config=with_credits_charged(
            {
                **payload.model_dump(),
                "variation_count": count,
                "seeds": [hash(f"{user.id}-{i}") % 1_000_000 for i in range(count)],
            },
            charged,
        ),
        idempotency_key=idempotency_key,
    )
    dispatch_variations(db, user.id, str(job.id), job.config)
    db.refresh(job)
    return job_response_with_credits(db, job, user.id)


@router.get("/embed/{work_id}", response_model=WorkResponse)
def embed_work(
    work_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    """Embed player data for public works, or private works owned by the signed-in user."""
    user = authenticate_token(credentials.credentials, db) if credentials else None
    work = get_viewable_work_optional(db, work_id, user)
    return work_to_response(work, user=user)


@router.get("/embed/{work_id}/branding")
def embed_work_branding(
    work_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    user = authenticate_token(credentials.credentials, db) if credentials else None
    work = get_viewable_work_optional(db, work_id, user)
    owner = db.query(User).filter(User.id == work.owner_id).first()
    from app.services.tenant import embed_branding_for_tenant

    tid = owner.tenant_id if owner and owner.tenant_id else "default"
    return embed_branding_for_tenant(db, tid)


class EmbedCompleteBody(BaseModel):
    listen_ratio: float = Field(ge=0, le=1)
    visitor: str | None = None


@router.post("/embed/{work_id}/complete")
def embed_complete(
    work_id: str,
    payload: EmbedCompleteBody,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.embed_engagement import record_embed_complete

    host = request.client.host if request.client else None
    return record_embed_complete(
        db,
        work_id=work_id,
        listen_ratio=payload.listen_ratio,
        user=user,
        visitor=payload.visitor,
        host=host,
    )


@router.post("/batch-delete")
def batch_delete_works(
    payload: BatchDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = 0
    for wid in payload.work_ids:
        work = db.query(Work).filter(Work.id == parse_uuid(wid, field="work_id"), Work.owner_id == user.id).first()
        if work:
            detach_work_from_sessions(db, user.id, work.id)
            db.delete(work)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.post("/{work_id}/reprocess")
def reprocess_work(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-enqueue post-processing for a degraded work."""
    work = db.query(Work).filter(Work.id == uuid.UUID(work_id), Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    pps = work.post_process_status or {}
    if pps.get("state") != "degraded":
        raise HTTPException(status_code=400, detail="Work is not in degraded state")
    from app.workers.tasks import post_process_work_task

    post_process_work_task.apply_async(
        args=[str(work.id), str(user.id)],
        queue="post_process",
    )
    return {"reprocessing": True}


@router.get("/{work_id}/timeline")
def work_timeline_endpoint(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.distribution.timeline import work_timeline

    return work_timeline(db, work_id, str(user.id))
