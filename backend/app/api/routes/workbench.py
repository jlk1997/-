from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user, require_scope
from app.api.rate_limits import check_generation_rate_limit
from app.database import get_db
from app.models.schemas import User
from app.services.legal import require_ai_notice
from app.core.mix_graph import publish_preflight
from app.services.workbench import (
    activate_take_session,
    apply_pack,
    claim_pack_demand,
    create_pack_demand,
    deliver_pack_demand,
    get_or_create_session,
    get_session,
    list_effect_packs,
    list_pack_demands,
    list_pending_packs,
    pack_earnings,
    patch_session,
    publish_pack,
    purchase_pack,
    accept_browser_bounce,
    queue_lane_separate,
    queue_pack_preview,
    queue_regen,
    queue_render,
    review_pack,
    suggest_packs_for_work,
    sync_light_editor,
    trim_session,
    undo_session,
)

router = APIRouter(prefix="/workbench", tags=["workbench"])


@router.get("/studio-ir")
def studio_ir_file():
    """Shared impulse for server afir and the browser convolver."""
    from fastapi.responses import FileResponse

    from app.core.studio_ir import ensure_studio_ir

    path = ensure_studio_ir()
    return FileResponse(path, media_type="audio/wav", filename="studio.wav")


class OpenSessionBody(BaseModel):
    work_id: str


class PatchSessionBody(BaseModel):
    mix_graph: dict[str, Any] | None = None
    intensity: float | None = Field(default=None, ge=0, le=1.5)
    lanes: list[dict[str, Any]] | None = None


class ApplyPackBody(BaseModel):
    pack_id: str
    intensity: float = Field(default=1.0, ge=0, le=1.5)


