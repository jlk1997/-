from app.core.mix_graph import (
    activate_take,
    apply_pack_graph,
    clip_take_work_ids,
    build_chain_af,
    empty_graph,
    freeze_pack_graph,
    graph_has_ai,
    graph_has_edits,
    graph_has_regen,
    graph_hash,
    lane_pan_af,
    light_editor_nodes,
    move_clip,
    node_af,
    official_pack_defs,
    pack_forbids_external_audio,
    pack_visible_on_surface,
    publish_preflight,
    resize_clip,
    set_master_trim,
    split_clip,
    split_pitch_tempo,
    suggest_need_tags,
    upsert_node,
    upsert_region,
    validate_mix_graph,
)


def test_validate_drops_unknown_nodes_and_caps_intensity():
    graph = validate_mix_graph(
        {
            "version": 9,
            "intensity": 9,
            "lanes": [{"id": "master", "kind": "spaceship", "gain": 8, "pan": 4}],
            "nodes": [
                {"id": "eq1", "type": "eq", "target": "ghost", "params": {"low": 2, "mid": 0, "high": 1}},
                {"id": "bad", "type": "vst_serum", "params": {}},
            ],
        },
        work_id="work-a",
    )
    assert graph["version"] == 2
    assert graph["intensity"] == 1.5
    assert graph["lanes"][0]["kind"] == "master"
    assert graph["lanes"][0]["gain"] == 2.0
    assert graph["lanes"][0]["solo"] is False
    assert graph["source"]["work_id"] == "work-a"
    assert [node["type"] for node in graph["nodes"]] == ["eq"]
    assert graph["nodes"][0]["target"] == "master"
    assert graph["nodes"][0]["origin"] == "pack"
    assert graph["clips"] == []
    assert graph["regions"] == []


def test_graph_hash_is_stable():
    a = empty_graph("w1")
    b = empty_graph("w1")
    assert graph_hash(a) == graph_hash(b)
    b["nodes"].append({"id": "eq", "type": "eq", "target": "master", "params": {"high": 1}})
    assert graph_hash(a) != graph_hash(validate_mix_graph(b))


def test_node_af_scales_wet_eq_and_labels_ai_honestly():
    eq = node_af({"type": "eq", "params": {"low": 0, "mid": 0, "high": 2}}, intensity=0.5)
    assert eq and "g=1.00" in eq
    assert node_af({"type": "ai_denoise", "params": {}}) == "afftdn=nf=-20"
    remaster = node_af({"type": "ai_remaster", "params": {"i": -14}})
    assert remaster and remaster.startswith("loudnorm=")
    assert "alimiter" in remaster


def test_build_chain_skips_pitch_and_keeps_master_only():
    graph = validate_mix_graph(
        {
            "nodes": [
                {"id": "p", "type": "pitch", "target": "master", "params": {"semitones": 2}},
                {"id": "eq", "type": "eq", "target": "vocal", "params": {"high": 2}},
                {"id": "loud", "type": "loudness", "target": "master", "params": {"i": -14}},
            ],
            "lanes": [
                {"id": "master", "kind": "master"},
                {"id": "vocal", "kind": "vocal"},
            ],
        }
    )
    pitch, tempo, rest = split_pitch_tempo(graph)
    assert pitch == 2
    assert tempo == 1
    assert "loudnorm" in build_chain_af(rest, 1.0, target="master")
    assert "equalizer" in build_chain_af(rest, 1.0, target="vocal")
    assert graph_has_ai({"nodes": [{"type": "ai_vocal"}]})


def test_official_packs_are_bounceable_and_include_ai_phase2():
    slugs = {item["slug"] for item in official_pack_defs()}
    assert "vocal_forward" in slugs
    assert "denoise_clean" in slugs
    assert "gentle_remaster" in slugs
    assert len(official_pack_defs()) >= 13
    assert "vocal_lift_lanes" in slugs
    for item in official_pack_defs():
        graph = validate_mix_graph(item["mix_graph"])
        assert graph["nodes"]
        af = build_chain_af(graph["nodes"], 1.0, target="master")
        assert af


