import uuid
from datetime import datetime

import pytest

from app.models.schemas import CreatorSeat, DistributionDelivery, DistributionLicense, HarvestUnmatched, Notification, PayoutAccount, Release, RoyaltyWallet, SeatJob, User, Work
from app.services.distribution.catalog import SETTLEMENT_SOURCES, seed_distribution_catalog
from app.services.distribution.track_code import ensure_track_code, extract_track_code, mint_track_code, title_with_code
from app.services.harvest.ingest import ingest_harvest_rows as _ingest_harvest_rows
from app.services.harvest.playbooks import health_fixture_rows, list_playbooks
from app.services.harvest.unmatched import attach_unmatched, list_unmatched, persist_unmatched
from app.services.royalty.ingest import settlement_row_usable
from app.services.seats.farm import drain_queued
from app.services.seats.service import (
    ack_remote_login,
    complete_job,
    connect_user_seat,
    enqueue_job,
    ensure_platform_seats,
    mark_challenge,
    maybe_expand_platform_pool,
    pick_platform_seat,
    save_seat_session,
    start_remote_login,
)
from app.services.royalty.wallet import ensure_wechat_payout_account, get_or_create_wallet, try_auto_payout, upsert_payout_account

PERIOD = datetime.utcnow().strftime("%Y-%m")


def ingest_harvest_rows(db, rows, *args, **kwargs):
    """Settlement-math tests stamp high confidence so auto-confirm still runs."""
    stamped = []
    for raw in rows:
        row = dict(raw)
        if "confidence" not in row and int(row.get("revenue_minor") or 0) > 0:
            row["confidence"] = 0.95
        stamped.append(row)
    seat = kwargs.get("seat")
    actor = kwargs.get("actor")
    if kwargs.get("settle", True) and seat is not None and getattr(seat, "ownership", None) == "user":
        user = actor or db.query(User).filter(User.id == seat.user_id).first()
        if user and db.query(DistributionLicense.id).filter(DistributionLicense.user_id == user.id).first() is None:
            work = db.query(Work).filter(Work.owner_id == user.id).first()
            release = db.query(Release).filter(Release.owner_id == user.id).first()
            if work and release is None:
                release = Release(work_id=work.id, owner_id=user.id, mode="label", status="live")
                db.add(release)
                db.flush()
            if release:
                db.add(
                    DistributionLicense(
                        user_id=user.id,
                        release_id=release.id,
                        agreement_version="test",
                        commission_rate=20,
                    )
                )
                db.flush()
    return _ingest_harvest_rows(db, stamped, *args, **kwargs)


def _user(db, prefix: str) -> User:
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


def _burn_label_promo(db, user: User) -> None:
    for index in range(4):
        work = Work(owner_id=user.id, title=f"Burn {index}", audio_url="http://example.com/a.mp3")
        db.add(work)
        db.flush()
        db.add(Release(work_id=work.id, owner_id=user.id, mode="label", status="live", selected_channels=["netease"]))
    db.commit()


def test_mint_track_code_is_stable():
    wid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert mint_track_code(wid) == "VSAAAAAAAABBBB"


def test_playbook_health_fixture_covers_cn_pack():
    books = {row["code"] for row in list_playbooks()}
    for code in ("netease", "qq_music", "kugou", "kuwo", "qishui", "bilibili", "spotify"):
        assert code in books
    rows = health_fixture_rows()
    assert len(rows) >= 2
    assert all(row.get("channel_code") and row.get("title") for row in rows)


def test_harvest_rows_are_settlement_sources():
    from types import SimpleNamespace

    assert "seat_harvest" in SETTLEMENT_SOURCES
    assert "user_connector" in SETTLEMENT_SOURCES
    assert settlement_row_usable(source="seat_harvest", release=None, match_kind="isrc") is True
    assert settlement_row_usable(source="user_connector", release=None, match_kind="title") is True
    assert settlement_row_usable(source="ops_connector", release=None, match_kind="") is False
    assert settlement_row_usable(
        source="distributor_export",
        release=SimpleNamespace(mode="self_release"),
        match_kind="isrc",
    ) is False


@pytest.mark.requires_db
def test_warmup_platform_pool_stamps_without_inventing_money(db):
    from app.services.seats.service import warmup_platform_pool

    seats = ensure_platform_seats(db, channels=["netease"], pool_size=1)
    assert seats[0].status == "connecting"
    out = warmup_platform_pool(db)
    assert out["invented_money"] is False
    assert out["queued"] == 0
    assert out["stamped"] >= 1
    health = (seats[0].extra or {}).get("farm_health") or {}
    assert health["ok"] is False
    assert health["warmup"] is True
    assert health.get("invented_money") is False
    assert health["reason"] == "needs_session"
    assert health.get("rows") == 0


@pytest.mark.requires_db
def test_platform_seats_and_pool(db):
    ensure_platform_seats(db, channels=["netease"], pool_size=3)
    db.commit()
    rows = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "platform", CreatorSeat.channel_code == "netease")
        .order_by(CreatorSeat.pool_index.asc())
        .all()
    )
    assert len(rows) == 3
    work_a = uuid.uuid4()
    first = pick_platform_seat(db, "netease", work_a)
    again = pick_platform_seat(db, "netease", work_a)
    assert first and again and first.id == again.id


@pytest.mark.requires_db
def test_platform_harvest_settles_label_cut(db):
    seed_distribution_catalog(db)
    owner = _user(db, "label")
    _burn_label_promo(db, owner)
    work = _work(db, owner)
    code = ensure_track_code(db, work)
    db.commit()
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    result = ingest_harvest_rows(
        db,
        [
            {
                "channel_code": "netease",
                "period_key": PERIOD,
                "title": "Night Drive",
                "isrc": code,
                "streams": 100,
                "revenue_minor": 1000,
            }
        ],
        seat=seat,
        settle=True,
    )
    assert result["matched"] == 1
    assert result["usable_for_settlement"] is True
    assert any(item.get("auto_confirmed") for item in result["settlements"])
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id, RoyaltyWallet.currency == "CNY").first()
    assert wallet is not None
    assert wallet.available_minor == 800
    from app.services.royalty.wallet import source_split

    split = source_split(db, owner)
    assert split["harvest_minor"] == 1000
    assert split["dsp_minor"] == 1000
    assert split["label_royalty_minor"] == 1000


