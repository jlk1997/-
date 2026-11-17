"""Creator weekly digest notifications — factory OS, two wallets kept apart."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.schemas import ClipDrop, CreatorTip, Duel, ListenCheckin, Post, User, Work


def _week_since() -> datetime:
    return datetime.utcnow() - timedelta(days=7)


def build_creator_week_report(db: Session, user: User) -> dict:
    since = _week_since()
    my_works = db.query(Work).filter(Work.owner_id == user.id).all()
    my_work_ids = [w.id for w in my_works]
    work_listen: dict[uuid.UUID, int] = {}
    radio_completes = 0
    radio_self = 0
    if my_work_ids:
        listen_rows = (
            db.query(ListenCheckin)
            .filter(ListenCheckin.work_id.in_(my_work_ids), ListenCheckin.created_at >= since)
            .all()
        )
        for row in listen_rows:
            work_listen[row.work_id] = work_listen.get(row.work_id, 0) + 1
            if float(row.listen_ratio or 0) < 0.8:
                continue
            if row.user_id == user.id:
                radio_self += 1
            else:
                radio_completes += 1

    listens = sum(work_listen.values())
    tips = 0
    if my_work_ids:
        tips = int(
            db.query(func.coalesce(func.sum(CreatorTip.credits), 0))
            .filter(CreatorTip.work_id.in_(my_work_ids), CreatorTip.created_at >= since)
            .scalar()
            or 0
        )
    published = db.query(Post).filter(Post.author_id == user.id, Post.created_at >= since).count()
    remix_count = 0
    if my_work_ids:
        remix_count = (
            db.query(Work)
            .filter(Work.parent_work_id.in_(my_work_ids), Work.created_at >= since)
            .count()
        )
    duel_mentions = (
        db.query(Duel)
        .filter(
            Duel.created_at >= since,
            (Duel.challenger_id == user.id) | (Duel.opponent_id == user.id),
        )
        .count()
    )
    clip_drops = 0
    try:
        clip_drops = db.query(ClipDrop).filter(ClipDrop.owner_id == user.id, ClipDrop.created_at >= since).count()
    except Exception:
        db.rollback()
        clip_drops = 0
    suggestions = []
    week_drop = None
    try:
        from app.services.distribution.automation import weekly_release_suggestions
        from app.services.emotion_calendar import week_drop_plan

        suggestions = weekly_release_suggestions(db, user, limit=3)
        week_drop = week_drop_plan(db, user)
    except Exception:
        suggestions = []
        week_drop = None

    from app.services.royalty.payout_calendar import payout_calendar
    from app.services.royalty.wallet import source_split

    calendar = payout_calendar()
    split = source_split(db, user)
    top = suggestions[0]["title"] if suggestions else ""
    drop_title = ((week_drop or {}).get("work") or {}).get("title") or top
    drop_station = (week_drop or {}).get("station_name") or ""
    message = (
        f"本周他人有效完播 {radio_completes} 次（发现预热展示，0 可提现），"
        f"自听 {radio_self} 次只展示；打赏 {tips} 额度（积分钱包，不加法币）；"
        f"发现预热展示 {int(split.get('radio_minor') or 0)}（不可提现） / "
        f"同步 {int(split.get('sync_minor') or 0)} / "
        f"嵌入 {int(split.get('embed_minor') or 0)} / "
        f"店端收割 {int(split.get('dsp_minor') or 0)} 分（可结算）"
    )
    if drop_title:
        message += f"；建议先试投「{drop_title}」"
        if drop_station:
            message += f"到{drop_station}"
    if calendar.get("is_payout_day"):
        message += f"。今天是周五申请提现日 {calendar.get('next_payout_date')}，不会自动打款"
    elif calendar.get("next_payout_date"):
        days = calendar.get("days_until_payout")
        message += f"。距周五申请日还有 {days} 天（{calendar['next_payout_date']}）"

    return {
        "listens": listens,
        "tips": tips,
        "published": published,
        "remixes": remix_count,
        "duel_mentions": duel_mentions,
        "unpublished_ready": len(suggestions),
        "release_suggestions": suggestions,
        "radio_completes": radio_completes,
        "radio_self_completes": radio_self,
        "radio_minor_display": int(split.get("radio_minor") or 0),
        "clip_drops": clip_drops,
        "week_drop": week_drop,
        "payout_calendar": calendar,
        "wallet_split": {
            "credits_tips": tips,
            "radio_minor": split.get("radio_minor") or 0,
            "sync_minor": split.get("sync_minor") or 0,
            "embed_minor": split.get("embed_minor") or 0,
            "dsp_minor": split.get("dsp_minor") or 0,
            "harvest_minor": split.get("harvest_minor") or 0,
        },
        "message": message,
        "meaningful": bool(
            radio_completes
            or listens >= 3
            or tips
            or published
            or remix_count
            or clip_drops
            or suggestions
        ),
    }


def _collect_digest_user_ids(db: Session, since: datetime) -> set[uuid.UUID]:
    owner_ids: set[uuid.UUID] = set()
    listen_rows = (
        db.query(ListenCheckin.work_id, func.count(ListenCheckin.id))
        .filter(ListenCheckin.created_at >= since)
        .group_by(ListenCheckin.work_id)
        .all()
    )
    work_listen = {wid: int(cnt) for wid, cnt in listen_rows}
    if work_listen:
        works = db.query(Work.id, Work.owner_id).filter(Work.id.in_(work_listen.keys())).all()
        for wid, owner_id in works:
            if owner_id and work_listen.get(wid, 0) >= 3:
                owner_ids.add(owner_id)
    tip_owners = (
        db.query(Work.owner_id)
        .join(CreatorTip, CreatorTip.work_id == Work.id)
        .filter(CreatorTip.created_at >= since)
        .distinct()
        .all()
    )
    for (oid,) in tip_owners:
        if oid:
            owner_ids.add(oid)
    duel_users = db.query(Duel.challenger_id, Duel.opponent_id).filter(Duel.created_at >= since).all()
    for challenger_id, opponent_id in duel_users:
        if challenger_id:
            owner_ids.add(challenger_id)
        if opponent_id:
            owner_ids.add(opponent_id)
    try:
        clip_owners = db.query(ClipDrop.owner_id).filter(ClipDrop.created_at >= since).distinct().all()
        for (oid,) in clip_owners:
            if oid:
                owner_ids.add(oid)
    except Exception:
        db.rollback()
    return owner_ids


def send_creator_weekly_digests(db: Session) -> int:
    """Notify creators with meaningful activity in the past 7 days."""
    since = _week_since()
    sent = 0
    owner_ids = _collect_digest_user_ids(db, since)

    from app.services.notifications import create_notification

    for uid in owner_ids:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            continue
        report = build_creator_week_report(db, user)
        if not report.get("meaningful"):
            continue
        create_notification(
            db,
            uid,
            "creator_weekly",
            {
                "listens": report["listens"],
                "tips": report["tips"],
                "published": report["published"],
                "remixes": report["remixes"],
                "radio_completes": report["radio_completes"],
                "radio_self_completes": report["radio_self_completes"],
                "clip_drops": report["clip_drops"],
                "release_suggestions": report["release_suggestions"],
                "week_drop": report["week_drop"],
                "payout_calendar": report["payout_calendar"],
                "wallet_split": report["wallet_split"],
                "message": report["message"],
            },
        )
        try:
            from app.services.wechat_subscribe import try_notify_creator_weekly

            try_notify_creator_weekly(
                db,
                uid,
                message=f"完播{report['radio_completes']}·打赏{report['tips']}额度",
            )
        except Exception:
            pass
        sent += 1
    return sent


def get_creator_weekly_summary(db: Session, user_id: uuid.UUID) -> dict:
    """Return creator activity stats for the past 7 days (same metrics as weekly digest)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {
            "listens": 0,
            "tips": 0,
            "published": 0,
            "remixes": 0,
            "duel_mentions": 0,
            "unpublished_ready": 0,
            "release_suggestions": [],
            "radio_completes": 0,
            "radio_self_completes": 0,
            "clip_drops": 0,
        }
    report = build_creator_week_report(db, user)
    return {k: v for k, v in report.items() if k != "meaningful"}