def test_apply_pack_keeps_existing_edit_lanes():
    existing = {
        "lanes": [
            {"id": "vocal", "kind": "vocal", "gain": 0.8, "mute": False},
            {"id": "master", "kind": "master", "gain": 1},
        ],
        "nodes": [{"id": "mine", "type": "ai_denoise", "target": "master", "origin": "user"}],
        "clips": [
            {
                "id": "c1",
                "lane": "vocal",
                "src": "lane:vocal",
                "start": 1,
                "end": 8,
                "offset": 1,
                "fade_in": 0.1,
                "fade_out": 0.2,
                "gain": 1,
            }
        ],
    }
    packed = official_pack_defs()[0]["mix_graph"]
    merged = apply_pack_graph(packed, work_id="w9", intensity=0.6, existing=existing)
    assert merged["intensity"] == 0.6
    assert any(lane["id"] == "vocal" and lane["gain"] == 0.8 for lane in merged["lanes"])
    assert merged["nodes"]
    assert any(node["origin"] == "user" and node["type"] == "ai_denoise" for node in merged["nodes"])
    assert any(node["origin"] == "pack" for node in merged["nodes"])
    assert merged["clips"][0]["id"] == "c1"
    frozen = freeze_pack_graph(merged)
    assert frozen["clips"] == []
    assert frozen["regions"] == []
    assert not any(node["type"].startswith("regen_") for node in frozen["nodes"])
    pre = publish_preflight(merged)
    assert pre["has_clips"] is True
    assert pre["mix_graph"]["clips"] == []


def test_lane_pack_degrades_to_master_until_lanes_ready():
    lane_pack = next(item["mix_graph"] for item in official_pack_defs() if item["slug"] == "vocal_lift_lanes")
    existing = {
        "lanes": [{"id": "master", "kind": "master", "gain": 1}],
        "clips": [{"id": "c1", "lane": "master", "src": "work", "start": 0, "end": 8, "offset": 0, "gain": 1}],
    }
    degraded = apply_pack_graph(lane_pack, work_id="w-lite", intensity=1, existing=existing, lanes_ready=False)
    assert degraded["clips"][0]["id"] == "c1"
    assert all(node["target"] == "master" for node in degraded["nodes"] if node["origin"] == "pack")
    assert not any(lane["kind"] == "vocal" for lane in degraded["lanes"])
    ready = apply_pack_graph(lane_pack, work_id="w-pro", intensity=1, existing=existing, lanes_ready=True)
    assert any(node["target"] == "vocal" for node in ready["nodes"])


def test_weapp_surface_hides_community_packs():
    assert pack_visible_on_surface(official=True, surface="weapp")
    assert not pack_visible_on_surface(official=False, surface="weapp")
    assert pack_visible_on_surface(official=False, surface="h5")


def test_v1_graph_upgrades_and_trim_splits():
    graph = validate_mix_graph({"version": 1, "nodes": [{"id": "eq", "type": "eq", "target": "master", "params": {"high": 1}}]})
    assert graph["version"] == 2
    assert graph["clips"] == []
    trimmed = set_master_trim(graph, start=2, end=20)
    assert trimmed["clips"][0]["id"] == "master-trim"
    assert trimmed["clips"][0]["start"] == 2
    split = split_clip(
        {
            **trimmed,
            "clips": [
                {
                    "id": "c1",
                    "lane": "master",
                    "src": "work",
                    "start": 0,
                    "end": 10,
                    "offset": 0,
                    "fade_in": 0,
                    "fade_out": 0,
                    "gain": 1,
                }
            ],
        },
        "c1",
        4,
    )
    assert len(split["clips"]) == 2
    assert graph_has_edits(trimmed)
    assert lane_pan_af(0) is None
    assert lane_pan_af(-0.4) == "stereotools=panorama=-0.400"
    assert suggest_need_tags(["energetic"], ["pop"])[0] in {"club", "bright", "vocal", "radio"}


def test_regen_nodes_are_metadata_not_ffmpeg():
    assert node_af({"type": "regen_extend", "params": {}}) is None
    assert node_af({"type": "regen_remelt", "params": {}}) is None
    assert node_af({"type": "regen_same_style", "params": {}}) is None
    graph = upsert_node(empty_graph("w-regen"), {"id": "regen_extend", "type": "regen_extend", "target": "master"})
    assert graph_has_regen(graph)
    assert build_chain_af(graph["nodes"], 1.0) == ""


