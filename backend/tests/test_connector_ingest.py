import uuid

import pytest
from fastapi import HTTPException

from app.models.schemas import PlatformMetricSnapshot, User, Work
from app.services.royalty.connector import (
    ConnectorActor,
    confirm_batch,
    ingest_connector_rows,
    list_claims,
    match_claim,
    mint_ingest_token,
    resolve_connector_actor,
)


def _user(db, prefix: str, *, admin: bool = False) -> User:
    user = User(
        email=f"{prefix}-{uuid.uuid4()}@test.local",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        is_admin=admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _work(db, user: User, title="Night Drive") -> Work:
    work = Work(owner_id=user.id, title=title, audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


@pytest.mark.requires_db
def test_ops_connector_unmatched_then_confirm(db):
    admin = _user(db, "ops", admin=True)
    owner = _user(db, "creator")
    work = _work(db, owner)
    actor = ConnectorActor(user=admin, role="ops", via="jwt")
    result = ingest_connector_rows(
        db,
        actor,
        {
            "rows": [
                {
                    "channel_code": "netease",
                    "period_key": "2026-08",
                    "title": "Night Drive",
                    "user_id": str(owner.id),
                    "streams": 120,
                    "revenue_minor": 800,
                    "currency": "CNY",
                    "confidence": 0.8,
                },
                {
                    "channel_code": "qq_music",
                    "period_key": "2026-08",
                    "title": "Unknown Song",
                    "streams": 9,
                    "revenue_minor": 10,
                },
            ]
        },
    )
    assert result["source"] == "ops_connector"
    assert result["matched"] == 1
    assert result["unclaimed"] == 1
    assert result["usable_for_settlement"] is False
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.source == "ops_connector")
        .first()
    )
    assert snap is None
    claims = [row for row in list_claims(db, status="unclaimed") if row.get("batch_id") == result["batch"]["id"]]
    assert len(claims) == 1
    matched = match_claim(db, claims[0]["id"], str(work.id), admin, admin=True)
    assert matched["status"] == "matched"
    assert (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.source == "ops_connector")
        .first()
        is None
    )


@pytest.mark.requires_db
def test_ops_connector_auto_match_never_settles(db):
    admin = _user(db, "opsauto", admin=True)
    owner = _user(db, "creatorauto")
    work = _work(db, owner)
    actor = ConnectorActor(user=admin, role="ops", via="jwt")
    result = ingest_connector_rows(
        db,
        actor,
        {
            "rows": [
                {
                    "channel_code": "netease",
                    "period_key": "2026-08",
                    "title": "Night Drive",
                    "isrc": "USXXX0000001",
                    "user_id": str(owner.id),
                    "streams": 120,
                    "revenue_minor": 800,
                    "currency": "CNY",
                    "confidence": 0.95,
                }
            ]
        },
    )
    assert result["source"] == "ops_connector"
    assert result["matched"] == 1
    assert result["unclaimed"] == 0
    assert result["usable_for_settlement"] is False
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.source == "ops_connector")
        .first()
    )
    assert snap is None


@pytest.mark.requires_db
def test_user_connector_never_settles(db):
    user = _user(db, "self")
    work = _work(db, user, "My Demo")
    actor = ConnectorActor(user=user, role="user", via="jwt")
    result = ingest_connector_rows(
        db,
        actor,
        {
            "rows": [
                {
                    "channel_code": "netease",
                    "period_key": "2026-08",
                    "work_id": str(work.id),
                    "streams": 50,
                    "revenue_minor": 200,
                }
            ]
        },
    )
    assert result["source"] == "user_connector"
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.source == "user_connector")
        .first()
    )
    assert snap is None
    try:
        confirm_batch(db, result["batch"]["id"])
        assert False, "user connector batch review stays ops-only"
    except HTTPException as exc:
        assert exc.status_code == 400


@pytest.mark.requires_db
def test_connector_token_roundtrip(db):
    user = _user(db, "tok")
    minted = mint_ingest_token(db, user)
    assert minted["token"].startswith("vsc_")
    assert minted["pair_text"].startswith("BITTUNE_PAIR:")
    assert minted["pair"]["period"] == minted["period_key"]
    assert minted["pair"]["minVersion"]
    actor = resolve_connector_actor(db, minted["token"])
    assert actor is not None
    assert actor.user.id == user.id
    assert actor.role == "user"


@pytest.mark.requires_db
def test_mint_revokes_previous_token(db):
    user = _user(db, "rev")
    first = mint_ingest_token(db, user)
    second = mint_ingest_token(db, user)
    assert resolve_connector_actor(db, first["token"]) is None
    actor = resolve_connector_actor(db, second["token"])
    assert actor is not None
    assert actor.user.id == user.id


@pytest.mark.requires_db
def test_revoke_connector_tokens_kills_pair(db):
    user = _user(db, "kill")
    minted = mint_ingest_token(db, user)
    assert resolve_connector_actor(db, minted["token"]) is not None
    from app.services.royalty.connector import revoke_connector_tokens

    out = revoke_connector_tokens(db, user)
    assert out["revoked"] == 1
    assert resolve_connector_actor(db, minted["token"]) is None


@pytest.mark.requires_db
def test_heartbeat_sync_matches_current_period(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.distribution.assist import last_harvest_from_seats, touch_heartbeat
    from app.services.royalty.settlement import current_period

    assert last_harvest_from_seats([]) is None
    assert last_harvest_from_seats(
        [{"channel_code": "netease", "last_harvest_at": "2026-08-01T00:00:00", "farm_health": {"rows": 2, "matched": 1}}]
    )["count"] == 2

    user = _user(db, "beat")
    minted = mint_ingest_token(db, user)
    actor = resolve_connector_actor(db, minted["token"])
    assert actor is not None
    sync = touch_heartbeat(db, actor.user, {"extension_version": "0.8.0", "channel": "netease"})
    period, _, _ = current_period(db)
    assert sync["online"] is True
    assert sync["period_key"] == period
    assert sync["extension_version"] == "0.8.0"
    client = TestClient(app)
    res = client.post(
        "/api/v1/distribution/assist/heartbeat",
        headers={"X-Connector-Token": minted["token"], "Content-Type": "application/json"},
        json={"extension_version": "0.8.0", "period_key": period},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period_key"] == period
    assert body["online"] is True
