"""Per-channel release asset profiles.

Stores list a mixed stereo master. Stems and accompaniment are originality
evidence for CN musician portals — never extra DistroKid tracks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DSP_GLOBAL = frozenset(
    {
        "spotify",
        "apple_music",
        "youtube_music",
        "tiktok_music",
        "amazon_music",
        "deezer",
        "soundcloud",
        "bandcamp",
    }
)
CN_CATALOG = frozenset({"netease", "qq_music", "kugou", "kuwo", "qishui", "bilibili"})
CN_TME_ONBOARD = frozenset({"qq_music", "kugou"})
SHORT_VIDEO = frozenset({"wechat_channels", "douyin_musician", "kuaishou_musician"})
REVIEW_STEMS_QUALITY = "demucs"


@dataclass(frozen=True)
class ChannelAssetProfile:
    channel_code: str
    group: str
    needs_master: bool = True
    needs_stems_evidence: bool = False
    needs_instrumental: bool = False
    needs_clips: bool = False


def _profile(code: str) -> ChannelAssetProfile:
    if code in SHORT_VIDEO:
        return ChannelAssetProfile(
            channel_code=code,
            group="short_video",
            needs_master=True,
            needs_clips=True,
        )
    if code in CN_TME_ONBOARD:
        return ChannelAssetProfile(
            channel_code=code,
            group="cn_tme_onboard",
            needs_stems_evidence=True,
            needs_instrumental=True,
        )
    if code == "qishui":
        return ChannelAssetProfile(
            channel_code=code,
            group="cn_catalog",
            needs_stems_evidence=True,
            needs_clips=True,
        )
    if code in CN_CATALOG:
        return ChannelAssetProfile(
            channel_code=code,
            group="cn_catalog",
            needs_stems_evidence=True,
        )
    if code in DSP_GLOBAL:
        return ChannelAssetProfile(channel_code=code, group="dsp_global")
    return ChannelAssetProfile(channel_code=code, group="dsp_global")


CHANNEL_ASSET_PROFILES: dict[str, ChannelAssetProfile] = {
    code: _profile(code)
    for code in (
        *DSP_GLOBAL,
        *CN_CATALOG,
        *SHORT_VIDEO,
    )
}


def profile_for(channel_code: str | None) -> ChannelAssetProfile:
    code = (channel_code or "").strip()
    return CHANNEL_ASSET_PROFILES.get(code) or _profile(code)


def profile_payload(channel_code: str | None) -> dict:
    return asdict(profile_for(channel_code))


def aggregate_needs(channel_codes: list[str] | None) -> dict:
    codes = [str(c) for c in (channel_codes or []) if c]
    needs_master = True
    needs_stems_evidence = False
    needs_instrumental = False
    needs_clips = False
    groups: list[str] = []
    for code in codes:
        profile = profile_for(code)
        needs_master = needs_master or profile.needs_master
        needs_stems_evidence = needs_stems_evidence or profile.needs_stems_evidence
        needs_instrumental = needs_instrumental or profile.needs_instrumental
        needs_clips = needs_clips or profile.needs_clips
        if profile.group not in groups:
            groups.append(profile.group)
    return {
        "needs_master": needs_master,
        "needs_stems_evidence": needs_stems_evidence,
        "needs_instrumental": needs_instrumental,
        "needs_clips": needs_clips,
        "groups": groups,
        "channels": codes,
    }


def stems_meta(work) -> dict:
    pps = getattr(work, "post_process_status", None) or {}
    raw = pps.get("stems") if isinstance(pps, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def stems_quality(work) -> str | None:
    quality = str(stems_meta(work).get("quality") or "").strip().lower()
    return quality or None


def review_stems_ready(work) -> bool:
    if stems_quality(work) != REVIEW_STEMS_QUALITY:
        return False
    meta = stems_meta(work)
    return bool(meta.get("originality_zip_key") or meta.get("originality_zip_url"))


def listing_master_ref(work) -> dict:
    """Listing SKU is the persisted 44.1kHz WAV. Mix URL is only a fallback for players."""
    pps = getattr(work, "post_process_status", None) or {}
    master = pps.get("master") if isinstance(pps, dict) else None
    master = master if isinstance(master, dict) else {}
    wav_key = master.get("key")
    wav_url = master.get("url")
    audio_url = wav_url or getattr(work, "audio_url", None)
    storage_key = wav_key or getattr(work, "storage_key", None)
    return {
        "wav_key": wav_key,
        "wav_url": wav_url,
        "storage_key": storage_key,
        "audio_url": audio_url,
        "ready": bool(wav_key),
    }


def clips_pack_ref(work) -> dict:
    pps = getattr(work, "post_process_status", None) or {}
    raw = pps.get("clips") if isinstance(pps, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    key = raw.get("clip_pack_key")
    url = raw.get("clip_pack_url")
    return {
        "key": key,
        "url": url,
        "clip_windows": raw.get("clip_windows") or [],
        "ready": bool(key),
    }


def clips_ready(work) -> bool:
    return bool(clips_pack_ref(work).get("ready"))


def instrumental_sku_ref(work) -> dict:
    pps = getattr(work, "post_process_status", None) or {}
    if not isinstance(pps, dict):
        return {"ready": False}
    if str(pps.get("sku_kind") or "") == "instrumental":
        return {"ready": True, "work_id": str(getattr(work, "id", "") or ""), "self": True}
    raw = pps.get("instrumental_sku")
    if isinstance(raw, dict) and raw.get("work_id"):
        return {"ready": True, "work_id": str(raw.get("work_id")), "title": raw.get("title"), "self": False}
    return {"ready": False}


def cn_originality_qc_note(work, channel_codes: list[str] | None = None) -> dict:
    """CN stems are evidence — they must never fail DistroKid / global QC."""
    needs = aggregate_needs(channel_codes)
    needed = bool(needs.get("needs_stems_evidence"))
    return {
        "needed": needed,
        "ready": review_stems_ready(work) if needed else True,
        "blocks_qc": False,
        "note": "国内审核分轨不阻塞全球 DSP 质检",
    }


def sku_gap_for_channel(work, channel_code: str | None) -> str | None:
    """Return the first SKU lamp that blocks Suggested Ship for this store."""
    profile = profile_for(channel_code)
    if profile.needs_master and not listing_master_ref(work).get("wav_key"):
        return "master"
    if profile.needs_stems_evidence and not review_stems_ready(work):
        return "evidence"
    if profile.needs_clips and not clips_ready(work):
        return "clips"
    if profile.needs_instrumental and not instrumental_sku_ref(work).get("ready"):
        return "instrumental"
    return None


def release_asset_status(work, channel_codes: list[str] | None = None) -> dict:
    needs = aggregate_needs(channel_codes)
    quality = stems_quality(work)
    listing = listing_master_ref(work)
    evidence_ready = review_stems_ready(work)
    evidence_needed = bool(needs["needs_stems_evidence"])
    clips = clips_pack_ref(work)
    inst = instrumental_sku_ref(work)
    inst_needed = bool(needs["needs_instrumental"])
    sku_kind = ""
    pps = getattr(work, "post_process_status", None) or {}
    if isinstance(pps, dict):
        sku_kind = str(pps.get("sku_kind") or "")
    codes = [str(c) for c in (channel_codes or []) if c]
    return {
        "listing": {
            "kind": "master",
            "ready": bool(listing.get("wav_key")),
            "label": "上架文件：母带",
            "wav": bool(listing.get("wav_key")),
        },
        "evidence": {
            "kind": "originality",
            "needed": evidence_needed,
            "ready": evidence_ready,
            "quality": quality or "none",
            "label": "审核材料：分轨包" if evidence_ready else "审核材料：未就绪",
        },
        "clips": {
            "kind": "clips",
            "needed": bool(needs["needs_clips"]),
            "ready": bool(clips.get("ready")),
            "key": clips.get("key"),
        },
        "instrumental": {
            "kind": "instrumental_sku",
            "needed": inst_needed,
            "ready": bool(inst.get("ready")),
            "work_id": inst.get("work_id"),
            "title": inst.get("title"),
            "self": bool(inst.get("self")),
            "can_spawn": sku_kind != "instrumental" and not inst.get("ready") and evidence_ready,
        },
        "needs_ai_musician": "netease" in codes,
        "needs": needs,
    }
