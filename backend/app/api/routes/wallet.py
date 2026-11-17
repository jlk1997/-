from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.surface import require_h5_desk
from app.config import settings
from app.database import get_db
from app.models.schemas import User
from app.services.royalty.ingest import (
    attach_snapshot_to_work,
    attach_suggested_snapshots,
    ingest_report,
    list_isrc_unmatched_snapshots,
    list_report_imports,
    list_unattached_snapshots,
)
from app.services.royalty.wallet import (
    delete_payout_account,
    list_payout_accounts,
    request_withdrawal,
    upsert_payout_account,
    wallet_overview,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])


class PayoutBody(BaseModel):
    channel: str
    account_name: str | None = None
    account_no: str
    extra: dict | None = None
    is_default: bool = False


class AttachSnapshotBody(BaseModel):
    work_id: str


class WithdrawBody(BaseModel):
    amount_minor: int = Field(gt=0)
    currency: str = "CNY"
    channel: str = "alipay"
    payout_account_id: str | None = None


@router.get("")
def get_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return wallet_overview(db, user)


@router.get("/payout-accounts")
def payouts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"accounts": list_payout_accounts(db, user)}


@router.post("/payout-accounts")
def add_payout(payload: PayoutBody, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    return upsert_payout_account(db, user, payload.model_dump())


@router.delete("/payout-accounts/{account_id}")
def remove_payout(account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    return delete_payout_account(db, user, account_id)


@router.post("/withdraw")
def withdraw(payload: WithdrawBody, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    return request_withdrawal(db, user, payload.model_dump())


class KycRequestBody(BaseModel):
    real_name: str = ""
    id_number: str = ""


@router.post("/kyc-request")
def request_kyc(payload: KycRequestBody | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    from app.services.kyc import request_kyc as start_kyc

    body = payload or KycRequestBody()
    return start_kyc(db, user, real_name=body.real_name, id_number=body.id_number)


@router.post("/kyc/webhook")
async def kyc_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_kyc_signature: str | None = Header(default=None, alias="X-Kyc-Signature"),
):
    from app.services.kyc import apply_provider_result, provider_configured

    secret = (settings.kyc_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="KYC webhook secret not configured")
    if not provider_configured() or x_kyc_signature != secret:
        raise HTTPException(status_code=401, detail="Invalid KYC webhook")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    try:
        import uuid as _uuid

        uid = _uuid.UUID(str(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid user_id") from exc
    target = db.query(User).filter(User.id == uid).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return apply_provider_result(
        db,
        target,
        verified=bool(body.get("verified") or body.get("match") or body.get("passed")),
        rejected=bool(body.get("rejected") or body.get("status") == "rejected"),
    )


@router.get("/reports")
def list_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"imports": list_report_imports(db, user)}


@router.post("/reports/rematch")
def rematch_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    from app.services.royalty.ingest import rematch_unattached_snapshots

    return rematch_unattached_snapshots(db, user.id)


@router.get("/unattached")
def unattached_snapshots(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"snapshots": list_unattached_snapshots(db, user)}


@router.get("/isrc-blocked")
def isrc_blocked_snapshots(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"snapshots": list_isrc_unmatched_snapshots(db, user_id=user.id)}


@router.post("/unattached/attach-suggested")
def attach_suggested(user: User = Depends(get_current_user), db: Session = Depends(get_db), _desk: None = Depends(require_h5_desk)):
    return attach_suggested_snapshots(db, user)


@router.post("/unattached/{snapshot_id}/attach")
def attach_unattached(
    snapshot_id: str,
    payload: AttachSnapshotBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    return attach_snapshot_to_work(db, user, snapshot_id, payload.work_id)


@router.post("/reports")
async def upload_report(
    file: UploadFile = File(...),
    source: str = Form("user_export"),
    distributor_code: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _desk: None = Depends(require_h5_desk),
):
    content = await file.read()
    return ingest_report(
        db,
        user=user,
        content=content,
        filename=file.filename or "report.csv",
        source=source,
        distributor_code=distributor_code,
        default_user_id=user.id,
    )
