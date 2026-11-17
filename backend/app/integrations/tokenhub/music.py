"""TokenHub MiniMax music generation.

Synchronous POST. No task polling. A returned URL expires in 12 hours, so the
caller must checkpoint it before downloading.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx

from app.config import settings
from app.core.lyrics_structure import LYRICS_BODY_LIMIT, PROMPT_LIMIT, lyrics_body_length, normalize_lyrics
from app.integrations.minimax.client import MusicGenerationResult
from app.integrations.minimax.http_utils import minimax_timeout
from app.integrations.vendors.errors import MusicProviderError, error_from_status

logger = logging.getLogger(__name__)

GENERATION_PATH = "/v1/wand/minimax-music/generation"
AcceptedCallback = Callable[[dict[str, Any]], None]


def build_music_payload(
    *,
    model: str,
    prompt: str | None,
    lyrics: str | None,
    is_instrumental: bool,
    lyrics_optimizer: bool,
    output_format: str,
    audio_setting: dict[str, Any] | None,
    aigc_watermark: bool,
) -> tuple[dict[str, Any], str]:
    """Validate a TokenHub body. Returns (payload, mode). Raises MusicProviderError(kind=params)."""
    prompt_text = (prompt or "").strip()
    lyric_text = normalize_lyrics(lyrics or "").strip()
    if len(prompt_text) > PROMPT_LIMIT:
        raise MusicProviderError(
            "音乐描述不能超过 2000 字",
            kind="params",
            user_message="音乐描述不能超过 2000 字",
            provider="tokenhub",
        )

    if is_instrumental:
        mode = "instrumental"
        if not prompt_text:
            raise MusicProviderError(
                "纯音乐需要音乐描述",
                kind="params",
                user_message="纯音乐需要一段音乐描述",
                provider="tokenhub",
            )
    elif lyric_text:
        mode = "lyrics"
        body_len = lyrics_body_length(lyric_text)
        if body_len < 1 or body_len > LYRICS_BODY_LIMIT:
            raise MusicProviderError(
                "歌词正文需要 1 到 3500 字",
                kind="params",
                user_message="歌词正文需要 1 到 3500 字，结构标签不计入",
                provider="tokenhub",
            )
    elif lyrics_optimizer:
        mode = "auto_lyrics"
        if not prompt_text:
            raise MusicProviderError(
                "自动写词需要音乐描述",
                kind="params",
                user_message="自动写词需要一段音乐描述",
                provider="tokenhub",
            )
    else:
        raise MusicProviderError(
            "有人声需要歌词或自动写词",
            kind="params",
            user_message="有人声的歌需要歌词，或打开自动写词",
            provider="tokenhub",
        )

    payload: dict[str, Any] = {
        "model": model,
        "is_instrumental": bool(is_instrumental),
        "output_format": output_format or "url",
        "aigc_watermark": bool(aigc_watermark),
    }
    if prompt_text:
        payload["prompt"] = prompt_text[:PROMPT_LIMIT]
    if is_instrumental:
        payload["lyrics_optimizer"] = False
    else:
        payload["lyrics_optimizer"] = mode == "auto_lyrics"
        if lyric_text:
            payload["lyrics"] = lyric_text
    if audio_setting:
        payload["audio_setting"] = {
            "sample_rate": int(audio_setting.get("sample_rate") or settings.minimax_music_sample_rate),
            "bitrate": int(audio_setting.get("bitrate") or settings.minimax_music_bitrate),
            "format": str(audio_setting.get("format") or settings.minimax_music_format),
        }
    return payload, mode


def parse_generation_body(data: dict[str, Any]) -> dict[str, Any]:
    """Split a TokenHub JSON body into audio handle plus trace fields."""
    if not isinstance(data, dict):
        raise MusicProviderError(
            "音乐服务返回了无法识别的内容",
            kind="server",
            retryable=True,
            user_message="音乐服务暂时不可用，请稍后重试",
            provider="tokenhub",
        )
    base = data.get("base_resp") if isinstance(data.get("base_resp"), dict) else {}
    code = int(base.get("status_code") or 0)
    trace_id = str(data.get("trace_id") or "") or None
    if code != 0:
        raise error_from_status(
            status_code=code,
            status_msg=str(base.get("status_msg") or ""),
            trace_id=trace_id,
            provider="tokenhub",
        )
    block = data.get("data") if isinstance(data.get("data"), dict) else {}
    status = block.get("status")
    if status not in (None, 2):
        raise MusicProviderError(
            f"音乐生成未完成 (status={status})",
            kind="server",
            retryable=True,
            trace_id=trace_id,
            user_message="音乐还在生成，请稍后重试",
            provider="tokenhub",
        )
    audio = str(block.get("audio") or "")
    if not audio:
        raise MusicProviderError(
            "音乐服务未返回音频",
            kind="server",
            retryable=True,
            trace_id=trace_id,
            user_message="音乐服务未返回音频，请稍后重试",
            provider="tokenhub",
        )
    kind = "url" if audio.startswith("http://") or audio.startswith("https://") else "hex"
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    extra = data.get("extra_info") if isinstance(data.get("extra_info"), dict) else {}
    return {
        "audio_kind": kind,
        "audio": audio,
        "trace_id": trace_id or "",
        "request_id": str(data.get("request_id") or ""),
        "usage": usage,
        "extra_info": extra,
        "response": data,
    }


class TokenHubMusicClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = (api_key or settings.tokenhub_api_key or "").strip()
        self.base_url = (base_url or settings.tokenhub_api_base).rstrip("/")
        self.model = (model or settings.tokenhub_music_model or "minimax-music-v3.0").strip()

    async def generate_music(
        self,
        prompt: str,
        lyrics: str | None = None,
        is_instrumental: bool = True,
        lyrics_optimizer: bool | None = None,
        seed: int | None = None,
        audio_format: str | None = None,
        sample_rate: int | None = None,
        bitrate: int | None = None,
        audio_setting: dict[str, Any] | None = None,
        aigc_watermark: bool | None = None,
        output_format: str | None = None,
        model: str | None = None,
        db: Any = None,
        user_id: str | None = None,
        on_accepted: AcceptedCallback | None = None,
        **_: Any,
    ) -> MusicGenerationResult:
        if not self.api_key:
            raise MusicProviderError(
                "TokenHub API Key 未配置",
                kind="auth",
                user_message="音乐服务鉴权失败，请稍后再试",
                provider="tokenhub",
            )
        use_optimizer = bool(lyrics_optimizer) and not is_instrumental and not (lyrics or "").strip()
        setting = audio_setting or {
            "sample_rate": sample_rate or settings.minimax_music_sample_rate,
            "bitrate": bitrate or settings.minimax_music_bitrate,
            "format": audio_format or settings.minimax_music_format,
        }
        payload, mode = build_music_payload(
            model=model or self.model,
            prompt=prompt,
            lyrics=lyrics,
            is_instrumental=is_instrumental,
            lyrics_optimizer=use_optimizer,
            output_format=output_format or settings.tokenhub_music_output_format,
            audio_setting=setting,
            aigc_watermark=settings.tokenhub_aigc_watermark if aigc_watermark is None else aigc_watermark,
        )
        started = time.monotonic()
        data = await self._post(payload)
        parsed = parse_generation_body(data)
        expires_at = None
        audio_url = ""
        if parsed["audio_kind"] == "url":
            audio_url = parsed["audio"]
            expires_at = (datetime.utcnow() + timedelta(hours=11, minutes=30)).isoformat()
        accepted = {
            "provider": "tokenhub",
            "model": payload["model"],
            "mode": mode,
            "trace_id": parsed["trace_id"],
            "request_id": parsed["request_id"],
            "audio_url": audio_url,
            "expires_at": expires_at,
            "usage": parsed["usage"],
            "extra_info": parsed["extra_info"],
            "tokens": int(parsed["usage"].get("total_tokens") or 0) if isinstance(parsed["usage"], dict) else 0,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        if on_accepted:
            on_accepted(accepted)

        audio_bytes: bytes | None = None
        download_error = ""
        if parsed["audio_kind"] == "hex":
            try:
                audio_bytes = bytes.fromhex(parsed["audio"])
            except ValueError as exc:
                raise MusicProviderError(
                    "音频数据无法解码",
                    kind="server",
                    retryable=True,
                    trace_id=parsed["trace_id"] or None,
                    user_message="音乐服务返回的音频无法读取，请稍后重试",
                    provider="tokenhub",
                ) from exc
            if not audio_bytes:
                raise MusicProviderError(
                    "音频数据为空",
                    kind="server",
                    retryable=True,
                    trace_id=parsed["trace_id"] or None,
                    user_message="音乐服务返回了空音频，请稍后重试",
                    provider="tokenhub",
                )
        else:
            try:
                audio_bytes = await _download(audio_url)
            except Exception as exc:
                download_error = str(exc)[:200]
                logger.warning("tokenhub audio download failed trace_id=%s", parsed["trace_id"])

        metadata = {
            **accepted,
            "response": parsed["response"],
            "download_error": download_error,
            "stream": False,
        }
        return MusicGenerationResult(
            audio_url=audio_url,
            audio_bytes=audio_bytes,
            task_id=parsed["trace_id"],
            prompt=payload.get("prompt") or "",
            lyrics=payload.get("lyrics"),
            seed=seed,
            model=payload["model"],
            metadata=metadata,
        )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{GENERATION_PATH}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = minimax_timeout(float(settings.tokenhub_music_timeout_seconds))
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=settings.minimax_http_trust_env) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise MusicProviderError(
                "TokenHub 请求超时",
                kind="timeout",
                retryable=True,
                user_message="音乐生成超时，请稍后重试",
                provider="tokenhub",
            ) from exc
        except httpx.HTTPError as exc:
            raise MusicProviderError(
                "TokenHub 连接失败",
                kind="timeout",
                retryable=True,
                user_message="音乐生成服务连接中断，请稍后重试",
                provider="tokenhub",
            ) from exc

        try:
            data = resp.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if resp.status_code != 200:
            base = data.get("base_resp") if isinstance(data.get("base_resp"), dict) else {}
            raise error_from_status(
                http_status=resp.status_code,
                status_code=base.get("status_code") if isinstance(base.get("status_code"), int) else None,
                status_msg=str(base.get("status_msg") or resp.text[:180]),
                trace_id=str(data.get("trace_id") or "") or None,
                provider="tokenhub",
            )
        return data


async def _download(url: str) -> bytes:
    timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=settings.minimax_http_trust_env, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if not resp.content:
            raise RuntimeError("empty audio")
        return resp.content
