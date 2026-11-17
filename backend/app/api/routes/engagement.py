"""Engagement API: listen checkins, mood radio, remix chain."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.database import get_db
from app.models.schemas import User
from app.services.listen_engagement import RADIO_RULES, mood_radio_daily, remix_chain_depth, submit_listen_checkin, get_work_engagement_stats

router = APIRouter(prefix="/engagement", tags=["engagement"])


class ListenCheckinRequest(BaseModel):
    work_id: str
    listen_ratio: float = Field(ge=0, le=1)
    arousal: float | None = None
    valence: float | None = None
    mood_tags: list[str] = Field(default_factory=list)
    station: str | None = None


@router.post("/listen-checkin")
def listen_checkin(
    payload: ListenCheckinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return submit_listen_checkin(
        db,
        user.id,
        work_id=payload.work_id,
        listen_ratio=payload.listen_ratio,
        arousal=payload.arousal,
        valence=payload.valence,
        mood_tags=payload.mood_tags,
        station=payload.station,
    )


@router.get("/mood-radio")
def mood_radio(
    limit: int = 3,
    station: str | None = None,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.radio.network import radio_network_payload

    payload = radio_network_payload(db, user.id if user else None, station=station, limit=min(max(limit, 1), 12))
    if not payload["tracks"]:
        payload["tracks"] = mood_radio_daily(db, user.id if user else None, limit=min(max(limit, 1), 10))
    return payload


@router.get("/radio/stations")
def radio_stations(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    from app.services.radio.network import radio_network_payload

    return radio_network_payload(db, user.id if user else None, limit=8)


@router.get("/radio/stations/{station}")
def radio_station(
    station: str,
    limit: int = 8,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.radio.network import radio_network_payload

    return radio_network_payload(db, user.id if user else None, station=station, limit=min(max(limit, 1), 12))


@router.get("/radio/chart")
def radio_chart(db: Session = Depends(get_db)):
    from app.services.radio.network import weekly_radio_chart

    return {"chart": weekly_radio_chart(db, limit=8)}


@router.get("/remix-chain/{work_id}")
def remix_chain(work_id: str, db: Session = Depends(get_db)):
    return remix_chain_depth(db, work_id)


@router.get("/duel-quota")
def duel_quota(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.duels import get_duel_quota

    return get_duel_quota(db, user)


@router.get("/work-stats/{work_id}")
def work_engagement_stats(work_id: str, db: Session = Depends(get_db)):
    return get_work_engagement_stats(db, work_id)


@router.get("/creator-weekly-summary")
def creator_weekly_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.creator_weekly_digest import get_creator_weekly_summary

    return get_creator_weekly_summary(db, user.id)
