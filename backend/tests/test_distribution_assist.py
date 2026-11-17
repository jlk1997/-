import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.schemas import DistributionDelivery, Notification, Release, ReleaseMetadata, User, Work
from app.services.distribution.adapters import AdapterResult, DistroKidAdapter
from app.services.distribution.assist import (
    complete_assist_job,
    expire_stale_session_jobs,
    route_delivery,
)
from app.services.distribution.catalog import (
    channel_capability,
    channel_delivery_mode,
    connected_channel_codes,
    default_volume_channels,
    list_aggregator_partners,
    pick_configured_aggregator,
)
from app.services.distribution.pipeline import retry_configured_partner_holds


def test_assist_sort_prefers_priority_then_volume():
    from app.services.distribution.assist import _assist_sort_key

    high = SimpleNamespace(channel_code="bandcamp", attempt_meta={"priority_score": 80})
    netease = SimpleNamespace(channel_code="netease", attempt_meta={})
    spotify = SimpleNamespace(channel_code="spotify", attempt_meta={})
    assert _assist_sort_key(high) < _assist_sort_key(netease)
    assert _assist_sort_key(netease) < _assist_sort_key(spotify)


def test_full_pack_and_session_portals():
    from app.services.distribution.catalog import DEFAULT_UPLOAD_CHANNELS

    pack = default_volume_channels()
    if not any(pick_configured_aggregator(code) for code in ("netease", "spotify", "apple_music")):
        assert pack == list(DEFAULT_UPLOAD_CHANNELS)
        assert "spotify" not in pack
    assert "douyin_musician" not in pack or pick_configured_aggregator("douyin_musician")
    assert channel_delivery_mode("wechat_channels") == "session_assist"
    assert channel_delivery_mode("spotify") == "aggregator"
    partners = {row["code"] for row in list_aggregator_partners()}
    assert {"distrokid", "tunecore", "routenote", "cn_label"} <= partners
    connected = default_volume_channels(connected=["wechat_channels", "spotify"])
    assert "wechat_channels" in connected
    assert "spotify" in connected


def test_submit_without_channels_uses_launch_handoff():
    from pathlib import Path

    from app.services.distribution.handoff import AUTH_HOLD

    text = Path(__file__).resolve().parents[1].joinpath("app", "services", "distribution", "service.py").read_text(
        encoding="utf-8"
    )
    assert "DEFAULT_UPLOAD_CHANNELS" in text
    assert "mark_auth_hold(release)" not in text
    assert AUTH_HOLD == "NEEDS_AUTH"


def test_starter_stores_suggested_not_optional_clips():
    from app.services.distribution.catalog import STARTER_VOLUME_CHANNELS, is_volume_channel
    from app.services.seats.connections import _suggest_install

    assert STARTER_VOLUME_CHANNELS == ("netease", "qq_music", "spotify")
    assert _suggest_install(has_self_release=False, channel_code="netease") is True
    assert _suggest_install(has_self_release=False, channel_code="wechat_channels") is True
    assert _suggest_install(has_self_release=True, channel_code="douyin_musician") is False
    assert is_volume_channel("netease") is True
    assert is_volume_channel("wechat_channels") is False


def test_channel_capability_three_states():
    assert channel_capability("wechat_channels") == "needs_link"
    assert channel_capability("spotify") in {"auto", "wait_connector"}
    assert channel_capability("spotify", connected=["spotify"]) == "auto"
    assert channel_capability("wechat_channels", connected=["wechat_channels"]) == "auto"
    if not pick_configured_aggregator("netease"):
        assert channel_capability("netease") == "wait_connector"


def test_connected_channel_codes_ignores_platform(monkeypatch):
    monkeypatch.setattr(
        "app.services.seats.connections.build_connections",
        lambda db, user, seats: [
            {"channel_code": "netease", "status": "platform"},
            {"channel_code": "spotify", "status": "settle"},
            {"channel_code": "wechat_channels", "status": "disconnected"},
        ],
    )
    monkeypatch.setattr("app.services.seats.service.list_seats", lambda db, user: [])
    assert connected_channel_codes(object(), object()) == ["spotify"]
    assert "wechat_channels" not in default_volume_channels(
        connected=connected_channel_codes(object(), object())
    )


