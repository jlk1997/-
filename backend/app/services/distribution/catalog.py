from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.models.schemas import CommissionRule, DistributionChannel

CN_AGGREGATORS = ["cn_label"]
GLOBAL_AGGREGATORS = ["distrokid", "tunecore", "routenote"]

# Honest per-store automation. Connector-first. Partner APIs are a sidecar only.
CONNECTOR_FULL_CHANNELS = (
    "netease",
    "qq_music",
    "kugou",
    "kuwo",
    "qishui",
    "bilibili",
    "douyin_musician",
    "kuaishou_musician",
    "wechat_channels",
    "soundcloud",
    "bandcamp",
)
CONNECTOR_ASSIST_CHANNELS = ("youtube_music",)
METRICS_ONLY_CHANNELS = ("spotify", "apple_music", "amazon_music", "deezer", "tiktok_music")


def _automation_level_for(code: str) -> str:
    if code in CONNECTOR_FULL_CHANNELS:
        return "connector_full"
    if code in CONNECTOR_ASSIST_CHANNELS:
        return "connector_assist"
    if code in METRICS_ONLY_CHANNELS:
        return "metrics_only"
    return "ops_only"


CHANNEL_SPECS: list[dict] = [
    {"code": "netease", "name": "网易云音乐", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 10},
    {"code": "qq_music", "name": "QQ 音乐", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 20},
    {"code": "kugou", "name": "酷狗音乐", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 30},
    {"code": "kuwo", "name": "酷我音乐", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 40},
    {"code": "qishui", "name": "汽水音乐", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 50},
    {"code": "bilibili", "name": "B 站音频", "region": "cn", "distributor_code": "cn_label", "delivery_mode": "aggregator", "aggregators": CN_AGGREGATORS, "automation_level": "connector_full", "sort_order": 60},
    {"code": "spotify", "name": "Spotify", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "metrics_only", "sort_order": 70},
    {"code": "youtube_music", "name": "YouTube Music", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "connector_assist", "sort_order": 80},
    {"code": "douyin_musician", "name": "抖音音乐人", "region": "cn", "distributor_code": "session", "delivery_mode": "session_assist", "aggregators": [], "automation_level": "connector_full", "sort_order": 90},
    {"code": "kuaishou_musician", "name": "快手音乐人", "region": "cn", "distributor_code": "session", "delivery_mode": "session_assist", "aggregators": [], "automation_level": "connector_full", "sort_order": 100},
    {"code": "wechat_channels", "name": "微信视频号", "region": "cn", "distributor_code": "session", "delivery_mode": "session_assist", "aggregators": [], "automation_level": "connector_full", "sort_order": 110},
    {"code": "apple_music", "name": "Apple Music", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "metrics_only", "sort_order": 120},
    {"code": "tiktok_music", "name": "TikTok Music", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "metrics_only", "sort_order": 130},
    {"code": "amazon_music", "name": "Amazon Music", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "metrics_only", "sort_order": 140},
    {"code": "deezer", "name": "Deezer", "region": "global", "distributor_code": "distrokid", "delivery_mode": "aggregator", "aggregators": GLOBAL_AGGREGATORS, "automation_level": "metrics_only", "sort_order": 150},
    {"code": "soundcloud", "name": "SoundCloud", "region": "global", "distributor_code": "session", "delivery_mode": "session_assist", "aggregators": [], "automation_level": "connector_full", "sort_order": 160},
    {"code": "bandcamp", "name": "Bandcamp", "region": "global", "distributor_code": "session", "delivery_mode": "session_assist", "aggregators": [], "automation_level": "connector_full", "sort_order": 170},
]

AGGREGATOR_DIRECTORY = [
    {"code": "distrokid", "name": "DistroKid", "region": "global"},
    {"code": "tunecore", "name": "TuneCore", "region": "global"},
    {"code": "routenote", "name": "RouteNote", "region": "global"},
    {"code": "cn_label", "name": "国内厂牌聚合", "region": "cn"},
]
# Global and CN aggregators are separate pipes. Never pretend one API covers both.