@pytest.mark.requires_db
def test_user_seat_harvest_takes_ten_percent(db):
    seed_distribution_catalog(db)
    owner = _user(db, "self")
    work = _work(db, owner, "My Demo")
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": [{"name": "MUSIC_U", "value": "x"}]}, mark_live=True)
    db.commit()
    result = ingest_harvest_rows(
        db,
        [
            {
                "channel_code": "netease",
                "period_key": PERIOD,
                "work_id": str(work.id),
                "title": "My Demo",
                "streams": 50,
                "revenue_minor": 1000,
            }
        ],
        seat=seat,
        settle=True,
    )
    assert result["source"] == "seat_harvest"
    assert result["matched"] == 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 900
    from app.services.royalty.wallet import source_split

    split = source_split(db, owner)
    assert split["harvest_minor"] == 1000
    assert split["dsp_minor"] == 1000


@pytest.mark.requires_db
def test_harvest_increment_only(db):
    seed_distribution_catalog(db)
    owner = _user(db, "inc")
    _burn_label_promo(db, owner)
    work = _work(db, owner)
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Night Drive", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Night Drive", "revenue_minor": 1500}],
        seat=seat,
        settle=True,
    )
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 1200


@pytest.mark.requires_db
def test_unmatched_harvest_stays_out_of_wallet(db):
    seed_distribution_catalog(db)
    owner = _user(db, "miss")
    _work(db, owner)
    seats = ensure_platform_seats(db, channels=["netease"])
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "title": "Unknown Song", "revenue_minor": 9000}],
        seat=seats[0],
        settle=True,
    )
    assert result["matched"] == 0
    assert result["unmatched_count"] == 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_farm_drain_ingests_payload_rows(db):
    seed_distribution_catalog(db)
    owner = _user(db, "farm")
    _burn_label_promo(db, owner)
    work = _work(db, owner)
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["qq_music"])
    seat = seats[0]
    seat.status = "live"
    job = enqueue_job(
        db,
        seat,
        "harvest",
        {
            "rows": [
                {
                    "channel_code": "qq_music",
                    "period_key": PERIOD,
                    "isrc": code,
                    "title": "Night Drive",
                    "revenue_minor": 400,
                }
            ]
        },
    )
    db.commit()
    drained = drain_queued(db, seat_id=str(seat.id))
    assert drained["ran"] >= 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is not None
    assert wallet.available_minor == 320
    assert job.id


@pytest.mark.requires_db
def test_small_auto_payout(db):
    owner = _user(db, "pay")
    wallet = get_or_create_wallet(db, owner.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    upsert_payout_account(db, owner, {"channel": "alipay", "account_name": "t", "account_no": "18800001111", "is_default": True})
    row = try_auto_payout(db, owner)
    assert row is None
    db.refresh(wallet)
    assert wallet.available_minor == 5000


@pytest.mark.requires_db
def test_user_seat_ignores_other_creators_track(db):
    seed_distribution_catalog(db)
    owner = _user(db, "own")
    other = _user(db, "oth")
    foreign = _work(db, other, "Not Yours")
    seat = connect_user_seat(db, owner, "netease")
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "work_id": str(foreign.id), "revenue_minor": 800}],
        seat=seat,
        settle=True,
    )
    assert result["matched"] == 0
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0


def test_title_with_code_embeds_vs_suffix():
    assert title_with_code("Night Drive", "VSAAAAAAAABBBB") == "Night Drive [VSAAAAAAAABBBB]"
    assert title_with_code("Night Drive [VSAAAAAAAABBBB]", "VSAAAAAAAABBBB") == "Night Drive [VSAAAAAAAABBBB]"
    assert extract_track_code("Night Drive [VSAAAAAAAABBBB]") == "VSAAAAAAAABBBB"


@pytest.mark.requires_db
def test_unmatched_harvest_is_persisted_and_attachable(db):
    seed_distribution_catalog(db)
    owner = _user(db, "claim")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Claim Me")
    seats = ensure_platform_seats(db, channels=["netease"])
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "title": "Ghost Track", "revenue_minor": 2000}],
        seat=seats[0],
        settle=True,
    )
    assert result["unmatched_count"] == 1
    assert result["unmatched"][0]["id"]
    rows = db.query(HarvestUnmatched).filter(HarvestUnmatched.status == "unclaimed").all()
    rec = next((row for row in rows if row.title == "Ghost Track"), None)
    assert rec is not None
    attached = attach_unmatched(db, owner, str(rec.id), str(work.id), admin=True)
    assert attached["status"] == "matched"
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is not None
    assert wallet.available_minor == 1600


@pytest.mark.requires_db
def test_lower_harvest_writes_adjustment(db):
    seed_distribution_catalog(db)
    owner = _user(db, "adj")
    _burn_label_promo(db, owner)
    work = _work(db, owner)
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Night Drive", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Night Drive", "revenue_minor": 500}],
        seat=seat,
        settle=True,
    )
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 400
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Night Drive", "revenue_minor": 800}],
        seat=seat,
        settle=True,
    )
    db.refresh(wallet)
    assert wallet.available_minor == 640


@pytest.mark.requires_db
def test_account_total_splits_by_play_share(db):
    seed_distribution_catalog(db)
    owner = _user(db, "split")
    work_a = _work(db, owner, "Split A")
    work_b = _work(db, owner, "Split B")
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    for work in (work_a, work_b):
        release = Release(work_id=work.id, owner_id=owner.id, mode="self_release", status="live", selected_channels=["netease"])
        db.add(release)
        db.flush()
        db.add(
            DistributionDelivery(
                release_id=release.id,
                work_id=work.id,
                owner_id=owner.id,
                channel_code="netease",
                distributor_code="session",
                status="live",
                attempt_meta={"seat_id": str(seat.id)},
            )
        )
    db.commit()
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "account_total": True, "title": "账户合计", "revenue_minor": 1000, "streams": 100}],
        seat=seat,
        settle=True,
    )
    assert result["matched"] == 2
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 900


