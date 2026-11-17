"""Authorized connector: scopes, display sync, revenue prediction."""

from datetime import datetime

import pytest

from app.models.schemas import PlatformMetricSnapshot, RoyaltyWallet, User, Work
from app.services.distribution.catalog import DISPLAY_ONLY_SOURCES, seed_distribution_catalog
from app.services.harvest.ingest import ingest_harvest_rows
from app.services.royalty.predict import predict_revenue
from app.services.seats.consent import DEFAULT_USER_SCOPES, set_seat_scopes
from app.services.seats.service import connect_user_seat, enqueue_due_harvests, save_seat_session, serialize_seat

PERIOD = datetime.utcnow().strftime("%Y-%m")


def _user(db, prefix: str) -> User:
    import uuid

    user = User(
        email=f"{prefix}-{uuid.uuid4()}@test.local",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
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


def test_predict_revenue_is_a_range_not_exact():
    pred = predict_revenue("spotify", 10000, currency="USD")
    assert pred["low_minor"] < pred["high_minor"]
    assert pred["mid_minor"] >= pred["low_minor"]
    assert pred["disclaimer"] == "estimated_not_settlement"
    assert pred["currency"] == "USD"
    assert pred["basis"] == "catalog"
    assert pred["geo_applied"] is False
    empty = predict_revenue("netease", 0)
    assert empty["low_minor"] == 0
    assert empty["high_minor"] == 0


def test_normalize_geo_and_region_stretch():
    from app.services.royalty.predict import normalize_geo

    assert normalize_geo("US") == {"US": 1.0}
    assert normalize_geo(["CN", "IN"])["CN"] == 1.0
    us = predict_revenue("spotify", 10000, geo={"US": 1})
    india = predict_revenue("spotify", 10000, geo="IN")
    assert us["geo_applied"] is True
    assert us["mid_minor"] > india["mid_minor"]


def test_predict_uses_history_rate_and_share():
    pred = predict_revenue("spotify", 1000, currency="USD", history_rate=4.0, share=0.8)
    assert pred["basis"] == "history"
    assert pred["share"] == 0.8
    catalog = predict_revenue("spotify", 1000, currency="USD")
    assert pred["mid_minor"] != catalog["mid_minor"] or pred["low_minor"] != catalog["low_minor"]


def test_store_compare_needs_two_stores():
    from app.services.royalty.predict import store_compare

    assert store_compare([]) is None
    assert store_compare([{"channel_code": "netease", "display_streams": 9}]) is None
    out = store_compare(
        [
            {"channel_code": "netease", "display_streams": 800, "predicted_revenue": {"mid_minor": 200}},
            {"channel_code": "spotify", "display_streams": 1200, "predicted_revenue": {"mid_minor": 400}},
        ]
    )
    assert out["top_channel"] == "spotify"
    assert out["runner_up"] == "netease"


def test_geo_from_index_does_not_bleed_other_stores():
    from app.services.royalty.predict import geo_from_index, predict_revenue

    index = {
        "channel": {"spotify": {"US": 10.0}},
        "work": {"w1": {"US": 10.0}},
        "both": {("spotify", "w1"): {"US": 10.0}},
        "user": {"US": 10.0},
    }
    assert geo_from_index(index, channel_code="netease") is None
    assert geo_from_index(index, channel_code="spotify") == {"US": 10.0}
    assert geo_from_index(index, work_id="w1") == {"US": 10.0}
    mixed = predict_revenue("netease", 1000, geo=geo_from_index(index, channel_code="netease"))
    assert mixed["geo_applied"] is False


def test_consent_log_version_fits_column():
    from app.services.seats.consent import CONNECTOR_CONSENT_VERSION

    assert len(CONNECTOR_CONSENT_VERSION) <= 32
    kind = f"connector_settle:wechat_channels"
    assert len(kind) <= 64


def test_default_handoff_allows_upload_not_settle():
    from app.services.seats.consent import DEFAULT_USER_SCOPES, grant_handoff_upload

    assert DEFAULT_USER_SCOPES["upload"] is True
    assert DEFAULT_USER_SCOPES["settle"] is False

    class Seat:
        ownership = "user"
        extra = {"scopes": {"metrics": True, "export_csv": True, "upload": False, "settle": False, "keep_sync": False}}

    seat = Seat()
    scopes = grant_handoff_upload(seat)
    assert scopes["upload"] is True
    assert scopes["settle"] is False


def test_due_job_kind_respects_scopes():
    from app.services.seats.consent import due_job_kind, job_matches_scopes

    class Seat:
        def __init__(self, ownership, extra):
            self.ownership = ownership
            self.extra = extra

    user = Seat("user", {"scopes": dict(DEFAULT_USER_SCOPES)})
    assert due_job_kind(user) is None
    assert job_matches_scopes(user, "harvest") is False
    assert job_matches_scopes(user, "sync_metrics") is True
    user.extra = {"scopes": {**DEFAULT_USER_SCOPES, "keep_sync": True}}
    assert due_job_kind(user) == "sync_metrics"
    user.extra = {"scopes": {**DEFAULT_USER_SCOPES, "settle": True, "export_csv": True}}
    assert due_job_kind(user) == "harvest"
    assert job_matches_scopes(user, "harvest") is True
    platform = Seat("platform", {})
    assert due_job_kind(platform) == "harvest"
    assert job_matches_scopes(platform, "harvest") is True


@pytest.mark.requires_db
def test_new_user_seat_defaults_to_metrics_not_settle(db):
    owner = _user(db, "scope")
    seat = connect_user_seat(db, owner, "spotify")
    db.commit()
    body = serialize_seat(seat)
    assert body["scopes"]["metrics"] is True
    assert body["scopes"]["settle"] is False
    assert body["scopes"] == {**DEFAULT_USER_SCOPES, **body["scopes"]}


@pytest.mark.requires_db
def test_reconnect_does_not_revoke_optional_scopes(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "reconnect")
    seat = connect_user_seat(db, owner, "netease")
    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "upload": True, "keep_sync": True, "settle": False},
        actor=owner,
        action="grant",
    )
    db.commit()
    client = TestClient(app)
    res = client.post(
        "/api/v1/seats/connect",
        headers={"Authorization": f"Bearer {create_access_token(str(owner.id))}"},
        json={
            "channel_code": "netease",
            "scopes": {"metrics": True, "export_csv": True, "upload": False, "settle": False, "keep_sync": False},
        },
    )
    assert res.status_code == 200, res.text
    scopes = res.json()["scopes"]
    assert scopes["upload"] is True
    assert scopes["keep_sync"] is True
    assert scopes["settle"] is False