def test_route_delivery_uses_configured_partner(monkeypatch):
    delivery = SimpleNamespace(distributor_code="distrokid", channel_code="spotify")
    monkeypatch.setattr(
        "app.services.distribution.adapters.DistroKidAdapter.configured",
        lambda self: True,
    )
    assert route_delivery(delivery) == "partner"
    monkeypatch.setattr(
        "app.services.distribution.adapters.DistroKidAdapter.configured",
        lambda self: False,
    )
    assert route_delivery(delivery) == "metrics"


def test_pick_configured_aggregator_prefers_ready_partner(monkeypatch):
    monkeypatch.setattr("app.services.distribution.adapters.DistroKidAdapter.configured", lambda self: False)
    monkeypatch.setattr("app.services.distribution.adapters.TuneCoreAdapter.configured", lambda self: True)
    monkeypatch.setattr("app.services.distribution.adapters.RouteNoteAdapter.configured", lambda self: False)
    assert pick_configured_aggregator("spotify") == "tunecore"
    assert pick_configured_aggregator("wechat_channels") is None


@pytest.mark.requires_db
def test_unconfigured_submit_parks_session_and_completes_live(db):
    user = User(email=f"assist-{uuid.uuid4()}@test.local", username=f"as_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="queued", selected_channels=["netease"])
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="submitting",
    )
    db.add(delivery)
    db.commit()
    from app.services.distribution.pipeline import process_one_delivery

    process_one_delivery(db, delivery, force=True, commit=True)
    db.refresh(delivery)
    from app.services.distribution.assist import LEASE_WAIT_NOTE

    assert delivery.status == "session_wait"
    assert delivery.last_error == LEASE_WAIT_NOTE
    assert (delivery.attempt_meta or {}).get("assist_job", {}).get("channel_code") == "netease"
    saved = complete_assist_job(db, user, str(delivery.id), store_url="https://music.163.com/song?id=88")
    assert saved["status"] == "live"
    assert saved["store_url"] == "https://music.163.com/song?id=88"
    assert saved["external_id"] == "88"
    from fastapi import HTTPException

    try:
        complete_assist_job(db, user, str(delivery.id), store_url="https://music.163.com/st/musician")
        assert False
    except HTTPException as exc:
        assert exc.status_code == 400


@pytest.mark.requires_db
def test_ops_queue_without_meta_lists_as_assist_job(db):
    from app.services.distribution.assist import list_assist_jobs

    user = User(email=f"opsjob-{uuid.uuid4()}@test.local", username=f"oj_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering")
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="spotify",
        distributor_code="distrokid",
        status="ops_queue",
    )
    db.add(delivery)
    db.commit()
    jobs = list_assist_jobs(db, user)
    assert jobs == []
    from app.services.seats.consent import set_seat_scopes
    from app.services.seats.service import connect_user_seat

    seat = connect_user_seat(db, user, "spotify")
    set_seat_scopes(db, seat, {"metrics": True, "export_csv": True, "upload": True}, actor=user, action="test")
    db.commit()
    jobs = list_assist_jobs(db, user)
    assert any(job["delivery_id"] == str(delivery.id) for job in jobs)
    assert any(job.get("upload_url") for job in jobs if job["delivery_id"] == str(delivery.id))


@pytest.mark.requires_db
def test_expire_session_moves_same_kit_to_ops(db):
    user = User(email=f"exp-{uuid.uuid4()}@test.local", username=f"ex_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering")
    db.add(release)
    db.commit()
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="spotify",
        distributor_code="distrokid",
        status="session_running",
        last_attempt_at=datetime.utcnow() - timedelta(hours=3),
        attempt_meta={"assist_job": {"channel_code": "spotify"}},
    )
    db.add(delivery)
    db.commit()
    assert expire_stale_session_jobs(db) >= 1
    db.refresh(delivery)
    assert delivery.status == "ops_queue"
    assert (delivery.attempt_meta or {}).get("assist_job", {}).get("channel_code") == "spotify"
    note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "distribution_status")
        .first()
    )
    assert note is not None
    assert "不是已上架" in str((note.payload or {}).get("message") or "")


