import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.models.schemas import (
    DistributionDelivery,
    DistributionLicense,
    FeatureFlag,
    Notification,
    PlatformMetricSnapshot,
    Release,
    ReleaseMetadata,
    RoyaltyWallet,
    SettlementBatch,
    SettlementLine,
    User,
    Work,
    WorkSplitShare,
)
from app.services.distribution.catalog import seed_distribution_catalog
from app.services.distribution.pipeline import process_one_delivery
from app.services.distribution.service import (
    admin_list_deliveries,
    admin_mark_release_live,
    admin_set_delivery_status,
    create_or_get_release,
    normalize_store_url,
    set_store_url,
    sign_license,
    submit_release,
    update_release,
)
from app.services.royalty.settlement import confirm_settlement, get_batch_detail, list_batches, run_settlement, void_settlement
from app.services.royalty.wallet import get_or_create_wallet, request_withdrawal, review_withdrawal, upsert_payout_account


def _user(db, prefix: str) -> User:
    user = User(
        email=f"{prefix}-{uuid.uuid4()}@test.local",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        kyc_status="verified",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _work_release(db, user: User, *, qc_passed: bool = True) -> tuple[Work, Release]:
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(
        work_id=work.id,
        owner_id=user.id,
        mode="self_release",
        status="qc",
        selected_channels=["spotify"],
        qc_result={"passed": qc_passed},
    )
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
    db.commit()
    db.refresh(release)
    return work, release


@pytest.mark.requires_db
def test_create_release_reuses_active_and_submit_needs_artist(db):
    user = _user(db, "reuse")
    work, release = _work_release(db, user)
    release.mode = "label"
    release.status = "delivering"
    db.commit()
    again = create_or_get_release(db, user, str(work.id))
    assert again["id"] == str(release.id)
    assert again["already_active"] is True
    draft_user = _user(db, "noartist")
    work2, release2 = _work_release(db, draft_user)
    release2.mode = "label"
    release2.qc_result = {"passed": True}
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release2.id).first()
    meta.artist_name = ""
    db.add(DistributionLicense(user_id=draft_user.id, release_id=release2.id, agreement_version="2026-08-19", commission_rate=20))
    db.commit()
    try:
        submit_release(db, draft_user, str(release2.id))
        assert False, "artist required"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Artist" in str(exc.detail)


@pytest.mark.requires_db
def test_submit_release_requires_qc(db):
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "release_qc").first()
    if not flag:
        db.add(FeatureFlag(key="release_qc", enabled=True))
    else:
        flag.enabled = True
    db.commit()
    user = _user(db, "qc")
    _work, release = _work_release(db, user, qc_passed=False)
    try:
        submit_release(db, user, str(release.id))
        assert False, "should reject failed QC"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "QC" in str(exc.detail)


@pytest.mark.requires_db
def test_admin_mark_live_saves_store_url(db):
    user = _user(db, "live")
    work, release = _work_release(db, user)
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="spotify",
        distributor_code="distrokid",
        status="awaiting_manual",
    )
    db.add(delivery)
    db.commit()
    result = admin_set_delivery_status(
        db,
        str(delivery.id),
        "live",
        store_url="https://open.spotify.com/track/demo",
    )
    assert result["status"] == "live"
    assert result["store_url"] == "https://open.spotify.com/track/demo"
    db.refresh(release)
    assert release.status == "live"


@pytest.mark.requires_db
def test_update_release_copies_isrc_to_work(db):
    user = _user(db, "isrc")
    work, release = _work_release(db, user)
    update_release(db, user, str(release.id), {"isrc": "USXXX2600001"})
    db.refresh(work)
    assert work.isrc == "USXXX2600001"


