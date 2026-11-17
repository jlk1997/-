import hashlib
import io
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.config import settings
from app.services.storage import get_storage_service


def transcode_to_hls(source_bytes: bytes, work_id: str) -> dict:
    """Convert audio to HLS segments and upload to object storage."""
    storage = get_storage_service()
    prefix = f"hls/{work_id}/{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.mp3"
        src.write_bytes(source_bytes)
        playlist = tmp_path / "index.m3u8"
        segment_pattern = tmp_path / "seg_%03d.ts"

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-codec:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "hls",
            "-hls_time",
            "6",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            str(segment_pattern),
            str(playlist),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            return {
                "status": "skipped",
                "reason": str(e),
                "hls_url": None,
                "prefix": None,
            }

        uploaded_keys = []
        for f in sorted(tmp_path.iterdir()):
            if f.suffix in (".m3u8", ".ts"):
                key = f"{prefix}/{f.name}"
                content_type = "application/vnd.apple.mpegurl" if f.suffix == ".m3u8" else "video/mp2t"
                storage.upload_bytes(f.read_bytes(), key, content_type)
                uploaded_keys.append(key)

        m3u8_key = f"{prefix}/index.m3u8"
        hls_url = storage.get_presigned_url(m3u8_key, expires=86400 * 7)
        if settings.cdn_base_url:
            hls_url = f"{settings.cdn_url}/{storage.bucket}/{m3u8_key}"

        return {
            "status": "completed",
            "hls_url": hls_url,
            "prefix": prefix,
            "segments": len([k for k in uploaded_keys if k.endswith(".ts")]),
        }


def transcode_audio(
    source_bytes: bytes,
    *,
    fmt: str,
    bitrate: str | None = None,
    sample_rate: int = 44100,
    channels: int = 2,
    bit_depth: int = 16,
) -> bytes | None:
    """Transcode audio via FFmpeg. fmt=wav (16-bit PCM default, 24-bit for TuneCore), flac, or mp3."""
    suffix = ".wav" if fmt == "wav" else ".flac" if fmt == "flac" else ".mp3"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.bin"
        out = tmp_path / f"out{suffix}"
        src.write_bytes(source_bytes)
        cmd = [settings.ffmpeg_path, "-y", "-i", str(src), "-ar", str(sample_rate), "-ac", str(channels)]
        if fmt == "wav":
            sample_fmt = "s24" if int(bit_depth) == 24 else "s16"
            cmd += ["-sample_fmt", sample_fmt, str(out)]
        elif fmt == "flac":
            cmd += ["-codec:a", "flac", str(out)]
        else:
            cmd += ["-codec:a", "libmp3lame", "-b:a", bitrate or "320k", str(out)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if not out.exists():
            return None
        return out.read_bytes()


def cut_audio_clip(
    source_bytes: bytes,
    *,
    start: float,
    duration: float,
    fmt: str = "mp3",
    bitrate: str = "192k",
) -> bytes | None:
    """Cut a short clip with fade in/out. Used for short-video BGM packs."""
    if not source_bytes or duration <= 0:
        return None
    suffix = ".wav" if fmt == "wav" else ".mp3"
    fade = min(0.18, max(0.05, float(duration) * 0.08))
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "source.bin"
        out = tmp_path / f"clip{suffix}"
        src.write_bytes(source_bytes)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-ss",
            f"{max(0.0, float(start)):.3f}",
            "-i",
            str(src),
            "-t",
            f"{float(duration):.3f}",
            "-af",
            f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={max(0.0, float(duration) - fade):.3f}:d={fade:.3f}",
            "-ar",
            "44100",
            "-ac",
            "2",
        ]
        if fmt == "wav":
            cmd += ["-sample_fmt", "s16", str(out)]
        else:
            cmd += ["-codec:a", "libmp3lame", "-b:a", bitrate, str(out)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if not out.exists():
            return None
        return out.read_bytes()


def analyze_loudness(source_bytes: bytes) -> dict:
    """Return integrated LUFS / true peak via ffmpeg loudnorm (JSON print)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.bin"
        src.write_bytes(source_bytes)
        cmd = [
            settings.ffmpeg_path,
            "-i",
            str(src),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, check=False, capture_output=True, timeout=180, text=True)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {"ok": False, "reason": "ffmpeg_unavailable"}
        blob = (proc.stderr or "") + (proc.stdout or "")
        start = blob.rfind("{")
        end = blob.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "reason": "parse_failed"}
        try:
            payload = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return {"ok": False, "reason": "invalid_json"}
        return {
            "ok": True,
            "input_i": _safe_float(payload.get("input_i")),
            "input_tp": _safe_float(payload.get("input_tp")),
            "input_lra": _safe_float(payload.get("input_lra")),
            "raw": payload,
        }


def stamp_aigc_mark(source_bytes: bytes, *, model: str, trace_id: str, fmt: str = "mp3") -> bytes:
    """Write an implicit AIGC mark into ID3/INFO. The audible watermark stays off."""
    if not source_bytes:
        return source_bytes
    summary = (trace_id or "")[:24]
    comment = f"AIGC;platform=bittune;model={model or 'unknown'};trace={summary}"
    suffix = ".wav" if fmt == "wav" else ".mp3"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dest = Path(tmp) / f"out{suffix}"
        src.write_bytes(source_bytes)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-c",
            "copy",
            "-metadata",
            f"comment={comment}",
            "-metadata",
            "encoded_by=bittune",
        ]
        if fmt != "wav":
            cmd.extend(["-id3v2_version", "3"])
        cmd.append(str(dest))
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except Exception:
            return source_bytes
        return dest.read_bytes() if dest.exists() else source_bytes


def probe_audio(source_bytes: bytes) -> dict:
    """Duration / channels / sample rate via ffprobe if available, else mutagen."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.bin"
        src.write_bytes(source_bytes)
        probe = settings.ffmpeg_path.replace("ffmpeg", "ffprobe")
        cmd = [
            probe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(src),
        ]
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, timeout=60, text=True)
            data = json.loads(proc.stdout or "{}")
            stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
            return {
                "duration": _safe_float((data.get("format") or {}).get("duration")),
                "channels": int(stream.get("channels") or 0) or None,
                "sample_rate": int(stream.get("sample_rate") or 0) or None,
            }
        except Exception:
            pass
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(io.BytesIO(source_bytes))
        if audio is None:
            return {}
        return {
            "duration": float(getattr(audio.info, "length", 0) or 0) or None,
            "channels": getattr(audio.info, "channels", None),
            "sample_rate": getattr(audio.info, "sample_rate", None),
        }
    except Exception:
        return {}


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def atempo_chain(ratio: float) -> str:
    """Split extreme ratios so each atempo stays in ffmpeg's 0.5–2.0 window."""
    parts: list[str] = []
    r = max(0.25, min(4.0, float(ratio)))
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.6f}")
    return ",".join(parts)


