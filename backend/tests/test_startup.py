"""Startup and health check tests."""

import pytest

from app.startup_checks import validate_production_config


def test_startup_allows_debug_defaults(monkeypatch, caplog):
    from app.config import settings

    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "jwt_secret", "change-me-in-production")
    monkeypatch.setattr(settings, "seat_vault_key", "")
    with caplog.at_level("WARNING"):
        validate_production_config()
    assert "SEAT_VAULT_KEY" in caplog.text


def test_startup_rejects_default_jwt_in_production(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "jwt_secret", "change-me-in-production")
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_production_config()


def test_startup_rejects_mock_generation_in_production(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "dev_mock_generation", True)
    with pytest.raises(RuntimeError, match="DEV_MOCK_GENERATION"):
        validate_production_config()


def _production_ok(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "dev_mock_generation", False)
    monkeypatch.setattr(settings, "minimax_api_key", "sk-test")
    monkeypatch.setattr(settings, "partner_stub_enabled", False)
    monkeypatch.setattr(settings, "legal_contact_phone", "400-800-0000")
    monkeypatch.setattr(settings, "legal_contact_email", "support@bittune.app")


def test_startup_rejects_missing_ai_keys_in_production(monkeypatch):
    from app.config import settings

    _production_ok(monkeypatch)
    monkeypatch.setattr(settings, "minimax_api_key", "")
    monkeypatch.setattr(settings, "mureka_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        validate_production_config()


def test_startup_rejects_partner_stub_in_production(monkeypatch):
    from app.config import settings

    _production_ok(monkeypatch)
    monkeypatch.setattr(settings, "partner_stub_enabled", True)
    with pytest.raises(RuntimeError, match="PARTNER_STUB"):
        validate_production_config()


def test_startup_rejects_placeholder_legal_contacts(monkeypatch):
    from app.config import settings

    _production_ok(monkeypatch)
    monkeypatch.setattr(settings, "legal_contact_phone", "400-000-0000")
    with pytest.raises(RuntimeError, match="LEGAL_CONTACT_PHONE"):
        validate_production_config()


def test_startup_allows_production_with_vendor_keys(monkeypatch):
    _production_ok(monkeypatch)
    validate_production_config()


def test_health_collects_checks():
    from app.health import collect_health

    result = collect_health()
    assert "status" in result
    assert "checks" in result
    assert "database" in result["checks"]
    assert "redis" in result["checks"]
    assert "essentia_models" in result["checks"]
    assert "seat_runtime" in result["checks"]
    assert "seat_vault" in result["checks"]


def test_health_stays_ok_when_essentia_degraded(monkeypatch):
    from app import health

    monkeypatch.setattr(health, "_check_database", lambda: {"status": "ok"})
    monkeypatch.setattr(health, "_check_redis", lambda: {"status": "ok"})
    monkeypatch.setattr(health, "_check_essentia_models", lambda: {"status": "degraded", "models_found": 0})
    monkeypatch.setattr(health, "_check_seat_runtime", lambda: {"status": "ok", "farm_navigate": False})
    result = health.collect_health()
    assert result["status"] == "ok"
    assert result["checks"]["essentia_models"]["status"] == "degraded"