@pytest.mark.requires_db
def test_user_seat_settle_requires_distribution_license(db):
    from fastapi import HTTPException

    seed_distribution_catalog(db)
    owner = _user(db, "nolicense")
    work = _work(db, owner)
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    with pytest.raises(HTTPException) as err:
        ingest_harvest_rows(
            db,
            [
                {
                    "channel_code": "netease",
                    "period_key": PERIOD,
                    "work_id": str(work.id),
                    "title": work.title,
                    "streams": 10,
                    "revenue_minor": 100,
                    "confidence": 0.95,
                }
            ],
            seat=seat,
            actor=owner,
            settle=True,
        )
    assert err.value.status_code == 403
    assert "license" in str(err.value.detail).lower()


@pytest.mark.requires_db
def test_sync_does_not_book_wallet(db):
    seed_distribution_catalog(db)
    owner = _user(db, "sync")
    work = _work(db, owner, "Sync Song")
    seat = connect_user_seat(db, owner, "spotify")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    result = ingest_harvest_rows(
        db,
        [
            {
                "channel_code": "spotify",
                "period_key": PERIOD,
                "work_id": str(work.id),
                "title": work.title,
                "streams": 5000,
                "revenue_minor": 8800,
            }
        ],
        seat=seat,
        actor=owner,
        settle=False,
        source="connector_sync",
    )
    assert result["usable_for_settlement"] is False
    assert result["matched"] == 1
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.work_id == work.id,
            PlatformMetricSnapshot.source == "connector_sync",
        )
        .first()
    )
    assert snap is not None
    assert snap.usable_for_settlement is False
    assert snap.revenue_minor == 0
    assert snap.streams == 5000
    assert (snap.raw or {}).get("prediction", {}).get("high_minor", 0) > 0
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or int(wallet.available_minor or 0) == 0
    assert "connector_sync" in DISPLAY_ONLY_SOURCES


@pytest.mark.requires_db
def test_harvest_http_blocked_without_settle_scope(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "nosettle")
    work = _work(db, owner, "No Settle")
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    client = TestClient(app)
    res = client.post(
        "/api/v1/seats/harvest",
        headers={"Authorization": f"Bearer {create_access_token(str(owner.id))}"},
        json={
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "revenue_minor": 1000, "streams": 40}],
        },
    )
    assert res.status_code == 403


