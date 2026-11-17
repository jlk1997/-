from app.core.music_prompt_builder import MusicCreativeSpec, build_minimax_prompt
from app.services.generation_contract import audio_setting_for_quality, resolve_freedom, resolve_mode


def test_legacy_fields_map_to_modes():
    assert resolve_mode({"instrumental": True}) == "instrumental"
    assert resolve_mode({"instrumental": False, "lyrics": "[Verse]\n海"}) == "lyrics"
    assert resolve_mode({"lyrics_optimizer": True, "instrumental": False}) == "auto_lyrics"
    assert resolve_mode({"mode": "instrumental", "lyrics": "ignored by explicit mode"}) == "instrumental"
    assert resolve_freedom({}) == "balanced"
    assert resolve_freedom({"freedom": "literal"}) == "literal"


def test_literal_freedom_keeps_the_recipe():
    import asyncio

    from app.services.generation_contract import prepare_generation_inputs

    spec = MusicCreativeSpec(instruments=["piano"], text_intent="雨夜")
    prepared = asyncio.run(
        prepare_generation_inputs(
            {"mode": "lyrics", "freedom": "literal", "text_intent": "雨夜", "lyrics": "[Verse]\n海"},
            spec,
            db=None,
            user_id=None,
        )
    )
    assert prepared["spec"].instruments == ["piano"]
    assert not prepared["spec"].custom_prompt_override
    assert "海" in (prepared["lyrics"] or "")
    prompt = build_minimax_prompt(
        MusicCreativeSpec(vocal_gender="female", vocal_style="breathy", language="zh", text_intent="雨夜")
    )
    assert "female vocal" in prompt
    assert "breathy vocal" in prompt
    assert "Mandarin lyrics" in prompt


def test_master_quality_stays_mp3_until_wav_is_enabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "tokenhub_wav_enabled", False)
    assert audio_setting_for_quality("master")["format"] == "mp3"
    assert audio_setting_for_quality("master")["bitrate"] == 320000
    assert audio_setting_for_quality("standard")["bitrate"] == settings.minimax_music_bitrate
    monkeypatch.setattr(settings, "tokenhub_wav_enabled", True)
    assert audio_setting_for_quality("master")["format"] == "wav"


def test_platform_payload_has_limits_without_vendor_names(monkeypatch):
    from app.api.routes import config as config_routes

    monkeypatch.setattr(config_routes, "cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(config_routes, "cache_set", lambda *_a, **_k: None)
    import json

    payload = json.loads(config_routes.platform_info(user=None).body)
    studio = payload["studio"]
    assert studio["max_prompt_length"] == 2000
    assert studio["max_lyrics_length"] == 3500
    assert "Verse" in studio["structure_tags"]
    assert studio["default_freedom"] == "balanced"
    assert "minimax" not in json.dumps(payload).lower()
    assert "tokenhub" not in json.dumps(payload).lower()
