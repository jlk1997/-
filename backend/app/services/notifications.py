"""In-app notifications."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.schemas import Notification

logger = logging.getLogger(__name__)


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    ntype: str,
    payload: dict,
    *,
    commit: bool = True,
) -> Notification:
    n = Notification(user_id=user_id, type=ntype, payload=payload)
    db.add(n)
    if commit:
        db.commit()
        db.refresh(n)
    else:
        db.flush()
    return n


def notify_remix_done(
    db: Session,
    source_owner_id: uuid.UUID,
    remixer_id: uuid.UUID,
    source_work_id: str,
    new_work_id: str,
    remixer_username: str,
):
    if source_owner_id == remixer_id:
        return
    create_notification(
        db,
        source_owner_id,
        "remix_done",
        {
            "source_work_id": source_work_id,
            "new_work_id": new_work_id,
            "remixer_username": remixer_username,
            "message": f"@{remixer_username} 二次创作了你的作品",
        },
    )


def notify_new_follower(
    db: Session,
    following_id: uuid.UUID,
    follower_username: str,
):
    create_notification(
        db,
        following_id,
        "new_follower",
        {
            "follower_username": follower_username,
            "message": f"@{follower_username} 关注了你",
        },
    )


def notify_post_liked(
    db: Session,
    *,
    author_id: uuid.UUID,
    liker_id: uuid.UUID,
    liker_username: str,
    post_id: str,
    work_id: str,
    work_title: str,
):
    if author_id == liker_id:
        return
    create_notification(
        db,
        author_id,
        "post_liked",
        {
            "post_id": post_id,
            "work_id": work_id,
            "work_title": work_title,
            "liker_username": liker_username,
            "message": f"@{liker_username} 赞了你的作品「{work_title}」",
        },
    )


def notify_post_commented(
    db: Session,
    *,
    author_id: uuid.UUID,
    commenter_id: uuid.UUID,
    commenter_username: str,
    post_id: str,
    work_id: str,
    work_title: str,
    preview: str,
):
    if author_id == commenter_id:
        return
    snippet = preview[:80] + ("…" if len(preview) > 80 else "")
    create_notification(
        db,
        author_id,
        "post_commented",
        {
            "post_id": post_id,
            "work_id": work_id,
            "work_title": work_title,
            "commenter_username": commenter_username,
            "preview": snippet,
            "message": f"@{commenter_username} 评论：{snippet}",
        },
    )


def build_job_notify_payload(
    *,
    job_id: str,
    job_type: str,
    work_id: str | None,
    config: dict,
    result: dict,
    message: str,
) -> dict:
    """Shared completed/failed payload so taps can reopen the MixGraph session."""
    cfg = config or {}
    res = result or {}
    source_work_id = cfg.get("source_work_id") or cfg.get("seed_work_id")
    session_id = cfg.get("workbench_session_id") or cfg.get("session_id")
    payload: dict = {
        "job_id": job_id,
        "job_type": job_type,
        "message": message,
    }
    if work_id:
        payload["work_id"] = str(work_id)
    if source_work_id:
        payload["source_work_id"] = str(source_work_id)
    if session_id:
        payload["workbench_session_id"] = str(session_id)
    parent = res.get("parent_work_id")
    if parent:
        payload["parent_work_id"] = str(parent)
    if job_type == "workbench_render" or session_id:
        payload["remix_intent"] = "workbench"
    return payload


def notify_job_terminal(
    db: Session,
    job,
) -> None:
    """In-app notification when a generation job finishes."""
    from app.models.schemas import GenerationJob

    if not isinstance(job, GenerationJob):
        return

    config = job.config or {}
    result = job.result or {}
    title = config.get("title") or "你的作品"

    if job.status == "completed":
        if job.job_type == "playlist":
            playlist_id = result.get("playlist_id") or (
                str(job.playlist_id) if job.playlist_id else None
            )
            create_notification(
                db,
                job.owner_id,
                "job_completed",
                {
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "playlist_id": playlist_id,
                    "message": f"心情歌单「{title}」生成完成，可以开始转换收听了",
                },
            )
            return

        work_ids = result.get("work_ids") or []
        work_id = result.get("work_id") or (work_ids[0] if work_ids else None)
        cfg = job.config or {}
        if job.job_type == "workbench_render":
            done_msg = f"「{title}」新母带已打成，仍是一首立体声"
        elif cfg.get("workbench_session_id") or cfg.get("session_id"):
            done_msg = f"「{title}」会话内再生成完成"
        else:
            done_msg = f"「{title}」生成完成"
        create_notification(
            db,
            job.owner_id,
            "job_completed",
            build_job_notify_payload(
                job_id=str(job.id),
                job_type=job.job_type,
                work_id=work_id,
                config=cfg,
                result=result,
                message=done_msg,
            ),
        )
        return

    if job.status in ("failed", "cancelled"):
        detail = job.error_message or ("已取消" if job.status == "cancelled" else "未知错误")
        create_notification(
            db,
            job.owner_id,
            "job_failed",
            build_job_notify_payload(
                job_id=str(job.id),
                job_type=job.job_type,
                work_id=(result or {}).get("work_id"),
                config=job.config or {},
                result=result,
                message=f"生成失败：{detail}",
            ),
        )


def list_notifications(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not n:
        return False
    n.read_at = datetime.utcnow()
    db.commit()
    return True


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({Notification.read_at: datetime.utcnow()})
    )
    db.commit()
    return count


def notify_mention(
    db: Session,
    mentioned_id: uuid.UUID,
    *,
    commenter_username: str,
    post_id: str,
    work_id: str,
    preview: str,
):
    snippet = preview[:60] + ("…" if len(preview) > 60 else "")
    create_notification(
        db,
        mentioned_id,
        "mention",
        {
            "post_id": post_id,
            "work_id": work_id,
            "commenter_username": commenter_username,
            "preview": snippet,
            "message": f"@{commenter_username} 在评论中提到了你",
        },
    )


def notify_duel_invite(
    db: Session,
    opponent_id: uuid.UUID,
    *,
    challenger_username: str,
    duel_id: str,
):
    create_notification(
        db,
        opponent_id,
        "duel_invite",
        {
            "duel_id": duel_id,
            "challenger_username": challenger_username,
            "message": f"@{challenger_username} 向你发起了情绪决斗",
        },
    )


def notify_duel_accepted(
    db: Session,
    challenger_id: uuid.UUID,
    *,
    opponent_username: str,
    duel_id: str,
):
    create_notification(
        db,
        challenger_id,
        "duel_accepted",
        {
            "duel_id": duel_id,
            "opponent_username": opponent_username,
            "message": f"@{opponent_username} 接受了你的决斗挑战",
        },
    )


def notify_duel_result(db: Session, duel) -> None:
    if not getattr(duel, "id", None):
        return
    for uid in (duel.challenger_id, duel.opponent_id):
        if not uid:
            continue
        won = duel.winner_id == uid
        draw = duel.status == "draw"
        if draw:
            msg = "情绪决斗平局，双方获得参与奖"
        elif won:
            msg = "恭喜，你在情绪决斗中获胜！"
        else:
            msg = "情绪决斗已结束，下次再接再厉"
        winner_work_id = None
        if duel.winner_id == duel.challenger_id:
            winner_work_id = str(duel.challenger_work_id) if duel.challenger_work_id else None
        elif duel.winner_id == duel.opponent_id:
            winner_work_id = str(duel.opponent_work_id) if duel.opponent_work_id else None
        create_notification(
            db,
            uid,
            "duel_result",
            {
                "duel_id": str(duel.id),
                "winner_id": str(duel.winner_id) if duel.winner_id else None,
                "work_id": winner_work_id,
                "won": won,
                "status": duel.status,
                "message": msg,
            },
        )


def notify_tip_received(
    db: Session,
    creator_id: uuid.UUID,
    *,
    tipper_username: str,
    work_id: str,
    work_title: str,
    credits: int,
    public_message: str | None = None,
):
    payload = {
        "work_id": work_id,
        "work_title": work_title,
        "tipper_username": tipper_username,
        "credits": credits,
        "message": f"@{tipper_username} 打赏了你的作品「{work_title}」{credits} 额度",
    }
    if public_message:
        payload["public_message"] = public_message
    create_notification(db, creator_id, "tip_received", payload)


def notify_challenge_award(
    db: Session,
    user_id: uuid.UUID,
    *,
    challenge_title: str,
    rank: int,
    credits: int,
    work_title: str,
    work_id: str | None = None,
    challenge_slug: str | None = None,
):
    payload = {
        "challenge_title": challenge_title,
        "rank": rank,
        "credits": credits,
        "work_title": work_title,
        "message": f"挑战「{challenge_title}」第 {rank} 名，获得 {credits} 额度",
    }
    if work_id:
        payload["work_id"] = work_id
    if challenge_slug:
        payload["challenge_slug"] = challenge_slug
    create_notification(db, user_id, "challenge_award", payload)


def radio_settled_notified_today(payloads: list, work_id: str) -> bool:
    wid = str(work_id)
    return any(str((row or {}).get("work_id") or "") == wid for row in payloads)


def notify_radio_listen_settled(
    db: Session,
    creator_id: uuid.UUID,
    *,
    work_id: str,
    work_title: str,
    payout_minor: int,
    listener_username: str = "",
    station: str | None = None,
    commit: bool = False,
) -> None:
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Notification.payload)
        .filter(
            Notification.user_id == creator_id,
            Notification.type == "radio_listen_settled",
            Notification.created_at >= since,
        )
        .limit(40)
        .all()
    )
    if radio_settled_notified_today([row[0] for row in rows], work_id):
        return
    title = work_title or work_id
    payload: dict = {
        "work_id": work_id,
        "work_title": title,
        "payout_minor": payout_minor,
        "listener_username": listener_username,
        "message": f"有人听完了「{title}」，电台记了一次完播（发现预热展示，不可提现）",
    }
    if station:
        payload["station"] = station
    create_notification(db, creator_id, "radio_listen_settled", payload, commit=commit)


def _dedupe_exists(db: Session, user_id: uuid.UUID, ntype: str, dedupe_key: str | None) -> bool:
    """Check if a notification with the same type + dedupe context exists within the last hour."""
    if not dedupe_key:
        return False
    cutoff = datetime.utcnow() - timedelta(hours=1)
    from sqlalchemy import cast, String
    existing = (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.type == ntype,
            Notification.created_at >= cutoff,
            cast(Notification.payload["dedupe_key"], String) == dedupe_key,
        )
        .first()
    )
    return existing is not None


_FANOUT_TASKS: set = set()
LAST_FANOUT: dict[str, dict] = {}


def _track_fanout(task, *, event_type: str, user_id: str) -> None:
    """Keep a live reference so the task is not GC'd, and log the outcome."""
    _FANOUT_TASKS.add(task)

    def _done(done) -> None:
        _FANOUT_TASKS.discard(done)
        if done.cancelled():
            logger.warning("key event fanout cancelled event=%s user=%s", event_type, user_id)
            LAST_FANOUT[user_id] = {"event": event_type, "ok": False, "reason": "cancelled"}
            return
        exc = done.exception()
        if exc:
            logger.exception("key event fanout failed event=%s user=%s", event_type, user_id)
            LAST_FANOUT[user_id] = {"event": event_type, "ok": False, "reason": str(exc)[:200]}
            return
        result = done.result()
        logger.info("key event fanout ok event=%s user=%s result=%s", event_type, user_id, result)
        LAST_FANOUT[user_id] = {"event": event_type, "ok": True, "result": result}

    task.add_done_callback(_done)


