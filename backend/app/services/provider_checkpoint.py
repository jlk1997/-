"""Remember a paid music call before the audio is durable.

Celery redelivers a task when the worker dies (`task_acks_late`). The checkpoint
lets that redelivery download the URL already paid for instead of generating again.
A URL from TokenHub expires in 12 hours.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.minimax.client import MusicGenerationResult
from app.models.schemas import GenerationJob

logger = logging.getLogger(__name__)


class ProviderAudioPending(Exception):
    """The provider already returned a URL. A recover task will finish the download."""


def call_expired(call: dict | None, *, now: datetime | None = None) -> bool:
    raw = (call or {}).get("expires_at")
    if not raw:
        return False
    try:
        expires = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    return (now or datetime.utcnow()) > expires


def read_slot(job: GenerationJob, slot: str = "main") -> dict:
    config = job.config or {}
    if slot == "main":
        call = config.get("provider_call")
        return dict(call) if isinstance(call, dict) else {}
    calls = config.get("provider_calls")
    if not isinstance(calls, dict):
        return {}
    call = calls.get(slot)
    return dict(call) if isinstance(call, dict) else {}


def write_slot(db: Session, job: GenerationJob, slot: str, patch: dict) -> dict:
    config = dict(job.config or {})
    current = read_slot(job, slot)
    current.update(patch)
    if slot == "main":
        config["provider_call"] = current
    else:
        calls = dict(config.get("provider_calls") or {})
        calls[slot] = current
        config["provider_calls"] = calls
    job.config = config
    db.commit()
    db.refresh(job)
    return current


def reusable(call: dict | None) -> bool:
    saved = call or {}
    if saved.get("state") == "stored" and saved.get("storage_key"):
        return True
    if saved.get("state") == "ready" and saved.get("audio_url") and not call_expired(saved):
        return True
    return False


def result_from_checkpoint(call: dict, audio_bytes: bytes) -> MusicGenerationResult:
    usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
    return MusicGenerationResult(
        audio_url=str(call.get("audio_url") or ""),
        audio_bytes=audio_bytes,
        task_id=str(call.get("trace_id") or ""),
        prompt=str(call.get("prompt") or ""),
        lyrics=call.get("lyrics"),
        seed=call.get("seed"),
        model=str(call.get("model") or ""),
        metadata={
            "vendor": call.get("provider"),
            "vendor_id": call.get("vendor_id"),
            "trace_id": call.get("trace_id"),
            "request_id": call.get("request_id"),
            "usage": usage,
            "extra_info": call.get("extra_info") if isinstance(call.get("extra_info"), dict) else {},
            "fallback": bool(call.get("fallback")),
            "tokens": call.get("tokens") or usage.get("total_tokens") or 0,
            "mode": call.get("mode"),
            "reused": True,
        },
    )


def checkpoint_from_result(result: MusicGenerationResult) -> dict[str, Any]:
    meta = dict(result.metadata or {})
    response = meta.get("response") if isinstance(meta.get("response"), dict) else {}
    extra = meta.get("extra_info") if isinstance(meta.get("extra_info"), dict) else {}
    if not extra and isinstance(response.get("extra_info"), dict):
        extra = response["extra_info"]
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    if not usage and isinstance(response.get("usage"), dict):
        usage = response["usage"]
    expires = meta.get("expires_at")
    if result.audio_url and not expires:
        expires = (datetime.utcnow() + timedelta(hours=11, minutes=30)).isoformat()
    return {
        "state": "ready",
        "provider": meta.get("vendor") or meta.get("provider"),
        "vendor_id": meta.get("vendor_id"),
        "model": result.model,
        "mode": meta.get("mode"),
        "trace_id": meta.get("trace_id") or result.task_id,
        "request_id": meta.get("request_id") or response.get("request_id"),
        "audio_url": result.audio_url or "",
        "expires_at": expires,
        "usage": usage,
        "extra_info": extra,
        "tokens": meta.get("tokens") or (usage.get("total_tokens") if isinstance(usage, dict) else 0) or 0,
        "fallback": bool(meta.get("fallback")),
        "prompt": result.prompt,
        "lyrics": result.lyrics,
        "seed": result.seed,
    }


async def download_provider_audio(url: str, *, attempts: int = 3) -> bytes:
    last: Exception | None = None
    timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
    for attempt in range(max(1, attempts)):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=settings.minimax_http_trust_env,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                if not resp.content:
                    raise RuntimeError("empty audio")
                return resp.content
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                import asyncio

                await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError("音频转存失败") from last


def schedule_audio_recover(job_id: str, *, countdown: int = 20) -> None:
    from app.workers.tasks import recover_provider_audio_task

    recover_provider_audio_task.apply_async(args=[str(job_id)], countdown=max(1, int(countdown)))


async def guarded_generate_music(
    db: Session,
    job: GenerationJob,
    *,
    slot: str = "main",
    schedule_recover: bool = True,
    prompt_context: dict | None = None,
    **kwargs: Any,
) -> MusicGenerationResult:
    """Call a music vendor, or reuse a checkpoint from an earlier attempt of this job."""
    from app.integrations.vendors.router import generate_music as routed_generate_music
    from app.services.storage import get_storage_service

    saved = read_slot(job, slot)
    if saved.get("state") == "stored" and saved.get("storage_key"):
        audio = get_storage_service().get_object_bytes(str(saved["storage_key"]))
        return result_from_checkpoint(saved, audio)
    if saved.get("state") == "ready" and saved.get("audio_url") and not call_expired(saved):
        try:
            audio = await download_provider_audio(str(saved["audio_url"]))
        except Exception:
            if schedule_recover and slot == "main":
                schedule_audio_recover(str(job.id))
                raise ProviderAudioPending()
            raise
        return result_from_checkpoint(saved, audio)

    context = dict(prompt_context or {})

    def _on_accepted(info: dict) -> None:
        write_slot(db, job, slot, {"state": "ready", **info, **context})

    kwargs = dict(kwargs)
    kwargs.pop("db", None)
    kwargs["on_accepted"] = _on_accepted
    result = await routed_generate_music(db=db, **kwargs)
    patch = checkpoint_from_result(result)
    patch.update(context)
    write_slot(db, job, slot, patch)
    if result.audio_bytes:
        return result
    if result.audio_url:
        try:
            result.audio_bytes = await download_provider_audio(result.audio_url)
        except Exception:
            if schedule_recover and slot == "main":
                schedule_audio_recover(str(job.id))
                raise ProviderAudioPending()
            raise
        return result
    base = ((result.metadata or {}).get("response") or {}).get("base_resp") or {}
    detail = base.get("status_msg") or "未返回音频数据"
    raise RuntimeError(f"生成失败：{detail}")
