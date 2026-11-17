"""Official Chartmetric API — display-only streams. No settlement."""

from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import CreatorIdentityBinding, Release, ReleaseMetadata, User, Work
from app.services.royalty.snapshots import upsert_metric_snapshot

logger = logging.getLogger(__name__)

CHARTMETRIC_HOST = "https://api.chartmetric.com"
_token_cache: dict[str, object] = {"token": "", "exp": 0.0}


def configured() -> bool:
    return bool(getattr(settings, "chartmetric_api_key", "").strip())


def _access_token() -> str:
    now = time.time()
    cached = str(_token_cache.get("token") or "")
    exp = float(_token_cache.get("exp") or 0)
    if cached and exp > now + 60:
        return cached
    refresh = settings.chartmetric_api_key.strip()
    resp = httpx.post(
        f"{CHARTMETRIC_HOST}/api/token",
        json={"refreshtoken": refresh},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token") or ""
    if not token:
        raise RuntimeError("chartmetric token missing")
    _token_cache["token"] = token
    _token_cache["exp"] = now + int(data.get("expires_in") or 3600)
    return token


def _get(path: str) -> dict:
    token = _access_token()
    resp = httpx.get(
        f"{CHARTMETRIC_HOST}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if resp.status_code == 401:
        _token_cache["token"] = ""
        _token_cache["exp"] = 0
        token = _access_token()
        resp = httpx.get(
            f"{CHARTMETRIC_HOST}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _isrc_variants(isrc: str) -> list[str]:
    compact = isrc.replace("-", "").replace(" ", "").upper()
    variants = [compact]
    if isrc != compact:
        variants.append(isrc.strip())
    return variants


def _chartmetric_id(isrc: str) -> int | None:
    for variant in _isrc_variants(isrc):
        try:
            data = _get(f"/api/track/isrc/{variant}/get-ids")
        except Exception as exc:
            logger.info("Chartmetric get-ids failed for %s: %s", variant, exc)
            continue
        rows = data.get("obj") if isinstance(data, dict) else None
        if not rows:
            continue
        first = rows[0] if isinstance(rows, list) else rows
        ids = (first or {}).get("chartmetric_ids") or []
        if ids:
            return int(ids[0])
    return None


def _as_int(value) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def fetch_track_display_stats(isrc: str | None = None, cmid: int | None = None) -> list[dict]:
    if not cmid and isrc:
        cmid = _chartmetric_id(isrc)
    if not cmid:
        return []
    data = _get(f"/api/track/{cmid}")
    obj = data.get("obj") if isinstance(data, dict) else None
    stats = (obj or {}).get("cm_statistics") or {}
    out = []
    mapping = (
        ("spotify", _as_int(stats.get("sp_streams"))),
        ("youtube_music", _as_int(stats.get("youtube_views"))),
        ("tiktok_music", _as_int(stats.get("num_tt_videos"))),
        ("apple_music", _as_int(stats.get("itunes_plays") or stats.get("am_streams"))),
    )
    for channel, streams in mapping:
        if streams > 0:
            out.append({"channel_code": channel, "streams": streams, "chartmetric_id": cmid})
    return out


def _iter_artist_tracks(data: dict) -> list[dict]:
    obj = data.get("obj")
    items = obj if isinstance(obj, list) else (obj.get("tracks") if isinstance(obj, dict) else None) or []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        isrc = item.get("isrc") or item.get("isrcs")
        if isinstance(isrc, list):
            isrc = isrc[0] if isrc else None
        cmid = item.get("cm_track") or item.get("id")
        out.append({"isrc": isrc, "cmid": int(cmid) if cmid else None, "name": item.get("name")})
    return out


def _user_works_by_isrc(db: Session, user: User) -> dict[str, tuple[Work | None, Release | None]]:
    mapped: dict[str, tuple[Work | None, Release | None]] = {}
    for work in db.query(Work).filter(Work.owner_id == user.id, Work.isrc.isnot(None)).all():
        key = (work.isrc or "").replace("-", "").replace(" ", "").upper()
        if key:
            mapped[key] = (work, None)
    metas = (
        db.query(ReleaseMetadata)
        .join(Release, Release.id == ReleaseMetadata.release_id)
        .filter(Release.owner_id == user.id, ReleaseMetadata.isrc.isnot(None))
        .all()
    )
    for meta in metas:
        key = (meta.isrc or "").replace("-", "").replace(" ", "").upper()
        if not key:
            continue
        release = db.query(Release).filter(Release.id == meta.release_id).first()
        work = db.query(Work).filter(Work.id == release.work_id).first() if release else None
        mapped[key] = (work, release)
    return mapped


def sync_artist(db: Session, user: User, *, limit: int = 20) -> dict:
    if not configured():
        return {"source": "licensed_analytics", "provider": "chartmetric_artist", "synced": 0, "reason": "not_configured"}
    row = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == "chartmetric")
        .first()
    )
    artist_id = (row.external_release_id or "").strip() if row else ""
    if not artist_id.isdigit():
        return {"source": "licensed_analytics", "provider": "chartmetric_artist", "synced": 0, "reason": "not_bound"}
    try:
        data = _get(f"/api/artist/{int(artist_id)}/tracks?limit={limit}")
    except Exception as exc:
        logger.warning("Chartmetric artist tracks failed: %s", exc)
        return {"source": "licensed_analytics", "provider": "chartmetric_artist", "synced": 0, "reason": "provider_error"}
    owned = _user_works_by_isrc(db, user)
    stored = 0
    for track in _iter_artist_tracks(data)[:limit]:
        isrc = (track.get("isrc") or "").replace("-", "").replace(" ", "").upper()
        work, release = owned.get(isrc, (None, None))
        if not work and track.get("name"):
            title = str(track["name"]).strip()
            work = db.query(Work).filter(Work.owner_id == user.id, Work.title == title).first()
        try:
            stats = fetch_track_display_stats(isrc=track.get("isrc"), cmid=track.get("cmid"))
        except Exception:
            continue
        for row_stat in stats:
            if upsert_metric_snapshot(
                db,
                user_id=user.id,
                channel_code=row_stat["channel_code"],
                period_key="latest",
                source="licensed_analytics",
                streams=row_stat["streams"],
                work_id=work.id if work else None,
                release_id=release.id if release else None,
                raw={"artist_id": artist_id, "isrc": track.get("isrc"), **row_stat},
            ):
                stored += 1
    db.commit()
    return {
        "source": "licensed_analytics",
        "provider": "chartmetric_artist",
        "synced": stored,
        "usable_for_settlement": False,
        "reason": "ok" if stored else "no_match",
    }


def sync_user(db: Session, user: User, *, limit: int = 20) -> dict:
    if not configured():
        return {"source": "licensed_analytics", "synced": 0, "reason": "not_configured"}
    metas = (
        db.query(ReleaseMetadata)
        .join(Release, Release.id == ReleaseMetadata.release_id)
        .filter(Release.owner_id == user.id, ReleaseMetadata.isrc.isnot(None))
        .limit(limit)
        .all()
    )
    works = (
        db.query(Work)
        .filter(Work.owner_id == user.id, Work.isrc.isnot(None))
        .limit(limit)
        .all()
    )
    seen: set[str] = set()
    jobs: list[tuple[str, Work | None, Release | None]] = []
    for meta in metas:
        isrc = (meta.isrc or "").strip()
        if not isrc or isrc in seen:
            continue
        seen.add(isrc)
        release = db.query(Release).filter(Release.id == meta.release_id).first()
        work = db.query(Work).filter(Work.id == release.work_id).first() if release else None
        jobs.append((isrc, work, release))
    for work in works:
        isrc = (work.isrc or "").strip()
        if not isrc or isrc in seen:
            continue
        seen.add(isrc)
        jobs.append((isrc, work, None))

    stored = 0
    errors = 0
    for isrc, work, release in jobs[:limit]:
        try:
            stats = fetch_track_display_stats(isrc)
        except Exception as exc:
            logger.warning("Chartmetric track sync failed for %s: %s", isrc, exc)
            errors += 1
            continue
        for row in stats:
            if upsert_metric_snapshot(
                db,
                user_id=user.id,
                channel_code=row["channel_code"],
                period_key="latest",
                source="licensed_analytics",
                streams=row["streams"],
                work_id=work.id if work else None,
                release_id=release.id if release else None,
                raw={"isrc": isrc, **row},
            ):
                stored += 1
    db.commit()
    return {
        "source": "licensed_analytics",
        "provider": "chartmetric",
        "synced": stored,
        "tracks": len(jobs),
        "errors": errors,
        "usable_for_settlement": False,
        "reason": "ok" if stored or jobs else "no_isrc",
    }
