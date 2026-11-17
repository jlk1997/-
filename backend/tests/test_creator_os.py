from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.distribution.catalog import channel_sop
from app.services.distribution.passport import _share_line
from app.services.distribution.service import SLA_HOURS, _sla_payload
from app.services.listen_engagement import RADIO_RULES, MIN_LISTEN_RATIO
from app.services.royalty.priority import filter_settlement_snapshots
from app.services.royalty.splits import PARENT_PERCENT, expand_split_lines


def test_remix_parent_default_is_20():
    assert PARENT_PERCENT == 20


def test_expand_split_lines_parent_share(monkeypatch):
    from app.services.royalty import splits as splits_mod

    monkeypatch.setattr(
        splits_mod,
        "_raw_shares",
        lambda db, work: [
            {"user_id": "owner", "role": "owner", "percent": 80},
            {"user_id": "parent", "role": "parent", "percent": 20},
        ],
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return object()

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    parts = expand_split_lines(DB(), "work-1", "owner", 1000, 200, 800)
    assert [row["user_id"] for row in parts] == ["owner", "parent"]
    assert parts[0]["net_minor"] == 640
    assert parts[1]["net_minor"] == 160
    assert sum(row["net_minor"] for row in parts) == 800


def test_two_official_sources_settle_once():
    first = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=900,
    )
    second = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="official_api",
        usable_for_settlement=True,
        revenue_minor=900,
    )
    out = filter_settlement_snapshots([first, second])
    assert out == [first] or out == [second]


def test_passport_share_line_and_sla():
    assert "6" in _share_line("Night Drive", 6)
    assert "已上架 6 店" in _share_line("Night Drive", 6)
    assert "试听局进行中" in _share_line("Night Drive", 0, trial=True)
    assert "已上架 2 店 / 试听局进行中" in _share_line("Night Drive", 2, trial=True)
    assert "正在发行" in _share_line("Night Drive", 0)
    due = _sla_payload(SimpleNamespace(status="ops_queue", created_at=datetime.utcnow(), attempt_meta={}))
    assert due["sla_hours"] == SLA_HOURS
    assert due["sla_overdue"] is False
    assert due["sla_escalated"] is False
    hot = _sla_payload(
        SimpleNamespace(
            status="ops_queue",
            created_at=datetime.utcnow(),
            attempt_meta={"sla_escalated_at": "2026-08-19T12:00:00"},
        )
    )
    assert hot["sla_escalated"] is True
    idle = _sla_payload(SimpleNamespace(status="live", created_at=datetime.utcnow(), attempt_meta={}))
    assert idle["sla_due_at"] is None


def test_channel_sop_and_radio_rules():
    assert "网易" in channel_sop("netease")
    assert "原创证明" in channel_sop("netease")
    assert "母带" in channel_sop("kugou")
    assert "分轨" in channel_sop("kugou")
    assert "母带" in channel_sop("bilibili")
    assert "master" in channel_sop("youtube_music").lower()
    assert "TME_tmemusicians" in channel_sop("qq_music")
    assert "切片" in channel_sop("qishui")
    assert "母带" in channel_sop("qishui")
    assert RADIO_RULES["usable_for_settlement"] is False
    assert RADIO_RULES["revenue_minor_per_complete"] == 0
    assert RADIO_RULES["min_listen_ratio"] == MIN_LISTEN_RATIO
    assert RADIO_RULES["channel_code"] == "vibe_radio"
    assert RADIO_RULES["self_listen_source"] == "first_party_radio_self"


def test_increment_display_snapshot_stays_unusable():
    from app.services.royalty.snapshots import increment_display_snapshot

    existing = SimpleNamespace(streams=2, usable_for_settlement=True, revenue_minor=0, release_id=None, raw={})

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return existing

    class DB:
        def query(self, *args, **kwargs):
            return Query()

        def add(self, row):
            raise AssertionError("should increment existing row")

    row = increment_display_snapshot(
        DB(),
        user_id="u",
        channel_code="vibe_radio",
        period_key="2026-08",
        source="first_party_radio",
        streams=1,
        work_id="w",
    )
    assert row.streams == 3
    assert row.usable_for_settlement is False


def test_increment_settlement_snapshot_is_usable():
    from app.services.royalty.snapshots import increment_settlement_snapshot

    existing = SimpleNamespace(
        streams=2,
        usable_for_settlement=False,
        revenue_minor=0,
        release_id=None,
        currency="CNY",
        raw={},
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return existing

    class DB:
        def query(self, *args, **kwargs):
            return Query()

        def add(self, row):
            raise AssertionError("should increment existing row")

    row = increment_settlement_snapshot(
        DB(),
        user_id="u",
        channel_code="vibe_radio",
        period_key="2026-08",
        source="first_party_radio",
        streams=1,
        revenue_minor=1,
        work_id="w",
    )
    assert row.streams == 3
    assert row.revenue_minor == 1
    assert row.usable_for_settlement is True


@pytest.mark.requires_db
def test_passport_includes_human_edits(db):
    import uuid

    from app.models.schemas import ProvenanceRecord, User, Work
    from app.services.distribution.passport import build_passport

    user_id = uuid.uuid4()
    work_id = uuid.uuid4()
    try:
        user = User(
            id=user_id,
            email=f"pass-{uuid.uuid4().hex[:8]}@test.local",
            username=f"pass_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        work = Work(id=work_id, owner_id=user_id, title="Passport Edit", audio_url="http://x/a.mp3", duration=120)
        db.add_all([user, work])
        db.flush()
        db.add(
            ProvenanceRecord(
                work_id=work_id,
                pipeline_version="test",
                record_type="generated",
                output_meta={"human_edits": [{"kind": "section", "section": "chorus"}]},
            )
        )
        db.commit()
        passport = build_passport(db, work_id=str(work_id))
        assert passport["human_edits"][0]["section"] == "chorus"
        assert [c["length"] for c in passport["clip_windows"]] == [15, 30, 60]
    finally:
        db.rollback()
        db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work_id).delete()
        db.query(Work).filter(Work.id == work_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