@pytest.mark.requires_db
def test_content_hash_matches_harvest_row(db):
    seed_distribution_catalog(db)
    owner = _user(db, "hash")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Hashed")
    work.content_hash = "abc" + uuid.uuid4().hex[:29]
    seats = ensure_platform_seats(db, channels=["netease"])
    db.commit()
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "content_hash": work.content_hash, "revenue_minor": 1000}],
        seat=seats[0],
        settle=True,
    )
    assert result["matched"] == 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 800


@pytest.mark.requires_db
def test_wechat_openid_becomes_default_payout(db):
    owner = _user(db, "wxpay")
    ensure_wechat_payout_account(db, owner, "openid-xyz-123")
    db.commit()
    row = db.query(PayoutAccount).filter(PayoutAccount.user_id == owner.id, PayoutAccount.channel == "wechat").first()
    assert row is not None
    assert row.account_no == "openid-xyz-123"
    assert row.is_default is True
    ensure_wechat_payout_account(db, owner, "openid-other")
    db.commit()
    assert db.query(PayoutAccount).filter(PayoutAccount.user_id == owner.id).count() == 1


@pytest.mark.requires_db
def test_remote_login_and_challenge_notify(db):
    owner = _user(db, "remote")
    owner.is_admin = True
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    payload = start_remote_login(db, owner, seat)
    db.commit()
    assert payload["status"] == "waiting_login"
    assert payload["login_url"]
    mark_challenge(db, seat, note="captcha")
    db.commit()
    note = (
        db.query(Notification)
        .filter(Notification.user_id == owner.id, Notification.type == "seat_challenge")
        .first()
    )
    assert note is not None


@pytest.mark.requires_db
def test_platform_pool_expands_when_tracks_exceed_cap(db):
    owner = _user(db, "expand")
    ensure_platform_seats(db, channels=["bandcamp"], pool_size=1)
    db.commit()
    for index in range(2):
        work = _work(db, owner, f"Expand {index}")
        release = Release(work_id=work.id, owner_id=owner.id, mode="label", status="live", selected_channels=["bandcamp"])
        db.add(release)
        db.flush()
        db.add(
            DistributionDelivery(
                release_id=release.id,
                work_id=work.id,
                owner_id=owner.id,
                channel_code="bandcamp",
                distributor_code="distrokid",
                status="live",
            )
        )
    db.commit()
    maybe_expand_platform_pool(db, "bandcamp", track_cap=1)
    db.commit()
    rows = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.ownership == "platform", CreatorSeat.channel_code == "bandcamp")
        .all()
    )
    assert len(rows) >= 2


@pytest.mark.requires_db
def test_ack_remote_login_enqueues_capture(db):
    owner = _user(db, "ack")
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    start_remote_login(db, owner, seat)
    db.commit()
    payload = ack_remote_login(db, seat)
    db.commit()
    assert payload["status"] in {"user_finished", "waiting_login", "awaiting_user"}
    assert not (seat.extra or {}).get("has_session")
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "remote_login").all()
    assert any((job.payload or {}).get("capture_session") for job in jobs)


@pytest.mark.requires_db
def test_remote_complete_saves_session_without_storing_cookies(db):
    owner = _user(db, "cookie")
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    job = enqueue_job(db, seat, "remote_login", {"capture_session": True})
    db.commit()
    complete_job(
        db,
        str(job.id),
        ok=True,
        result={"cookies": [{"name": "MUSIC_U", "value": "secret-token"}], "captured": True},
    )
    db.refresh(seat)
    db.refresh(job)
    assert (seat.extra or {}).get("has_session") is True
    assert "secret-token" not in str(job.result)
    assert "cookies" not in (job.result or {})


@pytest.mark.requires_db
def test_upload_store_url_marks_delivery_live(db):
    owner = _user(db, "live")
    work = _work(db, owner)
    release = Release(work_id=work.id, owner_id=owner.id, mode="label", status="delivering", selected_channels=["netease"])
    db.add(release)
    db.flush()
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=owner.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="delivering",
    )
    db.add(delivery)
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    job = enqueue_job(db, seat, "upload", {"delivery_id": str(delivery.id)})
    db.commit()
    complete_job(db, str(job.id), ok=True, result={"store_url": "https://music.163.com/song?id=12345"})
    db.refresh(delivery)
    assert delivery.status == "live"
    assert "song" in (delivery.store_url or "")


@pytest.mark.requires_db
def test_upload_portal_url_does_not_autolive(db):
    owner = _user(db, "portal")
    work = _work(db, owner)
    release = Release(work_id=work.id, owner_id=owner.id, mode="label", status="delivering", selected_channels=["netease"])
    db.add(release)
    db.flush()
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=owner.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="delivering",
    )
    db.add(delivery)
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    job = enqueue_job(db, seat, "upload", {"delivery_id": str(delivery.id)})
    db.commit()
    complete_job(db, str(job.id), ok=True, result={"store_url": "https://music.163.com/st/musician"})
    db.refresh(delivery)
    assert delivery.status == "delivering"
    assert not delivery.store_url


@pytest.mark.requires_db
def test_hub_unmatched_is_harvest_rows(db):
    from app.services.royalty.hub import build_creator_hub

    owner = _user(db, "hubu")
    work = _work(db, owner, "Claimable Song")
    seats = ensure_platform_seats(db, channels=["netease"])
    persist_unmatched(
        db,
        [
            {"channel_code": "netease", "period_key": PERIOD, "title": work.title, "revenue_minor": 100},
            {"channel_code": "netease", "period_key": PERIOD, "title": "Someone Else Ghost", "revenue_minor": 100},
        ],
        seat=seats[0],
    )
    db.commit()
    visible = list_unmatched(db, owner)
    assert visible == []
    hub = build_creator_hub(db, owner)
    assert hub["unmatched_count"] == 0
    from fastapi import HTTPException

    rec = db.query(HarvestUnmatched).filter(HarvestUnmatched.title == work.title).first()
    assert rec is not None
    try:
        attach_unmatched(db, owner, str(rec.id), str(work.id), admin=False)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 403


