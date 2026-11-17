from app.core.mix_graph import graph_has_edits, validate_mix_graph
from app.core.mix_graph_v3 import migrate_v2_graph


def test_v2_graph_stays_version_2():
    cleaned = validate_mix_graph({"version": 2, "lanes": [{"id": "master", "kind": "master", "gain": 1}]})
    assert cleaned["version"] == 2
    assert "channels" not in cleaned


def test_v2_migrates_when_asked_and_round_trips_as_v3():
    migrated = migrate_v2_graph(
        {
            "version": 2,
            "lanes": [
                {"id": "vocal", "kind": "vocal", "gain": 1, "pan": -0.2, "mute": False, "solo": False},
                {"id": "master", "kind": "master", "gain": 1},
            ],
            "nodes": [{"id": "c1", "type": "compress", "target": "vocal", "params": {"threshold": -16, "ratio": 3}}],
        }
    )
    cleaned = validate_mix_graph(migrated)
    assert cleaned["version"] == 3
    vocal = next(row for row in cleaned["channels"] if row["id"] == "vocal")
    assert vocal["pan"] == -0.2
    assert any(insert["type"] == "compressor" for insert in vocal["inserts"])
    assert any(bus["id"] == "master" for bus in cleaned["buses"])
    assert graph_has_edits(cleaned)


def test_flat_v3_without_inserts_is_not_an_edit():
    cleaned = validate_mix_graph(
        {
            "version": 3,
            "channels": [{"id": "vocal", "kind": "vocal", "name": "人声", "fader_db": 0, "pan": 0, "inserts": [], "sends": []}],
            "buses": [],
        }
    )
    assert cleaned["version"] == 3
    assert graph_has_edits(cleaned) is False
