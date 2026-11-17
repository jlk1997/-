from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models.schemas import FeatureFlag, LedgerEntry, PayoutAccount, PlatformMetricSnapshot, RoyaltyWallet, User, Withdrawal
from app.services.notifications import create_notification
from app.services.royalty.payout_calendar import payout_calendar, receipt_no_for

KYC_WITHDRAW_STATUS = "verified"


def get_or_create_wallet(db: Session, user_id: uuid.UUID, currency: str = "CNY") -> RoyaltyWallet:
    currency = currency.upper()
    row = (
        db.query(RoyaltyWallet)
        .filter(RoyaltyWallet.user_id == user_id, RoyaltyWallet.currency == currency)
        .first()
    )
    if row:
        return row
    row = RoyaltyWallet(user_id=user_id, currency=currency)
    db.add(row)
    db.flush()
    return row


def lock_wallet(db: Session, user_id: uuid.UUID, currency: str = "CNY") -> RoyaltyWallet:
    """Row-lock the wallet so concurrent withdrawals cannot double-spend available."""
    currency = currency.upper()
    row = (
        db.query(RoyaltyWallet)
        .filter(RoyaltyWallet.user_id == user_id, RoyaltyWallet.currency == currency)
        .with_for_update()
        .first()
    )
    if row:
        return row
    get_or_create_wallet(db, user_id, currency)
    db.flush()
    row = (
        db.query(RoyaltyWallet)
        .filter(RoyaltyWallet.user_id == user_id, RoyaltyWallet.currency == currency)
        .with_for_update()
        .one()
    )
    return row


def add_ledger(
    db: Session,
    *,
    user_id: uuid.UUID,
    wallet: RoyaltyWallet,
    entry_type: str,
    amount_minor: int,
    currency: str,
    source: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        user_id=user_id,
        wallet_id=wallet.id,
        entry_type=entry_type,
        amount_minor=amount_minor,
        currency=currency,
        source=source,
        ref_id=ref_id,
        note=note,
    )
    db.add(entry)
    return entry


def serialize_wallet(wallet: RoyaltyWallet) -> dict:
    return {
        "currency": wallet.currency,
        "pending_minor": wallet.pending_minor or 0,
        "available_minor": wallet.available_minor or 0,
        "frozen_minor": wallet.frozen_minor or 0,
        "lifetime_earned_minor": wallet.lifetime_earned_minor or 0,
    }


def wallet_overview(db: Session, user: User) -> dict:
    wallets = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == user.id).all()
    if not wallets:
        wallets = [get_or_create_wallet(db, user.id, "CNY")]
        db.commit()
    ledger = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.user_id == user.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(50)
        .all()
    )
    withdrawals = (
        db.query(Withdrawal)
        .filter(Withdrawal.user_id == user.id)
        .order_by(Withdrawal.created_at.desc())
        .limit(20)
        .all()
    )
    kyc_status = getattr(user, "kyc_status", None) or "none"
    return {
        "enabled": _wallet_on(db),
        "kyc_status": kyc_status,
        "can_withdraw": kyc_status == KYC_WITHDRAW_STATUS,
        "wallets": [serialize_wallet(w) for w in wallets],
        "ledger": [_ser_ledger(e) for e in ledger],
        "withdrawals": [_ser_withdrawal(w) for w in withdrawals],
        "withdraw_config": _wallet_config(db),
        "withdraw_quote": quote_withdrawal(db, currency=wallets[0].currency if wallets else "CNY"),
        "payout_calendar": payout_calendar(period=_wallet_config(db).get("period") or "weekly"),
        "source_split": source_split(db, user),
    }


