"""Pluggable stem isolation.

Preview exports may fall back to ffmpeg bands / mid-side.
Review / originality packs must call Demucs only — ffmpeg is not DAW stems.
Worker images may optionally install Demucs (`htdemucs`, CPU is fine).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings


def _ffmpeg_filter(source: bytes, af: str, suffix: str, *, timeout: int = 90) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.mp3"
        dest = Path(tmp) / suffix
        src.write_bytes(source)
        cmd = [settings.ffmpeg_path, "-y", "-i", str(src), "-af", af, "-acodec", "libmp3lame", "-q:a", "4", str(dest)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        except Exception:
            return None
        return dest.read_bytes() if dest.exists() else None


class FfmpegBandSeparator:
    """Vocal / drums / bass / accompaniment via complementary bands.

    Honest label: ffmpeg_bands — not studio Demucs. Better than mid-side alone.
    """

    name = "ffmpeg_bands"

    def separate(self, source_bytes: bytes) -> dict[str, bytes]:
        vocal = _ffmpeg_filter(source_bytes, "highpass=f=200,pan=mono|c0=0.5*c0+-0.5*c1", "vocal.mp3")
        bass = _ffmpeg_filter(source_bytes, "lowpass=f=180,volume=1.15", "bass.mp3")
        drums = _ffmpeg_filter(
            source_bytes,
            "highpass=f=80,lowpass=f=6000,acompressor=threshold=-18dB:ratio=6:attack=5:release=80",
            "drums.mp3",
        )
        accomp = _ffmpeg_filter(
            source_bytes,
            "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,lowpass=f=8000",
            "accomp.mp3",
        )
        stems: dict[str, bytes] = {}
        if vocal:
            stems["vocal"] = vocal
        if bass:
            stems["bass"] = bass
        if drums:
            stems["drums"] = drums
        if accomp:
            stems["accompaniment"] = accomp
        return stems


class FfmpegMidSideSeparator:
    name = "mid_side"

    def separate(self, source_bytes: bytes) -> dict[str, bytes]:
        vocal = _ffmpeg_filter(source_bytes, "pan=mono|c0=0.5*c0+-0.5*c1", "vocal.mp3")
        accomp = _ffmpeg_filter(
            source_bytes,
            "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1",
            "accomp.mp3",
        )
        stems: dict[str, bytes] = {}
        if vocal:
            stems["vocal"] = vocal
        if accomp:
            stems["accompaniment"] = accomp
        return stems


class DemucsSeparator:
    """Optional local Demucs CLI. Never invented rows if the binary is missing."""

    name = "demucs"

    def __init__(self, *, two_stems: bool = False, model: str | None = None):
        self.two_stems = two_stems
        self.model = (model or getattr(settings, "stem_model", "") or "htdemucs").strip() or "htdemucs"

    def separate(self, source_bytes: bytes) -> dict[str, bytes]:
        binary = shutil.which("demucs")
        if not binary:
            raise RuntimeError("demucs_unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "mix.mp3"
            out_dir = Path(tmp) / "out"
            src.write_bytes(source_bytes)
            command = [binary, "-n", self.model, "-j", "1", "--segment", "7", "-o", str(out_dir), str(src)]
            if self.two_stems:
                command[1:1] = ["--two-stems", "vocals"]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=900)
            except Exception as exc:
                raise RuntimeError("demucs_failed") from exc
            wavs = list(out_dir.rglob("*.wav"))
            stems: dict[str, bytes] = {}
            for wav in wavs:
                key = wav.stem.lower()
                if key in {"vocals", "vocal"}:
                    stems["vocal"] = wav.read_bytes()
                elif key in {"no_vocals", "accompaniment"}:
                    stems["accompaniment"] = wav.read_bytes()
                elif key == "other":
                    # 4-stem htdemucs calls this the accompaniment. 6-stem keeps guitar and piano apart.
                    stems["other" if "6s" in self.model else "accompaniment"] = wav.read_bytes()
                elif key in {"drums", "bass", "guitar", "piano"}:
                    stems[key] = wav.read_bytes()
            if not stems:
                raise RuntimeError("demucs_empty")
            return stems


def get_separator(name: str | None = None):
    pref = (name or getattr(settings, "stem_separator", "auto") or "auto").strip().lower()
    if pref == "demucs":
        return DemucsSeparator()
    if pref == "mid_side":
        return FfmpegMidSideSeparator()
    if pref in ("ffmpeg_bands", "bands", "auto"):
        return FfmpegBandSeparator()
    return FfmpegBandSeparator()


def separate_stems(
    source_bytes: bytes,
    *,
    preferred: str | None = None,
    allow_ffmpeg_fallback: bool = True,
) -> tuple[dict[str, bytes], str]:
    """Return stems plus isolation name.

    allow_ffmpeg_fallback=False is the review path: Demucs or empty, never bands.
    """
    pref = (preferred or getattr(settings, "stem_separator", "auto") or "auto").strip().lower()
    if pref in ("auto", "demucs"):
        try:
            stems = DemucsSeparator().separate(source_bytes)
            if stems:
                return stems, DemucsSeparator.name
        except RuntimeError:
            pass
        if not allow_ffmpeg_fallback:
            return {}, "preview"
    separator = get_separator("ffmpeg_bands" if pref in ("auto", "demucs") else pref)
    stems = separator.separate(source_bytes)
    if stems:
        return stems, separator.name
    fallback = FfmpegMidSideSeparator()
    stems = fallback.separate(source_bytes)
    return stems, fallback.name if stems else "full_mix_proxy"