CHANNEL_NAMES = {spec["code"]: spec["name"] for spec in CHANNEL_SPECS}
CHANNEL_NAMES.update({"sync_desk": "同步授权柜台", "embed_player": "嵌入播放器", "vibe_radio": "比特音电台"})

CHANNEL_UPLOAD_FORMS = {
    "netease": "https://music.163.com/st/musician/upload",
    "qq_music": "https://y.qq.com/portal/publish.html",
    "kuwo": "https://kuwo.cn/musician/upload",
    "qishui": "https://musician.douyin.com/upload",
    "bilibili": "https://member.bilibili.com/platform/upload/audio/home",
    "soundcloud": "https://soundcloud.com/upload",
}

CHANNEL_PORTALS = {
    "netease": "https://music.163.com/st/musician",
    "qq_music": "https://y.qq.com/portal/",
    "kugou": "https://www.kugou.com/musician/",
    "kuwo": "https://www.kuwo.cn/musician",
    "qishui": "https://music.douyin.com/",
    "bilibili": "https://member.bilibili.com/",
    "spotify": "https://artists.spotify.com/",
    "apple_music": "https://artists.apple.com/",
    "youtube_music": "https://studio.youtube.com/",
    "tiktok_music": "https://www.tiktok.com/studio",
    "amazon_music": "https://artists.amazon.com/",
    "deezer": "https://www.deezer.com/",
    "wechat_channels": "https://channels.weixin.qq.com/",
    "douyin_musician": "https://creator.douyin.com/",
    "kuaishou_musician": "https://cp.kuaishou.com/",
    "soundcloud": "https://soundcloud.com/upload",
    "bandcamp": "https://bandcamp.com/",
}

# Official portal + consumer live hosts. Connector matches the full hostname, never the first label.
CHANNEL_HOSTS: dict[str, list[str]] = {
    "netease": ["music.163.com"],
    "qq_music": ["y.qq.com", "music.qq.com"],
    "kugou": ["kugou.com"],
    "kuwo": ["kuwo.cn"],
    "qishui": ["music.douyin.com", "musician.douyin.com"],
    "bilibili": ["bilibili.com", "member.bilibili.com"],
    "spotify": ["artists.spotify.com", "open.spotify.com"],
    "apple_music": ["artists.apple.com", "music.apple.com"],
    "youtube_music": ["studio.youtube.com", "youtube.com", "youtu.be", "music.youtube.com"],
    "tiktok_music": ["tiktok.com"],
    "amazon_music": ["music.amazon.com", "artists.amazon.com", "artists.amazonmusic.com"],
    "deezer": ["deezer.com"],
    "wechat_channels": ["channels.weixin.qq.com"],
    "douyin_musician": ["douyin.com", "creator.douyin.com"],
    "kuaishou_musician": ["kuaishou.com"],
    "soundcloud": ["soundcloud.com"],
    "bandcamp": ["bandcamp.com"],
}

STORE_ID_PATTERNS: list[tuple[str, str]] = [
    (r"open\.spotify\.com/(?:intl-[a-z]+/)?track/([A-Za-z0-9]+)", "spotify"),
    (r"music\.163\.com/(?:#/)?song\?id=(\d+)", "netease"),
    (r"music\.163\.com/song/(\d+)", "netease"),
    (r"y\.qq\.com/.*/songDetail/([A-Za-z0-9]+)", "qq_music"),
    (r"(?:www\.)?bilibili\.com/video/(BV[\w]+)", "bilibili"),
    (r"(?:www\.)?bilibili\.com/audio/au(\d+)", "bilibili"),
    (r"youtu\.be/([\w-]{6,})", "youtube_music"),
    (r"(?:www\.)?(?:music\.)?youtube\.com/watch\?v=([\w-]{6,})", "youtube_music"),
    (r"music\.apple\.com/.+/(?:id)?(\d+)", "apple_music"),
    (r"tiktok\.com/music/.+-(\d+)", "tiktok_music"),
    (r"soundcloud\.com/(?!you|pages|upload|discover|search|stream|library|sets|charts)([^/?#]+)/(?!sets|likes|reposts|followers)([^/?#]+)", "soundcloud"),
    (r"(?:www\.)?deezer\.com/.*/track/(\d+)", "deezer"),
    (r"kugou\.com/.+[?&]hash=([A-Fa-f0-9]+)", "kugou"),
    (r"kuwo\.cn/.+?(\d{5,})", "kuwo"),
    (r"music\.amazon\.[^/]+/albums/([A-Z0-9]+)", "amazon_music"),
]