@pytest.mark.requires_db
def test_admin_mark_release_live_all_channels(db):
    user = _user(db, "relive")
    work, release = _work_release(db, user)
    rows = []
    for code in ("spotify", "apple_music"):
        row = DistributionDelivery(
            release_id=release.id,
            work_id=work.id,
            owner_id=user.id,
            channel_code=code,
            distributor_code="distrokid",
            status="awaiting_manual",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    empty = admin_mark_release_live(db, str(release.id))
    assert empty["updated"] == 0
    assert empty["skipped"] == 2
    db.refresh(rows[0])
    assert rows[0].status == "awaiting_manual"
    rows[0].store_url = "https://open.spotify.com/track/abc123"
    rows[1].store_url = "https://music.apple.com/us/song/demo/1"
    db.commit()
    result = admin_mark_release_live(db, str(release.id))
    assert result["updated"] == 2
    db.refresh(release)
    db.refresh(work)
    assert release.status == "live"
    assert work.release_status == "live"


@pytest.mark.requires_db
def test_withdraw_blocked_when_wallet_flag_off(db):
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    if not flag:
        db.add(FeatureFlag(key="royalty_wallet", enabled=False))
    else:
        flag.enabled = False
    db.commit()
    user = _user(db, "wdflag")
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    try:
        request_withdrawal(db, user, {"amount_minor": 2000, "currency": "CNY", "channel": "alipay"})
        assert False, "should reject when wallet flag is off"
    except HTTPException as exc:
        assert exc.status_code == 403
    finally:
        row = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
        if row:
            row.enabled = True
            db.commit()


@pytest.mark.requires_db
def test_run_settlement_confirm_moves_available(db):
    user = _user(db, "settle")
    work, release = _work_release(db, user)
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=20))
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key="2026-08",
            streams=10,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    empty = run_settlement(db, period_key="2025-01")
    assert empty["lines"] == 0
    assert empty["reason"] == "no_unsettled_for_period"
    release.mode = "label"
    db.commit()
    result = run_settlement(db, period_key="2026-08")
    assert result["lines"] == 1
    assert result["needs_confirm"] is True
    wallet = get_or_create_wallet(db, user.id, "CNY")
    db.refresh(wallet)
    assert (wallet.pending_minor or 0) > 0
    assert (wallet.available_minor or 0) == 0
    draft_note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "settlement_draft")
        .order_by(Notification.created_at.desc())
        .first()
    )
    assert draft_note is not None
    confirm_settlement(db, result["batch_id"])
    db.refresh(wallet)
    assert (wallet.available_minor or 0) > 0
    assert (wallet.pending_minor or 0) == 0
    note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "settlement_ready")
        .order_by(Notification.created_at.desc())
        .first()
    )
    assert note is not None
    assert note.payload.get("period_key") == "2026-08"
    assert int(note.payload.get("amount_minor") or 0) == wallet.available_minor
    assert note.payload.get("currency") == "CNY"
    assert str(note.payload.get("receipt_no") or "").startswith("VS-S-")


@pytest.mark.requires_db
def test_list_batches_includes_net_minor(db):
    user = _user(db, "batch")
    batch = SettlementBatch(
        period_key=f"test-{uuid.uuid4().hex[:8]}",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        status="draft",
    )
    db.add(batch)
    db.commit()
    db.add(
        SettlementLine(
            batch_id=batch.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            gross_minor=1000,
            commission_minor=200,
            net_minor=800,
        )
    )
    db.commit()
    rows = list_batches(db)
    found = next(r for r in rows if r["id"] == str(batch.id))
    assert found["net_minor"] == 800
    assert found["line_count"] == 1
    assert found["user_count"] == 1
    assert found["platform_take_minor"] == 200
    detail = get_batch_detail(db, str(batch.id))
    assert detail["line_count"] == 1
    assert detail["lines"][0]["net_minor"] == 800


@pytest.mark.requires_db
def test_cannot_confirm_voided_or_empty_draft(db):
    empty = SettlementBatch(
        period_key=f"empty-{uuid.uuid4().hex[:8]}",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        status="draft",
    )
    db.add(empty)
    db.commit()
    try:
        confirm_settlement(db, str(empty.id))
        assert False, "empty draft should not confirm"
    except HTTPException as exc:
        assert exc.status_code == 400
    user = _user(db, "voided")
    batch = SettlementBatch(
        period_key=f"void-{uuid.uuid4().hex[:8]}",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        status="draft",
    )
    db.add(batch)
    db.commit()
    db.add(
        SettlementLine(
            batch_id=batch.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            gross_minor=1000,
            commission_minor=200,
            net_minor=800,
        )
    )
    db.commit()
    void_settlement(db, str(batch.id))
    try:
        confirm_settlement(db, str(batch.id))
        assert False, "voided batch should not confirm"
    except HTTPException as exc:
        assert exc.status_code == 400