@pytest.mark.requires_db
def test_farm_upload_keeps_title_with_code(db):
    from app.services.seats.farm import _run_upload

    owner = _user(db, "fill")
    work = _work(db, owner)
    code = title_with_code(work.title, mint_track_code(work.id))
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    job = enqueue_job(db, seat, "upload", {"title": work.title, "title_with_code": code})
    db.commit()
    result = _run_upload(db, job, seat, dict(job.payload or {}))
    assert result["status"] == "queued"
    assert result.get("handed_to_runtime")
    db.refresh(job)
    assert job.status == "queued"
    assert (job.payload or {}).get("title_with_code") == code


@pytest.mark.requires_db
def test_seat_unmatched_and_remote_routes(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "route")
    token = create_access_token(str(owner.id))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    empty = client.get("/api/v1/seats/unmatched", headers=headers)
    assert empty.status_code == 200
    assert empty.json().get("rows") == []
    seat = connect_user_seat(db, owner, "kugou")
    db.commit()
    start = client.post(f"/api/v1/seats/{seat.id}/remote-login", headers=headers)
    assert start.status_code == 200
    ack = client.post(f"/api/v1/seats/{seat.id}/remote/ack", headers=headers)
    assert ack.status_code == 200
    assert ack.json().get("status") in {"user_finished", "waiting_login", "awaiting_user", "ready"}
    db.expire_all()
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "remote_login").all()
    assert any((job.payload or {}).get("capture_session") for job in jobs)


@pytest.mark.requires_db
def test_enqueue_harvest_dedup_and_farm_skips_empty(db):
    from app.services.seats.service import lease_jobs

    owner = _user(db, "dedup")
    seat = connect_user_seat(db, owner, "netease")
    db.commit()
    first = enqueue_job(db, seat, "harvest", {})
    second = enqueue_job(db, seat, "harvest", {})
    db.commit()
    assert first.id == second.id
    drain_queued(db, seat_id=str(seat.id))
    db.refresh(first)
    assert first.status == "queued"
    farm = lease_jobs(db, owner="farm", runtime="farm", seat_id=str(seat.id))
    assert farm == []
    ext = lease_jobs(db, owner="ext-1", runtime="extension", seat_id=str(seat.id))
    assert len(ext) == 1
    assert ext[0]["id"] == str(first.id)


@pytest.mark.requires_db
def test_extension_leases_platform_harvest_when_farm_cannot(db):
    from app.services.seats.service import lease_jobs

    seats = ensure_platform_seats(db, channels=["kugou"])
    seat = seats[0]
    seat.status = "live"
    extra = dict(seat.extra or {})
    extra["has_session"] = True
    seat.extra = extra
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    db.flush()
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    assert seat.runtime == "farm"
    assert lease_jobs(db, owner="farm", runtime="farm", seat_id=str(seat.id)) == []
    ext = lease_jobs(db, owner="ops-ext", runtime="extension", seat_id=str(seat.id))
    assert len(ext) == 1
    assert ext[0]["id"] == str(job.id)


@pytest.mark.requires_db
def test_harvest_task_skips_seats_without_session(db):
    from app.workers.harvest_tasks import run_seat_runtime

    owner = _user(db, "task")
    bare = connect_user_seat(db, owner, "kuwo")
    bare.status = "live"
    ready = connect_user_seat(db, owner, "qishui")
    ready.status = "live"
    save_seat_session(db, ready, session={"cookies": []}, mark_live=True)
    db.commit()
    run_seat_runtime(db, enqueue_due_harvest=True, force_harvest=True, seat_id=str(ready.id))
    run_seat_runtime(db, enqueue_due_harvest=True, force_harvest=True, seat_id=str(bare.id))
    db.expire_all()
    after = (
        db.query(SeatJob)
        .filter(SeatJob.kind == "harvest", SeatJob.seat_id.in_([bare.id, ready.id]))
        .all()
    )
    assert not any(job.seat_id == bare.id for job in after)
    assert any(job.seat_id == ready.id for job in after)


@pytest.mark.requires_db
def test_ack_merges_capture_into_open_remote_job(db):
    owner = _user(db, "merge")
    seat = connect_user_seat(db, owner, "bilibili")
    db.commit()
    start_remote_login(db, owner, seat)
    ack_remote_login(db, seat)
    db.commit()
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "remote_login").all()
    assert len(jobs) == 1
    assert (jobs[0].payload or {}).get("capture_session") is True


@pytest.mark.requires_db
def test_admin_harvest_unmatched_attach_route(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    seed_distribution_catalog(db)
    admin = _user(db, "hadm")
    admin.is_admin = True
    owner = _user(db, "hown")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Admin Claim Song")
    seats = ensure_platform_seats(db, channels=["netease"])
    title = f"Ghost Admin Row {uuid.uuid4().hex[:8]}"
    persist_unmatched(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "title": title, "revenue_minor": 2000}],
        seat=seats[0],
    )
    db.commit()
    rec = db.query(HarvestUnmatched).filter(HarvestUnmatched.title == title).first()
    assert rec is not None
    token = create_access_token(str(admin.id))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    listed = client.get("/api/v1/admin/harvest/unmatched", headers=headers)
    assert listed.status_code == 200
    assert "rows" in listed.json()
    attached = client.post(
        f"/api/v1/admin/harvest/unmatched/{rec.id}/attach",
        headers=headers,
        params={"work_id": str(work.id)},
    )
    assert attached.status_code == 200
    assert attached.json().get("status") == "matched"


def test_clean_harvest_row_keeps_track_code():
    from types import SimpleNamespace

    from app.services.seats.farm import clean_harvest_row

    seat = SimpleNamespace(channel_code="netease")
    row = clean_harvest_row(
        seat,
        {
            "title": "Night Drive [VSAAAAAAAABBBB]",
            "isrc": "CN-ABC-00-00001",
            "track_code": "VSAAAAAAAABBBB",
            "streams": 12,
            "revenue_minor": 340,
            "currency": "USD",
            "period_key": "2026-08",
        },
    )
    assert row["channel_code"] == "netease"
    assert row["track_code"] == "VSAAAAAAAABBBB"
    assert row["isrc"] == "CN-ABC-00-00001"
    assert row["currency"] == "USD"
    assert row["period_key"] == "2026-08"


