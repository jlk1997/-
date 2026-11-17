import uuid

import pytest

from app.core.emotion_engine import emotion_engine
from app.database import SessionLocal
from app.models.schemas import User, Work
from app.services.reference_track import apply_reference_emotion


@pytest.mark.requires_db
def test_apply_reference_emotion_with_offset():
    db = SessionLocal()
    try:
        user = User(
            email=f"ref-{uuid.uuid4()}@test.local",
            username=f"refuser_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        ref = Work(
            owner_id=user.id,
            title="Reference",
            audio_url="http://example/a.mp3",
            moods=["calm"],
            genres=["ambient"],
            arousal=4.0,
            valence=5.0,
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        base = emotion_engine.infer_from_intent(text_intent="happy electronic")
        skipped, skipped_id = apply_reference_emotion(
            db,
            base,
            ref.id,
            av_offset={"arousal": 2, "valence": 1},
        )
        assert skipped_id is None
        assert skipped is base

        merged, ref_id = apply_reference_emotion(
            db,
            base,
            ref.id,
            av_offset={"arousal": 2, "valence": 1},
            user=user,
        )
        assert ref_id == ref.id
        assert merged["moods"] == ["calm"]
        assert merged["genres"] == ["ambient"]
        assert merged["arousal"] == 6.0
        assert merged["valence"] == 6.0
        assert merged.get("reference_embedding_ready") is True
        assert merged.get("reference_embedding")
    finally:
        db.close()


@pytest.mark.requires_db
def test_apply_reference_emotion_requires_remix_rights():
    db = SessionLocal()
    try:
        owner = User(
            email=f"ref-own-{uuid.uuid4()}@test.local",
            username=f"refown_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        stranger = User(
            email=f"ref-str-{uuid.uuid4()}@test.local",
            username=f"refstr_{uuid.uuid4().hex[:8]}",
            hashed_password="x",
        )
        db.add_all([owner, stranger])
        db.commit()
        db.refresh(owner)
        db.refresh(stranger)

        ref = Work(
            owner_id=owner.id,
            title="Locked",
            audio_url="http://example/a.mp3",
            moods=["dark"],
            genres=["ambient"],
            arousal=3.0,
            valence=3.0,
            visibility="public",
            allow_remix=False,
            license="no_remix",
        )
        db.add(ref)
        db.commit()
        db.refresh(ref)

        base = emotion_engine.infer_from_intent(text_intent="happy electronic")
        merged, ref_id = apply_reference_emotion(db, base, ref.id, user=stranger)
        assert ref_id is None
        assert merged is base
        assert "reference_embedding" not in merged
    finally:
        db.close()
