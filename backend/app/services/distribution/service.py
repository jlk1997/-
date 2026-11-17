from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.schemas import (
    CreatorIdentityBinding,
    DistributionDelivery,
    DistributionLicense,
    FeatureFlag,
    Release,
    ReleaseMetadata,
    User,
    Work,
)
from app.services.distribution.adapters import get_adapter
from app.services.distribution.catalog import (
    channel_automation_level,
    channel_delivery_mode,
    channel_sop,
    channel_upload_url,
    clip_windows,
    connected_channel_codes,
    default_upload_channels,
    delivery_has_live_receipt,
    distributor_for_code,
    preview_delivery_route,
    DEFAULT_UPLOAD_CHANNELS,
    seed_distribution_catalog,
)
from app.services.distribution.channel_fields import handoff_lines, listing_from_metadata, paste_sheet
from app.services.distribution.pipeline import (
    ACTIVE_RELEASE,
    EDITABLE_RELEASE,
    delivery_progress,
    dispatch_delivery,
    notify_distribution_status,
    process_one_delivery,
    process_release_submit as pipeline_process_release,
    refresh_release_progress,
)
from app.services.distribution.kit import build_self_release_kit
from app.services.distribution.release_ready import draft_metadata, ensure_release_draft, run_release_qc
from app.services.notifications import create_notification
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)

RELEASE_STATUSES = {"draft", "qc", "pending_license", "queued", "delivering", "live", "taken_down"}
DELIVERY_STATUSES = {
    "submitting",
    "ops_queue",
    "awaiting_manual",
    "session_wait",
    "session_running",
    "in_review",
    "live",
    "rejected",
    "taken_down",
}
PUBLISHING_STATUSES = {"submitting", "ops_queue", "awaiting_manual", "session_wait", "session_running", "in_review", "metrics_only"}
SELF_AUTOLIVE_STATUSES = {"awaiting_manual", "submitting", "ops_queue", "session_wait", "session_running", "in_review"}
SLA_STATUSES = {"ops_queue", "awaiting_manual", "in_review", "submitting", "session_wait", "session_running"}
QUEUE_STATUSES = ("ops_queue", "awaiting_manual", "session_wait", "session_running", "submitting")


def should_autolive_from_ops_receipt(status: str, store_url: str | None, channel_code: str | None = None) -> bool:
    """Official ops paste of a store URL is a receipt — promote hold rows to live."""
    from app.services.distribution.catalog import looks_like_store_page

    if not (store_url or "").strip():
        return False
    if status in {"rejected", "taken_down", "live"}:
        return False
    if status not in SELF_AUTOLIVE_STATUSES | PUBLISHING_STATUSES | {"queued", "delivering"}:
        return False
    return looks_like_store_page(store_url, channel_code)
CLAIM_TTL = timedelta(minutes=20)
SLA_HOURS = 48


def _sla_payload(d: DistributionDelivery) -> dict:
    meta = getattr(d, "attempt_meta", None) or {}
    escalated = bool(meta.get("sla_escalated_at"))
    if d.status not in SLA_STATUSES:
        return {"sla_hours": SLA_HOURS, "sla_due_at": None, "sla_overdue": False, "sla_escalated": escalated}
    start = d.created_at or datetime.utcnow()
    due = start + timedelta(hours=SLA_HOURS)
    return {
        "sla_hours": SLA_HOURS,
        "sla_due_at": due.isoformat(),
        "sla_overdue": datetime.utcnow() > due,
        "sla_escalated": escalated,
    }


LEASE_WAIT_NOTE = "farm_or_extension_lease_wait"


def release_next_action(deliveries) -> str:
    """Honest one-tap follow-up: wait for a handed store, connector, ops, or live receipt."""
    rows = list(deliveries or [])
    if not rows:
        return "wait_connector"
    statuses = [
        user_delivery_status(
            row.status,
            getattr(row, "last_error", None),
            has_receipt=delivery_has_live_receipt(row) if getattr(row, "status", None) == "live" else None,
        )
        for row in rows
    ]
    closed = {"live", "rejected", "taken_down"}
    if any(item == "live" for item in statuses) and all(item in closed for item in statuses):
        return "live"
    if any(item == "waiting_login" for item in statuses):
        return "wait_connector"
    if any(item in {"assisting", "needs_challenge", "needs_retry"} for item in statuses):
        return "assisting"
    if any(item == "ops_handling" for item in statuses):
        return "ops_handling"
    if any(item == "live" for item in statuses):
        return "partial_live"
    if all(item == "metrics_only" for item in statuses):
        return "metrics_only"
    return "publishing"


def user_delivery_status(status: str, last_error: str | None = None, *, has_receipt: bool | None = None) -> str:
    if status == "needs_challenge" or (last_error and "needs_challenge" in str(last_error)):
        return "needs_challenge"
    if last_error and "fill_incomplete" in str(last_error):
        return "needs_retry"
    if status == "awaiting_manual":
        return "needs_upload"
    if status == "session_wait":
        if last_error and LEASE_WAIT_NOTE in str(last_error):
            return "assisting"
        return "waiting_login"
    if status == "session_running":
        return "assisting"
    if status == "ops_queue":
        return "ops_handling"
    if status == "in_review":
        return "in_review"
    if status == "metrics_only":
        return "metrics_only"
    if status in PUBLISHING_STATUSES:
        return "publishing"
    if status == "live":
        if has_receipt is False:
            return "publishing"
        return "live"
    if status == "rejected":
        return "rejected"
    if status == "taken_down":
        return "taken_down"
    return status or "publishing"