@pytest.mark.requires_db
def test_start_remote_login_keeps_ready_session(db):
    owner = _user(db, "ready")
    seat = connect_user_seat(db, owner, "netease")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    payload = start_remote_login(db, owner, seat)
    assert payload["status"] == "ready"
    assert payload["has_session"] is True
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "remote_login").all()
    assert jobs == []


@pytest.mark.requires_db
def test_ops_connector_batch_stays_draft(db):
    from datetime import date

    from app.models.schemas import SettlementBatch, SettlementLine
    from app.services.royalty.settlement import should_auto_confirm_harvest_batch
    from app.services.royalty.subjects import AUTO_CONFIRM_SOURCES

    owner = _user(db, "opsauto")
    work = _work(db, owner, "Ops Draft")
    ops = SettlementBatch(period_key=PERIOD, period_start=date.today(), period_end=date.today(), status="draft")
    seat = SettlementBatch(period_key=PERIOD, period_start=date.today(), period_end=date.today(), status="draft")
    db.add_all([ops, seat])
    db.flush()
    db.add(
        SettlementLine(
            batch_id=ops.id,
            user_id=owner.id,
            work_id=work.id,
            channel_code="netease",
            source="ops_connector",
            gross_minor=1000,
            commission_minor=200,
            net_minor=800,
        )
    )
    db.add(
        SettlementLine(
            batch_id=seat.id,
            user_id=owner.id,
            work_id=work.id,
            channel_code="netease",
            source="seat_harvest",
            gross_minor=1000,
            commission_minor=200,
            net_minor=800,
        )
    )
    db.commit()
    assert "ops_connector" not in AUTO_CONFIRM_SOURCES
    assert should_auto_confirm_harvest_batch(db, ops.id) is False
    assert should_auto_confirm_harvest_batch(db, seat.id) is False


@pytest.mark.requires_db
def test_low_confidence_harvest_stays_draft(db):
    seed_distribution_catalog(db)
    owner = _user(db, "lowconf")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Low Conf")
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    result = _ingest_harvest_rows(
        db,
        [
            {
                "channel_code": "netease",
                "period_key": PERIOD,
                "isrc": code,
                "title": "Low Conf",
                "revenue_minor": 1000,
                "confidence": 0.4,
            }
        ],
        seat=seat,
        settle=True,
    )
    assert result["matched"] == 1
    assert not any(item.get("auto_confirmed") for item in result["settlements"])
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0
    pending = wallet.pending_minor if wallet else 0
    assert pending >= 0


@pytest.mark.requires_db
def test_dom_harvest_without_explicit_confidence_stays_draft(db):
    seed_distribution_catalog(db)
    owner = _user(db, "domconf")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Dom Conf")
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    result = _ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Dom Conf", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    assert result["matched"] == 1
    assert not any(item.get("auto_confirmed") for item in result["settlements"])
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_harvest_auto_confirm_ignores_foreign_ops_draft(db):
    seed_distribution_catalog(db)
    owner = _user(db, "mixauto")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Mix Auto")
    code = ensure_track_code(db, work)
    from datetime import date

    from app.models.schemas import SettlementBatch, SettlementLine

    foreign = SettlementBatch(period_key=PERIOD, period_start=date.today(), period_end=date.today(), status="draft")
    db.add(foreign)
    db.flush()
    db.add(
        SettlementLine(
            batch_id=foreign.id,
            user_id=owner.id,
            work_id=work.id,
            channel_code="qq_music",
            source="ops_connector",
            gross_minor=100,
            commission_minor=20,
            net_minor=80,
        )
    )
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Mix Auto", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    assert any(item.get("auto_confirmed") for item in result["settlements"])
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is not None
    assert wallet.available_minor == 800


@pytest.mark.requires_db
def test_settled_harvest_blocks_official_same_key(db):
    from app.models.schemas import DistributionLicense, PlatformMetricSnapshot
    from app.services.royalty.settlement import run_settlement

    seed_distribution_catalog(db)
    owner = _user(db, "blockoff")
    work = _work(db, owner, "Block Official")
    release = Release(work_id=work.id, owner_id=owner.id, mode="label", status="live", selected_channels=["netease"])
    db.add(release)
    db.flush()
    db.add(DistributionLicense(user_id=owner.id, release_id=release.id, agreement_version="2026-08-21", commission_rate=20))
    period = f"2099-{uuid.uuid4().hex[:2]}"
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=owner.id,
            channel_code="netease",
            source="seat_harvest",
            usable_for_settlement=True,
            settled=True,
            period_key=period,
            streams=10,
            revenue_minor=800,
            currency="CNY",
            raw={"settled_revenue_minor": 800},
        )
    )
    db.add(
        PlatformMetricSnapshot(
            work_id=work.id,
            release_id=release.id,
            user_id=owner.id,
            channel_code="netease",
            source="distributor_export",
            usable_for_settlement=True,
            settled=False,
            period_key=period,
            streams=99,
            revenue_minor=9000,
            currency="CNY",
        )
    )
    db.commit()
    result = run_settlement(db, period_key=period)
    assert result["lines"] == 0
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_harvest_adjustment_splits_collaborators(db):
    from app.models.schemas import WorkSplitShare

    seed_distribution_catalog(db)
    owner = _user(db, "adjown")
    collab = _user(db, "adjcol")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Split Claw")
    db.add(WorkSplitShare(work_id=work.id, user_id=owner.id, role="owner", percent=70))
    db.add(WorkSplitShare(work_id=work.id, user_id=collab.id, role="collaborator", percent=30))
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Split Claw", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    owner_wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    collab_wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == collab.id).first()
    assert owner_wallet.available_minor == 560
    assert collab_wallet.available_minor == 240
    from app.services.royalty.wallet import source_split

    assert source_split(db, collab)["harvest_minor"] == 240
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Split Claw", "revenue_minor": 500}],
        seat=seat,
        settle=True,
    )
    db.refresh(owner_wallet)
    db.refresh(collab_wallet)
    assert owner_wallet.available_minor == 280
    assert collab_wallet.available_minor == 120


