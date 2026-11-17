from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.admin import _set_user_banned
from app.services.auth import assert_account_login_allowed
from app.services.work_access import assert_seed_rights, can_remix_work


def test_ban_blocks_self_and_last_admin():
    admin = SimpleNamespace(id="a1")
    target = SimpleNamespace(id="a1", is_admin=True, is_active=True)
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        _set_user_banned(db, target, banned=True, admin=admin)
    assert exc.value.status_code == 400

    other = SimpleNamespace(id="u2", is_admin=True, is_active=True, username="boss")
    db.query.return_value.filter.return_value.count.return_value = 0
    with pytest.raises(HTTPException):
        _set_user_banned(db, other, banned=True, admin=admin)


def test_banned_account_cannot_login():
    with pytest.raises(HTTPException) as exc:
        assert_account_login_allowed(SimpleNamespace(is_active=False, deleted_at=None))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        assert_account_login_allowed(SimpleNamespace(is_active=True, deleted_at="2026-01-01"))
    assert assert_account_login_allowed(SimpleNamespace(is_active=True, deleted_at=None)) is not None


def test_can_remix_work_respects_license():
    assert can_remix_work(SimpleNamespace(allow_remix=True, license="allow_remix")) is True
    assert can_remix_work(SimpleNamespace(allow_remix=False, license="allow_remix")) is False
    assert can_remix_work(SimpleNamespace(allow_remix=True, license="no_remix")) is False
    assert can_remix_work(SimpleNamespace(allow_remix=True, license="no_derivatives")) is False


def test_assert_seed_rights_blocks_foreign_no_remix(monkeypatch):
    owner = SimpleNamespace(id="owner")
    other = SimpleNamespace(id="other")
    work = SimpleNamespace(id="w1", owner_id="owner", allow_remix=False, license="no_remix")
    monkeypatch.setattr("app.services.work_access.get_seed_work", lambda db, work_id, user: work)
    with pytest.raises(HTTPException) as exc:
        assert_seed_rights(None, "w1", other)
    assert exc.value.status_code == 403
    assert assert_seed_rights(None, "w1", owner) is work
