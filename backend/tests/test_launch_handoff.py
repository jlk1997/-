import uuid
from types import SimpleNamespace

import pytest

from app.models.schemas import DistributionDelivery, DistributionLicense, FeatureFlag, Release, ReleaseMetadata, RoyaltyWallet, User, Withdrawal, Work
from app.services.distribution.assist import complete_assist_job
from app.services.distribution.catalog import (
    DEFAULT_UPLOAD_CHANNELS,
    default_upload_channels,
    default_volume_channels,
    has_live_receipt,
    pick_configured_aggregator,
    seed_distribution_catalog,
)
from app.services.distribution.pipeline import process_one_delivery
from app.services.distribution.service import (
    admin_mark_release_live,
    release_next_action,
    serialize_release,
    submit_release,
)
from app.services.ops_dashboard import ops_daily_digest


def test_launch_channels_when_no_partner_keys():
    pack = default_volume_channels()
    upload = default_upload_channels()
    if not any(pick_configured_aggregator(code) for code in ("netease", "spotify", "apple_music")):
        assert pack == list(DEFAULT_UPLOAD_CHANNELS)
        assert upload == list(DEFAULT_UPLOAD_CHANNELS)
        assert "spotify" not in pack
        assert "spotify" not in upload
    assert has_live_receipt(store_url="https://artists.spotify.com/") is False
    assert has_live_receipt(store_url="https://music.163.com/st/musician") is False
    assert has_live_receipt(external_id="dk_1") is True
    assert has_live_receipt(store_url="https://open.spotify.com/track/abc") is True
    assert has_live_receipt(store_url="https://soundcloud.com/you/insights", channel_code="soundcloud") is False
    assert has_live_receipt(store_url="https://soundcloud.com/artist/night-drive", channel_code="soundcloud") is True