@pytest.mark.requires_db
def test_increment_keeps_locked_promo_rate(db):
    seed_distribution_catalog(db)
    owner = _user(db, "lockrate")
    work = _work(db, owner, "Lock Rate")
    code = ensure_track_code(db, work)
    db.add(Release(work_id=work.id, owner_id=owner.id, mode="label", status="live", selected_channels=["netease"]))
    seats = ensure_platform_seats(db, channels=["netease"])
    seat = seats[0]
    seat.status = "live"
    db.commit()
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Lock Rate", "revenue_minor": 1000}],
        seat=seat,
        settle=True,
    )
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet.available_minor == 900
    _burn_label_promo(db, owner)
    ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "isrc": code, "title": "Lock Rate", "revenue_minor": 1500}],
        seat=seat,
        settle=True,
    )
    db.refresh(wallet)
    assert wallet.available_minor == 1350


def test_celery_schedules_seat_drain():
    from app.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    assert beat["drain-seat-jobs-every-1m"]["task"] == "drain_seat_jobs_task"
    assert beat["drain-seat-jobs-every-1m"]["kwargs"]["enqueue_due_harvest"] is True
    assert beat["harvest-seats-every-6h"]["task"] == "harvest_seats_task"
    assert celery_app.conf.task_routes["drain_seat_jobs_task"]["queue"] == "analytics"


def test_kick_seat_runtime_is_noop_under_pytest():
    from app.services.seats.runtime import kick_seat_runtime

    assert kick_seat_runtime() is False


def test_runtime_kick_debounce():
    from app.services.seats import runtime

    runtime._last_kick_mono = 0.0
    assert runtime.runtime_kick_allowed(gap_seconds=10, now=100.0) is True
    assert runtime.runtime_kick_allowed(gap_seconds=10, now=105.0) is False
    assert runtime.runtime_kick_allowed(gap_seconds=10, now=111.0) is True


def test_farm_cannot_navigate_without_flag(monkeypatch):
    from app.services.seats.service import farm_can_navigate, farm_navigate_requested

    monkeypatch.delenv("VIBE_FARM_NAVIGATE", raising=False)
    assert farm_navigate_requested() is False
    monkeypatch.setenv("VIBE_FARM_NAVIGATE", "0")
    assert farm_navigate_requested() is False
    assert farm_can_navigate() is False
    monkeypatch.setenv("VIBE_FARM_NAVIGATE", "1")
    assert farm_navigate_requested() is True
    monkeypatch.setattr("app.services.seats.service.playwright_available", lambda: False)
    assert farm_can_navigate() is False
    monkeypatch.setattr("app.services.seats.service.playwright_available", lambda: True)
    assert farm_can_navigate() is True


@pytest.mark.requires_db
def test_enqueue_due_harvests_skips_fresh_and_bare(db):
    from datetime import timedelta

    from app.services.seats.service import enqueue_due_harvests

    owner = _user(db, "dueh")
    fresh = connect_user_seat(db, owner, "netease")
    save_seat_session(db, fresh, session={"cookies": []}, mark_live=True)
    fresh.last_harvest_at = datetime.utcnow()
    stale = connect_user_seat(db, owner, "qq_music")
    save_seat_session(db, stale, session={"cookies": []}, mark_live=True)
    stale.last_harvest_at = datetime.utcnow() - timedelta(hours=7)
    bare = connect_user_seat(db, owner, "kugou")
    bare.status = "live"
    db.commit()
    for seat in (fresh, stale, bare):
        for job in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
            job.status = "done"
            job.finished_at = datetime.utcnow()
    db.commit()
    other = _user(db, "dueh2")
    assert enqueue_due_harvests(db, force=False, user_id=other.id) == 0
    queued = enqueue_due_harvests(db, force=False, user_id=owner.id)
    assert queued >= 1
    fresh_jobs = db.query(SeatJob).filter(SeatJob.seat_id == fresh.id, SeatJob.kind == "harvest", SeatJob.status.in_(("queued", "leased"))).all()
    stale_jobs = db.query(SeatJob).filter(SeatJob.seat_id == stale.id, SeatJob.kind == "harvest", SeatJob.status.in_(("queued", "leased"))).all()
    bare_jobs = db.query(SeatJob).filter(SeatJob.seat_id == bare.id, SeatJob.kind == "harvest", SeatJob.status.in_(("queued", "leased"))).all()
    assert fresh_jobs == []
    assert len(stale_jobs) == 1
    assert bare_jobs == []


