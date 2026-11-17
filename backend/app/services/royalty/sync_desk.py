"""Sync Desk: first-party sync licensing. Credits or invoice — no fake DSP APIs."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import SyncLicenseOrder, User, UserConsentLog, Work
from app.services.c2pa import c2pa_state
from app.services.credits import deduct_credits, grant_credits_with_transaction
from app.services.ecosystem import REMIX_ROYALTY_RATE
from app.services.notifications import create_notification

SYNC_AGREEMENT = "2026-08-19"
SYNC_CHANNEL = "sync_desk"
SYNC_SOURCE = "sync_license"
SYNC_CREDITS_SOURCE = "sync_license_credits"
PLATFORM_RATE = 0.20
DEFAULT_TIERS = ("personal", "short_video")

SYNC_TIERS = {
    "personal": {"credits": 8, "fiat_minor": 800, "label": "个人向"},
    "short_video": {"credits": 20, "fiat_minor": 2800, "label": "短视频商用"},
    "ads": {"credits": 40, "fiat_minor": 6800, "label": "广告"},
    "game": {"credits": 60, "fiat_minor": 9800, "label": "游戏"},
    "film": {"credits": 120, "fiat_minor": 19800, "label": "影视"},
}


def list_tiers() -> list[dict]:
    return [
        {"id": key, "credits": spec["credits"], "fiat_minor": spec["fiat_minor"], "label": spec["label"]}
        for key, spec in SYNC_TIERS.items()
    ]


def listing_of(work: Work) -> dict:
    raw = ((work.post_process_status or {}).get("sync_listing")) or {}
    return dict(raw) if isinstance(raw, dict) else {}


def listing_enabled(work: Work) -> bool:
    return bool(listing_of(work).get("enabled")) or bool(work.commercial_cleared_at)


def enabled_tiers(work: Work) -> list[str]:
    raw = listing_of(work).get("tiers") or []
    chosen = [str(item) for item in raw if item in SYNC_TIERS]
    if listing_enabled(work) and not chosen:
        return list(DEFAULT_TIERS)
    return chosen


def _write_listing(work: Work, enabled: bool, tiers: list[str]) -> dict:
    pps = dict(work.post_process_status or {})
    payload = {
        "enabled": bool(enabled),
        "tiers": [t for t in tiers if t in SYNC_TIERS],
        "updated_at": datetime.utcnow().isoformat(),
    }
    pps["sync_listing"] = payload
    work.post_process_status = pps
    if enabled and not work.commercial_cleared_at:
        work.commercial_cleared_at = datetime.utcnow()
    if not enabled:
        work.commercial_cleared_at = None
    return payload


def ensure_default_sync_listing(work: Work) -> dict | None:
    if listing_of(work).get("enabled"):
        return listing_of(work)
    pps = work.post_process_status or {}
    ready = work.release_status in {"qc_ready", "queued", "delivering", "live"} or bool(pps.get("release_qc"))
    if not ready:
        return None
    return _write_listing(work, True, list(DEFAULT_TIERS))


def set_work_listing(db: Session, user: User, work_id: str, *, enabled: bool, tiers: list[str] | None = None) -> dict:
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    work, origin = resolve_sync_work(db, work, for_owner=True)
    chosen = [t for t in (tiers or list(DEFAULT_TIERS)) if t in SYNC_TIERS] or list(DEFAULT_TIERS)
    payload = _write_listing(work, enabled, chosen)
    db.commit()
    data = serialize_listing(work, payload, db=db)
    if origin:
        data["redirected_from_work_id"] = str(origin.id)
    return data


def rights_certificate_for_work(work: Work | None = None, *, db: Session | None = None, extra: dict | None = None) -> dict:
    """Buyer-facing B2B trust stamp. Always non-exclusive; never invents a lock-in."""
    blob = dict(extra or {})
    pps = (getattr(work, "post_process_status", None) or {}) if work else {}
    if not isinstance(pps, dict):
        pps = {}
    edits = blob.get("human_edits")
    if edits is None and work is not None and db is not None:
        from app.models.schemas import ProvenanceRecord

        try:
            prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
        except Exception:
            prov = None
        if prov and isinstance(prov.output_meta, dict):
            edits = len(list(prov.output_meta.get("human_edits") or []))
        else:
            edits = 0
    elif isinstance(edits, list):
        edits = len(edits)
    elif edits is None:
        edits = 0
    else:
        try:
            edits = int(edits)
        except (TypeError, ValueError):
            edits = 0
    ai = blob.get("ai_disclosed")
    if ai is None:
        ai = bool(getattr(work, "is_ai_generated", True)) if work else False
    return {
        "exclusive": False,
        "non_exclusive": True,
        "ai_disclosed": bool(ai),
        "human_edits": edits,
        "c2pa_verified": c2pa_state(pps) == "embedded",
        "c2pa_state": c2pa_state(pps),
        "commission_rate": blob.get("commission_rate"),
        "sync_tiers": list(blob.get("sync_tiers") or []),
    }


def should_hop_sync(*, for_owner: bool, successor_listed: bool) -> bool:
    """Owner always edits unpublished Work B. Buyers only hop if B is already listed."""
    return bool(for_owner or successor_listed)


def resolve_sync_work(db: Session, work: Work, *, for_owner: bool = False) -> tuple[Work, Work | None]:
    from app.services.royalty.hub import unpublished_workbench_successor

    child = unpublished_workbench_successor(db, work)
    if child is None or not should_hop_sync(for_owner=for_owner, successor_listed=listing_enabled(child)):
        return work, None
    return child, work


def serialize_listing(work: Work, payload: dict | None = None, db: Session | None = None) -> dict:
    from app.services.royalty.hub import is_workbench_master

    listing = payload or listing_of(work)
    tiers = enabled_tiers(work) if listing.get("enabled") else [t for t in (listing.get("tiers") or []) if t in SYNC_TIERS]
    return {
        "work_id": str(work.id),
        "title": work.title,
        "cover_url": work.cover_url,
        "audio_url": work.audio_url,
        "owner_id": str(work.owner_id) if work.owner_id else None,
        "enabled": bool(listing.get("enabled")),
        "commercial": listing_enabled(work),
        "tiers": tiers,
        "tier_cards": [row for row in list_tiers() if row["id"] in tiers] if listing.get("enabled") else list_tiers(),
        "rights_certificate": rights_certificate_for_work(work, db=db, extra={"sync_tiers": tiers if listing.get("enabled") else []}),
        "from_workbench": is_workbench_master(work),
    }


def catalog(db: Session, *, limit: int = 24, tenant_id: str | None = None) -> list[dict]:
    q = db.query(Work).filter(Work.visibility == "public")
    from app.services.tenant import is_multi_tenant_enabled

    if tenant_id and is_multi_tenant_enabled(db):
        q = q.filter(Work.tenant_id == tenant_id)
    rows = q.order_by(Work.created_at.desc()).limit(80).all()
    from app.services.royalty.hub import prefer_workbench_masters

    listed = prefer_workbench_masters([work for work in rows if listing_enabled(work)])
    out = []
    for work in listed:
        out.append(serialize_listing(work, db=db))
        if len(out) >= limit:
            break
    return out


def _quote(tier: str) -> dict:
    spec = SYNC_TIERS.get(tier)
    if not spec:
        raise HTTPException(400, "Unknown license tier")
    gross = int(spec["fiat_minor"])
    platform = int(round(gross * PLATFORM_RATE))
    remain = gross - platform
    parent = int(round(remain * REMIX_ROYALTY_RATE))
    seller = remain - parent
    return {
        "credits": int(spec["credits"]),
        "gross_minor": gross,
        "platform_minor": platform,
        "parent_minor": parent,
        "seller_minor": seller,
        "currency": "CNY",
    }


def _log_consent(db: Session, user: User, tier: str, work_id: str) -> None:
    db.add(
        UserConsentLog(
            user_id=user.id,
            consent_type=f"sync_license_{tier}",
            version=SYNC_AGREEMENT,
            user_agent=work_id[:64],
        )
    )


def place_order(db: Session, buyer: User, *, work_id: str, tier: str, pay_method: str, consent: bool) -> dict:
    if not consent:
        raise HTTPException(400, "Consent is required")
    if pay_method not in {"credits", "invoice"}:
        raise HTTPException(400, "Pay method must be credits or invoice")
    if tier not in SYNC_TIERS:
        raise HTTPException(400, "Unknown license tier")
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(404, "Work not found")
    work, _origin = resolve_sync_work(db, work, for_owner=False)
    if work.owner_id == buyer.id:
        raise HTTPException(400, "Cannot license your own work")
    if not listing_enabled(work) or tier not in enabled_tiers(work):
        raise HTTPException(400, "This tier is not listed")
    quote = _quote(tier)
    parent_id = work.parent_work_id
    parent_owner = None
    if parent_id:
        parent = db.query(Work).filter(Work.id == parent_id).first()
        parent_owner = parent.owner_id if parent else None
        if parent_owner == work.owner_id:
            quote["seller_minor"] += quote["parent_minor"]
            quote["parent_minor"] = 0
            parent_owner = None
    order = SyncLicenseOrder(
        work_id=work.id,
        seller_id=work.owner_id,
        buyer_id=buyer.id,
        tier=tier,
        pay_method=pay_method,
        status="pending_invoice" if pay_method == "invoice" else "paid",
        gross_credits=quote["credits"],
        gross_minor=quote["gross_minor"],
        platform_minor=quote["platform_minor"],
        seller_minor=quote["seller_minor"],
        parent_minor=quote["parent_minor"] if parent_owner else 0,
        currency="CNY",
        license_id=f"VSK-SYNC-{secrets.token_hex(6).upper()}",
        agreement_version=SYNC_AGREEMENT,
        meta={"parent_user_id": str(parent_owner) if parent_owner else None},
        paid_at=datetime.utcnow() if pay_method == "credits" else None,
    )
    if pay_method == "credits":
        if not deduct_credits(db, buyer.id, quote["credits"], source="sync_license", commit=False):
            raise HTTPException(402, "Insufficient credits")
        grant_credits_with_transaction(
            db,
            work.owner_id,
            max(1, quote["credits"] - int(round(quote["credits"] * PLATFORM_RATE))),
            source="sync_license",
            external_id=f"sync_seller_{order.license_id}",
            commit=False,
        )
        if parent_owner and quote["parent_minor"] > 0:
            parent_credits = max(1, int(round(quote["credits"] * (1 - PLATFORM_RATE) * REMIX_ROYALTY_RATE)))
            grant_credits_with_transaction(
                db,
                parent_owner,
                parent_credits,
                source="sync_license_parent",
                external_id=f"sync_parent_{order.license_id}",
                commit=False,
            )
        _record_credit_snapshot(db, work, order)
    _log_consent(db, buyer, tier, str(work.id))
    db.add(order)
    db.flush()
    create_notification(
        db,
        work.owner_id,
        "sync_order",
        {
            "order_id": str(order.id),
            "work_id": str(work.id),
            "tier": tier,
            "pay_method": pay_method,
            "message": f"同步授权新订单 · {SYNC_TIERS[tier]['label']}",
        },
        commit=False,
    )
    db.commit()
    db.refresh(order)
    return serialize_order(order)


def _record_credit_snapshot(db: Session, work: Work, order: SyncLicenseOrder) -> None:
    from app.services.royalty.snapshots import increment_display_snapshot

    increment_display_snapshot(
        db,
        user_id=work.owner_id,
        channel_code=SYNC_CHANNEL,
        period_key=datetime.utcnow().strftime("%Y-%m"),
        source=SYNC_CREDITS_SOURCE,
        streams=1,
        work_id=work.id,
        raw={"license_id": order.license_id, "tier": order.tier, "pay_method": "credits"},
    )


def confirm_invoice(db: Session, admin: User, order_id: str) -> dict:
    if not getattr(admin, "is_admin", False):
        raise HTTPException(403, "Admin required")
    try:
        oid = uuid.UUID(order_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid order id") from exc
    order = db.query(SyncLicenseOrder).filter(SyncLicenseOrder.id == oid).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.pay_method != "invoice":
        raise HTTPException(400, "Not an invoice order")
    if order.status == "confirmed":
        return serialize_order(order)
    from app.services.royalty.settlement import prefer_label_release
    from app.services.royalty.snapshots import increment_settlement_snapshot

    work = db.query(Work).filter(Work.id == order.work_id).first()
    release = prefer_label_release(db, order.work_id) if work else None
    increment_settlement_snapshot(
        db,
        user_id=order.seller_id,
        channel_code=SYNC_CHANNEL,
        period_key=datetime.utcnow().strftime("%Y-%m"),
        source=SYNC_SOURCE,
        streams=1,
        revenue_minor=order.seller_minor,
        currency=order.currency or "CNY",
        work_id=order.work_id,
        release_id=release.id if release else None,
        raw={"license_id": order.license_id, "tier": order.tier, "pay_method": "invoice"},
    )
    if order.parent_minor and (order.meta or {}).get("parent_user_id"):
        increment_settlement_snapshot(
            db,
            user_id=uuid.UUID(order.meta["parent_user_id"]),
            channel_code=SYNC_CHANNEL,
            period_key=datetime.utcnow().strftime("%Y-%m"),
            source=SYNC_SOURCE,
            streams=1,
            revenue_minor=order.parent_minor,
            currency=order.currency or "CNY",
            work_id=order.work_id,
            raw={"license_id": order.license_id, "role": "parent"},
        )
    order.status = "confirmed"
    order.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return serialize_order(order)


def serialize_order(order: SyncLicenseOrder) -> dict:
    return {
        "id": str(order.id),
        "work_id": str(order.work_id),
        "tier": order.tier,
        "pay_method": order.pay_method,
        "status": order.status,
        "license_id": order.license_id,
        "agreement_version": order.agreement_version,
        "gross_credits": order.gross_credits,
        "gross_minor": order.gross_minor,
        "seller_minor": order.seller_minor,
        "parent_minor": order.parent_minor,
        "currency": order.currency,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def list_orders(db: Session, user: User, *, role: str = "all") -> list[dict]:
    q = db.query(SyncLicenseOrder)
    if role == "bought":
        q = q.filter(SyncLicenseOrder.buyer_id == user.id)
    elif role == "sold":
        q = q.filter(SyncLicenseOrder.seller_id == user.id)
    else:
        q = q.filter((SyncLicenseOrder.buyer_id == user.id) | (SyncLicenseOrder.seller_id == user.id))
    rows = q.order_by(SyncLicenseOrder.created_at.desc()).limit(80).all()
    return [serialize_order(row) for row in rows]


def list_pending_invoices(db: Session) -> list[dict]:
    rows = (
        db.query(SyncLicenseOrder)
        .filter(SyncLicenseOrder.status == "pending_invoice")
        .order_by(SyncLicenseOrder.created_at.desc())
        .limit(80)
        .all()
    )
    return [serialize_order(row) for row in rows]

