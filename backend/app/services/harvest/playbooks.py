"""Shared DSP playbook metadata. DOM harvest is the money path; partner APIs stay uncalled."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[4] / "packages" / "dsp-playbooks"

# Kept for ops display only. Never invent settlement money from streams.
CHANNEL_RATE_CARD = {}

# Coverage order: 网易/QQ → Spotify/YouTube → 汽水会话 → Apple, then remaining CN stores.
PLATFORM_SEAT_CHANNELS = [
    "netease",
    "qq_music",
    "spotify",
    "youtube_music",
    "qishui",
    "apple_music",
    "kugou",
    "kuwo",
    "bilibili",
]

PLAYBOOKS: dict[str, dict] = {
    "netease": {
        "name": "网易云音乐",
        "portal": "https://music.163.com/st/musician",
        "harvest_url": "https://music.163.com/st/musician",
        "upload_url": "https://music.163.com/st/musician/upload",
        "region": "cn",
        "csv_export_hint": "优先用音乐人后台导出的官方 CSV，再退回表格刮取。",
    },
    "qq_music": {
        "name": "QQ 音乐",
        "portal": "https://y.qq.com/portal/",
        "harvest_url": "https://y.qq.com/portal/",
        "upload_url": "https://y.qq.com/portal/publish.html",
        "region": "cn",
    },
    "kugou": {
        "name": "酷狗音乐",
        "portal": "https://www.kugou.com/musician/",
        "harvest_url": "https://www.kugou.com/musician/",
        "upload_url": "https://www.kugou.com/musician/",
        "region": "cn",
    },
    "kuwo": {
        "name": "酷我音乐",
        "portal": "https://www.kuwo.cn/musician",
        "harvest_url": "https://www.kuwo.cn/musician",
        "upload_url": "https://kuwo.cn/musician/upload",
        "region": "cn",
    },
    "qishui": {
        "name": "汽水音乐",
        "portal": "https://music.douyin.com/",
        "harvest_url": "https://music.douyin.com/",
        "upload_url": "https://musician.douyin.com/upload",
        "region": "cn",
    },
    "bilibili": {
        "name": "B 站音频",
        "portal": "https://member.bilibili.com/",
        "harvest_url": "https://member.bilibili.com/",
        "upload_url": "https://member.bilibili.com/platform/upload/audio/home",
        "region": "cn",
    },
    "spotify": {
        "name": "Spotify",
        "portal": "https://artists.spotify.com/",
        "harvest_url": "https://artists.spotify.com/",
        "upload_url": "https://artists.spotify.com/",
        "region": "global",
    },
    "apple_music": {
        "name": "Apple Music",
        "portal": "https://artists.apple.com/",
        "harvest_url": "https://artists.apple.com/",
        "upload_url": "https://artists.apple.com/",
        "region": "global",
    },
    "youtube_music": {
        "name": "YouTube Music",
        "portal": "https://studio.youtube.com/",
        "harvest_url": "https://studio.youtube.com/",
        "upload_url": "https://studio.youtube.com/",
        "region": "global",
    },
    "tiktok_music": {
        "name": "TikTok Music",
        "portal": "https://www.tiktok.com/studio",
        "harvest_url": "https://www.tiktok.com/studio",
        "upload_url": "https://www.tiktok.com/studio",
        "region": "global",
    },
    "amazon_music": {
        "name": "Amazon Music",
        "portal": "https://artists.amazon.com/",
        "harvest_url": "https://artists.amazon.com/",
        "upload_url": "https://artists.amazon.com/",
        "region": "global",
    },
    "deezer": {
        "name": "Deezer",
        "portal": "https://www.deezer.com/",
        "harvest_url": "https://www.deezer.com/",
        "upload_url": "https://www.deezer.com/",
        "region": "global",
    },
    "wechat_channels": {
        "name": "微信视频号",
        "portal": "https://channels.weixin.qq.com/",
        "harvest_url": "https://channels.weixin.qq.com/",
        "upload_url": "https://channels.weixin.qq.com/",
        "region": "cn",
    },
    "douyin_musician": {
        "name": "抖音音乐人",
        "portal": "https://creator.douyin.com/",
        "harvest_url": "https://creator.douyin.com/",
        "upload_url": "https://creator.douyin.com/",
        "region": "cn",
    },
    "kuaishou_musician": {
        "name": "快手音乐人",
        "portal": "https://cp.kuaishou.com/",
        "harvest_url": "https://cp.kuaishou.com/",
        "upload_url": "https://cp.kuaishou.com/",
        "region": "cn",
    },
    "soundcloud": {
        "name": "SoundCloud",
        "portal": "https://soundcloud.com/upload",
        "harvest_url": "https://soundcloud.com/",
        "upload_url": "https://soundcloud.com/upload",
        "region": "global",
    },
    "bandcamp": {
        "name": "Bandcamp",
        "portal": "https://bandcamp.com/",
        "harvest_url": "https://bandcamp.com/",
        "upload_url": "https://bandcamp.com/",
        "region": "global",
    },
}


CHANNEL_STEPS = {
    "netease": {
        "stats_url": "https://music.163.com/st/musician",
        "stats_urls": ["https://music.163.com/st/musician"],
        "wait_selectors": ["table", ".song-item", ".m-table"],
        "export_selectors": ["a[href*='.csv']", "button[data-export]"],
        "export_texts": ["导出CSV", "导出报表", "导出"],
        "next_page_selectors": [".znxt", ".nxt", "a.next", ".pagination-next"],
        "login_hints": ["登录", "二维码"],
    },
    "qq_music": {
        "stats_url": "https://y.qq.com/portal/",
        "stats_urls": ["https://y.qq.com/portal/", "https://y.qq.com/nportal/"],
        "wait_selectors": ["table", ".song_item"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["导出CSV", "导出"],
        "next_page_selectors": [".page_next", "a.next"],
        "login_hints": ["登录"],
    },
    "qishui": {
        "stats_url": "https://music.douyin.com/",
        "stats_urls": ["https://music.douyin.com/"],
        "wait_selectors": ["table", ".track-card"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["导出"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "kugou": {
        "stats_url": "https://www.kugou.com/musician/",
        "stats_urls": ["https://www.kugou.com/musician/"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["导出"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "kuwo": {
        "stats_url": "https://www.kuwo.cn/musician",
        "stats_urls": ["https://www.kuwo.cn/musician"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["导出"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "douyin_musician": {
        "stats_url": "https://creator.douyin.com/",
        "stats_urls": ["https://creator.douyin.com/", "https://creator.douyin.com/creator-micro/home"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["导出"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "spotify": {
        "stats_url": "https://artists.spotify.com/c/music",
        "stats_urls": ["https://artists.spotify.com/c/music", "https://artists.spotify.com/c/music/songs"],
        "wait_selectors": ["table", "[data-testid='row']"],
        "export_selectors": ["a[href*='.csv']", "button[data-testid='export']"],
        "export_texts": ["Download CSV", "Export"],
        "next_page_selectors": ["button[aria-label='Next']"],
        "login_hints": ["Log in", "Sign in"],
    },
    "apple_music": {
        "stats_url": "https://artists.apple.com/",
        "stats_urls": ["https://artists.apple.com/"],
        "wait_selectors": ["table", ".song-row"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["Download CSV", "Export"],
        "next_page_selectors": ["button[aria-label='Next']"],
        "login_hints": ["Sign in"],
    },
    "youtube_music": {
        "stats_url": "https://studio.youtube.com/channel/analytics/tab-overview/period-default",
        "stats_urls": ["https://studio.youtube.com/", "https://studio.youtube.com/channel/analytics/tab-overview/period-default"],
        "wait_selectors": ["table", "[data-views]"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["Download CSV", "Download"],
        "next_page_selectors": ["#next-page-button"],
        "login_hints": ["Sign in"],
    },
    "bilibili": {
        "stats_url": "https://member.bilibili.com/",
        "stats_urls": ["https://member.bilibili.com/", "https://member.bilibili.com/platform/home"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "wechat_channels": {
        "stats_url": "https://channels.weixin.qq.com/",
        "stats_urls": ["https://channels.weixin.qq.com/", "https://channels.weixin.qq.com/platform"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录", "扫码"],
    },
    "kuaishou_musician": {
        "stats_url": "https://cp.kuaishou.com/",
        "stats_urls": ["https://cp.kuaishou.com/"],
        "wait_selectors": ["table"],
        "export_selectors": ["a[href*='.csv']"],
        "next_page_selectors": [".pagination-next"],
        "login_hints": ["登录"],
    },
    "tiktok_music": {
        "stats_url": "https://www.tiktok.com/studio/analytics",
        "stats_urls": ["https://www.tiktok.com/studio/analytics", "https://www.tiktok.com/studio"],
        "wait_selectors": [".analytics-table", "[data-e2e='analytics']", "table", "[data-vibe-row]"],
        "export_selectors": ["a[href*='.csv']"],
        "export_texts": ["Download", "Export"],
        "next_page_selectors": ["button[aria-label='Next']"],
        "login_hints": ["Log in", "登录", "Sign in"],
    },
    "amazon_music": {
        "stats_url": "https://artists.amazon.com/",
        "stats_urls": ["https://artists.amazon.com/", "https://artists.amazonmusic.com/analytics"],
        "wait_selectors": [".analytics-table", "[data-testid='streams-table']", "table"],
        "login_hints": ["Sign in", "Sign In"],
    },
    "deezer": {
        "stats_url": "https://artists.deezer.com/analytics",
        "stats_urls": ["https://artists.deezer.com/analytics", "https://www.deezer.com/"],
        "wait_selectors": [".analytics-table", ".streams-list", "table"],
        "login_hints": ["Log in", "Se connecter"],
    },
    "soundcloud": {
        "stats_url": "https://soundcloud.com/you/insights",
        "stats_urls": ["https://soundcloud.com/you/insights"],
        "wait_selectors": ["table", "[data-vibe-row]"],
        "export_selectors": ["a[href*='.csv']"],
        "login_hints": ["Sign in", "Log in"],
    },
    "bandcamp": {
        "stats_url": "https://bandcamp.com/",
        "stats_urls": ["https://bandcamp.com/"],
        "wait_selectors": ["table", "[data-vibe-row]"],
        "export_selectors": ["a[href*='.csv']"],
        "login_hints": ["Log in", "Sign in"],
    },
}


def channel_playbook(code: str | None) -> dict:
    spec = PLAYBOOKS.get(code or "")
    if not spec:
        return {"name": code or "", "portal": "", "harvest_url": "", "upload_url": "", "region": "global"}
    merged = dict(spec)
    steps = CHANNEL_STEPS.get(code or "") or {}
    if steps:
        merged.update(steps)
        merged.setdefault("harvest_url", steps.get("stats_url") or merged.get("harvest_url"))
    return merged


def estimate_revenue_minor(channel_code: str | None, streams: int, revenue_minor: int = 0) -> int:
    del channel_code, streams
    return max(0, int(revenue_minor or 0))


def playbook_health(code: str | None) -> dict:
    """Same contract as packages/dsp-playbooks health(): stats URLs + wait selectors."""
    heal = heal_candidates(code)
    issues: list[str] = []
    if not heal.get("statsUrls"):
        issues.append("missing_stats_url")
    if not heal.get("primary") and not heal.get("alternateSelectors"):
        issues.append("missing_wait_selectors")
    spec = PLAYBOOKS.get(code or "") or {}
    return {
        "ok": not issues,
        "code": code,
        "issues": issues,
        "name": spec.get("name"),
        "region": spec.get("region"),
        **heal,
    }


def heal_candidates(code: str | None) -> dict:
    """Alternate selectors / stats URLs ops can try after selector_broke."""
    steps = CHANNEL_STEPS.get(code or "") or {}
    waits = list(steps.get("wait_selectors") or [])
    primary = waits[:1]
    alternate = waits[1:]
    return {
        "primary": primary,
        "alternateSelectors": alternate,
        "statsUrls": list(steps.get("stats_urls") or ([steps.get("stats_url")] if steps.get("stats_url") else [])),
        "exportSelectors": list(steps.get("export_selectors") or []),
    }


def list_playbooks() -> list[dict]:
    return [{"code": code, **channel_playbook(code), "heal_candidates": heal_candidates(code)} for code in PLAYBOOKS]


def health_fixture_rows() -> list[dict]:
    fixture = PACKAGE_DIR / "fixtures" / "health-rows.json"
    if fixture.exists():
        import json

        data = json.loads(fixture.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return list(data)
        return list(data.get("rows") or [])
    return [
        {
            "channel_code": "netease",
            "title": "Night Drive",
            "isrc": "VSFIXTURE0001",
            "streams": 120,
            "revenue_minor": 480,
            "currency": "CNY",
            "period_key": "2026-08",
        }
    ]
