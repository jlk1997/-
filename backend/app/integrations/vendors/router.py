"""Capability router over the vendor key pool. UI never sees vendor brands."""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.minimax.client import LyricsGenerationResult, MusicGenerationResult, minimax_client
from app.integrations.vendors import adapters
from app.integrations.vendors.errors import FAIL, SWITCH, MusicProviderError, cooldown_for, provider_failure_policy
from app.integrations.vendors.pool import mark_error, mark_ok, pick_key, release_key
from app.integrations.vendors.usage import record_provider_attempt

logger = logging.getLogger(__name__)

MUSIC_DISPATCH = {
    "tokenhub": adapters.generate_music_tokenhub,
    "minimax": adapters.generate_music_minimax,
    "mureka": adapters.generate_music_mureka,
    "lyria": adapters.generate_music_lyria,
    "elevenlabs": adapters.generate_music_elevenlabs,
    "stability": adapters.generate_music_stability,
}


def _music_dispatch() -> dict:
    mapping = dict(MUSIC_DISPATCH)
    if getattr(settings, "fun_music_enabled", False):
        mapping["fun_music"] = adapters.generate_music_fun_music
    return mapping


_MINIMAX_MUSIC_FIELDS = {
    "prompt",
    "lyrics",
    "is_instrumental",
    "lyrics_optimizer",
    "seed",
    "audio_format",
    "sample_rate",
    "bitrate",
    "db",
    "user_id",
    "mock_audio_bytes",
}


def _minimax_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if key in _MINIMAX_MUSIC_FIELDS}


async def _direct_music(**kwargs: Any):
    if settings.tokenhub_api_key:
        from app.integrations.tokenhub.music import TokenHubMusicClient

        return await TokenHubMusicClient().generate_music(**kwargs)
    return await minimax_client.generate_music(**_minimax_kwargs(kwargs))


async def generate_music(
    *,
    db: Session | None,
    remelt: bool = False,
    skip_vendors: list[str] | None = None,
    avoid_vendor: str | None = None,
    capability: str = "music",
    **kwargs: Any,
) -> MusicGenerationResult:
    if settings.use_mock_ai:
        return await minimax_client.generate_music(db=db, **_minimax_kwargs(kwargs))
    if db is None:
        return await _direct_music(db=db, **kwargs)

    last_error: Exception | None = None
    skipped_vendors = list(skip_vendors or [])
    skipped_ids: list[str] = []
    failed_by_vendor: dict[str, int] = {}
    dispatch = _music_dispatch()
    user_id = kwargs.get("user_id")
    for _ in range(6):
        row = pick_key(
            db,
            capability,
            skip_vendors=skipped_vendors,
            skip_ids=skipped_ids,
            remelt=remelt,
            avoid_vendor=avoid_vendor,
        )
        if row is None:
            break
        fn = dispatch.get(row.vendor)
        if fn is None:
            release_key(db, row)
            skipped_vendors.append(row.vendor)
            continue
        started = time.monotonic()
        try:
            result = await fn(row, **kwargs)
            mark_ok(db, row)
            meta = dict(result.metadata or {})
            meta.update(
                {
                    "vendor": row.vendor,
                    "vendor_id": str(row.id),
                    "vendor_key_prefix": row.key_prefix,
                    "fallback": bool(skipped_vendors),
                }
            )
            result.metadata = meta
            record_provider_attempt(
                db,
                user_id=user_id if isinstance(user_id, str) else None,
                provider=row.vendor,
                model=result.model or row.model or "",
                endpoint="/music_generation",
                tokens=int(meta.get("tokens") or 0),
                metadata={
                    "mode": meta.get("mode"),
                    "elapsed_ms": meta.get("elapsed_ms") or int((time.monotonic() - started) * 1000),
                    "trace_id": meta.get("trace_id") or result.task_id,
                    "request_id": meta.get("request_id"),
                    "music_duration": (meta.get("extra_info") or {}).get("music_duration")
                    if isinstance(meta.get("extra_info"), dict)
                    else None,
                    "error_kind": None,
                    "fallback": bool(skipped_vendors),
                },
            )
            return result
        except Exception as exc:
            last_error = exc
            policy = provider_failure_policy(exc, attempts_on_vendor=failed_by_vendor.get(row.vendor, 0) + 1)
            failed_by_vendor[row.vendor] = failed_by_vendor.get(row.vendor, 0) + 1
            logger.warning("vendor %s music failed kind=%s policy=%s: %s", row.vendor, getattr(exc, "kind", ""), policy, exc)
            if isinstance(exc, MusicProviderError) and exc.kind == "auth":
                logger.error("provider_auth_alert vendor=%s", row.vendor)
            mark_error(db, row, str(exc)[:200], cooldown_seconds=cooldown_for(exc))
            record_provider_attempt(
                db,
                user_id=user_id if isinstance(user_id, str) else None,
                provider=row.vendor,
                model=row.model or "",
                endpoint="/music_generation",
                tokens=0,
                metadata={
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "trace_id": getattr(exc, "trace_id", None),
                    "error_kind": getattr(exc, "kind", "server"),
                    "fallback": False,
                },
            )
            skipped_ids.append(str(row.id))
            if policy == FAIL:
                raise
            if policy == SWITCH or failed_by_vendor[row.vendor] >= 2:
                skipped_vendors.append(row.vendor)
    if last_error:
        raise last_error
    return await _direct_music(db=db, **kwargs)


