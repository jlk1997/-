from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.distribution.catalog import clip_windows
from app.services.distribution.passport import workbench_human_edits
from app.services.distribution.timeline import _compute_next_action
from app.services.notifications import build_job_notify_payload
from app.services.radio.network import include_owner_radio_trial, should_retarget_radio_trial
from app.services.royalty.hub import count_needs_beautify, is_workbench_master, prefer_workbench_masters
from app.services.workbench import stamp_regen_failed


def test_is_workbench_master_reads_post_process_flag():
    assert is_workbench_master(SimpleNamespace(post_process_status={"workbench": True}))
    assert not is_workbench_master(SimpleNamespace(post_process_status={}))
    assert not is_workbench_master(SimpleNamespace(post_process_status=None))


def test_unpublished_prefers_workbench_master_over_parent():
    parent = SimpleNamespace(id="work-a", parent_work_id=None, post_process_status={})
    child = SimpleNamespace(id="work-b", parent_work_id="work-a", post_process_status={"workbench": True})
    other = SimpleNamespace(id="work-c", parent_work_id=None, post_process_status={})
    kept = prefer_workbench_masters([parent, child, other])
    assert [row.id for row in kept] == ["work-b", "work-c"]
    assert count_needs_beautify(kept) == 1
    assert count_needs_beautify([parent, other]) == 2
    assert count_needs_beautify([child]) == 0


def test_next_action_beautify_for_raw_unpublished():
    stages = [
        {"stage": "post_process", "status": "ready", "can_rerun": False},
        {"stage": "qc", "status": "pending"},
        {"stage": "distribution", "status": "not_started"},
        {"stage": "release_assets", "status": "pending"},
    ]
    raw = SimpleNamespace(audio_url="https://cdn/a.mp3", post_process_status={})
    assert _compute_next_action(stages, raw)["action"] == "beautify"
    bounced = SimpleNamespace(audio_url="https://cdn/b.mp3", post_process_status={"workbench": True})
    assert _compute_next_action(stages, bounced)["action"] == "run_qc"


def test_passport_stamps_workbench_as_human_edit():
    prov = SimpleNamespace(
        record_type="workbench",
        output_meta={"sha256": "x", "tracks": 1},
        music_request={"graph_hash": "abc123", "pack_id": "pack-1", "exit": "stereo_master"},
    )
    edits = workbench_human_edits(prov)
    assert edits[0]["kind"] == "workbench"
    assert edits[0]["exit"] == "stereo_master"
    assert edits[0]["not_store_multitrack"] is True
    again = workbench_human_edits(
        SimpleNamespace(record_type="workbench", output_meta={"human_edits": edits}, music_request=prov.music_request)
    )
    assert sum(1 for row in again if row.get("kind") == "workbench") == 1


def test_bounce_clip_windows_backfill_when_parent_empty():
    assert clip_windows(12) == []
    windows = clip_windows(90)
    assert windows
    assert windows[0]["length"] == 15
    assert windows[0]["use"] == "short_video"


def test_failed_regen_stamps_node_without_moving_result():
    graph = {
        "nodes": [
            {
                "id": "regen_remelt",
                "type": "regen_remelt",
                "target": "master",
                "params": {"job": "abc12345-xxxx-xxxx-xxxx"},
            },
            {"id": "eq", "type": "eq", "target": "master", "params": {}},
        ]
    }
    out = stamp_regen_failed(graph, "abc12345-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    remelt = next(node for node in out["nodes"] if node["type"] == "regen_remelt")
    eq = next(node for node in out["nodes"] if node["type"] == "eq")
    assert remelt["params"]["failed"] is True
    assert "failed" not in (eq.get("params") or {})


def test_failed_regen_keeps_private_clips():
    graph = {
        "clips": [{"id": "c1", "lane": "master", "src": "work", "start": 0, "end": 8, "offset": 0}],
        "nodes": [{"id": "regen_extend", "type": "regen_extend", "target": "master", "params": {"job": "abc12345"}}],
    }
    out = stamp_regen_failed(graph, "abc12345-dead-beef")
    assert out["clips"][0]["id"] == "c1"
    assert next(node for node in out["nodes"] if node["type"] == "regen_extend")["params"]["failed"] is True


def test_job_notify_payload_routes_workbench_tap_to_session():
    bounced = build_job_notify_payload(
        job_id="j1",
        job_type="workbench_render",
        work_id="work-b",
        config={"source_work_id": "work-a", "workbench_session_id": "sess-1"},
        result={"parent_work_id": "work-a"},
        message="done",
    )
    assert bounced["source_work_id"] == "work-a"
    assert bounced["parent_work_id"] == "work-a"
    assert bounced["workbench_session_id"] == "sess-1"
    assert bounced["remix_intent"] == "workbench"
    regen = build_job_notify_payload(
        job_id="j2",
        job_type="single",
        work_id="work-c",
        config={
            "source_work_id": "work-a",
            "seed_work_id": "work-b",
            "workbench_session_id": "sess-1",
        },
        result={},
        message="fail",
    )
    assert regen["remix_intent"] == "workbench"
    assert regen["source_work_id"] == "work-a"
    plain = build_job_notify_payload(
        job_id="j3",
        job_type="single",
        work_id="work-d",
        config={},
        result={},
        message="ok",
    )
    assert "remix_intent" not in plain
    assert "workbench_session_id" not in plain


def test_should_retarget_radio_when_trial_not_live():
    assert should_retarget_radio_trial(SimpleNamespace(post_process_status={}))
    assert should_retarget_radio_trial(SimpleNamespace(post_process_status={"radio_trial": {"status": "ended"}}))
    live_until = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    assert not should_retarget_radio_trial(
        SimpleNamespace(post_process_status={"radio_trial": {"status": "live", "ends_at": live_until}})
    )
    expired = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    assert should_retarget_radio_trial(
        SimpleNamespace(post_process_status={"radio_trial": {"status": "live", "ends_at": expired}})
    )


def test_owner_radio_list_keeps_live_parent_hides_superseded():
    assert include_owner_radio_trial(has_trial=True, live=True, superseded=True)
    assert not include_owner_radio_trial(has_trial=True, live=False, superseded=True)
    assert include_owner_radio_trial(has_trial=True, live=False, superseded=False)
    assert not include_owner_radio_trial(has_trial=False, live=False, superseded=False)


def test_week_drop_pool_drops_superseded_parent():
    parent = SimpleNamespace(id="work-a", parent_work_id=None, post_process_status={})
    child = SimpleNamespace(id="work-b", parent_work_id="work-a", post_process_status={"workbench": True})
    pool = prefer_workbench_masters([parent, child])
    assert [row.id for row in pool] == ["work-b"]


def test_sync_hops_to_listed_or_owner_successor():
    from app.services.royalty.sync_desk import should_hop_sync

    assert should_hop_sync(for_owner=True, successor_listed=False)
    assert should_hop_sync(for_owner=False, successor_listed=True)
    assert not should_hop_sync(for_owner=False, successor_listed=False)
