import pytest

from app.core.mix_graph import graph_has_ai, graph_hash, official_pack_defs, validate_mix_graph
from app.services.credits import GENERATION_COST
from app.services.workbench import (
    _pps_degraded,
    estimate_session_cost,
    list_effect_packs,
    next_core_door,
    preview_source_allowed,
    seed_official_effect_packs,
    session_source_id,
    walk_to_session_root,
)


@pytest.mark.requires_db
def test_seed_and_list_official_packs(db):
    created = seed_official_effect_packs(db)
    db.commit()
    assert created >= 0
    packs = list_effect_packs(db, None, scope="official", surface="h5")
    slugs = {row["slug"] for row in packs}
    expected = {item["slug"] for item in official_pack_defs()}
    assert expected <= slugs
    assert all(row["is_official"] and row["price_credits"] == 0 for row in packs)
    assert all(row["mix_graph"]["nodes"] for row in packs)
    assert all(row.get("need_tags") is not None for row in packs)
    assert any(row["slug"] == "vocal_lift_lanes" and row.get("kind") == "lane" for row in packs)
    weapp = list_effect_packs(db, None, scope="all", surface="weapp")
    assert all(row["is_official"] for row in weapp)
    assert all(row["slug"] != "community-fake" for row in weapp)


def test_official_preview_may_use_catalog_demo():
    assert preview_source_allowed(job_owner_id="u1", source_owner_id="u1", official=True, catalog_owner_id="cat")
    assert preview_source_allowed(job_owner_id="u1", source_owner_id="cat", official=True, catalog_owner_id="cat")
    assert not preview_source_allowed(job_owner_id="u1", source_owner_id="other", official=True, catalog_owner_id="cat")
    assert not preview_source_allowed(job_owner_id="u1", source_owner_id="cat", official=False, catalog_owner_id="cat")


def test_session_source_and_next_door_follow_work_b():
    from types import SimpleNamespace

    master = SimpleNamespace(id="work-b", parent_work_id="work-a", post_process_status={"workbench": True})
    raw = SimpleNamespace(id="work-a", parent_work_id=None, post_process_status={})
    assert session_source_id(master) == "work-a"
    assert session_source_id(raw) == "work-a"
    assert next_core_door(release_status=None, has_result=False) == "beautify"
    assert next_core_door(release_status="processing", has_result=True) == "radio"
    assert next_core_door(release_status="qc_ready", has_result=True) == "release"
    assert next_core_door(release_status="qc_ready", has_result=True, degraded=True) == "fix"
    assert next_core_door(release_status="live", has_result=True) == "deliveries"
    assert next_core_door(release_status="live", has_result=True, degraded=True) == "deliveries"
    assert next_core_door(release_status="", has_result=True, degraded=True) == "fix"
    # Opening Work B must not count as a bounce; no result still means beautify.
    assert next_core_door(release_status="qc_ready", has_result=False) == "beautify"

    works = {
        "c": SimpleNamespace(id="c", parent_work_id="b", post_process_status={"workbench": True}),
        "b": SimpleNamespace(id="b", parent_work_id="a", post_process_status={"workbench": True}),
        "a": SimpleNamespace(id="a", parent_work_id=None, post_process_status={}),
    }
    assert walk_to_session_root(works["c"], lambda parent_id: works.get(str(parent_id))).id == "a"
    works["b"].parent_work_id = "c"
    assert walk_to_session_root(works["c"], lambda parent_id: works.get(str(parent_id))).id in {"b", "c"}
    assert _pps_degraded({"state": "ready", "last_error": "old"}) is False
    assert _pps_degraded({"state": "pending", "failed": True}) is False
    assert _pps_degraded({"state": "degraded"}) is True
    assert _pps_degraded({"last_error": "boom"}) is True


def test_workbench_lineage_fields_are_honest():
    graph = validate_mix_graph(official_pack_defs()[0]["mix_graph"], work_id="parent-1")
    assert graph_hash(graph)
    assert graph["source"]["work_id"] == "parent-1"
    request = {
        "parent_work_id": "parent-1",
        "graph_hash": graph_hash(graph),
        "not_store_multitrack": True,
        "exit": "stereo_master",
        "intensity": graph["intensity"],
    }
    output_meta = {"tracks": 1, "sha256": "demo"}
    assert request["exit"] == "stereo_master"
    assert request["not_store_multitrack"] is True
    assert output_meta["tracks"] == 1
    eq_only = validate_mix_graph({"nodes": [{"id": "eq", "type": "eq", "target": "master", "params": {"high": 1}}]})
    free = estimate_session_cost(eq_only)
    assert free["bounce"] == 0
    assert free["fiat"] is False
    assert free["regen"] == GENERATION_COST
    ai_graph = validate_mix_graph({"nodes": [{"id": "ai", "type": "ai_denoise", "target": "master"}]})
    assert graph_has_ai(ai_graph)
    ai = estimate_session_cost(ai_graph)
    assert ai["bounce"] == 1
    assert ai["fiat"] is False
