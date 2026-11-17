"""Map a generation request onto the three TokenHub modes and a freedom level.

Old clients still send `instrumental` and `lyrics_optimizer`. New clients send
`mode`, `freedom`, `quality`, and `quick`.
"""

from __future__ import annotations

from typing import Any

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.core.lyrics_structure import normalize_lyrics
from app.core.music_prompt_builder import MusicCreativeSpec

logger = logging.getLogger(__name__)

MODES = ("lyrics", "auto_lyrics", "instrumental")
FREEDOMS = ("literal", "balanced", "open")
QUALITIES = ("standard", "master")

_OPEN_VARIANTS = (
    "",
    "，换一种编配和乐器层次",
    "，更留白，人声更靠后",
)


def resolve_mode(config: dict) -> str:
    mode = str(config.get("mode") or "").strip()
    if mode in MODES:
        return mode
    lyrics = (config.get("lyrics") or "").strip()
    if config.get("instrumental", True) and not lyrics:
        return "instrumental"
    if config.get("lyrics_optimizer") and not lyrics:
        return "auto_lyrics"
    if lyrics:
        return "lyrics"
    return "instrumental"


def resolve_freedom(config: dict) -> str:
    freedom = str(config.get("freedom") or "").strip()
    return freedom if freedom in FREEDOMS else "balanced"


def audio_setting_for_quality(quality: str | None) -> dict[str, Any]:
    if quality == "master" and settings.tokenhub_wav_enabled:
        return {"sample_rate": 44100, "bitrate": 256000, "format": "wav"}
    if quality == "master":
        return {"sample_rate": 44100, "bitrate": 320000, "format": "mp3"}
    return {
        "sample_rate": settings.minimax_music_sample_rate,
        "bitrate": settings.minimax_music_bitrate,
        "format": settings.minimax_music_format,
    }


def apply_vocal(spec: MusicCreativeSpec, config: dict) -> MusicCreativeSpec:
    vocal = config.get("vocal") if isinstance(config.get("vocal"), dict) else {}
    patch: dict[str, str] = {}
    for key in ("vocal_gender", "vocal_style", "language"):
        value = str(vocal.get(key) or getattr(spec, key, "") or "").strip()
        if value:
            patch[key] = value
    if not patch:
        return spec
    return spec.model_copy(update=patch)


async def prepare_generation_inputs(
    config: dict,
    creative_spec: MusicCreativeSpec,
    *,
    db: Session | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Return lyrics, mode flags, and the spec the prompt builder should see."""
    mode = resolve_mode(config)
    freedom = resolve_freedom(config)
    quality = str(config.get("quality") or "standard")
    if quality not in QUALITIES:
        quality = "standard"
    quick = bool(config.get("quick"))
    spec = apply_vocal(creative_spec, config)
    lyrics = normalize_lyrics(config.get("lyrics") or "").strip()

    if freedom == "literal" and (spec.custom_prompt_override or "").strip():
        spec = spec.model_copy(update={"custom_prompt_override": spec.custom_prompt_override.strip()[:2000]})
    elif freedom == "open":
        raw = (spec.text_intent or config.get("text_intent") or "").strip()
        variant = _OPEN_VARIANTS[int(config.get("freedom_variant") or 0) % len(_OPEN_VARIANTS)]
        polished = raw
        if raw and db is not None and not settings.use_mock_ai:
            try:
                from app.integrations.vendors.router import polish_text_intent

                polished = (await polish_text_intent(db=db, text_intent=raw, user_id=user_id) or raw).strip()
            except Exception:
                logger.warning("prompt polish failed; using the original line")
                polished = raw
        if raw or variant:
            spec = spec.model_copy(update={"text_intent": f"{polished}{variant}".strip()[:500]})
    elif freedom == "balanced" and int(config.get("freedom_variant") or 0):
        hint = "，另一版编配，乐器层次不同"
        base = (spec.text_intent or config.get("text_intent") or "").strip()
        spec = spec.model_copy(update={"text_intent": f"{base}{hint}".strip()[:500]})

    is_instrumental = mode == "instrumental"
    if is_instrumental:
        lyrics = ""
        if not (spec.text_intent or spec.custom_prompt_override or config.get("text_intent")):
            spec = spec.model_copy(update={"text_intent": "温暖的原声配器，适合安静聆听"})
    lyrics_optimizer = False
    if mode == "auto_lyrics":
        if quick and not lyrics:
            lyrics_optimizer = True
            lyrics = ""
        elif not lyrics and db is not None:
            try:
                from app.integrations.vendors.router import generate_lyrics

                written = await generate_lyrics(
                    db=db,
                    theme=(spec.text_intent or config.get("text_intent") or "一首歌")[:500],
                    moods=list(spec.moods or []),
                    language=spec.language or "zh",
                    user_id=user_id,
                )
                lyrics = normalize_lyrics(written.lyrics or "")
                if written.style_tags and not spec.style_tags:
                    spec = spec.model_copy(update={"style_tags": written.style_tags})
            except Exception:
                logger.warning("lyrics step failed; generating with automatic lyrics")
                lyrics = ""
                lyrics_optimizer = True
        if not lyrics:
            lyrics_optimizer = True
        else:
            lyrics_optimizer = False

    return {
        "mode": mode,
        "freedom": freedom,
        "quality": quality,
        "quick": quick,
        "spec": spec,
        "lyrics": lyrics or None,
        "is_instrumental": is_instrumental,
        "lyrics_optimizer": lyrics_optimizer if mode == "auto_lyrics" else False,
        "audio_setting": audio_setting_for_quality(quality),
        "text_intent": spec.text_intent or config.get("text_intent") or "",
    }