def _ser_ledger(e: LedgerEntry) -> dict:
    from app.services.royalty.subjects import accounting_subject

    return {
        "id": str(e.id),
        "type": e.entry_type,
        "amount_minor": e.amount_minor,
        "currency": e.currency,
        "source": e.source,
        "accounting_subject": accounting_subject(e.source, entry_type=e.entry_type),
        "note": e.note,
        "ref_id": e.ref_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _ser_withdrawal(w: Withdrawal) -> dict:
    return {
        "id": str(w.id),
        "user_id": str(w.user_id),
        "amount_minor": w.amount_minor,
        "fee_minor": w.fee_minor,
        "currency": w.currency,
        "channel": w.channel,
        "status": w.status,
        "risk_flag": w.risk_flag,
        "admin_note": w.admin_note,
        "receipt_no": receipt_no_for(w),
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


def source_split(db: Session, user: User) -> dict:
    rows = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.user_id == user.id,
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
        )
        .all()
    )
    from app.services.distribution.catalog import HARVEST_SOURCES
    from app.services.royalty.priority import filter_settlement_snapshots
    from app.services.royalty.subjects import money_bucket

    radio = sync = embed = dsp = harvest = 0
    for row in filter_settlement_snapshots(rows):
        amount = int(row.revenue_minor or 0)
        bucket = money_bucket(row.source)
        if bucket == "radio":
            radio += amount
        elif bucket == "sync":
            sync += amount
        elif bucket == "embed":
            embed += amount
        elif bucket == "dsp":
            dsp += amount
            if (row.source or "") in HARVEST_SOURCES:
                harvest += amount
    if dsp == 0 and harvest == 0:
        from app.models.schemas import SettlementBatch, SettlementLine

        share_rows = (
            db.query(SettlementLine)
            .join(SettlementBatch, SettlementBatch.id == SettlementLine.batch_id)
            .filter(
                SettlementLine.user_id == user.id,
                SettlementBatch.status == "confirmed",
            )
            .all()
        )
        for line in share_rows:
            amount = int(line.net_minor or 0)
            bucket = money_bucket(line.source)
            if bucket == "radio":
                radio += amount
            elif bucket == "sync":
                sync += amount
            elif bucket == "embed":
                embed += amount
            elif bucket == "dsp":
                dsp += amount
                if (line.source or "") in HARVEST_SOURCES:
                    harvest += amount
    return {
        "radio_minor": radio,
        "sync_minor": sync,
        "embed_minor": embed,
        "dsp_minor": dsp,
        "harvest_minor": harvest,
        "warmup_minor": radio,
        "label_royalty_minor": dsp,
        "note": "电台预热是站内科目；席位收割是厂牌版税主路。积分与法币永不加总。",
    }


def admin_list_withdrawals(db: Session) -> list[dict]:
    rows = (
        db.query(Withdrawal)
        .order_by(case((Withdrawal.status == "pending", 0), else_=1), Withdrawal.created_at.desc())
        .limit(100)
        .all()
    )
    if not rows:
        return []
    users = {u.id: u for u in db.query(User).filter(User.id.in_({r.user_id for r in rows})).all()}
    out = []
    for row in rows:
        payload = _ser_withdrawal(row)
        user = users.get(row.user_id)
        payload["user_email"] = user.email if user else None
        payload["user_username"] = user.username if user else None
        payload["kyc_status"] = (user.kyc_status if user else None) or "none"
        out.append(payload)
    return out


def _wallet_on(db: Session) -> bool:
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    return flag.enabled if flag else True


def _wallet_config(db: Session) -> dict:
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    cfg = (flag.config if flag and flag.config else {}) or {}
    return {
        "min_withdraw_cny_fen": int(cfg.get("min_withdraw_cny_fen") or 1000),
        "min_withdraw_usd_cents": int(cfg.get("min_withdraw_usd_cents") or 500),
        "fee_fen": int(cfg.get("fee_fen") or 0),
        "fee_usd_cents": int(cfg.get("fee_usd_cents") or 0),
        "period": cfg.get("period") or "weekly",
    }


def quote_withdrawal(db: Session, *, currency: str = "CNY", amount_minor: int | None = None) -> dict:
    currency = (currency or "CNY").upper()
    cfg = _wallet_config(db)
    minimum = cfg["min_withdraw_cny_fen"] if currency == "CNY" else cfg["min_withdraw_usd_cents"]
    fee = cfg["fee_fen"] if currency == "CNY" else cfg["fee_usd_cents"]
    fee = max(0, int(fee or 0))
    amount = int(amount_minor) if amount_minor is not None else None
    return {
        "currency": currency,
        "min_minor": minimum,
        "fee_minor": fee,
        "fee_on_top": True,
        "receive_minor": amount,
        "debit_minor": None if amount is None else amount + fee,
    }


