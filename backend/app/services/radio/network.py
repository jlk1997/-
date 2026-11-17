"""First-party emotion radio: official stations, trial drops, clip receipts.

Membership completes pay more. Self-listens stay display-only.
No third-party scraping, no fake ad impressions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.schemas import ClipDrop, ListenCheckin, Post, User, Work, WorkEngagementStats
from app.services.distribution.catalog import CHANNEL_NAMES, channel_display_name
from app.services.distribution.channel_suggest import suggest_channels_for_work
from app.services.listen_engagement import MEMBER_RADIO_PAYOUT_MINOR, RADIO_PAYOUT_MINOR, RADIO_RULES

RADIO_FEATURE_DAYS = 7
RADIO_TRIAL_HOURS = 48
CLIP_PORTALS = {
    "wechat_channels": ("channels.weixin.qq.com", "weixin.qq.com"),
    "douyin_musician": ("www.douyin.com", "v.douyin.com", "www.iesdouyin.com"),
    "kuaishou_musician": ("www.kuaishou.com", "v.kuaishou.com"),
    "tiktok_music": ("www.tiktok.com", "vm.tiktok.com"),
    "bilibili": ("www.bilibili.com", "b23.tv"),
}

STATIONS: dict[str, dict] = {
    "daily": {
        "code": "daily",
        "name": "今日心情",
        "blurb": "按你最近的共鸣口味轮播",
        "moods": set(),
        "hour_bias": None,
    },
    "commute": {
        "code": "commute",
        "name": "通勤电台",
        "blurb": "路上听完记一次完播，不进可提现",
        "moods": {"energetic", "city", "hopeful", "joy", "energy"},
        "hour_bias": (7, 10),
    },
    "night": {
        "code": "night",
        "name": "深夜 lo-fi",
        "blurb": "低唤醒、可循环，适合熬夜和失眠",
        "moods": {"night", "lofi", "calm", "dream", "ambient", "sleep"},
        "hour_bias": (21, 24),
    },
    "calm": {
        "code": "calm",
        "name": "焦虑→平静",
        "blurb": "从紧到松的官方情绪航线",
        "moods": {"calm", "healing", "peaceful", "sad", "melancholy"},
        "hour_bias": None,
    },
    "focus": {
        "code": "focus",
        "name": "学习专注",
        "blurb": "少歌词、稳节奏，写作业和赶工",
        "moods": {"study", "focus", "lofi", "calm"},
        "hour_bias": (13, 17),
    },
    "lineage": {
        "code": "lineage",
        "name": "接龙电台",
        "blurb": "只播 Remix / 续作，看一条情绪怎么传下去",
        "moods": set(),
        "hour_bias": None,
    },
    "weekend": {
        "code": "weekend",
        "name": "周末推新",
        "blurb": "挑战/决斗胜出 + 本周电台榜，发行前的试验田",
        "moods": set(),
        "hour_bias": None,
    },
}


def list_stations(*, now: datetime | None = None) -> list[dict]:
    today = station_of_the_day(now=now)
    return [
        {
            "code": spec["code"],
            "name": spec["name"],
            "blurb": spec["blurb"],
            "of_the_day": spec["code"] == today,
        }
        for spec in STATIONS.values()
    ]


def station_of_the_day(*, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    hour = now.hour
    weekday = now.weekday()
    if hour >= 21 or hour < 6:
        return "night"
    if 7 <= hour <= 9:
        return "commute"
    if weekday >= 5:
        return "weekend"
    if weekday in (2, 3):
        return "calm" if weekday == 3 else "focus"
    return "daily"


def normalize_station(code: str | None) -> str:
    raw = (code or "daily").strip().lower()
    return raw if raw in STATIONS else "daily"


def radio_payout_minor(db: Session, listener_id) -> int:
    """Radio completes are discovery-only. Never book fiat."""
    return 0


def _iso_week_start() -> datetime:
    today = datetime.utcnow().date()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def _iso_week_key(*, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _feature_until(work: Work) -> datetime | None:
    raw = ((work.post_process_status or {}).get("radio_feature") or {})
    until = raw.get("until")
    if not until:
        return None
    try:
        return datetime.fromisoformat(str(until))
    except ValueError:
        return None


def _trial_live(work: Work, *, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    raw = ((work.post_process_status or {}).get("radio_trial") or {})
    if raw.get("status") != "live":
        return False
    try:
        ends = datetime.fromisoformat(str(raw.get("ends_at")))
    except (TypeError, ValueError):
        return False
    return ends > now


def should_retarget_radio_trial(work: Work, *, now: datetime | None = None) -> bool:
    """Hop to unpublished Work B unless this work already has a live trial."""
    return not _trial_live(work, now=now)


def include_owner_radio_trial(*, has_trial: bool, live: bool, superseded: bool) -> bool:
    """Keep a live trial on A; hide ended/empty A once a beautify master exists."""
    if not has_trial:
        return False
    if superseded and not live:
        return False
    return True


def resolve_radio_work(db: Session, work: Work) -> tuple[Work, Work | None]:
    if not should_retarget_radio_trial(work):
        return work, None
    from app.services.royalty.hub import unpublished_workbench_successor

    child = unpublished_workbench_successor(db, work)
    if child is None:
        return work, None
    return child, work


def stamp_radio_feature(
    work: Work,
    *,
    reason: str,
    rank: int = 1,
    stations: list[str] | None = None,
    days: int = RADIO_FEATURE_DAYS,
) -> dict:
    until = datetime.utcnow() + timedelta(days=days)
    payload = {
        "reason": reason,
        "rank": int(rank),
        "stations": stations or ["weekend", "daily"],
        "until": until.isoformat(),
    }
    pps = dict(work.post_process_status or {})
    pps["radio_feature"] = payload
    work.post_process_status = pps
    return payload


def start_radio_trial(db: Session, user: User, work_id: str, *, station: str | None = None, commit: bool = True) -> dict:
    try:
        wid = uuid.UUID(str(work_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    if not (work.audio_url or work.storage_key):
        raise HTTPException(400, "Work has no audio")
    work, origin = resolve_radio_work(db, work)
    current = (work.post_process_status or {}).get("radio_trial") or {}
    now = datetime.utcnow()
    if current.get("status") == "live":
        try:
            if datetime.fromisoformat(str(current.get("ends_at"))) > now:
                return describe_radio_trial_for_work(db, work, origin=origin)
        except (TypeError, ValueError):
            pass
    code = normalize_station(station or station_of_the_day(now=now))
    if code == "daily":
        code = "calm"
    ends = now + timedelta(hours=RADIO_TRIAL_HOURS)
    pps = dict(work.post_process_status or {})
    pps["radio_trial"] = {
        "status": "live",
        "station": code,
        "started_at": now.isoformat(),
        "ends_at": ends.isoformat(),
    }
    work.post_process_status = pps
    if work.visibility == "private":
        work.visibility = "unlisted"
    if commit:
        db.commit()
    return describe_radio_trial_for_work(db, work, origin=origin)


def radio_trial_next_action(db: Session, work: Work, *, live: bool | None = None, status: str | None = None) -> str:
    """After 48h, the default next hop is pick stores / confirm release."""
    if live is None:
        live = _trial_live(work)
    raw = dict((work.post_process_status or {}).get("radio_trial") or {})
    state = status or raw.get("status") or "none"
    if live or state == "live":
        return "watch_trial"
    if state == "ended":
        from app.models.schemas import Release

        release = (
            db.query(Release)
            .filter(Release.work_id == work.id)
            .order_by(Release.updated_at.desc())
            .first()
        )
        if release and release.status in {"queued", "delivering"}:
            return "stores"
        if release and release.status == "live":
            return "sync"
        return "release"
    return "radio_trial"


def describe_radio_trial(db: Session, work: Work) -> dict:
    raw = dict((work.post_process_status or {}).get("radio_trial") or {})
    live = _trial_live(work)
    if raw.get("status") == "live" and not live:
        raw["status"] = "ended"
        pps = dict(work.post_process_status or {})
        pps["radio_trial"] = raw
        work.post_process_status = pps
    stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id == work.id).first()
    suggestion = suggest_channels_for_work(db, work)
    status = raw.get("status") or "none"
    from app.services.royalty.hub import is_workbench_master

    return {
        "work_id": str(work.id),
        "status": status,
        "station": raw.get("station"),
        "started_at": raw.get("started_at"),
        "ends_at": raw.get("ends_at"),
        "live": live,
        "listen_completes": int((stats.listen_completes if stats else 0) or 0),
        "channel_suggestion": suggestion,
        "hours": RADIO_TRIAL_HOURS,
        "next_action": radio_trial_next_action(db, work, live=live, status=status),
        "from_workbench": is_workbench_master(work),
    }


def describe_radio_trial_for_work(db: Session, work: Work, *, origin: Work | None = None) -> dict:
    target, redirected = (work, origin) if origin is not None else resolve_radio_work(db, work)
    desc = describe_radio_trial(db, target)
    if redirected:
        desc["redirected_from_work_id"] = str(redirected.id)
    return desc


def _clip_portal(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for code, hosts in CLIP_PORTALS.items():
        for allowed in hosts:
            needle = allowed[4:] if allowed.startswith("www.") else allowed
            if host == needle or host.endswith("." + needle):
                return code
    return None


def add_clip_drop(db: Session, user: User, work_id: str, *, url: str, clip_length: int | None = None) -> dict:
    try:
        wid = uuid.UUID(str(work_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    from app.services.royalty.hub import resolve_release_work

    work, _origin = resolve_release_work(db, work)
    link = (url or "").strip()
    if not link.startswith("https://"):
        raise HTTPException(400, "Clip URL must be https")
    portal = _clip_portal(link)
    if not portal:
        raise HTTPException(400, "Unsupported clip portal")
    length = int(clip_length or 15)
    if length not in (15, 30):
        length = 15
    row = ClipDrop(
        work_id=work.id,
        owner_id=user.id,
        portal_code=portal,
        url=link,
        clip_length=length,
    )
    db.add(row)
    from app.services.user_engagement import on_engagement_event

    on_engagement_event(db, user.id, "clip_drop", {"work_id": str(work.id), "portal": portal})
    db.commit()
    db.refresh(row)
    return _ser_clip(row)


def list_clip_drops(db: Session, user: User, work_id: str) -> list[dict]:
    try:
        wid = uuid.UUID(str(work_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    from app.services.royalty.hub import unpublished_workbench_successor

    ids = {work.id}
    child = unpublished_workbench_successor(db, work)
    if child:
        ids.add(child.id)
    rows = (
        db.query(ClipDrop)
        .filter(ClipDrop.work_id.in_(ids), ClipDrop.owner_id == user.id)
        .order_by(ClipDrop.created_at.desc())
        .limit(20)
        .all()
    )
    return [_ser_clip(row) for row in rows]


def _ser_clip(row: ClipDrop) -> dict:
    return {
        "id": str(row.id),
        "work_id": str(row.work_id),
        "portal_code": row.portal_code,
        "portal_name": channel_display_name(row.portal_code) or CHANNEL_NAMES.get(row.portal_code, row.portal_code),
        "url": row.url,
        "clip_length": row.clip_length,
        "display_only": True,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def weekly_radio_chart(db: Session, *, limit: int = 5) -> list[dict]:
    since = _iso_week_start()
    rows = (
        db.query(ListenCheckin)
        .filter(ListenCheckin.created_at >= since, ListenCheckin.listen_ratio >= 0.8)
        .all()
    )
    work_ids = list({row.work_id for row in rows})
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()} if work_ids else {}
    counts: dict = {}
    for row in rows:
        work = works.get(row.work_id)
        if not work or work.owner_id == row.user_id:
            continue
        counts[work.id] = counts.get(work.id, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[: max(1, min(limit, 10))]
    out = []
    for index, (work_id, completes) in enumerate(ranked, start=1):
        work = works.get(work_id)
        if not work:
            continue
        out.append(
            {
                "rank": index,
                "work_id": str(work.id),
                "title": work.title,
                "cover_url": work.cover_url,
                "completes": completes,
                "featured": bool(_feature_until(work)),
            }
        )
    return out


def maybe_stamp_chart_features(db: Session, *, commit: bool = True) -> int:
    chart = weekly_radio_chart(db, limit=3)
    stamped = 0
    for row in chart:
        work = db.query(Work).filter(Work.id == uuid.UUID(row["work_id"])).first()
        if not work:
            continue
        from app.services.distribution.automation import stamp_release_priority

        stamp_release_priority(work, reason="radio_chart", rank=row["rank"], label="radio_chart")
        stamp_radio_feature(work, reason="radio_chart", rank=row["rank"], stations=["weekend", "daily"])
        stamped += 1
    if stamped and commit:
        db.commit()
    return stamped


def compute_lineage_seed(db: Session) -> dict | None:
    since = _iso_week_start()
    rows = (
        db.query(Work.parent_work_id, func.count(Work.id))
        .filter(Work.parent_work_id.isnot(None), Work.created_at >= since)
        .group_by(Work.parent_work_id)
        .all()
    )
    if not rows:
        return None
    parent_id, remixes = max(rows, key=lambda item: int(item[1] or 0))
    if not parent_id or int(remixes or 0) < 1:
        return None
    work = db.query(Work).filter(Work.id == parent_id).first()
    if not work:
        return None
    return {
        "work_id": str(work.id),
        "title": work.title,
        "cover_url": work.cover_url,
        "remixes": int(remixes),
        "week": _iso_week_key(),
    }


def maybe_stamp_lineage_seed(db: Session) -> int:
    seed = compute_lineage_seed(db)
    if not seed:
        return 0
    work = db.query(Work).filter(Work.id == uuid.UUID(seed["work_id"])).first()
    if not work:
        return 0
    pps = dict(work.post_process_status or {})
    existing = dict(pps.get("lineage_seed") or {})
    if existing.get("week") == seed["week"]:
        return 0
    until = datetime.utcnow() + timedelta(days=RADIO_FEATURE_DAYS)
    pps["lineage_seed"] = {
        "week": seed["week"],
        "remixes": seed["remixes"],
        "until": until.isoformat(),
    }
    work.post_process_status = pps
    return 1


def _lineage_seed_live(work: Work, *, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    raw = dict((work.post_process_status or {}).get("lineage_seed") or {})
    if raw.get("week") != _iso_week_key(now=now):
        return False
    until = raw.get("until")
    if not until:
        return True
    try:
        return datetime.fromisoformat(str(until)) > now
    except ValueError:
        return True


def expire_radio_trials(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    try:
        works = (
            db.query(Work)
            .filter(Work.post_process_status["radio_trial"]["status"].astext == "live")
            .limit(300)
            .all()
        )
    except Exception:
        db.rollback()
        since = now - timedelta(days=14)
        works = db.query(Work).filter(Work.created_at >= since).limit(300).all()
    ended = 0
    for work in works:
        raw = dict((work.post_process_status or {}).get("radio_trial") or {})
        if raw.get("status") != "live":
            continue
        if _trial_live(work, now=now):
            _maybe_remind_trial_ending(db, work, raw, now)
            continue
        raw["status"] = "ended"
        raw["ended_at"] = now.isoformat()
        pps = dict(work.post_process_status or {})
        pps["radio_trial"] = raw
        work.post_process_status = pps
        ended += 1
        _notify_trial_ended(db, work)
    return ended


def _maybe_remind_trial_ending(db: Session, work: Work, raw: dict, now: datetime) -> None:
    try:
        ends = datetime.fromisoformat(str(raw.get("ends_at")))
    except (TypeError, ValueError):
        return
    if ends - now > timedelta(hours=6) or raw.get("ending_reminded_at"):
        return
    raw["ending_reminded_at"] = now.isoformat()
    pps = dict(work.post_process_status or {})
    pps["radio_trial"] = raw
    work.post_process_status = pps
    from app.services.notifications import create_notification

    create_notification(
        db,
        work.owner_id,
        "radio_trial_ending",
        {
            "work_id": str(work.id),
            "title": work.title,
            "station": raw.get("station"),
            "ends_at": raw.get("ends_at"),
            "message": f"「{work.title}」电台试听局约 6 小时后结束，先看完播再决定上哪家店",
        },
        commit=False,
    )


def _notify_trial_ended(db: Session, work: Work) -> None:
    from app.services.distribution.channel_suggest import suggest_channels_for_work
    from app.services.notifications import create_notification

    stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id == work.id).first()
    completes = int((stats.listen_completes if stats else 0) or 0)
    suggestion = suggest_channels_for_work(db, work)
    reason = (suggestion or {}).get("reason") or "先看完播再选店"
    trial = dict((work.post_process_status or {}).get("radio_trial") or {})
    create_notification(
        db,
        work.owner_id,
        "radio_trial_ended",
        {
            "work_id": str(work.id),
            "title": work.title,
            "listen_completes": completes,
            "channel_suggestion": suggestion,
            "station": trial.get("station"),
            "message": f"「{work.title}」48h 电台试听局已结束，他人完播 {completes}。{reason}",
        },
        commit=False,
    )


def list_owner_clip_drops(db: Session, user: User, *, limit: int = 8) -> list[dict]:
    rows = (
        db.query(ClipDrop)
        .filter(ClipDrop.owner_id == user.id)
        .order_by(ClipDrop.created_at.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )
    return [_ser_clip(row) for row in rows]


def list_owner_radio_trials(db: Session, user: User, *, limit: int = 6) -> list[dict]:
    works = (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(40)
        .all()
    )
    from app.services.royalty.hub import is_workbench_master

    parents = {work.parent_work_id for work in works if is_workbench_master(work)}
    out = []
    for work in works:
        raw = (work.post_process_status or {}).get("radio_trial") or {}
        if not include_owner_radio_trial(
            has_trial=bool(raw),
            live=_trial_live(work),
            superseded=work.id in parents,
        ):
            continue
        desc = describe_radio_trial(db, work)
        if desc.get("status") in {"none"}:
            continue
        out.append({**desc, "title": work.title, "cover_url": work.cover_url})
        if len(out) >= max(1, min(limit, 8)):
            break
    return out


def radio_network_tick(db: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    expired = expire_radio_trials(db, now=now)
    seeded = maybe_stamp_lineage_seed(db)
    stamped = 0
    if now.weekday() == 0:
        stamped = maybe_stamp_chart_features(db, commit=False)
    db.commit()
    return {"expired_trials": expired, "lineage_seeded": seeded, "chart_stamped": stamped}


def _score_for_station(work: Work, post: Post | None, spec: dict, stats: WorkEngagementStats | None) -> float:
    score = float((post.like_count if post else 0) or 0) * 0.3
    moods = {str(m).lower() for m in (work.moods or [])}
    wanted = spec.get("moods") or set()
    if wanted and moods & wanted:
        score += 4.0
    if spec["code"] == "lineage" and work.parent_work_id:
        score += 6.0
    elif spec["code"] == "lineage":
        score -= 3.0
    if spec["code"] == "lineage" and _lineage_seed_live(work):
        score += 10.0
    feature = _feature_until(work)
    if feature and feature > datetime.utcnow():
        stations = ((work.post_process_status or {}).get("radio_feature") or {}).get("stations") or []
        if spec["code"] in stations or spec["code"] in {"weekend", "daily"}:
            score += 8.0
    if _trial_live(work):
        trial = (work.post_process_status or {}).get("radio_trial") or {}
        if trial.get("station") == spec["code"] or spec["code"] in {"daily", "weekend"}:
            score += 5.0
    if stats and stats.resonance_count:
        score += (stats.resonance_total / stats.resonance_count) * 2
    if stats:
        score += min(4.0, float(stats.listen_completes or 0) * 0.15)
    return score


def station_playlist(db: Session, station: str, user_id=None, *, limit: int = 8) -> list[dict]:
    code = normalize_station(station)
    spec = STATIONS[code]
    since = datetime.utcnow() - timedelta(days=21)
    posts = (
        db.query(Post, Work, User)
        .join(Work, Work.id == Post.work_id)
        .join(User, User.id == Post.author_id)
        .filter(Post.visibility.in_(("public", "unlisted")), Post.created_at >= since)
        .order_by(Post.created_at.desc())
        .limit(80)
        .all()
    )
    extras = (
        db.query(Work, User)
        .join(User, User.id == Work.owner_id)
        .filter(Work.visibility.in_(("public", "unlisted")))
        .order_by(Work.created_at.desc())
        .limit(40)
        .all()
    )
    seen = {work.id for _, work, _ in posts}
    rows: list[tuple[Post | None, Work, User]] = [(post, work, author) for post, work, author in posts]
    for work, author in extras:
        if work.id in seen:
            continue
        if (
            _trial_live(work)
            or (_feature_until(work) and _feature_until(work) > datetime.utcnow())
            or _lineage_seed_live(work)
        ):
            rows.append((None, work, author))
            seen.add(work.id)
    seed = compute_lineage_seed(db)
    if seed and code == "lineage":
        try:
            seed_id = uuid.UUID(seed["work_id"])
        except ValueError:
            seed_id = None
        if seed_id and seed_id not in seen:
            seed_work = db.query(Work).filter(Work.id == seed_id).first()
            seed_owner = db.query(User).filter(User.id == seed_work.owner_id).first() if seed_work else None
            if seed_work and seed_owner and (seed_work.audio_url or seed_work.storage_key):
                rows.append((None, seed_work, seed_owner))
                seen.add(seed_work.id)
    work_ids = [work.id for _, work, _ in rows]
    stats_map = {
        row.work_id: row
        for row in (
            db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id.in_(work_ids)).all() if work_ids else []
        )
    }
    scored = []
    for post, work, author in rows:
        if not (work.audio_url or work.storage_key):
            continue
        scored.append((_score_for_station(work, post, spec, stats_map.get(work.id)), post, work, author))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    from app.api.routes.works import _resolve_audio_url

    for _, post, work, author in scored[: max(1, min(limit, 12))]:
        feature = (work.post_process_status or {}).get("radio_feature") or {}
        trial = (work.post_process_status or {}).get("radio_trial") or {}
        out.append(
            {
                "work_id": str(work.id),
                "post_id": str(post.id) if post else None,
                "title": work.title,
                "author": author.username,
                "cover_url": work.cover_url,
                "audio_url": _resolve_audio_url(work),
                "moods": work.moods or [],
                "arousal": work.arousal,
                "valence": work.valence,
                "station": code,
                "featured": bool(_feature_until(work) and _feature_until(work) > datetime.utcnow()),
                "trial": _trial_live(work),
                "lineage_seed": _lineage_seed_live(work),
                "badge": (
                    "lineage_seed"
                    if _lineage_seed_live(work)
                    else (feature.get("reason") if _feature_until(work) else ("trial" if _trial_live(work) else None))
                ),
                "trial_station": trial.get("station"),
                "is_mine": bool(user_id and work.owner_id == user_id),
            }
        )
    return out


def radio_network_payload(db: Session, user_id=None, *, station: str | None = None, limit: int = 8) -> dict:
    code = normalize_station(station or station_of_the_day())
    return {
        "stations": list_stations(),
        "station": next(item for item in list_stations() if item["code"] == code),
        "station_of_day": station_of_the_day(),
        "tracks": station_playlist(db, code, user_id, limit=limit),
        "chart": weekly_radio_chart(db, limit=5),
        "lineage_seed": compute_lineage_seed(db),
        "channel_code": RADIO_RULES["channel_code"],
        "usable_for_settlement": bool(RADIO_RULES.get("usable_for_settlement")),
        "rules": {
            **RADIO_RULES,
            "member_revenue_minor_per_complete": MEMBER_RADIO_PAYOUT_MINOR,
            "trial_hours": RADIO_TRIAL_HOURS,
            "feature_days": RADIO_FEATURE_DAYS,
            "note": "first_party_discovery",
        },
    }
