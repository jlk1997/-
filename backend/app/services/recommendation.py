import math
import uuid
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.schemas import EmotionEmbedding, Follow, Post, User, UserPreference, Work, WorkEngagementStats


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def get_user_preference_vector(db: Session, user_id) -> tuple[list[str], list[str], Optional[list[float]]]:
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    moods = pref.mood_tags if pref and pref.mood_tags else []
    genres = pref.genre_tags if pref and pref.genre_tags else []

    user_works = db.query(Work.id).filter(Work.owner_id == user_id).order_by(Work.created_at.desc()).limit(5).all()
    work_ids = [row[0] for row in user_works]
    if not work_ids:
        return moods, genres, None

    embs = (
        db.query(EmotionEmbedding)
        .filter(EmotionEmbedding.work_id.in_(work_ids))
        .all()
    )
    embeddings = []
    for emb in embs:
        if emb.embedding is not None:
            vec = list(emb.embedding) if not isinstance(emb.embedding, list) else emb.embedding
            embeddings.append(vec)

    avg_emb = None
    if embeddings:
        dim = len(embeddings[0])
        avg_emb = [sum(e[i] for e in embeddings) / len(embeddings) for i in range(dim)]
    return moods, genres, avg_emb


def _preload_heats(db: Session, posts: list[Post]) -> dict:
    work_ids = list({p.work_id for p in posts})
    heats: dict = {}
    if not work_ids:
        return heats
    stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id.in_(work_ids)).all()
    for row in stats:
        heats[row.work_id] = float(row.listen_completes or 0) * 0.4
    return heats


def _preload_personalization(
    db: Session,
    posts: list[Post],
    user: User,
) -> tuple[dict, dict, list[str], list[str], Optional[list[float]], set]:
    work_ids = list({p.work_id for p in posts})
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()}

    moods, genres, user_emb = get_user_preference_vector(db, user.id)

    following_rows = db.query(Follow.following_id).filter(Follow.follower_id == user.id).all()
    following_ids = {row[0] for row in following_rows}

    work_embs: dict = {}
    if user_emb and work_ids:
        rows = db.query(EmotionEmbedding).filter(EmotionEmbedding.work_id.in_(work_ids)).all()
        for row in rows:
            if row.embedding is not None:
                work_embs[row.work_id] = list(row.embedding) if not isinstance(row.embedding, list) else row.embedding

    heats: dict = {}
    if work_ids:
        stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id.in_(work_ids)).all()
        for row in stats:
            heats[row.work_id] = float(row.listen_completes or 0) * 0.4 + float(getattr(row, "like_count", 0) or 0) * 0.3

    return works, work_embs, moods, genres, user_emb, following_ids, heats


def _score_with_context(
    post: Post,
    works: dict,
    work_embs: dict,
    moods: list[str],
    genres: list[str],
    user_emb: Optional[list[float]],
    following_ids: set,
    heats: dict | None = None,
) -> float:
    score = float(post.like_count) * 2 + float(post.comment_count)
    work = works.get(post.work_id)
    if not work:
        return score

    if moods and work.moods:
        score += len(set(moods) & set(work.moods)) * 5
    if genres and work.genres:
        score += len(set(genres) & set(work.genres)) * 3

    if user_emb:
        vec = work_embs.get(work.id)
        if vec:
            score += _cosine_similarity(user_emb, vec) * 28

    heat = (heats or {}).get(work.id, 0.0)
    score += min(heat, 40)

    if post.author_id in following_ids:
        score += 15

    return score


def explain_post_recommendation(
    post: Post,
    work: Work,
    *,
    moods: list[str],
    genres: list[str],
    following_ids: set,
    work_embs: dict,
    user_emb: Optional[list[float]],
    heats: dict | None = None,
) -> str | None:
    """Return a machine-readable reason code for personalized feed chips."""
    if post.author_id in following_ids:
        return "following"
    if user_emb:
        vec = work_embs.get(work.id)
        if vec and _cosine_similarity(user_emb, vec) > 0.45:
            return "similar_taste"
    if moods and work.moods:
        overlap = sorted(set(moods) & set(work.moods))
        if overlap:
            return f"mood:{overlap[0]}"
    if genres and work.genres:
        overlap = sorted(set(genres) & set(work.genres))
        if overlap:
            return f"genre:{overlap[0]}"
    if (heats or {}).get(work.id, 0.0) >= 4:
        return "heat"
    return None