@pytest.mark.requires_db
def test_partner_retry_leaves_session_when_key_arrives(db):
    from app.services.distribution import adapters

    class Ready(DistroKidAdapter):
        def configured(self) -> bool:
            return True

        def submit(self, payload: dict) -> AdapterResult:
            return AdapterResult(ok=True, status="in_review", external_id="dk_ready")

    adapters.ADAPTERS["distrokid"] = Ready()
    try:
        user = User(email=f"retry-{uuid.uuid4()}@test.local", username=f"rt_{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        db.commit()
        work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
        db.add(work)
        db.commit()
        release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering")
        db.add(release)
        db.commit()
        db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
        delivery = DistributionDelivery(
            release_id=release.id,
            work_id=work.id,
            owner_id=user.id,
            channel_code="spotify",
            distributor_code="distrokid",
            status="session_wait",
        )
        db.add(delivery)
        db.commit()
        assert retry_configured_partner_holds(db) >= 1
        db.refresh(delivery)
        assert delivery.status == "in_review"
        assert delivery.external_id == "dk_ready"
    finally:
        adapters.ADAPTERS["distrokid"] = DistroKidAdapter()


def _park_fixture(db, *, prefix: str, channel="netease", mode="label"):
    user = User(email=f"{prefix}-{uuid.uuid4()}@test.local", username=f"{prefix}_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode=mode, status="queued", selected_channels=[channel])
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Night Drive", artist_name="Tester"))
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code=channel,
        distributor_code="cn_label",
        status="submitting",
    )
    db.add(delivery)
    db.commit()
    return user, work, release, delivery


@pytest.mark.requires_db
def test_park_lease_wait_when_platform_seat_ready(db):
    from app.services.distribution.assist import LEASE_WAIT_NOTE, park_for_session
    from app.services.distribution.service import user_delivery_status
    from app.services.seats.service import ensure_platform_seats, save_seat_session

    user, work, release, delivery = _park_fixture(db, prefix="parkseat")
    seats = ensure_platform_seats(db, channels=["netease"], pool_size=1)
    save_seat_session(db, seats[0], session={"cookies": []}, mark_live=True)
    db.commit()
    status = park_for_session(db, delivery, release)
    assert status == "session_wait"
    assert delivery.last_error == LEASE_WAIT_NOTE
    assert user_delivery_status(delivery.status, delivery.last_error) == "assisting"
    assert (delivery.attempt_meta or {}).get("assist_job", {}).get("seat_job_id")


@pytest.mark.requires_db
def test_park_user_seat_without_session_needs_login(db):
    from app.services.distribution.assist import park_for_session
    from app.services.distribution.service import user_delivery_status
    from app.services.seats.service import connect_user_seat

    user, work, release, delivery = _park_fixture(db, prefix="parku", mode="self_release")
    seat = connect_user_seat(db, user, "netease")
    seat.status = "live"
    seat.extra = {"has_session": False}
    db.commit()
    status = park_for_session(db, delivery, release)
    assert status == "session_wait"
    assert delivery.last_error is None
    assert user_delivery_status(delivery.status, delivery.last_error) == "waiting_login"
    assert (delivery.attempt_meta or {}).get("seat_id") == str(seat.id)
    from app.models.schemas import SeatJob

    assert db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "upload").all() == []


def test_seat_ownership_follows_mode_and_clip_channels():
    from app.services.seats.service import seat_ownership_for

    assert seat_ownership_for(mode="label", channel_code="netease") == "platform"
    assert seat_ownership_for(mode="label", channel_code="netease", user_session_ready=True) == "user"
    assert seat_ownership_for(mode="self_release", channel_code="netease") == "user"
    assert seat_ownership_for(mode="label", channel_code="wechat_channels") == "user"


@pytest.mark.requires_db
def test_label_park_uses_handed_user_seat(db):
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.distribution.assist import park_for_session
    from app.services.seats.service import connect_user_seat

    user, work, release, delivery = _park_fixture(db, prefix="parklabu")
    user_seat = connect_user_seat(db, user, "netease")
    user_seat.status = "live"
    user_seat.extra = {"has_session": True}
    db.commit()
    park_for_session(db, delivery, release)
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    bound = db.query(CreatorSeat).filter(CreatorSeat.id == uuid.UUID(str(seat_id))).first() if seat_id else None
    assert bound is not None
    assert bound.ownership == "user"
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == user_seat.id, SeatJob.kind == "upload").all()
    assert jobs