DELIVERY_TIER_LABELS = {
    "api_verified": {"label": "已上架（可信）", "label_en": "Live (Verified)", "icon": "verified"},
    "assisted": {"label": "协助中（有SLA）", "label_en": "Assisting (SLA)", "icon": "assist"},
    "ops_pending": {"label": "平台在发", "label_en": "Platform Publishing", "icon": "ops"},
}


def delivery_tier_info(tier: str | None) -> dict:
    return DELIVERY_TIER_LABELS.get(tier or "", DELIVERY_TIER_LABELS["ops_pending"])


def normalize_store_url(raw: str) -> str:
    url = (raw or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Invalid store url")
    return url[:512]


def _license_rate(db: Session, release: Release) -> int | None:
    row = (
        db.query(DistributionLicense)
        .filter(DistributionLicense.release_id == release.id)
        .order_by(DistributionLicense.signed_at.desc())
        .first()
    )
    return row.commission_rate if row else None


def _flag_on(db: Session, key: str, default: bool = True) -> bool:
    row = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    return row.enabled if row else default


def _work_owned(db: Session, user: User, work_id: str) -> Work:
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    return work


def _fresh_kit_url(release: Release) -> str | None:
    if release.kit_storage_key:
        try:
            return get_storage_service().get_presigned_url(release.kit_storage_key)
        except Exception:
            logger.warning("Could not refresh kit URL for %s", release.id)
    return release.kit_url


def ensure_release_kit(db: Session, user: User, release_id: str) -> tuple[bytes, str]:
    release = _owned_release(db, user, release_id)
    storage = get_storage_service()
    if release.kit_storage_key:
        try:
            data = storage.get_object_bytes(release.kit_storage_key)
            if data:
                return data, _fresh_kit_url(release) or ""
        except Exception:
            logger.warning("Stored kit missing for %s, rebuilding", release.id)
    work = db.query(Work).filter(Work.id == release.work_id).first()
    if not work:
        raise HTTPException(404, "Work not found")
    audio = None
    if work and work.storage_key:
        try:
            audio = storage.get_object_bytes(work.storage_key)
        except Exception:
            audio = None
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    kit = build_self_release_kit(work=work, release=release, meta=meta, audio_bytes=audio, db=db)
    release.kit_storage_key = kit["key"]
    release.kit_url = kit["url"]
    db.commit()
    try:
        data = storage.get_object_bytes(kit["key"])
    except Exception as exc:
        raise HTTPException(502, "Kit storage unavailable") from exc
    if not data:
        raise HTTPException(502, "Kit storage unavailable")
    return data, kit["url"]


def _release_metadata_payload(db: Session, release: Release, meta: ReleaseMetadata | None) -> dict:
    work = db.query(Work).filter(Work.id == release.work_id).first()
    return {
        "title": (meta.title if meta else None) or (work.title if work else None),
        "artist_name": (meta.artist_name if meta else None),
        "lyrics": (meta.lyrics if meta else None) or getattr(work, "lyrics", None),
        "isrc": (meta.isrc if meta else None) or (work.isrc if work else None),
        "upc": meta.upc if meta else None,
        "genres": ((meta.genres if meta else None) or []) or [],
        "language": (meta.language if meta else None) or "zh",
        "copyright_year": meta.copyright_year if meta else None,
        "ai_disclosed": meta.ai_disclosed if meta else False,
        "cover_url": (meta.cover_url if meta else None) or (work.cover_url if work else None),
        "listing": listing_from_metadata(meta),
    }


def _allowed_rates_for_release(db: Session, release: Release) -> list[int]:
    from app.services.royalty.settlement import allowed_label_rates

    owner = db.query(User).filter(User.id == release.owner_id).first()
    return allowed_label_rates(db, owner) if owner else [20, 30]


def serialize_release(db: Session, release: Release) -> dict:
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    deliveries = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.release_id == release.id)
        .all()
    )
    progress = delivery_progress(deliveries)
    work = db.query(Work).filter(Work.id == release.work_id).first()
    from app.services.distribution.automation import describe_release_automation
    from app.services.distribution.asset_profiles import release_asset_status
    from app.services.distribution.catalog import preview_release_routes
    from app.services.distribution.telemetry import hydrate_telemetry

    hydrate_telemetry(db)
    from app.services.distribution.channel_suggest import suggest_channels_for_work

    automation = describe_release_automation(
        release,
        meta,
        work,
        channel_suggestion=suggest_channels_for_work(db, work),
    )
    return {
        "id": str(release.id),
        "work_id": str(release.work_id),
        "mode": release.mode,
        "status": release.status,
        "distributor_code": release.distributor_code,
        "selected_channels": release.selected_channels or [],
        "kit_url": _fresh_kit_url(release),
        "has_kit": bool(release.kit_storage_key),
        "qc_result": release.qc_result or {},
        "error_message": release.error_message,
        "commission_rate": _license_rate(db, release),
        "allowed_commission_rates": _allowed_rates_for_release(db, release),
        "metadata": _release_metadata_payload(db, release, meta),
        "deliveries": [serialize_delivery(d) for d in deliveries],
        "progress": progress,
        "editable": release.status in EDITABLE_RELEASE,
        "already_active": release.status in ACTIVE_RELEASE,
        "can_takedown": bool(progress.get("can_takedown")),
        "automation": automation,
        "priority": automation.get("priority"),
        "asset_status": release_asset_status(work, release.selected_channels or []) if work else None,
        "from_workbench": bool((work.post_process_status or {}).get("workbench")) if work else False,
        "next_action": (next_action := release_next_action(deliveries)),
        "route_preview": preview_release_routes(
            release.selected_channels
            or [row.channel_code for row in deliveries if getattr(row, "channel_code", None)]
        ),
        "needs_handoff": next_action == "wait_connector",
        # Older clients mapped 409 NEEDS_AUTH. Same meaning as wait_connector, not a hard stop.
        "needs_auth": next_action == "wait_connector",
        "created_at": release.created_at.isoformat() if release.created_at else None,
        "updated_at": release.updated_at.isoformat() if release.updated_at else None,
    }