def notify_key_event_sync(
    db: Session,
    user_id: uuid.UUID,
    event_type: str,
    *,
    title: str,
    body: str,
    data: dict | None = None,
    skip_in_app: bool = False,
) -> dict[str, bool]:
    """Sync wrapper for wallet/settlement paths. External fanout uses a fresh session if a loop is running."""
    import asyncio

    async def _fresh_external() -> dict[str, bool]:
        from app.database import SessionLocal

        session = SessionLocal()
        try:
            return await _fanout_external(session, user_id, event_type, title=title, body=body)
        finally:
            session.close()

    ref = (data or {}).get("ref")
    dedupe_key = f"{event_type}:{ref}" if ref else None
    if dedupe_key and _dedupe_exists(db, user_id, event_type, dedupe_key):
        return {"in_app": False, "wechat": False, "email": False}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        if skip_in_app:
            return asyncio.run(_fresh_external())
        return asyncio.run(
            notify_key_event(db, user_id, event_type, title=title, body=body, data=data)
        )
    if not skip_in_app:
        create_notification(
            db,
            user_id,
            event_type,
            {"title": title, "body": body, **({"dedupe_key": dedupe_key} if dedupe_key else {}), **(data or {})},
            commit=False,
        )
    try:
        task = loop.create_task(_fresh_external())
        _track_fanout(task, event_type=event_type, user_id=str(user_id))
    except Exception:
        logger.exception("key event fanout schedule failed event=%s user=%s", event_type, user_id)
        LAST_FANOUT[str(user_id)] = {"event": event_type, "ok": False, "reason": "schedule_failed"}
    return {"in_app": not skip_in_app, "wechat": False, "email": False, "queued": True}