@pytest.mark.requires_db
def test_label_park_uses_platform_without_user_session(db):
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.distribution.assist import LEASE_WAIT_NOTE, park_for_session
    from app.services.seats.service import connect_user_seat, ensure_platform_seats, save_seat_session

    user, work, release, delivery = _park_fixture(db, prefix="parklab")
    user_seat = connect_user_seat(db, user, "netease")
    user_seat.status = "live"
    user_seat.extra = {"has_session": False}
    seats = ensure_platform_seats(db, channels=["netease"], pool_size=1)
    save_seat_session(db, seats[0], session={"cookies": []}, mark_live=True)
    db.commit()
    park_for_session(db, delivery, release)
    assert delivery.last_error == LEASE_WAIT_NOTE
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    bound = db.query(CreatorSeat).filter(CreatorSeat.id == uuid.UUID(str(seat_id))).first() if seat_id else None
    assert bound is not None
    assert bound.ownership == "platform"
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == user_seat.id, SeatJob.kind == "upload").all()
    assert jobs == []


@pytest.mark.requires_db
def test_self_release_park_does_not_use_platform_seat(db):
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.distribution.assist import park_for_session
    from app.services.distribution.service import user_delivery_status
    from app.services.seats.service import ensure_platform_seats

    user, work, release, delivery = _park_fixture(db, prefix="parkself", mode="self_release")
    seats = ensure_platform_seats(db, channels=["netease"], pool_size=1)
    db.commit()
    park_for_session(db, delivery, release)
    assert delivery.last_error is None
    assert user_delivery_status(delivery.status, delivery.last_error) == "waiting_login"
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    assert seat_id
    bound = db.query(CreatorSeat).filter(CreatorSeat.id == uuid.UUID(str(seat_id))).first()
    assert bound is not None
    assert bound.ownership == "user"
    assert bound.user_id == user.id
    jobs = [
        job
        for job in db.query(SeatJob).filter(SeatJob.seat_id == seats[0].id, SeatJob.kind == "upload").all()
        if str((job.payload or {}).get("delivery_id") or "") == str(delivery.id)
    ]
    assert jobs == []
    user_jobs = db.query(SeatJob).filter(SeatJob.seat_id == bound.id, SeatJob.kind == "upload").all()
    assert user_jobs == []


@pytest.mark.requires_db
def test_promote_session_skips_waiting_login(db):
    from app.models.schemas import ConnectorIngestToken
    from app.services.distribution.assist import promote_session_if_online

    user, work, release, delivery = _park_fixture(db, prefix="promolog", mode="self_release")
    delivery.status = "session_wait"
    delivery.last_error = None
    db.add(
        ConnectorIngestToken(
            user_id=user.id,
            token_hash=f"h{uuid.uuid4().hex}",
            last_used_at=datetime.utcnow(),
        )
    )
    db.commit()
    assert promote_session_if_online(db, user) == 0
    db.refresh(delivery)
    assert delivery.status == "session_wait"


@pytest.mark.requires_db
def test_saving_user_session_resumes_waiting_uploads(db):
    from app.services.distribution.assist import LEASE_WAIT_NOTE, park_for_session
    from app.services.seats.service import connect_user_seat, save_seat_session

    user, work, release, delivery = _park_fixture(db, prefix="parkres", mode="self_release")
    seat = connect_user_seat(db, user, "netease")
    db.commit()
    park_for_session(db, delivery, release)
    assert delivery.last_error is None
    save_seat_session(db, seat, session={"cookies": []}, mark_live=True)
    db.refresh(delivery)
    assert delivery.last_error == LEASE_WAIT_NOTE
    assert (delivery.attempt_meta or {}).get("seat_id") == str(seat.id)