def test_l0_handoff_client_and_copy_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    client = root / "apps" / "client" / "src"
    zh = (root / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    en = (root / "packages" / "i18n" / "src" / "locales" / "en.ts").read_text(encoding="utf-8")
    quick = (client / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    deliveries = (client / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    timeline = (client / "packageCreator" / "ChannelTimeline.tsx").read_text(encoding="utf-8")
    radio = (client / "packageSocial" / "pages" / "radio" / "index.tsx").read_text(encoding="utf-8")
    onboarding = (client / "utils" / "onboarding.ts").read_text(encoding="utf-8")
    catalog = (root / "backend" / "app" / "services" / "distribution" / "catalog.py").read_text(encoding="utf-8")
    service = (root / "backend" / "app" / "services" / "distribution" / "service.py").read_text(encoding="utf-8")
    automation = (root / "backend" / "app" / "services" / "distribution" / "automation.py").read_text(encoding="utf-8")
    assert "LAUNCH_HANDOFF_CHANNELS = (\"netease\", \"spotify\", \"wechat_channels\")" in catalog
    assert "DEFAULT_UPLOAD_CHANNELS = (\"netease\",)" in catalog
    assert "if not channels:" in service
    card = (client / "packageCreator" / "ShipCompleteCard.tsx").read_text(encoding="utf-8")
    assert "export function ShipCompleteCard" in card
    assert "一键全球" not in card
    assert "shipMetricsGroup" in zh
    assert "shipFillGroup" in zh
    assert "shipSettleHint" in zh
    assert "shipPublishingPaste" in zh
    release = (client / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    assert "shipChannelGroup" in release
    lib = (client / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    assert "pickShipBandAction" in lib
    assert 'if (unpublished) return "release"' in lib
    assert 'raise HTTPException(409, "NEEDS_AUTH")' not in service
    assert '"needs_auth": next_action == "wait_connector"' in service
    assert 'return False' in automation and "if row is None:" in automation
    assert "oneTapWaitConnector" in zh and "oneTapAssisting" in zh and "oneTapOpsQueue" in zh
    assert "confirmOnceHint" in zh and "没有店页回执不会标已上架" in zh
    assert "publishToDiscover: \"发到发现\"" in zh
    assert "shipToStores: \"上店发行\"" in zh
    assert "syncLicense: \"商用授权\"" in zh
    assert "publishToFeed: \"发到发现\"" in zh
    assert "oneTapWaitConnector" in en
    assert "toastForNextAction" in quick
    assert "locale.creatorUi.confirmOnceHint" in quick
    assert "openDeliveries" in quick
    assert "<AuthDesk" in deliveries
    assert 'id: "handoff"' in timeline and 'id: "assisting"' in timeline
    assert "Station enter is tap-to-play" in radio
    assert 'AUTO_COACH_PAGES: CoachPage[] = ["create", "creator"]' in onboarding
    assert (client / "assets" / "tab" / "library.png").exists()


def test_ops_digest_and_http_domain_are_honest():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    ops = (root / "backend" / "app" / "services" / "ops_dashboard.py").read_text(encoding="utf-8")
    assert "WithdrawalRequest" not in ops
    assert "Withdrawal.status" in ops
    assert "pending_kyc" in ops
    nginx = (root / "deploy" / "nginx" / "ip.conf").read_text(encoding="utf-8")
    assert "superformersmusic.com" in nginx
    assert "return 301 https" not in nginx
    https = (root / "deploy" / "nginx" / "https.superformersmusic.com.conf").read_text(encoding="utf-8")
    assert "ssl_certificate" in https
    assert "Install ONLY after TLS" in https
    assert "/opt/bittune/certs/superformersmusic.com_bundle.pem" in https
    assert "139.199.90.218" in https
    locations = (root / "deploy" / "nginx" / "app_locations.inc").read_text(encoding="utf-8")
    assert "include /etc/nginx/snippets/bittune_locations.inc" in nginx
    assert "include /etc/nginx/snippets/bittune_locations.inc" in https
    assert r"\.[0-9a-f]{8,}\.(?:js|css)$" in locations
    app_config = (root / "apps" / "client" / "src" / "app.config.ts").read_text(encoding="utf-8")
    assert 'pagePath: "pages/library/index"' in app_config
    assert "assets/tab/library.png" in app_config
    handoff = (root / "backend" / "app" / "services" / "distribution" / "handoff.py").read_text(encoding="utf-8")
    assert "resume_waiting_uploads" in handoff


def test_release_next_action_honest_states():
    wait = SimpleNamespace(status="session_wait", last_error=None)
    assist = SimpleNamespace(status="session_running", last_error=None)
    ops = SimpleNamespace(status="ops_queue", last_error=None)
    live = SimpleNamespace(status="live", last_error=None, store_url=None, external_id="dk_1", channel_code="spotify")
    ghost = SimpleNamespace(status="live", last_error=None, store_url=None, external_id=None, channel_code="spotify")
    assert release_next_action([]) == "wait_connector"
    assert release_next_action([wait]) == "wait_connector"
    assert release_next_action([assist]) == "assisting"
    assert release_next_action([ops]) == "ops_handling"
    assert release_next_action([live]) == "live"
    assert release_next_action([ghost]) == "publishing"
    assert release_next_action([live, ops]) == "ops_handling"
    assert release_next_action([live, wait]) == "wait_connector"
    assert release_next_action([live, assist]) == "assisting"


@pytest.mark.requires_db
def test_one_tap_without_keys_creates_handoff_then_live_harvest_withdraw(db):
    from app.services.harvest.ingest import ingest_harvest_rows
    from app.services.royalty.wallet import get_or_create_wallet, request_withdrawal, upsert_payout_account
    from app.services.seats.service import connect_user_seat, save_seat_session

    user = User(
        email=f"handoff-{uuid.uuid4()}@test.local",
        username=f"ho_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        kyc_status="verified",
    )
    pending = User(
        email=f"kyc-{uuid.uuid4()}@test.local",
        username=f"kyc_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        kyc_status="pending",
    )
    db.add_all([user, pending])
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(
        work_id=work.id,
        owner_id=user.id,
        mode="self_release",
        status="qc",
        selected_channels=None,
        qc_result={"passed": True},
    )
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
    db.commit()
    seed_distribution_catalog(db)
    data = submit_release(db, user, str(release.id))
    codes = {row["channel_code"] for row in data["deliveries"]}
    assert "netease" in codes
    assert "spotify" not in codes
    assert data["next_action"] in {"wait_connector", "assisting", "publishing"}
    assert data.get("needs_handoff") in {True, False}
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    assert rows
    for row in rows:
        process_one_delivery(db, row, force=True, commit=True)
        db.refresh(row)
    parked = serialize_release(db, release)
    assert parked["next_action"] in {"wait_connector", "assisting"}
    assert parked["needs_handoff"] == (parked["next_action"] == "wait_connector")
    netease = next(row for row in rows if row.channel_code == "netease")
    live = complete_assist_job(db, user, str(netease.id), store_url="https://music.163.com/song?id=88")
    assert live["status"] == "live"
    empty_live = admin_mark_release_live(db, str(release.id))
    assert empty_live["updated"] == 0 or empty_live["skipped"] >= 1
    seat = connect_user_seat(db, user, "netease")
    save_seat_session(db, seat, session={"cookies": [{"name": "MUSIC_U", "value": "x"}]}, mark_live=True)
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-09", commission_rate=20))
    db.commit()
    harvest = ingest_harvest_rows(
        db,
        [
            {
                "channel_code": "netease",
                "period_key": "2026-09",
                "work_id": str(work.id),
                "title": "Night Drive",
                "streams": 80,
                "revenue_minor": 2000,
                "confidence": 0.95,
            }
        ],
        seat=seat,
        settle=True,
    )
    assert harvest["matched"] == 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == user.id).first()
    assert wallet is not None
    assert (wallet.available_minor or 0) > 0
    credits_flag = db.query(FeatureFlag).filter(FeatureFlag.key == "royalty_wallet").first()
    if credits_flag:
        credits_flag.enabled = True
        db.commit()
    account = upsert_payout_account(
        db,
        user,
        {"channel": "alipay", "account_name": "t", "account_no": "18800005555", "is_default": True},
    )
    get_or_create_wallet(db, user.id, "CNY")
    db.refresh(wallet)
    if (wallet.available_minor or 0) < 1000:
        wallet.available_minor = 2000
        db.commit()
    row = request_withdrawal(
        db,
        user,
        {"amount_minor": 1000, "currency": "CNY", "channel": "alipay", "payout_account_id": account["id"]},
    )
    assert row["status"] == "pending"
    digest = ops_daily_digest(db)
    assert digest["actionable"]["pending_payouts"] >= 1
    assert digest["actionable"]["pending_kyc"] >= 1
    assert db.query(Withdrawal).filter(Withdrawal.status == "pending").count() >= 1
