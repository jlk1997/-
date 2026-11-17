"""Render a MixGraph to one stereo master. Edit lanes never become store tracks."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from app.config import settings
from app.core.mix_graph import build_chain_af, lane_pan_af, split_pitch_tempo, validate_mix_graph
from app.services.media import transform_audio

logger = logging.getLogger(__name__)


def automation_volume(points: list | None) -> str:
    """Piecewise gain from {t, v} points. Empty when there is nothing to ride."""
    cleaned: list[tuple[float, float]] = []
    for point in points or []:
        if not isinstance(point, dict):
            continue
        try:
            cleaned.append((max(0.0, float(point.get("t") or 0)), max(0.0, min(2.0, float(point.get("v") or 1)))))
        except (TypeError, ValueError):
            continue
    if len(cleaned) < 2:
        return ""
    cleaned.sort(key=lambda item: item[0])
    expr = f"{cleaned[-1][1]:.3f}"
    for at, gain in reversed(cleaned[:-1]):
        expr = f"if(lt(t\\,{at:.3f})\\,{gain:.3f}\\,{expr})"
    return f"volume='{expr}'"


def loudness_filter(target: str = "stream") -> str:
    """Streaming -14 LUFS, short video -11 LUFS, true peak held at -1 dBTP."""
    integrated = -11 if target == "short" else -14
    return f"loudnorm=I={integrated}:TP=-1:LRA=11"


def _ffmpeg_pcm(source: bytes, af: str = "") -> bytes:
    """One intermediate step stays 32-bit float. The caller encodes once at the end."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "step.wav"
        src.write_bytes(source)
        cmd = [settings.ffmpeg_path, "-y", "-i", str(src)]
        if af:
            cmd.extend(["-af", af])
        cmd.extend(["-c:a", "pcm_f32le", str(dest)])
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except Exception:
            return source
        return dest.read_bytes() if dest.exists() else source


def _encode_mp3(source: bytes, bitrate: str = "320k") -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "out.mp3"
        src.write_bytes(source)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except Exception:
            return None
        return dest.read_bytes() if dest.exists() else None


def _encode_wav24(source: bytes) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "out.wav"
        src.write_bytes(source)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-c:a",
            "pcm_s24le",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except Exception:
            return None
        return dest.read_bytes() if dest.exists() else None


def delivery_masters(source: bytes, *, target: str = "stream") -> dict[str, bytes]:
    """Loudness-normalize once, then encode the wav master, 320k stream, and 128k preview."""
    leveled = _ffmpeg_pcm(source, loudness_filter(target))
    wav = _encode_wav24(leveled) or leveled
    mp3 = _encode_mp3(wav, "320k") or source
    preview = _encode_mp3(wav, "128k") or mp3
    return {"wav": wav, "mp3": mp3, "preview": preview}