def _claim_state(meta: dict | None) -> dict:
    payload = dict(meta or {})
    claimed_by = payload.get("claimed_by")
    claimed_at_raw = payload.get("claimed_at")
    claimed_at = None
    if claimed_at_raw:
        try:
            claimed_at = datetime.fromisoformat(str(claimed_at_raw))
        except ValueError:
            claimed_at = None
    expired = not claimed_by or not claimed_at or datetime.utcnow() - claimed_at > CLAIM_TTL
    if expired:
        return {"claimed_by": None, "claimed_email": None, "claimed_at": None, "claim_active": False}
    return {
        "claimed_by": claimed_by,
        "claimed_email": payload.get("claimed_email"),
        "claimed_at": claimed_at.isoformat() if claimed_at else None,
        "claim_active": True,
    }


def _delivery_lease_owner(d: DistributionDelivery, meta: dict) -> str | None:
    owner = meta.get("lease_owner") if isinstance(meta, dict) else None
    if owner:
        return str(owner)
    err = str(d.last_error or "")
    if d.status not in {"session_running", "session_wait"}:
        return None
    if LEASE_WAIT_NOTE in err:
        return "contested"
    return "extension"


def serialize_delivery(d: DistributionDelivery) -> dict:
    from app.services.distribution.asset_profiles import profile_payload
    from app.services.distribution.reject import humanize_reject

    claim = _claim_state(d.attempt_meta)
    meta = d.attempt_meta or {}
    assist = meta.get("assist_job") if isinstance(meta, dict) else None
    assist = assist if isinstance(assist, dict) else {}
    needs_challenge = bool(
        assist.get("needs_challenge")
        or assist.get("error") == "needs_challenge"
        or (isinstance(meta, dict) and meta.get("needs_challenge"))
        or "needs_challenge" in str(d.last_error or "")
        or d.status == "needs_challenge"
    )
    receipt = delivery_has_live_receipt(d)
    return {
        "id": str(d.id),
        "release_id": str(d.release_id),
        "work_id": str(d.work_id),
        "channel_code": d.channel_code,
        "distributor_code": d.distributor_code,
        "status": d.status,
        "user_status": user_delivery_status(d.status, d.last_error, has_receipt=receipt if d.status == "live" else None),
        "has_receipt": receipt,
        "needs_challenge": needs_challenge,
        "reject_reason": d.reject_reason,
        "reject_next": humanize_reject(d.reject_reason or d.last_error, status=d.status),
        "ops_honest": d.status == "ops_queue",
        "external_id": d.external_id,
        "store_url": d.store_url,
        "upload_url": channel_upload_url(d.channel_code),
        "sop": channel_sop(d.channel_code),
        "asset_profile": profile_payload(d.channel_code),
        "listing_asset": "master",
        "originality_zip_url": assist.get("originality_zip_url"),
        "delivery_mode": channel_delivery_mode(d.channel_code),
        "automation_level": channel_automation_level(d.channel_code),
        "degraded": bool((preview_delivery_route(d.channel_code) or {}).get("degraded")),
        "layer": (
            "session_assist"
            if d.status in {"session_wait", "session_running"}
            else "ops"
            if d.status == "ops_queue"
            else channel_delivery_mode(d.channel_code)
        ),
        "assist_job": (meta.get("assist_job") if isinstance(meta, dict) else None),
        **_sla_payload(d),
        "retry_count": d.retry_count,
        "last_error": d.last_error,
        "last_attempt_at": d.last_attempt_at.isoformat() if d.last_attempt_at else None,
        "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "priority_score": int(meta.get("priority_score") or 0),
        "priority_reason": meta.get("priority_reason"),
        "submissions": list(meta.get("submissions") or [])[-8:],
        "lease_owner": _delivery_lease_owner(d, meta),
        "seat_id": str(meta.get("seat_id")) if isinstance(meta, dict) and meta.get("seat_id") else None,
        **claim,
    }


def _get_delivery(db: Session, delivery_id: str) -> DistributionDelivery:
    try:
        did = uuid.UUID(delivery_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid delivery id") from exc
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == did).first()
    if not row:
        raise HTTPException(404, "Delivery not found")
    return row


def claim_delivery(db: Session, admin: User, delivery_id: str) -> dict:
    row = _get_delivery(db, delivery_id)
    if row.status in ("live", "taken_down"):
        raise HTTPException(400, "Delivery is already closed")
    current = _claim_state(row.attempt_meta)
    if current["claim_active"] and current["claimed_by"] != str(admin.id):
        raise HTTPException(409, "Delivery is claimed by another operator")
    meta = dict(row.attempt_meta or {})
    meta.update({
        "claimed_by": str(admin.id),
        "claimed_email": admin.email,
        "claimed_at": datetime.utcnow().isoformat(),
    })
    row.attempt_meta = meta
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(row, event="ops_claim", actor=str(admin.id), message=admin.email)
    db.commit()
    return serialize_delivery(row)


