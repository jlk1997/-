"""One screen for a person: songs, orders, wallet, payouts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, RoyaltyWallet, User, Withdrawal, Work
from app.services.ops.maturity import reconciliation_row
from app.services.ops.orders import order_brief


def user_panorama(db: Session, user_id) -> dict | None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    works = (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(20)
        .all()
    )
    orders = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.owner_id == user.id)
        .order_by(DistributionDelivery.updated_at.desc())
        .limit(20)
        .all()
    )
    wallets = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == user.id).all()
    withdrawals = (
        db.query(Withdrawal)
        .filter(Withdrawal.user_id == user.id)
        .order_by(Withdrawal.created_at.desc())
        .limit(10)
        .all()
    )
    available = sum(int(row.available_minor or 0) for row in wallets)
    pending = sum(int(row.pending_minor or 0) for row in wallets)
    paid = sum(int(row.amount_minor or 0) for row in withdrawals if row.status == "paid_manual")
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "kyc_status": user.kyc_status,
        "works": [{"id": str(row.id), "title": row.title, "release_status": row.release_status} for row in works],
        "orders": [order_brief(row) for row in orders],
        "wallet": {
            "available_minor": available,
            "pending_minor": pending,
            "frozen_minor": sum(int(row.frozen_minor or 0) for row in wallets),
        },
        "withdrawals": [
            {"id": str(row.id), "amount_minor": row.amount_minor, "status": row.status, "receipt_no": row.receipt_no}
            for row in withdrawals
        ],
        "reconciliation": reconciliation_row(
            user_id=str(user.id),
            available_minor=available,
            pending_minor=pending,
            ledger_net_minor=available + pending + paid,
            withdrawal_paid_minor=paid,
        ),
    }
