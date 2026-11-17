import uuid

import pytest

from app.database import SessionLocal
from app.models.schemas import User
from app.services.notify_prefs import DEFAULT_NOTIFY, get_notify_prefs, set_notify_prefs


@pytest.mark.requires_db
def test_notify_prefs_default_and_update():
    db = SessionLocal()
    try:
        user = User(
            email=f"np-{uuid.uuid4().hex[:8]}@test.local",
            username=f"np_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        db.add(user)
        db.commit()
        prefs = get_notify_prefs(db, user.id)
        assert prefs == DEFAULT_NOTIFY
        updated = set_notify_prefs(db, user.id, {"email": False, "recall": False})
        assert updated["email"] is False
        assert updated["recall"] is False
        assert updated["in_app"] is True
        again = get_notify_prefs(db, user.id)
        assert again["email"] is False
        assert again["wechat"] is True
    finally:
        db.close()