def unclaim_delivery(db: Session, admin: User, delivery_id: str) -> dict:
    row = _get_delivery(db, delivery_id)
    current = _claim_state(row.attempt_meta)
    if current["claim_active"] and current["claimed_by"] != str(admin.id) and not getattr(admin, "is_admin", False):
        raise HTTPException(409, "Delivery is claimed by another operator")
    meta = dict(row.attempt_meta or {})
    meta.pop("claimed_by", None)
    meta.pop("claimed_email", None)
    meta.pop("claimed_at", None)
    row.attempt_meta = meta
    db.commit()
    return serialize_delivery(row)


def _ops_steps_for(db: Session, row: DistributionDelivery, payload: dict) -> list[str]:
    from app.services.distribution.assist import has_connector_heartbeat
    from app.services.distribution.asset_profiles import profile_for

    title = payload.get("title") or "未命名"
    profile = profile_for(row.channel_code)
    steps = [
        f"下载同一套资产包（{title}）",
        "正片只传 audio/master.wav（一条立体声母带）。TuneCore 可用 audio/master_24bit.wav。不要把 vocal/drums 当分曲。",
        f"打开 {row.channel_code} 官方后台：{channel_upload_url(row.channel_code) or row.distributor_code or '门户'}",
        f"{channel_sop(row.channel_code) or '按官方页上传音频与封面'}",
    ]
    if profile.needs_stems_evidence:
        steps.append("原创证明 originality.zip 只放分轨/版权证明栏（或邮件 TME），不是正片音频。")
    if profile.needs_clips:
        steps.append("短视频用 audio/clips/ 或切片包，不要上传分轨当 BGM。")
    if row.status in {"session_wait", "session_running"}:
        online = has_connector_heartbeat(db, row.owner_id)
        steps.insert(1, "创作者连接器在线，可在已打开的官方页继续一键" if online else "创作者连接器离线：装扩展或运营同 kit 继续")
        steps.append("席位任务回传商店页后标 live；没有回执才人工补听众能打开的歌曲页")
    else:
        steps.append("席位或运营回传 store URL / 外部曲目 ID（有歌曲页才标 live）")
    steps.append("有合作密钥后队列会自动切聚合提交，无需另开流程")
    return steps


def delivery_ops_pack(db: Session, delivery_id: str) -> dict:
    row = _get_delivery(db, delivery_id)
    release = db.query(Release).filter(Release.id == row.release_id).first()
    work = db.query(Work).filter(Work.id == row.work_id).first()
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == row.release_id).first() if release else None
    kit_url = None
    has_kit = False
    if release:
        if not release.kit_storage_key:
            from app.services.distribution.pipeline import ensure_kit_for_release

            ensure_kit_for_release(db, release)
            db.commit()
        kit_url = _fresh_kit_url(release)
        has_kit = bool(release.kit_storage_key)
    payload = _release_metadata_payload(db, release, meta) if release else {}
    clips = clip_windows(getattr(work, "duration", None)) if work else []
    clip_pack_url = None
    if work:
        try:
            from app.services.distribution.kit import ensure_work_clip_pack

            _data, clip_pack_url = ensure_work_clip_pack(work)
        except Exception:
            clip_pack_url = None
    selected = (release.selected_channels or []) if release else [row.channel_code]
    asset_status = None
    orig = {}
    if work:
        from app.services.distribution.asset_profiles import release_asset_status
        from app.services.stem_assets import originality_pack_ref

        asset_status = release_asset_status(work, selected)
        orig = originality_pack_ref(work)
    return {
        "delivery": serialize_delivery(row),
        "mode": release.mode if release else None,
        "title": payload.get("title") or (work.title if work else None),
        "artist_name": payload.get("artist_name"),
        "isrc": payload.get("isrc"),
        "metadata": payload,
        "kit_url": kit_url,
        "has_kit": has_kit,
        "selected_channels": selected,
        "ops_steps": _ops_steps_for(db, row, payload),
        "cover_url": payload.get("cover_url"),
        "clip_windows": clips,
        "clip_pack_url": clip_pack_url,
        "asset_status": asset_status,
        "listing_asset": "master",
        "originality_zip_url": orig.get("url"),
        "originality_ready": bool(orig.get("ready")),
        "handoff": handoff_lines(meta, [row.channel_code]),
        "paste_sheet": paste_sheet(handoff_lines(meta, [row.channel_code])),
        "listing": listing_from_metadata(meta),
        "lyrics": meta.lyrics if meta else None,
        "distributor_code": row.distributor_code,
        "qc_passed": bool((release.qc_result or {}).get("passed")) if release else False,
        "commission_rate": _license_rate(db, release) if release else None,
        **_sla_payload(row),
    }


