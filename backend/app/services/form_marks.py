"""Estimated section marks. Lyric tags set the order; energy only suggests the boundaries."""

from __future__ import annotations

import io

from app.core.lyrics_structure import STRUCTURE_TEMPLATES, canonical_label, _TAG_RE


def tag_sequence(lyrics: str | None) -> list[str]:
    found: list[str] = []
    for match in _TAG_RE.finditer(lyrics or ""):
        label = canonical_label(match.group(1))
        if label:
            found.append(label)
    return found or list(STRUCTURE_TEMPLATES["standard"])


def _equal_marks(tags: list[str], duration: float) -> list[dict]:
    span = duration / max(1, len(tags))
    return [
        {
            "tag": tag,
            "start": round(i * span, 2),
            "end": round((i + 1) * span, 2),
            "estimated": True,
        }
        for i, tag in enumerate(tags)
    ]


def estimate_sections(audio_bytes: bytes | None, lyrics: str | None, *, duration_hint: float | None = None) -> list[dict]:
    tags = tag_sequence(lyrics)
    duration = float(duration_hint or 0)
    boundaries: list[float] = []
    if audio_bytes:
        try:
            import librosa
            import numpy as np

            audio, sample_rate = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True, duration=240)
            if sample_rate and len(audio):
                duration = float(len(audio) / sample_rate)
            if duration > 8 and len(tags) > 1:
                hop = 512
                rms = librosa.feature.rms(y=audio, hop_length=hop)[0]
                change = np.maximum(0, np.diff(rms))
                need = len(tags) - 1
                gap = max(1, int(len(change) / (need + 1) * 0.55))
                picks: list[int] = []
                for index in np.argsort(change)[::-1]:
                    point = int(index)
                    if all(abs(point - chosen) > gap for chosen in picks):
                        picks.append(point)
                    if len(picks) >= need:
                        break
                picks.sort()
                boundaries = [0.0, *[float(point * hop / sample_rate) for point in picks], duration]
        except Exception:
            boundaries = []
    if duration <= 1:
        duration = float(duration_hint or 180)
    if len(boundaries) < len(tags) + 1:
        return _equal_marks(tags, duration)
    marks = []
    for index, tag in enumerate(tags):
        start = boundaries[index]
        end = boundaries[index + 1] if index + 1 < len(boundaries) else duration
        marks.append({"tag": tag, "start": round(start, 2), "end": round(max(end, start), 2), "estimated": True})
    return marks
