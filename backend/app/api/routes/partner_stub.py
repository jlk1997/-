"""Local partner webhook for adapter E2E. Enabled only in debug or PARTNER_STUB_ENABLED."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/dev/partner", tags=["dev-partner"])

_STORE: dict[str, dict] = {}


def _authorized(authorization: str | None) -> None:
    token = (authorization or "").replace("Bearer ", "").strip()
    keys = [
        settings.distrokid_api_key,
        settings.tunecore_api_key,
        settings.routenote_api_key,
        settings.cn_label_api_key,
    ]
    allowed = {k.strip() for k in keys if k and k.strip()}
    if settings.debug or settings.partner_stub_enabled:
        allowed.add("dev")
    if token in allowed:
        return
    if (settings.debug or settings.partner_stub_enabled) and not token and not {k for k in allowed if k != "dev"}:
        return
    raise HTTPException(401, "Invalid partner stub token")


class DeliveryIn(BaseModel):
    provider: str | None = None
    release_id: str | None = None
    delivery_id: str | None = None
    channel: str | None = None
    title: str | None = None
    artist_name: str | None = None
    isrc: str | None = None


@router.post("/v1/deliveries")
def create_delivery(payload: DeliveryIn, authorization: str | None = Header(default=None)):
    _authorized(authorization)
    external_id = f"stub_{uuid.uuid4().hex[:12]}"
    _STORE[external_id] = {
        "status": "in_review",
        "polls": 0,
        "channel": payload.channel,
        "title": payload.title,
        "created_at": datetime.utcnow().isoformat(),
    }
    return {"ok": True, "status": "in_review", "external_id": external_id, "message": "partner stub accepted"}


@router.get("/v1/deliveries/{external_id}")
def get_delivery(external_id: str, authorization: str | None = Header(default=None)):
    _authorized(authorization)
    row = _STORE.get(external_id)
    if not row:
        raise HTTPException(404, "Unknown delivery")
    row["polls"] = int(row.get("polls") or 0) + 1
    if row["polls"] >= 1:
        row["status"] = "live"
        row["store_url"] = f"https://example.com/stub/{external_id}"
    return {
        "ok": True,
        "status": row["status"],
        "external_id": external_id,
        "store_url": row.get("store_url"),
        "message": "partner stub status",
    }


@router.post("/v1/deliveries/{external_id}/takedown")
def takedown(external_id: str, authorization: str | None = Header(default=None)):
    _authorized(authorization)
    row = _STORE.get(external_id) or {}
    row["status"] = "taken_down"
    _STORE[external_id] = row
    return {"ok": True, "status": "taken_down", "external_id": external_id}


@router.get("/v1/earnings")
def earnings(authorization: str | None = Header(default=None)):
    _authorized(authorization)
    return {"rows": []}