def test_activate_take_mutes_siblings_and_keeps_chosen():
    graph = upsert_region(
        {
            "clips": [
                {"id": "take1", "lane": "master", "src": "take:w1", "start": 4, "end": 12, "offset": 0, "gain": 1},
                {"id": "take2", "lane": "master", "src": "take:w2", "start": 4, "end": 12, "offset": 0, "gain": 1},
            ],
            "regions": [
                {
                    "id": "sel",
                    "start": 4,
                    "end": 12,
                    "active_take": "take1",
                    "takes": [{"id": "take1", "work_id": "w1"}, {"id": "take2", "work_id": "w2"}],
                }
            ],
        },
        {"id": "sel", "start": 4, "end": 12, "active_take": "take1", "takes": [{"id": "take1", "work_id": "w1"}, {"id": "take2", "work_id": "w2"}]},
    )
    chosen = activate_take(graph, "sel", "take2")
    region = next(row for row in chosen["regions"] if row["id"] == "sel")
    assert region["active_take"] == "take2"
    by_id = {clip["id"]: clip for clip in chosen["clips"]}
    assert by_id["take2"]["mute"] is False
    assert by_id["take1"]["mute"] is True
    ignored = activate_take(chosen, "sel", "missing")
    assert next(row for row in ignored["regions"] if row["id"] == "sel")["active_take"] == "take2"


def test_move_and_resize_clip_keep_lane_private():
    graph = {
        "clips": [
            {
                "id": "c1",
                "lane": "master",
                "src": "work",
                "start": 2,
                "end": 10,
                "offset": 2,
                "fade_in": 0,
                "fade_out": 0,
                "gain": 1,
            }
        ]
    }
    moved = move_clip(graph, "c1", 5)
    clip = moved["clips"][0]
    assert clip["start"] == 5
    assert clip["end"] == 13
    assert clip["offset"] == 2
    left = resize_clip(moved, "c1", start=6)
    assert left["clips"][0]["start"] == 6
    assert left["clips"][0]["offset"] == 3
    frozen = freeze_pack_graph(left)
    assert frozen["clips"] == []


def test_light_editor_nodes_upsert_onto_graph():
    nodes = light_editor_nodes(semitones=2, tempo=1.1, master=True)
    assert {node["type"] for node in nodes} == {"pitch", "tempo", "loudness"}
    graph = empty_graph("w-light")
    for node in nodes:
        graph = upsert_node(graph, node)
    assert [node["type"] for node in graph["nodes"]] == ["pitch", "tempo", "loudness"]
    again = upsert_node(graph, {"id": "pitch", "type": "pitch", "target": "master", "params": {"semitones": -1}})
    assert sum(1 for node in again["nodes"] if node["type"] == "pitch") == 1
    assert again["nodes"][-1]["params"]["semitones"] == -1.0


def test_clip_take_ids_include_regen_src():
    graph = {
        "clips": [{"id": "t1", "lane": "master", "src": "regen:w-regen", "start": 0, "end": 4}],
        "regions": [{"id": "sel", "takes": [{"id": "t2", "work_id": "w-take"}]}],
    }
    assert clip_take_work_ids(graph) == ["w-regen", "w-take"]


def test_missing_take_clip_does_not_fall_back_to_source():
    from app.services.workbench_render import _source_for_clip

    assert _source_for_clip({"src": "take:missing"}, source_bytes=b"A", lane_bytes=None, take_bytes={}) is None
    assert _source_for_clip({"src": "regen:w1"}, source_bytes=b"A", lane_bytes=None, take_bytes={"w1": b"T"}) == b"T"
    assert _source_for_clip({"src": "lane:vocal"}, source_bytes=b"A", lane_bytes={"vocal": b"V"}) == b"V"
    assert _source_for_clip({"src": "lane:missing"}, source_bytes=b"A", lane_bytes={}) is None
    assert _source_for_clip({"src": ""}, source_bytes=b"A", lane_bytes=None) == b"A"


def test_publish_preflight_blocks_external_ir_and_remote_samples():
    dirty = validate_mix_graph(
        {
            "nodes": [
                {"id": "r", "type": "reverb", "target": "master", "params": {"ir": "https://evil.test/hot.wav"}},
            ]
        }
    )
    assert pack_forbids_external_audio(dirty)
    blocked = publish_preflight(dirty)
    assert blocked["ok"] is False
    assert blocked["forbids_external_audio"] is True
    sample = {
        "clips": [{"id": "c1", "lane": "master", "src": "s3://bucket/sample.wav", "start": 0, "end": 4}],
        "nodes": [{"id": "eq", "type": "eq", "target": "master", "params": {"high": 1}}],
    }
    assert pack_forbids_external_audio(sample)
    clean = validate_mix_graph(official_pack_defs()[0]["mix_graph"])
    assert pack_forbids_external_audio(clean) is False
    assert publish_preflight(clean)["forbids_external_audio"] is False
    assert publish_preflight(clean)["ok"] is True