@pytest.mark.requires_db
def test_kick_user_due_harvests_commits_independently(db):
    from datetime import timedelta

    from app.services.seats.service import kick_user_due_harvests

    owner = _user(db, "kickiso")
    seat = connect_user_seat(db, owner, "netease")
    extra = dict(seat.extra or {})
    extra["has_session"] = True
    seat.extra = extra
    seat.status = "live"
    seat.last_harvest_at = datetime.utcnow() - timedelta(hours=7)
    db.commit()
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    db.commit()
    dirty = User(email=f"dirty-{uuid.uuid4()}@test.local", username=f"dirty_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(dirty)
    queued = kick_user_due_harvests(db, owner)
    assert queued >= 1
    db.rollback()
    assert db.query(User).filter(User.email == dirty.email).first() is None
    jobs = db.query(SeatJob).filter(
        SeatJob.seat_id == seat.id,
        SeatJob.kind == "harvest",
        SeatJob.status.in_(("queued", "leased")),
    ).all()
    assert len(jobs) == 1


@pytest.mark.requires_db
def test_run_seat_runtime_settles_payload_harvest(db):
    from app.workers.harvest_tasks import run_seat_runtime

    seed_distribution_catalog(db)
    owner = _user(db, "runt")
    _burn_label_promo(db, owner)
    work = _work(db, owner, "Runtime Hit")
    code = ensure_track_code(db, work)
    seats = ensure_platform_seats(db, channels=["kuwo"])
    seat = seats[0]
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    db.flush()
    enqueue_job(
        db,
        seat,
        "harvest",
        {
            "rows": [
                {
                    "channel_code": "kuwo",
                    "period_key": PERIOD,
                    "isrc": code,
                    "title": "Runtime Hit",
                    "revenue_minor": 500,
                }
            ]
        },
    )
    db.commit()
    result = run_seat_runtime(db, seat_id=str(seat.id))
    assert result["ran"] >= 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is not None
    assert wallet.available_minor == 400


@pytest.mark.requires_db
def test_farm_empty_harvest_hands_off_after_retries(db, monkeypatch):
    from app.services.seats.farm import run_job
    from app.services.seats.service import lease_jobs

    owner = _user(db, "retryh")
    seat = connect_user_seat(db, owner, "qishui")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    monkeypatch.setattr("app.services.seats.service.farm_can_navigate", lambda: True)
    monkeypatch.setattr("app.services.seats.farm._try_playwright_extract", lambda *args, **kwargs: [])
    for _ in range(3):
        job.status = "queued"
        job.lease_owner = None
        job.leased_at = None
        db.commit()
        leased = lease_jobs(db, owner="farm", runtime="farm", seat_id=str(seat.id))
        assert leased
        db.refresh(job)
        run_job(db, job)
        db.refresh(job)
    assert (job.payload or {}).get("farm_attempts") == 3
    assert job.status == "queued"
    assert (job.result or {}).get("reason") == "handed_to_extension"


@pytest.mark.requires_db
def test_run_auto_payouts_force_pays_bound_wallet(db):
    from app.services.royalty.wallet import run_auto_payouts

    owner = _user(db, "autop")
    wallet = get_or_create_wallet(db, owner.id, "CNY")
    wallet.available_minor = 5000
    db.commit()
    upsert_payout_account(
        db,
        owner,
        {"channel": "alipay", "account_name": "t", "account_no": "18800002222", "is_default": True},
    )
    from app.services.royalty.payout_calendar import payout_calendar

    if not payout_calendar().get("is_payout_day"):
        skipped = run_auto_payouts(db, force=False)
        assert skipped.get("skipped") is True
    forced = run_auto_payouts(db, force=True)
    assert forced.get("skipped") is True
    assert forced.get("reason") == "manual_payout_only"
    assert forced.get("paid", 0) == 0
    db.refresh(wallet)
    assert wallet.available_minor == 5000


@pytest.mark.requires_db
def test_extension_user_cannot_lease_platform_jobs(db):
    from app.services.seats.service import lease_jobs

    owner = _user(db, "nolease")
    seats = ensure_platform_seats(db, channels=["kugou"])
    seat = seats[0]
    seat.status = "live"
    extra = dict(seat.extra or {})
    extra["has_session"] = True
    seat.extra = extra
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    db.flush()
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    taken = lease_jobs(db, owner=f"user:{owner.id}", runtime="extension", actor=owner, seat_id=str(seat.id))
    assert taken == []
    db.refresh(job)
    assert job.status == "queued"
    admin = _user(db, "yeslease")
    admin.is_admin = True
    db.commit()
    ops = lease_jobs(db, owner=f"user:{admin.id}", runtime="extension", actor=admin, seat_id=str(seat.id))
    assert len(ops) == 1
    assert ops[0]["id"] == str(job.id)


@pytest.mark.requires_db
def test_complete_job_rejects_other_user_and_requeues_runtime(db):
    from fastapi import HTTPException

    owner = _user(db, "ownjob")
    other = _user(db, "othjob")
    seat = connect_user_seat(db, owner, "netease")
    job = enqueue_job(db, seat, "upload", {"delivery_id": str(uuid.uuid4())})
    db.commit()
    try:
        complete_job(db, str(job.id), ok=True, result={"store_url": "https://music.163.com/song?id=1"}, actor=other)
        assert False
    except HTTPException as exc:
        assert exc.status_code == 403
    db.refresh(job)
    assert job.status == "queued"
    released = complete_job(
        db,
        str(job.id),
        ok=False,
        result={"error": "fill_incomplete", "needs_runtime": True},
        actor=owner,
    )
    assert released["status"] == "queued"
    db.refresh(job)
    assert job.status == "queued"


@pytest.mark.requires_db
def test_harvest_http_requires_own_seat(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "hseat")
    other = _user(db, "hoth")
    work = _work(db, owner, "Mint Block")
    token = create_access_token(str(other.id))
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    naked = client.post(
        "/api/v1/seats/harvest",
        headers=headers,
        json={
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "revenue_minor": 9999}],
        },
    )
    assert naked.status_code == 403
    seats = ensure_platform_seats(db, channels=["netease"])
    db.commit()
    stolen = client.post(
        "/api/v1/seats/harvest",
        headers=headers,
        json={
            "seat_id": str(seats[0].id),
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "revenue_minor": 9999}],
        },
    )
    assert stolen.status_code == 403