async def generate_lyrics(
    *,
    db: Session | None,
    theme: str,
    moods: list[str] | None = None,
    language: str = "zh",
    user_id: str | None = None,
) -> LyricsGenerationResult:
    if settings.use_mock_ai or db is None:
        return await minimax_client.generate_lyrics(theme=theme, moods=moods, language=language, db=db, user_id=user_id)
    skipped: list[str] = []
    for _ in range(3):
        row = pick_key(db, "lyrics", skip_ids=skipped)
        if row is None:
            break
        try:
            if row.vendor == "qwen":
                result = await adapters.generate_lyrics_qwen(row, theme=theme, moods=moods, language=language)
            elif row.vendor == "minimax":
                result = await adapters.generate_lyrics_minimax(
                    row, theme=theme, moods=moods, language=language, db=db, user_id=user_id
                )
            else:
                release_key(db, row)
                skipped.append(str(row.id))
                continue
            mark_ok(db, row)
            return result
        except Exception as exc:
            logger.warning("vendor %s lyrics failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    return await minimax_client.generate_lyrics(theme=theme, moods=moods, language=language, db=db, user_id=user_id)


async def chat(
    *,
    db: Session | None,
    messages: list[dict],
    user_id: str | None = None,
    **kwargs: Any,
) -> str:
    if settings.use_mock_ai or db is None:
        return await minimax_client.chat_completion(messages=messages, db=db, user_id=user_id, **kwargs)
    skipped: list[str] = []
    for _ in range(3):
        row = pick_key(db, "chat", skip_ids=skipped)
        if row is None:
            break
        try:
            if row.vendor == "qwen":
                text = await adapters.qwen_chat(row, messages, **kwargs)
            elif row.vendor == "minimax":
                text = await adapters.chat_minimax(row, messages, db=db, user_id=user_id, **kwargs)
            else:
                release_key(db, row)
                skipped.append(str(row.id))
                continue
            mark_ok(db, row)
            return text
        except Exception as exc:
            logger.warning("vendor %s chat failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    return await minimax_client.chat_completion(messages=messages, db=db, user_id=user_id, **kwargs)


def chunk_reply(text: str, step: int = 12):
    raw = text or ""
    for index in range(0, len(raw), step):
        yield raw[index : index + step]


async def chat_stream(
    *,
    db: Session | None,
    messages: list[dict],
    user_id: str | None = None,
    **kwargs: Any,
):
    if settings.use_mock_ai or db is None:
        async for chunk in minimax_client.chat_completion_stream(
            messages=messages, db=db, user_id=user_id
        ):
            yield chunk
        return
    skipped: list[str] = []
    for _ in range(3):
        row = pick_key(db, "chat", skip_ids=skipped)
        if row is None:
            break
        try:
            if row.vendor == "qwen":
                text = await adapters.qwen_chat(row, messages, **kwargs)
                mark_ok(db, row)
                for chunk in chunk_reply(text):
                    yield chunk
                return
            if row.vendor == "minimax":
                from app.integrations.minimax.client import MiniMaxClient
                from app.integrations.vendors.pool import key_plaintext

                client = MiniMaxClient(api_key=key_plaintext(row), base_url=row.base_url)
                async for chunk in client.chat_completion_stream(
                    messages=messages, db=db, user_id=user_id
                ):
                    yield chunk
                mark_ok(db, row)
                return
            release_key(db, row)
            skipped.append(str(row.id))
        except Exception as exc:
            logger.warning("vendor %s chat stream failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    async for chunk in minimax_client.chat_completion_stream(
        messages=messages, db=db, user_id=user_id
    ):
        yield chunk


async def polish_text_intent(
    *,
    db: Session | None,
    text_intent: str,
    user_id: str | None = None,
) -> str:
    raw = (text_intent or "").strip()
    if settings.use_mock_ai:
        if len(raw) < 24:
            return f"{raw}，层次渐进的氛围铺陈，适合深夜独处的呼吸感纯音乐"
        return raw
    system = (
        "你是音乐创作助手。用户给出一句简陋的音乐创作意图，请润色成更有画面感、"
        "更适合 AI 音乐生成的中文描述。保持一句或两句，不超过 120 字。"
        "只返回润色后的文本，不要解释、不要引号、不要标题。"
    )
    polished = await chat(
        db=db,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": raw}],
        user_id=user_id,
    )
    return polished.strip().strip('"').strip("'").strip("「").strip("」") or raw


async def plan_journey(
    *,
    db: Session | None,
    text_intent: str,
    steps: int = 6,
    user_id: str | None = None,
) -> dict:
    import json

    system = (
        "Plan an emotional music journey. Return ONLY valid JSON with keys: "
        "title (string), target_curve (one of calm_to_energy, sad_to_hope, chaos_to_order), "
        "steps (int), waypoints (list of {step, arousal, valence, description})."
    )
    raw = await chat(
        db=db,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": text_intent}],
        user_id=user_id,
    )
    try:
        plan = json.loads(raw)
        if isinstance(plan, dict):
            plan.setdefault("steps", steps)
            return plan
    except json.JSONDecodeError:
        pass
    return await minimax_client.plan_journey(text_intent, steps, db=db, user_id=user_id)


async def build_music_prompt(*, db: Session | None, user_id: str | None = None, **kwargs: Any) -> dict:
    if settings.use_mock_ai or db is None:
        return await minimax_client.build_music_prompt(db=db, user_id=user_id, **kwargs)
    from app.integrations.minimax.client import MiniMaxClient
    from app.integrations.vendors.pool import key_plaintext

    skipped: list[str] = []
    for _ in range(3):
        row = pick_key(db, "chat", skip_ids=skipped)
        if row is None:
            row = pick_key(
                db,
                "music",
                skip_ids=skipped,
                skip_vendors=["mureka", "lyria", "elevenlabs", "stability", "fun_music"],
            )
        if row is None:
            break
        if row.vendor != "minimax":
            release_key(db, row)
            skipped.append(str(row.id))
            continue
        try:
            client = MiniMaxClient(api_key=key_plaintext(row), base_url=row.base_url)
            result = await client.build_music_prompt(db=db, user_id=user_id, **kwargs)
            mark_ok(db, row)
            return result
        except Exception as exc:
            logger.warning("vendor %s prompt failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    return await minimax_client.build_music_prompt(db=db, user_id=user_id, **kwargs)


async def remix_prompt(
    *,
    db: Session | None,
    original_prompt: str,
    user_intent: str,
    user_id: str | None = None,
) -> dict:
    import json

    system = "Rewrite the music generation prompt based on user remix intent. Return JSON: {prompt, bpm, key}."
    raw = await chat(
        db=db,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps({"original_prompt": original_prompt, "remix_intent": user_intent}),
            },
        ],
        user_id=user_id,
    )
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"prompt": f"{original_prompt}, {user_intent}", "bpm": 100, "key": "auto"}


