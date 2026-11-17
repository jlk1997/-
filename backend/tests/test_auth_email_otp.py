from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas import ChangeEmailRequest, UserRegister
from app.services.email_otp import (
    OTP_PURPOSES,
    assert_send_cooldown,
    consume_otp,
    generate_otp,
    hash_otp,
    is_placeholder_email,
    mark_send_cooldown,
    reset_otp_state_for_tests,
    store_otp,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _otp_memory():
    reset_otp_state_for_tests()
    yield
    reset_otp_state_for_tests()


def test_otp_store_verify_consume_and_reject_reuse():
    store_otp("register", "A@Example.com", "123456")
    consume_otp("register", "a@example.com", "123456")
    with pytest.raises(HTTPException) as exc:
        consume_otp("register", "a@example.com", "123456")
    assert exc.value.status_code == 400
    assert exc.value.detail == "otp_invalid"


def test_otp_hash_does_not_store_plain_code():
    digest = hash_otp("login", "a@b.com", "654321")
    assert "654321" not in digest
    assert len(digest) == 64


def test_otp_wrong_code_and_bad_purpose():
    store_otp("login", "a@b.com", "111111")
    with pytest.raises(HTTPException) as exc:
        consume_otp("login", "a@b.com", "000000")
    assert exc.value.detail == "otp_invalid"
    with pytest.raises(HTTPException):
        store_otp("signup", "a@b.com", "111111")


def test_otp_cooldown_blocks_second_send():
    assert_send_cooldown("a@b.com")
    mark_send_cooldown("a@b.com")
    with pytest.raises(HTTPException) as exc:
        assert_send_cooldown("a@b.com")
    assert exc.value.status_code == 429
    assert exc.value.detail == "otp_cooldown"


def test_register_schema_requires_otp():
    with pytest.raises(ValidationError):
        UserRegister(
            email="a@b.com",
            password="secret1",
            accepted_terms_version="2026-07-20",
            accepted_privacy_version="2026-07-20",
        )


def test_generate_otp_is_six_digits():
    code = generate_otp()
    assert code.isdigit()
    assert len(code) == 6


def test_placeholder_email_and_account_otp_purposes():
    assert is_placeholder_email("wx_abcd1234@wechat.local")
    assert not is_placeholder_email("a@b.com")
    assert {"rebind", "bind"}.issubset(set(OTP_PURPOSES))
    store_otp("bind", "new@b.com", "123456")
    consume_otp("bind", "new@b.com", "123456")
    with pytest.raises(ValidationError):
        ChangeEmailRequest(new_email="new@b.com", new_otp="12")


def test_login_page_and_client_have_otp_paths():
    login = (ROOT / "apps" / "client" / "src" / "packageStack" / "pages" / "login" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert "forgotPassword" in login
    assert "loginWithOtp" in login
    assert "sendEmailOtp" in login
    assert 'value: "otp"' in login
    assert "requireAgreement" in login
    assert "submitRegister" in login
    assert "confirmAction" in login
    assert "looksLikeEmail" in login
    assert "otpSentTo" in login
    assert "login-reset-head" in login
    assert "registerHint" in login
    copy_zh = (ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    assert "otpSentTo:" in copy_zh
    assert "invalidEmail:" in copy_zh
    assert "needPassword:" in copy_zh
    email_copy = (ROOT / "backend" / "app" / "services" / "email_otp.py").read_text(encoding="utf-8")
    assert "垃圾箱" in email_copy
    helper = (ROOT / "apps" / "client" / "src" / "utils" / "confirmAction.ts").read_text(encoding="utf-8")
    assert "looksLikeEmail" in helper
    assert "maskEmail" in helper
    assert "clipModalLabel" in helper
    client = (ROOT / "packages" / "api-client" / "src" / "client.ts").read_text(encoding="utf-8")
    assert '"/auth/email-otp"' in client
    assert '"/auth/login-otp"' in client
    assert '"/auth/reset-password"' in client
    assert '"/auth/change-email"' in client
    assert '"/auth/change-password"' in client
    assert '"/auth/verify-email"' in client
    assert "otp," in client
    auth = (ROOT / "backend" / "app" / "api" / "routes" / "auth.py").read_text(encoding="utf-8")
    assert "wrong_password" in auth
    assert "unknown_email" in auth
    assert "consume_otp" in auth
    assert "change-email" in auth
    assert "email_bound" in auth
    settings_page = (ROOT / "apps" / "client" / "src" / "packageStack" / "pages" / "settings" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert "AccountSecurityCard" in settings_page
    assert "logoutConfirm" in settings_page
    card = (ROOT / "apps" / "client" / "src" / "components" / "account" / "AccountSecurityCard.tsx").read_text(
        encoding="utf-8"
    )
    assert "changeAccountEmail" in card
    assert "changeAccountPassword" in card
    gate = (ROOT / "apps" / "client" / "src" / "components" / "legal" / "PrivacyConsentGate.tsx").read_text(
        encoding="utf-8"
    )
    assert "termsOfService" in gate
    assert "userAgreement" not in gate
    core = (ROOT / "packages" / "api-client" / "src" / "core.ts").read_text(encoding="utf-8")
    assert "same_email" in core
    assert "email_unbound" in core
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SMTP_HOST=smtp.qq.com" in example
    assert "SMTP_PORT=587" in example
    assert "SMTP_TLS=true" in example


@pytest.mark.requires_db
def test_password_login_distinguishes_unknown_and_wrong(db, monkeypatch):
    import uuid

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app
    from app.models.schemas import User
    from app.services.auth import hash_password

    monkeypatch.setattr(settings, "rate_limit_fail_closed", False)
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    email = f"otp_{suffix}@test.local"
    db.add(User(email=email, username=f"otp_{suffix}", hashed_password=hash_password("right-pass")))
    db.commit()

    missing = client.post("/api/v1/auth/login", json={"email": f"missing_{suffix}@test.local", "password": "x"})
    assert missing.status_code == 401
    assert missing.json()["detail"] == "unknown_email"

    wrong = client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "wrong_password"


@pytest.mark.requires_db
def test_register_login_otp_and_reset_password(db, monkeypatch):
    import uuid

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app
    from app.models.schemas import User
    from app.services import email_notify
    from app.services.auth import verify_password
    from app.services.email_otp import store_otp
    from app.services.legal import get_required_versions

    monkeypatch.setattr(settings, "rate_limit_fail_closed", False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.qq.com")
    sent: list[str] = []

    async def fake_send(to, subject, body_html, body_text=None):
        sent.append(subject)
        return True

    monkeypatch.setattr(email_notify, "send_email", fake_send)
    monkeypatch.setattr("app.services.email_otp.generate_otp", lambda: "424242")

    client = TestClient(app)
    suffix = uuid.uuid4().hex[:8]
    email = f"new_{suffix}@test.local"

    no_otp = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secret1",
            "accepted_terms_version": "x",
            "accepted_privacy_version": "x",
        },
    )
    assert no_otp.status_code == 422

    versions = get_required_versions()
    store_otp("register", email, "424242")
    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secret1",
            "otp": "424242",
            "accepted_terms_version": versions["terms"],
            "accepted_privacy_version": versions["privacy"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["access_token"]
    user = db.query(User).filter(User.email == email).one()
    assert user.email_verified_at is not None
    db.refresh(user)

    taken = client.post(
        "/api/v1/auth/email-otp",
        json={"email": email, "purpose": "register"},
    )
    assert taken.status_code == 409
    assert taken.json()["detail"] == "email_taken"

    store_otp("login", email, "111111")
    otp_login = client.post("/api/v1/auth/login-otp", json={"email": email, "otp": "111111"})
    assert otp_login.status_code == 200, otp_login.text

    store_otp("reset", email, "222222")
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"email": email, "otp": "222222", "password": "newpass1"},
    )
    assert reset.status_code == 200, reset.text
    db.refresh(user)
    assert verify_password("newpass1", user.hashed_password)
    assert not verify_password("secret1", user.hashed_password)

    old = client.post("/api/v1/auth/login", json={"email": email, "password": "secret1"})
    assert old.status_code == 401
    assert old.json()["detail"] == "wrong_password"
    fresh = client.post("/api/v1/auth/login", json={"email": email, "password": "newpass1"})
    assert fresh.status_code == 200

    store_otp("rebind", email, "333333")
    store_otp("bind", f"next_{suffix}@test.local", "444444")
    changed = client.post(
        "/api/v1/auth/change-email",
        headers={"Authorization": f"Bearer {fresh.json()['access_token']}"},
        json={
            "new_email": f"next_{suffix}@test.local",
            "new_otp": "444444",
            "current_otp": "333333",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["email"] == f"next_{suffix}@test.local"
    assert changed.json()["email_bound"] is True
    assert changed.json()["email_verified"] is True
