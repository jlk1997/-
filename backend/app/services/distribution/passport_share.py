"""Share a Release Passport into first-party Feed. One post per work."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import PlatformMetricSnapshot, Post, User, Work
from app.services.distribution.catalog import channel_display_name
from app.services.distribution.passport import build_passport
from app.services.royalty.settlement import current_period
from app.services.tenant import tenant_id_for_user


def _fen_label(amount_minor: int, currency: str = "CNY") -> str:
    currency = (currency or "CNY").upper()
    yuan = (amount_minor or 0) / 100
    if currency == "USD":
        return f"${yuan:.2f}"
    return f"¥{yuan:.2f}"


def build_feed_caption(
    *,
    share_line: str,
    store_names: list[str] | None = None,
    period_net_minor: int = 0,
    currency: str = "CNY",
) -> str:
    parts = [share_line.strip()] if share_line and share_line.strip() else []
    names = [name for name in (store_names or []) if name]
    if names:
        parts.append(" / ".join(names[:6]))
    if period_net_minor > 0:
        parts.append(f"本账期可结算净额 {_fen_label(period_net_minor, currency)}（不含积分打赏）")
    return " · ".join(parts)


def period_net_for_work(db: Session, user: User, work: Work) -> tuple[int, str]:
    period_key, _, _ = current_period(db)
    rows = (
        db.query(PlatformMetricSnapshot)
        .filter(
            PlatformMetricSnapshot.user_id == user.id,
            PlatformMetricSnapshot.work_id == work.id,
            PlatformMetricSnapshot.period_key == period_key,
            PlatformMetricSnapshot.usable_for_settlement.is_(True),
        )
        .all()
    )
    total = 0
    currency = "CNY"
    for row in rows:
        total += int(row.revenue_minor or 0)
        if row.currency:
            currency = str(row.currency).upper()
    return total, currency


def share_passport_to_feed(db: Session, user: User, work_id: str) -> dict:
    import uuid

    try:
        wid = uuid.UUID(str(work_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")

    passport = build_passport(db, work_id=str(work.id))
    live_names = [
        row.get("name") or channel_display_name(row.get("channel_code"))
        for row in (passport.get("stores") or [])
        if row.get("status") == "live"
    ]
    net_minor, currency = period_net_for_work(db, user, work)
    caption = build_feed_caption(
        share_line=str(passport.get("share_line") or ""),
        store_names=live_names,
        period_net_minor=net_minor,
        currency=currency,
    )
    if not caption:
        raise HTTPException(400, "Passport caption is empty")

    from app.services.content_moderation import moderate_publish_content

    moderate_publish_content(caption, work_title=work.title, db=db)

    tags = ["passport", "release"]
    existing = db.query(Post).filter(Post.work_id == work.id, Post.author_id == user.id).first()
    created = existing is None
    if existing:
        existing.caption = caption
        merged = list(existing.tags or [])
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
        existing.tags = merged
        existing.visibility = "public"
        post = existing
    else:
        post = Post(
            author_id=user.id,
            work_id=work.id,
            caption=caption,
            tags=tags,
            visibility="public",
            tenant_id=tenant_id_for_user(user),
            consent_at=datetime.utcnow(),
        )
        db.add(post)
    work.visibility = "public"
    db.commit()
    db.refresh(post)
    from app.services.cache import cache_clear

    cache_clear("feed:")
    cache_clear("rising_creators:")
    return {
        "post_id": str(post.id),
        "work_id": str(work.id),
        "caption": post.caption,
        "created": created,
        "updated": not created,
        "period_net_minor": net_minor,
        "currency": currency,
        "share_line": passport.get("share_line"),
    }