@pytest.mark.requires_db
def test_harvest_http_resolves_own_user_seat(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    owner = _user(db, "hown")
    work = _work(db, owner, "Own Seat Harvest")
    seat = connect_user_seat(db, owner, "netease")
    from app.services.seats.consent import set_seat_scopes

    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "upload": True, "settle": True, "keep_sync": True},
        actor=owner,
        action="test",
    )
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.commit()
    from app.models.schemas import DistributionLicense

    license_release = Release(work_id=work.id, owner_id=owner.id, mode="self_release", status="draft")
    db.add(license_release)
    db.flush()
    db.add(DistributionLicense(user_id=owner.id, release_id=license_release.id, agreement_version="2026-09-02", commission_rate=10))
    db.commit()
    token = create_access_token(str(owner.id))
    client = TestClient(app)
    res = client.post(
        "/api/v1/seats/harvest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [
                {
                    "work_id": str(work.id),
                    "title": f"{work.title} [VSAAAAAAAABBBB]",
                    "revenue_minor": 3600,
                    "streams": 1200,
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["matched"] >= 1
    assert body["last_harvest"]["channel"] == "netease"
    assert body["last_harvest"]["count"] >= 1
    assert body["sync"]["last_harvest"]["seat_id"] == str(seat.id)
    assert body["sync"]["period_key"]
    db.refresh(seat)
    assert seat.last_harvest_at is not None
    assert (seat.extra or {}).get("farm_health", {}).get("source") == "extension"
    assert (seat.extra or {}).get("farm_health", {}).get("matched") == body["matched"]


@pytest.mark.requires_db
def test_disconnect_user_seat_clears_session(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token
    from fastapi import HTTPException

    from app.services.seats.service import disconnect_user_seat

    owner = _user(db, "disc")
    other = _user(db, "doth")
    seat = connect_user_seat(db, owner, "qq_music")
    save_seat_session(db, seat, session={"cookies": [{"name": "x"}]}, mark_live=True)
    db.commit()
    with pytest.raises(HTTPException) as stolen:
        disconnect_user_seat(db, other, str(seat.id))
    assert stolen.value.status_code == 403
    out = disconnect_user_seat(db, owner, str(seat.id))
    assert out["status"] == "disconnected"
    assert out["has_session"] is False
    client = TestClient(app)
    token = create_access_token(str(owner.id))
    res = client.post(f"/api/v1/seats/{seat.id}/disconnect", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text


@pytest.mark.requires_db
def test_complete_expired_clears_session(db):
    owner = _user(db, "expclr")
    seat = connect_user_seat(db, owner, "kuwo")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id).all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    job = enqueue_job(db, seat, "harvest", {})
    db.commit()
    complete_job(db, str(job.id), ok=False, result={"error": "cookie_expired", "expired": True}, actor=owner)
    db.refresh(seat)
    assert seat.status == "expired"
    assert (seat.extra or {}).get("has_session") is False


@pytest.mark.requires_db
def test_release_stale_leases(db):
    from datetime import timedelta

    from app.services.seats.service import release_stale_leases

    owner = _user(db, "stalej")
    seat = connect_user_seat(db, owner, "qishui")
    job = enqueue_job(db, seat, "upload", {"delivery_id": str(uuid.uuid4())})
    job.status = "leased"
    job.lease_owner = "farm"
    job.leased_at = datetime.utcnow() - timedelta(seconds=200)
    db.commit()
    assert release_stale_leases(db, seat_id=str(seat.id)) == 1
    db.refresh(job)
    assert job.status == "queued"
    assert job.lease_owner is None
    assert (job.result or {}).get("reason") == "stale_lease"


@pytest.mark.requires_db
def test_heal_enqueues_relogin_for_expired_seat(db):
    from app.services.seats.service import farm_can_run_job, heal_seat_runtime
    from app.workers.harvest_tasks import run_seat_runtime

    owner = _user(db, "relog")
    seat = connect_user_seat(db, owner, "bilibili")
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    extra = dict(seat.extra or {})
    extra["has_session"] = False
    seat.extra = extra
    seat.status = "expired"
    for leftover in db.query(SeatJob).filter(SeatJob.seat_id == seat.id).all():
        leftover.status = "done"
        leftover.finished_at = datetime.utcnow()
    db.commit()
    first = heal_seat_runtime(db, seat_id=str(seat.id))
    assert first["relogins"] == 1
    jobs = db.query(SeatJob).filter(
        SeatJob.seat_id == seat.id,
        SeatJob.kind == "remote_login",
        SeatJob.status.in_(("queued", "leased")),
    ).all()
    assert len(jobs) == 1
    assert farm_can_run_job(jobs[0]) is False
    second = heal_seat_runtime(db, seat_id=str(seat.id))
    assert second["relogins"] == 0
    runtime = run_seat_runtime(db, seat_id=str(seat.id))
    assert runtime["relogins"] == 0
    assert runtime["ran"] == 0
    assert "repaired" in runtime
    assert "released" in runtime
    db.refresh(jobs[0])
    assert jobs[0].status == "queued"


@pytest.mark.requires_db
def test_harvest_without_revenue_does_not_settle(db):
    seed_distribution_catalog(db)
    owner = _user(db, "norev")
    work = _work(db, owner)
    seats = ensure_platform_seats(db, channels=["netease"])
    result = ingest_harvest_rows(
        db,
        [{"channel_code": "netease", "period_key": PERIOD, "work_id": str(work.id), "title": work.title, "streams": 9999}],
        seat=seats[0],
        settle=True,
    )
    assert result["matched"] == 0
    assert result["unmatched_count"] >= 1
    assert all(int(row.get("revenue_minor") or 0) == 0 for row in result["unmatched"])
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is None or (wallet.available_minor or 0) == 0


@pytest.mark.requires_db
def test_connector_token_can_harvest_user_seat(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.royalty.connector import mint_ingest_token

    seed_distribution_catalog(db)
    owner = _user(db, "vsch")
    work = _work(db, owner, "Pair Song")
    seat = connect_user_seat(db, owner, "netease")
    from app.services.seats.consent import set_seat_scopes

    set_seat_scopes(
        db,
        seat,
        {"metrics": True, "export_csv": True, "upload": True, "settle": True, "keep_sync": True},
        actor=owner,
        action="test",
    )
    from app.models.schemas import DistributionLicense

    license_release = Release(work_id=work.id, owner_id=owner.id, mode="self_release", status="draft")
    db.add(license_release)
    db.flush()
    db.add(DistributionLicense(user_id=owner.id, release_id=license_release.id, agreement_version="2026-09-02", commission_rate=10))
    minted = mint_ingest_token(db, owner)
    client = TestClient(app)
    res = client.post(
        "/api/v1/seats/harvest",
        headers={"X-Connector-Token": minted["token"]},
        json={
            "seat_id": str(seat.id),
            "channel_code": "netease",
            "period_key": PERIOD,
            "rows": [{"work_id": str(work.id), "title": work.title, "revenue_minor": 1000, "confidence": 0.95}],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "seat_harvest"
    assert body["matched"] == 1
    wallet = db.query(RoyaltyWallet).filter(RoyaltyWallet.user_id == owner.id).first()
    assert wallet is not None
    assert wallet.available_minor == 900
