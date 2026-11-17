from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.emotion_calendar import infer_station_from_moods
from app.services.radio.network import _lineage_seed_live, _trial_live, expire_radio_trials
from app.services.royalty.payout_calendar import statement_receipt_no
from app.services.royalty.settlement import render_statement_receipt


def test_infer_station_from_journal_moods():
    assert infer_station_from_moods(["calm", "night"]) == "calm"
    assert infer_station_from_moods(["energetic"]) == "commute"
    assert infer_station_from_moods(["study"]) == "focus"
    assert infer_station_from_moods([], arousal=4.0) == "commute"
    assert infer_station_from_moods([], valence=1.2) == "calm"
    assert infer_station_from_moods([], arousal=1.5) == "night"


def test_statement_receipt_keeps_credits_out():
    no = statement_receipt_no("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "2026-08")
    assert no.startswith("VS-S-202608-")
    text = render_statement_receipt(
        receipt_no=no,
        period_key="2026-08",
        by_currency=[{"currency": "CNY", "gross_minor": 200, "commission_minor": 40, "net_minor": 160}],
        source_split={"radio_minor": 12, "sync_minor": 0, "embed_minor": 5, "dsp_minor": 148},
        next_payout_date="2026-08-21",
    )
    assert "不含积分打赏" in text
    assert "电台预热" in text
    assert "厂牌版税" in text
    assert "嵌入完播" in text
    assert "¥0.12" in text
    assert "¥0.05" in text
    assert "2026-08-21" in text
    assert no in text


def test_trial_live_and_lineage_seed_flags():
    now = datetime(2026, 8, 19, 12, 0, 0)
    live = SimpleNamespace(post_process_status={"radio_trial": {"status": "live", "ends_at": "2026-08-20T12:00:00"}})
    dead = SimpleNamespace(post_process_status={"radio_trial": {"status": "live", "ends_at": "2026-08-18T12:00:00"}})
    assert _trial_live(live, now=now) is True
    assert _trial_live(dead, now=now) is False
    seeded = SimpleNamespace(post_process_status={"lineage_seed": {"week": "2026-W34", "until": "2026-08-26T00:00:00"}})
    assert _lineage_seed_live(seeded, now=now) is True


@pytest.mark.requires_db
def test_expire_radio_trials_marks_ended(db):
    import uuid

    from app.models.schemas import User, Work

    user = User(
        email=f"t-{uuid.uuid4().hex[:8]}@test.local",
        username=f"t_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    work = Work(
        owner_id=user.id,
        title="Ended Trial",
        audio_url="http://example.com/a.mp3",
        visibility="unlisted",
        post_process_status={"radio_trial": {"status": "live", "ends_at": "2020-01-01T00:00:00", "station": "calm"}},
    )
    db.add(work)
    db.commit()
    db.refresh(work)
    ended = expire_radio_trials(db, now=datetime(2026, 8, 19, 12, 0, 0))
    db.commit()
    db.refresh(work)
    assert ended >= 1
    assert (work.post_process_status or {}).get("radio_trial", {}).get("status") == "ended"


@pytest.mark.requires_db
def test_week_drop_matches_journal_mood(db):
    import uuid
    from datetime import date

    from app.models.schemas import EmotionJournalEntry, User, Work
    from app.services.emotion_calendar import week_drop_plan

    user = User(
        email=f"e-{uuid.uuid4().hex[:8]}@test.local",
        username=f"e_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    calm = Work(owner_id=user.id, title="Calm River", audio_url="http://example.com/a.mp3", moods=["calm", "healing"])
    hype = Work(owner_id=user.id, title="City Run", audio_url="http://example.com/b.mp3", moods=["energetic"])
    db.add_all([calm, hype])
    db.add(
        EmotionJournalEntry(
            user_id=user.id,
            entry_date=date.today(),
            arousal=2.0,
            valence=2.4,
            mood_tags=["calm"],
        )
    )
    db.commit()
    plan = week_drop_plan(db, user)
    assert plan["station"] == "calm"
    assert plan["work"]["title"] == "Calm River"
    assert plan["why"] == "emotion_week"
    assert plan["next_action"] == "radio_trial"
