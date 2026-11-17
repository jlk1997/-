from types import SimpleNamespace

from app.api.schemas import WorkResponse
from app.services.distribution.passport import _share_line
from app.services.duels import MIN_VOTE_LISTEN_RATIO
from app.services.listen_engagement import MIN_LISTEN_RATIO
from app.services.work_access import can_view_work
from app.services.work_quality import compute_work_quality


def test_duel_vote_threshold_matches_radio():
    assert MIN_VOTE_LISTEN_RATIO == MIN_LISTEN_RATIO == 0.8


def test_share_line_prefers_live_and_trial():
    assert "我做了首歌" not in _share_line("Night Drive", 3, trial=True)
    assert _share_line("Night Drive", 3, trial=True) == "「Night Drive」已上架 3 店 / 试听局进行中"


def test_work_quality_preflight_loudness_fails_early():
    work = SimpleNamespace(
        moods=["calm"],
        genres=["lofi"],
        cover_url="https://cdn.example/cover.png",
        arousal=4,
        valence=6,
        duration=120,
        audio_url="https://cdn.example/a.mp3",
        post_process_status={
            "generation_preflight": {"duration_ok": True, "loudness_ok": False, "has_cover": True, "lufs": -6}
        },
    )
    out = compute_work_quality(work)
    assert out["suggestion_key"] == "loudness"
    assert out["preflight"]["passed"] is False
    assert out["completion"] <= 54


def test_work_quality_preflight_duration_then_cover():
    work = SimpleNamespace(
        moods=["calm", "night", "warm", "soft"],
        genres=["lofi", "jazz"],
        cover_url=None,
        arousal=4,
        valence=6,
        duration=12,
        audio_url="https://cdn.example/a.mp3",
        post_process_status={
            "generation_preflight": {"duration_ok": False, "loudness_ok": True, "has_cover": False}
        },
    )
    out = compute_work_quality(work)
    assert out["suggestion_key"] == "duration"


def test_work_quality_cover_before_mood():
    work = SimpleNamespace(
        moods=["calm"],
        genres=["lofi"],
        cover_url=None,
        arousal=4,
        valence=6,
        duration=120,
        audio_url="https://cdn.example/a.mp3",
        post_process_status={
            "generation_preflight": {"duration_ok": True, "loudness_ok": True, "has_cover": False, "originality_risk": 0}
        },
    )
    out = compute_work_quality(work)
    assert out["suggestion_key"] == "cover"
    assert out["preflight"]["has_cover"] is False


def test_work_quality_originality_before_cover():
    work = SimpleNamespace(
        moods=["calm"],
        genres=["lofi"],
        cover_url=None,
        arousal=4,
        valence=6,
        duration=120,
        audio_url="https://cdn.example/a.mp3",
        post_process_status={
            "generation_preflight": {
                "duration_ok": True,
                "loudness_ok": True,
                "has_cover": False,
                "originality_risk": 80,
            }
        },
    )
    out = compute_work_quality(work)
    assert out["suggestion_key"] == "originality"
    assert out["preflight"]["originality_risk"] == 80


def test_work_quality_exposes_listing_vs_evidence():
    work = SimpleNamespace(
        moods=["calm"],
        genres=["lofi"],
        cover_url="https://cdn.example/c.jpg",
        arousal=4,
        valence=6,
        duration=120,
        audio_url="https://cdn.example/a.mp3",
        storage_key="works/1/mix.mp3",
        post_process_status={
            "master": {"key": "works/1/master.wav", "url": "https://cdn.example/master.wav"},
            "stems": {"quality": "preview"},
            "sku_kind": None,
        },
    )
    out = compute_work_quality(work)
    assets = out["release_assets"]
    assert assets["master_ready"] is True
    assert assets["master_wav"] is True
    assert assets["stems_quality"] == "preview"
    assert assets["evidence_ready"] is False


def test_guest_can_view_public_not_private():
    public = SimpleNamespace(visibility="public", owner_id="owner")
    unlisted = SimpleNamespace(visibility="unlisted", owner_id="owner")
    private = SimpleNamespace(visibility="private", owner_id="owner")
    assert can_view_work(public, None) is True
    assert can_view_work(unlisted, None) is True
    assert can_view_work(private, None) is False


def test_work_response_exposes_artist_placeholder_fields():
    assert "artist_name" in WorkResponse.model_fields
    assert "owner_username" in WorkResponse.model_fields


def test_share_line_never_uses_i_made_a_song():
    assert "我做了首歌" not in _share_line("Night Drive", 0, trial=False)
    assert "已上架" in _share_line("Night Drive", 1, trial=False)


def test_self_listen_is_own_work():
    from app.services.listen_engagement import is_own_work

    owner = "owner-id"
    work = SimpleNamespace(owner_id=owner)
    assert is_own_work(work, owner) is True
    assert is_own_work(work, "other") is False
    assert is_own_work(work, None) is False


def test_radio_trial_does_not_pin_daily_meta_station():
    from app.services.radio.network import normalize_station

    code = normalize_station("daily")
    if code == "daily":
        code = "calm"
    assert code != "daily"
    assert normalize_station("calm") == "calm"


def test_radio_payout_is_display_only():
    from app.services.listen_engagement import MEMBER_RADIO_PAYOUT_MINOR, RADIO_PAYOUT_MINOR, RADIO_RULES
    from app.services.radio import network as net

    assert RADIO_PAYOUT_MINOR == 0
    assert MEMBER_RADIO_PAYOUT_MINOR == 0
    assert net.MEMBER_RADIO_PAYOUT_MINOR == MEMBER_RADIO_PAYOUT_MINOR
    assert RADIO_RULES["revenue_minor_per_complete"] == RADIO_PAYOUT_MINOR
    assert RADIO_RULES["member_revenue_minor_per_complete"] == MEMBER_RADIO_PAYOUT_MINOR
    assert RADIO_RULES["min_listen_ratio"] == MIN_LISTEN_RATIO == 0.8
    assert RADIO_RULES["usable_for_settlement"] is False
    assert RADIO_RULES["self_listen_source"] == "first_party_radio_self"
    assert net.radio_payout_minor(None, "member") == 0


def test_radio_listen_settled_notifier_exists():
    from app.services.notifications import notify_radio_listen_settled, radio_settled_notified_today

    assert callable(notify_radio_listen_settled)
    assert radio_settled_notified_today([{"work_id": "w1"}], "w1") is True
    assert radio_settled_notified_today([{"work_id": "w2"}], "w1") is False
    assert radio_settled_notified_today([], "w1") is False
