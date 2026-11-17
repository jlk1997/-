"""One studio impulse. The server convolver and the browser convolver load the same file."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DECAY_SECONDS = 0.8


def studio_ir_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "ir" / "studio.wav"


def ensure_studio_ir() -> Path:
    path = studio_ir_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 44:
        return path
    count = int(SAMPLE_RATE * DECAY_SECONDS)
    frames = bytearray()
    state = 0xC0FFEE
    for index in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        noise = ((state % 2000) - 1000) / 1000.0
        envelope = math.exp(-4.5 * index / count)
        sample = int(max(-32767, min(32767, noise * envelope * 16000)))
        frames += struct.pack("<hh", sample, sample)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)
    return path
