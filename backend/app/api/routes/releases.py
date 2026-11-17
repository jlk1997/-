from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.api.surface import require_h5_desk
from app.database import get_db
from app.models.schemas import User
from app.services.distribution import service as dist
from app.services.distribution.channel_fields import CHANNEL_REQUIRED_FIELDS
from app.services.distribution.catalog import (
    channel_automation_level,
    channel_capability,
    channel_delivery_mode,
    channel_sop,
    channel_upload_url,
    connected_channel_codes,
    default_upload_channels,
    list_aggregator_partners,
    list_channels,
    list_portal_channels,
    optional_assist_channels,
    seed_distribution_catalog,
)
from app.services.distribution.asset_profiles import profile_payload

router = APIRouter(prefix="/releases", tags=["releases"])


class ReleaseCreate(BaseModel):
    work_id: str


class ReleaseUpdate(BaseModel):
    mode: str | None = None
    selected_channels: list[str] | None = None
    distributor_code: str | None = None
    title: str | None = None
    artist_name: str | None = None
    lyrics: str | None = None
    isrc: str | None = None
    upc: str | None = None
    genres: list[str] | None = None
    language: str | None = None
    copyright_year: int | None = None
    ai_disclosed: bool | None = None
    cover_url: str | None = None


class LicenseBody(BaseModel):
    agreement_version: str = "2026-08-19"
    commission_rate: int = Field(default=20, ge=10, le=30)


class AutoSubmitBody(BaseModel):
    consent: bool = False
    agreement_version: str = "2026-08-19"
    commission_rate: int = Field(default=20, ge=10, le=30)
    mode: str | None = None
    title: str | None = None
    artist_name: str | None = None
    isrc: str | None = None
    selected_channels: list[str] | None = None


class QuickReleaseBody(AutoSubmitBody):
    work_id: str


@router.get("/channels")
def channels(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    seed_distribution_catalog(db)
    db.commit()
    connected = connected_channel_codes(db, _user)
    auto = default_upload_channels(connected=connected)
    optional = optional_assist_channels(connected=connected)
    return {
        "channels": [
            {
                "code": c.code,
                "name": c.name,
                "region": c.region,
                "distributor_code": c.distributor_code,
                "enabled": c.enabled,
                "requirements": c.requirements or {},
                "upload_url": channel_upload_url(c.code),
                "sop": channel_sop(c.code),
                "delivery_mode": channel_delivery_mode(c.code),
                "automation_level": channel_automation_level(c.code),
                "capability": channel_capability(c.code, connected=connected),
                "auto_default": c.code in auto,
                "asset_profile": profile_payload(c.code),
                "required_fields": list(CHANNEL_REQUIRED_FIELDS.get(c.code, ())),
            }
            for c in list_channels(db)
        ],
        "default_channels": auto,
        "optional_channels": optional,
        "portals": list_portal_channels(),
        "aggregators": list_aggregator_partners(),
    }


@router.get("")
def list_releases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"releases": dist.list_user_releases(db, user)}


@router.post("")
def create_release(
    payload: ReleaseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    try:
        return dist.create_or_get_release(db, user, payload.work_id)
    finally:
        from app.services.royalty.hub import invalidate_creator_hub

        invalidate_creator_hub(user.id)


@router.post("/quick")
def quick_release(payload: QuickReleaseBody, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    data = payload.model_dump(exclude_none=True)
    work_id = data.pop("work_id")
    try:
        return dist.quick_release_work(db, user, work_id, data)
    finally:
        from app.services.royalty.hub import invalidate_creator_hub

        invalidate_creator_hub(user.id)


@router.get("/{release_id}/passport")
def get_release_passport(
    release_id: str,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    from app.services.distribution.passport import reveal_passport

    return reveal_passport(db, release_id=release_id, viewer=user)


@router.get("/{release_id}")
def get_release(release_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dist.serialize_release(db, dist._owned_release(db, user, release_id))


@router.get("/{release_id}/kit")
def download_kit(
    release_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    data, _url = dist.ensure_release_kit(db, user, release_id)
    filename = f"vibe-release-{release_id[:8]}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.patch("/{release_id}")
def patch_release(
    release_id: str,
    payload: ReleaseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.update_release(db, user, release_id, payload.model_dump(exclude_unset=True))


@router.post("/{release_id}/qc")
def qc_release(
    release_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.run_qc(db, user, release_id)


@router.post("/{release_id}/license")
def license_release(
    release_id: str,
    payload: LicenseBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.sign_license(db, user, release_id, payload.agreement_version, payload.commission_rate)


@router.post("/{release_id}/submit")
def submit(
    release_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.submit_release(db, user, release_id)


@router.post("/{release_id}/auto-submit")
def auto_submit(
    release_id: str,
    payload: AutoSubmitBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.auto_submit_release(db, user, release_id, payload.model_dump(exclude_none=True))


@router.post("/{release_id}/takedown")
def takedown(
    release_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return dist.takedown_release(db, user, release_id)
