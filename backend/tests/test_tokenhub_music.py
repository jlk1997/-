import pytest

from app.core.lyrics_structure import lyrics_body_length
from app.integrations.tokenhub.music import build_music_payload, parse_generation_body
from app.integrations.vendors.errors import (
    FAIL,
    RETRY_SAME,
    SWITCH,
    MusicProviderError,
    cooldown_for,
    provider_failure_policy,
)


def _setting(**overrides):
    base = {
        "model": "minimax-music-v3.0",
        "prompt": "独立民谣, 忧郁",
        "lyrics": None,
        "is_instrumental": False,
        "lyrics_optimizer": False,
        "output_format": "url",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        "aigc_watermark": False,
    }
    base.update(overrides)
    return base


def test_custom_lyrics_payload_keeps_structure_tags():
    lyrics = "[verse]\n街灯\n[chorus]\n木门"
    payload, mode = build_music_payload(**_setting(lyrics=lyrics))
    assert mode == "lyrics"
    assert payload["lyrics"].startswith("[Verse]")
    assert "[Chorus]" in payload["lyrics"]
    assert payload["lyrics_optimizer"] is False
    assert payload["model"] == "minimax-music-v3.0"


def test_structure_tags_do_not_count_toward_3500():
    lyrics = "[Verse]\n" + ("啊" * 3500)
    assert lyrics_body_length(lyrics) == 3500
    payload, mode = build_music_payload(**_setting(lyrics=lyrics))
    assert mode == "lyrics"
    assert "lyrics" in payload


def test_lyrics_over_limit_is_params():
    with pytest.raises(MusicProviderError) as caught:
        build_music_payload(**_setting(lyrics="啊" * 3501))
    assert caught.value.kind == "params"


def test_auto_lyrics_and_instrumental_modes():
    auto, auto_mode = build_music_payload(**_setting(lyrics_optimizer=True))
    assert auto_mode == "auto_lyrics"
    assert auto["lyrics_optimizer"] is True
    assert "lyrics" not in auto

    inst, inst_mode = build_music_payload(**_setting(is_instrumental=True, lyrics_optimizer=True))
    assert inst_mode == "instrumental"
    assert inst["is_instrumental"] is True
    assert inst["lyrics_optimizer"] is False


def test_vocal_without_lyrics_or_optimizer_is_params():
    with pytest.raises(MusicProviderError) as caught:
        build_music_payload(**_setting())
    assert caught.value.kind == "params"


def test_instrumental_requires_prompt():
    with pytest.raises(MusicProviderError) as caught:
        build_music_payload(**_setting(is_instrumental=True, prompt="  "))
    assert caught.value.kind == "params"


def test_parse_url_and_error_body():
    parsed = parse_generation_body(
        {
            "data": {"audio": "https://cdn.example/song.mp3", "status": 2},
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "trace_id": "trace-1",
            "request_id": "req-1",
            "usage": {"total_tokens": 12},
            "extra_info": {"music_duration": 180000, "music_sample_rate": 44100},
        }
    )
    assert parsed["audio_kind"] == "url"
    assert parsed["trace_id"] == "trace-1"
    assert parsed["usage"]["total_tokens"] == 12

    with pytest.raises(MusicProviderError) as caught:
        parse_generation_body(
            {
                "base_resp": {"status_code": 1026, "status_msg": "moderation"},
                "trace_id": "trace-2",
            }
        )
    assert caught.value.kind == "moderation"
    assert caught.value.trace_id == "trace-2"


def test_parse_hex_audio():
    parsed = parse_generation_body(
        {
            "data": {"audio": "fffb", "status": 2},
            "base_resp": {"status_code": 0},
            "trace_id": "hex-1",
        }
    )
    assert parsed["audio_kind"] == "hex"
    assert bytes.fromhex(parsed["audio"]) == b"\xff\xfb"


def test_failure_policy_and_cooldown():
    params = MusicProviderError("bad", kind="params", user_message="bad")
    moderation = MusicProviderError("no", kind="moderation", user_message="no")
    auth = MusicProviderError("key", kind="auth", user_message="key")
    limited = MusicProviderError("slow", kind="rate_limit", user_message="slow")
    server = MusicProviderError("down", kind="server", retryable=True, user_message="down")
    assert provider_failure_policy(params, attempts_on_vendor=1) == FAIL
    assert provider_failure_policy(moderation, attempts_on_vendor=1) == FAIL
    assert provider_failure_policy(auth, attempts_on_vendor=1) == SWITCH
    assert provider_failure_policy(limited, attempts_on_vendor=1) == SWITCH
    assert provider_failure_policy(server, attempts_on_vendor=1) == RETRY_SAME
    assert provider_failure_policy(server, attempts_on_vendor=2) == SWITCH
    assert cooldown_for(auth) == 1800
    assert cooldown_for(limited) == 120
    assert cooldown_for(server) == 60


def test_dispatch_includes_tokenhub():
    from app.integrations.vendors.router import MUSIC_DISPATCH

    assert "tokenhub" in MUSIC_DISPATCH
    assert "suno" not in MUSIC_DISPATCH
