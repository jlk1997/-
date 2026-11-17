import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.schemas import PlatformMetricSnapshot, SettlementBatch, SettlementLine, User, Work
from app.services.auth import create_access_token, hash_password
from app.services.distribution.automation import sweep_auto_releases
from app.services.royalty.sync_desk import confirm_invoice, list_pending_invoices, place_order, set_work_listing


@pytest.fixture
def client():
    return TestClient(app)


def _user(db, prefix: str, *, admin: bool = False) -> User:
    user = User(
        email=f"{prefix}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("testpass123"),
        is_admin=admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _work(db, user: User, title: str = "Repair Drive") -> Work:
    work = Work(owner_id=user.id, title=title, audio_url="http://example.com/a.mp3", visibility="public")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


@pytest.mark.requires_db
def test_settlement_batch_http(client):
    db = SessionLocal()
    try:
        user = _user(db, "stmt")
        work = _work(db, user)
        batch = SettlementBatch(
            period_key=f"stmt-{uuid.uuid4().hex[:8]}",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            status="confirmed",
        )
        db.add(batch)
        db.commit()
        db.add(
            SettlementLine(
                batch_id=batch.id,
                user_id=user.id,
                work_id=work.id,
                channel_code="vibe_radio",
                source="first_party_radio",
                gross_minor=2,
                commission_minor=0,
                net_minor=2,
            )
        )
        db.commit()
        token = create_access_token(str(user.id))
        res = client.get(f"/api/v1/creator/settlements/{batch.id}", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body.get("batch_id") == str(batch.id)
        lines = body.get("lines") or []
        assert lines
        assert any(line.get("source") == "first_party_radio" for line in lines)
        assert all(line.get("source") != "listen_checkin" for line in lines)
    finally:
        db.close()


@pytest.mark.requires_db
def test_radio_complete_snapshot_http(client):
    db = SessionLocal()
    try:
        owner = _user(db, "radio-own")
        listener = _user(db, "radio-lis")
        work = _work(db, owner)
        token = create_access_token(str(listener.id))
        res = client.post(
            "/api/v1/engagement/listen-checkin",
            json={"work_id": str(work.id), "listen_ratio": 0.86, "arousal": 4, "valence": 6, "station": "daily"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200, res.text
        db.expire_all()
        snap = (
            db.query(PlatformMetricSnapshot)
            .filter(
                PlatformMetricSnapshot.work_id == work.id,
                PlatformMetricSnapshot.source == "first_party_radio",
            )
            .first()
        )
        assert snap is not None
        assert snap.usable_for_settlement is False
        assert (snap.revenue_minor or 0) == 0
        self_token = create_access_token(str(owner.id))
        self_res = client.post(
            "/api/v1/engagement/listen-checkin",
            json={"work_id": str(work.id), "listen_ratio": 0.9, "station": "daily"},
            headers={"Authorization": f"Bearer {self_token}"},
        )
        assert self_res.status_code == 200, self_res.text
        db.expire_all()
        self_snap = (
            db.query(PlatformMetricSnapshot)
            .filter(
                PlatformMetricSnapshot.work_id == work.id,
                PlatformMetricSnapshot.source == "first_party_radio_self",
            )
            .first()
        )
        assert self_snap is not None
        assert self_snap.usable_for_settlement is False
    finally:
        db.close()


@pytest.mark.requires_db
def test_sync_seller_and_invoice_confirm(client, db):
    seller = _user(db, "sync-sell")
    buyer = _user(db, "sync-buy")
    admin = _user(db, "sync-adm", admin=True)
    work = _work(db, seller)
    listing = set_work_listing(db, seller, str(work.id), enabled=True, tiers=["ads"])
    assert listing["enabled"] is True
    assert "ads" in listing["tiers"]
    seller_token = create_access_token(str(seller.id))
    put = client.put(
        f"/api/v1/sync/works/{work.id}",
        json={"enabled": True, "tiers": ["personal", "ads"]},
        headers={"Authorization": f"Bearer {seller_token}"},
    )
    assert put.status_code == 200, put.text
    order = place_order(db, buyer, work_id=str(work.id), tier="ads", pay_method="invoice", consent=True)
    assert order["status"] == "pending_invoice"
    pending = list_pending_invoices(db)
    assert any(row["id"] == order["id"] for row in pending)
    admin_token = create_access_token(str(admin.id))
    confirm = client.post(
        f"/api/v1/sync/admin/orders/{order['id']}/confirm",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert confirm.status_code == 200, confirm.text
    db.expire_all()
    confirmed = confirm_invoice(db, admin, order["id"])
    assert confirmed["status"] == "confirmed"
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.user_id == seller.id,
            PlatformMetricSnapshot.source == "sync_license",
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
        )
        .first()
    )
    assert snap is not None
    assert (snap.revenue_minor or 0) > 0


@pytest.mark.requires_db
def test_auto_release_sweep_skips_without_consent(db):
    from app.services.distribution.automation import set_auto_release_consent

    user = _user(db, "sweep")
    set_auto_release_consent(db, user, False)
    work = _work(db, user)
    work.release_status = "qc_ready"
    db.commit()
    result = sweep_auto_releases(db)
    assert result["submitted"] == 0
    assert result["checked"] >= 1