def release_ops_workbench(db: Session, release_id: str, admin: User | None = None) -> dict:
    try:
        rid = uuid.UUID(release_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid release id") from exc
    release = db.query(Release).filter(Release.id == rid).first()
    if not release:
        raise HTTPException(404, "Release not found")
    deliveries = (
        db.query(DistributionDelivery)
        .filter(DistributionDelivery.release_id == release.id)
        .order_by(DistributionDelivery.created_at.asc())
        .all()
    )
    focus = next((d for d in deliveries if d.status in PUBLISHING_STATUSES), deliveries[0] if deliveries else None)
    if admin and focus and focus.status in PUBLISHING_STATUSES and not _claim_state(focus.attempt_meta)["claim_active"]:
        meta = dict(focus.attempt_meta or {})
        meta.update({
            "claimed_by": str(admin.id),
            "claimed_email": admin.email,
            "claimed_at": datetime.utcnow().isoformat(),
            "auto_claimed": True,
        })
        focus.attempt_meta = meta
        db.commit()
    pack = delivery_ops_pack(db, str(focus.id)) if focus else {}
    dues = [d.created_at for d in deliveries if d.status in PUBLISHING_STATUSES and d.created_at]
    due_at = (min(dues) + timedelta(hours=SLA_HOURS)).isoformat() if dues else None
    overdue = bool(dues and datetime.utcnow() > min(dues) + timedelta(hours=SLA_HOURS))
    return {
        **serialize_release(db, release),
        "workbench": True,
        "sla_hours": SLA_HOURS,
        "sla_due_at": due_at,
        "sla_overdue": overdue,
        "kit_url": pack.get("kit_url"),
        "has_kit": pack.get("has_kit"),
        "ops_steps": pack.get("ops_steps") or [],
        "cover_url": pack.get("cover_url"),
        "clip_windows": pack.get("clip_windows") or [],
        "clip_pack_url": pack.get("clip_pack_url"),
        "asset_status": pack.get("asset_status"),
        "listing_asset": pack.get("listing_asset") or "master",
        "originality_zip_url": pack.get("originality_zip_url"),
        "originality_ready": pack.get("originality_ready"),
        "handoff": pack.get("handoff") or [],
        "focus_delivery_id": str(focus.id) if focus else None,
        "priority_score": max((int((d.attempt_meta or {}).get("priority_score") or 0) for d in deliveries), default=0),
        "priority_reason": next(( (d.attempt_meta or {}).get("priority_reason") for d in deliveries if (d.attempt_meta or {}).get("priority_reason") ), None),
    }


def create_or_get_release(db: Session, user: User, work_id: str) -> dict:
    if not _flag_on(db, "dsp_distribution"):
        raise HTTPException(403, "Distribution is not enabled")
    work = _work_owned(db, user, work_id)
    from app.services.royalty.hub import resolve_release_work

    work, redirected_from = resolve_release_work(db, work)
    seed_distribution_catalog(db)
    release = ensure_release_draft(db, work, user)
    db.commit()
    data = serialize_release(db, release)
    if redirected_from:
        data["redirected_from_work_id"] = str(redirected_from.id)
        data["from_workbench"] = True
    return data


def update_release(db: Session, user: User, release_id: str, payload: dict) -> dict:
    release = _owned_release(db, user, release_id)
    if payload.get("mode") in ("self_release", "label"):
        if release.status in ACTIVE_RELEASE and payload["mode"] != release.mode:
            raise HTTPException(400, "Cannot change mode after submit")
        release.mode = payload["mode"]
    if "selected_channels" in payload:
        release.selected_channels = payload["selected_channels"]
    if payload.get("distributor_code"):
        release.distributor_code = payload["distributor_code"]
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    if not meta:
        meta = ReleaseMetadata(
            release_id=release.id,
            title=payload.get("title") or "Untitled",
            ai_disclosed=bool(payload.get("ai_disclosed", False)),
        )
        db.add(meta)
    for field in ("title", "artist_name", "lyrics", "isrc", "upc", "language", "cover_url"):
        if field in payload and payload[field] is not None:
            setattr(meta, field, payload[field])
    if "genres" in payload:
        meta.genres = payload["genres"]
    if "copyright_year" in payload:
        meta.copyright_year = payload["copyright_year"]
    if "ai_disclosed" in payload:
        meta.ai_disclosed = bool(payload["ai_disclosed"])
    from app.services.distribution.channel_fields import apply_listing_payload

    apply_listing_payload(meta, payload.get("listing") if isinstance(payload.get("listing"), dict) else payload)
    from app.services.ops.orders import settle_field_requests

    settle_field_requests(db, release)
    if meta.isrc:
        work = db.query(Work).filter(Work.id == release.work_id).first()
        if work:
            work.isrc = meta.isrc
    db.commit()
    if meta.isrc and release.work_id:
        from app.services.royalty.ingest import revalidate_isrc_snapshots_for_work

        revalidate_isrc_snapshots_for_work(db, release.work_id)
    return serialize_release(db, release)


def run_qc(db: Session, user: User, release_id: str) -> dict:
    if not _flag_on(db, "release_qc"):
        raise HTTPException(403, "Release QC is not enabled")
    release = _owned_release(db, user, release_id)
    work = db.query(Work).filter(Work.id == release.work_id).first()
    result = run_release_qc(db, work, release=release, user=user)
    release.qc_result = result
    release.status = "qc" if result["passed"] else "draft"
    if work:
        work.release_status = "qc_ready" if result["passed"] else "qc_failed"
    db.commit()
    return {"qc": result, "release": serialize_release(db, release)}


def sign_license(db: Session, user: User, release_id: str, agreement_version: str, rate: int) -> dict:
    from app.services.royalty.settlement import allowed_label_rates

    if rate not in allowed_label_rates(db, user):
        raise HTTPException(400, "Commission rate is not available for this account")
    release = _owned_release(db, user, release_id)
    if release.mode != "label":
        raise HTTPException(400, "License only required for label mode")
    row = DistributionLicense(
        user_id=user.id,
        release_id=release.id,
        agreement_version=agreement_version,
        commission_rate=rate,
    )
    db.add(row)
    release.status = "pending_license"
    db.commit()
    return {"signed": True, "commission_rate": rate, "release": serialize_release(db, release)}


def submit_release(db: Session, user: User, release_id: str) -> dict:
    release = _owned_release(db, user, release_id)
    release = (
        db.query(Release)
        .filter(Release.id == release.id, Release.owner_id == user.id)
        .with_for_update()
        .first()
        or release
    )
    if release.status in ACTIVE_RELEASE:
        return serialize_release(db, release)
    if _flag_on(db, "release_qc") and not (release.qc_result or {}).get("passed"):
        raise HTTPException(400, "Release QC has not passed")
    work = db.query(Work).filter(Work.id == release.work_id).first()
    seed_distribution_catalog(db)
    channels = [
        code
        for code in (
            release.selected_channels
            or default_upload_channels(connected=connected_channel_codes(db, user))
        )
        if distributor_for_code(db, code)
    ]
    if not channels:
        channels = [code for code in DEFAULT_UPLOAD_CHANNELS if distributor_for_code(db, code)]
    if not channels:
        raise HTTPException(400, "No deliverable channels")
    from app.services.distribution.handoff import AUTH_HOLD

    if release.error_message == AUTH_HOLD:
        release.error_message = None
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
    title = (meta.title if meta else None) or (work.title if work else None)
    artist = (meta.artist_name if meta else None)
    if not title or not str(title).strip():
        raise HTTPException(400, "Title is required")
    if not artist or not str(artist).strip():
        raise HTTPException(400, "Artist name is required")
    if work:
        from app.services.distribution.track_code import ensure_track_code

        ensure_track_code(db, work, release)
        if meta and not meta.isrc:
            meta.isrc = work.isrc
    if release.mode == "label":
        lic = (
            db.query(DistributionLicense)
            .filter(DistributionLicense.release_id == release.id, DistributionLicense.user_id == user.id)
            .first()
        )
        if not lic:
            raise HTTPException(400, "Sign the distribution license first")
    audio = None
    if work and work.storage_key:
        try:
            audio = get_storage_service().get_object_bytes(work.storage_key)
        except Exception:
            audio = None
    if work:
        try:
            kit = build_self_release_kit(work=work, release=release, meta=meta, audio_bytes=audio, db=db)
            release.kit_storage_key = kit["key"]
            release.kit_url = kit["url"]
        except Exception as exc:
            logger.warning("Could not build release kit for %s: %s", release.id, exc)

    created = 0
    for code in channels:
        distributor = distributor_for_code(db, code)
        if not distributor:
            continue
        existing = (
            db.query(DistributionDelivery)
            .filter(DistributionDelivery.release_id == release.id, DistributionDelivery.channel_code == code)
            .first()
        )
        if existing:
            if existing.status not in ("live", "taken_down"):
                existing.status = "submitting"
                existing.next_retry_at = None
                existing.last_error = None
            created += 1
            continue
        try:
            with db.begin_nested():
                db.add(
                    DistributionDelivery(
                        release_id=release.id,
                        work_id=release.work_id,
                        owner_id=user.id,
                        channel_code=code,
                        distributor_code=distributor,
                        status="submitting",
                    )
                )
                db.flush()
            created += 1
        except IntegrityError:
            existing = (
                db.query(DistributionDelivery)
                .filter(DistributionDelivery.release_id == release.id, DistributionDelivery.channel_code == code)
                .first()
            )
            if not existing:
                continue
            if existing.status not in ("live", "taken_down"):
                existing.status = "submitting"
                existing.next_retry_at = None
                existing.last_error = None
            created += 1
    if created <= 0:
        raise HTTPException(400, "No deliverable channels")
    if work:
        from app.services.distribution.automation import copy_priority_to_deliveries

        copy_priority_to_deliveries(db, work, release)
    release.status = "queued"
    release.error_message = None
    release.selected_channels = channels
    if work:
        work.release_status = "queued"
        if meta and meta.isrc:
            work.isrc = meta.isrc
    db.commit()
    if work and getattr(work, "isrc", None):
        from app.services.royalty.ingest import revalidate_isrc_snapshots_for_work

        revalidate_isrc_snapshots_for_work(db, work.id)
    try:
        from app.services.radio.network import start_radio_trial

        start_radio_trial(db, user, str(release.work_id), commit=True)
    except Exception:
        logger.exception("radio trial after submit failed for %s", release.work_id)
    try:
        pipeline_process_release(db, str(release.id))
    except Exception as exc:
        logger.exception("sync pipeline failed for %s; celery/reconcile will retry", release.id)
        release.error_message = str(exc)[:500]
        db.commit()
    try:
        from app.workers.distribution_tasks import submit_release_task

        submit_release_task.apply_async(args=[str(release.id)], queue="distribution")
    except Exception as exc:
        logger.warning("Could not enqueue submit_release_task: %s", exc)
    try:
        db.refresh(release)
    except Exception:
        release = db.query(Release).filter(Release.id == release.id).first() or release
    return serialize_release(db, release)


def auto_submit_release(db: Session, user: User, release_id: str, payload: dict) -> dict:
    if not payload.get("consent"):
        raise HTTPException(400, "Consent is required")
    release = _owned_release(db, user, release_id)
    if release.status in ACTIVE_RELEASE:
        return serialize_release(db, release)
    fields = {
        key: payload[key]
        for key in ("mode", "title", "artist_name", "isrc", "selected_channels")
        if payload.get(key) is not None
    }
    if fields:
        update_release(db, user, release_id, fields)
        release = _owned_release(db, user, release_id)
    work = db.query(Work).filter(Work.id == release.work_id).first()
    if work:
        from app.services.distribution.automation import prepare_release_automation

        prepare_release_automation(db, work, user, release)
        db.commit()
    if _flag_on(db, "release_qc") and not (release.qc_result or {}).get("passed"):
        run_qc(db, user, release_id)
        release = _owned_release(db, user, release_id)
        if not (release.qc_result or {}).get("passed"):
            raise HTTPException(400, "Release QC has not passed")
    if release.mode == "label":
        lic = (
            db.query(DistributionLicense)
            .filter(DistributionLicense.release_id == release.id, DistributionLicense.user_id == user.id)
            .first()
        )
        if not lic:
            rate = int(payload.get("commission_rate") or 20)
            sign_license(db, user, release_id, str(payload.get("agreement_version") or "2026-08-19"), rate)
    return submit_release(db, user, release_id)


def quick_release_work(db: Session, user: User, work_id: str, payload: dict) -> dict:
    created = create_or_get_release(db, user, work_id)
    if created.get("already_active"):
        return created
    update_release(db, user, created["id"], {"ai_disclosed": True})
    return auto_submit_release(db, user, created["id"], payload)


def process_release_submit(db: Session, release_id: str) -> None:
    pipeline_process_release(db, release_id)


def retry_delivery(db: Session, user: User, delivery_id: str) -> dict:
    d = _owned_delivery(db, user, delivery_id)
    if d.status in ("live", "taken_down"):
        raise HTTPException(400, "Delivery is already closed")
    d.status = "submitting"
    d.next_retry_at = None
    d.last_error = None
    db.commit()
    db.refresh(d)
    process_one_delivery(db, d, force=True, commit=True)
    db.refresh(d)
    if d.status == "submitting":
        dispatch_delivery(str(d.id), str(d.release_id), process_now=False)
    return serialize_delivery(d)


def takedown_release(db: Session, user: User, release_id: str) -> dict:
    release = _owned_release(db, user, release_id)
    deliveries = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    for d in deliveries:
        if d.status == "taken_down":
            continue
        try:
            adapter = get_adapter(d.distributor_code)
            result = adapter.takedown(d.external_id)
            d.status = result.status if result.status in DELIVERY_STATUSES else "taken_down"
            d.last_error = None if result.ok else (result.message or d.last_error)
        except Exception as exc:
            logger.exception("takedown failed for %s", d.id)
            d.status = "taken_down"
            d.last_error = str(exc)[:300]
    refresh_release_progress(db, release)
    db.commit()
    create_notification(
        db,
        user.id,
        "distribution_status",
        {"release_id": str(release.id), "status": "taken_down", "message": "已提交全渠道下架"},
    )
    return serialize_release(db, release)


def set_store_url(db: Session, user: User, delivery_id: str, store_url: str, external_id: str | None = None) -> dict:
    from app.services.distribution.catalog import extract_store_ref, looks_like_store_page

    d = _owned_delivery(db, user, delivery_id)
    previous = d.status
    url = normalize_store_url(store_url)
    if not looks_like_store_page(url, d.channel_code):
        raise HTTPException(400, "not a store page")
    d.store_url = url
    if not external_id:
        external_id = extract_store_ref(url, d.channel_code)
    if external_id:
        d.external_id = str(external_id)[:128]
    release = db.query(Release).filter(Release.id == d.release_id).first()
    if should_autolive_from_ops_receipt(d.status, url, d.channel_code):
        d.status = "live"
        d.last_error = None
        d.reject_reason = None
        if release:
            refresh_release_progress(db, release)
        notify_distribution_status(
            db,
            d.owner_id,
            release_id=str(d.release_id),
            status="live",
            channel_code=d.channel_code,
            message=f"{d.channel_code} 已记录店铺链接并上架",
        )
    if previous != "live" and d.status == "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, d)
    db.commit()
    return serialize_delivery(d)


def admin_list_deliveries(db: Session, status: str | None = None, queue_only: bool = False) -> list[dict]:
    q = db.query(DistributionDelivery)
    if status:
        q = q.filter(DistributionDelivery.status == status)
    elif queue_only:
        q = q.filter(DistributionDelivery.status.in_(QUEUE_STATUSES))
    rows = q.order_by(DistributionDelivery.updated_at.desc()).limit(200).all()
    if not rows:
        return []
    release_ids = {r.release_id for r in rows}
    work_ids = {r.work_id for r in rows}
    owner_ids = {r.owner_id for r in rows}
    metas = {
        m.release_id: m
        for m in db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id.in_(release_ids)).all()
    }
    works = {w.id: w for w in db.query(Work).filter(Work.id.in_(work_ids)).all()}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(owner_ids)).all()}
    releases = {r.id: r for r in db.query(Release).filter(Release.id.in_(release_ids)).all()}
    out = []
    for d in rows:
        payload = serialize_delivery(d)
        meta = metas.get(d.release_id)
        work = works.get(d.work_id)
        user = users.get(d.owner_id)
        release = releases.get(d.release_id)
        payload["title"] = (meta.title if meta else None) or (work.title if work else None)
        payload["owner_email"] = user.email if user else None
        payload["owner_username"] = user.username if user else None
        payload["mode"] = release.mode if release else None
        payload["release_status"] = release.status if release else None
        out.append(payload)
    out.sort(key=lambda item: (int(item.get("priority_score") or 0), item.get("updated_at") or ""), reverse=True)
    return out


