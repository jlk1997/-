"""Lyrics timeline parsing tests."""

from app.services.lyrics_timeline import build_lyrics_timeline, parse_lrc_timeline, sections_from_lyrics


def test_parse_lrc_timeline():
    text = """[00:12.50]第一句歌词
[00:25.00]第二句歌词
[ar:Artist]"""
    timeline = parse_lrc_timeline(text)
    assert len(timeline) == 2
    assert timeline[0]["text"] == "第一句歌词"
    assert abs(timeline[0]["time"] - 12.5) < 0.01
    assert timeline[1]["time"] == 25.0


def test_build_lyrics_timeline_prefers_embedded():
    embedded = [{"time": 5.0, "text": "Hello"}, {"time": 10.0, "text": "World"}]
    lyrics, timeline = build_lyrics_timeline(None, duration=60, embedded_timeline=embedded)
    assert lyrics == "Hello\nWorld"
    assert timeline == embedded


def test_build_lyrics_timeline_plain_fallback():
    lyrics, timeline = build_lyrics_timeline("Line one\nLine two", duration=60)
    assert lyrics == "Line one\nLine two"
    assert timeline and len(timeline) == 2


def test_sections_from_lyrics_tags():
    lyrics = "[Verse]\n夜里走路\n[Chorus]\n灯还亮着\n[Bridge]\n先别回家"
    sections = sections_from_lyrics(lyrics, 90)
    ids = [row["id"] for row in sections]
    assert ids == ["verse", "chorus", "bridge"]
    assert sections[0]["start"] == 0
    assert sections[-1]["end"] == 90


def test_variation_second_take_remelts():
    from app.workers.tasks import variation_sub_config

    first = variation_sub_config({"title": "Demo", "remelt": False, "seeds": [1, 2], "variation_count": 2}, 0, 11)
    second = variation_sub_config({"title": "Demo", "remelt": False, "seeds": [1, 2], "variation_count": 2}, 1, 22)
    assert first["remelt"] is False
    assert first["title"] == "Demo #1"
    assert "seeds" not in first
    assert second["remelt"] is True
    assert second["title"] == "Demo #2"


def test_apply_section_edits_overrides_times():
    from app.api.routes.studio import _apply_section_edits

    sections = [{"id": "verse", "start": 0, "end": 30}, {"id": "chorus", "start": 30, "end": 60}]
    out = _apply_section_edits(sections, [{"kind": "section", "section": "chorus", "start": 28, "end": 58}])
    chorus = next(row for row in out if row["id"] == "chorus")
    assert chorus["start"] == 28
    assert chorus["end"] == 58


def test_playlist_music_request_keeps_vendor_id_only():
    from types import SimpleNamespace

    from app.core.playlist_orchestrator import playlist_music_request

    req = playlist_music_request(
        SimpleNamespace(
            prompt="night drive",
            metadata={"vendor": "minimax", "vendor_id": "abc", "vendor_key_prefix": "sk-xxx"},
            model="music-1.5",
            task_id="tid",
        ),
        seed=7,
        extra={
            "is_instrumental": True,
            "model": "should-not-win",
            "vendor": "mureka",
            "bpm_range": [80, 120],
        },
    )
    assert req["prompt"] == "night drive"
    assert req["seed"] == 7
    assert req["vendor_id"] == "abc"
    assert req["is_instrumental"] is True
    assert req["bpm_range"] == [80, 120]
    assert "vendor" not in req
    assert "model" not in req
    assert "vendor_key_prefix" not in req
    assert "task_id" not in req


def test_public_music_request_strips_vendor():
    from app.services.provenance import _public_music_request, collect_human_edits

    public = _public_music_request(
        {
            "prompt": "night drive",
            "vendor": "minimax",
            "vendor_id": "abc",
            "vendor_key_prefix": "sk-xxx",
            "bpm": 100,
        }
    )
    assert public == {"prompt": "night drive", "bpm": 100}
    edits = collect_human_edits(
        [{"human_edits": [{"kind": "section", "section": "chorus", "vendor": "minimax", "at": "t"}]}]
    )
    assert edits[0]["section"] == "chorus"
    assert "vendor" not in edits[0]

    from app.services.provenance import sanitize_lineage_for_client

    cleaned = sanitize_lineage_for_client(
        [{"music_request": {"prompt": "x", "vendor_id": "abc", "m3_request": {"raw": 1}}, "pipeline_version": "1"}]
    )
    assert cleaned[0]["music_request"] == {"prompt": "x"}
    assert "vendor_id" not in cleaned[0]["music_request"]
    assert cleaned[0]["pipeline_version"] == "1"


def test_sections_from_lyrics_fallback():
    sections = sections_from_lyrics("", 90)
    assert [row["id"] for row in sections] == ["verse", "chorus", "bridge"]
