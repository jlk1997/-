from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user, require_admin
from app.api.surface import require_h5_desk
from app.database import get_db
from app.models.schemas import User, Work
from app.services.royalty import sync_desk as desk

router = APIRouter(prefix="/sync", tags=["sync-desk"])


class ListingBody(BaseModel):
    enabled: bool
    tiers: list[str] | None = None


class OrderBody(BaseModel):
    work_id: str
    tier: str
    pay_method: str = "credits"
    consent: bool = False


@router.get("/tiers")
def tiers():
    return {"tiers": desk.list_tiers(), "agreement_version": desk.SYNC_AGREEMENT}


@router.get("/catalog")
def public_catalog(db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    from app.services.tenant import is_multi_tenant_enabled, tenant_id_for_user

    tenant_id = tenant_id_for_user(user) if user and is_multi_tenant_enabled(db) else None
    return {"listings": desk.catalog(db, tenant_id=tenant_id)}


@router.get("/works/{work_id}")
def work_listing(work_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    from fastapi import HTTPException
    import uuid

    from app.services.work_access import can_view_work

    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(404, "Work not found")
    if not can_view_work(work, user):
        raise HTTPException(404, "Work not found")
    for_owner = user is not None and getattr(user, "id", None) == work.owner_id
    target, origin = desk.resolve_sync_work(db, work, for_owner=for_owner)
    data = desk.serialize_listing(target, db=db)
    if origin:
        data["redirected_from_work_id"] = str(origin.id)
    return data


@router.put("/works/{work_id}")
def save_listing(
    work_id: str,
    payload: ListingBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return desk.set_work_listing(db, user, work_id, enabled=payload.enabled, tiers=payload.tiers)


@router.post("/orders")
def create_order(
    payload: OrderBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return desk.place_order(
        db,
        user,
        work_id=payload.work_id,
        tier=payload.tier,
        pay_method=payload.pay_method,
        consent=payload.consent,
    )


@router.get("/orders")
def my_orders(role: str = "all", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"orders": desk.list_orders(db, user, role=role)}


@router.get("/admin/pending")
def pending_invoices(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"orders": desk.list_pending_invoices(db)}


@router.post("/admin/orders/{order_id}/confirm")
def confirm_invoice(order_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return desk.confirm_invoice(db, admin, order_id)
