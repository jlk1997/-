import logging
import uuid

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.surface import is_weapp_surface, require_h5_desk
from app.database import get_db
from app.models.schemas import User, Work
from app.services.royalty.hub import (
    build_creator_hub,
    build_work_ledger,
    display_work_level_keys,
    include_display_snapshot,
)
from app.services.royalty.settlement import export_user_statement, get_user_settlement, list_user_settlements
from app.services.royalty.splits import list_splits, replace_splits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/creator", tags=["creator"])

__all__ = ["display_work_level_keys", "include_display_snapshot", "hub", "settlements", "work_ledger"]


class SplitShareIn(BaseModel):
    user_id: str | None = None
    username: str | None = None
    role: str = "collaborator"
    percent: int = Field(ge=1, le=100)


class SplitSheetIn(BaseModel):
    shares: list[SplitShareIn]


class AutoReleaseBody(BaseModel):
    enabled: bool


def _owned_work(db: Session, user: User, work_id: str) -> Work:
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    return work


@router.get("/hub")
def hub(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_vibe_surface: str | None = Header(default=None, alias="X-Vibe-Surface"),
):
    if not is_weapp_surface(x_vibe_surface):
        try:
            from app.services.seats.service import kick_user_due_harvests

            kick_user_due_harvests(db, user)
        except Exception:
            logger.exception("hub harvest kick failed")
    return build_creator_hub(db, user)


@router.get("/release-calendar")
def release_calendar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.distribution.automation import weekly_release_suggestions
    from app.services.emotion_calendar import week_drop_plan

    return {"suggestions": weekly_release_suggestions(db, user, limit=5), "week_drop": week_drop_plan(db, user)}


@router.get("/auto-release")
def get_auto_release(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.distribution.automation import auto_release_status

    return auto_release_status(db, user)


@router.put("/auto-release")
def put_auto_release(payload: AutoReleaseBody, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    from app.services.distribution.automation import set_auto_release_consent

    return set_auto_release_consent(db, user, payload.enabled)


@router.get("/works/{work_id}/splits")
def work_splits(work_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    work = _owned_work(db, user, work_id)
    return {"shares": list_splits(db, work), "max": 4, "parent_default": 20}


@router.put("/works/{work_id}/splits")
def save_work_splits(
    work_id: str,
    payload: SplitSheetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    work = _owned_work(db, user, work_id)
    return {"shares": replace_splits(db, work, [row.model_dump() for row in payload.shares], actor=user)}


@router.get("/works/{work_id}")
def work_ledger(work_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_work_ledger(db, user, work_id)


@router.get("/settlements")
def settlements(period_key: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"settlements": list_user_settlements(db, user, period_key=period_key)}


@router.get("/statement")
def statement(period_key: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return export_user_statement(db, user, period_key=period_key)


@router.get("/settlements/{batch_id}")
def settlement_detail(batch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_settlement(db, user, batch_id)


@router.get("/pro-export")
def pro_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.royalty.pro_export import export_collection_society_rows

    return export_collection_society_rows(db, user)


class CommuneCreate(BaseModel):
    name: str = ""


class CommuneInvite(BaseModel):
    username: str | None = None
    invite_code: str | None = None


@router.get("/commune")
def get_commune(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.creator.commune import commune_board

    return commune_board(db, user)


@router.post("/commune")
def post_commune(
    payload: CommuneCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.creator.commune import create_commune

    return create_commune(db, user, payload.name)


@router.post("/commune/invite")
def post_commune_invite(
    payload: CommuneInvite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.creator.commune import invite_username, join_commune

    if payload.invite_code:
        return join_commune(db, user, payload.invite_code)
    if not payload.username:
        raise HTTPException(400, "username or invite_code required")
    return invite_username(db, user, payload.username)


@router.post("/commune/leave")
def post_commune_leave(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.creator.commune import leave_commune

    return leave_commune(db, user)


@router.post("/works/{work_id}/share-passport")
def share_work_passport(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.distribution.passport_share import share_passport_to_feed

    return share_passport_to_feed(db, user, work_id)


class RadioTrialBody(BaseModel):
    station: str | None = None


class ClipDropBody(BaseModel):
    url: str
    clip_length: int | None = 15


@router.post("/works/{work_id}/radio-trial")
def start_work_radio_trial(
    work_id: str,
    payload: RadioTrialBody | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.radio.network import start_radio_trial

    return start_radio_trial(db, user, work_id, station=(payload.station if payload else None))


@router.get("/works/{work_id}/radio-trial")
def get_work_radio_trial(work_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.radio.network import describe_radio_trial_for_work

    work = _owned_work(db, user, work_id)
    return describe_radio_trial_for_work(db, work)


@router.post("/works/{work_id}/clip-drops")
def post_work_clip_drop(
    work_id: str,
    payload: ClipDropBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.radio.network import add_clip_drop

    return add_clip_drop(db, user, work_id, url=payload.url, clip_length=payload.clip_length)


@router.get("/works/{work_id}/clip-drops")
def get_work_clip_drops(work_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.radio.network import list_clip_drops

    return {"drops": list_clip_drops(db, user, work_id), "display_only": True}


@router.get("/works/{work_id}/clips")
def list_work_clips(work_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.distribution.catalog import clip_windows
    from app.services.radio.network import list_clip_drops

    work = _owned_work(db, user, work_id)
    windows = clip_windows(getattr(work, "duration", None))
    return {
        "work_id": str(work.id),
        "clip_windows": windows,
        "clip_drops": list_clip_drops(db, user, work_id),
        "display_only": True,
        "note": "15s/30s/60s climax windows. Download the pack, post from your own account, paste the URL back. Not settlement.",
    }


@router.get("/works/{work_id}/clip-pack")
def download_clip_pack(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.distribution.kit import ensure_work_clip_pack

    work = _owned_work(db, user, work_id)
    data, _url = ensure_work_clip_pack(work)
    filename = f"vibe-clips-{str(work.id)[:8]}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/works/{work_id}/originality")
def download_originality_pack(
    work_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    from app.services.stem_assets import ensure_work_originality_pack

    work = _owned_work(db, user, work_id)
    data, _url = ensure_work_originality_pack(work)
    filename = f"vibe-originality-{str(work.id)[:8]}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
            "X-Listing-Asset": "master",
        },
    )