async def _fanout_external(db: Session, user_id: uuid.UUID, event_type: str, *, title: str, body: str) -> dict[str, bool]:
    from app.models.schemas import User
    from app.services.notify_prefs import get_notify_prefs

    results = {"in_app": False, "wechat": False, "email": False}
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return results
    prefs = get_notify_prefs(db, user_id)
    if prefs.get("wechat", True):
        try:
            from app.models.schemas import WeChatUser
            from app.services.wechat_subscribe import try_notify_event

            wx = db.query(WeChatUser).filter(WeChatUser.user_id == user_id).first()
            if wx and wx.openid:
                results["wechat"] = try_notify_event(wx.openid, event_type, title, body)
        except Exception:
            pass
    if prefs.get("email", True) and user.email and "@" in user.email:
        try:
            from app.services.email_notify import send_email

            results["email"] = await send_email(user.email, title, f"<h3>{title}</h3><p>{body}</p>")
        except Exception:
            pass
    return results


async def notify_key_event(
    db: Session,
    user_id: uuid.UUID,
    event_type: str,
    *,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict[str, bool]:
    """Three-channel notification with fallback: in-app → WeChat → email."""
    from app.models.schemas import User

    results: dict[str, bool] = {"in_app": False, "wechat": False, "email": False}

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return results

    from app.services.notify_prefs import get_notify_prefs

    prefs = get_notify_prefs(db, user_id)
    if event_type.startswith("recall_") and not prefs.get("recall", True):
        return results

    ref = (data or {}).get("ref")
    dedupe_key = f"{event_type}:{ref}" if ref else None
    if dedupe_key and _dedupe_exists(db, user_id, event_type, dedupe_key):
        return results

    # 1. In-app notification (always unless opted out)
    if prefs.get("in_app", True):
        try:
            create_notification(
                db,
                user_id,
                event_type,
                {"title": title, "body": body, **({"dedupe_key": dedupe_key} if dedupe_key else {}), **(data or {})},
            )
            results["in_app"] = True
        except Exception:
            pass

    # 2. WeChat subscribe (if openid available)
    if prefs.get("wechat", True):
        try:
            from app.services.wechat_subscribe import try_notify_event
            from app.models.schemas import WeChatUser

            wx = db.query(WeChatUser).filter(WeChatUser.user_id == user_id).first()
            if wx and wx.openid:
                results["wechat"] = try_notify_event(wx.openid, event_type, title, body)
        except Exception:
            pass

    # 3. Email (if email available)
    if prefs.get("email", True):
        try:
            if user.email and "@" in user.email:
                from app.services.email_notify import send_email

                html = f"<h3>{title}</h3><p>{body}</p>"
                results["email"] = await send_email(user.email, title, html)
        except Exception:
            pass

    return results


def notify_challenge_ending(
    db: Session,
    user_id: uuid.UUID,
    *,
    challenge_slug: str,
    challenge_title: str,
    hours_left: int,
):
    create_notification(
        db,
        user_id,
        "challenge_ending",
        {
            "challenge_slug": challenge_slug,
            "challenge_title": challenge_title,
            "hours_left": hours_left,
            "message": f"挑战「{challenge_title}」将在约 {hours_left} 小时后结束，抓紧拉票吧",
        },
    )
