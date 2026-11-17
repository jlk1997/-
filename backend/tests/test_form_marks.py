from app.core.mix_graph import validate_mix_graph
from app.services.form_marks import estimate_sections, tag_sequence
from app.services.workbench_render import automation_volume


def test_tag_sequence_and_equal_sections_without_audio():
    tags = tag_sequence("[verse]\n海\n[chorus]\n灯")
    assert tags[:2] == ["Verse", "Chorus"]
    marks = estimate_sections(None, "[Verse]\n海\n[Chorus]\n灯", duration_hint=60)
    assert marks[0]["tag"] == "Verse"
    assert marks[0]["estimated"] is True
    assert marks[-1]["end"] == 60


def test_lane_automation_survives_validation_and_builds_a_ride():
    graph = validate_mix_graph(
        {
            "lanes": [
                {"id": "vocal", "kind": "vocal", "gain": 1, "automation": [{"t": 0, "v": 0}, {"t": 4, "v": 1}]},
                {"id": "master", "kind": "master", "gain": 1},
            ],
            "nodes": [],
        }
    )
    points = graph["lanes"][0]["automation"]
    assert points[0]["v"] == 0
    ride = automation_volume(points)
    assert ride.startswith("volume=")
    assert "lt(t" in ride
