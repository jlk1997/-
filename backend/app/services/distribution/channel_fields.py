"""Per-channel release fields.

The form collects the union. Each store only requires its own subset.
Ops must still check the live upload page before a group is treated as verified.
"""

from __future__ import annotations

from typing import Any

FIELD_CATALOG: dict[str, str] = {
    "title": "歌名",
    "artist_name": "主艺人",
    "featured_artists": "合作艺人",
    "cover_url": "封面",
    "lyrics": "歌词",
    "lyrics_lrc": "带时间的歌词",
    "instrumental": "纯音乐",
    "language": "语种",
    "genres": "流派",
    "lyricist": "作词",
    "composer": "作曲",
    "arranger": "编曲",
    "producer": "制作人",
    "ai_disclosed": "AI 说明",
    "explicit": "内容分级",
    "copyright_line": "词曲版权行",
    "sound_recording_line": "录音版权行",
    "label_name": "厂牌名",
    "isrc": "ISRC",
    "upc": "UPC",
    "release_date": "发行日期",
    "territories": "发行地区",
    "price_minor": "售价",
}

CN_CORE = (
    "title",
    "artist_name",
    "cover_url",
    "lyrics",
    "language",
    "genres",
    "lyricist",
    "composer",
    "ai_disclosed",
)
SHORT_VIDEO = ("title", "artist_name", "cover_url", "ai_disclosed")
GLOBAL_DSP = (
    "title",
    "artist_name",
    "cover_url",
    "language",
    "genres",
    "lyricist",
    "composer",
    "explicit",
    "release_date",
    "copyright_line",
    "sound_recording_line",
    "upc",
    "ai_disclosed",
)
INDEPENDENT = ("title", "artist_name", "cover_url", "genres", "ai_disclosed")

# Draft until ops checks the live upload form. Do not hard-block release on this yet.
CHANNEL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "netease": CN_CORE,
    "kuwo": CN_CORE,
    "bilibili": CN_CORE,
    "qq_music": CN_CORE,
    "kugou": CN_CORE,
    "qishui": CN_CORE,
    "wechat_channels": SHORT_VIDEO,
    "douyin_musician": SHORT_VIDEO,
    "kuaishou_musician": SHORT_VIDEO,
    "spotify": GLOBAL_DSP,
    "apple_music": GLOBAL_DSP,
    "youtube_music": GLOBAL_DSP,
    "tiktok_music": GLOBAL_DSP,
    "amazon_music": GLOBAL_DSP,
    "deezer": GLOBAL_DSP,
    "soundcloud": INDEPENDENT,
    "bandcamp": (*INDEPENDENT, "price_minor"),
}

FIELD_STATUS = "draft_needs_ops_check"


def required_fields_for(channels: list[str] | None) -> list[str]:
    seen: list[str] = []
    for code in channels or []:
        for field in CHANNEL_REQUIRED_FIELDS.get(code, CN_CORE):
            if field not in seen:
                seen.append(field)
    return seen


def editable_fields(channels: list[str] | None) -> list[str]:
    """Fields the release form should ask for, besides title, artist, cover and the AI checkbox."""
    skip = {"title", "artist_name", "cover_url", "ai_disclosed", "isrc"}
    return [field for field in required_fields_for(channels) if field not in skip]


def handoff_lines(meta: Any, channels: list[str] | None) -> list[dict[str, Any]]:
    """The sheet the creator confirms and ops uploads from. One list, same labels."""
    fields: list[str] = []
    for field in ("title", "artist_name", "isrc", "cover_url", "ai_disclosed", *editable_fields(channels)):
        if field not in fields:
            fields.append(field)
    lines: list[dict[str, Any]] = []
    instrumental = metadata_value(meta, "instrumental") is True
    for field in fields:
        value = metadata_value(meta, field)
        if field == "ai_disclosed":
            shown = "已说明" if value else ""
            filled = bool(value)
        elif field == "lyrics" and instrumental:
            shown = "纯音乐"
            filled = True
        elif isinstance(value, list):
            shown = "，".join(str(item) for item in value if item)
            filled = _present(value)
        else:
            shown = "" if value is None else str(value)
            filled = _present(value)
        lines.append(
            {
                "field": field,
                "label": FIELD_CATALOG.get(field, field),
                "value": shown,
                "filled": filled,
            }
        )
    return lines


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def listing_from_metadata(meta: Any) -> dict[str, Any]:
    extra = getattr(meta, "extra", None) if meta is not None else None
    listing = extra.get("listing") if isinstance(extra, dict) else None
    return dict(listing) if isinstance(listing, dict) else {}


def metadata_value(meta: Any, field: str) -> Any:
    if meta is None:
        return None
    if field in {"title", "artist_name", "lyrics", "isrc", "upc", "language", "genres", "cover_url", "ai_disclosed"}:
        return getattr(meta, field, None)
    return listing_from_metadata(meta).get(field)


def missing_release_fields(meta: Any, channels: list[str] | None) -> list[dict[str, str]]:
    gaps = []
    for field in required_fields_for(channels):
        if field == "lyrics" and metadata_value(meta, "instrumental") is True:
            continue
        if not _present(metadata_value(meta, field)):
            gaps.append({"field": field, "label": FIELD_CATALOG.get(field, field)})
    return gaps


COLUMN_FIELDS = (
    "title",
    "artist_name",
    "lyrics",
    "isrc",
    "upc",
    "language",
    "genres",
    "cover_url",
    "ai_disclosed",
)

LISTING_KEYS = tuple(key for key in FIELD_CATALOG if key not in COLUMN_FIELDS)


def apply_listing_payload(meta: Any, payload: dict | None) -> None:
    """Store extended store-form fields on ReleaseMetadata.extra['listing']."""
    if meta is None or not isinstance(payload, dict):
        return
    extra = dict(getattr(meta, "extra", None) or {})
    listing = dict(extra.get("listing") or {}) if isinstance(extra.get("listing"), dict) else {}
    for key in LISTING_KEYS:
        if key in payload:
            listing[key] = payload[key]
    extra["listing"] = listing
    meta.extra = extra


def paste_sheet(lines: list[dict[str, Any]]) -> str:
    """One block ops can paste into a store form."""
    return "\n".join(f"{line.get('label') or line.get('field')}：{line.get('value') or '（空）'}" for line in lines)