def ensure_wechat_payout_account(db: Session, user: User, openid: str | None) -> PayoutAccount | None:
    if not openid or not user:
        return None
    existing = db.query(PayoutAccount).filter(PayoutAccount.user_id == user.id).first()
    if existing:
        return None
    row = PayoutAccount(
        user_id=user.id,
        channel="wechat",
        account_name="微信",
        account_no=openid,
        extra={"source": "wechat_openid"},
        is_default=True,
    )
    db.add(row)
    db.flush()
    return row


def upsert_payout_account(db: Session, user: User, payload: dict) -> dict:
    channel = payload.get("channel") or "alipay"
    row = PayoutAccount(
        user_id=user.id,
        channel=channel,
        account_name=payload.get("account_name"),
        account_no=payload["account_no"],
        extra=payload.get("extra") or {},
        is_default=bool(payload.get("is_default")),
    )
    if row.is_default:
        db.query(PayoutAccount).filter(PayoutAccount.user_id == user.id).update({"is_default": False})
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "channel": row.channel,
        "account_name": row.account_name,
        "account_no": row.account_no[-4:].rjust(len(row.account_no), "*") if row.account_no else "",
        "is_default": row.is_default,
    }


def delete_payout_account(db: Session, user: User, account_id: str) -> dict:
    try:
        aid = uuid.UUID(str(account_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid payout account id") from exc
    row = db.query(PayoutAccount).filter(PayoutAccount.id == aid, PayoutAccount.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "Payout account not found")
    in_use = (
        db.query(Withdrawal)
        .filter(
            Withdrawal.payout_account_id == row.id,
            Withdrawal.status.in_(("pending", "processing", "review")),
        )
        .first()
    )
    if in_use:
        raise HTTPException(400, "Payout account is in use")
    db.delete(row)
    db.commit()
    return {"id": str(aid), "deleted": True}


def list_payout_accounts(db: Session, user: User) -> list[dict]:
    rows = db.query(PayoutAccount).filter(PayoutAccount.user_id == user.id).all()
    return [
        {
            "id": str(r.id),
            "channel": r.channel,
            "account_name": r.account_name,
            "account_no_masked": (r.account_no[-4:].rjust(len(r.account_no), "*") if r.account_no else ""),
            "is_default": r.is_default,
        }
        for r in rows
    ]


def request_withdrawal(db: Session, user: User, payload: dict) -> dict:
    if not _wallet_on(db):
        raise HTTPException(403, "Royalty wallet is not enabled")
    kyc = getattr(user, "kyc_status", None) or "none"
    if kyc != KYC_WITHDRAW_STATUS:
        raise HTTPException(403, "KYC verification required")
    currency = (payload.get("currency") or "CNY").upper()
    amount = int(payload["amount_minor"])
    channel = payload.get("channel") or "alipay"
    cfg = _wallet_config(db)
    minimum = cfg["min_withdraw_cny_fen"] if currency == "CNY" else cfg["min_withdraw_usd_cents"]
    if amount < minimum:
        raise HTTPException(400, f"Minimum withdrawal is {minimum}")
    if not payload.get("payout_account_id"):
        raise HTTPException(400, "Payout account required")
    try:
        account_id = uuid.UUID(str(payload["payout_account_id"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid payout account") from exc
    account = db.query(PayoutAccount).filter(PayoutAccount.id == account_id).first()
    if not account or account.user_id != user.id:
        raise HTTPException(403, "Payout account does not belong to this user")
    wallet = lock_wallet(db, user.id, currency)
    quote = quote_withdrawal(db, currency=currency, amount_minor=amount)
    fee = quote["fee_minor"]
    total = quote["debit_minor"]
    if (wallet.available_minor or 0) < total:
        raise HTTPException(400, f"Insufficient available balance (need {total} including fee {fee})")
    risk = amount >= 20000
    wallet.available_minor -= total
    wallet.frozen_minor = (wallet.frozen_minor or 0) + amount
    row = Withdrawal(
        user_id=user.id,
        amount_minor=amount,
        fee_minor=fee,
        currency=currency,
        channel=channel,
        payout_account_id=account.id,
        status="pending",
        risk_flag=risk,
    )
    db.add(row)
    db.flush()
    row.receipt_no = receipt_no_for(row)
    add_ledger(
        db,
        user_id=user.id,
        wallet=wallet,
        entry_type="withdraw_hold",
        amount_minor=-amount,
        currency=currency,
        ref_id=None,
        note="提现冻结",
    )
    if fee:
        add_ledger(
            db,
            user_id=user.id,
            wallet=wallet,
            entry_type="withdraw_fee",
            amount_minor=-fee,
            currency=currency,
            ref_id=None,
            note="提现手续费",
        )
    db.commit()
    from app.services.notifications import create_notification, notify_key_event_sync

    create_notification(
        db,
        user.id,
        "withdrawal_update",
        {
            "id": str(row.id),
            "status": "pending",
            "receipt_no": receipt_no_for(row),
            "amount_minor": row.amount_minor,
            "currency": currency,
            "message": "提现已申请，周五人工打款，不是自动到账",
        },
    )
    notify_key_event_sync(
        db,
        user.id,
        "withdrawal_update",
        title="提现已申请",
        body="申请已进入待打款。周五人工打款，不是自动到账。",
        data={"id": str(row.id), "ref": str(row.id)},
        skip_in_app=True,
    )
    return _ser_withdrawal(row)


def review_withdrawal(db: Session, withdrawal_id: str, *, approve: bool, admin_note: str | None = None) -> dict:
    try:
        wid = uuid.UUID(withdrawal_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid withdrawal id") from exc
    row = db.query(Withdrawal).filter(Withdrawal.id == wid).with_for_update().first()
    if not row:
        raise HTTPException(404, "Withdrawal not found")
    if row.status not in ("pending", "processing", "review"):
        raise HTTPException(400, "Withdrawal already reviewed")
    wallet = lock_wallet(db, row.user_id, row.currency)
    row.admin_note = admin_note
    row.reviewed_at = datetime.utcnow()
    if approve:
        wallet.frozen_minor = max(0, (wallet.frozen_minor or 0) - row.amount_minor)
        row.status = "paid_manual"
        add_ledger(
            db,
            user_id=row.user_id,
            wallet=wallet,
            entry_type="withdraw_paid",
            amount_minor=-row.amount_minor,
            currency=row.currency,
            ref_id=str(row.id),
            note=admin_note or "财务打款",
        )
        create_notification(
            db,
            row.user_id,
            "withdrawal_paid",
            {
                "id": str(row.id),
                "status": "paid_manual",
                "receipt_no": receipt_no_for(row),
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "fee_minor": row.fee_minor or 0,
                "message": "提现已打款",
            },
            commit=False,
        )
        from app.services.notifications import notify_key_event_sync

        notify_key_event_sync(
            db,
            row.user_id,
            "withdrawal_paid",
            title="提现已打款",
            body="财务已人工打款。额度与电台数字不变。",
            data={"id": str(row.id), "ref": str(row.id)},
            skip_in_app=True,
        )
    else:
        wallet.frozen_minor = max(0, (wallet.frozen_minor or 0) - row.amount_minor)
        refund = row.amount_minor + (row.fee_minor or 0)
        wallet.available_minor = (wallet.available_minor or 0) + refund
        row.status = "rejected"
        add_ledger(
            db,
            user_id=row.user_id,
            wallet=wallet,
            entry_type="withdraw_rejected",
            amount_minor=refund,
            currency=row.currency,
            ref_id=str(row.id),
            note=admin_note or "提现驳回，退回可用余额",
        )
        create_notification(
            db,
            row.user_id,
            "withdrawal_update",
            {
                "id": str(row.id),
                "status": "rejected",
                "receipt_no": receipt_no_for(row),
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "fee_minor": row.fee_minor or 0,
                "message": "提现已驳回，金额已退回",
            },
            commit=False,
        )
    db.commit()
    return _ser_withdrawal(row)


AUTO_PAYOUT_MAX_MINOR = 20000


def try_auto_payout(db: Session, user: User, *, max_minor: int = AUTO_PAYOUT_MAX_MINOR) -> dict | None:
    """Never mark paid_manual. Ops must transfer money, then approve."""
    del db, user, max_minor
    return None


def run_auto_payouts(db: Session, *, force: bool = False) -> dict:
    del db, force
    return {"skipped": True, "reason": "manual_payout_only", "paid": 0, "scanned": 0}
