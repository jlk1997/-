"""Reference track — inherit AV/moods/genres from an existing work with optional offset."""

from __future__ import annotations

import hashlib
import math
import uuid
from copy import deepcopy

from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models.schemas import EmotionEmbedding, User, Work


def assert_reference_rights(db: Session, work_id: str | uuid.UUID, user: User) -> Work:
    """Owner can always seed; others need view + remix rights."""
    from app.services.work_access import can_remix_work, get_viewable_work

    ref = get_viewable_work(db, str(work_id), user)
    if ref.owner_id != user.id and not can_remix_work(ref):
        raise HTTPException(status_code=403, detail="reference_remix_forbidden")
    return ref


def av_mood_embedding(work: Work) -> list[float]:
    """Deterministic 512-d fallback from AV + moods when no audio embedding exists."""
    vec = [0.0] * 512
    arousal = float(work.arousal or 5) / 9.0
    valence = float(work.valence or 5) / 9.0
    vec[0] = arousal
    vec[1] = valence
    vec[2] = (arousal + valence) / 2.0
    for mood in list(work.moods or [])[:16]:
        digest = hashlib.sha256(str(mood).lower().encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % 512
        vec[idx] = min(1.0, vec[idx] + 0.35)
    norm = math.sqrt(sum(item * item for item in vec)) or 1.0
    return [item / norm for item in vec]


def ensure_reference_embedding(db: Session, work: Work) -> list[float]:
    row = db.query(EmotionEmbedding).filter(EmotionEmbedding.work_id == work.id).first()
    if row is not None and row.embedding is not None:
        return list(row.embedding) if not isinstance(row.embedding, list) else row.embedding
    vec = av_mood_embedding(work)
    if row is None:
        db.add(EmotionEmbedding(work_id=work.id, embedding=vec, model_name="av-mood-fallback"))
    else:
        row.embedding = vec
        row.model_name = row.model_name or "av-mood-fallback"
    db.flush()
    return vec


def apply_reference_emotion(
    db: Session,
    base: dict,
    reference_work_id: str | uuid.UUID | None,
    *,
    av_offset: dict | None = None,
    user: User | None = None,
) -> tuple[dict, uuid.UUID | None]:
    """Merge a rights-cleared reference work into base. No user → no inherit, no embedding."""
    if not reference_work_id or user is None:
        return base, None

    try:
        ref_uuid = uuid.UUID(str(reference_work_id))
    except ValueError:
        return base, None

    try:
        ref_work = assert_reference_rights(db, ref_uuid, user)
    except HTTPException:
        return base, None

    out = deepcopy(base)
    if ref_work.arousal is not None:
        out["arousal"] = ref_work.arousal
    if ref_work.valence is not None:
        out["valence"] = ref_work.valence
    if ref_work.moods:
        out["moods"] = list(ref_work.moods)
    if ref_work.genres:
        out["genres"] = list(ref_work.genres)

    offset = av_offset or {}
    if offset.get("arousal") is not None and out.get("arousal") is not None:
        out["arousal"] = max(1, min(9, float(out["arousal"]) + float(offset["arousal"])))
    if offset.get("valence") is not None and out.get("valence") is not None:
        out["valence"] = max(1, min(9, float(out["valence"]) + float(offset["valence"])))

    try:
        out["reference_embedding"] = ensure_reference_embedding(db, ref_work)
        out["reference_embedding_ready"] = True
    except Exception:
        out["reference_embedding_ready"] = False

    return out, ref_uuid


def resolve_reference_config(journey_config: dict, anchor_context: dict | None = None) -> dict | None:
    """Pick reference block from journey config or anchor context."""
    ref = journey_config.get("reference")
    if ref and ref.get("work_id"):
        return ref
    ctx = anchor_context or {}
    if ctx.get("reference_work_id"):
        return {
            "work_id": ctx["reference_work_id"],
            "av_offset": ref.get("av_offset") if ref else None,
        }
    return None
