"""Official YouTube OAuth + Analytics / Data API — display-only views."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import CreatorIdentityBinding, DistributionDelivery, User, Work
from app.services.royalty.snapshots import upsert_metric_snapshot

logger = logging.getLogger(__name__)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
YT_CHANNELS = "https://www.googleapis.com/youtube/v3/channels"
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
YT_ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly"


def configured() -> bool:
    return bool(settings.youtube_client_id and settings.youtube_client_secret)


def callback_uri() -> str:
    if settings.youtube_redirect_uri:
        return settings.youtube_redirect_uri
    return f"{settings.api_public_url.rstrip('/')}/distribution/youtube/callback"


def _sign_state(user_id: str) -> str:
    payload = json.dumps({"uid": user_id, "exp": int(time.time()) + 600}, separators=(",", ":"))
    sig = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = json.dumps({"p": payload, "s": sig}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _read_state(state: str) -> str:
    try:
        raw = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        payload = raw["p"]
        sig = raw["s"]
        expect = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            raise ValueError("bad sig")
        data = json.loads(payload)
        if int(data["exp"]) < int(time.time()):
            raise ValueError("expired")
        return str(data["uid"])
    except Exception as exc:
        raise HTTPException(400, "Invalid OAuth state") from exc


def auth_url(user_id: str) -> str:
    if not configured():
        raise HTTPException(400, "YouTube OAuth is not configured")
    params = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": callback_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": _sign_state(user_id),
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    resp = httpx.post(GOOGLE_TOKEN, data=data, timeout=20)
    if resp.status_code >= 400:
        logger.warning("YouTube token error: %s", resp.text[:300])
        raise HTTPException(400, "YouTube token exchange failed")
    return resp.json()


def exchange_code(code: str, state: str, db: Session) -> CreatorIdentityBinding:
    user_id = _read_state(state)
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(404, "User not found")
    tokens = _token_request(
        {
            "code": code,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "redirect_uri": callback_uri(),
            "grant_type": "authorization_code",
        }
    )
    return _store_tokens(db, user, tokens)


def _store_tokens(db: Session, user: User, tokens: dict, existing: CreatorIdentityBinding | None = None) -> CreatorIdentityBinding:
    row = existing or (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == "youtube")
        .first()
    )
    prev = {}
    if row and row.official_token:
        try:
            prev = json.loads(row.official_token)
        except json.JSONDecodeError:
            prev = {}
    merged = {
        "access_token": tokens.get("access_token") or prev.get("access_token"),
        "refresh_token": tokens.get("refresh_token") or prev.get("refresh_token"),
        "expiry": int(time.time()) + int(tokens.get("expires_in") or 3600),
        "token_type": tokens.get("token_type") or "Bearer",
    }
    if not row:
        row = CreatorIdentityBinding(user_id=user.id, provider="youtube")
        db.add(row)
    row.official_token = json.dumps(merged)
    row.status = "active"
    channel = _channel_profile(merged["access_token"])
    if channel:
        row.external_release_id = channel.get("id")
        merged["channel_title"] = channel.get("title")
        row.official_token = json.dumps(merged)
    db.commit()
    return row


def _channel_profile(access_token: str) -> dict | None:
    resp = httpx.get(
        YT_CHANNELS,
        params={"part": "id,snippet,statistics", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.warning("YouTube channel lookup failed: %s", resp.text[:300])
        return None
    items = (resp.json() or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    stats = item.get("statistics") or {}
    snippet = item.get("snippet") or {}
    return {
        "id": item.get("id"),
        "title": snippet.get("title"),
        "view_count": int(stats.get("viewCount") or 0),
        "subscriber_count": int(stats.get("subscriberCount") or 0),
    }


def _access_token_for(db: Session, row: CreatorIdentityBinding) -> str | None:
    try:
        tokens = json.loads(row.official_token or "{}")
    except json.JSONDecodeError:
        return None
    access = tokens.get("access_token")
    expiry = int(tokens.get("expiry") or 0)
    if access and expiry > int(time.time()) + 60:
        return access
    refresh = tokens.get("refresh_token")
    if not refresh:
        return access
    try:
        fresh = _token_request(
            {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            }
        )
    except HTTPException:
        return None
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        return None
    _store_tokens(db, user, fresh, existing=row)
    return fresh.get("access_token")


def normalize_title(value: str) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def extract_youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    raw = url.strip()
    for prefix in ("https://youtu.be/", "http://youtu.be/"):
        if raw.startswith(prefix):
            return raw[len(prefix) :].split("?")[0].split("/")[0] or None
    if "watch?v=" in raw:
        return raw.split("watch?v=", 1)[1].split("&")[0].split("#")[0] or None
    if "/shorts/" in raw:
        return raw.split("/shorts/", 1)[1].split("?")[0].split("/")[0] or None
    return None


def match_work_by_title(title: str, works: list[Work]) -> Work | None:
    needle = normalize_title(title)
    if not needle:
        return None
    exact = [w for w in works if normalize_title(w.title) == needle]
    if len(exact) == 1:
        return exact[0]
    contained = [w for w in works if normalize_title(w.title) and normalize_title(w.title) in needle]
    if len(contained) == 1:
        return contained[0]
    return None


def _list_mine_videos(access_token: str) -> list[dict]:
    resp = httpx.get(
        YT_SEARCH,
        params={"part": "snippet", "forMine": "true", "type": "video", "maxResults": 25},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.info("YouTube search.list failed: %s", resp.text[:200])
        return []
    items = (resp.json() or {}).get("items") or []
    out = []
    for item in items:
        vid = ((item.get("id") or {}).get("videoId")) if isinstance(item.get("id"), dict) else None
        snippet = item.get("snippet") or {}
        if vid:
            out.append({"id": vid, "title": snippet.get("title") or ""})
    return out


def _video_stats(access_token: str, video_ids: list[str]) -> dict[str, int]:
    ids = [v for v in video_ids if v][:50]
    if not ids:
        return {}
    resp = httpx.get(
        YT_VIDEOS,
        params={"part": "statistics", "id": ",".join(ids)},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.info("YouTube videos.list failed: %s", resp.text[:200])
        return {}
    stats: dict[str, int] = {}
    for item in (resp.json() or {}).get("items") or []:
        vid = item.get("id")
        views = int((item.get("statistics") or {}).get("viewCount") or 0)
        if vid and views > 0:
            stats[str(vid)] = views
    return stats


def _analytics_views(access_token: str) -> int:
    end = date.today()
    start = end - timedelta(days=28)
    resp = httpx.get(
        YT_ANALYTICS,
        params={
            "ids": "channel==MINE",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "metrics": "views,likes,estimatedMinutesWatched",
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.info("YouTube Analytics unavailable: %s", resp.text[:200])
        return 0
    rows = (resp.json() or {}).get("rows") or []
    if not rows:
        return 0
    try:
        return int(rows[0][0] or 0)
    except (TypeError, ValueError, IndexError):
        return 0


def should_write_channel_snapshot(channel_views: int, matched_video_views: list[int]) -> bool:
    """Avoid double-counting channel lifetime views when per-video matches exist."""
    return int(channel_views or 0) > 0 and not any(int(v or 0) > 0 for v in matched_video_views)


def sync_user(db: Session, user: User) -> dict:
    if not configured():
        return {"source": "official_api", "provider": "youtube", "synced": 0, "reason": "not_configured"}
    row = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == "youtube")
        .first()
    )
    if not row or not row.official_token:
        return {"source": "official_api", "provider": "youtube", "synced": 0, "reason": "not_bound"}
    token = _access_token_for(db, row)
    if not token:
        return {"source": "official_api", "provider": "youtube", "synced": 0, "reason": "token_expired"}
    profile = _channel_profile(token) or {}
    views = _analytics_views(token) or int(profile.get("view_count") or 0)
    works = db.query(Work).filter(Work.owner_id == user.id).all()
    videos = _list_mine_videos(token)
    linked: dict[str, Work] = {}
    for delivery in (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id, DistributionDelivery.store_url.isnot(None))
        .all()
    ):
        vid = extract_youtube_id(delivery.store_url)
        work = next((w for w in works if w.id == delivery.work_id), None)
        if vid and work:
            linked[vid] = work
    for video in videos:
        work = match_work_by_title(video["title"], works)
        if work:
            linked[video["id"]] = work
    stats = _video_stats(token, list(linked.keys()))
    stored = 0
    if should_write_channel_snapshot(views, [stats.get(vid) or 0 for vid in linked]):
        if upsert_metric_snapshot(
            db,
            user_id=user.id,
            channel_code="youtube_music",
            period_key="latest",
            source="official_api",
            streams=views,
            usable=False,
            raw={"channel_id": profile.get("id") or row.external_release_id, "window": "28d_or_lifetime"},
        ):
            stored += 1
    for vid, work in linked.items():
        count = stats.get(vid) or 0
        if count <= 0:
            continue
        if upsert_metric_snapshot(
            db,
            user_id=user.id,
            channel_code="youtube_music",
            period_key="latest",
            source="official_api",
            streams=count,
            work_id=work.id,
            usable=False,
            raw={"video_id": vid, "matched": work.title},
        ):
            stored += 1
    db.commit()
    if stored <= 0:
        return {
            "source": "official_api",
            "provider": "youtube",
            "synced": 0,
            "reason": "no_data",
            "usable_for_settlement": False,
        }
    return {
        "source": "official_api",
        "provider": "youtube",
        "synced": stored,
        "streams": views,
        "matched_videos": len([vid for vid, _w in linked.items() if stats.get(vid)]),
        "channel_id": profile.get("id") or row.external_release_id,
        "usable_for_settlement": False,
        "reason": "ok",
    }


def frontend_redirect() -> str:
    base = settings.frontend_base_url.rstrip("/")
    return f"{base}/packageCreator/pages/accounts/index?youtube=connected"