@pytest.mark.requires_db
def test_supplemental_settlement_after_confirm(db):
    user = _user(db, "supp")
    work, release = _work_release(db, user)
    release.mode = "label"
    period = f"2097-{uuid.uuid4().hex[:2]}"
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-21", commission_rate=20))
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key=period,
            streams=10,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    first = run_settlement(db, period_key=period)
    confirm_settlement(db, first["batch_id"])
    work2 = Work(owner_id=user.id, title="Second Drive", audio_url="http://example.com/b.mp3")
    db.add(work2)
    db.commit()
    release2 = Release(work_id=work2.id, owner_id=user.id, mode="label", status="live", selected_channels=["netease"])
    db.add(release2)
    db.commit()
    db.add(DistributionLicense(user_id=user.id, release_id=release2.id, agreement_version="2026-08-21", commission_rate=20))
    db.add(
        PlatformMetricSnapshot(
            work_id=work2.id,
            release_id=release2.id,
            user_id=user.id,
            channel_code="netease",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key=period,
            streams=8,
            revenue_minor=500,
            currency="CNY",
        )
    )
    db.commit()
    second = run_settlement(db, period_key=period)
    assert second["lines"] == 1
    assert second["supplemental"] is True
    assert second["batch_id"] != first["batch_id"]
    assert second["status"] == "draft"


@pytest.mark.requires_db
def test_hub_streams_exclude_display_only(db):
    from app.api.routes.creator import hub

    user = _user(db, "hub")
    work, _release = _work_release(db, user)
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=True,
            period_key="2026-08",
            streams=100,
            revenue_minor=500,
        )
    )
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            user_id=user.id,
            channel_code="youtube_music",
            source="licensed_analytics",
            usable_for_settlement=False,
            period_key="2026-08",
            streams=9999,
            revenue_minor=8800,
        )
    )
    db.add(
        PlatformMetricSnapshot(
            user_id=user.id,
            channel_code="youtube_music",
            source="official_api",
            usable_for_settlement=False,
            period_key="latest",
            streams=50000,
        )
    )
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            user_id=user.id,
            channel_code="youtube_music",
            source="official_api",
            usable_for_settlement=False,
            period_key="latest",
            streams=3200,
        )
    )
    db.commit()
    payload = hub(user=user, db=db)
    assert payload["total_streams"] == 100
    assert payload["display_streams"] == 13199
    assert payload["settlement_revenue_minor"] == 500
    assert payload["display_revenue_minor"] == 8800
    assert payload["has_real_data"] is True
    assert payload["distribution_enabled"] in (True, False)
    assert "unclaimed_count" in payload
    assert "available_minor" in payload
    assert "available_by_currency" in payload


@pytest.mark.requires_db
def test_withdraw_requires_payout_account(db):
    user = _user(db, "wdnone")
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    try:
        request_withdrawal(db, user, {"amount_minor": 2000, "currency": "CNY", "channel": "alipay"})
        assert False, "should reject without payout account"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Payout account" in str(exc.detail)
    db.refresh(wallet)
    assert wallet.available_minor == 5000


@pytest.mark.requires_db
def test_withdraw_reject_restores_available(db):
    user = _user(db, "wd")
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    account = upsert_payout_account(
        db, user, {"channel": "alipay", "account_name": "t", "account_no": "18800003333", "is_default": True}
    )
    row = request_withdrawal(
        db,
        user,
        {"amount_minor": 2000, "currency": "CNY", "channel": "alipay", "payout_account_id": account["id"]},
    )
    db.refresh(wallet)
    assert wallet.available_minor == 3000
    assert wallet.frozen_minor == 2000
    review_withdrawal(db, row["id"], approve=False, admin_note="test reject")
    db.refresh(wallet)
    assert wallet.available_minor == 5000
    assert wallet.frozen_minor == 0
    note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "withdrawal_update")
        .order_by(Notification.created_at.desc())
        .first()
    )
    assert note is not None
    assert str(note.payload.get("receipt_no") or "").startswith("VS-W-")
    assert note.payload.get("amount_minor") == 2000
    assert note.payload.get("currency") == "CNY"
    assert note.payload.get("status") == "rejected"