async def generate_cover(
    *,
    db: Session | None,
    reference_audio_url: str,
    prompt: str,
    lyrics: str | None = None,
    cover_mode: str | None = None,
    modified_lyrics: str | None = None,
    user_id: str | None = None,
) -> dict:
    from app.integrations.minimax.cover import MiniMaxCoverClient, cover_client
    from app.integrations.vendors.pool import key_plaintext

    if settings.use_mock_ai or db is None:
        return await cover_client.generate_cover(
            reference_audio_url=reference_audio_url,
            prompt=prompt,
            lyrics=lyrics,
            cover_mode=cover_mode,
            modified_lyrics=modified_lyrics,
            db=db,
            user_id=user_id,
        )
    skipped: list[str] = []
    last_error: Exception | None = None
    for _ in range(3):
        row = pick_key(db, "cover", skip_ids=skipped)
        if row is None:
            row = pick_key(
                db,
                "music",
                skip_ids=skipped,
                skip_vendors=["mureka", "lyria", "elevenlabs", "stability", "fun_music"],
            )
        if row is None:
            break
        if row.vendor != "minimax":
            release_key(db, row)
            skipped.append(str(row.id))
            continue
        try:
            client = MiniMaxCoverClient(api_key=key_plaintext(row))
            result = await client.generate_cover(
                reference_audio_url=reference_audio_url,
                prompt=prompt,
                lyrics=lyrics,
                cover_mode=cover_mode,
                modified_lyrics=modified_lyrics,
                db=db,
                user_id=user_id,
            )
            mark_ok(db, row)
            return result
        except Exception as exc:
            last_error = exc
            logger.warning("vendor %s cover failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    if last_error:
        logger.warning("cover pool exhausted, falling back: %s", last_error)
    return await cover_client.generate_cover(
        reference_audio_url=reference_audio_url,
        prompt=prompt,
        lyrics=lyrics,
        cover_mode=cover_mode,
        modified_lyrics=modified_lyrics,
        db=db,
        user_id=user_id,
    )


async def generate_image(
    *,
    db: Session | None,
    prompt: str,
    user_id: str | None = None,
    aspect_ratio: str = "1:1",
) -> dict:
    from app.integrations.minimax.image import image_client

    if settings.use_mock_ai or db is None:
        return await image_client.generate_cover_image(
            prompt=prompt, aspect_ratio=aspect_ratio, db=db, user_id=user_id
        )
    skipped: list[str] = []
    last_error: Exception | None = None
    for _ in range(3):
        row = pick_key(db, "image", skip_ids=skipped)
        if row is None:
            break
        try:
            if row.vendor == "qwen":
                result = await adapters.generate_image_qwen(row, prompt=prompt)
            elif row.vendor == "minimax":
                result = await adapters.generate_image_minimax(
                    row, prompt=prompt, aspect_ratio=aspect_ratio, db=db, user_id=user_id
                )
            else:
                release_key(db, row)
                skipped.append(str(row.id))
                continue
            mark_ok(db, row)
            return result
        except Exception as exc:
            last_error = exc
            logger.warning("vendor %s image failed: %s", row.vendor, exc)
            mark_error(db, row, str(exc)[:200])
            skipped.append(str(row.id))
    if last_error:
        logger.warning("image pool exhausted, falling back: %s", last_error)
    return await image_client.generate_cover_image(
        prompt=prompt, aspect_ratio=aspect_ratio, db=db, user_id=user_id
    )