def rank_posts(db: Session, posts: list[Post], user: User | None, sort: str = "personalized") -> list[Post]:
    ranked, _ctx = rank_posts_with_context(db, posts, user, sort=sort)
    return ranked


def rank_posts_with_context(
    db: Session,
    posts: list[Post],
    user: User | None,
    sort: str = "personalized",
) -> tuple[list[Post], dict | None]:
    """Rank posts and return personalization context for recommend_reason (single DB preload)."""
    if not posts:
        return [], None

    if sort == "latest":
        return sorted(posts, key=lambda p: p.created_at, reverse=True), None
    if sort == "popular":
        heats = _preload_heats(db, posts)
        return (
            sorted(
                posts,
                key=lambda p: (heats.get(p.work_id, 0.0), float(p.like_count or 0), float(p.comment_count or 0)),
                reverse=True,
            ),
            {"heats": heats},
        )

    if sort == "following":
        if not user:
            return [], None
        _works, _embs, _moods, _genres, _emb, following_ids, _heats = _preload_personalization(db, posts, user)
        if not following_ids:
            return [], None
        filtered = [p for p in posts if p.author_id in following_ids]
        return sorted(filtered, key=lambda p: p.created_at, reverse=True), None

    if sort == "personalized" and user:
        works, work_embs, moods, genres, user_emb, following_ids, heats = _preload_personalization(db, posts, user)
        author_ids = {p.author_id for p in posts}
        feed_following = following_ids & author_ids
        ranked = sorted(
            posts,
            key=lambda p: _score_with_context(p, works, work_embs, moods, genres, user_emb, following_ids, heats),
            reverse=True,
        )
        ctx = {
            "moods": moods,
            "genres": genres,
            "user_emb": user_emb,
            "work_embs": work_embs,
            "following_ids": feed_following,
            "heats": heats,
        }
        return ranked, ctx

    if sort == "personalized":
        heats = _preload_heats(db, posts)
        ranked = sorted(
            posts,
            key=lambda p: (heats.get(p.work_id, 0.0), float(p.like_count or 0), float(p.comment_count or 0)),
            reverse=True,
        )
        return ranked, {
            "moods": [],
            "genres": [],
            "user_emb": None,
            "work_embs": {},
            "following_ids": set(),
            "heats": heats,
        }

    return sorted(posts, key=lambda p: p.created_at, reverse=True), None


def serialize_wall_item(work: Work) -> dict:
    owner = getattr(work, "owner", None)
    return {
        "id": str(work.id),
        "title": work.title or "",
        "cover_url": work.cover_url,
        "audio_url": work.audio_url,
        "moods": list(work.moods or [])[:4],
        "genres": list(work.genres or [])[:4],
        "owner_username": getattr(owner, "username", None) if owner else None,
    }


def _public_candidate_works(
    db: Session,
    *,
    exclude_id=None,
    exclude_owner_id=None,
    tenant_id: str | None = None,
    limit: int = 80,
) -> list[Work]:
    posted = db.query(Post.work_id).filter(Post.visibility == "public")
    q = db.query(Work).filter(
        Work.audio_url.isnot(None),
        Work.audio_url != "",
        or_(Work.visibility == "public", Work.id.in_(posted)),
    )
    if exclude_id is not None:
        q = q.filter(Work.id != exclude_id)
    if exclude_owner_id is not None:
        q = q.filter(Work.owner_id != exclude_owner_id)
    if tenant_id:
        q = q.filter(Work.tenant_id == tenant_id)
    return q.order_by(Work.created_at.desc()).limit(limit).all()