@pytest.mark.requires_db
def test_withdraw_paid_notification_includes_receipt(db):
    user = _user(db, "wdpay")
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    account = upsert_payout_account(
        db, user, {"channel": "alipay", "account_name": "t", "account_no": "18800004444", "is_default": True}
    )
    row = request_withdrawal(
        db,
        user,
        {"amount_minor": 2000, "currency": "CNY", "channel": "alipay", "payout_account_id": account["id"]},
    )
    assert str(row.get("receipt_no") or "").startswith("VS-W-")
    paid = review_withdrawal(db, row["id"], approve=True, admin_note="paid")
    assert paid["status"] == "paid_manual"
    assert str(paid.get("receipt_no") or "").startswith("VS-W-")
    note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "withdrawal_paid")
        .order_by(Notification.created_at.desc())
        .first()
    )
    assert note is not None
    assert note.payload.get("receipt_no") == paid["receipt_no"]
    assert note.payload.get("amount_minor") == 2000
    assert note.payload.get("currency") == "CNY"


@pytest.mark.requires_db
def test_withdraw_requires_kyc(db):
    user = _user(db, "wdkyc")
    user.kyc_status = "none"
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    account = upsert_payout_account(
        db, user, {"channel": "alipay", "account_name": "t", "account_no": "18800005555", "is_default": True}
    )
    try:
        request_withdrawal(
            db,
            user,
            {"amount_minor": 2000, "currency": "CNY", "channel": "alipay", "payout_account_id": account["id"]},
        )
        assert False, "should reject without KYC"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "KYC" in str(exc.detail)
    db.refresh(wallet)
    assert wallet.available_minor == 5000
    assert wallet.frozen_minor in (0, None)


@pytest.mark.requires_db
def test_withdraw_rejects_foreign_payout_account(db):
    owner = _user(db, "wdown")
    thief = _user(db, "wdthief")
    wallet = get_or_create_wallet(db, thief.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    account = upsert_payout_account(
        db, owner, {"channel": "alipay", "account_name": "owner", "account_no": "18800006666", "is_default": True}
    )
    try:
        request_withdrawal(
            db,
            thief,
            {"amount_minor": 2000, "currency": "CNY", "channel": "alipay", "payout_account_id": account["id"]},
        )
        assert False, "should reject stolen payout account"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "belong" in str(exc.detail).lower()
    db.refresh(wallet)
    assert wallet.available_minor == 5000


@pytest.mark.requires_db
def test_concurrent_withdraw_does_not_double_spend(db):
    import threading

    from app.database import SessionLocal

    user = _user(db, "wdrace")
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    account = upsert_payout_account(
        db, user, {"channel": "alipay", "account_name": "t", "account_no": "18800007777", "is_default": True}
    )
    db.commit()
    db.expire_all()
    user_id = user.id
    account_id = account["id"]
    results: list[str | int] = []

    def attempt():
        session = SessionLocal()
        try:
            actor = session.query(User).filter(User.id == user_id).one()
            try:
                request_withdrawal(
                    session,
                    actor,
                    {"amount_minor": 2000, "currency": "CNY", "channel": "alipay", "payout_account_id": account_id},
                )
                results.append("ok")
            except HTTPException as exc:
                results.append(exc.status_code)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt), threading.Thread(target=attempt)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1
    assert 400 in results
    check = SessionLocal()
    try:
        row = (
            check.query(RoyaltyWallet)
            .filter(RoyaltyWallet.user_id == user_id, RoyaltyWallet.currency == "CNY")
            .one()
        )
        assert row.available_minor == 3000
        assert row.frozen_minor == 2000
    finally:
        check.close()


