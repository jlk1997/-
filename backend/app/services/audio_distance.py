"""Perceptual distance between works — AV first, embedding when present."""

from __future__ import annotations

import math
import uuid

from sqlalchemy.orm import Session

from app.models.schemas import EmotionEmbedding, Work
from app.services.recommendation import _cosine_similarity


def av_distance(left: Work | None, right: Work | None) -> float:
    if not left or not right:
        return 1.0
    if left.arousal is None or left.valence is None or right.arousal is None or right.valence is None:
        return 1.0
    da = (float(left.arousal) - float(right.arousal)) / 8.0
    dv = (float(left.valence) - float(right.valence)) / 8.0
    return min(1.0, math.hypot(da, dv))


def embedding_distance(db: Session, left_id, right_id) -> float | None:
    try:
        a = left_id if isinstance(left_id, uuid.UUID) else uuid.UUID(str(left_id))
        b = right_id if isinstance(right_id, uuid.UUID) else uuid.UUID(str(right_id))
    except (TypeError, ValueError):
        return None
    rows = db.query(EmotionEmbedding).filter(EmotionEmbedding.work_id.in_([a, b])).all()
    vecs = {}
    for row in rows:
        if row.embedding is None:
            continue
        vecs[row.work_id] = list(row.embedding) if not isinstance(row.embedding, list) else row.embedding
    if a not in vecs or b not in vecs:
        return None
    return 1.0 - _cosine_similarity(vecs[a], vecs[b])


def works_too_close(db: Session, seed: Work | None, other: Work | None, *, threshold: float = 0.15) -> bool:
    if not seed or not other:
        return False
    emb = embedding_distance(db, seed.id, other.id)
    if emb is not None:
        return emb < threshold
    return av_distance(seed, other) < threshold


def remelt_av_nudge(index: int) -> dict:
    """First remelt must clear the too-close band on the 1–9 AV plane."""
    step = 1.6 * max(1, index)
    return {"arousal": step, "valence": -step * 0.5}


def remelt_record(parent: Work | None, child: Work | None, offset: dict | None = None) -> dict:
    record: dict = {"explain": "av_distance", "offset": offset}
    if parent is None or child is None:
        return record
    dist = av_distance(parent, child)
    record["distance"] = round(dist, 3)
    record["too_close"] = dist < 0.15
    return record
