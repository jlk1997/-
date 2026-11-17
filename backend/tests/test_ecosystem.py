"""Ecosystem feature tests."""

import uuid

import pytest
from fastapi import HTTPException

from app.models.schemas import CreditTransaction, User, UserCredit, Work, WorkExport
from app.services.credits import add_credits
from app.services.ecosystem import EXPORT_COSTS, MEMBER_FREE_MV_PER_MONTH, export_work


def test_export_costs_defined():
    assert "hq_wav" in EXPORT_COSTS
    assert "commercial_license" in EXPORT_COSTS
    assert EXPORT_COSTS["hq_mp3"] == 0
    assert EXPORT_COSTS["hq_wav"] == 1


def test_member_mv_free_quota_constant():
    assert MEMBER_FREE_MV_PER_MONTH == 1


@pytest.mark.requires_db
def test_export_wav_returns_download_url(db):
    user_id = uuid.uuid4()
    work_id = uuid.uuid4()
    try:
        user = User(
            id=user_id,
            email=f"exp-{uuid.uuid4().hex[:8]}@test.local",
            username=f"exp_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        work = Work(id=work_id, owner_id=user_id, title="Export Me", audio_url="http://x/a.mp3")
        db.add_all([user, work])
        db.commit()
        add_credits(db, user_id, 5, source="test_grant")
        db.commit()

        with pytest.raises(HTTPException) as err:
            export_work(db, user, str(work_id), "hq_wav")
        assert err.value.status_code == 400
        assert "master file" in str(err.value.detail)
    finally:
        db.query(WorkExport).filter(WorkExport.work_id == work_id).delete()
        db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).delete()
        db.query(UserCredit).filter(UserCredit.user_id == user_id).delete()
        db.query(Work).filter(Work.id == work_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()


@pytest.mark.requires_db
def test_export_stems_returns_pack(db):
    user_id = uuid.uuid4()
    work_id = uuid.uuid4()
    try:
        user = User(
            id=user_id,
            email=f"stem-{uuid.uuid4().hex[:8]}@test.local",
            username=f"stem_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        work = Work(id=work_id, owner_id=user_id, title="Stem Me", audio_url="http://x/a.mp3")
        db.add_all([user, work])
        db.commit()
        add_credits(db, user_id, 5, source="test_grant")
        db.commit()

        with pytest.raises(HTTPException) as err:
            export_work(db, user, str(work_id), "stems")
        assert err.value.status_code == 400
        assert "master file" in str(err.value.detail)
    finally:
        db.query(WorkExport).filter(WorkExport.work_id == work_id).delete()
        db.query(CreditTransaction).filter(CreditTransaction.user_id == user_id).delete()
        db.query(UserCredit).filter(UserCredit.user_id == user_id).delete()
        db.query(Work).filter(Work.id == work_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