def admin_set_delivery_status(
    db: Session,
    delivery_id: str,
    status: str,
    reason: str | None = None,
    store_url: str | None = None,
    external_id: str | None = None,
) -> dict:
    if status not in DELIVERY_STATUSES:
        raise HTTPException(400, "Invalid delivery status")
    try:
        did = uuid.UUID(delivery_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid delivery id") from exc
    d = db.query(DistributionDelivery).filter(DistributionDelivery.id == did).first()
    if not d:
        raise HTTPException(404, "Delivery not found")
    previous = d.status
    from app.services.distribution.catalog import extract_store_ref, has_live_receipt, looks_like_store_page

    if store_url:
        url = normalize_store_url(store_url)
        if not looks_like_store_page(url, d.channel_code):
            raise HTTPException(400, "not a store page")
        d.store_url = url
        if should_autolive_from_ops_receipt(status, d.store_url, d.channel_code):
            status = "live"
    if not external_id and d.store_url:
        external_id = extract_store_ref(d.store_url, d.channel_code)
    if external_id:
        d.external_id = str(external_id)[:128]
    if status == "live" and not has_live_receipt(store_url=d.store_url, external_id=d.external_id, channel_code=d.channel_code):
        raise HTTPException(400, "live requires store_url or external_id")
    d.status = status
    d.reject_reason = reason
    from app.services.distribution.submit_log import append_delivery_event

    append_delivery_event(
        d,
        event="ops_receipt" if status == "live" else "ops_status",
        actor="ops",
        receipt_url=d.store_url,
        external_id=d.external_id,
        message=reason or status,
    )
    if previous != "live" and d.status == "live":
        from app.services.seats.service import queue_copy_after_live

        queue_copy_after_live(db, d)
    release = db.query(Release).filter(Release.id == d.release_id).first()
    if release:
        refresh_release_progress(db, release)
    db.commit()
    if status in ("live", "rejected", "taken_down", "in_review"):
        create_notification(
            db,
            d.owner_id,
            "distribution_status",
            {
                "delivery_id": str(d.id),
                "release_id": str(d.release_id),
                "channel_code": d.channel_code,
                "status": status,
                "message": reason or f"{d.channel_code} 状态更新为 {status}",
            },
        )
    return serialize_delivery(d)


def admin_mark_release_live(db: Session, release_id: str, store_url: str | None = None) -> dict:
    try:
        rid = uuid.UUID(release_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid release id") from exc
    release = db.query(Release).filter(Release.id == rid).first()
    if not release:
        raise HTTPException(404, "Release not found")
    from app.services.distribution.catalog import has_live_receipt

    rows = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    pending = [row for row in rows if row.status != "taken_down"]
    if not rows:
        return {"release_id": str(release.id), "updated": 0, "skipped": 0, "deliveries": [], "reason": "no_deliveries"}
    apply_url = store_url if store_url and len(pending) == 1 else None
    updated = []
    skipped = 0
    for row in pending:
        receipt = apply_url or row.store_url
        if not has_live_receipt(store_url=receipt, external_id=row.external_id, channel_code=row.channel_code):
            skipped += 1
            continue
        updated.append(admin_set_delivery_status(db, str(row.id), "live", store_url=receipt, external_id=row.external_id))
    return {"release_id": str(release.id), "updated": len(updated), "skipped": skipped, "deliveries": updated}


def bind_distributor(db: Session, user: User, provider: str, official_token: str | None, external_release_id: str | None) -> dict:
    if provider == "youtube":
        raise HTTPException(400, "Connect YouTube via official OAuth")
    if official_token and len(official_token) > 8 and "password" in provider:
        raise HTTPException(400, "Passwords are not accepted")
    row = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == provider)
        .first()
    )
    if not row:
        row = CreatorIdentityBinding(user_id=user.id, provider=provider)
        db.add(row)
    row.official_token = official_token
    row.external_release_id = external_release_id
    row.status = "active"
    db.commit()
    return {
        "provider": provider,
        "bound": True,
        "has_token": bool(official_token),
        "external_release_id": external_release_id,
    }


