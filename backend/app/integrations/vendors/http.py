from __future__ import annotations

import httpx

from app.config import settings


async def fetch_audio_bytes(url: str, headers: dict | None = None) -> bytes:
    async with httpx.AsyncClient(timeout=120, trust_env=settings.minimax_http_trust_env) as client:
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.content


async def post_json(url: str, *, headers: dict, payload: dict, timeout: float = 120) -> dict:
    async with httpx.AsyncClient(timeout=timeout, trust_env=settings.minimax_http_trust_env) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}


async def get_json(url: str, *, headers: dict, timeout: float = 60) -> dict:
    async with httpx.AsyncClient(timeout=timeout, trust_env=settings.minimax_http_trust_env) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}
