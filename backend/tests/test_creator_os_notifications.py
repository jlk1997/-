from types import SimpleNamespace
from uuid import uuid4

from app.services.notifications import notify_challenge_award, notify_duel_result


def test_notify_challenge_award_includes_work_id(monkeypatch):
    captured = {}

    def _create(db, user_id, ntype, payload, **kwargs):
        captured["type"] = ntype
        captured["payload"] = payload
        return SimpleNamespace()

    monkeypatch.setattr("app.services.notifications.create_notification", _create)
    notify_challenge_award(
        None,
        uuid4(),
        challenge_title="夜车",
        rank=1,
        credits=50,
        work_title="Night Drive",
        work_id="work-1",
        challenge_slug="night-drive",
    )
    assert captured["type"] == "challenge_award"
    assert captured["payload"]["work_id"] == "work-1"
    assert captured["payload"]["challenge_slug"] == "night-drive"


def test_notify_duel_result_includes_winner_work_id(monkeypatch):
    captured = []

    def _create(db, user_id, ntype, payload, **kwargs):
        captured.append({"user_id": user_id, "type": ntype, "payload": payload})
        return SimpleNamespace()

    monkeypatch.setattr("app.services.notifications.create_notification", _create)
    challenger = uuid4()
    opponent = uuid4()
    work_id = uuid4()
    duel = SimpleNamespace(
        id=uuid4(),
        challenger_id=challenger,
        opponent_id=opponent,
        winner_id=challenger,
        status="settled",
        challenger_work_id=work_id,
        opponent_work_id=uuid4(),
    )
    notify_duel_result(None, duel)
    winner_note = next(row for row in captured if row["payload"]["won"])
    assert winner_note["type"] == "duel_result"
    assert winner_note["payload"]["work_id"] == str(work_id)
