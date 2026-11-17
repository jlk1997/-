from datetime import date
from types import SimpleNamespace

import pytest

from app.services.creator.commune import COMMUNE_MAX
from app.services.distribution.channel_suggest import apply_suggested_ship, suggest_channels
from app.services.distribution.passport_share import build_feed_caption
from app.services.royalty.payout_calendar import next_payout_date, payout_calendar, receipt_no_for, send_payout_day_nudges, statement_receipt_no


def test_suggest_channels_cn_first_from_completes():
    work = SimpleNamespace(moods=["calm", "night"], genres=["lofi"])
    out = suggest_channels(work, listen_completes=12, resonance_avg=0.72)
    assert out["region"] == "cn"
    assert out["channels"][:2] == ["netease", "qq_music"]
    assert out["advisory"] is True
    assert "网易" in out["reason"] or "汽水" in out["reason"]


def test_suggest_channels_uses_complete_rate_copy():
    work = SimpleNamespace(moods=["calm"], genres=["lofi"])
    out = suggest_channels(work, listen_completes=31, listen_starts=50)
    assert out["complete_rate"] == 0.62
    assert "62%" in out["reason"]


def test_suggest_channels_global_when_hype():
    work = SimpleNamespace(moods=["energetic", "party"], genres=["edm"])
    out = suggest_channels(work, listen_completes=2, resonance_avg=0.2)
    assert out["region"] == "global"
    assert "spotify" in out["channels"]


def test_suggest_channels_uses_synced_store_streams():
    work = SimpleNamespace(moods=[], genres=[])
    out = suggest_channels(work, store_streams={"spotify": 8000, "apple_music": 1200})
    assert out["region"] == "global"
    assert "spotify" in out["channels"]
    assert out["used_store_streams"] is True


def test_suggested_ship_only_ready_stores():
    work = SimpleNamespace(
        moods=["calm"],
        genres=["lofi"],
        post_process_status={
            "master": {"key": "works/1/master.wav"},
            "release_qc_result": {"passed": True},
        },
    )
    advisory = suggest_channels(work, listen_completes=12, resonance_avg=0.7)
    out = apply_suggested_ship(work, advisory, connections=[])
    assert out["suggested_ship"] is True
    assert len(out["channels"]) <= 3
    assert "spotify" not in out["channels"]
    assert all(code not in {"spotify", "apple_music", "tiktok_music", "amazon_music", "deezer"} for code in out["channels"])
    blocked = apply_suggested_ship(
        SimpleNamespace(post_process_status={"release_qc_result": {"passed": False}}),
        {"channels": ["netease", "spotify"], "region": "cn"},
        connections=[],
    )
    assert blocked["channels"] == []
    assert any(row["reason"] == "qc" for row in blocked["blocked"])


def test_payout_calendar_friday():
    friday = date(2026, 8, 21)
    assert friday.weekday() == 4
    assert next_payout_date(friday) == friday
    assert next_payout_date(date(2026, 8, 19)) == friday
    cal = payout_calendar(today=date(2026, 8, 19))
    assert cal["next_payout_date"] == "2026-08-21"
    assert cal["weekday_label"] == "周五"
    assert cal["days_until_payout"] == 2
    assert cal["is_payout_day"] is False
    friday_cal = payout_calendar(today=friday)
    assert friday_cal["days_until_payout"] == 0
    assert friday_cal["is_payout_day"] is True
    skipped = send_payout_day_nudges(SimpleNamespace(), today=date(2026, 8, 19))
    assert skipped["skipped"] == "not_payout_day"
    assert skipped["sent"] == 0


def test_receipt_no_stable():
    row = SimpleNamespace(id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", created_at=None, receipt_no=None)
    assert receipt_no_for(row).startswith("VS-W-")
    stored = SimpleNamespace(receipt_no="VS-W-20260821-AA11BB22")
    assert receipt_no_for(stored) == "VS-W-20260821-AA11BB22"
    assert statement_receipt_no("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "2026-08").startswith("VS-S-202608-")


def test_passport_caption_keeps_wallets_apart():
    line = build_feed_caption(
        share_line="「Night Drive」已上架 2 店 / 试听局进行中",
        store_names=["网易云音乐", "汽水音乐"],
        period_net_minor=1200,
    )
    assert "已上架 2 店" in line
    assert "试听局进行中" in line
    assert "网易云音乐" in line
    assert "¥12.00" in line
    assert "不含积分打赏" in line
    assert COMMUNE_MAX == 10


@pytest.mark.requires_db
def test_commune_board_hides_wallets(db):
    import uuid

    from app.models.schemas import User
    from app.services.creator.commune import commune_board, create_commune, invite_username

    owner = User(email=f"c-{uuid.uuid4()}@t.local", username=f"c_{uuid.uuid4().hex[:8]}", hashed_password="x")
    peer = User(email=f"p-{uuid.uuid4()}@t.local", username=f"p_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add_all([owner, peer])
    db.commit()
    db.refresh(owner)
    db.refresh(peer)
    create_commune(db, owner, "Label Desk")
    invite_username(db, owner, peer.username)
    board = commune_board(db, owner)
    assert board["wallet_shared"] is False
    assert board["commune"]["member_count"] == 2
    assert "available_minor" not in board
    assert all("revenue" not in row for row in board["queue"])


@pytest.mark.requires_db
def test_payout_day_nudge_only_friday_with_balance(db):
    import uuid
    from datetime import date

    from app.models.schemas import Notification, User
    from app.services.royalty.payout_calendar import send_payout_day_nudges
    from app.services.royalty.wallet import get_or_create_wallet

    user = User(email=f"pay-{uuid.uuid4()}@t.local", username=f"pay_{uuid.uuid4().hex[:8]}", hashed_password="x")
    empty = User(email=f"empty-{uuid.uuid4()}@t.local", username=f"empty_{uuid.uuid4().hex[:8]}", hashed_password="x")
    db.add_all([user, empty])
    db.commit()
    db.refresh(user)
    db.refresh(empty)
    wallet = get_or_create_wallet(db, user.id, "CNY")
    wallet.available_minor = 1800
    get_or_create_wallet(db, empty.id, "CNY")
    db.commit()

    skipped = send_payout_day_nudges(db, today=date(2026, 8, 19))
    assert skipped["skipped"] == "not_payout_day"
    assert skipped["sent"] == 0

    first = send_payout_day_nudges(db, today=date(2026, 8, 21))
    assert first["sent"] == 1
    again = send_payout_day_nudges(db, today=date(2026, 8, 21))
    assert again["sent"] == 0
    note = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "payout_day")
        .first()
    )
    assert note is not None
    assert note.payload.get("available_minor") == 1800
    assert note.payload.get("manual_payout") is True
    assert note.payload.get("currency") == "CNY"
    assert (
        db.query(Notification)
        .filter(Notification.user_id == empty.id, Notification.type == "payout_day")
        .first()
        is None
    )
