"""Stale-job reconcile: dead workers fail, saved audio completes, post-process cannot un-hear a song."""

import uuid

import pytest

from app.services.job_state import STALE_COMPLETE, STALE_FAIL, STALE_SKIP, job_has_audio, stale_job_action

LIMITS = dict(
    pending_limit_s=15 * 60,
    running_limit_s=12 * 60,
    audio_ready_limit_s=10 * 60,
    post_process_limit_s=20 * 60,
)


def test_audio_ready_without_a_heartbeat_completes_when_audio_exists():
    action = stale_job_action(
        status="audio_ready",
        age_seconds=11 * 60,
        has_audio=True,
        has_celery_task=True,
        **LIMITS,
    )
    assert action == STALE_COMPLETE


def test_audio_ready_without_audio_fails():
    action = stale_job_action(
        status="audio_ready",
        age_seconds=11 * 60,
        has_audio=False,
        has_celery_task=True,
        **LIMITS,
    )
    assert action == STALE_FAIL


def test_dead_worker_fails_a_running_job_with_no_audio():
    fresh = stale_job_action(
        status="running",
        age_seconds=30,
        has_audio=False,
        has_celery_task=True,
        **LIMITS,
    )
    dead = stale_job_action(
        status="running",
        age_seconds=13 * 60,
        has_audio=False,
        has_celery_task=True,
        **LIMITS,
    )
    saved = stale_job_action(
        status="running",
        age_seconds=13 * 60,
        has_audio=True,
        has_celery_task=True,
        **LIMITS,
    )
    assert fresh == STALE_SKIP
    assert dead == STALE_FAIL
    assert saved == STALE_COMPLETE


def test_post_process_timeout_keeps_a_song_that_already_has_audio():
    action = stale_job_action(
        status="post_processing",
        age_seconds=21 * 60,
        has_audio=True,
        has_celery_task=True,
        **LIMITS,
    )
    assert action == STALE_COMPLETE
    assert job_has_audio({"work_id": "w1", "audio_url": "https://cdn/a.mp3"})
    assert job_has_audio({"work_ids": ["a"]})
    assert not job_has_audio({})
    assert not job_has_audio(None)


def test_pending_without_celery_fails_and_a_dispatched_one_waits():
    stuck = stale_job_action(
        status="pending",
        age_seconds=16 * 60,
        has_audio=False,
        has_celery_task=False,
        **LIMITS,
    )
    queued = stale_job_action(
        status="pending",
        age_seconds=16 * 60,
        has_audio=False,
        has_celery_task=True,
        **LIMITS,
    )
    assert stuck == STALE_FAIL
    assert queued == STALE_SKIP


@pytest.mark.requires_db
def test_post_process_failure_keeps_audio_ready_song():
    from app.database import SessionLocal
    from app.models.schemas import GenerationJob, User
    from app.services.job_state import begin_post_processing, mark_audio_ready, on_post_process_finished

    db = SessionLocal()
    try:
        user = User(
            email=f"ppw-{uuid.uuid4()}@test.local",
            username=f"ppw_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        db.add(user)
        db.commit()
        job = GenerationJob(
            owner_id=user.id,
            job_type="single",
            status="running",
            config={"credits_charged": 0},
            result={"work_id": "w1", "audio_url": "https://cdn/a.mp3"},
        )
        db.add(job)
        db.commit()
        mark_audio_ready(db, job.id, result=job.result)
        begin_post_processing(db, job.id, 1, result=job.result)
        done = on_post_process_finished(db, job.id, failed=True, error_message="cover failed")
        assert done is not None
        assert done.status == "completed"
        assert done.result.get("post_process_warning") == "cover failed"
        assert done.result.get("audio_url") == "https://cdn/a.mp3"
    finally:
        db.close()


@pytest.mark.requires_db
def test_fail_job_after_audio_ready_does_not_fail():
    from app.database import SessionLocal
    from app.models.schemas import GenerationJob, User
    from app.services.job_state import fail_job, mark_audio_ready

    db = SessionLocal()
    try:
        user = User(
            email=f"flk-{uuid.uuid4()}@test.local",
            username=f"flk_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        db.add(user)
        db.commit()
        job = GenerationJob(
            owner_id=user.id,
            job_type="single",
            status="running",
            config={"credits_charged": 0},
        )
        db.add(job)
        db.commit()
        mark_audio_ready(db, job.id, result={"work_id": "w2", "audio_url": "https://cdn/b.mp3"})
        locked = fail_job(db, job.id, error_message="worker exploded", error_code="WORKER_LOST")
        assert locked is not None
        assert locked.status == "completed"
        assert locked.result.get("post_process_warning") == "worker exploded"
    finally:
        db.close()