# Portal-only extras: deep links + clip SOP. Not DSP settlement channels.
PORTAL_CHANNELS: list[dict] = [
    {
        "code": "wechat_channels",
        "name": "微信视频号",
        "region": "cn",
        "portal": "https://channels.weixin.qq.com/",
        "clip": True,
        "sop": "用素材包 15s/30s 切片作 BGM，在视频号创作者端发布后把作品链接贴回比特音。",
    },
    {
        "code": "douyin_musician",
        "name": "抖音音乐人",
        "region": "cn",
        "portal": "https://creator.douyin.com/",
        "clip": True,
        "sop": "打开抖音音乐人/创作者入口，上传高潮切片或完整母带，复制音乐链接回比特音。不要上传分轨当 BGM。",
    },
    {
        "code": "kuaishou_musician",
        "name": "快手音乐人",
        "region": "cn",
        "portal": "https://cp.kuaishou.com/",
        "clip": True,
        "sop": "打开快手音乐人后台，上传切片或原曲母带，复制作品链接回比特音。",
    },
    {
        "code": "soundcloud",
        "name": "SoundCloud",
        "region": "global",
        "portal": "https://soundcloud.com/upload",
        "clip": False,
        "sop": "Upload the kit stereo master on SoundCloud, then paste the track URL back. Do not upload stems as extra tracks.",
    },
    {
        "code": "bandcamp",
        "name": "Bandcamp",
        "region": "global",
        "portal": "https://bandcamp.com/",
        "clip": False,
        "sop": "Upload the stereo master on Bandcamp, then paste the album or track URL back. Stems are not store tracks.",
    },
    {
        "code": "deezer",
        "name": "Deezer",
        "region": "global",
        "portal": "https://www.deezer.com/",
        "clip": False,
        "sop": "Confirm delivery in Deezer for Creators when available, then paste the track URL back.",
    },
]


def channel_upload_url(code: str | None) -> str | None:
    if not code:
        return None
    return CHANNEL_UPLOAD_FORMS.get(code) or CHANNEL_PORTALS.get(code)


def _host_name(url: str | None) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def channel_hosts(code: str | None) -> list[str]:
    listed = list(CHANNEL_HOSTS.get(code or "", []))
    portal_host = _host_name(CHANNEL_PORTALS.get(code or ""))
    if portal_host and portal_host not in listed:
        listed.append(portal_host)
    return listed


def has_live_receipt(*, store_url: str | None = None, external_id: str | None = None, channel_code: str | None = None) -> bool:
    if is_known_upload_portal(store_url):
        return False
    url = (store_url or "").strip()
    ext = (external_id or "").strip()
    if url:
        return looks_like_store_page(url, channel_code)
    if ext.startswith("http://") or ext.startswith("https://"):
        return looks_like_store_page(ext, channel_code)
    return bool(ext)


def delivery_has_live_receipt(row) -> bool:
    return has_live_receipt(
        store_url=getattr(row, "store_url", None),
        external_id=getattr(row, "external_id", None),
        channel_code=getattr(row, "channel_code", None),
    )