@pytest.mark.requires_db
def test_label_clip_park_binds_user_seat(db):
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.distribution.assist import park_for_session
    from app.services.distribution.service import user_delivery_status

    user, work, release, delivery = _park_fixture(db, prefix="parkclip")
    delivery.channel_code = "wechat_channels"
    db.commit()
    park_for_session(db, delivery, release)
    assert user_delivery_status(delivery.status, delivery.last_error) == "waiting_login"
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    bound = db.query(CreatorSeat).filter(CreatorSeat.id == uuid.UUID(str(seat_id))).first()
    assert bound is not None
    assert bound.ownership == "user"
    assert bound.user_id == user.id
    assert bound.channel_code == "wechat_channels"
    assert db.query(SeatJob).filter(SeatJob.seat_id == bound.id, SeatJob.kind == "upload").all() == []


@pytest.mark.requires_db
def test_configured_partner_without_receipt_parks_session(db, monkeypatch):
    from app.services.distribution.adapters import AdapterResult
    from app.services.distribution.pipeline import process_one_delivery
    from app.services.distribution.service import user_delivery_status

    user, work, release, delivery = _park_fixture(db, prefix="adapark", mode="self_release")
    delivery.distributor_code = "distrokid"
    db.commit()
    monkeypatch.setattr("app.services.distribution.catalog.pick_configured_aggregator", lambda code: "distrokid")
    monkeypatch.setattr("app.services.distribution.adapters.DistroKidAdapter.configured", lambda self: True)
    monkeypatch.setattr(
        "app.services.distribution.pipeline.adapter_submit_safe",
        lambda code, payload: AdapterResult(ok=True, status="ops_queue", kit_required=True, message="stub"),
    )
    process_one_delivery(db, delivery, force=True, commit=True)
    db.refresh(delivery)
    assert delivery.status == "session_wait"
    assert user_delivery_status(delivery.status, delivery.last_error) == "waiting_login"


@pytest.mark.requires_db
def test_heal_repairs_orphan_label_upload(db):
    from app.models.schemas import SeatJob
    from app.services.distribution.assist import LEASE_WAIT_NOTE, park_for_session
    from app.services.seats.service import ensure_platform_seats, heal_seat_runtime, save_seat_session

    user, work, release, delivery = _park_fixture(db, prefix="orphlab")
    seats = ensure_platform_seats(db, channels=["netease"], pool_size=1)
    save_seat_session(db, seats[0], session={"cookies": []}, mark_live=True)
    park_for_session(db, delivery, release, kick=False)
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    assert seat_id
    for job in db.query(SeatJob).filter(SeatJob.kind == "upload").all():
        if str((job.payload or {}).get("delivery_id") or "") == str(delivery.id):
            job.status = "failed"
            job.finished_at = datetime.utcnow()
    db.commit()
    healed = heal_seat_runtime(db, seat_id=str(seat_id))
    assert healed["repaired"] >= 1
    db.refresh(delivery)
    assert delivery.last_error == LEASE_WAIT_NOTE
    open_jobs = [
        job
        for job in db.query(SeatJob)
        .filter(SeatJob.kind == "upload", SeatJob.status.in_(("queued", "leased")))
        .all()
        if str((job.payload or {}).get("delivery_id") or "") == str(delivery.id)
    ]
    assert len(open_jobs) == 1


@pytest.mark.requires_db
def test_heal_skips_user_waiting_login(db):
    from app.models.schemas import SeatJob
    from app.services.distribution.assist import park_for_session
    from app.services.seats.service import heal_seat_runtime

    user, work, release, delivery = _park_fixture(db, prefix="skipwl", mode="self_release")
    park_for_session(db, delivery, release, kick=False)
    seat_id = (delivery.attempt_meta or {}).get("seat_id")
    assert seat_id
    healed = heal_seat_runtime(db, seat_id=str(seat_id))
    assert healed["repaired"] == 0
    assert db.query(SeatJob).filter(SeatJob.seat_id == uuid.UUID(str(seat_id)), SeatJob.kind == "upload").all() == []


