"""Creator weekly digest tests."""

import uuid

import pytest

from app.models.schemas import User
from app.services.creator_weekly_digest import get_creator_weekly_summary


@pytest.mark.requires_db
def test_creator_weekly_summary_shape(db):
    user = User(
        id=uuid.uuid4(),
        email=f"c-{uuid.uuid4().hex[:8]}@test.local",
        username=f"c_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
    )
    db.add(user)
    db.commit()

    summary = get_creator_weekly_summary(db, user.id)
    assert "listens" in summary
    assert "tips" in summary
    assert "duel_mentions" in summary
    assert "radio_completes" in summary
    assert "radio_self_completes" in summary
    assert "clip_drops" in summary
    assert summary["tips"] == 0
    assert (summary.get("wallet_split") or {}).get("credits_tips") == 0
    assert "embed_minor" in (summary.get("wallet_split") or {})
    assert "harvest_minor" in (summary.get("wallet_split") or {})
    assert "积分钱包" in (summary.get("message") or "")
    assert "嵌入" in (summary.get("message") or "")
    assert (summary.get("payout_calendar") or {}).get("days_until_payout") is not None