def extract_store_ref(url: str | None, channel_code: str | None = None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    qs = {key.lower(): values for key, values in parse_qs(urlparse(raw).query).items()}
    if (not channel_code or channel_code == "apple_music") and qs.get("i"):
        return str(qs["i"][0])[:128]
    preferred = [item for item in STORE_ID_PATTERNS if not channel_code or item[1] == channel_code]
    fallback = [item for item in STORE_ID_PATTERNS if item not in preferred]
    for pattern, _code in preferred + fallback:
        match = re.search(pattern, raw, re.I)
        if match:
            return match.group(match.lastindex or 1)[:128]
    if (not channel_code or channel_code in {"netease", "qq_music", "qishui", "kugou"}) and qs.get("id"):
        return str(qs["id"][0])[:128]
    if (not channel_code or channel_code == "youtube_music") and qs.get("v"):
        return str(qs["v"][0])[:128]
    return None


STORE_LIVE_PATTERNS: dict[str, list[str]] = {
    "netease": [r"music\.163\.com/(?:#/)?song"],
    "qq_music": [r"y\.qq\.com/.*/songDetail"],
    "kugou": [r"kugou\.com/.+(?:hash=|song)"],
    "kuwo": [r"kuwo\.cn/.+(?:play_detail|yinyue|\d{5,})"],
    "qishui": [r"music\.douyin\.com/.+"],
    "bilibili": [r"bilibili\.com/(?:video|audio)/"],
    "spotify": [r"open\.spotify\.com/(?:intl-[a-z]+/)?(?:track|album)/"],
    "apple_music": [r"music\.apple\.com/.+/(?:album|song)/"],
    "youtube_music": [r"youtube\.com/watch", r"youtu\.be/", r"music\.youtube\.com/watch"],
    "tiktok_music": [r"tiktok\.com/music/", r"tiktok\.com/.+/sound/"],
    "amazon_music": [r"music\.amazon\.[^/]+/(?:albums|tracks)/"],
    "deezer": [r"deezer\.com/.*/(?:track|album)/"],
    "wechat_channels": [r"channels\.weixin\.qq\.com/.+(?:finder|export|feed|post)"],
    "douyin_musician": [r"douyin\.com/.+(?:video|note|music)"],
    "kuaishou_musician": [r"kuaishou\.com/.+(?:short-video|photo)"],
    "soundcloud": [r"soundcloud\.com/(?!you|pages|upload|discover|search|stream|library|sets|charts)[^/?#]+/(?!sets|likes|reposts|followers)[^/?#]+"],
    "bandcamp": [r"bandcamp\.com/(?:track|album)/"],
}


def is_known_upload_portal(url: str | None) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    host = _host_name(raw)
    path = (urlparse(raw).path or "").lower()
    if host in {
        "artists.spotify.com",
        "studio.youtube.com",
        "artists.apple.com",
        "artists.amazon.com",
        "artists.amazonmusic.com",
        "creator.douyin.com",
        "musician.douyin.com",
        "member.bilibili.com",
        "cp.kuaishou.com",
    }:
        return True
    if "/st/musician" in path or "/portal/" in path or "/musician" in path or path.rstrip("/").endswith("/upload"):
        return True
    return False


def looks_like_store_page(url: str | None, channel_code: str | None = None) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    if extract_store_ref(raw, channel_code):
        return True
    host = _host_name(raw)
    path = (urlparse(raw).path or "").lower()
    if host in {
        "artists.spotify.com",
        "studio.youtube.com",
        "artists.apple.com",
        "artists.amazon.com",
        "artists.amazonmusic.com",
        "creator.douyin.com",
        "musician.douyin.com",
        "member.bilibili.com",
        "cp.kuaishou.com",
    }:
        return False
    if "/st/musician" in path or "/portal/" in path or "/musician" in path or path.rstrip("/").endswith("/upload"):
        return False
    patterns = STORE_LIVE_PATTERNS.get(channel_code or "") if channel_code else None
    if patterns is None:
        patterns = [item for group in STORE_LIVE_PATTERNS.values() for item in group]
    return any(re.search(pattern, raw, re.I) for pattern in patterns)


def volume_rank(code: str | None) -> int:
    if not code:
        return 99
    try:
        return VOLUME_CHANNEL_CODES.index(code)
    except ValueError:
        return 99


def channel_display_name(code: str | None) -> str:
    if not code:
        return ""
    return CHANNEL_NAMES.get(code, code)


DEFAULT_REQUIREMENTS = {
    "min_duration": 30,
    "max_duration": 600,
    "sample_rate": 44100,
    "lufs_target": -14,
    "formats": ["wav", "mp3_320"],
}

HARVEST_SOURCES = frozenset({"ops_connector", "user_connector", "seat_harvest", "farm_harvest"})
SETTLEMENT_SOURCES = frozenset(
    {
        "distributor_export",
        "distributor_api",
        "official_api",
        "user_export",
        "sync_license",
        "first_party_embed",
        *HARVEST_SOURCES,
    }
)
DISPLAY_ONLY_SOURCES = frozenset(
    {
        "licensed_analytics",
        "public_api",
        "first_party_radio",
        "first_party_radio_self",
        "first_party_embed_uncertified",
        "sync_license_credits",
        "connector_sync",
    }
)

CHANNEL_SOPS = {
    "netease": "席位在网易云音乐人后台只传一条立体声母带 WAV。分轨/伴奏只放「作品管理 → 原创证明」，不要当多轨上架。AI 作品走「AI 音乐人」披露，不要伪造 DAW 工程。电音或被拒后再补 Demucs 级 originality.zip。",
    "qq_music": "正片传母带。TME 入驻/电音补件把 originality.zip（分轨+去人声伴奏+生成记录）放到分轨或版权证明栏，也可邮件 TME_tmemusicians@tencentmusic.com。不要把 vocal/drums 当正片。",
    "kugou": "正片传母带（≤200MB MP3/WAV）。电音必须交工程/分轨时，只把 kit 里 originality.zip 挂到证明文件栏；听众听到的仍是母带。建议 ≤10 条分轨、打包 ≤300MB。",
    "kuwo": "正片传立体声母带。如需原创证明，使用发行包 originality/（仅 Demucs 级）。AI 作品请披露生成，不要伪造 DAW 工程，也不要把分轨当多首歌上传。",
    "qishui": "汽水后台按完整曲或短视频切片上传。完整曲用立体声母带；切片用 audio/clips/。分轨不是汽水正片，也不要当 BGM。",
    "bilibili": "创作中心只上传一条立体声母带。分轨不是稿件正片；不要伪造 Logic/FL 工程。稿件页由席位回传。",
    "spotify": "Upload one stereo master WAV in the aggregator or Spotify for Artists. Never split vocals/drums into extra tracks. The store page is the receipt.",
    "apple_music": "One stereo master via the aggregator. Confirm in Apple Music for Artists. Stems are not store tracks.",
    "youtube_music": "Upload one mixed stereo master in YouTube Studio. Never attach Demucs stems as extra videos or tracks. The watch URL is the receipt.",
    "tiktok_music": "The seat uploads the sound in TikTok Studio. Use clips for short video; the listing audio is still the master. Do not upload stems as the sound.",
    "amazon_music": "One stereo master. Confirm in Amazon Music for Artists. Stems are not extra tracks. The store page comes back as a receipt.",
    "deezer": "One stereo master. Confirm delivery in Deezer for Creators when available. Never upload vocal/drum stems as extra songs.",
    "wechat_channels": "用素材包 15s/30s 切片作 BGM，在视频号创作者端发布后把作品链接贴回比特音。不要把分轨当 BGM。",
    "douyin_musician": "打开抖音音乐人/创作者入口，上传高潮切片或完整母带，复制音乐链接回比特音。不要上传分轨当 BGM。",
    "kuaishou_musician": "打开快手音乐人后台，上传切片或原曲母带，复制作品链接回比特音。不要上传分轨当正片。",
    "soundcloud": "Upload the kit stereo master on SoundCloud, then paste the track URL back. Do not upload stems as extra tracks.",
    "bandcamp": "Upload the stereo master on Bandcamp, then paste the album or track URL back. Stems are not store tracks.",
}


def channel_sop(code: str | None) -> str:
    if not code:
        return ""
    if code in CHANNEL_SOPS:
        return CHANNEL_SOPS[code]
    portal = next((item for item in PORTAL_CHANNELS if item["code"] == code), None)
    return str(portal.get("sop") or "") if portal else ""


def list_portal_channels() -> list[dict]:
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "region": item["region"],
            "upload_url": item["portal"],
            "sop": item["sop"],
            "clip": bool(item.get("clip")),
            "portal_only": False,
        }
        for item in PORTAL_CHANNELS
    ]