class PublishPackBody(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    price_credits: int = Field(default=0, ge=0, le=50)
    need_tags: list[str] = Field(default_factory=list)
    kind: Literal["scene", "lane", "demand"] | None = None


class ReviewPackBody(BaseModel):
    status: Literal["published", "rejected"]


class RegenBody(BaseModel):
    kind: Literal["extend", "remelt", "same_style"]
    seconds: int = Field(default=15, ge=10, le=40)
    region_start: float | None = Field(default=None, ge=0, le=600)
    region_end: float | None = Field(default=None, ge=0, le=600)
    region_id: str | None = Field(default=None, max_length=32)


class TrimBody(BaseModel):
    start: float = Field(default=0, ge=0, le=600)
    end: float = Field(default=30, ge=0.1, le=600)


class ActivateTakeBody(BaseModel):
    region_id: str = Field(min_length=1, max_length=32)
    take_id: str = Field(min_length=1, max_length=32)


class DemandBody(BaseModel):
    work_id: str
    brief: str = Field(min_length=4, max_length=400)
    need_tags: list[str] = Field(default_factory=list)
    bid_credits: int = Field(default=0, ge=0, le=50)
    reference_work_id: str | None = None


class DeliverDemandBody(BaseModel):
    pack_id: str | None = None
    session_id: str | None = None


class LightSyncBody(BaseModel):
    work_id: str
    semitones: float = 0
    tempo: float = 1.0
    master: bool = False


def _surface(raw: str | None) -> str:
    value = (raw or "h5").lower()
    return "weapp" if value in {"weapp", "mini", "miniprogram"} else "h5"


@router.get("/packs")
def packs(
    scope: str = Query(default="all"),
    surface: str = Query(default="h5"),
    need: str | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return list_effect_packs(db, user, scope=scope, surface=_surface(surface), need=need)


@router.get("/packs/suggest")
def suggest_packs(
    work_id: str = Query(...),
    surface: str = Query(default="h5"),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return suggest_packs_for_work(db, user, work_id, surface=_surface(surface))


@router.get("/packs/earnings")
def earnings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return pack_earnings(db, user)


@router.post("/packs/{pack_id}/purchase")
def buy_pack(
    pack_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return purchase_pack(db, user, pack_id)


@router.post("/packs/{pack_id}/preview")
def preview_pack(
    pack_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return queue_pack_preview(db, user, pack_id)


@router.get("/admin/packs")
def admin_list_packs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_pending_packs(db, user)


@router.post("/sessions/from-light")
def sync_from_light(
    payload: LightSyncBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return sync_light_editor(
        db,
        user,
        payload.work_id,
        semitones=payload.semitones,
        tempo=payload.tempo,
        master=payload.master,
    )


@router.get("/sessions/{session_id}/estimate")
def session_estimate(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_session(db, user, session_id).get("credit_estimate") or {}


@router.post("/sessions/{session_id}/regen")
def regen_session(
    session_id: str,
    payload: RegenBody,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    return queue_regen(
        db,
        user,
        session_id,
        kind=payload.kind,
        seconds=payload.seconds,
        idempotency_key=idempotency_key,
        region_start=payload.region_start,
        region_end=payload.region_end,
        region_id=payload.region_id,
    )


@router.post("/admin/packs/{pack_id}/review")
def admin_review_pack(
    pack_id: str,
    payload: ReviewPackBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return review_pack(db, user, pack_id, status=payload.status)


@router.post("/sessions")
def open_session(
    payload: OpenSessionBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_or_create_session(db, user, payload.work_id)


@router.get("/sessions/{session_id}")
def read_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_session(db, user, session_id)


@router.patch("/sessions/{session_id}")
def update_session(
    session_id: str,
    payload: PatchSessionBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return patch_session(
        db,
        user,
        session_id,
        mix_graph=payload.mix_graph,
        intensity=payload.intensity,
        lanes=payload.lanes,
    )


@router.post("/sessions/{session_id}/apply-pack")
def apply_session_pack(
    session_id: str,
    payload: ApplyPackBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return apply_pack(db, user, session_id, payload.pack_id, intensity=payload.intensity)


@router.post("/sessions/{session_id}/render")
def render_session(
    session_id: str,
    user: User = Depends(require_scope("generate")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    check_generation_rate_limit(user)
    require_ai_notice(user)
    return queue_render(db, user, session_id, idempotency_key=idempotency_key)


@router.post("/sessions/{session_id}/bounce")
async def bounce_session(
    session_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Browser OfflineAudioContext bounce. The server only checks loudness and stores a new stereo work."""
    data = await file.read()
    return accept_browser_bounce(db, user, session_id, data, title=title)


@router.post("/sessions/{session_id}/lanes")
def separate_lanes(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    profile: str = "full",
):
    return queue_lane_separate(db, user, session_id, profile=profile)


@router.post("/sessions/{session_id}/publish-pack")
def publish_session_pack(
    session_id: str,
    payload: PublishPackBody,
    surface: str = Query(default="h5"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return publish_pack(
        db,
        user,
        session_id,
        title=payload.title,
        description=payload.description,
        price_credits=payload.price_credits,
        surface=_surface(surface),
        need_tags=payload.need_tags,
        kind=payload.kind,
    )


@router.get("/sessions/{session_id}/publish-preflight")
def pack_preflight(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = get_session(db, user, session_id)
    return publish_preflight(session.get("mix_graph") or {})


@router.post("/sessions/{session_id}/undo")
def undo(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return undo_session(db, user, session_id)


@router.post("/sessions/{session_id}/trim")
def trim(
    session_id: str,
    payload: TrimBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return trim_session(db, user, session_id, start=payload.start, end=payload.end)


@router.post("/sessions/{session_id}/takes")
def choose_take(
    session_id: str,
    payload: ActivateTakeBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return activate_take_session(db, user, session_id, region_id=payload.region_id, take_id=payload.take_id)


@router.get("/demands")
def demands(
    scope: str = Query(default="open"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_pack_demands(db, user, scope=scope)


@router.post("/demands")
def open_demand(
    payload: DemandBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_pack_demand(
        db,
        user,
        work_id=payload.work_id,
        brief=payload.brief,
        need_tags=payload.need_tags,
        bid_credits=payload.bid_credits,
        reference_work_id=payload.reference_work_id,
    )


@router.post("/demands/{demand_id}/claim")
def claim_demand(
    demand_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return claim_pack_demand(db, user, demand_id)


@router.post("/demands/{demand_id}/deliver")
def deliver_demand(
    demand_id: str,
    payload: DeliverDemandBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return deliver_pack_demand(db, user, demand_id, pack_id=payload.pack_id, session_id=payload.session_id)
