"""Landing plan: fields, fees, next step, graduation, SLA. No database."""

from datetime import datetime, timedelta

from app.core.mix_graph import export_listen_check, loudness_match_db
from app.services.creator_next import primary_creator_step
from app.services.distribution.channel_fields import missing_release_fields, required_fields_for
from app.services.distribution.fee_collection import fee_collection_policy
from app.services.ops.automation_graduation import graduation_verdict
from app.services.ops.maturity import reconciliation_row, retention_policy, sla_snapshot
from app.services.ops.roles import user_can, user_ops_role
from types import SimpleNamespace


def test_channel_union_asks_lyrics_for_netease_not_for_douyin():
    netease = required_fields_for(["netease"])
    douyin = required_fields_for(["douyin_musician"])
    assert "lyrics" in netease
    assert "composer" in netease
    assert "lyrics" not in douyin
    assert "price_minor" in required_fields_for(["bandcamp"])


def test_missing_fields_skip_lyrics_when_instrumental():
    meta = SimpleNamespace(
        title="夜车",
        artist_name="阿陈",
        lyrics=None,
        isrc=None,
        upc=None,
        language="zh",
        genres=["pop"],
        cover_url="https://cdn.example/c.jpg",
        ai_disclosed=True,
        extra={"listing": {"lyricist": "阿陈", "composer": "阿陈", "instrumental": True}},
    )
    gaps = {row["field"] for row in missing_release_fields(meta, ["netease"])}
    assert "lyrics" not in gaps
    assert "title" not in gaps


def test_self_release_fee_does_not_debit_the_store():
    policy = fee_collection_policy()
    assert policy["debits_user_store"] is False
    assert policy["self_release"] == "recorded_obligation"
    assert policy["self_release_rate_default"] == 10
    assert policy["label_rate_default"] == 20


def test_primary_step_releases_before_connector_and_drafts_before_sync():
    assert primary_creator_step(works=1, releases=0, unpublished_count=1, session_wait_count=3)["step"] == "release"
    assert (
        primary_creator_step(
            works=2,
            releases=1,
            has_live=True,
            delivering=True,
            pending_confirm_count=2,
        )["step"]
        == "settlements"
    )


def test_graduation_stays_manual_until_the_streak():
    early = graduation_verdict(channel_code="netease", days=30, orders=50, fill_rate=0.99, receipt_rate=0.91, match_rate=0.5)
    assert early["graduated"] is False
    assert early["ops_mode"] == "manual"
    ready = graduation_verdict(channel_code="netease", days=30, orders=50, fill_rate=0.96, receipt_rate=0.9, match_rate=0.98)
    assert ready["graduated"] is True
    assert ready["ops_mode"] == "spot_check"


def test_sla_and_reconciliation_and_retention():
    now = datetime(2026, 10, 1, 12, 0, 0)
    snap = sla_snapshot(
        [{"id": "a", "status": "ops_queue", "store_url": None, "created_at": now - timedelta(hours=72)}],
        now=now,
    )
    assert snap["overdue_count"] == 1
    tied = reconciliation_row(user_id="u", available_minor=80, pending_minor=20, ledger_net_minor=150, withdrawal_paid_minor=50)
    assert tied["ties"] is True
    assert retention_policy()["deletes_money_records"] is False


def test_export_check_and_loudness_match():
    bad = export_listen_check(duration=10, lufs=-6, peak_db=0.2, sample_rate=22050)
    assert bad["ok"] is False
    assert "loudness" in bad["reasons"]
    assert bad["web_audio_is_approximate"] is True
    assert loudness_match_db(-10) == -4


def test_editable_fields_follow_the_selected_stores():
    from app.services.distribution.channel_fields import editable_fields

    netease = editable_fields(["netease"])
    assert "lyrics" in netease
    assert "title" not in netease
    assert "lyrics" not in editable_fields(["douyin_musician"])
    assert "price_minor" in editable_fields(["netease", "bandcamp"])


def test_channel_stats_do_not_graduate_without_match_data():
    from app.services.ops.channel_stats import channel_automation_rows

    rows = channel_automation_rows(
        [
            {"channel_code": "netease", "status": "live", "store_url": "https://music.163.com/song?id=1", "last_error": None},
            {"channel_code": "netease", "status": "ops_queue", "store_url": None, "last_error": "fill_incomplete"},
        ]
    )
    assert rows[0]["channel_code"] == "netease"
    assert rows[0]["receipts"] == 1
    assert rows[0]["fill_failed"] == 1
    assert rows[0]["graduated"] is False
    assert rows[0]["match_rate"] is None
    admin = SimpleNamespace(is_admin=True, ops_role=None)
    staff = SimpleNamespace(is_admin=False, ops_role="finance")
    stranger = SimpleNamespace(is_admin=False, ops_role=None)
    assert user_ops_role(admin) == "admin"
    assert user_can(staff, "finance") is True
    assert user_can(staff, "distribution") is False
    assert user_can(stranger, "finance") is False