def clip_windows(duration: float | None) -> list[dict]:
    """Suggest 15s/30s climax windows for short-video BGM packs. No transcode."""
    try:
        total = float(duration or 0)
    except (TypeError, ValueError):
        return []
    if total < 20:
        return []
    climax = total * 0.55

    def _window(length: int) -> dict:
        start = max(0.0, climax - length / 2)
        if start + length > total:
            start = max(0.0, total - length)
        return {
            "length": length,
            "start": round(start, 2),
            "end": round(min(total, start + length), 2),
            "use": "short_video",
        }

    out = [_window(15)]
    if total >= 35:
        out.append(_window(30))
    if total >= 70:
        out.append(_window(60))
    return out


CONNECTOR_SOURCES = frozenset({"ops_connector", "user_connector"})
OFFICIAL_SOURCES = frozenset({"distributor_export", "distributor_api", "official_api"})

STORE_ALIASES = {
    "spotify": "spotify",
    "apple": "apple_music",
    "apple music": "apple_music",
    "apple_music": "apple_music",
    "itunes": "apple_music",
    "itunes music": "apple_music",
    "youtube": "youtube_music",
    "youtube music": "youtube_music",
    "youtube_music": "youtube_music",
    "youtube content id": "youtube_music",
    "youtube art track": "youtube_music",
    "tiktok": "tiktok_music",
    "tiktok music": "tiktok_music",
    "amazon": "amazon_music",
    "amazon music": "amazon_music",
    "amazon unlimited": "amazon_music",
    "netease": "netease",
    "netease cloud music": "netease",
    "网易云": "netease",
    "网易云音乐": "netease",
    "qq": "qq_music",
    "qq音乐": "qq_music",
    "qq music": "qq_music",
    "tencent": "qq_music",
    "tencent music": "qq_music",
    "kugou": "kugou",
    "酷狗": "kugou",
    "酷狗音乐": "kugou",
    "kuwo": "kuwo",
    "酷我": "kuwo",
    "酷我音乐": "kuwo",
    "汽水": "qishui",
    "汽水音乐": "qishui",
    "qishui": "qishui",
    "bilibili": "bilibili",
    "b站": "bilibili",
    "deezer": "deezer",
    "wechat": "wechat_channels",
    "wechat channels": "wechat_channels",
    "视频号": "wechat_channels",
    "douyin": "douyin_musician",
    "抖音": "douyin_musician",
    "kuaishou": "kuaishou_musician",
    "快手": "kuaishou_musician",
    "soundcloud": "soundcloud",
    "bandcamp": "bandcamp",
}


