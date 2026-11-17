"""Legitimate distribution automation: QC hydrate, priority queue, SLA, release hints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, Release, ReleaseMetadata, User, UserConsentLog, Work

logger = logging.getLogger(__name__)
from app.services.distribution.catalog import clip_windows, default_upload_channels, list_portal_channels

LISTEN_HINT_COMPLETES = 8
SLA_REMIND_AFTER_HOURS = 24
SLA_ESCALATE_HOURS = 48
SLA_ESCALATE_PRIORITY = 85
AUTO_CONFIRM_MIN_CONFIDENCE = 0.9
AUTO_CONFIRM_MAX_NET_MINOR = 20000  # ¥200 — larger harvest lines stay draft for ops
AUTO_RELEASE_KEY = "auto_release_after_qc"
AUTO_RELEASE_VERSION = "2026-08-19"
PRIORITY_SCORES = {
    "challenge_winner": {1: 100, 2: 90, 3: 80},
    "duel_winner": {1: 70},
}


def _latest_auto_release_log(db: Session, user_id) -> UserConsentLog | None:
    return (
        db.query(UserConsentLog)
        .filter(UserConsentLog.user_id == user_id, UserConsentLog.consent_type == AUTO_RELEASE_KEY)
        .order_by(UserConsentLog.created_at.desc())
        .first()
    )


def has_auto_release_consent(db: Session, user_id) -> bool:
    row = _latest_auto_release_log(db, user_id)
    if row is None:
        return False
    return row.version not in {None, "", "off"}


def auto_release_status(db: Session, user: User) -> dict:
    row = _latest_auto_release_log(db, user.id)
    enabled = has_auto_release_consent(db, user.id)
    return {
        "enabled": enabled,
        "consented_at": row.created_at.isoformat() if row and enabled and row.created_at else None,
        "version": (row.version if row and enabled else AUTO_RELEASE_VERSION),
        "default_on": False,
    }


def set_auto_release_consent(db: Session, user: User, enabled: bool) -> dict:
    db.add(
        UserConsentLog(
            user_id=user.id,
            consent_type=AUTO_RELEASE_KEY,
            version=AUTO_RELEASE_VERSION if enabled else "off",
        )
    )
    db.commit()
    return auto_release_status(db, user)


def maybe_auto_submit_after_qc(db: Session, work: Work, user: User, release: Release) -> bool:
    if not (release.qc_result or {}).get("passed"):
        return False
    if work.release_status in {"queued", "delivering", "live"}:
        return False
    if not has_auto_release_consent(db, user.id):
        return False
    from app.services.distribution.service import auto_submit_release
    from app.services.notifications import create_notification

    try:
        auto_submit_release(
            db,
            user,
            str(release.id),
            {"consent": True, "mode": "label", "agreement_version": AUTO_RELEASE_VERSION},
        )
        create_notification(
            db,
            user.id,
            "release_auto_submitted",
            {
                "work_id": str(work.id),
                "release_id": str(release.id),
                "message": "已按自动发行偏好提交。连接器或运营会继续发，不是已上架。",
            },
            commit=False,
        )
        from app.services.notifications import notify_key_event_sync

        notify_key_event_sync(
            db,
            user.id,
            "release_auto_submitted",
            title="自动发行已提交",
            body="已按偏好提交。连接器或运营会继续发，不是已上架。",
            data={"work_id": str(work.id), "release_id": str(release.id), "ref": str(release.id)},
            skip_in_app=True,
        )
        try:
            from app.services.radio.network import start_radio_trial

            start_radio_trial(db, user, str(work.id), commit=False)
        except Exception:
            logger.exception("volume radio trial failed for work %s", work.id)
        db.commit()
        return True
    except Exception:
        logger.exception("standing auto-release failed for work %s", work.id)
        return False


def sweep_auto_releases(db: Session, *, limit: int = 40) -> dict:
    """QC-ready / repairable works with standing consent that missed the QC hook."""
    from sqlalchemy import or_

    works = (
        db.query(Work)
        .filter(
            or_(
                Work.release_status == "qc_ready",
                Work.release_status == "qc_failed",
            )
        )
        .order_by(Work.created_at.desc())
        .limit(200)
        .all()
    )
    scanned = 0
    submitted = 0
    repaired = 0
    for work in works:
        if submitted >= limit:
            break
        if not (work.audio_url or work.storage_key):
            continue
        if not has_auto_release_consent(db, work.owner_id):
            continue
        user = db.query(User).filter(User.id == work.owner_id).first()
        if not user:
            continue
        from app.services.distribution.release_ready import ensure_release_draft, run_release_qc

        release = ensure_release_draft(db, work, user)
        if not (release.qc_result or {}).get("passed"):
            qc = run_release_qc(db, work, release=release, user=user)
            if not qc.get("passed"):
                continue
            release.qc_result = {**qc, "hydrated": True, "source": "sweep_repair"}
            if release.status in (None, "draft"):
                release.status = "qc"
            work.release_status = "qc_ready"
            fill_release_defaults(db, release, work, user)
            repaired += 1
        scanned += 1
        if maybe_auto_submit_after_qc(db, work, user, release):
            submitted += 1
    db.commit()
    return {"scanned": scanned, "submitted": submitted, "repaired": repaired, "checked": len(works)}


def priority_score(reason: str, rank: int = 1) -> int:
    table = PRIORITY_SCORES.get(reason) or {}
    if rank in table:
        return table[rank]
    if table:
        return max(10, min(table.values()) - max(0, rank - 1) * 5)
    return 10


def release_priority_payload(work: Work | None) -> dict | None:
    if not work:
        return None
    raw = (work.post_process_status or {}).get("release_priority")
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        "reason": raw.get("reason"),
        "rank": int(raw.get("rank") or 1),
        "score": int(raw.get("score") or 0),
        "label": raw.get("label") or raw.get("reason"),
        "at": raw.get("at"),
    }


def stamp_release_priority(
    work: Work,
    *,
    reason: str,
    rank: int = 1,
    label: str | None = None,
) -> dict:
    score = priority_score(reason, rank)
    pps = dict(work.post_process_status or {})
    current = pps.get("release_priority") if isinstance(pps.get("release_priority"), dict) else {}
    if int(current.get("score") or 0) >= score:
        return current
    payload = {
        "reason": reason,
        "rank": int(rank),
        "score": score,
        "label": label or reason,
        "at": datetime.utcnow().isoformat(),
    }
    pps["release_priority"] = payload
    work.post_process_status = pps
    return payload


def copy_priority_to_deliveries(db: Session, work: Work, release: Release) -> int:
    pri = release_priority_payload(work)
    if not pri:
        return 0
    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    updated = 0
    for row in rows:
        meta = dict(row.attempt_meta or {})
        if int(meta.get("priority_score") or 0) >= int(pri.get("score") or 0):
            continue
        meta.update(
            {
                "priority_score": pri["score"],
                "priority_reason": pri.get("reason"),
                "priority_rank": pri.get("rank"),
                "priority_label": pri.get("label"),
            }
        )
        row.attempt_meta = meta
        updated += 1
    return updated


def stored_generation_qc(work: Work | None) -> dict | None:
    if not work:
        return None
    pps = work.post_process_status or {}
    stored = pps.get("release_qc_result")
    if isinstance(stored, dict) and stored:
        return stored
    if pps.get("release_qc"):
        return {
            "passed": True,
            "hydrated": True,
            "source": "post_process",
            "checks": {
                "has_audio": bool(work.audio_url or work.storage_key),
                "has_title": bool(work.title and str(work.title).strip()),
                "ai_disclosed": True,
            },
        }
    return None


def hydrate_generation_qc(release: Release, work: Work | None) -> bool:
    if (release.qc_result or {}).get("passed"):
        return False
    stored = stored_generation_qc(work)
    if not stored or not stored.get("passed"):
        return False
    release.qc_result = {**stored, "hydrated": True}
    if release.status in (None, "draft"):
        release.status = "qc"
    if work and (not work.release_status or work.release_status in {"qc_failed", "draft", "none"}):
        work.release_status = "qc_ready"
    return True


def fill_release_defaults(db: Session, release: Release, work: Work, user: User) -> None:
    from app.services.distribution.release_ready import draft_metadata

    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    draft = draft_metadata(db, work, user)
    if not meta:
        meta = next(
            (row for row in db.new if isinstance(row, ReleaseMetadata) and row.release_id == release.id),
            None,
        )
    if not meta:
        meta = ReleaseMetadata(
            release_id=release.id,
            title=draft.get("title") or work.title or "Untitled",
            ai_disclosed=False,
        )
        db.add(meta)
        db.flush()
    if not (meta.artist_name or "").strip():
        meta.artist_name = draft.get("artist_name") or user.display_name or user.username
    if not (meta.title or "").strip():
        meta.title = draft.get("title") or work.title or "Untitled"
    if not meta.cover_url and (draft.get("cover_url") or work.cover_url):
        meta.cover_url = draft.get("cover_url") or work.cover_url
    if not release.selected_channels:
        from app.services.distribution.catalog import connected_channel_codes

        release.selected_channels = default_upload_channels(connected=connected_channel_codes(db, user))
    from app.services.distribution.track_code import ensure_track_code
    from app.services.royalty.sync_desk import ensure_default_sync_listing

    ensure_track_code(db, work, release)
    ensure_default_sync_listing(work)


def describe_release_automation(
    release: Release,
    meta: ReleaseMetadata | None,
    work: Work | None,
    *,
    channel_suggestion: dict | None = None,
) -> dict:
    qc = release.qc_result or {}
    title = (meta.title if meta else None) or (work.title if work else None)
    artist = meta.artist_name if meta else None
    missing: list[str] = []
    if not title or not str(title).strip():
        missing.append("title")
    if not artist or not str(artist).strip():
        missing.append("artist")
    if not (release.selected_channels or []):
        missing.append("channels")
    if not qc.get("passed"):
        missing.append("qc")
    return {
        "ready_to_confirm": not missing,
        "qc_hydrated": bool(qc.get("hydrated") or qc.get("source") == "post_process"),
        "qc_passed": bool(qc.get("passed")),
        "missing": missing,
        "priority": release_priority_payload(work),
        "clip_windows": clip_windows(getattr(work, "duration", None)),
        "portal_channels": list_portal_channels(),
        "channel_suggestion": channel_suggestion,
    }


def prepare_release_automation(db: Session, work: Work, user: User, release: Release) -> dict:
    from app.services.distribution.channel_suggest import suggest_channels_for_work

    fill_release_defaults(db, release, work, user)
    hydrated = hydrate_generation_qc(release, work)
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    suggestion = suggest_channels_for_work(db, work)
    payload = describe_release_automation(release, meta, work, channel_suggestion=suggestion)
    payload["qc_hydrated"] = payload["qc_hydrated"] or hydrated
    return payload


def attach_generation_qc(db: Session, work: Work, user: User, qc: dict) -> None:
    if work.release_status in {"queued", "delivering", "live"}:
        return
    from app.services.distribution.release_ready import ensure_release_draft

    release = ensure_release_draft(db, work, user)
    first_pass = bool(qc.get("passed") and not (release.qc_result or {}).get("passed"))
    if first_pass:
        release.qc_result = {**qc, "hydrated": True, "source": "post_process"}
        if release.status in (None, "draft"):
            release.status = "qc"
        work.release_status = "qc_ready"
    fill_release_defaults(db, release, work, user)
    if not first_pass:
        return
    if maybe_auto_submit_after_qc(db, work, user, release):
        return
    from app.services.notifications import create_notification

    create_notification(
        db,
        user.id,
        "release_hint",
        {
            "work_id": str(work.id),
            "release_id": str(release.id),
            "qc_passed": True,
            "message": "作品已自动过检，确认一次即可发行",
        },
        commit=False,
    )


def release_hint_for_work(
    *,
    work: Work,
    listen_completes: int = 0,
    unpublished: bool = True,
    channel_suggestion: dict | None = None,
) -> dict | None:
    if not unpublished:
        return None
    pri = release_priority_payload(work)
    if pri:
        hint = {"id": "priority", "level": "accent", "listen_completes": listen_completes, "priority": pri}
    else:
        qc_ready = bool((work.post_process_status or {}).get("release_qc") or work.release_status == "qc_ready")
        if listen_completes >= LISTEN_HINT_COMPLETES and qc_ready:
            hint = {"id": "listen", "level": "info", "listen_completes": listen_completes}
        else:
            from app.services.work_quality import compute_work_quality

            quality = compute_work_quality(work)
            if quality.get("suggestion_key") == "publish" and (qc_ready or listen_completes >= 3):
                hint = {"id": "quality", "level": "info", "listen_completes": listen_completes}
            elif qc_ready:
                hint = {"id": "qc_ready", "level": "info", "listen_completes": listen_completes}
            else:
                hint = None
    if hint and channel_suggestion:
        hint["channel_suggestion"] = channel_suggestion
    return hint


def should_auto_confirm_batch(batch, claims) -> bool:
    """High-confidence ops match is display-ready only. Never promotes settlement cash."""
    if getattr(batch, "source", None) != "ops_connector":
        return False
    rows = list(claims or [])
    if not rows or int(getattr(batch, "unmatched_count", 0) or 0) > 0:
        return False
    for claim in rows:
        if getattr(claim, "status", None) != "matched":
            return False
        if not getattr(claim, "work_id", None) or not getattr(claim, "isrc", None):
            return False
        if float(getattr(claim, "confidence", 0) or 0) < AUTO_CONFIRM_MIN_CONFIDENCE:
            return False
    return True


def weekly_release_suggestions(db: Session, user: User, *, limit: int = 3) -> list[dict]:
    from app.models.schemas import Release, Work
    from app.services.royalty.hub import _serialize_unpublished, prefer_workbench_masters

    active = {
        row.work_id
        for row in db.query(Release)
        .filter(Release.owner_id == user.id, Release.status.in_(("queued", "delivering", "live")))
        .all()
    }
    works = []
    for work in (
        db.query(Work)
        .filter(Work.owner_id == user.id)
        .order_by(Work.created_at.desc())
        .limit(40)
        .all()
    ):
        if work.id in active or not (work.audio_url or work.storage_key):
            continue
        works.append(work)
    works = prefer_workbench_masters(works)
    rows = _serialize_unpublished(db, works)
    weekday = datetime.utcnow().weekday()
    drop_id = None
    try:
        from app.services.emotion_calendar import week_drop_plan

        drop = week_drop_plan(db, user)
        drop_id = (drop.get("work") or {}).get("work_id")
    except Exception:
        drop_id = None
    for row in rows:
        hint_id = (row.get("hint") or {}).get("id")
        if drop_id and row.get("work_id") == drop_id:
            why = "emotion_week"
        elif hint_id == "priority":
            why = "winner"
        elif hint_id == "listen":
            why = "listens"
        elif row.get("qc_ready"):
            why = "qc_ready"
        elif weekday >= 4:
            why = "weekend"
        else:
            why = "unpublished"
        row["why"] = why
    rows.sort(key=lambda item: (1 if item.get("why") == "emotion_week" else 0, int((item.get("priority") or {}).get("score") or 0), item.get("listen_completes") or 0), reverse=True)
    return rows[: max(1, min(limit, 8))]


def remind_stale_deliveries(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=SLA_REMIND_AFTER_HOURS)
    rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.status.in_(("ops_queue", "awaiting_manual", "session_wait", "session_running")),
            DistributionDelivery.created_at <= cutoff,
        )
        .limit(80)
        .all()
    )
    from app.services.distribution.pipeline import notify_distribution_status

    reminded = 0
    for row in rows:
        meta = dict(row.attempt_meta or {})
        if meta.get("sla_reminded_at"):
            continue
        if row.status in {"awaiting_manual", "session_wait", "session_running"}:
            message = f"{row.channel_code} 已等待超过 {SLA_REMIND_AFTER_HOURS} 小时，打开连接器或官方后台继续一键"
        else:
            message = f"{row.channel_code} 一键代发已超过 {SLA_REMIND_AFTER_HOURS} 小时，运营正在用同一套 kit 处理"
        notify_distribution_status(
            db,
            row.owner_id,
            release_id=str(row.release_id),
            status=row.status,
            channel_code=row.channel_code,
            message=message,
        )
        meta["sla_reminded_at"] = now.isoformat()
        row.attempt_meta = meta
        reminded += 1
    return reminded


def escalate_overdue_deliveries(db: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=SLA_ESCALATE_HOURS)
    rows = (
        db.query(DistributionDelivery)
        .filter(
            DistributionDelivery.status.in_(("ops_queue", "awaiting_manual", "session_wait", "session_running")),
            DistributionDelivery.created_at <= cutoff,
        )
        .limit(80)
        .all()
    )
    from app.services.notifications import create_notification
    from app.services.distribution.pipeline import notify_distribution_status

    admins = db.query(User).filter(User.is_admin.is_(True)).limit(20).all()
    escalated = 0
    for row in rows:
        meta = dict(row.attempt_meta or {})
        if meta.get("sla_escalated_at"):
            continue
        meta["priority_score"] = max(int(meta.get("priority_score") or 0), SLA_ESCALATE_PRIORITY)
        meta["priority_reason"] = meta.get("priority_reason") or "sla_overdue"
        meta["sla_escalated_at"] = now.isoformat()
        row.attempt_meta = meta
        notify_distribution_status(
            db,
            row.owner_id,
            release_id=str(row.release_id),
            status=row.status,
            channel_code=row.channel_code,
            message=f"{row.channel_code} 已超过 {SLA_ESCALATE_HOURS} 小时 SLA，已加急",
        )
        for admin in admins:
            create_notification(
                db,
                admin.id,
                "ops_sla",
                {
                    "delivery_id": str(row.id),
                    "release_id": str(row.release_id),
                    "channel_code": row.channel_code,
                    "message": f"{row.channel_code} SLA 超时，请优先代发",
                },
                commit=False,
            )
        escalated += 1
    return escalated
