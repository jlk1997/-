"""Reuse official identity bindings. Never invent an upload API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.schemas import CreatorIdentityBinding, DistributionDelivery, Release, ReleaseMetadata, Work

logger = logging.getLogger(__name__)

CHANNEL_PROVIDERS = {
    "youtube_music": "youtube",
    "soundcloud": "soundcloud",
}
MATCH_COOLDOWN = timedelta(minutes=20)


def list_owner_bindings(db: Session, user_id) -> list[dict]:
    rows = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user_id)
        .all()
    )
    return [
        {
            "provider": row.provider,
            "bound": row.status == "active",
            "has_token": bool(row.official_token),
            "external_release_id": row.external_release_id,
        }
        for row in rows
    ]


def _title_for(db: Session, delivery: DistributionDelivery, release: Release | None) -> str:
    meta = None
    if release:
        meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    work = db.query(Work).filter(Work.id == delivery.work_id).first()
    return ((meta.title if meta else None) or (work.title if work else None) or "").strip()


def _mark_attempt(delivery: DistributionDelivery) -> bool:
    meta = dict(delivery.attempt_meta or {})
    raw = meta.get("direct_match_at")
    if raw:
        try:
            if datetime.fromisoformat(str(raw)) > datetime.utcnow() - MATCH_COOLDOWN:
                return False
        except ValueError:
            pass
    meta["direct_match_at"] = datetime.utcnow().isoformat()
    delivery.attempt_meta = meta
    return True


def _autolive(db: Session, delivery: DistributionDelivery, *, store_url: str, external_id: str | None, source: str) -> bool:
    from app.services.distribution.catalog import has_live_receipt, is_known_upload_portal, looks_like_store_page

    if not store_url:
        return False
    if is_known_upload_portal(store_url):
        return False
    if not has_live_receipt(store_url=store_url, external_id=external_id, channel_code=delivery.channel_code):
        return False
    if not (external_id or looks_like_store_page(store_url, delivery.channel_code)):
        return False
    previous = delivery.status
    delivery.store_url = store_url[:512]
    if external_id:
        delivery.external_id = str(external_id)[:128]
    delivery.status = "live"
    delivery.last_error = None
    delivery.reject_reason = None
    meta = dict(delivery.attempt_meta or {})
    meta["direct_match"] = source
    delivery.attempt_meta = meta
    if previous != "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, delivery)
    return True


def _match_youtube(db: Session, delivery: DistributionDelivery, release: Release | None) -> bool:
    from app.services.royalty import youtube

    if not youtube.configured():
        return False
    row = (
        db.query(CreatorIdentityBinding)
        .filter(
            CreatorIdentityBinding.user_id == delivery.owner_id,
            CreatorIdentityBinding.provider == "youtube",
            CreatorIdentityBinding.status == "active",
        )
        .first()
    )
    if not row or not row.official_token:
        return False
    token = youtube._access_token_for(db, row)
    if not token:
        return False
    title = _title_for(db, delivery, release)
    if not title:
        return False
    needle = youtube.normalize_title(title)
    videos = youtube._list_mine_videos(token)
    exact = [item for item in videos if youtube.normalize_title(item.get("title") or "") == needle]
    video = exact[0] if len(exact) == 1 else None
    if not video:
        contained = [
            item
            for item in videos
            if needle and needle in youtube.normalize_title(item.get("title") or "")
        ]
        video = contained[0] if len(contained) == 1 else None
    if not video:
        return False
    return _autolive(
        db,
        delivery,
        store_url=f"https://www.youtube.com/watch?v={video['id']}",
        external_id=video["id"],
        source="youtube_oauth",
    )


def _match_bound_permalink(db: Session, delivery: DistributionDelivery, provider: str) -> bool:
    row = (
        db.query(CreatorIdentityBinding)
        .filter(
            CreatorIdentityBinding.user_id == delivery.owner_id,
            CreatorIdentityBinding.provider == provider,
            CreatorIdentityBinding.status == "active",
        )
        .first()
    )
    raw = (row.external_release_id if row else "") or ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return _autolive(db, delivery, store_url=raw, external_id=raw, source=f"{provider}_binding")
    return False


def maybe_link_direct_binding(db: Session, delivery: DistributionDelivery, release: Release | None = None) -> bool:
    """If an official binding already has the track, promote to live with a real URL."""
    if delivery.status not in {"session_wait", "session_running", "ops_queue", "awaiting_manual"}:
        return False
    if delivery.store_url:
        return False
    if not _mark_attempt(delivery):
        return False
    try:
        if delivery.channel_code == "youtube_music":
            return _match_youtube(db, delivery, release)
        if delivery.channel_code == "soundcloud":
            # A SoundCloud account binding is not a track-page receipt for this song.
            return False
    except Exception:
        logger.exception("direct match failed for %s", delivery.id)
    return False


def link_session_directs(db: Session, *, limit: int = 20) -> int:
    rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.status.in_(("session_wait", "session_running")),
            DistributionDelivery.channel_code.in_(tuple(CHANNEL_PROVIDERS)),
            DistributionDelivery.store_url.is_(None),
        )
        .limit(limit)
        .all()
    )
    linked = 0
    for row in rows:
        release = db.query(Release).filter(Release.id == row.release_id).first()
        if maybe_link_direct_binding(db, row, release):
            linked += 1
            if release:
                from app.services.distribution.pipeline import refresh_release_progress

                refresh_release_progress(db, release)
    return linked