def transform_audio(source_bytes: bytes, *, semitones: float = 0, tempo: float = 1.0) -> bytes | None:
    """Pitch / tempo via rubberband, falling back to asetrate + atempo."""
    semitones = max(-12.0, min(12.0, float(semitones)))
    tempo = max(0.5, min(2.0, float(tempo)))
    if abs(semitones) < 0.01 and abs(tempo - 1.0) < 0.01:
        return source_bytes
    rubber = _ffmpeg_filter(
        source_bytes,
        f"rubberband=pitch={semitones}:tempo={tempo}",
        "tx.mp3",
        timeout=180,
    )
    if rubber:
        return rubber
    filters: list[str] = []
    if abs(semitones) >= 0.01:
        rate = 2 ** (semitones / 12.0)
        filters.append(f"asetrate=44100*{rate:.8f}")
        filters.append("aresample=44100")
        filters.append(atempo_chain(1.0 / rate))
    if abs(tempo - 1.0) >= 0.01:
        filters.append(atempo_chain(tempo))
    return _ffmpeg_filter(source_bytes, ",".join(filters), "tx.mp3", timeout=180)


def normalize_loudness(source_bytes: bytes, *, target_i: float = -14.0, target_tp: float = -1.5) -> bytes | None:
    """Two-pass loudnorm to a streaming target (default -14 LUFS)."""
    measured = analyze_loudness(source_bytes)
    raw = measured.get("raw") if measured.get("ok") else None
    if isinstance(raw, dict) and raw.get("input_i") is not None:
        af = (
            f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:"
            f"measured_I={raw.get('input_i')}:"
            f"measured_TP={raw.get('input_tp', target_tp)}:"
            f"measured_LRA={raw.get('input_lra', 11)}:"
            f"measured_thresh={raw.get('input_thresh', -24)}:"
            f"offset={raw.get('target_offset', 0)}:linear=true"
        )
    else:
        af = f"loudnorm=I={target_i}:TP={target_tp}:LRA=11"
    return _ffmpeg_filter(source_bytes, af, "master.mp3", timeout=180)


