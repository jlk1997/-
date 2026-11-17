"""Growth engine unit tests."""

import uuid

import pytest

from app.models.schemas import User
from app.services.growth import _normalize_code, apply_referral_on_signup, ensure_referral_code, generate_referral_code


def test_normalize_referral_code():
    assert _normalize_code(" ab-12 ") == "AB12"


def test_generate_referral_code_from_username():
    code = generate_referral_code("lofi_user", suffix="ABCD")
    assert code.startswith("LOFIUS")
    assert len(code) <= 12


@pytest.mark.requires_db
def test_apply_referral_links_once_and_skips_repeat(db):
    referrer = User(email=f"r-{uuid.uuid4()}@t.local", username=f"r_{uuid.uuid4().hex[:8]}", hashed_password="x")
    invitee = User(email=f"i-{uuid.uuid4()}@t.local", username=f"i_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add_all([referrer, invitee])
    db.commit()
    db.refresh(referrer)
    db.refresh(invitee)
    code = ensure_referral_code(db, referrer)
    db.commit()
    result = apply_referral_on_signup(db, invitee, code)
    db.commit()
    assert result is not None
    assert invitee.referred_by_id == referrer.id
    assert apply_referral_on_signup(db, invitee, code) is None


@pytest.mark.requires_db
def test_apply_referral_rejects_self(db):
    user = User(email=f"s-{uuid.uuid4()}@t.local", username=f"s_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    code = ensure_referral_code(db, user)
    db.commit()
    assert apply_referral_on_signup(db, user, code) is None
    assert user.referred_by_id is None
