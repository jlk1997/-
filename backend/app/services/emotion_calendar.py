"""Emotion calendar — daily mood journal, monthly album, weekly drop."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.schemas import EmotionJournalEntry, Playlist, PlaylistTrack, User, Work

MOOD_TO_STATION = {
    "calm": "calm",
    "healing": "calm",
    "peaceful": "calm",
    "sad": "calm",
    "melancholy": "calm",
    "energetic": "commute",
    "city": "commute",
    "hopeful": "commute",
    "joy": "commute",
    "energy": "commute",
    "night": "night",
    "lofi": "night",
    "dream": "night",
    "ambient": "night",
    "sleep": "night",
    "study": "focus",
    "focus": "focus",
}


def log_entry(
    db: Session,
    user_id: uuid.UUID,
    *,
    work_id: str | None = None,
    arousal: float | None = None,
    valence: float | None = None,
    mood_tags: list[str] | None = None,
    note: str | None = None,
    entry_date: date | None = None,
) -> dict[str, Any]:
    today = entry_date or date.today()
    wid = None
    if work_id:
        try:
            wid = uuid.UUID(work_id)
        except ValueError:
            wid = None
    if wid and (arousal is None or valence is None):
        work = db.query(Work).filter(Work.id == wid, Work.owner_id == user_id).first()
        if work:
            arousal = arousal if arousal is not None else work.arousal
            valence = valence if valence is not None else work.valence
            mood_tags = mood_tags or (work.moods or [])

    row = EmotionJournalEntry(
        user_id=user_id,
        entry_date=today,
        arousal=arousal,
        valence=valence,
        work_id=wid,
        mood_tags=mood_tags or [],
        note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _entry_dict(row)


def list_entries(db: Session, user_id: uuid.UUID, *, days: int = 60) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=max(7, min(days, 365)))
    rows = (
        db.query(EmotionJournalEntry)
        .filter(EmotionJournalEntry.user_id == user_id, EmotionJournalEntry.entry_date >= since)
        .order_by(EmotionJournalEntry.entry_date.desc(), EmotionJournalEntry.created_at.desc())
        .all()
    )
    return [_entry_dict(r) for r in rows]


def _emotion_album_tag(year: int, month: int) -> str:
    return f"emotion_album_{year}_{month:02d}"


def ensure_monthly_playlist(
    db: Session,
    user_id: uuid.UUID,
    *,
    year: int,
    month: int,
    title: str,
    work_ids: list[str],
) -> str | None:
    """Create or refresh a private playlist from monthly emotion journal works."""
    if not work_ids:
        return None
    tag = _emotion_album_tag(year, month)

    existing = db.query(Playlist).filter(Playlist.owner_id == user_id).all()
    playlist: Playlist | None = None
    for row in existing:
        jc = row.journey_config or {}
        if jc.get("emotion_album_tag") == tag:
            playlist = row
            break

    if playlist is None:
        playlist = Playlist(
            owner_id=user_id,
            title=title,
            journey_config={
                "type": "emotion_album",
                "emotion_album_tag": tag,
                "year": year,
                "month": month,
                "share_text": f"我的{year}年{month}月情绪专辑",
            },
            visibility="private",
        )
        db.add(playlist)
        db.flush()
    else:
        playlist.title = title
        db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist.id).delete()

    for i, wid in enumerate(work_ids):
        try:
            work_uuid = uuid.UUID(wid)
        except ValueError:
            continue
        db.add(PlaylistTrack(playlist_id=playlist.id, work_id=work_uuid, position=i + 1))
    db.commit()
    return str(playlist.id)


def monthly_album(db: Session, user_id: uuid.UUID, *, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    today = date.today()
    year = year or today.year
    month = month or today.month
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows = (
        db.query(EmotionJournalEntry)
        .filter(
            EmotionJournalEntry.user_id == user_id,
            EmotionJournalEntry.entry_date >= start,
            EmotionJournalEntry.entry_date < end,
            EmotionJournalEntry.work_id.isnot(None),
        )
        .order_by(EmotionJournalEntry.entry_date.asc())
        .all()
    )
    work_ids = [str(r.work_id) for r in rows if r.work_id]
    works = {str(w.id): w for w in db.query(Work).filter(Work.id.in_([r.work_id for r in rows if r.work_id])).all()}
    tracks = []
    for r in rows:
        if not r.work_id:
            continue
        w = works.get(str(r.work_id))
        if w:
            tracks.append({"work_id": str(w.id), "title": w.title, "date": r.entry_date.isoformat(), "cover_url": w.cover_url})
    avg_a = sum(r.arousal or 0 for r in rows) / max(len(rows), 1)
    avg_v = sum(r.valence or 0 for r in rows) / max(len(rows), 1)
    title = f"{year}年{month}月情绪专辑"
    playlist_id = (
        ensure_monthly_playlist(db, user_id, year=year, month=month, title=title, work_ids=work_ids)
        if work_ids
        else None
    )
    return {
        "year": year,
        "month": month,
        "title": title,
        "track_count": len(tracks),
        "work_ids": work_ids,
        "tracks": tracks,
        "avg_arousal": round(avg_a, 2),
        "avg_valence": round(avg_v, 2),
        "playlist_id": playlist_id,
    }


def _entry_dict(row: EmotionJournalEntry) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entry_date": row.entry_date.isoformat(),
        "arousal": row.arousal,
        "valence": row.valence,
        "work_id": str(row.work_id) if row.work_id else None,
        "mood_tags": row.mood_tags or [],
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def infer_station_from_moods(
    tags: list[str] | None,
    *,
    valence: float | None = None,
    arousal: float | None = None,
    now: datetime | None = None,
) -> str:
    from app.services.radio.network import station_of_the_day

    tags_l = {str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()}
    for tag, station in MOOD_TO_STATION.items():
        if tag in tags_l:
            return station
    if arousal is not None and arousal >= 3.5:
        return "commute"
    if valence is not None and valence <= 2.5:
        return "calm"
    if arousal is not None and arousal <= 2.2:
        return "night"
    return station_of_the_day(now=now)


def _journal_week(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    since = date.today() - timedelta(days=7)
    rows = (
        db.query(EmotionJournalEntry)
        .filter(EmotionJournalEntry.user_id == user_id, EmotionJournalEntry.entry_date >= since)
        .order_by(EmotionJournalEntry.entry_date.desc())
        .all()
    )
    tags: list[str] = []
    for row in rows:
        tags.extend(str(tag) for tag in (row.mood_tags or []) if tag)
    scored = [row for row in rows if row.arousal is not None or row.valence is not None]
    avg_a = sum(float(row.arousal or 0) for row in scored) / max(len(scored), 1) if scored else None
    avg_v = sum(float(row.valence or 0) for row in scored) / max(len(scored), 1) if scored else None
    return {
        "entries": len(rows),
        "mood_tags": list(dict.fromkeys(tags))[:8],
        "avg_arousal": round(avg_a, 2) if avg_a is not None else None,
        "avg_valence": round(avg_v, 2) if avg_v is not None else None,
    }


def week_drop_plan(db: Session, user: User) -> dict[str, Any]:
    """Map this week's journal to a radio station and one unpublished drop."""
    from app.models.schemas import Release
    from app.services.radio.network import STATIONS, describe_radio_trial, station_of_the_day

    journal = _journal_week(db, user.id)
    station = infer_station_from_moods(
        journal["mood_tags"],
        valence=journal["avg_valence"],
        arousal=journal["avg_arousal"],
    )
    spec = STATIONS.get(station) or STATIONS["daily"]
    active = {
        row.work_id
        for row in db.query(Release)
        .filter(Release.owner_id == user.id, Release.status.in_(("queued", "delivering", "live")))
        .all()
    }
    wanted = {str(tag).lower() for tag in journal["mood_tags"]}
    candidates: list[tuple[int, Work]] = []
    for work in (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(40)
        .all()
    ):
        if work.id in active or not (work.audio_url or work.storage_key):
            continue
        moods = {str(mood).lower() for mood in (work.moods or [])}
        overlap = len(moods & wanted)
        candidates.append((overlap, work))
    from app.services.royalty.hub import is_workbench_master, prefer_workbench_masters

    pool = prefer_workbench_masters([row[1] for row in candidates])
    kept = {row.id for row in pool}
    candidates = [row for row in candidates if row[1].id in kept]
    candidates.sort(key=lambda item: (item[0], item[1].created_at or datetime.min), reverse=True)
    work = candidates[0][1] if candidates else None
    trial = describe_radio_trial(db, work) if work else None
    if not work:
        next_action = "create"
        why = "empty"
    elif trial and trial.get("live"):
        next_action = "watch_trial"
        why = "emotion_week" if candidates and candidates[0][0] > 0 else "unpublished"
    elif trial and trial.get("status") == "ended":
        next_action = trial.get("next_action") or "release"
        why = "trial_ended"
    else:
        next_action = "radio_trial"
        why = "emotion_week" if candidates and candidates[0][0] > 0 else "unpublished"
    return {
        "station": station,
        "station_name": spec.get("name"),
        "station_blurb": spec.get("blurb"),
        "station_of_day": station_of_the_day(),
        "why": why,
        "next_action": next_action,
        "journal": journal,
        "work": (
            {
                "work_id": str(work.id),
                "title": work.title,
                "cover_url": work.cover_url,
                "moods": work.moods or [],
                "qc_ready": getattr(work, "release_status", None) == "qc_ready",
                "from_workbench": is_workbench_master(work),
                "channel_suggestion": (trial or {}).get("channel_suggestion"),
            }
            if work
            else None
        ),
        "radio_trial": trial,
    }
