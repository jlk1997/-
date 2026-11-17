"""Public creator homepage as a label showcase. Display stats only."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import User, Work
from app.services.distribution.passport import live_store_counts
from app.services.royalty.sync_desk import listing_enabled


def build_profile_showcase(db: Session, user: User, *, limit: int = 6) -> dict:
    works = (
        db.query(Work)
        .filter(Work.owner_id == user.id, Work.visibility == "public")
        .order_by(Work.created_at.desc())
        .limit(50)
        .all()
    )
    counts = live_store_counts(db, [work.id for work in works])
    featured_src = []
    live_works = 0
    commercial_works = 0
    live_store_total = 0
    for work in works:
        stores = int(counts.get(work.id, counts.get(str(work.id), 0)))
        commercial = listing_enabled(work) or bool(work.commercial_cleared_at)
        if stores:
            live_works += 1
            live_store_total += stores
        if commercial:
            commercial_works += 1
        featured_src.append((stores, 1 if commercial else 0, work, stores, commercial))
    featured_src.sort(key=lambda row: (row[0], row[1]), reverse=True)
    featured = []
    for _stores, _flag, work, stores, commercial in featured_src[: max(1, min(limit, 8))]:
        featured.append(
            {
                "work_id": str(work.id),
                "title": work.title,
                "cover_url": work.cover_url,
                "live_stores": stores,
                "commercial": commercial,
                "release_status": work.release_status,
            }
        )
    return {
        "live_store_total": live_store_total,
        "live_works": live_works,
        "commercial_works": commercial_works,
        "featured": featured,
    }