@pytest.mark.requires_db
def test_label_submit_enters_session_wait(db):
    seed_distribution_catalog(db)
    db.commit()
    user = _user(db, "labelq")
    work, release = _work_release(db, user)
    release.mode = "label"
    release.selected_channels = ["netease", "spotify"]
    work.isrc = "USXXX0000001"
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    meta.isrc = "USXXX0000001"
    db.commit()
    sign_license(db, user, str(release.id), "2026-08-19", 30)
    result = submit_release(db, user, str(release.id))
    if result["deliveries"] and result["deliveries"][0]["status"] == "submitting":
        from app.services.distribution.service import process_release_submit, serialize_release

        process_release_submit(db, str(release.id))
        release = db.query(Release).filter(Release.id == release.id).first()
        result = serialize_release(db, release)
    assert result["mode"] == "label"
    assert result["commission_rate"] == 30
    statuses = {d["channel_code"]: d["status"] for d in result["deliveries"]}
    assert statuses.get("netease") == "session_wait"
    assert statuses.get("spotify") == "metrics_only"
    netease = next(row for row in result["deliveries"] if row["channel_code"] == "netease")
    spotify = next(row for row in result["deliveries"] if row["channel_code"] == "spotify")
    assert netease["user_status"] == "assisting"
    assert "farm_or_extension_lease_wait" in str(netease.get("last_error") or "")
    assert netease.get("assist_job")
    assert spotify["user_status"] == "metrics_only"
    queued = admin_list_deliveries(db, queue_only=True)
    assert any(row["id"] == result["deliveries"][0]["id"] for row in queued)


@pytest.mark.requires_db
def test_settlement_uses_license_rate(db):
    user = _user(db, "licrate")
    work, release = _work_release(db, user)
    release.mode = "label"
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=30))
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="netease",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key="2026-09",
            streams=10,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    result = run_settlement(db, period_key="2026-09")
    assert result["lines"] == 1
    line = db.query(SettlementLine).filter(SettlementLine.user_id == user.id).first()
    assert line.commission_minor == 300
    assert line.net_minor == 700


@pytest.mark.requires_db
def test_submit_uses_catalog_fallback_without_seed(db):
    user = _user(db, "fb")
    work, release = _work_release(db, user)
    release.mode = "label"
    release.selected_channels = ["netease"]
    work.isrc = "USXXX0000001"
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    meta.isrc = "USXXX0000001"
    db.commit()
    sign_license(db, user, str(release.id), "2026-08-19", 20)
    result = submit_release(db, user, str(release.id))
    assert len(result["deliveries"]) == 1
    assert result["deliveries"][0]["channel_code"] == "netease"
    assert result["deliveries"][0]["status"] == "session_wait"


@pytest.mark.requires_db
def test_process_skips_live_delivery(db):
    user = _user(db, "liveok")
    work, release = _work_release(db, user)
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="spotify",
        distributor_code="distrokid",
        status="live",
        store_url="https://open.spotify.com/track/demo",
    )
    db.add(delivery)
    db.commit()
    result = process_one_delivery(db, delivery, force=False, commit=True)
    assert result.get("skipped") is True
    db.refresh(delivery)
    assert delivery.status == "live"


@pytest.mark.requires_db
def test_adapter_failure_does_not_block_other_channels(db):
    from app.services.distribution import adapters
    from app.services.distribution.adapters import AdapterResult, DistributorAdapter
    from app.services.distribution.pipeline import process_release_submit

    class Boom(DistributorAdapter):
        provider = "boom"

        def configured(self) -> bool:
            return True

        def submit(self, payload: dict) -> AdapterResult:
            raise RuntimeError("cn label timeout")

    adapters.ADAPTERS["cn_label"] = Boom()
    try:
        user = _user(db, "iso")
        work, release = _work_release(db, user)
        release.mode = "label"
        db.add(
            DistributionDelivery(
                release_id=release.id,
                work_id=work.id,
                owner_id=user.id,
                channel_code="netease",
                distributor_code="cn_label",
                status="submitting",
            )
        )
        db.add(
            DistributionDelivery(
                release_id=release.id,
                work_id=work.id,
                owner_id=user.id,
                channel_code="spotify",
                distributor_code="distrokid",
                status="submitting",
            )
        )
        db.commit()
        process_release_submit(db, str(release.id))
        rows = {d.channel_code: d for d in db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id)}
        assert rows["spotify"].status == "metrics_only"
        assert rows["netease"].status == "submitting"
        assert rows["netease"].last_error
    finally:
        adapters.ADAPTERS["cn_label"] = adapters.CnLabelAdapter()


