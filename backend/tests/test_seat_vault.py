import pytest

from app.services.seats import secrets as secrets_mod


def test_fernet_roundtrip_and_xor_fallback(monkeypatch):
    monkeypatch.setattr(secrets_mod.settings, "jwt_secret", "unit-test-secret")
    monkeypatch.setattr(secrets_mod.settings, "seat_vault_key", "")
    payload = {"session": {"cookie": "abc"}, "credentials": {}}
    token = secrets_mod.encrypt_blob(payload)
    assert token.startswith("v2:")
    assert secrets_mod.decrypt_blob(token)["session"]["cookie"] == "abc"

    raw = b'{"session":{"cookie":"legacy"}}'
    key = secrets_mod._xor_key()
    mixed = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    import base64

    legacy = base64.urlsafe_b64encode(mixed).decode("ascii")
    assert secrets_mod.decrypt_blob(legacy)["session"]["cookie"] == "legacy"
    assert secrets_mod.decrypt_blob("") == {}


def test_kyc_stays_pending_without_provider(monkeypatch):
    from types import SimpleNamespace

    from app.services import kyc

    monkeypatch.setattr(kyc.settings, "kyc_api_url", "")
    monkeypatch.setattr(kyc.settings, "kyc_api_key", "")
    user = SimpleNamespace(kyc_status="none")
    db = SimpleNamespace(commit=lambda: None)
    result = kyc.request_kyc(db, user)
    assert result["verified"] is False
    assert result["provider_configured"] is False
    assert user.kyc_status == "pending"


def test_kyc_marks_verified_only_when_vendor_says_so(monkeypatch):
    from types import SimpleNamespace

    from app.services import kyc

    monkeypatch.setattr(kyc.settings, "kyc_api_url", "https://kyc.example/v1")
    monkeypatch.setattr(kyc.settings, "kyc_api_key", "k")
    monkeypatch.setattr(kyc.settings, "kyc_provider", "vendor")
    monkeypatch.setattr(kyc, "verify_identity", lambda *args, **kwargs: {"verified": True, "provider": "vendor"})
    user = SimpleNamespace(id="u1", kyc_status="none")
    db = SimpleNamespace(commit=lambda: None)
    result = kyc.request_kyc(db, user)
    assert result["verified"] is True
    assert user.kyc_status == "verified"


def test_kyc_webhook_requires_secret(monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from app.api.routes import wallet as wallet_mod

    monkeypatch.setattr(wallet_mod.settings, "kyc_webhook_secret", "")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wallet_mod.kyc_webhook(request=None, db=None, x_kyc_signature=None))
    assert exc.value.status_code == 503