def unbind_distributor(db: Session, user: User, provider: str) -> dict:
    row = (
        db.query(CreatorIdentityBinding)
        .filter(CreatorIdentityBinding.user_id == user.id, CreatorIdentityBinding.provider == provider)
        .first()
    )
    if not row:
        raise HTTPException(404, "Binding not found")
    db.delete(row)
    db.commit()
    return {"provider": provider, "bound": False}


def list_bindings(db: Session, user: User) -> list[dict]:
    rows = db.query(CreatorIdentityBinding).filter(CreatorIdentityBinding.user_id == user.id).all()
    return [
        {
            "id": str(r.id),
            "provider": r.provider,
            "has_token": bool(r.official_token),
            "external_release_id": r.external_release_id,
            "status": r.status,
        }
        for r in rows
    ]


def list_user_releases(db: Session, user: User) -> list[dict]:
    rows = db.query(Release).filter(Release.owner_id == user.id).order_by(Release.created_at.desc()).all()
    return [serialize_release(db, r) for r in rows]


def list_user_deliveries(db: Session, user: User, work_id: str | None = None) -> list[dict]:
    q = db.query(DistributionDelivery).filter(DistributionDelivery.owner_id == user.id)
    if work_id:
        q = q.filter(DistributionDelivery.work_id == uuid.UUID(work_id))
    return [serialize_delivery(d) for d in q.order_by(DistributionDelivery.updated_at.desc()).all()]


def _owned_release(db: Session, user: User, release_id: str) -> Release:
    try:
        rid = uuid.UUID(release_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid release id") from exc
    release = db.query(Release).filter(Release.id == rid, Release.owner_id == user.id).first()
    if not release:
        raise HTTPException(404, "Release not found")
    return release


def _owned_delivery(db: Session, user: User, delivery_id: str) -> DistributionDelivery:
    try:
        did = uuid.UUID(delivery_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid delivery id") from exc
    d = db.query(DistributionDelivery).filter(DistributionDelivery.id == did, DistributionDelivery.owner_id == user.id).first()
    if not d:
        raise HTTPException(404, "Delivery not found")
    return d