def score_work_similarity(
    work: Work,
    *,
    seed_emb: list[float] | None,
    seed_moods: list[str],
    seed_genres: list[str],
    work_emb: list[float] | None,
    heat: float = 0.0,
) -> float:
    score = 0.0
    if seed_emb and work_emb:
        score += _cosine_similarity(seed_emb, work_emb) * 40
    if seed_moods and work.moods:
        score += len(set(seed_moods) & set(work.moods)) * 6
    if seed_genres and work.genres:
        score += len(set(seed_genres) & set(work.genres)) * 4
    score += min(float(heat or 0), 20)
    return score


def _heat_map(db: Session, works: list[Work]) -> dict:
    if not works:
        return {}
    stats = db.query(WorkEngagementStats).filter(WorkEngagementStats.work_id.in_([w.id for w in works])).all()
    return {row.work_id: float(row.listen_completes or 0) * 0.4 for row in stats}


def _embedding_map(db: Session, works: list[Work]) -> dict:
    if not works:
        return {}
    rows = db.query(EmotionEmbedding).filter(EmotionEmbedding.work_id.in_([w.id for w in works])).all()
    out = {}
    for row in rows:
        if row.embedding is not None:
            out[row.work_id] = list(row.embedding) if not isinstance(row.embedding, list) else row.embedding
    return out


def _tenant_scope(db: Session, user: User | None) -> str | None:
    from app.services.tenant import is_multi_tenant_enabled, tenant_id_for_user

    if not is_multi_tenant_enabled(db):
        return None
    return tenant_id_for_user(user)


def list_similar_works(db: Session, work: Work, *, limit: int = 6) -> list[dict]:
    from app.services.reference_track import av_mood_embedding

    candidates = _public_candidate_works(db, exclude_id=work.id, tenant_id=getattr(work, "tenant_id", None))
    if not candidates:
        return []
    seed_row = db.query(EmotionEmbedding).filter(EmotionEmbedding.work_id == work.id).first()
    seed_emb = None
    if seed_row is not None and seed_row.embedding is not None:
        seed_emb = list(seed_row.embedding) if not isinstance(seed_row.embedding, list) else seed_row.embedding
    if seed_emb is None:
        seed_emb = av_mood_embedding(work)
    heats = _heat_map(db, candidates)
    embs = _embedding_map(db, candidates)
    seed_moods = list(work.moods or [])
    seed_genres = list(work.genres or [])
    scored = [
        (
            item,
            score_work_similarity(
                item,
                seed_emb=seed_emb,
                seed_moods=seed_moods,
                seed_genres=seed_genres,
                work_emb=embs.get(item.id),
                heat=heats.get(item.id, 0.0),
            ),
        )
        for item in candidates
    ]
    ranked = [item for item, score in sorted(scored, key=lambda row: row[1], reverse=True) if score > 0]
    return [serialize_wall_item(item) for item in ranked[: max(1, min(limit, 12))]]


def list_same_style_wall(db: Session, user: User | None = None, *, limit: int = 6) -> list[dict]:
    tenant_id = _tenant_scope(db, user)
    candidates = _public_candidate_works(
        db,
        exclude_owner_id=user.id if user else None,
        tenant_id=tenant_id,
    )
    if not candidates:
        return []
    heats = _heat_map(db, candidates)
    cap = max(1, min(limit, 12))
    if not user:
        ranked = sorted(candidates, key=lambda item: heats.get(item.id, 0.0), reverse=True)
        return [serialize_wall_item(item) for item in ranked[:cap]]
    moods, genres, user_emb = get_user_preference_vector(db, user.id)
    embs = _embedding_map(db, candidates)
    scored = [
        (
            item,
            score_work_similarity(
                item,
                seed_emb=user_emb,
                seed_moods=moods,
                seed_genres=genres,
                work_emb=embs.get(item.id),
                heat=heats.get(item.id, 0.0),
            ),
        )
        for item in candidates
    ]
    has_taste = bool(moods or genres or user_emb)
    ranked = [
        item
        for item, score in sorted(scored, key=lambda row: row[1], reverse=True)
        if (score > 0 if has_taste else True)
    ]
    return [serialize_wall_item(item) for item in ranked[:cap]]