def _ffmpeg_amix(parts: list[tuple[bytes, float]], *, duration: str = "longest") -> bytes | None:
    if not parts:
        return None
    if len(parts) == 1:
        blob, gain = parts[0]
        if abs(gain - 1.0) < 0.01:
            return blob
        return _ffmpeg_pcm(blob, f"volume={gain:.3f}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inputs: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        for index, (blob, gain) in enumerate(parts):
            src = root / f"in{index}.mp3"
            src.write_bytes(blob)
            inputs.extend(["-i", str(src)])
            label = f"a{index}"
            filters.append(f"[{index}:a]volume={max(0.0, min(2.0, gain)):.3f}[{label}]")
            labels.append(f"[{label}]")
        mix = (
            ";".join(filters)
            + f";{''.join(labels)}amix=inputs={len(parts)}:normalize=0:dropout_transition=0:duration={duration}[out]"
        )
        dest = root / "mix.wav"
        cmd = [
            settings.ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex",
            mix,
            "-map",
            "[out]",
            "-c:a",
            "pcm_f32le",
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except Exception:
            logger.warning("lane amix failed")
            return None
        return dest.read_bytes() if dest.exists() else None


def _apply_af(source: bytes, af: str) -> bytes:
    if not af:
        return source
    return _ffmpeg_pcm(source, af)


def _apply_afir(source: bytes, af: str, ir_path: str, wet: float) -> bytes:
    """Convolution reverb with the shared studio impulse. Same file the browser convolver loads."""
    wet_gain = max(0.05, min(0.8, wet))
    dry_gain = max(0.2, 1.0 - wet_gain)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.bin"
        dest = Path(tmp) / "fx.wav"
        src.write_bytes(source)
        chain = f"[0:a]{af}[dry];" if af else ""
        head = "[dry]" if af else "[0:a]"
        filt = f"{chain}{head}[1:a]afir=dry={dry_gain:.2f}:wet={wet_gain:.2f}"
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-i",
            ir_path,
            "-filter_complex",
            filt,
            "-c:a",
            "pcm_f32le",
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        except Exception:
            return _apply_af(source, af) if af else source
        return dest.read_bytes() if dest.exists() else source


def _apply_target(source: bytes, nodes: list[dict], intensity: float, target: str) -> bytes:
    from app.core.studio_ir import ensure_studio_ir

    aimed = [node for node in nodes if str(node.get("target") or "master") == target]
    reverbs = [node for node in aimed if str(node.get("type") or "") == "reverb"]
    ir = ensure_studio_ir() if reverbs else None
    if ir and reverbs:
        rest = [node for node in nodes if node not in reverbs]
        af = build_chain_af(rest, intensity, target=target)
        mix = 0.2
        for node in reverbs:
            params = node.get("params") if isinstance(node.get("params"), dict) else {}
            mix = max(mix, float(params.get("mix") or 0.2) * intensity)
        return _apply_afir(source, af, str(ir), mix)
    af = build_chain_af(nodes, intensity, target=target)
    return _apply_af(source, af) if af else source


def _lane_audible(lanes: list[dict], lane: dict) -> bool:
    if lane.get("mute") or lane.get("kind") == "master":
        return False
    solos = [row for row in lanes if row.get("solo") and row.get("kind") != "master" and not row.get("mute")]
    if solos and not lane.get("solo"):
        return False
    return True


def _source_for_clip(
    clip: dict,
    *,
    source_bytes: bytes,
    lane_bytes: dict[str, bytes] | None = None,
    take_bytes: dict[str, bytes] | None = None,
) -> bytes | None:
    src = str(clip.get("src") or "")
    if src.startswith("take:") or src.startswith("regen:"):
        token = src.split(":", 1)[1]
        return (take_bytes or {}).get(token)
    if src.startswith("lane:"):
        return (lane_bytes or {}).get(src.split(":", 1)[1])
    if lane_bytes:
        blob = lane_bytes.get(str(clip.get("lane") or ""))
        if blob:
            return blob
    return source_bytes


def _render_clip(source: bytes, clip: dict) -> bytes | None:
    if clip.get("mute") or not source:
        return None
    duration = max(0.05, float(clip.get("end") or 0) - float(clip.get("start") or 0))
    offset = max(0.0, float(clip.get("offset") or 0))
    fade_in = max(0.0, float(clip.get("fade_in") or 0))
    fade_out = max(0.0, float(clip.get("fade_out") or 0))
    gain = max(0.0, min(2.0, float(clip.get("gain") or 1)))
    parts = [f"atrim=start={offset:.3f}:duration={duration:.3f}", "asetpts=PTS-STARTPTS"]
    if fade_in >= 0.005:
        parts.append(f"afade=t=in:st=0:d={min(fade_in, duration / 2):.3f}")
    if fade_out >= 0.005:
        parts.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={min(fade_out, duration / 2):.3f}")
    if abs(gain - 1.0) >= 0.01:
        parts.append(f"volume={gain:.3f}")
    placed = _apply_af(source, ",".join(parts))
    start = max(0.0, float(clip.get("start") or 0))
    if start >= 0.02:
        ms = int(start * 1000)
        placed = _apply_af(placed, f"adelay={ms}|{ms}:all=1")
    return placed


def _finish_lane(blob: bytes, lane: dict, nodes: list[dict], intensity: float) -> bytes:
    blob = _apply_target(blob, nodes, intensity, str(lane.get("id")))
    ride = automation_volume(lane.get("automation"))
    if ride:
        blob = _apply_af(blob, ride)
    pan_af = lane_pan_af(float(lane.get("pan") or 0))
    if pan_af:
        blob = _apply_af(blob, pan_af)
    return blob


def render_mix_graph(
    source_bytes: bytes,
    graph: dict,
    *,
    lane_bytes: dict[str, bytes] | None = None,
    take_bytes: dict[str, bytes] | None = None,
    encode: str = "mp3",
) -> bytes | None:
    """Bounce one stereo master. lane_bytes are edit_lanes, never review_stems."""
    if not source_bytes:
        return None
    g = validate_mix_graph(graph)
    intensity = float(g.get("intensity") or 1.0)
    pitch, tempo, nodes = split_pitch_tempo(g)
    clips = [clip for clip in (g.get("clips") or []) if not clip.get("mute")]
    lanes = list(g.get("lanes") or [])

    mixed = source_bytes
    if clips:
        master_only = all(str(clip.get("lane") or "master") == "master" for clip in clips)
        if master_only or not lane_bytes:
            rendered: list[bytes] = []
            for clip in clips:
                blob = _source_for_clip(clip, source_bytes=source_bytes, lane_bytes=lane_bytes, take_bytes=take_bytes)
                if not blob:
                    continue
                out = _render_clip(blob, clip)
                if out:
                    rendered.append(out)
            if rendered:
                mixed = _ffmpeg_amix([(blob, 1.0) for blob in rendered]) or source_bytes
        else:
            usable: list[tuple[bytes, float]] = []
            for lane in lanes:
                if not _lane_audible(lanes, lane):
                    continue
                lane_clips = [clip for clip in clips if clip.get("lane") == lane.get("id") or clip.get("lane") == lane.get("kind")]
                blobs: list[bytes] = []
                if lane_clips:
                    for clip in lane_clips:
                        src = _source_for_clip(clip, source_bytes=source_bytes, lane_bytes=lane_bytes, take_bytes=take_bytes)
                        if not src:
                            continue
                        out = _render_clip(src, clip)
                        if out:
                            blobs.append(out)
                else:
                    raw = lane_bytes.get(str(lane.get("kind") or "")) or lane_bytes.get(str(lane.get("id") or ""))
                    if raw:
                        blobs.append(raw)
                if not blobs:
                    continue
                lane_mix = blobs[0] if len(blobs) == 1 else (_ffmpeg_amix([(blob, 1.0) for blob in blobs]) or blobs[0])
                lane_mix = _finish_lane(lane_mix, lane, nodes, intensity)
                usable.append((lane_mix, float(lane.get("gain") or 1.0)))
            if usable:
                mixed = _ffmpeg_amix(usable) or source_bytes
    elif lane_bytes:
        usable = []
        for lane in lanes:
            if not _lane_audible(lanes, lane):
                continue
            blob = lane_bytes.get(str(lane.get("kind") or "")) or lane_bytes.get(str(lane.get("id") or ""))
            if not blob:
                continue
            blob = _finish_lane(blob, lane, nodes, intensity)
            usable.append((blob, float(lane.get("gain") or 1.0)))
        if usable:
            mixed = _ffmpeg_amix(usable) or source_bytes

    if abs(pitch) >= 0.01 or abs(tempo - 1.0) >= 0.01:
        mixed = transform_audio(mixed, semitones=pitch, tempo=tempo) or mixed

    mixed = _apply_target(mixed, nodes, intensity, "master")
    if encode == "wav":
        return mixed
    return _encode_mp3(mixed, "320k") or mixed


def trim_preview(source_bytes: bytes, seconds: float = 6.0) -> bytes | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.mp3"
        dest = Path(tmp) / "preview.mp3"
        src.write_bytes(source_bytes)
        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(src),
            "-t",
            f"{max(2.0, min(12.0, seconds)):.1f}",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "5",
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except Exception:
            return None
        return dest.read_bytes() if dest.exists() else None
