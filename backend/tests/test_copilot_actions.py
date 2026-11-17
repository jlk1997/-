"""Copilot StudioAction builder tests."""

from app.copilot.actions import build_studio_actions


def test_apply_preset_builds_prefill_and_navigate():
    actions = build_studio_actions(
        "apply_preset",
        {"preset_id": "lo-fi-night", "text_intent": "深夜专注", "steps": 6},
    )
    types = [a["type"] for a in actions]
    assert "prefill_create" in types
    assert "navigate" in types
    prefill = next(a for a in actions if a["type"] == "prefill_create")
    assert prefill["mode"] == "playlist"
    assert prefill["payload"]["preset_id"] == "lo-fi-night"


def test_start_generation_builds_confirm_action():
    actions = build_studio_actions(
        "start_generation",
        {
            "mode": "quickTrack",
            "text_intent": "深夜 lo-fi",
            "estimate": {"cost": 3, "label": "single"},
        },
    )
    types = [a["type"] for a in actions]
    assert "start_generation" in types
    assert "prefill_create" in types
    assert "navigate" in types


def test_plan_journey_builds_journey_prefill():
    actions = build_studio_actions(
        "plan_journey_hint",
        {"journey": {"mode": "prompt_journey", "waypoints": []}, "text_intent": "焦虑到平静"},
    )
    assert any(a["type"] == "prefill_journey" for a in actions)


def test_open_creator_os_navigates_to_alias():
    actions = build_studio_actions("open_creator_os", {"target": "dataImport", "navigate": "dataImport"})
    nav = next(a for a in actions if a["type"] == "navigate")
    assert nav["path"] == "dataImport"


def test_open_creator_os_navigates_to_wallet():
    actions = build_studio_actions("open_creator_os", {"target": "wallet", "navigate": "wallet"})
    nav = next(a for a in actions if a["type"] == "navigate")
    assert nav["path"] == "wallet"


def test_open_creator_os_navigates_to_emotion_calendar():
    actions = build_studio_actions("open_creator_os", {"target": "emotionCalendar", "navigate": "emotionCalendar"})
    nav = next(a for a in actions if a["type"] == "navigate")
    assert nav["path"] == "emotionCalendar"


def test_open_beautify_navigates_to_bench():
    actions = build_studio_actions(
        "open_beautify",
        {"navigate": "/packageStudio/pages/workbench-lite/index?workId=w1", "work_id": "w1"},
    )
    nav = next(a for a in actions if a["type"] == "navigate")
    assert "workbench-lite" in nav["path"]
    assert "workId=w1" in nav["path"]