def build_stem_pack(source_bytes: bytes, *, title: str, duration: float | None, work=None) -> tuple[bytes, dict]:
    """Vocal / drums / bass / accompaniment pack.

    This is isolation for the light editor — not DistroKid multi-track and not a DAW project.
    """
    import zipfile

    from app.services.distribution.catalog import clip_windows
    from app.services.stem_assets import isolation_quality, load_review_stem_bytes
    from app.services.stem_separator import separate_stems

    stems: dict[str, bytes] = {}
    isolation = "unavailable"
    if work is not None:
        persisted = load_review_stem_bytes(work)
        if persisted:
            stems = persisted
            isolation = "demucs"
    if not stems:
        stems, isolation = separate_stems(source_bytes)
    names = ["full", *sorted(stems.keys())] if stems else ["full"]
    if not stems:
        isolation = "full_mix_proxy"
        stems = {"vocal": source_bytes, "accompaniment": source_bytes}
        names = ["full", "vocal", "accompaniment"]
    quality = isolation_quality(isolation)
    manifest = {
        "title": title,
        "isolation": isolation,
        "quality": quality,
        "grade": "review" if quality == "demucs" else "preview",
        "stems": names,
        "clip_windows": clip_windows(duration),
        "sections": default_sections(duration),
        "not_for_dsp_multitrack": True,
        "not_daw_stems": True,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("full.mp3", source_bytes)
        for name, blob in stems.items():
            zf.writestr(f"{name}.mp3", blob)
        zf.writestr("stems.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(
            "README.txt",
            (
                "Isolation preview / 听感隔离预览\n"
                "Not DAW stems. Not DistroKid extra tracks.\n"
                "Store listing uses the mixed master. CN originality evidence uses Demucs-grade originality.zip only.\n"
                f"quality: {quality}\n"
            ),
        )
    return buf.getvalue(), manifest


def default_sections(duration: float | None) -> list[dict]:
    total = float(duration or 90)
    third = max(total / 3, 8)
    return [
        {"id": "verse", "start": 0, "end": round(third, 2)},
        {"id": "chorus", "start": round(third, 2), "end": round(third * 2, 2)},
        {"id": "bridge", "start": round(third * 2, 2), "end": round(total, 2)},
    ]


def _png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b""
    stride = width * 4
    for y in range(height):
        raw += b"\x00" + pixels[y * stride : (y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def waveform_png_from_peaks(peaks: list[float], width: int = 640, height: int = 80) -> bytes:
    n = max(len(peaks), 1)
    pixels = bytearray(width * height * 4)
    mid = height // 2
    color = (124, 58, 237, 230)
    for x in range(width):
        peak = min(1.0, max(0.0, peaks[int(x * n / width)] if peaks else 0.0))
        bar = max(1, int(peak * (height / 2 - 2)))
        for y in range(max(0, mid - bar), min(height, mid + bar)):
            i = (y * width + x) * 4
            pixels[i : i + 4] = bytes(color)
    return _png_rgba(width, height, bytes(pixels))


def _peaks_from_pcm(pcm: bytes, buckets: int = 240) -> list[float]:
    import array

    samples = array.array("h")
    trim = len(pcm) - (len(pcm) % 2)
    if trim <= 0:
        return []
    samples.frombytes(pcm[:trim])
    if not samples:
        return []
    step = max(len(samples) // buckets, 1)
    peaks: list[float] = []
    for i in range(0, len(samples), step):
        window = samples[i : i + step]
        peaks.append(min(1.0, max(abs(s) for s in window) / 32768.0))
        if len(peaks) >= buckets:
            break
    return peaks


def _pcm_preview(source_bytes: bytes) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.bin"
        dst = Path(tmp) / "out.s16"
        src.write_bytes(source_bytes)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "8000",
            "-t",
            "60",
            "-f",
            "s16le",
            str(dst),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None
        return dst.read_bytes() if dst.exists() else None


def generate_waveform_preview(source_bytes: bytes) -> bytes | None:
    """PNG waveform: librosa/matplotlib if present, else ffmpeg PCM + stdlib PNG."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import librosa

        y, _ = librosa.load(io.BytesIO(source_bytes), sr=22050, mono=True, duration=30)
        fig, ax = plt.subplots(figsize=(6, 1.5))
        ax.plot(np.linspace(0, len(y), len(y)), y, color="#7c3aed", linewidth=0.5)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        pass
    pcm = _pcm_preview(source_bytes)
    if not pcm:
        return None
    peaks = _peaks_from_pcm(pcm)
    if not peaks:
        return None
    return waveform_png_from_peaks(peaks)
