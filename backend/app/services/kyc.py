"""KYC identity verification. Never mark verified without a provider or admin."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import User

logger = logging.getLogger(__name__)


def provider_configured() -> bool:
    return bool((settings.kyc_api_url or "").strip() and (settings.kyc_api_key or "").strip())


def verify_identity(
    user_id: str,
    *,
    real_name: str = "",
    id_number: str = "",
) -> dict[str, Any]:
    """Call the configured vendor. Never invent a pass."""
    if not provider_configured():
        return {"verified": False, "provider": "none", "reason": "KYC provider not configured"}

    try:
        import httpx

        resp = httpx.post(
            settings.kyc_api_url,
            json={"name": real_name, "id_number": id_number, "user_id": user_id},
            headers={"Authorization": f"Bearer {settings.kyc_api_key}", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code >= 400:
            return {"verified": False, "provider": settings.kyc_provider or "third_party", "reason": f"http_{resp.status_code}"}
        result = resp.json() if resp.content else {}
        if not isinstance(result, dict):
            return {"verified": False, "provider": settings.kyc_provider or "third_party", "reason": "invalid_payload"}
        verified = bool(result.get("match") or result.get("verified") or result.get("passed"))
        return {
            "verified": verified,
            "provider": settings.kyc_provider or result.get("provider") or "third_party",
            "reason": result.get("reason") or result.get("status"),
            "external_id": result.get("id") or result.get("session_id"),
            "session_url": result.get("session_url") or result.get("url"),
        }
    except Exception as exc:
        logger.warning("KYC verification failed: %s", exc)
        return {"verified": False, "provider": "error", "reason": "API call failed"}


def request_kyc(db: Session, user: User, *, real_name: str = "", id_number: str = "") -> dict[str, Any]:
    status = getattr(user, "kyc_status", None) or "none"
    if status == "verified":
        return {"kyc_status": "verified", "provider_configured": provider_configured(), "verified": True}

    if not provider_configured():
        user.kyc_status = "pending"
        db.commit()
        return {
            "kyc_status": "pending",
            "provider_configured": False,
            "verified": False,
            "note": "厂商未配置。财务人工核验后才会标已实名。",
        }

    result = verify_identity(str(user.id), real_name=real_name, id_number=id_number)
    if result.get("verified"):
        user.kyc_status = "verified"
    else:
        user.kyc_status = "pending"
    db.commit()
    return {
        "kyc_status": user.kyc_status,
        "provider_configured": True,
        "verified": bool(result.get("verified")),
        "provider": result.get("provider"),
        "session_url": result.get("session_url"),
        "reason": result.get("reason"),
    }


def apply_provider_result(db: Session, user: User, *, verified: bool, rejected: bool = False) -> dict[str, Any]:
    if verified:
        user.kyc_status = "verified"
    elif rejected:
        user.kyc_status = "rejected"
    else:
        user.kyc_status = "pending"
    db.commit()
    return {"kyc_status": user.kyc_status, "verified": user.kyc_status == "verified"}
