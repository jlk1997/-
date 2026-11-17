from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.distribution.automation import (
    AUTO_CONFIRM_MIN_CONFIDENCE,
    hydrate_generation_qc,
    priority_score,
    release_hint_for_work,
    should_auto_confirm_batch,
    stamp_release_priority,
)
from app.services.distribution.service import should_autolive_from_ops_receipt
from app.services.media import cut_audio_clip
from app.services.royalty.ingest import _norm_isrc
from app.services.distribution.catalog import channel_sop, clip_windows, default_volume_channels, list_portal_channels
from app.services.distribution.release_ready import infer_qc_artist
from app.services.listen_engagement import is_own_work
from app.services.distribution.partner_events import sign_partner_body, verify_partner_request


def test_volume_pack_is_cn_and_global_one_click():
    from app.services.distribution.catalog import all_channel_codes, optional_assist_channels

    pack = default_volume_channels()
    codes = set(all_channel_codes())
    assert {"netease", "bilibili", "spotify", "apple_music", "wechat_channels", "douyin_musician"} <= codes
    from app.services.distribution.catalog import DEFAULT_UPLOAD_CHANNELS, pick_configured_aggregator

    if not any(pick_configured_aggregator(code) for code in codes):
        assert pack == list(DEFAULT_UPLOAD_CHANNELS)
        assert "spotify" not in pack
    assert "douyin_musician" not in pack or pick_configured_aggregator("douyin_musician")
    optional = optional_assist_channels()
    assert "wechat_channels" in optional
    assert "douyin_musician" in optional


def test_qc_artist_falls_back_to_owner_name():
    assert infer_qc_artist(SimpleNamespace(artist_name="  Meta  "), None, None) == "Meta"
    user = SimpleNamespace(display_name="", username="alice")
    assert infer_qc_artist(SimpleNamespace(artist_name=""), None, user) == "alice"
    assert infer_qc_artist(None, None, SimpleNamespace(display_name="丹", username="x")) == "丹"
    assert infer_qc_artist(None, None, None) == ""


