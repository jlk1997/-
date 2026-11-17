"""Paid TokenHub checks. Each mode is one billed generation. Do not print the API key.

Usage (from backend/):  python scripts/probe_tokenhub_music.py
Reads TOKENHUB_API_KEY from the environment or the repo .env. Writes a summary
without response audio to stdout.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.integrations.tokenhub.music import TokenHubMusicClient  # noqa: E402
from app.integrations.vendors.errors import MusicProviderError  # noqa: E402


CASES = [
    ("v3-auto", {"model": "minimax-music-v3.0", "prompt": "soft piano, night, short", "lyrics_optimizer": True, "is_instrumental": False}),
    ("v3-lyrics", {"model": "minimax-music-v3.0", "prompt": "folk", "lyrics": "[Verse]\n雨\n[Chorus]\n灯", "is_instrumental": False}),
    ("v3-inst", {"model": "minimax-music-v3.0", "prompt": "quiet piano study", "is_instrumental": True}),
    ("v3-wav", {"model": "minimax-music-v3.0", "prompt": "quiet piano", "is_instrumental": True, "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "wav"}}),
    ("v3-48k", {"model": "minimax-music-v3.0", "prompt": "quiet piano", "is_instrumental": True, "audio_setting": {"sample_rate": 48000, "bitrate": 256000, "format": "mp3"}}),
    ("v26-inst", {"model": "minimax-music-v2.6", "prompt": "quiet piano", "is_instrumental": True}),
]


async def _one(client: TokenHubMusicClient, name: str, payload: dict) -> dict:
    started = time.monotonic()
    try:
        result = await client.generate_music(
            prompt=payload.get("prompt") or "",
            lyrics=payload.get("lyrics"),
            is_instrumental=bool(payload.get("is_instrumental")),
            lyrics_optimizer=bool(payload.get("lyrics_optimizer")),
            model=payload.get("model"),
            audio_setting=payload.get("audio_setting"),
            output_format="url",
        )
    except MusicProviderError as exc:
        return {"case": name, "ok": False, "kind": exc.kind, "seconds": round(time.monotonic() - started, 1), "trace_id": exc.trace_id}
    meta = result.metadata or {}
    extra = meta.get("extra_info") if isinstance(meta.get("extra_info"), dict) else {}
    return {
        "case": name,
        "ok": bool(result.audio_bytes or result.audio_url),
        "seconds": round(time.monotonic() - started, 1),
        "bytes": len(result.audio_bytes or b""),
        "has_url": bool(result.audio_url),
        "sample_rate": extra.get("music_sample_rate"),
        "duration_ms": extra.get("music_duration"),
        "tokens": meta.get("tokens"),
        "trace_id": meta.get("trace_id"),
        "download_error": meta.get("download_error") or "",
    }


async def main() -> int:
    if not settings.tokenhub_api_key:
        print("TOKENHUB_API_KEY is empty. Nothing was called.")
        return 2
    client = TokenHubMusicClient()
    print("probing", len(CASES), "paid generations")
    for name, payload in CASES:
        row = await _one(client, name, payload)
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
