"""Creator economy: tips, exports, marketplace, wallets, invoices."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import (
    CreatorTip,
    CreatorWallet,
    CnRecurringWaitlist,
    InvoiceRequest,
    PaidWorkPack,
    RecipeTemplate,
    RecipeTemplatePurchase,
    SupportTicket,
    User,
    Work,
    WorkExport,
)
from app.services.credits import deduct_credits, grant_credits_with_transaction
from app.services.subscriptions import is_active_subscriber

PLATFORM_TIP_FEE_RATE = 0.10
REMIX_ROYALTY_RATE = 0.20
TEMPLATE_PLATFORM_FEE_RATE = 0.30

EXPORT_COSTS = {
    "hq_mp3": 0,
    "hq_wav": 1,
    "stems": 1,
    "commercial_license": 1,
}


def _wallet_credit(db: Session, user_id: uuid.UUID, credits: int, *, source: str) -> CreatorWallet:
    wallet = db.query(CreatorWallet).filter(CreatorWallet.user_id == user_id).first()
    if not wallet:
        wallet = CreatorWallet(user_id=user_id, balance_credits=0, lifetime_earned=0)
        db.add(wallet)
        db.flush()
    wallet.balance_credits += credits
    wallet.lifetime_earned += credits
    wallet.updated_at = datetime.utcnow()
    grant_credits_with_transaction(db, user_id, credits, source=source, external_id=f"{source}_{uuid.uuid4().hex}")
    return wallet


def tip_creator(
    db: Session,
    from_user: User,
    *,
    work_id: str,
    credits: int,
    public_message: str | None = None,
    is_public: bool = False,
) -> dict[str, Any]:
    if credits < 1 or credits > 10:
        raise HTTPException(status_code=400, detail="Tip must be 1–10 credits")
    if public_message:
        from app.services.content_moderation import moderate_text

        result = moderate_text(public_message, db=db, scene="comment")
        if result.action == "block":
            raise HTTPException(status_code=400, detail=result.reason or "感谢语不合规")
        public_message = result.text
        is_public = True

    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid work id") from exc

    work = db.query(Work).filter(Work.id == wid).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if work.owner_id == from_user.id:
        raise HTTPException(status_code=400, detail="Cannot tip your own work")

    fee = max(1, int(credits * PLATFORM_TIP_FEE_RATE)) if credits >= 5 else 0
    net = credits - fee
    if not deduct_credits(db, from_user.id, credits, source="tip_sent"):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    tip = CreatorTip(
        from_user_id=from_user.id,
        to_user_id=work.owner_id,
        work_id=work.id,
        credits=net,
        platform_fee=fee,
        public_message=public_message,
        is_public=bool(is_public and public_message),
    )
    db.add(tip)
    _wallet_credit(db, work.owner_id, net, source="tip_received")

    from app.services.notifications import notify_tip_received

    notify_tip_received(
        db,
        work.owner_id,
        tipper_username=from_user.username,
        work_id=str(work.id),
        work_title=work.title,
        credits=net,
        public_message=public_message if tip.is_public else None,
    )
    db.commit()

    from app.services.cache import invalidate_discovery_caches

    invalidate_discovery_caches()
    return {"tipped": net, "fee": fee, "work_id": work_id, "public": tip.is_public}


def grant_remix_royalty(db: Session, source_owner_id: uuid.UUID, remix_cost: int) -> int:
    if remix_cost <= 0 or source_owner_id is None:
        return 0
    royalty = max(1, int(remix_cost * REMIX_ROYALTY_RATE))
    _wallet_credit(db, source_owner_id, royalty, source="remix_royalty")
    db.commit()
    return royalty


MEMBER_FREE_STEMS_PER_MONTH = 5
MEMBER_FREE_WAV_PER_MONTH = 10
MEMBER_FREE_COVERS_PER_MONTH = 3
MEMBER_FREE_MV_PER_MONTH = 1
AI_COVER_COST = 1


def _member_export_count_this_month(db: Session, user_id: uuid.UUID, export_type: str) -> int:
    from datetime import datetime

    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(WorkExport)
        .filter(
            WorkExport.user_id == user_id,
            WorkExport.export_type == export_type,
            WorkExport.created_at >= start,
        )
        .count()
    )


def _quota_item(
    db: Session,
    user_id: uuid.UUID,
    export_type: str,
    monthly_limit: int,
    *,
    is_member: bool,
    available: bool,
) -> dict[str, Any]:
    used = _member_export_count_this_month(db, user_id, export_type)
    limit = monthly_limit if is_member else 0
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "available": available,
    }


def export_capabilities() -> dict[str, bool]:
    """A quota row must not advertise an export this deploy cannot actually render."""
    from app.config import settings
    from app.services.mood_visual_export import ffmpeg_available

    ffmpeg = ffmpeg_available()
    return {
        "stems": ffmpeg,
        "hq_wav": ffmpeg,
        "mv_video": ffmpeg,
        "ai_cover": not settings.use_mock_ai,
    }


def get_member_export_quotas(db: Session, user: User) -> dict[str, Any]:
    is_member = is_active_subscriber(db, user.id)
    caps = export_capabilities()
    return {
        "is_member": is_member,
        "capabilities": caps,
        "stems": _quota_item(
            db, user.id, "stems", MEMBER_FREE_STEMS_PER_MONTH, is_member=is_member, available=caps["stems"]
        ),
        "hq_wav": _quota_item(
            db, user.id, "hq_wav", MEMBER_FREE_WAV_PER_MONTH, is_member=is_member, available=caps["hq_wav"]
        ),
        "ai_cover": _quota_item(
            db, user.id, "ai_cover", MEMBER_FREE_COVERS_PER_MONTH, is_member=is_member, available=caps["ai_cover"]
        ),
        "mv_video": _quota_item(
            db, user.id, "mv_video", MEMBER_FREE_MV_PER_MONTH, is_member=is_member, available=caps["mv_video"]
        ),
    }


def list_user_exports(db: Session, user_id: uuid.UUID, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        db.query(WorkExport)
        .filter(WorkExport.user_id == user_id)
        .order_by(WorkExport.created_at.desc())
        .limit(limit)
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row.meta or {}
        out.append(
            {
                "id": str(row.id),
                "work_id": str(row.work_id),
                "export_type": row.export_type,
                "status": row.status,
                "license_id": row.license_id,
                "download_url": meta.get("download_url") or meta.get("audio_url") or meta.get("cover_url"),
                "title": meta.get("title"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


def list_cn_recurring_waitlist(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        db.query(CnRecurringWaitlist, User.email)
        .join(User, User.id == CnRecurringWaitlist.user_id)
        .order_by(CnRecurringWaitlist.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "user_id": str(entry.user_id),
            "email": email,
            "channel": entry.channel,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry, email in rows
    ]


def _stem_pack_or_raise(work: Work) -> tuple[bytes, dict]:
    """Build a real zip. Never charge for a master MP3 disguised as stems."""
    from app.services.media import build_stem_pack
    from app.services.stem_assets import isolation_is_sellable
    from app.services.storage import get_storage_service

    source = b""
    if work.storage_key:
        try:
            source = get_storage_service().get_object_bytes(work.storage_key)
        except Exception:
            source = b""
    if not source:
        raise HTTPException(status_code=400, detail="Stem export needs the master file")
    pack, manifest = build_stem_pack(
        source,
        title=work.title or "track",
        duration=getattr(work, "duration", None),
        work=work,
    )
    if not pack or not isolation_is_sellable(manifest.get("isolation")):
        raise HTTPException(status_code=400, detail="Stem pack not ready")
    return pack, manifest


def _wav_or_raise(work: Work) -> tuple[bytes, dict]:
    """Build a real WAV. Never charge for a preview MP3 named .wav."""
    from app.services.media import transcode_audio
    from app.services.storage import get_storage_service

    if not work.storage_key:
        raise HTTPException(status_code=400, detail="WAV export needs the master file")
    try:
        source = get_storage_service().get_object_bytes(work.storage_key)
        wav = transcode_audio(source, fmt="wav") if source else None
    except Exception as exc:
        raise HTTPException(status_code=503, detail="WAV export unavailable") from exc
    if not wav:
        raise HTTPException(status_code=400, detail="WAV master not ready")
    return wav, {"format": "wav"}


def export_work(
    db: Session,
    user: User,
    work_id: str,
    export_type: str,
) -> dict[str, Any]:
    if export_type not in EXPORT_COSTS:
        raise HTTPException(status_code=400, detail="Unknown export type")

    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid work id") from exc

    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")

    cost = EXPORT_COSTS[export_type]
    is_member = is_active_subscriber(db, user.id)
    if export_type == "hq_mp3" and is_member:
        cost = 0
    if is_member:
        if export_type == "stems" and _member_export_count_this_month(db, user.id, "stems") < MEMBER_FREE_STEMS_PER_MONTH:
            cost = 0
        if export_type == "hq_wav" and _member_export_count_this_month(db, user.id, "hq_wav") < MEMBER_FREE_WAV_PER_MONTH:
            cost = 0
    stem_pack: bytes | None = None
    wav_bytes: bytes | None = None
    extra_meta: dict = {}
    if export_type == "stems":
        stem_pack, extra_meta = _stem_pack_or_raise(work)
    if export_type == "hq_wav":
        wav_bytes, extra_meta = _wav_or_raise(work)

    if cost > 0 and not deduct_credits(db, user.id, cost, source=f"export_{export_type}"):
        raise HTTPException(status_code=402, detail="Insufficient credits for export")

    license_id = None
    if export_type == "commercial_license":
        license_id = f"VSK-COM-{secrets.token_hex(8).upper()}"

    download_url = None
    if export_type == "stems" and stem_pack:
        from app.services.storage import get_storage_service

        try:
            key, url = get_storage_service().upload_bytes(
                stem_pack, f"exports/{user.id}/{work.id}-stems.zip", "application/zip"
            )
            extra_meta = {"storage_key": key, "format": "zip", **extra_meta}
            download_url = url
        except Exception as exc:
            if cost > 0:
                grant_credits_with_transaction(db, user.id, cost, source="export_stems_refund")
            raise HTTPException(status_code=500, detail="Stem upload failed") from exc
    if export_type == "hq_wav" and wav_bytes:
        from app.services.storage import get_storage_service

        try:
            key, url = get_storage_service().upload_bytes(
                wav_bytes, f"exports/{user.id}/{work.id}.wav", "audio/wav"
            )
            extra_meta = {"storage_key": key, "format": "wav"}
            download_url = url
        except Exception as exc:
            if cost > 0:
                grant_credits_with_transaction(db, user.id, cost, source="export_wav_refund")
            raise HTTPException(status_code=500, detail="WAV upload failed") from exc

    row = WorkExport(
        work_id=work.id,
        user_id=user.id,
        export_type=export_type,
        status="ready",
        license_id=license_id,
        meta={
            "audio_url": work.audio_url,
            "title": work.title,
            "format": "wav" if export_type == "hq_wav" else "mp3",
            "bitrate": "320k" if export_type in ("hq_mp3", "hq_wav") else "128k",
            "stems": extra_meta.get("stems") if export_type == "stems" else None,
            **extra_meta,
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    from app.services.media_playback import protected_stream_url

    if export_type == "stems" and not download_url:
        if cost > 0:
            grant_credits_with_transaction(db, user.id, cost, source="export_stems_refund")
        raise HTTPException(status_code=400, detail="Stem pack not ready")
    if export_type == "hq_wav" and not download_url:
        if cost > 0:
            grant_credits_with_transaction(db, user.id, cost, source="export_wav_refund")
        raise HTTPException(status_code=400, detail="WAV master not ready")

    return {
        "id": str(row.id),
        "export_type": export_type,
        "license_id": license_id,
        "download_url": download_url or protected_stream_url(work, user),
        "meta": row.meta,
    }


def ai_cover_cost(db: Session, user: User) -> int:
    is_member = is_active_subscriber(db, user.id)
    if is_member and _member_export_count_this_month(db, user.id, "ai_cover") < MEMBER_FREE_COVERS_PER_MONTH:
        return 0
    return AI_COVER_COST


def charge_ai_cover(db: Session, user: User) -> int:
    cost = ai_cover_cost(db, user)
    if cost > 0 and not deduct_credits(db, user.id, cost, source="ai_cover"):
        raise HTTPException(status_code=402, detail="Insufficient credits for AI cover")
    return cost


def record_ai_cover(db: Session, user: User, work: Work, *, cost: int) -> None:
    db.add(
        WorkExport(
            work_id=work.id,
            user_id=user.id,
            export_type="ai_cover",
            status="ready",
            meta={"cover_url": work.cover_url, "cost": cost},
        )
    )
    db.commit()


def create_support_ticket(
    db: Session,
    user: User,
    *,
    category: str,
    subject: str,
    body: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    if category not in ("refund", "billing", "technical"):
        raise HTTPException(status_code=400, detail="Invalid category")
    row = SupportTicket(
        user_id=user.id,
        category=category,
        order_id=order_id,
        subject=subject.strip()[:255],
        body=body.strip(),
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _ticket_dict(row)


def list_support_tickets(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        db.query(SupportTicket)
        .filter(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.created_at.desc())
        .limit(30)
        .all()
    )
    return [_ticket_dict(r) for r in rows]


def list_open_support_tickets(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        db.query(SupportTicket, User.email)
        .join(User, User.id == SupportTicket.user_id)
        .filter(SupportTicket.status.in_(("open", "in_review")))
        .order_by(SupportTicket.created_at.asc())
        .limit(limit)
        .all()
    )
    return [{**_ticket_dict(ticket), "user_email": email} for ticket, email in rows]


def resolve_support_ticket(
    db: Session,
    ticket_id: uuid.UUID,
    *,
    resolution: str,
    admin_note: str | None = None,
    credits_compensation: int = 0,
    stripe_refund_id: str | None = None,
) -> dict[str, Any]:
    row = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if resolution not in ("approved", "rejected", "credits_granted", "stripe_refunded"):
        raise HTTPException(status_code=400, detail="Invalid resolution")
    if credits_compensation > 0:
        grant_credits_with_transaction(
            db,
            row.user_id,
            credits_compensation,
            source="support_compensation",
            external_id=f"support_{row.id}",
        )
        row.credits_granted = credits_compensation
    row.resolution = resolution
    row.admin_note = admin_note
    row.stripe_refund_id = stripe_refund_id
    row.status = "resolved"
    row.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _ticket_dict(row)


def join_cn_recurring_waitlist(db: Session, user: User, *, channel: str = "wechat") -> dict[str, Any]:
    if channel not in ("wechat", "alipay"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    existing = (
        db.query(CnRecurringWaitlist)
        .filter(CnRecurringWaitlist.user_id == user.id, CnRecurringWaitlist.channel == channel)
        .first()
    )
    if existing:
        return {"joined": True, "channel": channel, "duplicate": True}
    db.add(CnRecurringWaitlist(user_id=user.id, channel=channel))
    db.commit()
    return {"joined": True, "channel": channel}


def _ticket_dict(row: SupportTicket) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "category": row.category,
        "order_id": row.order_id,
        "subject": row.subject,
        "body": row.body,
        "status": row.status,
        "admin_note": row.admin_note,
        "resolution": row.resolution,
        "credits_granted": row.credits_granted or 0,
        "stripe_refund_id": row.stripe_refund_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


SEED_RECIPES = [
    {
        "seed": "night-lit",
        "title": "夜店 lit",
        "description": "电子合成器、快板、激昂。适合短视频高潮。",
        "spec": {
            "instruments": ["synth"],
            "genres": ["electronic"],
            "moods": ["energetic"],
            "tempo_feel": "fast",
            "texture": "band",
            "key": "auto",
            "meter": "44",
            "era": "modern",
            "text_intent": "夜店 lit，合成器驱动的高潮",
            "style_tags": "electronic energetic club",
        },
    },
    {
        "seed": "late-lofi",
        "title": "深夜 lofi",
        "description": "钢琴与合成器、慢板、平静。适合夜间电台。",
        "spec": {
            "instruments": ["piano", "synth"],
            "genres": ["lofi"],
            "moods": ["calm", "nostalgic"],
            "tempo_feel": "slow",
            "texture": "solo",
            "key": "auto",
            "meter": "44",
            "era": "modern",
            "text_intent": "深夜 lofi，柔和磁带底噪",
            "style_tags": "lofi calm night",
        },
    },
    {
        "seed": "cinematic-strings",
        "title": "电影感弦乐",
        "description": "弦乐铺底、中速、希望。适合预告与广告。",
        "spec": {
            "instruments": ["strings", "piano"],
            "genres": ["cinematic"],
            "moods": ["hopeful"],
            "tempo_feel": "medium",
            "texture": "orchestral",
            "key": "auto",
            "meter": "44",
            "era": "modern",
            "text_intent": "电影感弦乐，由暗到明",
            "style_tags": "cinematic hopeful strings",
        },
    },
    {
        "seed": "folk-guitar",
        "title": "民谣吉他",
        "description": "原声吉他、中速、怀旧。适合做同款翻唱。",
        "spec": {
            "instruments": ["guitar"],
            "genres": ["folk"],
            "moods": ["nostalgic"],
            "tempo_feel": "medium",
            "texture": "solo",
            "key": "auto",
            "meter": "44",
            "era": "modern",
            "text_intent": "一把吉他把故事唱完",
            "style_tags": "folk acoustic nostalgic",
        },
    },
]

CATALOG_STEWARD_EMAIL = "catalog@bittune.local"
CATALOG_STEWARD_USERNAME = "bittune.catalog"


def ensure_catalog_owner(db: Session) -> User:
    steward = (
        db.query(User).filter(User.email == CATALOG_STEWARD_EMAIL).first()
        or db.query(User).filter(User.username == CATALOG_STEWARD_USERNAME).first()
    )
    if steward:
        return steward
    from app.services.auth import hash_password

    steward = User(
        email=CATALOG_STEWARD_EMAIL,
        username=CATALOG_STEWARD_USERNAME,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        display_name="比特音配方",
        is_active=True,
        is_admin=False,
    )
    db.add(steward)
    db.flush()
    return steward


def seed_recipe_catalog(db: Session) -> int:
    owner = ensure_catalog_owner(db)
    existing = {
        (row.spec or {}).get("seed")
        for row in db.query(RecipeTemplate).limit(200).all()
        if isinstance(row.spec, dict)
    }
    created = 0
    for item in SEED_RECIPES:
        if item["seed"] in existing:
            continue
        db.add(
            RecipeTemplate(
                owner_id=owner.id,
                title=item["title"],
                description=item["description"],
                spec={**item["spec"], "seed": item["seed"]},
                price_credits=0,
                is_public=True,
            )
        )
        created += 1
    return created


def recipe_spec_from_work(db: Session, work: Work) -> dict[str, Any]:
    from app.models.schemas import ProvenanceRecord

    spec: dict[str, Any] = {
        "instruments": [],
        "genres": list(work.genres or [])[:4],
        "moods": list(work.moods or [])[:4],
        "tempo_feel": "",
        "key": "auto",
        "texture": "",
        "meter": "",
        "era": "",
        "text_intent": work.title or "",
        "style_tags": " ".join(list(work.moods or [])[:3]),
        "arousal": work.arousal,
        "valence": work.valence,
        "reference_work_id": str(work.id),
    }
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    blob = prov.music_request if prov and isinstance(prov.music_request, dict) else {}
    if blob.get("style_tags"):
        spec["style_tags"] = str(blob["style_tags"])
    if blob.get("key"):
        spec["key"] = str(blob["key"])
    if blob.get("bpm") is not None:
        try:
            spec["bpm"] = int(blob["bpm"])
        except (TypeError, ValueError):
            pass
    if blob.get("text_intent"):
        spec["text_intent"] = str(blob["text_intent"])
    return spec


def publish_recipe_from_work(
    db: Session,
    user: User,
    work_id: str,
    *,
    title: str | None = None,
    price_credits: int = 0,
) -> dict[str, Any]:
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid work id") from exc
    work = db.query(Work).filter(Work.id == wid, Work.owner_id == user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if not work.audio_url:
        raise HTTPException(status_code=400, detail="Work has no audio")
    spec = recipe_spec_from_work(db, work)
    for row in (
        db.query(RecipeTemplate)
        .filter(RecipeTemplate.owner_id == user.id)
        .order_by(RecipeTemplate.created_at.desc())
        .limit(40)
        .all()
    ):
        prev = row.spec if isinstance(row.spec, dict) else {}
        if prev.get("reference_work_id") == str(work.id):
            row.title = (title or work.title or row.title).strip()
            row.description = f"从《{work.title}》抽出的听感配方"
            row.spec = spec
            row.price_credits = max(0, min(50, price_credits))
            db.commit()
            db.refresh(row)
            return {"id": str(row.id), "title": row.title, "price_credits": row.price_credits, "updated": True}
    return create_recipe_template(
        db,
        user,
        title=(title or work.title or "未命名配方").strip(),
        description=f"从《{work.title}》抽出的听感配方",
        spec=spec,
        price_credits=price_credits,
    )


def list_recipe_templates(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    if seed_recipe_catalog(db):
        db.commit()
    rows = (
        db.query(RecipeTemplate, User.username, User.display_name)
        .outerjoin(User, User.id == RecipeTemplate.owner_id)
        .filter(RecipeTemplate.is_public == True)
        .order_by(RecipeTemplate.purchase_count.desc(), RecipeTemplate.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r, username, display_name in rows:
        spec = r.spec if isinstance(r.spec, dict) else {}
        author = display_name or username
        if username == CATALOG_STEWARD_USERNAME:
            author = "比特音"
        out.append(
            {
                "id": str(r.id),
                "title": r.title,
                "description": r.description,
                "price_credits": r.price_credits,
                "purchase_count": r.purchase_count,
                "author_username": author,
                "moods": list(spec.get("moods") or [])[:4],
                "genres": list(spec.get("genres") or [])[:4],
            }
        )
    return out


def create_recipe_template(
    db: Session,
    user: User,
    *,
    title: str,
    description: str | None,
    spec: dict,
    price_credits: int = 0,
) -> dict[str, Any]:
    row = RecipeTemplate(
        owner_id=user.id,
        title=title.strip(),
        description=description,
        spec=spec,
        price_credits=max(0, min(50, price_credits)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "title": row.title, "price_credits": row.price_credits}


def purchase_recipe_template(db: Session, buyer: User, template_id: str) -> dict[str, Any]:
    try:
        tid = uuid.UUID(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid template id") from exc

    template = db.query(RecipeTemplate).filter(RecipeTemplate.id == tid, RecipeTemplate.is_public == True).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    spec = template.spec if isinstance(template.spec, dict) else {}
    if template.owner_id == buyer.id:
        return {"spec": spec, "owned": True, "reference_work_id": spec.get("reference_work_id")}

    existing = (
        db.query(RecipeTemplatePurchase)
        .filter(RecipeTemplatePurchase.template_id == tid, RecipeTemplatePurchase.buyer_id == buyer.id)
        .first()
    )
    if existing:
        return {"spec": spec, "owned": True, "reference_work_id": spec.get("reference_work_id")}

    price = template.price_credits or 0
    if price > 0:
        if not deduct_credits(db, buyer.id, price, source="template_purchase"):
            raise HTTPException(status_code=402, detail="Insufficient credits")
        platform_fee = max(1, int(price * TEMPLATE_PLATFORM_FEE_RATE))
        creator_share = price - platform_fee
        _wallet_credit(db, template.owner_id, creator_share, source="template_sale")

    db.add(
        RecipeTemplatePurchase(
            template_id=tid,
            buyer_id=buyer.id,
            credits_paid=price,
        )
    )
    template.purchase_count = (template.purchase_count or 0) + 1
    db.commit()
    spec = template.spec if isinstance(template.spec, dict) else {}
    return {
        "spec": spec,
        "purchased": True,
        "credits_paid": price,
        "reference_work_id": spec.get("reference_work_id"),
    }


def create_paid_work_pack(
    db: Session,
    user: User,
    *,
    title: str,
    work_ids: list[str],
    price_credits: int,
) -> dict[str, Any]:
    if price_credits < 5 or price_credits > 50:
        raise HTTPException(status_code=400, detail="Price must be 5–50 credits")
    pack = PaidWorkPack(
        owner_id=user.id,
        title=title.strip(),
        work_ids=work_ids,
        price_credits=price_credits,
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return {"id": str(pack.id), "title": pack.title, "price_credits": pack.price_credits}


def list_work_packs(db: Session, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = (
        db.query(PaidWorkPack)
        .filter(PaidWorkPack.is_active == True)
        .order_by(PaidWorkPack.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []
    owner_ids = list({r.owner_id for r in rows})
    owners = {u.id: u.username for u in db.query(User).filter(User.id.in_(owner_ids)).all()}
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "price_credits": r.price_credits,
            "work_count": len(r.work_ids or []),
            "owner_username": owners.get(r.owner_id),
        }
        for r in rows
    ]


def list_work_packs_for_user(db: Session, *, username: str) -> list[dict[str, Any]]:
    from app.models.schemas import User

    owner = db.query(User).filter(User.username == username).first()
    if not owner:
        return []
    rows = (
        db.query(PaidWorkPack)
        .filter(PaidWorkPack.owner_id == owner.id, PaidWorkPack.is_active == True)
        .order_by(PaidWorkPack.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "price_credits": r.price_credits,
            "work_count": len(r.work_ids or []),
            "owner_username": username,
        }
        for r in rows
    ]


def purchase_work_pack(db: Session, buyer: User, pack_id: str) -> dict[str, Any]:
    try:
        pid = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pack id") from exc

    pack = db.query(PaidWorkPack).filter(PaidWorkPack.id == pid, PaidWorkPack.is_active == True).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    if pack.owner_id == buyer.id:
        raise HTTPException(status_code=400, detail="Cannot buy your own pack")
    if not deduct_credits(db, buyer.id, pack.price_credits, source="work_pack_purchase"):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    fee = max(1, int(pack.price_credits * PLATFORM_TIP_FEE_RATE))
    _wallet_credit(db, pack.owner_id, pack.price_credits - fee, source="work_pack_sale")
    pack.purchase_count = (pack.purchase_count or 0) + 1
    db.commit()
    return {"work_ids": pack.work_ids, "title": pack.title}


def get_creator_wallet(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    from app.models.schemas import CreditTransaction, CreatorTip

    wallet = db.query(CreatorWallet).filter(CreatorWallet.user_id == user_id).first()
    tips = (
        db.query(CreatorTip)
        .filter(CreatorTip.to_user_id == user_id)
        .order_by(CreatorTip.created_at.desc())
        .limit(20)
        .all()
    )
    remix_rows = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.user_id == user_id, CreditTransaction.source == "remix_royalty")
        .order_by(CreditTransaction.created_at.desc())
        .limit(20)
        .all()
    )
    remix_credits_7d = sum(tx.credits for tx in remix_rows[:7])
    remix_ledger = [
        {
            "credits": tx.credits,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx in remix_rows
        if tx.credits
    ]
    return {
        "balance_credits": wallet.balance_credits if wallet else 0,
        "lifetime_earned": wallet.lifetime_earned if wallet else 0,
        "ledger": "credits",
        "recent_tips": [
            {
                "amount": t.credits,
                "from_user_id": str(t.from_user_id),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tips
        ],
        # Remix split is credit fuel, never fiat. Zero stays hidden on the client.
        "remix_credits_7d": remix_credits_7d,
        "recent_remix_credits": remix_ledger,
        "estimated_weekly_royalty": remix_credits_7d,
        "recent_royalties": remix_ledger,
    }


def list_public_tips_for_work(db: Session, work_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    try:
        wid = uuid.UUID(work_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid work id") from exc

    rows = (
        db.query(CreatorTip, User)
        .join(User, User.id == CreatorTip.from_user_id)
        .filter(CreatorTip.work_id == wid, CreatorTip.is_public == True)
        .order_by(CreatorTip.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "username": user.username,
            "credits": tip.credits,
            "message": tip.public_message,
            "created_at": tip.created_at.isoformat() if tip.created_at else None,
        }
        for tip, user in rows
    ]


def request_invoice(
    db: Session,
    user: User,
    *,
    order_id: str,
    title: str,
    email: str,
    tax_id: str | None = None,
) -> dict[str, Any]:
    row = InvoiceRequest(
        user_id=user.id,
        order_id=order_id,
        title=title.strip(),
        email=email.strip(),
        tax_id=tax_id,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status, "message": "发票申请已提交，将在 3 个工作日内发送至邮箱"}


def list_user_invoices(db: Session, user_id: uuid.UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        db.query(InvoiceRequest)
        .filter(InvoiceRequest.user_id == user_id)
        .order_by(InvoiceRequest.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "order_id": r.order_id,
            "title": r.title,
            "email": r.email,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def distribute_challenge_prizes(db: Session, challenge_id: uuid.UUID) -> int:
    """Delegate to challenge_awards for full prize + notification flow."""
    from app.models.schemas import Challenge
    from app.services.challenge_awards import distribute_challenge_prizes as distribute

    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        return 0
    result = distribute(db, challenge)
    if result.get("skipped"):
        return 0
    return int(result.get("awarded") or 0)