def _seat_ready_to_copy(db, user, *, settle: bool):
    from app.services.seats.service import connect_user_seat

    seat = connect_user_seat(db, user, "netease")
    extra = dict(seat.extra or {})
    scopes = dict(extra.get("scopes") or {})
    scopes["settle"] = settle
    scopes["keep_sync"] = False
    extra["scopes"] = scopes
    extra["has_session"] = True
    seat.extra = extra
    seat.status = "live"
    seat.last_harvest_at = datetime.utcnow()
    db.commit()
    return seat


@pytest.mark.requires_db
def test_live_receipt_queues_copy_even_when_harvest_is_fresh(db):
    from app.models.schemas import DistributionLicense, SeatJob
    from app.services.seats.service import queue_copy_after_live

    user = User(email=f"copy-{uuid.uuid4()}@test.local", username=f"cp_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Copy Now", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering", selected_channels=["netease"])
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Copy Now", artist_name="Tester"))
    db.add(DistributionLicense(user_id=user.id, release_id=release.id, agreement_version="2026-09-02", commission_rate=10))
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="in_review",
    )
    db.add(delivery)
    db.commit()
    seat = _seat_ready_to_copy(db, user, settle=True)
    saved = complete_assist_job(db, user, str(delivery.id), store_url="https://music.163.com/song?id=88")
    assert saved["status"] == "live"
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest", SeatJob.status.in_(("queued", "leased"))).all()
    assert len(jobs) == 1
    assert (jobs[0].payload or {}).get("reason") == "live_receipt"
    assert queue_copy_after_live(db, delivery) == "harvest"


@pytest.mark.requires_db
def test_live_receipt_without_license_does_not_queue_harvest(db):
    from app.models.schemas import SeatJob

    user = User(email=f"nolic-{uuid.uuid4()}@test.local", username=f"nl_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="No License", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering", selected_channels=["netease"])
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="No License", artist_name="Tester"))
    delivery = DistributionDelivery(
        release_id=release.id,
        work_id=work.id,
        owner_id=user.id,
        channel_code="netease",
        distributor_code="cn_label",
        status="in_review",
    )
    db.add(delivery)
    db.commit()
    seat = _seat_ready_to_copy(db, user, settle=True)
    saved = complete_assist_job(db, user, str(delivery.id), store_url="https://music.163.com/song?id=99")
    assert saved["status"] == "live"
    jobs = db.query(SeatJob).filter(SeatJob.seat_id == seat.id, SeatJob.kind == "harvest").all()
    assert jobs == []


def test_queue_copy_after_live_waits_for_license_not_for_a_fresh_harvest(monkeypatch):
    from app.services.seats.service import queue_copy_after_live

    seat = SimpleNamespace(
        id="s1",
        extra={
            "has_session": True,
            "scopes": {
                "metrics": True,
                "export_csv": True,
                "upload": True,
                "settle": True,
                "keep_sync": False,
                "auto_submit": False,
            },
        },
        ownership="user",
        status="live",
        channel_code="netease",
        user_id="u1",
        last_harvest_at=datetime.utcnow(),
    )
    user = SimpleNamespace(id="u1", is_admin=False)
    delivery = SimpleNamespace(
        id="d1",
        status="live",
        store_url="https://music.163.com/song?id=88",
        external_id="88",
        channel_code="netease",
        owner_id="u1",
    )
    queued: list[tuple[str, dict]] = []

    class Rows:
        def __init__(self, row):
            self.row = row

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self.row

    from app.models.schemas import CreatorSeat, User as UserModel

    def query(model):
        if model is CreatorSeat:
            return Rows(seat)
        if model is UserModel:
            return Rows(user)
        return Rows(None)

    db = SimpleNamespace(query=query)
    monkeypatch.setattr(
        "app.services.seats.service.enqueue_job",
        lambda db, seat, kind, payload: queued.append((kind, payload)) or SimpleNamespace(id="j1"),
    )
    monkeypatch.setattr("app.services.seats.consent.user_has_distribution_license", lambda db, user: False)
    assert queue_copy_after_live(db, delivery) is None
    assert queued == []
    monkeypatch.setattr("app.services.seats.consent.user_has_distribution_license", lambda db, user: True)
    assert queue_copy_after_live(db, delivery) == "harvest"
    assert queued[0][0] == "harvest"
    assert queued[0][1]["reason"] == "live_receipt"