@pytest.mark.requires_db
def test_sync_http_and_command_and_connections(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "cmd")
    work = _work(db, owner, "Cmd Song")
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token(str(owner.id))}"}
    sync = client.post(
        "/api/v1/seats/sync",
        headers=headers,
        json={
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "streams": 800, "revenue_minor": 0}],
        },
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["usable_for_settlement"] is False
    assert body["matched"] == 1
    scopes = client.patch(
        f"/api/v1/seats/{seat.id}/scopes",
        headers=headers,
        json={"keep_sync": True},
    )
    assert scopes.status_code == 200
    assert scopes.json()["scopes"]["keep_sync"] is True
    cmd = client.post(
        f"/api/v1/seats/{seat.id}/command",
        headers=headers,
        json={"kind": "sync_metrics"},
    )
    assert cmd.status_code == 200, cmd.text
    conn = client.get("/api/v1/seats/connections", headers=headers)
    assert conn.status_code == 200
    rows = conn.json()["connections"]
    netease = next(item for item in rows if item["channel_code"] == "netease")
    assert netease["suggest_connector"] is True or netease["status"] in {"metrics", "needs_login", "settle"}
    assert "last_sync_at" in netease
    cfg = client.get("/api/v1/seats/connector-config", headers=headers)
    assert cfg.status_code == 200
    assert "music.163.com" in str(cfg.json().get("hosts"))
    hub = client.get("/api/v1/creator/hub", headers=headers)
    assert hub.status_code == 200
    payload = hub.json()
    assert payload.get("predicted_revenue")
    assert payload.get("connections")


@pytest.mark.requires_db
def test_due_jobs_skip_user_seat_without_keep_or_settle(db):
    owner = _user(db, "due")
    seat = connect_user_seat(db, owner, "spotify")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    assert enqueue_due_harvests(db, force=True, user_id=owner.id) == 0
    set_seat_scopes(db, seat, {"metrics": True, "keep_sync": True, "export_csv": True}, actor=owner, action="test")
    db.commit()
    assert enqueue_due_harvests(db, force=True, user_id=owner.id) == 1
    from app.models.schemas import SeatJob

    job = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.status.in_(("queued", "leased"))).first()
    assert job is not None
    assert job.kind == "sync_metrics"


@pytest.mark.requires_db
def test_revoke_optional_scopes_keeps_seat_connected(db):
    from app.models.schemas import UserConsentLog
    from app.services.seats.consent import CONNECTOR_CONSENT_VERSION, revoke_optional_scopes, seat_scopes

    owner = _user(db, "revoke")
    seat = connect_user_seat(db, owner, "spotify")
    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "upload": True, "settle": True, "keep_sync": True},
        actor=owner,
        action="grant",
    )
    db.commit()
    scopes = revoke_optional_scopes(db, seat, actor=owner)
    db.commit()
    assert scopes["metrics"] is True
    assert scopes["settle"] is False
    assert scopes["upload"] is False
    assert scopes["keep_sync"] is False
    body = serialize_seat(seat)
    assert body["status"] != "disconnected"
    log = (
        db.query(UserConsentLog)
        .filter(UserConsentLog.user_id == owner.id, UserConsentLog.consent_type.like("connector_revoke:%"))
        .first()
    )
    assert log is not None
    assert log.version == CONNECTOR_CONSENT_VERSION
    assert len(log.version) <= 32
    assert seat_scopes(seat)["metrics"] is True


@pytest.mark.requires_db
def test_lease_drops_harvest_after_scope_revoke(db):
    from app.models.schemas import SeatJob
    from app.services.seats.consent import revoke_optional_scopes
    from app.services.seats.service import enqueue_job, lease_jobs

    owner = _user(db, "lease")
    seat = connect_user_seat(db, owner, "spotify")
    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "settle": True},
        actor=owner,
        action="grant",
    )
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    revoke_optional_scopes(db, seat, actor=owner)
    db.commit()
    leased = lease_jobs(db, owner=f"user:{owner.id}", runtime="extension", actor=owner)
    assert all(item["kind"] != "harvest" for item in leased)
    db.refresh(job)
    assert job.status == "failed"
    assert (job.result or {}).get("error") == "scope_revoked"


@pytest.mark.requires_db
def test_harvest_http_blocked_without_license(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "nolic")
    work = _work(db, owner, "No License")
    seat = connect_user_seat(db, owner, "netease")
    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "settle": True},
        actor=owner,
        action="test",
    )
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    client = TestClient(app)
    res = client.post(
        "/api/v1/seats/harvest",
        headers={"Authorization": f"Bearer {create_access_token(str(owner.id))}"},
        json={
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "revenue_minor": 1000, "streams": 40}],
        },
    )
    assert res.status_code == 403
    patch = client.patch(
        f"/api/v1/seats/{seat.id}/scopes",
        headers={"Authorization": f"Bearer {create_access_token(str(owner.id))}"},
        json={"settle": True},
    )
    assert patch.status_code == 403
