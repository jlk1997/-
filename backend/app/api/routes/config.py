from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_optional_user
from app.config import settings
from app.core.style_presets import list_presets
from app.core.sound_recipe_options import SOUND_RECIPE_OPTIONS
from app.database import get_db
from app.integrations.minimax.client import JOURNEY_CURVES
from app.models.schemas import FeatureFlag, User
from app.services.cache import cache_get, cache_set

router = APIRouter(prefix="/config", tags=["config"])
catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])

STUDIO_CURVES = list(JOURNEY_CURVES.keys())
STUDIO_KEYS = [
    "auto",
    "C major",
    "G major",
    "D major",
    "A minor",
    "E minor",
    "F major",
    "Bb major",
]
STUDIO_BPM_PRESETS = [
    {"label": "舒缓", "range": [60, 90]},
    {"label": "适中", "range": [80, 120]},
    {"label": "明快", "range": [110, 140]},
    {"label": "激烈", "range": [130, 170]},
]
STUDIO_DURATION_OPTIONS = [
    {"value": "short", "label": "短 · 约 1 分钟"},
    {"value": "medium", "label": "中 · 约 2 分钟"},
    {"value": "long", "label": "长 · 约 3 分钟"},
]


@router.get("/presets")
def list_style_presets(category: str | None = None, db: Session = Depends(get_db)):
    cache_key = f"presets:{category or 'all'}"
    hit = cache_get(cache_key)
    if hit is not None:
        return JSONResponse(content=hit, headers={"Cache-Control": "public, max-age=300"})
    data = list_presets(db, category)
    cache_set(cache_key, data, 300)
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=300"})


@router.get("/flags")
def public_flags(db: Session = Depends(get_db)):
    hit = cache_get("flags:public")
    if hit is not None:
        return JSONResponse(content=hit, headers={"Cache-Control": "public, max-age=60"})
    flags = db.query(FeatureFlag).all()
    data = {f.key: f.enabled for f in flags}
    cache_set("flags:public", data, 60)
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=60"})


def _partners_configured() -> bool:
    from app.services.distribution.adapters import CnLabelAdapter, DistroKidAdapter, RouteNoteAdapter, TuneCoreAdapter

    return any(cls().configured() for cls in (DistroKidAdapter, TuneCoreAdapter, RouteNoteAdapter, CnLabelAdapter))


def _kyc_configured() -> bool:
    from app.services.kyc import provider_configured

    return provider_configured()


@catalog_router.get("/tracks")
def catalog_tracks(station: str | None = None):
    from app.services.catalog_seed import list_official_tracks

    return {"tracks": list_official_tracks(station=station), "discovery_only": True}


@catalog_router.get("/audio/{slug}")
def catalog_audio(slug: str):
    from app.services.catalog_seed import official_track_by_slug, synth_loop_wav

    item = official_track_by_slug(slug)
    if not item:
        raise HTTPException(status_code=404, detail="Unknown catalog track")
    return Response(content=synth_loop_wav(hz=float(item["hz"])), media_type="audio/wav")


def _compose_p50() -> int:
    try:
        from app.services.queue_metrics import p50_compose_seconds

        return int(p50_compose_seconds())
    except Exception:
        return int(settings.default_compose_eta_seconds)


@router.get("/platform")
def platform_info(user: User | None = Depends(get_optional_user)):
    hit = cache_get("platform:info:v6")
    if hit is not None:
        return JSONResponse(content=hit, headers={"Cache-Control": "public, max-age=120"})
    from app.health import _check_essentia_models
    from app.services.seats.service import farm_can_navigate

    essentia = _check_essentia_models()
    data = {
        "version": settings.app_version,
        "pipeline_version": settings.pipeline_version,
        "mock_ai": settings.use_mock_ai,
        "mock_payment": settings.payment_mock_allowed,
        "partner_stub": bool(settings.debug or settings.partner_stub_enabled),
        "farm_navigate": farm_can_navigate(),
        "partners_configured": _partners_configured(),
        "essentia_ready": essentia.get("status") == "ok",
        "payout_mode": "manual_only",
        "kyc_provider_configured": _kyc_configured(),
        "frontend_base_url": settings.frontend_base_url.rstrip("/"),
        "connector_origins": settings.connector_trusted_origins(),
        "debug": bool(settings.debug),
        "c2pa_enabled": settings.c2pa_enabled,
        "studio": {
            "curves": STUDIO_CURVES,
            "keys": STUDIO_KEYS,
            "bpm_presets": STUDIO_BPM_PRESETS,
            "duration_options": STUDIO_DURATION_OPTIONS,
            "sound_recipe": SOUND_RECIPE_OPTIONS,
            "max_lyrics_length": 3500,
            "max_prompt_length": 2000,
            "max_steps": 12,
            "min_steps": 1,
            "default_bpm_range": [80, 120],
            "default_key": "auto",
            "default_duration": "medium",
            "lyrics_optimizer_default": settings.minimax_lyrics_optimizer_default,
            "cover_mode_default": settings.minimax_cover_mode_default,
            "song_modes": ["auto_lyrics", "lyrics", "instrumental"],
            "default_song_mode": "auto_lyrics",
            "freedom_levels": ["literal", "balanced", "open"],
            "default_freedom": "balanced",
            "structure_tags": [
                "Intro",
                "Verse",
                "Pre Chorus",
                "Chorus",
                "Interlude",
                "Bridge",
                "Outro",
                "Post Chorus",
                "Transition",
                "Break",
                "Hook",
                "Build Up",
                "Inst",
                "Solo",
            ],
            "structure_templates": [
                {"id": "short", "minutes": 1},
                {"id": "standard", "minutes": 3},
                {"id": "full", "minutes": 4},
                {"id": "instrumental", "minutes": 2},
            ],
            "compose_eta_p50_seconds": _compose_p50(),
            "qualities": ["standard", "master"],
            "wav_master_available": bool(settings.tokenhub_wav_enabled),
            "vocal_is_guidance": True,
        },
        "wechat_subscribe": {
            "job_complete": settings.wechat_tpl_job_complete,
            "low_credits": settings.wechat_tpl_low_credits,
        },
    }
    cache_set("platform:info:v6", data, 120)
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=120"})


@router.get("/embed")
def embed_branding(
    tenant_id: str | None = None,
    host: str | None = None,
    db: Session = Depends(get_db),
):
    from app.services.tenant import embed_branding_for_tenant, resolve_tenant_by_host

    tid = tenant_id or settings.default_tenant_id
    if host:
        resolved = resolve_tenant_by_host(db, host)
        if resolved:
            tid = resolved
    data = embed_branding_for_tenant(db, tid)
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=120"})
