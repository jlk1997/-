"""Song-structure tags shared by generation, the lyrics editor, and release kits.

TokenHub counts lyric characters after structure tags are removed. Tags are a
guide for the model, not part of the sung lyric, and they must not be shipped
in store lyrics.
"""

from __future__ import annotations

import re

# Canonical labels. Order matches the TokenHub music document.
STRUCTURE_TAGS: tuple[str, ...] = (
    "Intro",
    "Verse",
    "Pre Chorus",
    "Chorus",
    "Interlude",
    "Bridge",
    "Outro",
    "Post Chorus",
    "Transition",
    "Break",
    "Hook",
    "Build Up",
    "Inst",
    "Solo",
)

_CANONICAL = {tag.lower(): tag for tag in STRUCTURE_TAGS}

# Common spellings the editor and older prompts may produce.
_ALIASES = {
    "prechorus": "pre chorus",
    "pre-chorus": "pre chorus",
    "postchorus": "post chorus",
    "post-chorus": "post chorus",
    "buildup": "build up",
    "build-up": "build up",
    "verse1": "verse",
    "verse2": "verse",
    "verse 1": "verse",
    "verse 2": "verse",
    "chorus1": "chorus",
    "chorus 1": "chorus",
    "hook1": "hook",
}

_TAG_RE = re.compile(r"\[([^\]\n]+)\]")

# Rough listening length. The model has no duration parameter; the template only guides form.
STRUCTURE_TEMPLATES: dict[str, list[str]] = {
    "short": ["Intro", "Verse", "Chorus", "Outro"],
    "standard": ["Intro", "Verse", "Pre Chorus", "Chorus", "Verse", "Chorus", "Bridge", "Chorus", "Outro"],
    "full": [
        "Intro",
        "Verse",
        "Pre Chorus",
        "Chorus",
        "Verse",
        "Pre Chorus",
        "Chorus",
        "Bridge",
        "Chorus",
        "Solo",
        "Chorus",
        "Outro",
    ],
    "instrumental": ["Intro", "Build Up", "Hook", "Break", "Hook", "Outro"],
}

TEMPLATE_MINUTES: dict[str, int] = {
    "short": 1,
    "standard": 3,
    "full": 4,
    "instrumental": 2,
}

LYRICS_BODY_LIMIT = 3500
PROMPT_LIMIT = 2000


def canonical_label(label: str) -> str | None:
    key = re.sub(r"\s+", " ", (label or "").strip().lower())
    key = _ALIASES.get(key, key)
    key = _ALIASES.get(key.replace(" ", ""), key)
    found = _CANONICAL.get(key)
    return found


def is_structure_tag(label: str) -> bool:
    return canonical_label(label) is not None


def format_tag(label: str) -> str | None:
    canon = canonical_label(label)
    if not canon:
        return None
    return f"[{canon}]"


def _replace_tag(match: re.Match[str], *, strip: bool) -> str:
    canon = canonical_label(match.group(1))
    if canon is None:
        return match.group(0)
    if strip:
        return ""
    return f"[{canon}]"


def normalize_lyrics(lyrics: str) -> str:
    """Rewrite known tags to canonical spelling. Leave sung text unchanged."""
    text = lyrics or ""
    return _TAG_RE.sub(lambda match: _replace_tag(match, strip=False), text)


def lyrics_body_text(lyrics: str) -> str:
    text = _TAG_RE.sub(lambda match: _replace_tag(match, strip=True), lyrics or "")
    return text.strip()


def lyrics_body_length(lyrics: str) -> int:
    return len(lyrics_body_text(lyrics))


def contains_structure_tags(lyrics: str) -> bool:
    return any(is_structure_tag(match.group(1)) for match in _TAG_RE.finditer(lyrics or ""))


def strip_structure_tags(lyrics: str) -> str:
    """Lyric text for store listings. Structure tags are not sung words."""
    lines: list[str] = []
    for raw in (lyrics or "").splitlines():
        cleaned = _TAG_RE.sub(lambda match: _replace_tag(match, strip=True), raw).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def template_lyrics(name: str) -> str:
    tags = STRUCTURE_TEMPLATES.get(name) or STRUCTURE_TEMPLATES["standard"]
    return "\n".join(f"[{tag}]\n" for tag in tags).strip() + "\n"
