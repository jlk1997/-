"""Official vendor adapters. No unofficial Suno/Udio wrappers."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from app.integrations.minimax.client import LyricsGenerationResult, MiniMaxClient, MusicGenerationResult
from app.integrations.vendors.http import fetch_audio_bytes, get_json, post_json
from app.models.schemas import VendorKey
from app.integrations.vendors.pool import key_plaintext

logger = logging.getLogger(__name__)


def first_audio_url(data: dict | None) -> str:
    payload = data or {}
    choices = payload.get("choices") or payload.get("songs") or payload.get("data") or []
    if isinstance(choices, dict):
        choices = [choices]
    candidates: list[object] = []
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        if isinstance(first, dict):
            candidates.extend([first.get("url"), first.get("audio_url")])
    candidates.extend([payload.get("url"), payload.get("audio_url")])
    for raw in candidates:
        url = str(raw or "")
        if url.startswith("http"):
            return url
    return ""


def first_image_url(data: dict | None) -> str:
    payload = data or {}
    direct = payload.get("image_url")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    images = payload.get("images") or payload.get("image_urls") or []
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict):
            url = str(first.get("url") or first.get("image_url") or "")
            if url.startswith("http"):
                return url
    for row in payload.get("results") or []:
        if isinstance(row, dict):
            url = str(row.get("url") or row.get("image_url") or "")
            if url.startswith("http"):
                return url
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else None
    output = payload.get("output") if isinstance(payload.get("output"), dict) else None
    for block in (nested, output):
        if not block:
            continue
        found = first_image_url({k: v for k, v in block.items() if k not in {"data", "output"}})
        if found:
            return found
        for choice in block.get("choices") or []:
            content = ((choice or {}).get("message") or {}).get("content")
            if isinstance(content, str) and content.startswith("http"):
                return content
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    url = str(part.get("image") or part.get("image_url") or part.get("url") or "")
                    if url.startswith("http"):
                        return url
        for row in block.get("results") or []:
            if isinstance(row, dict):
                url = str(row.get("url") or row.get("image_url") or "")
                if url.startswith("http"):
                    return url
    return ""


def _music(
    *,
    audio_bytes: bytes | None,
    audio_url: str = "",
    vendor: str,
    model: str,
    prompt: str,
    lyrics: str | None,
    extra: dict | None = None,
) -> MusicGenerationResult:
    return MusicGenerationResult(
        audio_url=audio_url,
        audio_bytes=audio_bytes,
        task_id="",
        prompt=prompt,
        lyrics=lyrics,
        seed=None,
        model=model,
        metadata={"vendor": vendor, **(extra or {})},
    )


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


async def generate_music_tokenhub(row: VendorKey, **kwargs) -> MusicGenerationResult:
    from app.integrations.tokenhub.music import TokenHubMusicClient

    client = TokenHubMusicClient(api_key=key_plaintext(row), base_url=row.base_url, model=row.model)
    try:
        result = await client.generate_music(**kwargs)
    except Exception as exc:
        from app.integrations.vendors.errors import coerce_music_error

        raise coerce_music_error(exc, provider="tokenhub") from exc
    result.metadata = {**(result.metadata or {}), "vendor": "tokenhub", "vendor_key_prefix": row.key_prefix}
    return result


async def generate_music_minimax(row: VendorKey, **kwargs) -> MusicGenerationResult:
    from app.integrations.vendors.errors import MusicProviderError, coerce_music_error

    client = MiniMaxClient(api_key=key_plaintext(row), base_url=row.base_url)
    clean = {key: value for key, value in kwargs.items() if key in _MINIMAX_MUSIC_FIELDS}
    try:
        result = await client.generate_music(**clean)
    except MusicProviderError:
        raise
    except Exception as exc:
        raise coerce_music_error(exc, provider="minimax") from exc
    result.metadata = {**(result.metadata or {}), "vendor": "minimax", "vendor_key_prefix": row.key_prefix}
    return result


async def generate_lyrics_minimax(row: VendorKey, **kwargs) -> LyricsGenerationResult:
    client = MiniMaxClient(api_key=key_plaintext(row), base_url=row.base_url)
    return await client.generate_lyrics(**kwargs)


async def chat_minimax(row: VendorKey, messages: list[dict], **kwargs) -> str:
    client = MiniMaxClient(api_key=key_plaintext(row), base_url=row.base_url)
    return await client.chat_completion(messages=messages, **kwargs)


async def generate_music_mureka(
    row: VendorKey,
    *,
    prompt: str,
    lyrics: str | None = None,
    is_instrumental: bool = True,
    **_: Any,
) -> MusicGenerationResult:
    secret = key_plaintext(row)
    base = (row.base_url or "https://api.mureka.ai").rstrip("/")
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    payload = {
        "lyrics": lyrics or ("[Inst]\n" if is_instrumental else ""),
        "model": row.model or "auto",
        "prompt": prompt[:1000],
    }
    created = await post_json(f"{base}/v1/song/generate", headers=headers, payload=payload, timeout=60)
    task_id = str(created.get("id") or created.get("task_id") or "")
    if not task_id:
        raise RuntimeError("mureka did not return a task id")
    audio_url = ""
    data: dict = {}
    for _ in range(40):
        await asyncio.sleep(3)
        try:
            data = await get_json(f"{base}/v1/song/query/{task_id}", headers=headers)
        except Exception:
            data = await get_json(f"{base}/v1/song/feed/{task_id}", headers=headers)
        audio_url = first_audio_url(data)
        status = str(data.get("status") or "").lower()
        if audio_url or status in {"succeeded", "success", "completed", "ready"}:
            break
        if status in {"failed", "error"}:
            raise RuntimeError(data.get("error") or "mureka generation failed")
    if not audio_url:
        raise RuntimeError("mureka timed out waiting for audio")
    audio_bytes = await fetch_audio_bytes(audio_url, headers={"Authorization": f"Bearer {secret}"})
    return _music(
        audio_bytes=audio_bytes,
        audio_url=audio_url,
        vendor="mureka",
        model=row.model or "mureka",
        prompt=prompt,
        lyrics=lyrics,
        extra={"task_id": task_id},
    )


async def generate_music_lyria(
    row: VendorKey,
    *,
    prompt: str,
    lyrics: str | None = None,
    is_instrumental: bool = True,
    **_: Any,
) -> MusicGenerationResult:
    secret = key_plaintext(row)
    model = row.model or "lyria-3-pro-preview"
    text = prompt if is_instrumental or not lyrics else f"{prompt}\n\nLyrics:\n{lyrics}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = await post_json(
        f"{url}?key={secret}",
        headers={"Content-Type": "application/json"},
        payload={"contents": [{"parts": [{"text": text}]}]},
        timeout=180,
    )
    audio_bytes = None
    audio_url = ""
    for cand in data.get("candidates") or []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            raw = inline.get("data")
            if raw:
                audio_bytes = base64.b64decode(raw)
                break
            audio_url = audio_url or str(part.get("fileData", {}).get("fileUri") or "")
        if audio_bytes:
            break
    if audio_url and not audio_bytes:
        audio_bytes = await fetch_audio_bytes(audio_url)
    if not audio_bytes:
        raise RuntimeError("lyria returned no audio")
    return _music(audio_bytes=audio_bytes, vendor="lyria", model=model, prompt=prompt, lyrics=lyrics)


async def generate_music_fun_music(
    row: VendorKey,
    *,
    prompt: str,
    lyrics: str | None = None,
    is_instrumental: bool = True,
    **_: Any,
) -> MusicGenerationResult:
    secret = key_plaintext(row)
    data = await post_json(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/music-generation/generation",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        payload={
            "model": row.model or "fun-music-v1",
            "input": {"prompt": prompt, "lyrics": lyrics or "", "instrumental": is_instrumental},
        },
        timeout=180,
    )
    output = data.get("output") or data
    audio_url = str(output.get("audio_url") or output.get("url") or "")
    if not audio_url:
        raise RuntimeError("fun-music returned no audio url")
    return _music(
        audio_bytes=await fetch_audio_bytes(audio_url),
        audio_url=audio_url,
        vendor="fun_music",
        model=row.model or "fun-music-v1",
        prompt=prompt,
        lyrics=lyrics,
    )


async def generate_music_elevenlabs(
    row: VendorKey,
    *,
    prompt: str,
    lyrics: str | None = None,
    **_: Any,
) -> MusicGenerationResult:
    secret = key_plaintext(row)
    async with __import__("httpx").AsyncClient(timeout=180) as client:
        resp = await client.post(
            "https://api.elevenlabs.io/v1/music",
            headers={"xi-api-key": secret, "Content-Type": "application/json"},
            json={"prompt": prompt if not lyrics else f"{prompt}\n{lyrics}", "model_id": row.model or "music_v1"},
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            data = resp.json()
            audio_url = str((data or {}).get("audio_url") or "")
            if not audio_url:
                raise RuntimeError("elevenlabs returned no audio")
            audio_bytes = await fetch_audio_bytes(audio_url)
        else:
            audio_bytes = resp.content
    return _music(audio_bytes=audio_bytes, vendor="elevenlabs", model=row.model or "music_v1", prompt=prompt, lyrics=lyrics)


async def generate_music_stability(
    row: VendorKey,
    *,
    prompt: str,
    **_: Any,
) -> MusicGenerationResult:
    secret = key_plaintext(row)
    async with __import__("httpx").AsyncClient(timeout=180) as client:
        resp = await client.post(
            "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio",
            headers={"Authorization": f"Bearer {secret}"},
            files={"none": (None, "")},
            data={"prompt": prompt, "output_format": "mp3"},
        )
        if resp.status_code >= 400:
            resp = await client.post(
                "https://api.stability.ai/v2beta/stable-audio/generate/text-to-audio",
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                json={"prompt": prompt},
            )
        resp.raise_for_status()
        audio_bytes = resp.content
    return _music(audio_bytes=audio_bytes, vendor="stability", model=row.model or "stable-audio", prompt=prompt, lyrics=None)


async def qwen_chat(row: VendorKey, messages: list[dict], response_format: str = "text", **_: Any) -> str:
    secret = key_plaintext(row)
    payload: dict[str, Any] = {"model": row.model or "qwen-plus", "messages": messages}
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    data = await post_json(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        payload=payload,
        timeout=90,
    )
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("qwen returned no choices")
    return str(((choices[0] or {}).get("message") or {}).get("content") or "")


async def generate_lyrics_qwen(row: VendorKey, *, theme: str, moods: list[str] | None = None, language: str = "zh", **_: Any) -> LyricsGenerationResult:
    text = await qwen_chat(
        row,
        [
            {"role": "system", "content": "Write structured song lyrics with [Verse], [Chorus], [Bridge]. Return lyrics only."},
            {"role": "user", "content": f"Theme: {theme}. Moods: {', '.join(moods or [])}. Language: {language}"},
        ],
    )
    return LyricsGenerationResult(lyrics=text, style_tags=", ".join((moods or [])[:3]) or None, song_title=theme[:40])


async def generate_image_minimax(row: VendorKey, *, prompt: str, aspect_ratio: str = "1:1", db=None, user_id: str | None = None, **_: Any) -> dict:
    from app.integrations.minimax.image import MiniMaxImageClient

    client = MiniMaxImageClient(api_key=key_plaintext(row), base_url=row.base_url)
    return await client.generate_cover_image(prompt=prompt, aspect_ratio=aspect_ratio, db=db, user_id=user_id)


async def generate_image_qwen(row: VendorKey, *, prompt: str, **_: Any) -> dict:
    secret = key_plaintext(row)
    model = row.model or "qwen-image-plus"
    data = await post_json(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        payload={
            "model": model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {"size": "1024*1024", "watermark": False},
        },
        timeout=120,
    )
    image_url = first_image_url(data)
    if not image_url:
        raise RuntimeError("qwen image returned no url")
    return {
        "image_url": image_url,
        "image_bytes": await fetch_audio_bytes(image_url),
        "prompt": prompt,
        "model": model,
    }
