"""Ops console API. Staff roles, not the public app."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.schemas import User
from app.services.distribution.channel_fields import CHANNEL_REQUIRED_FIELDS, FIELD_CATALOG, FIELD_STATUS
from app.services.distribution.fee_collection import fee_collection_policy
from app.services.ops.automation_graduation import GRADUATION_DAYS, GRADUATION_MIN_ORDERS
from app.services.ops.channel_stats import channel_automation_rows, match_rates_from_snapshots
from app.services.ops.maturity import retention_policy, sla_alert, wallet_tie
from app.services.ops.orders import (
    claim_order,
    inbox_counts,
    list_label_accounts,
    list_orders,
    note_order,
    order_detail,
    request_creator_fields,
)
from app.services.ops.panorama import user_panorama
from app.services.ops.roles import require_ops_role

router = APIRouter(prefix="/admin/ops", tags=["ops-console"])


class NoteBody(BaseModel):
    note: str = ""


class RequestFieldsBody(BaseModel):
    fields: list[str] = []


@router.get("/inbox")
def inbox(user: User = Depends(require_ops_role("distribution", "finance", "moderation")), db: Session = Depends(get_db)):
    return inbox_counts(db)


@router.get("/orders")
def orders(
    status: str | None = None,
    channel_code: str | None = None,
    user: User = Depends(require_ops_role("distribution")),
    db: Session = Depends(get_db),
):
    return {"orders": list_orders(db, status=status, channel_code=channel_code)}


@router.get("/orders/{delivery_id}")
def order(
    delivery_id: str,
    user: User = Depends(require_ops_role("distribution")),
    db: Session = Depends(get_db),
):
    return order_detail(db, delivery_id)


@router.post("/orders/{delivery_id}/claim")
def claim(
    delivery_id: str,
    user: User = Depends(require_ops_role("distribution")),
    db: Session = Depends(get_db),
):
    return claim_order(db, user, delivery_id)


@router.post("/orders/{delivery_id}/note")
def note(
    delivery_id: str,
    body: NoteBody,
    user: User = Depends(require_ops_role("distribution")),
    db: Session = Depends(get_db),
):
    return note_order(db, user, delivery_id, body.note)


@router.post("/orders/{delivery_id}/request-fields")
def request_fields(
    delivery_id: str,
    body: RequestFieldsBody,
    user: User = Depends(require_ops_role("distribution")),
    db: Session = Depends(get_db),
):
    return request_creator_fields(db, user, delivery_id, body.fields)


@router.get("/users/{user_id}")
def person(
    user_id: str,
    user: User = Depends(require_ops_role("finance", "moderation", "distribution")),
    db: Session = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid id") from exc
    found = user_panorama(db, uid)
    if not found:
        raise HTTPException(404, "User not found")
    return found


@router.get("/label-accounts")
def label_accounts(user: User = Depends(require_ops_role("distribution")), db: Session = Depends(get_db)):
    return {"accounts": list_label_accounts(db), "passwords_stored_here": False}


@router.get("/channels")
def channels(user: User = Depends(require_ops_role("distribution"))):
    return {
        "field_status": FIELD_STATUS,
        "fields": FIELD_CATALOG,
        "required": {code: list(fields) for code, fields in CHANNEL_REQUIRED_FIELDS.items()},
    }


@router.get("/generation")
def generation_health(user: User = Depends(require_ops_role("distribution")), db: Session = Depends(get_db)):
    from app.services.ops.generation_health import generation_snapshot

    return generation_snapshot(db)


@router.get("/automation")
def automation(user: User = Depends(require_ops_role("distribution")), db: Session = Depends(get_db)):
    from app.models.schemas import DistributionDelivery

    from app.models.schemas import PlatformMetricSnapshot

    rows = db.query(DistributionDelivery).all()
    packed = [
        {"channel_code": row.channel_code, "status": row.status, "store_url": row.store_url, "last_error": row.last_error}
        for row in rows
    ]
    snaps = db.query(PlatformMetricSnapshot).all()
    rates = match_rates_from_snapshots(
        [
            {
                "channel_code": snap.channel_code,
                "source": snap.source,
                "work_id": str(snap.work_id) if snap.work_id else None,
                "usable_for_settlement": bool(snap.usable_for_settlement),
            }
            for snap in snaps
        ]
    )
    oldest = min((row.created_at for row in rows if row.created_at), default=None)
    from datetime import datetime

    days = (datetime.utcnow() - oldest).days if oldest else 0
    return {"channels": channel_automation_rows(packed, match_rates=rates, days=days)}


@router.get("/policy")
def policy(user: User = Depends(require_ops_role("finance", "distribution"))):
    return {
        "fee": fee_collection_policy(),
        "retention": retention_policy(),
        "graduation": {"days": GRADUATION_DAYS, "min_orders": GRADUATION_MIN_ORDERS},
        "sla": sla_alert([]),
        "payout": "paid_manual",
    }


@router.get("/sla")
def sla(user: User = Depends(require_ops_role("distribution")), db: Session = Depends(get_db)):
    from app.models.schemas import DistributionDelivery

    rows = db.query(DistributionDelivery).all()
    packed = [
        {"id": str(row.id), "status": row.status, "store_url": row.store_url, "created_at": row.created_at}
        for row in rows
    ]
    return sla_alert(packed)


@router.get("/reconciliation")
def reconciliation(user: User = Depends(require_ops_role("finance")), db: Session = Depends(get_db)):
    from sqlalchemy import func

    from app.models.schemas import RoyaltyWallet, Withdrawal

    wallets = db.query(RoyaltyWallet).limit(200).all()
    out = []
    for wallet in wallets:
        paid = (
            db.query(func.coalesce(func.sum(Withdrawal.amount_minor), 0))
            .filter(
                Withdrawal.user_id == wallet.user_id,
                Withdrawal.currency == wallet.currency,
                Withdrawal.status.in_(("paid", "paid_manual")),
            )
            .scalar()
        )
        out.append(
            wallet_tie(
                user_id=str(wallet.user_id),
                available_minor=int(wallet.available_minor or 0),
                pending_minor=int(wallet.pending_minor or 0),
                frozen_minor=int(wallet.frozen_minor or 0),
                lifetime_earned_minor=int(wallet.lifetime_earned_minor or 0),
                paid_minor=int(paid or 0),
            )
        )
    return {"payout": "paid_manual", "auto_payout": False, "rows": out, "untied": sum(1 for row in out if not row["ties"])}