def test_own_work_is_not_other_listener():
    owner = SimpleNamespace(id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    work = SimpleNamespace(owner_id=owner.id)
    assert is_own_work(work, owner.id) is True
    assert is_own_work(work, "ffffffff-1111-2222-3333-444444444444") is False
    assert is_own_work(work, None) is False


def test_clip_windows_around_climax():
    clips = clip_windows(120)
    assert all(clip.get("use") == "short_video" for clip in clips)
    assert [c["length"] for c in clips] == [15, 30, 60]
    mid = next(c for c in clips if c["length"] == 15)
    assert 50 <= mid["start"] <= 70
    assert mid["end"] - mid["start"] == 15
    assert clip_windows(10) == []


def test_portal_channels_are_not_settlement_specs():
    portals = list_portal_channels()
    codes = {item["code"] for item in portals}
    assert {"wechat_channels", "douyin_musician", "soundcloud", "bandcamp", "deezer"} <= codes
    assert all(item["portal_only"] is False for item in portals)
    assert "视频号" in channel_sop("wechat_channels")


def test_priority_score_and_stamp():
    assert priority_score("challenge_winner", 1) == 100
    assert priority_score("challenge_winner", 3) == 80
    assert priority_score("duel_winner", 1) == 70
    work = SimpleNamespace(post_process_status={})
    first = stamp_release_priority(work, reason="duel_winner", rank=1, label="duel")
    assert first["score"] == 70
    second = stamp_release_priority(work, reason="challenge_winner", rank=1, label="win")
    assert second["score"] == 100
    kept = stamp_release_priority(work, reason="duel_winner", rank=1)
    assert kept["score"] == 100


def test_hydrate_generation_qc_from_post_process():
    work = SimpleNamespace(
        post_process_status={"release_qc": True},
        audio_url="http://x",
        storage_key=None,
        title="Song",
        release_status="draft",
    )
    release = SimpleNamespace(qc_result={}, status="draft")
    assert hydrate_generation_qc(release, work) is True
    assert release.qc_result["passed"] is True
    assert release.status == "qc"
    assert work.release_status == "qc_ready"
    assert hydrate_generation_qc(release, work) is False


def test_release_hint_priority_beats_listen():
    work = SimpleNamespace(
        post_process_status={"release_priority": {"reason": "challenge_winner", "score": 100, "rank": 1}},
        release_status="qc_ready",
        moods=["calm"],
        genres=["lofi"],
        cover_url="http://x",
        arousal=0.2,
        valence=0.4,
        duration=90,
        audio_url="http://x",
    )
    hint = release_hint_for_work(work=work, listen_completes=20)
    assert hint["id"] == "priority"


def test_should_auto_confirm_batch_requires_isrc_and_confidence():
    batch = SimpleNamespace(source="ops_connector", unmatched_count=0)
    good = SimpleNamespace(status="matched", work_id="w", isrc="USXXX0000001", confidence=0.95)
    assert should_auto_confirm_batch(batch, [good]) is True
    weak = SimpleNamespace(status="matched", work_id="w", isrc="USXXX0000001", confidence=AUTO_CONFIRM_MIN_CONFIDENCE - 0.2)
    assert should_auto_confirm_batch(batch, [weak]) is False
    user_batch = SimpleNamespace(source="user_connector", unmatched_count=0)
    assert should_auto_confirm_batch(user_batch, [good]) is False


def test_partner_hmac_roundtrip(monkeypatch):
    from app.services.distribution import partner_events as events

    monkeypatch.setattr(events.settings, "partner_webhook_secret", "s3cret", raising=False)
    monkeypatch.setattr(events.settings, "debug", False, raising=False)
    monkeypatch.setattr(events.settings, "partner_stub_enabled", False, raising=False)
    monkeypatch.setattr(events.settings, "distrokid_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "tunecore_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "routenote_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "cn_label_api_key", "", raising=False)
    body = b'{"status":"live","delivery_id":"x"}'
    sig = sign_partner_body(body, "s3cret")
    assert verify_partner_request(None, f"sha256={sig}", body) == "hmac"
    with pytest.raises(HTTPException) as exc:
        verify_partner_request(None, "sha256=deadbeef", body)
    assert exc.value.status_code == 401


def test_partner_bearer_accepts_configured_key(monkeypatch):
    from app.services.distribution import partner_events as events

    monkeypatch.setattr(events.settings, "partner_webhook_secret", "", raising=False)
    monkeypatch.setattr(events.settings, "debug", False, raising=False)
    monkeypatch.setattr(events.settings, "partner_stub_enabled", False, raising=False)
    monkeypatch.setattr(events.settings, "distrokid_api_key", "dk_live", raising=False)
    monkeypatch.setattr(events.settings, "tunecore_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "routenote_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "cn_label_api_key", "", raising=False)
    assert verify_partner_request("Bearer dk_live", None, b"{}") == "bearer"
    with pytest.raises(HTTPException):
        verify_partner_request("Bearer no", None, b"{}")


def test_partner_adapters_normalize_webhooks():
    from app.services.distribution.adapters import CnLabelAdapter, DistroKidAdapter, RouteNoteAdapter, TuneCoreAdapter

    dk = DistroKidAdapter().parse_webhook(
        {"release_id": "dk_1", "dk_status": "approved", "store_link": "https://open.spotify.com/track/1"}
    )
    assert dk["status"] == "live"
    assert dk["external_id"] == "dk_1"
    tc = TuneCoreAdapter().parse_webhook({"tunecore_id": "tc_9", "tc_status": "distributed"})
    assert tc["status"] == "live"
    assert tc["external_id"] == "tc_9"
    rn = RouteNoteAdapter().parse_webhook({"routenote_id": "rn_2", "rn_status": "released"})
    assert rn["status"] == "live"
    cn = CnLabelAdapter().parse_webhook({"cn_label_id": "cn_3", "label_status": "online"})
    assert cn["status"] == "live"
    assert DistroKidAdapter().parse_webhook({"status": "live"}) is None


def test_partner_webhook_rejects_when_unconfigured(monkeypatch):
    from app.services.distribution import partner_events as events

    monkeypatch.setattr(events.settings, "partner_webhook_secret", "", raising=False)
    monkeypatch.setattr(events.settings, "debug", False, raising=False)
    monkeypatch.setattr(events.settings, "partner_stub_enabled", False, raising=False)
    monkeypatch.setattr(events.settings, "distrokid_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "tunecore_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "routenote_api_key", "", raising=False)
    monkeypatch.setattr(events.settings, "cn_label_api_key", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        verify_partner_request(None, None, b"{}")
    assert exc.value.status_code == 401


@pytest.mark.requires_db
def test_partner_webhook_marks_label_live(db):
    import uuid

    from app.models.schemas import DistributionDelivery, Release, ReleaseMetadata, User, Work
    from app.services.distribution.partner_events import apply_partner_event

    user = User(email=f"wh-{uuid.uuid4()}@test.local", username=f"wh_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Webhook Live", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    release = Release(work_id=work.id, owner_id=user.id, mode="label", status="delivering", selected_channels=["spotify"])
    db.add(release)
    db.commit()
    db.add(ReleaseMetadata(release_id=release.id, title="Webhook Live", artist_name="Tester"))
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
    result = apply_partner_event(
        db,
        {
            "delivery_id": str(delivery.id),
            "status": "live",
            "store_url": "https://open.spotify.com/track/demo",
            "external_id": "dk_auto_1",
            "event_id": "evt-1",
        },
    )
    assert result["status"] == "live"
    db.refresh(delivery)
    db.refresh(release)
    assert delivery.status == "live"
    assert delivery.store_url.endswith("/demo")
    assert delivery.external_id == "dk_auto_1"
    assert release.status == "live"
    again = apply_partner_event(db, {"delivery_id": str(delivery.id), "status": "live", "event_id": "evt-1"})
    assert again["duplicate"] is True


@pytest.mark.requires_db
def test_auto_submit_requires_consent_and_hydrates(db):
    import uuid

    from app.models.schemas import FeatureFlag, User, Work
    from app.services.distribution.service import auto_submit_release, create_or_get_release

    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "dsp_distribution").first()
    if not flag:
        db.add(FeatureFlag(key="dsp_distribution", enabled=True))
        db.commit()
    user = User(
        email=f"as-{uuid.uuid4()}@test.local",
        username=f"as_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        display_name="Auto Artist",
    )
    db.add(user)
    db.commit()
    work = Work(
        owner_id=user.id,
        title="Auto Track",
        audio_url="http://example.com/a.mp3",
        post_process_status={"release_qc": True, "release_qc_result": {"passed": True, "checks": {"has_audio": True}}},
    )
    db.add(work)
    db.commit()
    created = create_or_get_release(db, user, str(work.id))
    assert created["automation"]["ready_to_confirm"] is True
    assert created["qc_result"]["passed"] is True
    with pytest.raises(HTTPException) as exc:
        auto_submit_release(db, user, created["id"], {"consent": False})
    assert exc.value.status_code == 400


@pytest.mark.requires_db
def test_challenge_winner_stamps_priority(db):
    import uuid

    from app.models.schemas import Work, User
    from app.services.distribution.automation import release_priority_payload, stamp_release_priority

    user = User(email=f"pr-{uuid.uuid4()}@test.local", username=f"pr_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Winner", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    stamp_release_priority(work, reason="challenge_winner", rank=1, label="weekly")
    db.commit()
    db.refresh(work)
    pri = release_priority_payload(work)
    assert pri["score"] == 100
    assert pri["reason"] == "challenge_winner"


def test_ops_receipt_url_autolives_hold_only():
    assert should_autolive_from_ops_receipt("ops_queue", "https://open.spotify.com/track/x") is True
    assert should_autolive_from_ops_receipt("session_wait", "https://open.spotify.com/track/x") is True
    assert should_autolive_from_ops_receipt("in_review", "https://music.163.com/song?id=1") is True
    assert should_autolive_from_ops_receipt("rejected", "https://open.spotify.com/track/x") is False
    assert should_autolive_from_ops_receipt("ops_queue", "") is False
    assert should_autolive_from_ops_receipt("live", "https://open.spotify.com/track/x") is False
    assert should_autolive_from_ops_receipt("ops_queue", "https://artists.spotify.com/", "spotify") is False
    assert should_autolive_from_ops_receipt("session_wait", "https://music.163.com/st/musician", "netease") is False


def test_norm_isrc_strips_dashes():
    assert _norm_isrc("US-S1Z-26-00001") == "USS1Z2600001"


def test_cut_audio_clip_rejects_empty():
    assert cut_audio_clip(b"", start=10, duration=15) is None
    assert cut_audio_clip(b"not-audio", start=0, duration=0) is None


def test_sla_reminder_cutoff_is_24h():
    from app.services.distribution.automation import SLA_ESCALATE_HOURS, SLA_ESCALATE_PRIORITY, SLA_REMIND_AFTER_HOURS

    assert SLA_REMIND_AFTER_HOURS == 24
    assert SLA_ESCALATE_HOURS == 48
    assert SLA_ESCALATE_PRIORITY == 85
    assert datetime.utcnow() - timedelta(hours=SLA_REMIND_AFTER_HOURS) < datetime.utcnow()


def test_escalate_overdue_bumps_priority(monkeypatch):
    from app.services.distribution import automation as auto

    now = datetime.utcnow()
    row = SimpleNamespace(
        id="d1",
        owner_id="u1",
        release_id="r1",
        channel_code="spotify",
        status="ops_queue",
        created_at=now - timedelta(hours=50),
        attempt_meta={},
    )

    class Query:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *args, **kwargs):
            return self

        def limit(self, n):
            return self

        def all(self):
            return self._rows

    class DB:
        def query(self, model):
            name = getattr(model, "__name__", str(model))
            if "User" in name:
                return Query([])
            return Query([row])

    monkeypatch.setattr("app.services.distribution.pipeline.notify_distribution_status", lambda *a, **k: None)
    monkeypatch.setattr("app.services.notifications.create_notification", lambda *a, **k: None)
    assert auto.escalate_overdue_deliveries(DB(), now=now) == 1
    from app.services.distribution.service import _sla_payload

    assert _sla_payload(row)["sla_escalated"] is True
    assert row.attempt_meta["priority_score"] == 85
    assert row.attempt_meta.get("sla_escalated_at")


@pytest.mark.requires_db
def test_unattached_snapshot_attach_and_auto_release_consent(db):
    import uuid

    from app.models.schemas import PlatformMetricSnapshot, User, Work
    from app.services.distribution.automation import has_auto_release_consent, set_auto_release_consent
    from app.services.royalty.ingest import attach_snapshot_to_work, list_unattached_snapshots, rematch_unattached_snapshots

    user = User(
        email=f"ua-{uuid.uuid4()}@test.local",
        username=f"ua_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    work = Work(owner_id=user.id, title="Night Drive", audio_url="http://example.com/a.mp3")
    db.add(work)
    db.commit()
    snap = PlatformMetricSnapshot(
        user_id=user.id,
        work_id=None,
        channel_code="spotify",
        source="user_export",
        period_key="2026-08",
        streams=12,
        revenue_minor=80,
        usable_for_settlement=True,
        raw={"title": "Night Drive"},
    )
    db.add(snap)
    db.commit()
    rematch = rematch_unattached_snapshots(db, user.id)
    assert rematch["matched"] == 1
    db.refresh(snap)
    assert snap.work_id == work.id

    leftover = PlatformMetricSnapshot(
        user_id=user.id,
        work_id=None,
        channel_code="apple_music",
        source="user_export",
        period_key="2026-08",
        streams=3,
        revenue_minor=10,
        usable_for_settlement=True,
        raw={"title": "Unknown Cut"},
    )
    db.add(leftover)
    db.commit()
    listed = list_unattached_snapshots(db, user)
    assert any(row["id"] == str(leftover.id) for row in listed)
    attached = attach_snapshot_to_work(db, user, str(leftover.id), str(work.id))
    assert attached["attached"] is True
    assert has_auto_release_consent(db, user.id) is False
    status = set_auto_release_consent(db, user, False)
    assert status["enabled"] is False
    assert has_auto_release_consent(db, user.id) is False
    status = set_auto_release_consent(db, user, True)
    assert status["enabled"] is True
    assert has_auto_release_consent(db, user.id) is True
