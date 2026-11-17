"""Park and resume one-tap releases that waited for a handed store."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import Release, User

logger = logging.getLogger(__name__)

AUTH_HOLD = "NEEDS_AUTH"


def mark_auth_hold(release: Release) -> None:
    release.error_message = AUTH_HOLD


def resume_auth_held_releases(db: Session, user: User) -> int:
    from app.models.schemas import CreatorSeat
    from app.services.distribution.catalog import connected_channel_codes, default_upload_channels
    from app.services.distribution.service import auto_submit_release

    shipped = 0
    channels = default_upload_channels(connected=connected_channel_codes(db, user))
    if channels:
        rows = (
            db.query(Release)
            .filter(
                Release.owner_id == user.id,
                Release.status.in_(("draft", "pending_license", "qc_ready")),
                Release.error_message == AUTH_HOLD,
            )
            .order_by(Release.updated_at.desc())
            .limit(8)
            .all()
        )
        for release in rows:
            try:
                auto_submit_release(db, user, str(release.id), {"consent": True})
                shipped += 1
            except HTTPException:
                continue
            except Exception:
                logger.exception("auth-hold resume failed for %s", release.id)
    from app.services.seats.service import resume_waiting_uploads

    seats = (
        db.query(CreatorSeat)
        .filter(CreatorSeat.user_id == user.id, CreatorSeat.ownership == "user")
        .all()
    )
    for seat in seats:
        try:
            shipped += resume_waiting_uploads(db, seat)
        except Exception:
            logger.exception("session resume failed after handing %s", seat.channel_code)
    return shipped