@pytest.mark.requires_db
def test_reconcile_repairs_queued_release_without_deliveries(db):
    from app.services.distribution.pipeline import reconcile_distribution

    user = _user(db, "repair")
    work, release = _work_release(db, user)
    release.mode = "label"
    release.status = "queued"
    release.selected_channels = ["netease"]
    db.commit()
    result = reconcile_distribution(db)
    assert result["repaired_deliveries"] >= 1
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    assert rows
    assert all(row.channel_code == "netease" for row in rows)
    assert all(row.status in ("ops_queue", "submitting", "awaiting_manual", "session_wait", "session_running") for row in rows)


@pytest.mark.requires_db
def test_set_store_url_marks_self_release_live(db):
    user = _user(db, "selfurl")
    work, release = _work_release(db, user)
    release.mode = "self_release"
    release.status = "delivering"
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="spotify",
        distributor_code="distrokid",
        status="awaiting_manual",
    )
    db.add(delivery)
    db.commit()
    result = set_store_url(db, user, str(delivery.id), "https://open.spotify.com/track/demo")
    assert result["status"] == "live"
    assert result["user_status"] == "live"
    assert result["store_url"] == "https://open.spotify.com/track/demo"
    assert result["upload_url"]
    db.refresh(release)
    assert release.status == "live"


@pytest.mark.requires_db
def test_set_store_url_label_marks_live(db):
    user = _user(db, "labelurl")
    work, release = _work_release(db, user)
    release.mode = "label"
    release.status = "delivering"
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="ops_queue",
    )
    db.add(delivery)
    db.commit()
    result = set_store_url(db, user, str(delivery.id), "https://music.163.com/song?id=1")
    assert result["status"] == "live"
    assert result["user_status"] == "live"
    assert result["store_url"] == "https://music.163.com/song?id=1"
    db.refresh(release)
    assert release.status == "live"


@pytest.mark.requires_db
def test_official_export_without_license_is_skipped(db):
    user = _user(db, "nolic")
    work, release = _work_release(db, user)
    release.mode = "label"
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key="2026-08",
            streams=10,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    result = run_settlement(db, period_key="2026-08")
    assert result["lines"] == 0
    assert (result.get("skipped") or {}).get("no_license") == 1


@pytest.mark.requires_db
def test_radio_warmup_does_not_settle(db):
    user = _user(db, "radio")
    work, release = _work_release(db, user)
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="vibe_radio",
            source="first_party_radio",
            usable_for_settlement=True,
            settled=False,
            period_key="2026-08",
            streams=1,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    result = run_settlement(db, period_key="2026-08")
    assert result["lines"] == 0
    line = db.query(SettlementLine).filter(SettlementLine.user_id == user.id).first()
    assert line is None
    wallet = get_or_create_wallet(db, user.id, "CNY")
    db.refresh(wallet)
    assert (wallet.pending_minor or 0) == 0
    assert (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_official_ingest_isrc_and_license_opens_draft(db):
    from app.services.royalty.ingest import ingest_report, list_isrc_unmatched_snapshots

    user = _user(db, "isrcin")
    work, release = _work_release(db, user)
    work.isrc = "USXXX0000001"
    release.mode = "label"
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    meta.isrc = "USXXX0000001"
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=20))
    db.commit()
    raw = (
        "ISRC,Title,Store,Streams,Revenue,Currency,Period\n"
        "USXXX0000001,Night Drive,Spotify,1200,12.50,CNY,2026-08\n"
    ).encode()
    result = ingest_report(db, user=user, content=raw, filename="dk.csv", source="distributor_export")
    assert result["usable_for_settlement"] is True
    assert result["skipped_no_isrc"] == 0
    drafts = result.get("draft_batches") or []
    assert any(int(row.get("lines") or 0) == 1 and row.get("needs_confirm") for row in drafts)
    assert list_isrc_unmatched_snapshots(db) == []
    wallet = get_or_create_wallet(db, user.id, "CNY")
    db.refresh(wallet)
    assert (wallet.pending_minor or 0) > 0
    assert (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_title_only_official_row_stays_unmatched(db):
    from app.services.royalty.ingest import ingest_report, list_isrc_unmatched_snapshots

    user = _user(db, "titleonly")
    work, release = _work_release(db, user)
    release.mode = "label"
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=20))
    db.commit()
    raw = (
        "Title,Store,Streams,Revenue,Currency,Period\n"
        "Night Drive,Spotify,1200,12.50,CNY,2026-08\n"
    ).encode()
    result = ingest_report(db, user=user, content=raw, filename="title.csv", source="distributor_export")
    assert result["usable_for_settlement"] is False
    assert result["skipped_no_isrc"] >= 1
    assert not any(int(row.get("lines") or 0) for row in (result.get("draft_batches") or []))
    unmatched = list_isrc_unmatched_snapshots(db)
    assert any(row["reason"] == "no_isrc" for row in unmatched)


