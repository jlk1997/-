"""Inbound signed partner callbacks — the only legitimate live-status push."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import DistributionDelivery, Release
from app.services.distribution.adapters import AdapterResult, ALLOWED_STATUSES
from app.services.distribution.pipeline import apply_query_result, notify_distribution_status, refresh_release_progress

logger = logging.getLogger(__name__)


def configured_partner_keys() -> set[str]:
    keys = []
    for attr in ("distrokid_api_key", "tunecore_api_key", "routenote_api_key", "cn_label_api_key"):
        value = (getattr(settings, attr, "") or "").strip()
        if value:
            keys.append(value)
    if settings.debug or getattr(settings, "partner_stub_enabled", False):
        keys.append("dev")
    return set(keys)


def sign_partner_body(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_partner_request(authorization: str | None, signature: str | None, body: bytes) -> str:
    secret = (getattr(settings, "partner_webhook_secret", "") or "").strip()
    token = (authorization or "").replace("Bearer ", "").strip()
    given = (signature or "").replace("sha256=", "").strip()
    if secret and given:
        expected = sign_partner_body(body, secret)
        if hmac.compare_digest(expected, given):
            return "hmac"
        raise HTTPException(401, "Invalid partner signature")
    if token and token in configured_partner_keys():
        return "bearer"
    raise HTTPException(401, "Invalid partner token")


def _parse_payload(raw: bytes) -> dict:
    if not raw:
        raise HTTPException(400, "Empty partner payload")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid partner JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "Partner payload must be an object")
    return data


def _find_delivery(db: Session, payload: dict) -> DistributionDelivery:
    delivery_id = payload.get("delivery_id")
    external_id = payload.get("external_id")
    if delivery_id:
        try:
            did = uuid.UUID(str(delivery_id))
        except ValueError as exc:
            raise HTTPException(400, "Invalid delivery id") from exc
        row = db.query(DistributionDelivery).filter(DistributionDelivery.id == did).first()
        if row:
            return row
    if external_id:
        row = (
            db.query(DistributionDelivery)
            .filter(DistributionDelivery.external_id == str(external_id)[:128])
            .order_by(DistributionDelivery.updated_at.desc())
            .first()
        )
        if row:
            return row
    raise HTTPException(404, "Delivery not found")


def apply_partner_event(db: Session, payload: dict) -> dict:
    row = _find_delivery(db, payload)
    event_id = str(payload.get("event_id") or "")[:80]
    meta = dict(row.attempt_meta or {})
    if event_id and meta.get("last_event_id") == event_id:
        return {"ok": True, "duplicate": True, "id": str(row.id), "status": row.status}

    status = str(payload.get("status") or row.status)
    if status not in ALLOWED_STATUSES:
        raise HTTPException(400, "Unsupported delivery status")
    store_url = payload.get("store_url") or payload.get("url")
    if store_url:
        from app.services.distribution.service import normalize_store_url

        store_url = normalize_store_url(str(store_url))
    result = AdapterResult(
        ok=True,
        status=status,
        external_id=str(payload.get("external_id") or row.external_id or "") or None,
        store_url=store_url,
        message=str(payload.get("message") or "partner webhook")[:300],
    )
    previous = row.status
    changed = apply_query_result(row, result)
    if previous != "live" and row.status == "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, row)
    # Confirm tier when partner webhook sets live on a configured adapter
    if row.status == "live":
        from app.services.distribution.adapters import get_adapter
        adapter = get_adapter(row.distributor_code)
        if adapter.configured():
            row.delivery_tier = "api_verified"
    if event_id:
        meta["last_event_id"] = event_id
    meta["partner_event_at"] = datetime.utcnow().isoformat()
    meta["partner_source"] = "webhook"
    row.attempt_meta = meta
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(
        row,
        event="partner_webhook",
        actor="partner",
        receipt_url=store_url,
        external_id=result.external_id,
        message=result.message,
    )
    if result.message:
        row.reject_reason = result.message
    from app.services.distribution.reject import writeback_catalog_codes

    writeback_catalog_codes(
        db,
        row,
        isrc=payload.get("isrc") or getattr(result, "isrc", None),
        upc=payload.get("upc") or getattr(result, "upc", None),
    )
    release = db.query(Release).filter(Release.id == row.release_id).first()
    if release:
        refresh_release_progress(db, release)
        if changed and previous != row.status:
            notify_distribution_status(
                db,
                row.owner_id,
                release_id=str(release.id),
                status=row.status,
                channel_code=row.channel_code,
                message=result.message or f"{row.channel_code} 合作回执：{row.status}",
            )
    db.commit()
    return {
        "ok": True,
        "id": str(row.id),
        "status": row.status,
        "previous": previous,
        "changed": changed,
        "store_url": row.store_url,
        "external_id": row.external_id,
        "auth": None,
    }


def handle_partner_webhook(
    db: Session,
    *,
    body: bytes,
    authorization: str | None,
    signature: str | None,
) -> dict:
    auth = verify_partner_request(authorization, signature, body)
    payload = _parse_payload(body)
    provider = str(payload.get("provider") or payload.get("source") or "").lower()
    if provider:
        from app.services.distribution.adapters import get_adapter

        normalized = get_adapter(provider).parse_webhook(payload)
        if normalized:
            payload = {**payload, **{k: v for k, v in normalized.items() if v is not None}}
    result = apply_partner_event(db, payload)
    result["auth"] = auth
    logger.info("partner webhook %s delivery=%s status=%s", auth, result.get("id"), result.get("status"))
    return result
