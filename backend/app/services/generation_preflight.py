"""Reject a music request before credits are charged."""

from __future__ import annotations

from app.core.lyrics_structure import LYRICS_BODY_LIMIT, PROMPT_LIMIT, lyrics_body_length


class GenerationPreflightError(ValueError):
    pass


def preflight_music_request(
    *,
    lyrics: str | None = None,
    instrumental: bool = True,
    lyrics_optimizer: bool | None = None,
    prompt: str | None = None,
    text_intent: str | None = None,
    mode: str | None = None,
) -> None:
    for text in (prompt, text_intent):
        if text and len(text.strip()) > PROMPT_LIMIT:
            raise GenerationPreflightError("音乐描述不能超过 2000 字")
    lyric_text = lyrics or ""
    if lyric_text and lyrics_body_length(lyric_text) > LYRICS_BODY_LIMIT:
        raise GenerationPreflightError("歌词正文不能超过 3500 字，结构标签不计入")
    song_mode = (mode or "").strip()
    if song_mode == "auto_lyrics" or lyrics_optimizer:
        return
    if song_mode == "instrumental" or instrumental:
        return
    has_lyrics = bool(lyric_text.strip()) and lyrics_body_length(lyric_text) > 0
    if not has_lyrics:
        raise GenerationPreflightError("有人声的歌需要歌词，或改成 AI 写词")