@pytest.mark.requires_db
def test_official_bill_splits_collaborators(db):
    owner = _user(db, "splitown")
    collab = _user(db, "splitcol")
    work, release = _work_release(db, owner)
    release.mode = "label"
    db.add(DistributionLicense(user_id=owner.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=20))
    db.add(WorkSplitShare(work_id=work.id, user_id=owner.id, role="owner", percent=70))
    db.add(WorkSplitShare(work_id=work.id, user_id=collab.id, role="collaborator", percent=30))
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=owner.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key="2026-08",
            streams=10,
            revenue_minor=1000,
            currency="CNY",
        )
    )
    db.commit()
    result = run_settlement(db, period_key="2026-08")
    assert result["lines"] == 2
    lines = db.query(SettlementLine).filter(SettlementLine.work_id == work.id).all()
    by_user = {line.user_id: line for line in lines}
    assert by_user[owner.id].net_minor == 560
    assert by_user[collab.id].net_minor == 240
    owner_wallet = get_or_create_wallet(db, owner.id, "CNY")
    collab_wallet = get_or_create_wallet(db, collab.id, "CNY")
    db.refresh(owner_wallet)
    db.refresh(collab_wallet)
    assert owner_wallet.pending_minor == 560
    assert collab_wallet.pending_minor == 240
    detail = get_batch_detail(db, result["batch_id"])
    roles = {row["user_id"]: row.get("share_role") for row in detail["lines"]}
    assert roles[str(owner.id)] == "owner"
    assert roles[str(collab.id)] == "collaborator"


@pytest.mark.requires_db
def test_label_submit_requires_isrc(db):
    seed_distribution_catalog(db)
    db.commit()
    user = _user(db, "noisrc")
    _work, release = _work_release(db, user)
    release.mode = "label"
    release.selected_channels = ["spotify"]
    db.commit()
    sign_license(db, user, str(release.id), "2026-08-19", 20)
    try:
        submit_release(db, user, str(release.id))
        assert False, "ISRC required"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "ISRC" in str(exc.detail)


@pytest.mark.requires_db
def test_sign_license_rejects_rate_below_tier_floor(db):
    user = _user(db, "floor")
    _work, release = _work_release(db, user)
    release.mode = "label"
    db.commit()
    try:
        sign_license(db, user, str(release.id), "2026-08-19", 10)
        assert False, "standard cannot pick 10"
    except HTTPException as exc:
        assert exc.status_code == 400


@pytest.mark.requires_db
def test_revalidate_isrc_flips_official_snapshot(db):
    from app.services.royalty.ingest import revalidate_isrc_snapshots_for_work

    user = _user(db, "reval")
    work, release = _work_release(db, user)
    release.mode = "label"
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-08-19", commission_rate=20))
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=user.id,
            channel_code="spotify",
            source="distributor_export",
            usable_for_settlement=False,
            settled=False,
            period_key="2026-08",
            streams=10,
            revenue_minor=1000,
            currency="CNY",
            raw={"isrc": "USXXX0000001", "title": "Night Drive"},
        )
    )
    db.commit()
    work.isrc = "USXXX0000001"
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    meta.isrc = "USXXX0000001"
    db.commit()
    result = revalidate_isrc_snapshots_for_work(db, work.id)
    assert result["usable"] >= 1
    snap = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.source == "distributor_export")
        .first()
    )
    assert snap.usable_for_settlement is True
