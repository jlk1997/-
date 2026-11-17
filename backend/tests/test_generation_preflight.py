import pytest

from app.core.lyrics_structure import strip_structure_tags, template_lyrics
from app.services.generation_preflight import GenerationPreflightError, preflight_music_request
from app.services.provider_checkpoint import call_expired, reusable


def test_preflight_rejects_vocal_without_lyrics():
    with pytest.raises(GenerationPreflightError):
        preflight_music_request(instrumental=False, lyrics="", lyrics_optimizer=False)


def test_preflight_allows_ai_lyrics_before_the_lyric_step():
    preflight_music_request(mode="auto_lyrics", instrumental=False, lyrics="", lyrics_optimizer=False, text_intent="雨夜")
    preflight_music_request(mode="instrumental", instrumental=True, lyrics="", text_intent="钢琴")
    preflight_music_request(instrumental=False, lyrics="", lyrics_optimizer=True, prompt="雨夜")
    lyrics = "[Intro]\n" + ("海" * 3500) + "\n[Outro]"
    preflight_music_request(instrumental=False, lyrics=lyrics, prompt="民谣")


def test_preflight_rejects_prompt_and_body_overflow():
    with pytest.raises(GenerationPreflightError):
        preflight_music_request(prompt="字" * 2001, instrumental=True)
    with pytest.raises(GenerationPreflightError):
        preflight_music_request(instrumental=False, lyrics="字" * 3501)


def test_strip_tags_for_release_and_template():
    assert strip_structure_tags("[Verse]\n街灯\n[Chorus]\n木门") == "街灯\n木门"
    assert "[Intro]" in template_lyrics("short")
    assert "[Solo]" in template_lyrics("full")


def test_checkpoint_reuse_respects_expiry():
    assert reusable({"state": "stored", "storage_key": "works/a.mp3"})
    assert reusable({"state": "ready", "audio_url": "https://cdn.example/a.mp3", "expires_at": "2999-01-01T00:00:00"})
    assert not reusable({"state": "ready", "audio_url": "https://cdn.example/a.mp3", "expires_at": "2000-01-01T00:00:00"})
    assert call_expired({"expires_at": "2000-01-01T00:00:00"})
    assert not call_expired({"expires_at": "2999-01-01T00:00:00"})
