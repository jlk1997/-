"""Production startup validation — fail fast when misconfigured."""

from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("vibe.startup")

_DEFAULT_JWT_SECRET = "change-me-in-production"


def _frontend_looks_like_ip(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return True
    parts = host.split(".")
    return len(parts) == 4 and all(part.isdigit() for part in parts)


def validate_production_config() -> None:
    """Raise RuntimeError when critical secrets are missing in non-debug mode."""
    from app.services.billing import audit_product_prices

    price_problems = audit_product_prices()

    if settings.debug:
        if settings.jwt_secret == _DEFAULT_JWT_SECRET:
            log.warning("JWT_SECRET is default — set a strong secret in production")
        if settings.stripe_secret_key and not settings.stripe_webhook_secret:
            log.warning(
                "STRIPE_SECRET_KEY is set but STRIPE_WEBHOOK_SECRET is empty — webhooks will be rejected"
            )
        if not settings.admin_bootstrap_email.strip():
            log.info("ADMIN_BOOTSTRAP_EMAIL is empty — no automatic admin promotion on startup")
        for problem in price_problems:
            log.warning("Price table problem: %s", problem)
        if not (getattr(settings, "seat_vault_key", "") or "").strip():
            log.warning("SEAT_VAULT_KEY is empty — seat cookies derive from JWT_SECRET; set an independent key")
        if _frontend_looks_like_ip(getattr(settings, "frontend_base_url", "") or ""):
            log.warning("FRONTEND_BASE_URL is an IP/localhost — WeChat H5 copies will not open the public domain")
        return

    errors: list[str] = []
    errors.extend(f"Price table: {problem}" for problem in price_problems)
    if settings.jwt_secret == _DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
        errors.append("JWT_SECRET must be set to a strong random value (32+ chars) when DEBUG=false")
    if settings.stripe_secret_key and not settings.stripe_webhook_secret:
        errors.append("STRIPE_WEBHOOK_SECRET is required when STRIPE_SECRET_KEY is set")
    if settings.dev_mock_generation:
        errors.append("DEV_MOCK_GENERATION must be false when DEBUG=false")
    if settings.use_mock_ai:
        errors.append(
            "Set MINIMAX_API_KEY (or MUREKA_API_KEY / GEMINI_API_KEY / ELEVENLABS_API_KEY) when DEBUG=false — mock generation is not production"
        )
    if settings.partner_stub_enabled:
        errors.append("PARTNER_STUB_ENABLED must be false when DEBUG=false")
    if settings.payment_mock_allowed:
        errors.append("Payment mock must be off when DEBUG=false")
    if (settings.legal_contact_phone or "").strip() in {"", "400-000-0000"}:
        errors.append("LEGAL_CONTACT_PHONE must be a real support number when DEBUG=false")
    if (settings.legal_contact_email or "").strip() in {"", "privacy@vibe-sorcery.com"}:
        errors.append("LEGAL_CONTACT_EMAIL must be a real support inbox when DEBUG=false")
    if not settings.rate_limit_fail_closed:
        log.warning(
            "RATE_LIMIT_FAIL_CLOSED is false — rate limits fall back to per-process memory when Redis is down"
        )
    if not (getattr(settings, "seat_vault_key", "") or "").strip():
        log.warning("SEAT_VAULT_KEY is empty — seat cookies derive from JWT_SECRET; set an independent key")
    if _frontend_looks_like_ip(getattr(settings, "frontend_base_url", "") or ""):
        log.warning("FRONTEND_BASE_URL is an IP/localhost — WeChat H5 copies will not open the public domain")
    if not (getattr(settings, "ops_alert_webhook_url", "") or "").strip():
        log.warning("OPS_ALERT_WEBHOOK_URL is empty — ops daily digest only writes the structured log")
    if errors:
        raise RuntimeError("Production configuration invalid:\n- " + "\n- ".join(errors))
