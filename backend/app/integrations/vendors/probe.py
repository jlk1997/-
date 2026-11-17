"""Cheap live check for a vendor key. Never returns plaintext."""

from __future__ import annotations

from app.config import settings
from app.integrations.vendors.http import get_json
from app.integrations.vendors.pool import key_plaintext, mark_error, mark_ok
from app.models.schemas import VendorKey


async def probe_vendor_key(row: VendorKey) -> dict:
    key = key_plaintext(row)
    if not key:
        return {"ok": False, "error": "empty_key"}
    vendor = (row.vendor or "").strip().lower()
    base = (row.base_url or "").rstrip("/")
    try:
        if vendor == "tokenhub":
            await _probe_tokenhub(key, base)
        elif vendor == "minimax":
            await get_json(
                f"{base or settings.minimax_api_base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        elif vendor == "mureka":
            await get_json(
                f"{base or 'https://api.mureka.ai'}/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        elif vendor == "lyria":
            await get_json(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                headers={},
                timeout=15,
            )
        elif vendor == "qwen":
            await get_json(
                f"{base or 'https://dashscope.aliyuncs.com'}/compatible-mode/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        elif vendor == "elevenlabs":
            await get_json(
                f"{base or 'https://api.elevenlabs.io'}/v1/user",
                headers={"xi-api-key": key},
                timeout=15,
            )
        elif vendor == "stability":
            await get_json(
                f"{base or 'https://api.stability.ai'}/v1/user/account",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        else:
            return {"ok": True, "checked": "configured"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "checked": "live"}
    return {"ok": True, "checked": "live"}


async def _probe_tokenhub(key: str, base: str) -> None:
    """Auth check with an invalid body so a live probe does not start a paid generation."""
    import httpx

    url = f"{(base or settings.tokenhub_api_base).rstrip('/')}/v1/wand/minimax-music/generation"
    payload = {"model": settings.tokenhub_music_model, "is_instrumental": True, "prompt": ""}
    async with httpx.AsyncClient(timeout=20, trust_env=settings.minimax_http_trust_env) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code in {401, 403}:
        raise RuntimeError("tokenhub_auth_failed")
    try:
        data = resp.json()
    except Exception:
        data = {}
    base_resp = data.get("base_resp") if isinstance(data, dict) else {}
    code = (base_resp or {}).get("status_code")
    msg = str((base_resp or {}).get("status_msg") or "").lower()
    if code in {1004, 2049} or "api key" in msg or "鉴权" in msg or "unauthorized" in msg:
        raise RuntimeError("tokenhub_auth_failed")
    if resp.status_code >= 500:
        raise RuntimeError(f"tokenhub_unavailable:{resp.status_code}")


async def probe_and_record(db, row: VendorKey) -> dict:
    result = await probe_vendor_key(row)
    if result.get("ok"):
        mark_ok(db, row)
    else:
        mark_error(db, row, str(result.get("error") or "probe_failed"), cooldown_seconds=30)
    return result
