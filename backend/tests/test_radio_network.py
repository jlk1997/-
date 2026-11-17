from datetime import datetime
from types import SimpleNamespace

from app.services.radio.network import (
    MEMBER_RADIO_PAYOUT_MINOR,
    STATIONS,
    _clip_portal,
    _iso_week_key,
    normalize_station,
    radio_payout_minor,
    stamp_radio_feature,
    station_of_the_day,
)


def test_stations_cover_plan_play_modes():
    assert {"daily", "commute", "night", "calm", "focus", "lineage", "weekend"} <= set(STATIONS)


def test_station_of_the_day_night_and_commute():
    assert station_of_the_day(now=datetime(2026, 8, 19, 23, 0, 0)) == "night"
    assert station_of_the_day(now=datetime(2026, 8, 19, 8, 0, 0)) == "commute"
    assert normalize_station("nope") == "daily"
    assert normalize_station("calm") == "calm"


def test_clip_portal_https_hosts_only():
    assert _clip_portal("https://www.douyin.com/video/1") == "douyin_musician"
    assert _clip_portal("https://channels.weixin.qq.com/x") == "wechat_channels"
    assert _clip_portal("https://evil.example/x") is None


def test_radio_payout_stays_zero():
    assert MEMBER_RADIO_PAYOUT_MINOR == 0
    assert radio_payout_minor(SimpleNamespace(), "member") == 0
    assert radio_payout_minor(SimpleNamespace(), "free") == 0
    assert "不进可提现" in STATIONS["commute"]["blurb"]


def test_radio_feature_stamp():
    work = SimpleNamespace(post_process_status={})
    payload = stamp_radio_feature(work, reason="duel_winner", rank=1)
    assert payload["reason"] == "duel_winner"
    assert "weekend" in payload["stations"]
    assert work.post_process_status["radio_feature"]["until"]


def test_iso_week_key_stable():
    assert _iso_week_key(now=datetime(2026, 8, 19, 12, 0, 0)) == "2026-W34"
