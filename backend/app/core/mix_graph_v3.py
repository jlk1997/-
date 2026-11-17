"""MixGraph v3: Logic-style channels, inserts, sends, and buses.

v2 graphs migrate on read. The returned document still carries derived lanes and
nodes so the phone beautify renderer can keep working.
"""

from __future__ import annotations

import math
from typing import Any

MAX_CHANNELS = 16
MAX_INSERTS = 8
MAX_SENDS = 2
MAX_BUSES = 4
MAX_REGIONS_V3 = 64

CHANNEL_KINDS = frozenset(
    {"vocal", "drums", "bass", "guitar", "piano", "other", "accompaniment", "reference", "aux", "master"}
)
INSERT_TYPES = frozenset({"eq", "compressor", "gate", "deesser", "limiter", "reverb", "delay", "widen"})
BUS_IDS = ("aux-reverb", "aux-delay", "master")


def _clamp(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if math.isnan(number) or math.isinf(number):
        number = default
    return max(lo, min(hi, number))


def db_to_gain(db: float) -> float:
    if db <= -80:
        return 0.0
    return max(0.0, min(2.0, 10 ** (db / 20.0)))


def _clean_bands(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    bands: list[dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "bell")
        if kind not in {"highpass", "lowshelf", "bell", "highshelf", "lowpass"}:
            kind = "bell"
        bands.append(
            {
                "type": kind,
                "freq": _clamp(item.get("freq"), 20, 20000, 1000),
                "gain": _clamp(item.get("gain"), -24, 24, 0),
                "q": _clamp(item.get("q"), 0.1, 18, 1),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return bands


def _clean_params(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    bands = _clean_bands(raw.get("bands"))
    if bands:
        out["bands"] = bands
    for key, value in list(raw.items())[:16]:
        if key == "bands":
            continue
        name = str(key)[:24]
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = float(value)
        elif isinstance(value, str) and len(value) <= 32:
            out[name] = value
    return out


def _clean_insert(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "")
    if kind not in INSERT_TYPES:
        return None
    return {
        "id": str(raw.get("id") or f"{kind}{index}")[:32],
        "type": kind,
        "bypass": bool(raw.get("bypass")),
        "params": _clean_params(raw.get("params")),
    }


def _clean_send(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    bus = str(raw.get("bus") or "")
    if bus not in {"aux-reverb", "aux-delay"}:
        return None
    return {
        "id": str(raw.get("id") or f"send{index}")[:32],
        "bus": bus,
        "level": _clamp(raw.get("level"), 0, 1, 0),
        "pre": bool(raw.get("pre")),
    }


def _clean_points(raw: Any, *, value_key: str, lo: float, hi: float) -> list[dict[str, float]]:
    if not isinstance(raw, list):
        return []
    points: list[dict[str, float]] = []
    for item in raw[:64]:
        if not isinstance(item, dict):
            continue
        points.append({"t": _clamp(item.get("t"), 0, 3600, 0), value_key: _clamp(item.get(value_key, item.get("v")), lo, hi, 0)})
    return points


def _clean_channel(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "other")
    if kind not in CHANNEL_KINDS or kind in {"aux", "master"}:
        kind = "other"
    inserts = [row for i, item in enumerate((raw.get("inserts") or [])[:MAX_INSERTS]) if (row := _clean_insert(item, i))]
    sends = [row for i, item in enumerate((raw.get("sends") or [])[:MAX_SENDS]) if (row := _clean_send(item, i))]
    auto = raw.get("automation") if isinstance(raw.get("automation"), dict) else {}
    mode = str(raw.get("automation_mode") or "off")
    if mode not in {"read", "off"}:
        mode = "off"
    return {
        "id": str(raw.get("id") or f"ch{index}")[:32],
        "name": str(raw.get("name") or kind)[:32],
        "kind": kind,
        "color": str(raw.get("color") or "#8e8e93")[:16],
        "input_gain": _clamp(raw.get("input_gain"), -24, 24, 0),
        "fader_db": _clamp(raw.get("fader_db"), -80, 6, 0),
        "pan": _clamp(raw.get("pan"), -1, 1, 0),
        "mute": bool(raw.get("mute")),
        "solo": bool(raw.get("solo")),
        "automation_mode": mode,
        "output": "master",
        "inserts": inserts,
        "sends": sends,
        "automation": {
            "volume": _clean_points(auto.get("volume"), value_key="db", lo=-80, hi=6),
            "pan": _clean_points(auto.get("pan"), value_key="pan", lo=-1, hi=1),
        },
    }


def _default_master_inserts() -> list[dict[str, Any]]:
    return [
        {"id": "master-eq", "type": "eq", "bypass": False, "params": {}},
        {"id": "master-comp", "type": "compressor", "bypass": False, "params": {"threshold": -12, "ratio": 2, "attack": 0.03, "release": 0.2, "knee": 6, "makeup": 0}},
        {"id": "master-lim", "type": "limiter", "bypass": False, "params": {"ceiling": -1}},
    ]


def _clean_bus(raw: Any, fallback_id: str) -> dict[str, Any]:
    blob = raw if isinstance(raw, dict) else {}
    bus_id = str(blob.get("id") or fallback_id)
    if bus_id not in BUS_IDS:
        bus_id = fallback_id
    inserts_in = blob.get("inserts") if isinstance(blob.get("inserts"), list) else []
    inserts = [row for i, item in enumerate(inserts_in[:MAX_INSERTS]) if (row := _clean_insert(item, i))]
    if bus_id == "master" and not inserts:
        inserts = _default_master_inserts()
    if bus_id == "aux-reverb" and not inserts:
        inserts = [{"id": "aux-reverb-ir", "type": "reverb", "bypass": False, "params": {"decay": 1.6, "mix": 1, "predelay": 0.02}}]
    if bus_id == "aux-delay" and not inserts:
        inserts = [{"id": "aux-delay-fx", "type": "delay", "bypass": False, "params": {"mix": 1, "feedback": 0.35, "sync": 0.5}}]
    return {
        "id": bus_id,
        "name": str(blob.get("name") or bus_id)[:32],
        "kind": "master" if bus_id == "master" else "aux",
        "fader_db": _clamp(blob.get("fader_db"), -80, 6, 0),
        "mute": bool(blob.get("mute")),
        "inserts": inserts,
    }


def _clean_region(raw: Any, index: int, channel_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    channel = str(raw.get("channel") or "")
    if channel not in channel_ids:
        return None
    start = _clamp(raw.get("start"), 0, 3600, 0)
    end = _clamp(raw.get("end"), start + 0.01, 3600, start + 1)
    return {
        "id": str(raw.get("id") or f"r{index}")[:32],
        "channel": channel,
        "start": round(start, 3),
        "end": round(end, 3),
        "offset": _clamp(raw.get("offset"), 0, 3600, 0),
        "fade_in": _clamp(raw.get("fade_in"), 0, 10, 0),
        "fade_out": _clamp(raw.get("fade_out"), 0, 10, 0),
        "mute": bool(raw.get("mute")),
    }


def _derive_v2(channels: list[dict[str, Any]], buses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lanes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    for channel in channels:
        kind = channel["kind"] if channel["kind"] in {"vocal", "drums", "bass", "other", "accompaniment", "master"} else "other"
        lanes.append(
            {
                "id": channel["id"],
                "kind": kind,
                "gain": round(db_to_gain(float(channel["fader_db"])), 4),
                "mute": channel["mute"],
                "pan": channel["pan"],
                "solo": channel["solo"],
                "automation": [],
            }
        )
        for insert in channel["inserts"]:
            if insert["bypass"]:
                continue
            mapped = _insert_to_v2_node(insert, channel["id"])
            if mapped:
                nodes.append(mapped)
    master = next((bus for bus in buses if bus["id"] == "master"), None)
    master_lane = {"id": "master", "kind": "master", "gain": round(db_to_gain(float(master["fader_db"]) if master else 0), 4), "mute": False, "pan": 0.0, "solo": False, "automation": []}
    if master:
        for insert in master["inserts"]:
            mapped = _insert_to_v2_node(insert, "master")
            if mapped:
                nodes.append(mapped)
    return [*lanes[:7], master_lane], nodes[:24]


def _insert_to_v2_node(insert: dict[str, Any], target: str) -> dict[str, Any] | None:
    kind = insert["type"]
    params = insert.get("params") or {}
    if kind == "eq":
        bands = params.get("bands") if isinstance(params.get("bands"), list) else []
        low = mid = high = 0.0
        for band in bands:
            if not isinstance(band, dict) or not band.get("enabled", True):
                continue
            freq = float(band.get("freq") or 1000)
            gain = float(band.get("gain") or 0)
            if freq < 250:
                low = gain
            elif freq < 4000:
                mid = gain
            else:
                high = gain
        mapped = {"low": low, "mid": mid, "high": high}
        ntype = "eq"
    elif kind == "compressor":
        ntype = "compress"
        mapped = {"threshold": float(params.get("threshold") or -18), "ratio": float(params.get("ratio") or 2)}
    elif kind == "limiter":
        ntype = "limiter"
        mapped = {"limit": 0.9}
    elif kind == "reverb":
        ntype = "reverb"
        mapped = {"mix": float(params.get("mix") or 0.2)}
    elif kind == "delay":
        ntype = "delay"
        mapped = {"mix": float(params.get("mix") or 0.15), "ms": 180}
    elif kind == "widen":
        ntype = "widen"
        mapped = {"amount": float(params.get("amount") or 1)}
    else:
        return None
    return {"id": str(insert["id"])[:32], "type": ntype, "target": target[:32], "origin": "user", "params": mapped}


def migrate_v2_graph(blob: dict[str, Any]) -> dict[str, Any]:
    """Turn a v2 lane graph into v3 channels. Unknown lanes become 'other'."""
    lanes = blob.get("lanes") if isinstance(blob.get("lanes"), list) else []
    nodes = blob.get("nodes") if isinstance(blob.get("nodes"), list) else []
    channels: list[dict[str, Any]] = []
    for index, lane in enumerate(lanes):
        if not isinstance(lane, dict):
            continue
        kind = str(lane.get("kind") or "other")
        if kind == "master":
            continue
        gain = _clamp(lane.get("gain"), 0, 2, 1)
        db = -80.0 if gain <= 0.0001 else max(-80.0, min(6.0, 20.0 * math.log10(gain)))
        channel_id = str(lane.get("id") or kind)[:32]
        inserts = []
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            if str(node.get("target") or "master") != channel_id:
                continue
            insert = _v2_node_to_insert(node, node_index)
            if insert:
                inserts.append(insert)
        channels.append(
            {
                "id": channel_id,
                "name": kind,
                "kind": kind if kind in CHANNEL_KINDS else "other",
                "color": "#8e8e93",
                "input_gain": 0,
                "fader_db": db,
                "pan": _clamp(lane.get("pan"), -1, 1, 0),
                "mute": bool(lane.get("mute")),
                "solo": bool(lane.get("solo")),
                "automation_mode": "off",
                "output": "master",
                "inserts": inserts[:MAX_INSERTS],
                "sends": [
                    {"id": f"{channel_id}-rv", "bus": "aux-reverb", "level": 0, "pre": False},
                    {"id": f"{channel_id}-dl", "bus": "aux-delay", "level": 0, "pre": False},
                ],
                "automation": {"volume": [], "pan": []},
            }
        )
    master_inserts = []
    for node_index, node in enumerate(nodes):
        if isinstance(node, dict) and str(node.get("target") or "master") == "master":
            insert = _v2_node_to_insert(node, node_index)
            if insert:
                master_inserts.append(insert)
    return {
        "version": 3,
        "channels": channels,
        "buses": [
            {"id": "aux-reverb", "name": "Aux 1 混响", "kind": "aux"},
            {"id": "aux-delay", "name": "Aux 2 延迟", "kind": "aux"},
            {"id": "master", "name": "Stereo Out", "kind": "master", "inserts": master_inserts},
        ],
        "regions": [],
        "tempo": blob.get("tempo") if isinstance(blob.get("tempo"), dict) else {"bpm": 120, "beats_per_bar": 4, "key": ""},
        "loop": {"enabled": False, "start": 0, "end": 0},
        "source": blob.get("source") if isinstance(blob.get("source"), dict) else {},
    }


def _v2_node_to_insert(node: dict[str, Any], index: int) -> dict[str, Any] | None:
    ntype = str(node.get("type") or "")
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    mapping = {
        "eq": "eq",
        "compress": "compressor",
        "limiter": "limiter",
        "reverb": "reverb",
        "delay": "delay",
        "widen": "widen",
        "highpass": "eq",
        "lowpass": "eq",
    }
    kind = mapping.get(ntype)
    if not kind:
        return None
    cleaned = {key: value for key, value in params.items() if isinstance(value, (int, float, str, bool))}
    return {"id": str(node.get("id") or f"n{index}")[:32], "type": kind, "bypass": False, "params": cleaned}


def validate_mix_graph_v3(raw: dict[str, Any], *, work_id: str | None = None) -> dict[str, Any]:
    blob = raw
    if not isinstance(blob.get("channels"), list):
        blob = migrate_v2_graph(blob)
    channels = [row for i, item in enumerate(blob.get("channels") or []) if (row := _clean_channel(item, i))]
    channels = channels[:MAX_CHANNELS]
    buses_in = blob.get("buses") if isinstance(blob.get("buses"), list) else []
    by_id = {str(item.get("id")): item for item in buses_in if isinstance(item, dict)}
    buses = [_clean_bus(by_id.get(bus_id), bus_id) for bus_id in BUS_IDS]
    channel_ids = {row["id"] for row in channels}
    regions = [row for i, item in enumerate((blob.get("regions") or [])[:MAX_REGIONS_V3]) if (row := _clean_region(item, i, channel_ids))]
    tempo_in = blob.get("tempo") if isinstance(blob.get("tempo"), dict) else {}
    loop_in = blob.get("loop") if isinstance(blob.get("loop"), dict) else {}
    source = blob.get("source") if isinstance(blob.get("source"), dict) else {}
    sid = str(source.get("work_id") or work_id or "") or None
    lanes, nodes = _derive_v2(channels, buses)
    return {
        "version": 3,
        "source": {"work_id": sid} if sid else {},
        "tempo": {
            "bpm": _clamp(tempo_in.get("bpm"), 40, 240, 120),
            "beats_per_bar": int(_clamp(tempo_in.get("beats_per_bar"), 2, 7, 4)),
            "key": str(tempo_in.get("key") or "")[:8],
        },
        "loop": {
            "enabled": bool(loop_in.get("enabled")),
            "start": _clamp(loop_in.get("start"), 0, 3600, 0),
            "end": _clamp(loop_in.get("end"), 0, 3600, 0),
        },
        "channels": channels,
        "buses": buses,
        "regions": regions,
        "lanes": lanes,
        "nodes": nodes,
        "clips": [],
        "need_tags": [],
        "intensity": 1.0,
    }


def v3_has_edits(graph: dict[str, Any]) -> bool:
    for channel in graph.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        if abs(float(channel.get("fader_db") or 0)) >= 0.05 or channel.get("mute") or channel.get("solo"):
            return True
        if abs(float(channel.get("pan") or 0)) >= 0.01 or abs(float(channel.get("input_gain") or 0)) >= 0.05:
            return True
        if channel.get("inserts"):
            return True
        for send in channel.get("sends") or []:
            if isinstance(send, dict) and float(send.get("level") or 0) > 0.001:
                return True
    return bool(graph.get("regions"))