def normalize_store(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    return STORE_ALIASES.get(key) or key.replace(" ", "_")


def seed_distribution_catalog(db: Session) -> None:
    for spec in CHANNEL_SPECS:
        row = db.query(DistributionChannel).filter(DistributionChannel.code == spec["code"]).first()
        if row:
            row.name = spec["name"]
            row.region = spec["region"]
            row.distributor_code = spec["distributor_code"]
            row.sort_order = spec["sort_order"]
            if not row.requirements:
                row.requirements = dict(DEFAULT_REQUIREMENTS)
            continue
        db.add(
            DistributionChannel(
                id=uuid.uuid4(),
                code=spec["code"],
                name=spec["name"],
                region=spec["region"],
                distributor_code=spec["distributor_code"],
                requirements=dict(DEFAULT_REQUIREMENTS),
                enabled=True,
                sort_order=spec["sort_order"],
            )
        )
    defaults = [
        ("label", "*", "*", 20),
        ("label", "*", "standard", 20),
        ("label", "*", "pro", 10),
        ("self_release", "*", "*", 10),
    ]
    for mode, channel, level, rate in defaults:
        exists = (
            db.query(CommissionRule)
            .filter(
                CommissionRule.mode == mode,
                CommissionRule.channel_code == channel,
                CommissionRule.user_level == level,
            )
            .first()
        )
        if not exists:
            db.add(
                CommissionRule(
                    id=uuid.uuid4(),
                    mode=mode,
                    channel_code=channel,
                    user_level=level,
                    rate_percent=rate,
                    enabled=True,
                )
            )


def list_channels(db: Session, *, enabled_only: bool = True) -> list[DistributionChannel]:
    q = db.query(DistributionChannel)
    if enabled_only:
        q = q.filter(DistributionChannel.enabled.is_(True))
    return q.order_by(DistributionChannel.sort_order.asc()).all()


def channel_map(db: Session) -> dict[str, DistributionChannel]:
    return {c.code: c for c in list_channels(db, enabled_only=False)}


def all_channel_codes() -> list[str]:
    return [spec["code"] for spec in CHANNEL_SPECS]


# Catalog order for ranking. One-click default is narrower — see default_upload_channels.
VOLUME_CHANNEL_CODES = [spec["code"] for spec in CHANNEL_SPECS]
# First stores the auth desk offers. Optional clip lanes stay folded.
STARTER_VOLUME_CHANNELS = ("netease", "qq_music", "spotify")
# Auth-desk ranking only. Not the one-tap upload default — Spotify is metrics_only.
LAUNCH_HANDOFF_CHANNELS = ("netease", "spotify", "wechat_channels")
# One-tap fillable default. Metrics-only stores never belong here.
DEFAULT_UPLOAD_CHANNELS = ("netease",)


def is_volume_channel(code: str | None) -> bool:
    return channel_delivery_mode(code) != "session_assist"


def connected_channel_codes(db=None, user=None) -> list[str]:
    if db is None or user is None:
        return []
    from app.services.seats.connections import build_connections
    from app.services.seats.service import list_seats

    cards = build_connections(db, user, list_seats(db, user))
    return [
        str(card["channel_code"])
        for card in cards
        if card.get("status") in {"settle", "metrics"}
    ]


def channel_capability(code: str | None, *, connected: list[str] | None = None) -> str:
    if not code:
        return "wait_connector"
    connected_set = {item for item in (connected or []) if item}
    if pick_configured_aggregator(code) or code in connected_set:
        return "auto"
    if channel_delivery_mode(code) == "session_assist":
        return "needs_link"
    return "wait_connector"


def default_upload_channels(*, connected: list[str] | None = None) -> list[str]:
    """Fillable one-tap defaults. Never includes metrics-only stores."""
    connected_set = {item for item in (connected or []) if item}
    out: list[str] = []
    for code in DEFAULT_UPLOAD_CHANNELS:
        if channel_spec(code) and code not in out:
            out.append(code)
    for spec in CHANNEL_SPECS:
        code = spec["code"]
        if code in out:
            continue
        if spec.get("automation_level") != "connector_full":
            continue
        if code in connected_set:
            out.append(code)
    return out


def default_volume_channels(*, connected: list[str] | None = None) -> list[str]:
    connected_set = {item for item in (connected or []) if item}
    out: list[str] = []
    for spec in CHANNEL_SPECS:
        code = spec["code"]
        if pick_configured_aggregator(code) or code in connected_set:
            out.append(code)
    if out:
        return out
    return list(default_upload_channels())


def optional_assist_channels(*, connected: list[str] | None = None) -> list[str]:
    connected_set = {item for item in (connected or []) if item}
    return [
        spec["code"]
        for spec in CHANNEL_SPECS
        if spec.get("delivery_mode") == "session_assist" and spec["code"] not in connected_set
    ]


def channel_spec(code: str | None) -> dict | None:
    if not code:
        return None
    return next((item for item in CHANNEL_SPECS if item["code"] == code), None)


def channel_delivery_mode(code: str | None) -> str:
    spec = channel_spec(code) or {}
    return str(spec.get("delivery_mode") or "session_assist")


def channel_automation_level(code: str | None) -> str:
    spec = channel_spec(code) or {}
    stored = str(spec.get("automation_level") or "").strip()
    if stored:
        from app.services.distribution.telemetry import effective_automation_level

        return effective_automation_level(str(code or ""), stored)
    return _automation_level_for(str(code or ""))


def list_channel_capabilities() -> list[dict]:
    return [
        {
            "channel_code": spec["code"],
            "name": spec["name"],
            "region": spec.get("region"),
            "delivery_mode": spec.get("delivery_mode"),
            "automation_level": channel_automation_level(spec["code"]),
        }
        for spec in CHANNEL_SPECS
    ]


def preview_delivery_route(code: str | None) -> dict:
    """Honest one-tap preview. Connector is the trunk; partner keys are a sidecar."""
    level = channel_automation_level(code)
    spec = channel_spec(code) or {}
    base = str(spec.get("automation_level") or "").strip() or _automation_level_for(str(code or ""))
    from app.services.distribution.telemetry import channel_telemetry

    tel = channel_telemetry(None, code)
    degraded = bool(tel.get("degraded_to")) and base == "connector_full"
    partner = pick_configured_aggregator(code)
    extra = {"degraded": degraded, "degraded_to": tel.get("degraded_to") if degraded else None, "base_automation_level": base}
    if level in {"connector_full", "connector_assist"}:
        return {
            "channel_code": code,
            "route": "connector",
            "pipeline": "session_assist",
            "automation_level": level,
            "sidecar_partner": partner,
            **extra,
        }
    if partner:
        return {
            "channel_code": code,
            "route": "partner",
            "pipeline": "partner",
            "automation_level": level,
            "sidecar_partner": partner,
            **extra,
        }
    if level == "metrics_only":
        return {
            "channel_code": code,
            "route": "metrics",
            "pipeline": "metrics_only",
            "automation_level": level,
            "sidecar_partner": None,
            **extra,
        }
    return {
        "channel_code": code,
        "route": "ops",
        "pipeline": "ops",
        "automation_level": level or "ops_only",
        "sidecar_partner": None,
        **extra,
    }


def preview_release_routes(codes: list[str] | None) -> list[dict]:
    return [preview_delivery_route(code) for code in (codes or []) if code]


def aggregator_candidates(code: str | None) -> list[str]:
    spec = channel_spec(code) or {}
    if spec.get("delivery_mode") == "session_assist":
        return []
    listed = spec.get("aggregators")
    if listed:
        return [str(item) for item in listed if item]
    primary = spec.get("distributor_code")
    if primary and primary != "session":
        return [str(primary)]
    return []


def pick_configured_aggregator(code: str | None) -> str | None:
    from app.services.distribution.adapters import get_adapter

    for candidate in aggregator_candidates(code):
        if get_adapter(candidate).configured():
            return candidate
    return None


def list_aggregator_partners() -> list[dict]:
    from app.services.distribution.adapters import get_adapter

    return [
        {**row, "configured": get_adapter(row["code"]).configured()}
        for row in AGGREGATOR_DIRECTORY
    ]


def partner_payee_status() -> dict:
    from app.config import settings
    from app.services.distribution.adapters import get_adapter

    partners = []
    for row in AGGREGATOR_DIRECTORY:
        adapter = get_adapter(row["code"])
        configured = adapter.configured()
        partners.append(
            {
                **row,
                "configured": configured,
                "has_key": adapter.has_credentials(),
                "has_base": bool(adapter._base()),
                "earnings_api": configured,
                "settlement_path": "partner_api" if configured else "ops_csv",
            }
        )
    return {
        "partners": partners,
        "global_ready": any(p["configured"] and p.get("region") == "global" for p in partners),
        "cn_ready": any(p["configured"] and p.get("region") == "cn" for p in partners),
        "stub_enabled": bool(getattr(settings, "partner_stub_enabled", False)),
        "note": "未签约收款主体前，厂牌版税只走官方 CSV + 人审。密钥和端点都缺时继续运营队列，不假装已对接收益 API。",
    }


def distributor_for_code(db: Session, code: str) -> str | None:
    picked = pick_configured_aggregator(code)
    if picked:
        return picked
    row = channel_map(db).get(code)
    if row and row.enabled:
        return row.distributor_code
    spec = channel_spec(code)
    return spec["distributor_code"] if spec else None
