"""MixGraph: a bounceable effect graph shared by beautify and mixer benches."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

GRAPH_VERSION = 2
MAX_NODES = 24
MAX_LANES = 8
MAX_CLIPS = 48
MAX_REGIONS = 16
MAX_HISTORY = 30

ALLOWED_NODE_TYPES = frozenset(
    {
        "eq",
        "compress",
        "limiter",
        "reverb",
        "delay",
        "loudness",
        "highpass",
        "lowpass",
        "widen",
        "pitch",
        "tempo",
        "ai_denoise",
        "ai_vocal",
        "ai_remaster",
        "regen_extend",
        "regen_remelt",
        "regen_same_style",
    }
)
AI_NODE_TYPES = frozenset({"ai_denoise", "ai_vocal", "ai_remaster"})
REGEN_NODE_TYPES = frozenset({"regen_extend", "regen_remelt", "regen_same_style"})
METADATA_NODE_TYPES = REGEN_NODE_TYPES
LANE_KINDS = frozenset({"master", "vocal", "drums", "bass", "other", "accompaniment"})
NODE_ORIGINS = frozenset({"pack", "user", "regen"})
NEED_TAGS = frozenset(
    {
        "vocal",
        "club",
        "radio",
        "lofi",
        "warm",
        "space",
        "voice",
        "width",
        "close",
        "bright",
        "denoise",
        "master",
    }
)
MOOD_NEED = {
    "energetic": ["club", "bright"],
    "happy": ["bright", "club"],
    "sad": ["space", "close"],
    "calm": ["radio", "lofi"],
    "dark": ["lofi", "warm"],
    "romantic": ["close", "warm"],
    "angry": ["club", "vocal"],
    "dreamy": ["space", "lofi"],
    "melancholy": ["space", "warm"],
    "chill": ["lofi", "radio"],
}
GENRE_NEED = {
    "pop": ["vocal", "radio"],
    "electronic": ["club", "bright"],
    "edm": ["club", "bright"],
    "lofi": ["lofi", "warm"],
    "hiphop": ["club", "vocal"],
    "hip-hop": ["club", "vocal"],
    "rock": ["bright", "vocal"],
    "folk": ["warm", "close"],
    "rnb": ["vocal", "close"],
    "r&b": ["vocal", "close"],
    "ambient": ["space", "lofi"],
    "jazz": ["warm", "radio"],
}


def empty_graph(work_id: str | None = None) -> dict[str, Any]:
    source = {"work_id": work_id} if work_id else {}
    return {
        "version": GRAPH_VERSION,
        "source": source,
        "lanes": [{"id": "master", "kind": "master", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False}],
        "nodes": [],
        "clips": [],
        "regions": [],
        "need_tags": [],
        "intensity": 1.0,
    }


def default_edit_lanes() -> list[dict[str, Any]]:
    return [
        {"id": "vocal", "kind": "vocal", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False},
        {"id": "drums", "kind": "drums", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False},
        {"id": "bass", "kind": "bass", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False},
        {"id": "other", "kind": "other", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False},
        {"id": "master", "kind": "master", "gain": 1.0, "mute": False, "pan": 0.0, "solo": False},
    ]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _clean_need_tags(raw: Any) -> list[str]:
    tags = raw if isinstance(raw, list) else []
    out: list[str] = []
    for item in tags[:8]:
        slug = str(item or "").strip().lower()[:24]
        if slug in NEED_TAGS and slug not in out:
            out.append(slug)
    return out


def _clean_automation(raw: Any) -> list[dict[str, float]]:
    if not isinstance(raw, list):
        return []
    points: list[dict[str, float]] = []
    for point in raw[:16]:
        if not isinstance(point, dict):
            continue
        try:
            points.append(
                {
                    "t": max(0.0, float(point.get("t") or 0)),
                    "v": _clamp(point.get("v", 1.0), 0.0, 2.0),
                }
            )
        except (TypeError, ValueError):
            continue
    return points if len(points) >= 2 else []


def _clean_lane(raw: dict[str, Any], index: int) -> dict[str, Any]:
    kind = str(raw.get("kind") or "master")
    if kind not in LANE_KINDS:
        kind = "master"
    lane_id = str(raw.get("id") or kind or f"lane{index}")[:32]
    return {
        "id": lane_id,
        "kind": kind,
        "gain": _clamp(raw.get("gain", 1.0), 0.0, 2.0),
        "mute": bool(raw.get("mute")),
        "pan": _clamp(raw.get("pan", 0.0), -1.0, 1.0),
        "solo": bool(raw.get("solo")),
        "automation": _clean_automation(raw.get("automation")),
    }


def _infer_origin(raw: dict[str, Any]) -> str:
    origin = str(raw.get("origin") or "")
    if origin in NODE_ORIGINS:
        return origin
    if str(raw.get("type") or "") in REGEN_NODE_TYPES:
        return "regen"
    return "pack"


def _clean_node(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    ntype = str(raw.get("type") or "")
    if ntype not in ALLOWED_NODE_TYPES:
        return None
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    cleaned_params: dict[str, Any] = {}
    for key, value in list(params.items())[:12]:
        if isinstance(value, bool):
            cleaned_params[str(key)[:24]] = value
        elif isinstance(value, (int, float)):
            cleaned_params[str(key)[:24]] = float(value)
        elif isinstance(value, str) and len(value) < 80:
            cleaned_params[str(key)[:24]] = value
        elif key == "automation" and isinstance(value, list):
            points = _clean_automation(value)
            if points:
                cleaned_params["automation"] = points
    return {
        "id": str(raw.get("id") or f"{ntype}{index}")[:32],
        "type": ntype,
        "target": str(raw.get("target") or "master")[:32],
        "origin": _infer_origin({**raw, "type": ntype}),
        "params": cleaned_params,
    }


def _clean_clip(raw: dict[str, Any], index: int, lane_ids: set[str]) -> dict[str, Any] | None:
    lane = str(raw.get("lane") or "master")[:32]
    if lane not in lane_ids:
        lane = "master" if "master" in lane_ids else (next(iter(lane_ids)) if lane_ids else "master")
    start = _clamp(raw.get("start", 0), 0.0, 600.0)
    end = _clamp(raw.get("end", start + 0.05), start + 0.05, 600.0)
    src = str(raw.get("src") or f"lane:{lane}")[:80]
    if not src.startswith(("lane:", "work", "regen:", "take:")):
        src = f"lane:{lane}"
    return {
        "id": str(raw.get("id") or f"clip{index}")[:32],
        "lane": lane,
        "src": src,
        "start": round(start, 3),
        "end": round(end, 3),
        "offset": round(_clamp(raw.get("offset", 0), 0.0, 600.0), 3),
        "fade_in": round(_clamp(raw.get("fade_in", 0), 0.0, 12.0), 3),
        "fade_out": round(_clamp(raw.get("fade_out", 0), 0.0, 12.0), 3),
        "gain": _clamp(raw.get("gain", 1.0), 0.0, 2.0),
        "mute": bool(raw.get("mute")),
    }


def _clean_region(raw: dict[str, Any], index: int) -> dict[str, Any]:
    start = _clamp(raw.get("start", 0), 0.0, 600.0)
    end = _clamp(raw.get("end", start + 0.5), start + 0.05, 600.0)
    takes_in = raw.get("takes") if isinstance(raw.get("takes"), list) else []
    takes: list[dict[str, Any]] = []
    for take in takes_in[:8]:
        if not isinstance(take, dict):
            continue
        tid = str(take.get("id") or take.get("work_id") or "")[:64]
        if not tid:
            continue
        takes.append(
            {
                "id": tid[:32],
                "work_id": str(take.get("work_id") or tid)[:64],
                "kind": str(take.get("kind") or "remelt")[:24],
                "audio_url": str(take.get("audio_url") or "")[:512],
            }
        )
    return {
        "id": str(raw.get("id") or f"r{index}")[:32],
        "start": round(start, 3),
        "end": round(end, 3),
        "label": str(raw.get("label") or "")[:32],
        "active_take": str(raw.get("active_take") or "")[:32] or None,
        "takes": takes,
    }


def validate_mix_graph(raw: Any, *, work_id: str | None = None) -> dict[str, Any]:
    blob = raw if isinstance(raw, dict) else {}
    if int(blob.get("version") or 0) == 3 or isinstance(blob.get("channels"), list):
        from app.core.mix_graph_v3 import validate_mix_graph_v3

        return validate_mix_graph_v3(blob, work_id=work_id)
    source = blob.get("source") if isinstance(blob.get("source"), dict) else {}
    sid = str(source.get("work_id") or work_id or "") or None
    lanes_in = blob.get("lanes") if isinstance(blob.get("lanes"), list) else []
    nodes_in = blob.get("nodes") if isinstance(blob.get("nodes"), list) else []
    clips_in = blob.get("clips") if isinstance(blob.get("clips"), list) else []
    regions_in = blob.get("regions") if isinstance(blob.get("regions"), list) else []
    lanes = [_clean_lane(row, i) for i, row in enumerate(lanes_in[:MAX_LANES]) if isinstance(row, dict)]
    if not lanes:
        lanes = empty_graph(sid)["lanes"]
    lane_ids = {row["id"] for row in lanes}
    nodes: list[dict[str, Any]] = []
    for i, row in enumerate(nodes_in[:MAX_NODES]):
        if not isinstance(row, dict):
            continue
        node = _clean_node(row, i)
        if not node:
            continue
        if node["target"] not in lane_ids:
            node["target"] = "master" if "master" in lane_ids else lanes[0]["id"]
        nodes.append(node)
    clips: list[dict[str, Any]] = []
    for i, row in enumerate(clips_in[:MAX_CLIPS]):
        if not isinstance(row, dict):
            continue
        clip = _clean_clip(row, i, lane_ids)
        if clip:
            clips.append(clip)
    regions = [_clean_region(row, i) for i, row in enumerate(regions_in[:MAX_REGIONS]) if isinstance(row, dict)]
    intensity = _clamp(blob.get("intensity", 1.0), 0.0, 1.5)
    return {
        "version": GRAPH_VERSION,
        "source": {"work_id": sid} if sid else {},
        "lanes": lanes,
        "nodes": nodes,
        "clips": clips,
        "regions": regions,
        "need_tags": _clean_need_tags(blob.get("need_tags") or blob.get("tags")),
        "intensity": intensity,
    }


def graph_hash(graph: dict[str, Any]) -> str:
    canonical = json.dumps(validate_mix_graph(graph), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def graph_has_ai(graph: dict[str, Any]) -> bool:
    return any(str(node.get("type")) in AI_NODE_TYPES for node in (graph.get("nodes") or []))


def graph_has_regen(graph: dict[str, Any]) -> bool:
    return any(str(node.get("type")) in REGEN_NODE_TYPES for node in (graph.get("nodes") or []))


def graph_has_edits(graph: dict[str, Any]) -> bool:
    cleaned = validate_mix_graph(graph)
    if int(cleaned.get("version") or 0) >= 3:
        from app.core.mix_graph_v3 import v3_has_edits

        return v3_has_edits(cleaned)
    if cleaned["nodes"] or cleaned["clips"]:
        return True
    return any(
        abs(float(lane.get("gain") or 1) - 1) >= 0.01
        or lane.get("mute")
        or lane.get("solo")
        or abs(float(lane.get("pan") or 0)) >= 0.01
        for lane in cleaned["lanes"]
    )


def graph_has_private_clips(graph: dict[str, Any]) -> bool:
    return bool(validate_mix_graph(graph).get("clips"))


def pack_kind_from_graph(graph: dict[str, Any]) -> str:
    cleaned = validate_mix_graph(graph)
    if any(str(node.get("target") or "master") != "master" for node in cleaned["nodes"]):
        return "lane"
    return "scene"


def freeze_pack_graph(graph: dict[str, Any], *, need_tags: list[str] | None = None) -> dict[str, Any]:
    """Strip song-private clips / regions / regen takes. Packs only carry a portable chain."""
    cleaned = validate_mix_graph(graph, work_id=None)
    if int(cleaned.get("version") or 0) >= 3:
        frozen = dict(cleaned)
        frozen["regions"] = []
        frozen["source"] = {}
        return frozen
    nodes = []
    for node in cleaned["nodes"]:
        if node["type"] in REGEN_NODE_TYPES:
            continue
        nodes.append({**node, "origin": "pack"})
    tags = _clean_need_tags(need_tags if need_tags is not None else cleaned.get("need_tags"))
    return {
        "version": GRAPH_VERSION,
        "source": {},
        "lanes": cleaned["lanes"],
        "nodes": nodes,
        "clips": [],
        "regions": [],
        "need_tags": tags,
        "intensity": 1.0,
    }


FORBIDDEN_PACK_SOURCES = ("http://", "https://", "ir:", "impulse:", "sample:", "file:", "s3://")


def pack_forbids_external_audio(graph: dict[str, Any]) -> bool:
    """Packs cannot carry hot-song IRs, remote samples, or file paths."""
    raw = graph if isinstance(graph, dict) else {}
    cleaned = validate_mix_graph(raw)
    nodes = [*(raw.get("nodes") or []), *cleaned["nodes"]]
    clips = [*(raw.get("clips") or []), *cleaned["clips"]]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        for key in ("ir", "impulse", "url", "src", "file", "sample"):
            token = str(params.get(key) or "").strip().lower()
            if token.startswith(FORBIDDEN_PACK_SOURCES):
                return True
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        src = str(clip.get("src") or "").strip().lower()
        if src.startswith(FORBIDDEN_PACK_SOURCES):
            return True
    return False


def export_listen_check(
    *,
    duration: float | None = None,
    lufs: float | None = None,
    peak_db: float | None = None,
    sample_rate: int | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if duration is not None and not (30 <= float(duration) <= 600):
        reasons.append("duration")
    if lufs is not None and float(lufs) > -9:
        reasons.append("loudness")
    if peak_db is not None and float(peak_db) > -0.1:
        reasons.append("peak")
    if sample_rate is not None and int(sample_rate) not in (44100, 48000):
        reasons.append("sample_rate")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "preview": "server_render",
        "web_audio_is_approximate": True,
    }


def loudness_match_db(lufs: float | None, target: float = -14.0) -> float | None:
    """Gain to apply so an A/B take sits at the same loudness. None if unknown."""
    if lufs is None:
        return None
    return round(float(target) - float(lufs), 2)


def publish_preflight(graph: dict[str, Any], *, need_tags: list[str] | None = None) -> dict[str, Any]:
    frozen = freeze_pack_graph(graph, need_tags=need_tags)
    blocked = pack_forbids_external_audio(graph) or pack_forbids_external_audio(frozen)
    return {
        "ok": (not blocked)
        and bool(frozen["nodes"] or any(abs(float(lane.get("gain") or 1) - 1) >= 0.01 for lane in frozen["lanes"])),
        "has_clips": graph_has_private_clips(graph),
        "stripped_clips": True,
        "forbids_external_audio": blocked,
        "kind": pack_kind_from_graph(frozen),
        "mix_graph": frozen,
        "export_check": export_listen_check(),
        "loudness_match": "apply_on_server_render",
    }


def upsert_node(graph: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_mix_graph(graph)
    incoming = _clean_node(node, len(cleaned["nodes"]))
    if not incoming:
        return cleaned
    nodes = [row for row in cleaned["nodes"] if row["type"] != incoming["type"] or row["id"] != incoming["id"]]
    if incoming["type"] in {"pitch", "tempo", "loudness"}:
        nodes = [row for row in nodes if row["type"] != incoming["type"]]
    nodes.append(incoming)
    cleaned["nodes"] = nodes[:MAX_NODES]
    return cleaned


def light_editor_nodes(*, semitones: float = 0, tempo: float = 1.0, master: bool = False) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if abs(float(semitones or 0)) >= 0.01:
        nodes.append(
            {"id": "pitch", "type": "pitch", "target": "master", "origin": "user", "params": {"semitones": float(semitones)}}
        )
    if abs(float(tempo or 1) - 1.0) >= 0.01:
        nodes.append({"id": "tempo", "type": "tempo", "target": "master", "origin": "user", "params": {"ratio": float(tempo)}})
    if master:
        nodes.append({"id": "loud", "type": "loudness", "target": "master", "origin": "user", "params": {"i": -14}})
    return nodes


def apply_pack_graph(
    pack_graph: Any,
    *,
    work_id: str,
    intensity: float,
    existing: Any | None = None,
    lanes_ready: bool = True,
) -> dict[str, Any]:
    packed = validate_mix_graph(pack_graph, work_id=work_id)
    current = validate_mix_graph(existing or {}, work_id=work_id)
    lane_pack = pack_kind_from_graph(packed) == "lane"
    if lane_pack and not lanes_ready:
        lanes = current["lanes"]
        pack_nodes = [{**node, "origin": "pack", "target": "master"} for node in packed["nodes"]]
    else:
        lanes = current["lanes"] if any(lane["kind"] != "master" for lane in current["lanes"]) else packed["lanes"]
        if len(lanes) == 1 and lanes[0]["kind"] == "master" and packed.get("lanes"):
            if any(lane.get("kind") != "master" for lane in packed["lanes"]):
                lanes = packed["lanes"]
        pack_nodes = [{**node, "origin": "pack"} for node in packed["nodes"]]
    kept = [node for node in current["nodes"] if node.get("origin") in {"user", "regen"}]
    tags = packed.get("need_tags") or current.get("need_tags") or []
    return {
        "version": GRAPH_VERSION,
        "source": {"work_id": work_id},
        "lanes": lanes,
        "nodes": (kept + pack_nodes)[:MAX_NODES],
        "clips": current["clips"],
        "regions": current["regions"],
        "need_tags": _clean_need_tags(tags),
        "intensity": _clamp(intensity, 0.0, 1.5),
    }


def pack_visible_on_surface(*, official: bool, surface: str) -> bool:
    return bool(official) if surface == "weapp" else True


def set_master_trim(graph: dict[str, Any], *, start: float, end: float) -> dict[str, Any]:
    cleaned = validate_mix_graph(graph)
    start_s = _clamp(start, 0.0, 600.0)
    end_s = _clamp(end, start_s + 0.05, 600.0)
    others = [clip for clip in cleaned["clips"] if clip["lane"] != "master"]
    others.append(
        {
            "id": "master-trim",
            "lane": "master",
            "src": "work",
            "start": round(start_s, 3),
            "end": round(end_s, 3),
            "offset": round(start_s, 3),
            "fade_in": 0.01,
            "fade_out": 0.01,
            "gain": 1.0,
            "mute": False,
        }
    )
    cleaned["clips"] = others[:MAX_CLIPS]
    return validate_mix_graph(cleaned, work_id=(cleaned.get("source") or {}).get("work_id"))


def split_clip(graph: dict[str, Any], clip_id: str, at: float) -> dict[str, Any]:
    cleaned = validate_mix_graph(graph)
    next_clips: list[dict[str, Any]] = []
    for clip in cleaned["clips"]:
        if clip["id"] != clip_id or not (clip["start"] + 0.08 < at < clip["end"] - 0.08):
            next_clips.append(clip)
            continue
        left = {**clip, "id": f"{clip['id'][:28]}a", "end": round(at, 3)}
        right_len = clip["end"] - at
        right = {
            **clip,
            "id": f"{clip['id'][:28]}b",
            "start": round(at, 3),
            "end": clip["end"],
            "offset": round(float(clip["offset"]) + (at - clip["start"]), 3),
            "fade_in": min(clip["fade_in"], right_len / 2),
        }
        next_clips.extend([left, right])
    cleaned["clips"] = next_clips[:MAX_CLIPS]
    return cleaned


def upsert_region(graph: dict[str, Any], region: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_mix_graph(graph)
    incoming = _clean_region(region, len(cleaned["regions"]))
    regions = [row for row in cleaned["regions"] if row["id"] != incoming["id"]]
    regions.append(incoming)
    cleaned["regions"] = regions[:MAX_REGIONS]
    return cleaned


def activate_take(graph: dict[str, Any], region_id: str, take_id: str) -> dict[str, Any]:
    """Mute sibling takes in a region. Bounce uses the audible clip only."""
    cleaned = validate_mix_graph(graph)
    token = str(take_id or "")[:32]
    region = next((row for row in cleaned["regions"] if row["id"] == region_id), None)
    if not region or not token:
        return cleaned
    take_ids = {str(take.get("id") or "") for take in (region.get("takes") or [])}
    if token not in take_ids:
        return cleaned
    region["active_take"] = token
    cleaned["clips"] = [
        {**clip, "mute": True} if clip["id"] in take_ids and clip["id"] != token else (
            {**clip, "mute": False} if clip["id"] == token else clip
        )
        for clip in cleaned["clips"]
    ]
    cleaned["regions"] = [region if row["id"] == region_id else row for row in cleaned["regions"]]
    return cleaned


def move_clip(graph: dict[str, Any], clip_id: str, start: float) -> dict[str, Any]:
    """Slide a clip on the same lane. Source offset stays put."""
    cleaned = validate_mix_graph(graph)
    clips: list[dict[str, Any]] = []
    for clip in cleaned["clips"]:
        if clip["id"] != clip_id:
            clips.append(clip)
            continue
        length = max(0.05, float(clip["end"]) - float(clip["start"]))
        new_start = _clamp(start, 0.0, 600.0 - length)
        clips.append({**clip, "start": round(new_start, 3), "end": round(new_start + length, 3)})
    cleaned["clips"] = clips
    return validate_mix_graph(cleaned, work_id=(cleaned.get("source") or {}).get("work_id"))


def resize_clip(graph: dict[str, Any], clip_id: str, *, start: float | None = None, end: float | None = None) -> dict[str, Any]:
    """Drag a clip edge. Left edge also walks the source offset."""
    cleaned = validate_mix_graph(graph)
    clips: list[dict[str, Any]] = []
    for clip in cleaned["clips"]:
        if clip["id"] != clip_id:
            clips.append(clip)
            continue
        new_start = clip["start"] if start is None else _clamp(start, 0.0, float(clip["end"]) - 0.05)
        new_end = clip["end"] if end is None else _clamp(end, new_start + 0.05, 600.0)
        new_offset = float(clip["offset"])
        if start is not None:
            new_offset = _clamp(new_offset + (new_start - float(clip["start"])), 0.0, 600.0)
        clips.append(
            {
                **clip,
                "start": round(float(new_start), 3),
                "end": round(float(new_end), 3),
                "offset": round(new_offset, 3),
            }
        )
    cleaned["clips"] = clips
    return validate_mix_graph(cleaned, work_id=(cleaned.get("source") or {}).get("work_id"))


def suggest_need_tags(moods: list[str] | None = None, genres: list[str] | None = None) -> list[str]:
    scores: dict[str, int] = {}
    for mood in moods or []:
        for tag in MOOD_NEED.get(str(mood).lower(), []):
            scores[tag] = scores.get(tag, 0) + 2
    for genre in genres or []:
        for tag in GENRE_NEED.get(str(genre).lower(), []):
            scores[tag] = scores.get(tag, 0) + 2
    if not scores:
        return ["vocal", "radio", "club"]
    return [tag for tag, _ in sorted(scores.items(), key=lambda item: -item[1])[:3]]


def clip_take_work_ids(graph: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for clip in validate_mix_graph(graph).get("clips") or []:
        src = str(clip.get("src") or "")
        if src.startswith(("take:", "regen:")):
            token = src.split(":", 1)[1]
            if token and token not in ids:
                ids.append(token)
    for region in validate_mix_graph(graph).get("regions") or []:
        for take in region.get("takes") or []:
            tid = str(take.get("work_id") or "")
            if tid and tid not in ids:
                ids.append(tid)
    return ids


def node_af(node: dict[str, Any], intensity: float = 1.0) -> str | None:
    """Map one MixGraph node to an ffmpeg -af fragment. Pitch/tempo/regen are handled separately."""
    ntype = str(node.get("type") or "")
    if ntype in METADATA_NODE_TYPES:
        return None
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    wet = _clamp(intensity, 0.0, 1.5)

    if ntype == "eq":
        low = float(params.get("low") or 0) * wet
        mid = float(params.get("mid") or 0) * wet
        high = float(params.get("high") or 0) * wet
        parts: list[str] = []
        if abs(low) >= 0.05:
            parts.append(f"equalizer=f=120:width_type=h:width=80:g={low:.2f}")
        if abs(mid) >= 0.05:
            parts.append(f"equalizer=f=1000:width_type=h:width=400:g={mid:.2f}")
        if abs(high) >= 0.05:
            parts.append(f"equalizer=f=8000:width_type=h:width=2000:g={high:.2f}")
        return ",".join(parts) if parts else None

    if ntype == "compress":
        threshold = float(params.get("threshold") or -18)
        ratio = float(params.get("ratio") or 2)
        return f"acompressor=threshold={threshold:.1f}dB:ratio={ratio:.2f}:attack=15:release=120"

    if ntype == "limiter":
        limit = _clamp(params.get("limit", 0.92), 0.4, 1.0)
        return f"alimiter=limit={limit:.2f}"

    if ntype == "reverb":
        mix = _clamp(float(params.get("mix") or 0.2) * wet, 0.0, 0.7)
        return f"aecho=0.8:{0.45 + mix:.2f}:70:0.35"

    if ntype == "delay":
        ms = max(40, min(600, int(params.get("ms") or 180)))
        mix = _clamp(float(params.get("mix") or 0.12) * wet, 0.0, 0.6)
        return f"aecho=0.8:{0.5 + mix:.2f}:{ms}:0.30"

    if ntype == "loudness":
        target = float(params.get("i") or -14)
        return f"loudnorm=I={target:.1f}:TP=-1.5:LRA=11"

    if ntype == "highpass":
        return f"highpass=f={max(20, min(400, int(params.get('hz') or 80)))}"

    if ntype == "lowpass":
        return f"lowpass=f={max(2000, min(18000, int(params.get('hz') or 12000)))}"

    if ntype == "widen":
        amount = 1.0 + 0.45 * wet * float(params.get("amount") or 1)
        return f"extrastereo=m={_clamp(amount, 1.0, 2.2):.2f}"

    if ntype == "ai_denoise":
        return "afftdn=nf=-20"

    if ntype == "ai_vocal":
        g = 3.0 * wet
        return (
            f"highpass=f=80,equalizer=f=2800:width_type=h:width=1200:g={g:.2f},"
            "acompressor=threshold=-18dB:ratio=2.5:attack=10:release=80"
        )

    if ntype == "ai_remaster":
        target = float(params.get("i") or -14)
        return f"loudnorm=I={target:.1f}:TP=-1.5:LRA=11,alimiter=limit=0.95"

    return None


def split_pitch_tempo(graph: dict[str, Any]) -> tuple[float, float, list[dict[str, Any]]]:
    pitch = 0.0
    tempo = 1.0
    rest: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        ntype = str(node.get("type") or "")
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        if ntype == "pitch":
            pitch = _clamp(params.get("semitones", 0), -12, 12)
        elif ntype == "tempo":
            tempo = _clamp(params.get("ratio", 1), 0.5, 2.0)
        else:
            rest.append(node)
    return pitch, tempo, rest


def build_chain_af(nodes: list[dict[str, Any]], intensity: float, *, target: str | None = "master") -> str:
    parts: list[str] = []
    for node in nodes:
        if target is not None and str(node.get("target") or "master") != target:
            continue
        fragment = node_af(node, intensity)
        if fragment:
            parts.append(fragment)
    return ",".join(parts)


def lane_pan_af(pan: float) -> str | None:
    amount = _clamp(pan, -1.0, 1.0)
    if abs(amount) < 0.02:
        return None
    return f"stereotools=panorama={amount:.3f}"


def official_pack_defs() -> list[dict[str, Any]]:
    """Official free packs that can bounce a stereo master."""

    def graph(nodes: list[dict[str, Any]], extra_lanes: bool = False, need_tags: list[str] | None = None) -> dict[str, Any]:
        lanes = default_edit_lanes() if extra_lanes else empty_graph()["lanes"]
        stamped = [{**node, "origin": node.get("origin") or "pack"} for node in nodes]
        return {
            "version": GRAPH_VERSION,
            "source": {},
            "lanes": lanes,
            "nodes": stamped,
            "clips": [],
            "regions": [],
            "need_tags": need_tags or [],
            "intensity": 1.0,
        }

    return [
        {
            "slug": "vocal_forward",
            "title": "人声靠前",
            "title_en": "Vocal forward",
            "description": "人声更近，伴奏让一点。打成一首立体声母带。",
            "tags": ["vocal"],
            "need_tags": ["vocal"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "hp", "type": "highpass", "target": "master", "params": {"hz": 80}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -1, "mid": 1.5, "high": 2.5}},
                    {"id": "comp", "type": "compress", "target": "master", "params": {"threshold": -18, "ratio": 2.4}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -14}},
                ],
                need_tags=["vocal"],
            ),
        },
        {
            "slug": "club_loud",
            "title": "夜店响度",
            "title_en": "Club loud",
            "description": "更响、更挤，适合短视频高潮。",
            "tags": ["loud", "club"],
            "need_tags": ["club"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": 1.5, "mid": 0.5, "high": 1.2}},
                    {"id": "comp", "type": "compress", "target": "master", "params": {"threshold": -16, "ratio": 3.2}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -11}},
                    {"id": "lim", "type": "limiter", "target": "master", "params": {"limit": 0.9}},
                ],
                need_tags=["club"],
            ),
        },
        {
            "slug": "radio_clean",
            "title": "电台干净",
            "title_en": "Radio clean",
            "description": "流媒体响度，少一点糊。",
            "tags": ["radio"],
            "need_tags": ["radio"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "hp", "type": "highpass", "target": "master", "params": {"hz": 70}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -0.5, "mid": 0.8, "high": 1.2}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -14}},
                ],
                need_tags=["radio"],
            ),
        },
        {
            "slug": "lofi_room",
            "title": "Lo-fi 房间",
            "title_en": "Lo-fi room",
            "description": "房间感和一点暗。",
            "tags": ["lofi"],
            "need_tags": ["lofi"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "lp", "type": "lowpass", "target": "master", "params": {"hz": 9000}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": 1.2, "mid": -0.4, "high": -1.5}},
                    {"id": "rev", "type": "reverb", "target": "master", "params": {"mix": 0.28}},
                ],
                need_tags=["lofi"],
            ),
        },
        {
            "slug": "tape_warm",
            "title": "磁带暖",
            "title_en": "Tape warm",
            "description": "低频更暖，高频收一点。",
            "tags": ["warm"],
            "need_tags": ["warm"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": 2.0, "mid": 0.6, "high": -1.2}},
                    {"id": "comp", "type": "compress", "target": "master", "params": {"threshold": -20, "ratio": 1.8}},
                ],
                need_tags=["warm"],
            ),
        },
        {
            "slug": "night_space",
            "title": "夜空",
            "title_en": "Night space",
            "description": "混响和短延迟。",
            "tags": ["space"],
            "need_tags": ["space"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -0.4, "mid": 0.4, "high": 1.0}},
                    {"id": "rev", "type": "reverb", "target": "master", "params": {"mix": 0.32}},
                    {"id": "dly", "type": "delay", "target": "master", "params": {"ms": 210, "mix": 0.14}},
                ],
                need_tags=["space"],
            ),
        },
        {
            "slug": "podcast_voice",
            "title": "播客人声",
            "title_en": "Podcast voice",
            "description": "说话更清楚。",
            "tags": ["voice"],
            "need_tags": ["voice"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "hp", "type": "highpass", "target": "master", "params": {"hz": 100}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -1.5, "mid": 2.0, "high": 1.5}},
                    {"id": "comp", "type": "compress", "target": "master", "params": {"threshold": -18, "ratio": 2.8}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -16}},
                ],
                need_tags=["voice"],
            ),
        },
        {
            "slug": "wide_stereo",
            "title": "宽立体声",
            "title_en": "Wide stereo",
            "description": "声场拉开一点。",
            "tags": ["width"],
            "need_tags": ["width"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "wide", "type": "widen", "target": "master", "params": {"amount": 1.0}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": 0.2, "mid": 0.2, "high": 1.0}},
                ],
                need_tags=["width"],
            ),
        },
        {
            "slug": "intimate",
            "title": "贴耳",
            "title_en": "Intimate",
            "description": "近、小空间。",
            "tags": ["close"],
            "need_tags": ["close"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "hp", "type": "highpass", "target": "master", "params": {"hz": 90}},
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -0.8, "mid": 1.6, "high": 0.4}},
                    {"id": "rev", "type": "reverb", "target": "master", "params": {"mix": 0.12}},
                ],
                need_tags=["close"],
            ),
        },
        {
            "slug": "sparkle",
            "title": "亮片",
            "title_en": "Sparkle",
            "description": "高频更亮。",
            "tags": ["bright"],
            "need_tags": ["bright"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "eq", "type": "eq", "target": "master", "params": {"low": -0.6, "mid": 0.4, "high": 3.0}},
                    {"id": "comp", "type": "compress", "target": "master", "params": {"threshold": -20, "ratio": 1.6}},
                ],
                need_tags=["bright"],
            ),
        },
        {
            "slug": "denoise_clean",
            "title": "去噪干净",
            "title_en": "Denoise clean",
            "description": "压一点底噪再出片。服务端去噪，不是新人声模型。",
            "tags": ["ai", "denoise"],
            "need_tags": ["denoise"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "dn", "type": "ai_denoise", "target": "master", "params": {}},
                    {"id": "hp", "type": "highpass", "target": "master", "params": {"hz": 70}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -14}},
                ],
                need_tags=["denoise"],
            ),
        },
        {
            "slug": "gentle_remaster",
            "title": "轻母带",
            "title_en": "Gentle remaster",
            "description": "响度和限幅，不改编曲。",
            "tags": ["ai", "master"],
            "need_tags": ["master"],
            "kind": "scene",
            "mix_graph": graph(
                [
                    {"id": "rm", "type": "ai_remaster", "target": "master", "params": {"i": -14}},
                ],
                need_tags=["master"],
            ),
        },
        {
            "slug": "vocal_lift_lanes",
            "title": "人声轨抬起",
            "title_en": "Vocal lane lift",
            "description": "人声轨更近、鼓轨让一点。准备分轨后听完整效果。",
            "tags": ["vocal", "lane"],
            "need_tags": ["vocal"],
            "kind": "lane",
            "mix_graph": graph(
                [
                    {"id": "vhp", "type": "highpass", "target": "vocal", "params": {"hz": 90}},
                    {"id": "veq", "type": "eq", "target": "vocal", "params": {"low": -0.6, "mid": 2.0, "high": 2.2}},
                    {"id": "vcomp", "type": "compress", "target": "vocal", "params": {"threshold": -18, "ratio": 2.6}},
                    {"id": "deq", "type": "eq", "target": "drums", "params": {"low": -0.8, "mid": 0.2, "high": 0.4}},
                    {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -14}},
                ],
                extra_lanes=True,
                need_tags=["vocal"],
            ),
        },
    ]


def clone_graph(graph: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(validate_mix_graph(graph))
