"""Educational export for collection societies. We are not a CMO."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.schemas import Release, ReleaseMetadata, User, Work
from app.services.distribution.passport import live_store_count


def export_collection_society_rows(db: Session, user: User) -> dict:
    works = db.query(Work).filter(Work.owner_id == user.id).order_by(Work.created_at.desc()).limit(200).all()
    rows = []
    for work in works:
        release = (
            db.query(Release)
            .filter(Release.work_id == work.id)
            .order_by(Release.updated_at.desc())
            .first()
        )
        meta = (
            db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
            if release
            else None
        )
        rows.append(
            {
                "title": (meta.title if meta else None) or work.title,
                "artist": (meta.artist_name if meta else None) or user.display_name or user.username,
                "isrc": (meta.isrc if meta else None) or work.isrc,
                "upc": meta.upc if meta else None,
                "live_stores": live_store_count(db, work.id),
                "commercial": bool(work.commercial_cleared_at),
                "ai_generated": bool(work.is_ai_generated),
            }
        )
    csv_lines = ["title,artist,isrc,upc,live_stores,commercial,ai_generated"]
    for row in rows:
        csv_lines.append(
            ",".join(
                [
                    _csv(row["title"]),
                    _csv(row["artist"]),
                    _csv(row["isrc"]),
                    _csv(row["upc"]),
                    str(row["live_stores"]),
                    "yes" if row["commercial"] else "no",
                    "yes" if row["ai_generated"] else "no",
                ]
            )
        )
    return {
        "note": "education_only_not_a_collection_society",
        "rows": rows,
        "csv": "\n".join(csv_lines),
    }


def _csv(value) -> str:
    text = str(value or "").replace('"', "'")
    if "," in text:
        return f'"{text}"'
    return text
