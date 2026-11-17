import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.config import settings
from app.services.credits import add_credits
from app.database import get_db
from app.models.schemas import (
    ApiUsageLog,
    Challenge,
    Comment,
    FeatureFlag,
    GenerationJob,
    Post,
    Report,
    StylePreset,
    User,
    Work,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    config: dict | None = None


class ReportResolve(BaseModel):
    status: str = "resolved"
    action: str | None = None


class CreditGrantRequest(BaseModel):
    email: str | None = None
    user_id: str | None = None
    amount: int = Field(gt=0, le=100_000)


class TenantAssignRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")


class KycStatusBody(BaseModel):
    status: str = Field(pattern=r"^(none|pending|verified|rejected)$")


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=255)
    plan: str = Field(default="free", pattern=r"^(free|member|team|enterprise)$")
    invite_code: str | None = Field(default=None, max_length=32)
    initial_credits: int = Field(default=0, ge=0, le=100000)


class TenantPoolGrantRequest(BaseModel):
    amount: int = Field(gt=0, le=100000)


class StylePresetUpsert(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    label: str = Field(min_length=1, max_length=255)
    category: str = Field(default="scene", max_length=64)
    description: str | None = None
    example_intent: str | None = None
    moods: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    bpm_range: list[int] = Field(default_factory=lambda: [80, 120])
    key: str = "auto"
    duration_preference: str = "medium"
    default_curve: str = "neutral"
    waypoint_template: list[dict] = Field(default_factory=list)
    instrumental_default: bool = True
    tenant_id: str = "default"
    sort_order: int = 0
    enabled: bool = True


@router.get("/tenants")
def list_tenant_stats(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import func

    user_rows = (
        db.query(User.tenant_id, func.count(User.id))
        .group_by(User.tenant_id)
        .all()
    )
    work_rows = (
        db.query(Work.tenant_id, func.count(Work.id))
        .group_by(Work.tenant_id)
        .all()
    )
    post_rows = (
        db.query(Post.tenant_id, func.count(Post.id))
        .group_by(Post.tenant_id)
        .all()
    )
    tenants: dict[str, dict[str, int]] = {}
    for tid, count in user_rows:
        key = tid or "default"
        tenants.setdefault(key, {"users": 0, "works": 0, "posts": 0})
        tenants[key]["users"] = count
    for tid, count in work_rows:
        key = tid or "default"
        tenants.setdefault(key, {"users": 0, "works": 0, "posts": 0})
        tenants[key]["works"] = count
    for tid, count in post_rows:
        key = tid or "default"
        tenants.setdefault(key, {"users": 0, "works": 0, "posts": 0})
        tenants[key]["posts"] = count
    return [{"tenant_id": k, **v} for k, v in sorted(tenants.items())]


@router.post("/tenants/create")
def create_tenant(
    payload: TenantCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.schemas import Tenant
    from app.services.tenant import get_or_create_tenant

    if db.query(Tenant).filter(Tenant.id == payload.tenant_id).first():
        raise HTTPException(status_code=400, detail="Tenant already exists")
    tenant = Tenant(
        id=payload.tenant_id,
        name=payload.name.strip(),
        plan=payload.plan,
        invite_code=payload.invite_code.strip() if payload.invite_code else None,
        credit_pool=payload.initial_credits,
    )
    db.add(tenant)
    db.commit()
    return {
        "tenant_id": tenant.id,
        "name": tenant.name,
        "plan": tenant.plan,
        "credit_pool": tenant.credit_pool,
        "invite_code": tenant.invite_code,
    }


@router.post("/tenants/{tenant_id}/credits")
def grant_tenant_pool(
    tenant_id: str,
    payload: TenantPoolGrantRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.tenant import get_or_create_tenant

    tenant = get_or_create_tenant(db, tenant_id)
    tenant.credit_pool += payload.amount
    db.commit()
    return {"tenant_id": tenant.id, "credit_pool": tenant.credit_pool, "granted": payload.amount}


@router.put("/users/{user_id}/tenant-admin")
def set_tenant_admin(
    user_id: str,
    enabled: bool = True,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_tenant_admin = enabled
    db.commit()
    return {"user_id": str(target.id), "username": target.username, "is_tenant_admin": target.is_tenant_admin}


@router.put("/users/{user_id}/tenant")
def assign_user_tenant(
    user_id: str,
    payload: TenantAssignRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.tenant_id = payload.tenant_id.strip()
    db.commit()
    return {"user_id": str(target.id), "username": target.username, "tenant_id": target.tenant_id}


@router.patch("/users/{user_id}/kyc")
def admin_set_kyc(
    user_id: str,
    payload: KycStatusBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action

    target = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.kyc_status = payload.status
    db.commit()
    log_admin_action(db, admin_id=admin.id, action="set_kyc", target=user_id, detail={"status": payload.status})
    return {"user_id": str(target.id), "kyc_status": target.kyc_status}


def _set_user_banned(db: Session, target: User, *, banned: bool, admin: User) -> dict:
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")
    if banned and target.is_admin:
        others = db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True), User.id != target.id).count()
        if others <= 0:
            raise HTTPException(status_code=400, detail="Cannot ban the last admin")
    target.is_active = not banned
    from app.api.routes.auth import invalidate_me_cache

    invalidate_me_cache(target.id)
    db.commit()
    from app.services.admin_audit import log_admin_action

    log_admin_action(db, admin_id=admin.id, action="ban_user" if banned else "unban_user", target=str(target.id))
    return {"user_id": str(target.id), "username": target.username, "is_active": bool(target.is_active), "banned": banned}


@router.get("/users")
def admin_list_users(
    q: str | None = Query(default=None),
    banned: bool | None = Query(default=None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if banned is True:
        query = query.filter(User.is_active.is_(False))
    elif banned is False:
        query = query.filter(User.is_active.is_(True))
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        query = query.filter((User.email.ilike(like)) | (User.username.ilike(like)))
    rows = query.order_by(User.created_at.desc()).limit(40).all()
    return {
        "users": [
            {
                "id": str(row.id),
                "email": row.email,
                "username": row.username,
                "display_name": row.display_name,
                "is_active": bool(row.is_active),
                "is_admin": bool(row.is_admin),
                "kyc_status": row.kyc_status or "none",
            }
            for row in rows
        ]
    }


@router.post("/users/{user_id}/ban")
def admin_ban_user(user_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return _set_user_banned(db, target, banned=True, admin=admin)


@router.delete("/users/{user_id}/ban")
def admin_unban_user(user_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return _set_user_banned(db, target, banned=False, admin=admin)


@router.get("/kyc")
def admin_kyc_queue(
    status: str = Query(default="pending"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    allowed = {"none", "pending", "verified", "rejected"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid KYC status")
    rows = (
        db.query(User)
        .filter(User.kyc_status == status)
        .order_by(User.created_at.desc())
        .limit(80)
        .all()
    )
    return {
        "status": status,
        "users": [
            {
                "id": str(row.id),
                "email": row.email,
                "username": row.username,
                "kyc_status": row.kyc_status or "none",
            }
            for row in rows
        ],
    }


@router.post("/credits/grant")
def grant_credits(
    payload: CreditGrantRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.amount <= 0 or payload.amount > 100_000:
        raise HTTPException(status_code=400, detail="Invalid amount")
    target: User | None = None
    if payload.user_id:
        target = db.query(User).filter(User.id == uuid.UUID(payload.user_id)).first()
    elif payload.email:
        target = db.query(User).filter(User.email == payload.email.strip()).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    row = add_credits(db, target.id, payload.amount)
    from app.services.admin_audit import log_admin_action

    log_admin_action(
        db,
        admin_id=user.id,
        action="credits_grant",
        target=str(target.id),
        detail={"amount": payload.amount, "email": target.email},
    )
    return {
        "user_id": str(target.id),
        "username": target.username,
        "email": target.email,
        "balance": row.balance,
        "granted": payload.amount,
    }


@router.get("/commercial")
def admin_commercial(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import func

    from app.models.schemas import CreditTransaction, PaymentOrder, User
    from app.services.analytics import conversion_funnel
    from app.services.payment_orders import commercial_stats

    paid_orders = (
        db.query(PaymentOrder.pack_id, func.count(PaymentOrder.id))
        .filter(PaymentOrder.status == "paid")
        .group_by(PaymentOrder.pack_id)
        .all()
    )
    grants = (
        db.query(CreditTransaction.source, func.sum(CreditTransaction.credits))
        .filter(CreditTransaction.credits > 0)
        .group_by(CreditTransaction.source)
        .all()
    )
    spends = (
        db.query(func.sum(CreditTransaction.credits))
        .filter(CreditTransaction.credits < 0)
        .scalar()
    ) or 0
    duel_starts = (
        db.query(func.count(CreditTransaction.id))
        .filter(CreditTransaction.source == "duel_start")
        .scalar()
    ) or 0
    return {
        "billing_30d": commercial_stats(db, days=30),
        "pack_distribution": {pid: count for pid, count in paid_orders},
        "credit_grants_by_source": {src: int(total or 0) for src, total in grants},
        "total_credits_spent": abs(int(spends)),
        "duel_starts_count": int(duel_starts),
        "users": db.query(User).count(),
        "conversion_funnel_30d": conversion_funnel(db, days=30),
    }


@router.get("/stats")
def admin_stats(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.analytics import conversion_stats
    from app.services.payment_orders import commercial_stats

    return {
        "users": db.query(User).count(),
        "works": db.query(Work).count(),
        "jobs": db.query(GenerationJob).count(),
        "posts": db.query(Post).count(),
        "challenges": db.query(Challenge).count(),
        "pending_reports": db.query(Report).filter(Report.status == "pending").count(),
        "pipeline_version": settings.pipeline_version,
        "mock_ai_enabled": settings.use_mock_ai,
        "c2pa_enabled": settings.c2pa_enabled,
        "analytics_events_30d": conversion_stats(db, days=30),
        "billing_30d": commercial_stats(db, days=30),
    }


@router.get("/queue-metrics")
def admin_queue_metrics(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.queue_metrics import admin_queue_snapshot

    return admin_queue_snapshot(db)


@router.get("/activation-funnel")
def admin_activation_funnel(
    days: int = 30,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.analytics import activation_funnel

    return activation_funnel(db, days=days)


@router.get("/audit-logs")
def admin_audit_logs(
    limit: int = 50,
    action: str | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.schemas import AdminAuditLog

    query = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    if action:
        query = query.filter(AdminAuditLog.action == action)
    rows = query.limit(min(limit, 200)).all()
    return [
        {
            "id": str(r.id),
            "admin_id": str(r.admin_id),
            "action": r.action,
            "target": r.target,
            "detail": r.detail or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/usage")
def api_usage(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    logs = db.query(ApiUsageLog).order_by(ApiUsageLog.created_at.desc()).limit(100).all()
    return [
        {
            "provider": log.provider,
            "model": log.model,
            "endpoint": log.endpoint,
            "tokens_used": log.tokens_used,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get("/reports")
def list_reports(
    status: str = "pending",
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    reports = db.query(Report).filter(Report.status == status).order_by(Report.created_at.desc()).limit(100).all()
    comment_ids = [r.comment_id for r in reports if r.comment_id]
    comments = (
        {c.id: c for c in db.query(Comment).filter(Comment.id.in_(comment_ids)).all()}
        if comment_ids
        else {}
    )
    return [
        {
            "id": str(r.id),
            "reason": r.reason,
            "status": r.status,
            "post_id": str(r.post_id) if r.post_id else None,
            "work_id": str(r.work_id) if r.work_id else None,
            "comment_id": str(r.comment_id) if r.comment_id else None,
            "comment_preview": (
                (comments[r.comment_id].content or "")[:120]
                if r.comment_id and r.comment_id in comments
                else None
            ),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


@router.post("/reports/{report_id}/resolve")
def resolve_report(
    report_id: str,
    payload: ReportResolve,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    report = db.query(Report).filter(Report.id == uuid.UUID(report_id)).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = payload.status
    if payload.action == "hide_post" and report.post_id:
        post = db.query(Post).filter(Post.id == report.post_id).first()
        if post:
            post.visibility = "hidden"
    elif payload.action == "hide_comment" and report.comment_id:
        comment = db.query(Comment).filter(Comment.id == report.comment_id).first()
        if comment:
            comment.is_filtered = True
            comment.content = "[内容已隐藏]"
    elif payload.action == "ban_user":
        target = None
        if report.work_id:
            work = db.query(Work).filter(Work.id == report.work_id).first()
            if work:
                target = db.query(User).filter(User.id == work.owner_id).first()
        if target is None and report.post_id:
            post = db.query(Post).filter(Post.id == report.post_id).first()
            if post:
                target = db.query(User).filter(User.id == post.author_id).first()
        if target is None and report.comment_id:
            comment = db.query(Comment).filter(Comment.id == report.comment_id).first()
            if comment:
                target = db.query(User).filter(User.id == comment.user_id).first()
        if target:
            _set_user_banned(db, target, banned=True, admin=user)
    db.commit()
    from app.services.admin_audit import log_admin_action

    log_admin_action(
        db,
        admin_id=user.id,
        action="report_resolve",
        target=report_id,
        detail={"status": payload.status, "action": payload.action},
    )
    return {"status": report.status}


@router.get("/flags")
def list_flags(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    flags = db.query(FeatureFlag).all()
    return [{"key": f.key, "enabled": f.enabled, "description": f.description, "config": f.config} for f in flags]


@router.put("/flags/{key}")
def update_flag(
    key: str,
    payload: FeatureFlagUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if not flag:
        flag = FeatureFlag(key=key, enabled=payload.enabled, config=payload.config or {})
        db.add(flag)
    else:
        flag.enabled = payload.enabled
        if payload.config is not None:
            flag.config = payload.config
    db.commit()
    from app.services.admin_audit import log_admin_action

    log_admin_action(
        db,
        admin_id=user.id,
        action="flag_update",
        target=key,
        detail={"enabled": payload.enabled},
    )
    from app.services.cache import cache_clear

    cache_clear("flags:public")
    return {"key": key, "enabled": flag.enabled}


@router.post("/seed")
def seed_defaults(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Seed default challenges, feature flags, and style presets."""
    from app.core.style_presets import seed_builtin_presets

    defaults_flags = [
        ("music_cover", False, "Enable AI cover generation during post-process"),
        ("hls_streaming", True, "Enable HLS transcoding"),
        ("c2pa_provenance", settings.c2pa_enabled, "Enable C2PA manifests"),
        ("personalized_feed", True, "Enable embedding-based feed ranking"),
        ("credits_gate", settings.credits_gate_enabled, "Enable generation credits gate (402 when insufficient)"),
        ("multi_tenant", False, "Enable tenant_id isolation on feed and works"),
        ("dsp_distribution", True, "Enable DSP distribution and creator releases"),
        ("royalty_wallet", True, "Enable fiat royalty wallet and withdrawals"),
        ("release_qc", True, "Enable release-ready QC before distribution"),
    ]
    for key, enabled, desc in defaults_flags:
        if not db.query(FeatureFlag).filter(FeatureFlag.key == key).first():
            db.add(FeatureFlag(key=key, enabled=enabled, description=desc))

    if not db.query(Challenge).filter(Challenge.slug == "calm-to-chaos").first():
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        db.add(Challenge(
            slug="calm-to-chaos",
            title="Calm to Chaos 情绪挑战",
            description="从平静到混沌，用 6 首作品讲述你的情绪旅程",
            hashtag="CalmToChaos",
            target_curve="calm_to_energy",
            starts_at=now,
            ends_at=now + timedelta(days=14),
            prize_pool_credits=50,
            prize_winners=3,
        ))
    presets_seeded = seed_builtin_presets(db)
    from app.core.style_presets import sync_member_presets
    from app.services.distribution.catalog import seed_distribution_catalog

    member_synced = sync_member_presets(db)
    seed_distribution_catalog(db)
    db.commit()
    return {"status": "seeded", "presets_seeded": presets_seeded, "member_presets_synced": member_synced}


@router.get("/presets")
def admin_list_presets(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(StylePreset).order_by(StylePreset.sort_order.asc(), StylePreset.id.asc()).all()
    return [
        {
            "id": r.id,
            "label": r.label,
            "category": r.category,
            "description": r.description,
            "enabled": r.enabled,
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


@router.post("/presets")
def admin_create_preset(
    payload: StylePresetUpsert,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.cache import cache_clear

    if db.query(StylePreset).filter(StylePreset.id == payload.id).first():
        raise HTTPException(status_code=409, detail="Preset id already exists")
    row = StylePreset(**payload.model_dump())
    db.add(row)
    db.commit()
    cache_clear("presets:")
    return {"id": row.id}


@router.put("/presets/{preset_id}")
def admin_update_preset(
    preset_id: str,
    payload: StylePresetUpsert,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.cache import cache_clear

    row = db.query(StylePreset).filter(StylePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    data = payload.model_dump()
    if data["id"] != preset_id:
        raise HTTPException(status_code=400, detail="Preset id mismatch")
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    cache_clear("presets:")
    return {"id": row.id}


@router.delete("/presets/{preset_id}")
def admin_delete_preset(
    preset_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.cache import cache_clear

    row = db.query(StylePreset).filter(StylePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    row.enabled = False
    db.commit()
    cache_clear("presets:")
    return {"id": preset_id, "enabled": False}


class ModerationWordUpsert(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)
    category: str = Field(default="general", max_length=64)
    level: str = Field(default="block", pattern=r"^(block|mask)$")
    enabled: bool = True


@router.get("/moderation-words")
def admin_list_moderation_words(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models.schemas import ModerationWord

    rows = db.query(ModerationWord).order_by(ModerationWord.created_at.desc()).all()
    return [
        {
            "id": str(r.id),
            "pattern": r.pattern,
            "category": r.category,
            "level": r.level,
            "enabled": r.enabled,
        }
        for r in rows
    ]


@router.post("/moderation-words")
def admin_create_moderation_word(
    payload: ModerationWordUpsert,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.schemas import ModerationWord
    from app.services.content_moderation import invalidate_word_cache

    row = ModerationWord(
        pattern=payload.pattern,
        category=payload.category,
        level=payload.level,
        enabled=payload.enabled,
    )
    db.add(row)
    db.commit()
    invalidate_word_cache()
    return {"id": str(row.id)}


@router.delete("/moderation-words/{word_id}")
def admin_delete_moderation_word(
    word_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models.schemas import ModerationWord
    from app.services.content_moderation import invalidate_word_cache

    row = db.query(ModerationWord).filter(ModerationWord.id == uuid.UUID(word_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Word not found")
    row.enabled = False
    db.commit()
    invalidate_word_cache()
    return {"disabled": True}


@router.post("/challenges/{slug}/finalize")
def admin_finalize_challenge(
    slug: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.challenge_awards import distribute_challenge_prizes

    c = db.query(Challenge).filter(Challenge.slug == slug).first()
    if not c:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return distribute_challenge_prizes(db, c)


class DeliveryStatusBody(BaseModel):
    status: str
    reason: str | None = None
    store_url: str | None = None
    external_id: str | None = None


class MarkReleaseLiveBody(BaseModel):
    store_url: str | None = None


class WithdrawalReviewBody(BaseModel):
    approve: bool = True
    admin_note: str | None = None


class SettlementRunBody(BaseModel):
    period_key: str | None = None


class ConnectorMatchBody(BaseModel):
    work_id: str


@router.get("/distribution/deliveries")
def admin_deliveries(
    status: str | None = Query(default=None),
    queue_only: bool = Query(default=False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.distribution.service import admin_list_deliveries

    return {"deliveries": admin_list_deliveries(db, status=status, queue_only=queue_only)}


@router.post("/distribution/deliveries/{delivery_id}/retry")
def admin_retry_delivery(delivery_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.models.schemas import DistributionDelivery
    from app.services.distribution.pipeline import dispatch_delivery, process_one_delivery

    try:
        did = uuid.UUID(delivery_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid delivery id") from exc
    row = db.query(DistributionDelivery).filter(DistributionDelivery.id == did).first()
    if not row:
        raise HTTPException(404, "Delivery not found")
    if row.status in ("live", "taken_down"):
        raise HTTPException(400, "Delivery is already closed")
    row.status = "submitting"
    row.next_retry_at = None
    row.last_error = None
    db.commit()
    result = process_one_delivery(db, row, force=True, commit=True)
    if result.get("status") == "submitting":
        dispatch_delivery(str(row.id), str(row.release_id), process_now=False)
    log_admin_action(db, admin_id=user.id, action="retry_delivery", target=delivery_id, detail=result)
    return result


@router.post("/distribution/deliveries/{delivery_id}/claim")
def admin_claim_delivery(delivery_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.distribution.service import claim_delivery

    result = claim_delivery(db, user, delivery_id)
    log_admin_action(db, admin_id=user.id, action="claim_delivery", target=delivery_id, detail={"claimed_by": result.get("claimed_by")})
    return result


@router.post("/distribution/deliveries/{delivery_id}/unclaim")
def admin_unclaim_delivery(delivery_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.distribution.service import unclaim_delivery

    result = unclaim_delivery(db, user, delivery_id)
    log_admin_action(db, admin_id=user.id, action="unclaim_delivery", target=delivery_id)
    return result


@router.get("/distribution/deliveries/{delivery_id}/pack")
def admin_delivery_pack(delivery_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.distribution.service import delivery_ops_pack

    return delivery_ops_pack(db, delivery_id)


@router.get("/distribution/releases/{release_id}/workbench")
def admin_release_workbench(release_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.distribution.service import release_ops_workbench

    return release_ops_workbench(db, release_id, admin=user)


@router.post("/distribution/reconcile")
def admin_reconcile_distribution(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.distribution.pipeline import reconcile_distribution

    result = reconcile_distribution(db)
    log_admin_action(db, admin_id=user.id, action="reconcile_distribution", target="platform", detail=result)
    return result


@router.get("/distribution/health")
def admin_distribution_health(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.distribution.pipeline import distribution_health

    return distribution_health(db)


@router.get("/seats/health")
def admin_seats_health(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models.schemas import CreatorSeat, SeatJob
    from app.services.seats.service import serialize_seat

    seats = db.query(CreatorSeat).order_by(CreatorSeat.ownership.desc(), CreatorSeat.channel_code.asc()).all()
    queued = db.query(SeatJob).filter(SeatJob.status == "queued").count()
    failed = db.query(SeatJob).filter(SeatJob.status == "failed").count()
    login_wall = sum(1 for row in seats if row.status in ("needs_challenge", "expired", "needs_session"))
    broke = set()
    for row in seats:
        health = (row.extra or {}).get("farm_health") or {}
        err = str(health.get("error") or "")
        if health.get("selector_broke") or err in ("selector_broke", "no_rows"):
            broke.add(str(row.id))
    recent = (
        db.query(SeatJob)
        .filter(SeatJob.status.in_(("failed", "done")))
        .order_by(SeatJob.created_at.desc())
        .limit(80)
        .all()
    )
    for job in recent:
        payload = job.result if isinstance(job.result, dict) else {}
        err = str(payload.get("error") or "")
        if payload.get("selector_broke") or err in ("selector_broke", "no_rows"):
            broke.add(str(job.seat_id))
    selector_broke = len(broke)
    from app.services.harvest.playbooks import playbook_health

    patrol_failed = 0
    for row in seats:
        extra = row.extra if isinstance(row.extra, dict) else {}
        health = extra.get("farm_health") if isinstance(extra.get("farm_health"), dict) else {}
        if extra.get("patrol_error") or health.get("error") or health.get("ok") is False:
            patrol_failed += 1

    return {
        "queued": queued,
        "failed": failed,
        "selector_broke": selector_broke,
        "login_wall": login_wall,
        "patrol_failed": patrol_failed,
        "seats": [
            {
                **serialize_seat(row),
                "farm_health": (row.extra or {}).get("farm_health"),
                "playbook_health": playbook_health(row.channel_code),
            }
            for row in seats
        ],
    }


@router.get("/distribution/connector/batches")
def admin_connector_batches(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty import connector as connector_svc

    return {"batches": connector_svc.list_batches(db)}


@router.get("/distribution/connector/claims")
def admin_connector_claims(status: str = Query(default="unclaimed"), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty import connector as connector_svc

    return {"claims": connector_svc.list_claims(db, status=status)}


@router.post("/distribution/connector/batches/{batch_id}/confirm")
def admin_confirm_connector_batch(batch_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty import connector as connector_svc

    result = connector_svc.confirm_batch(db, batch_id)
    log_admin_action(db, admin_id=user.id, action="confirm_connector_batch", target=batch_id, detail=result)
    return result


@router.post("/distribution/connector/claims/{claim_id}/match")
def admin_match_connector_claim(
    claim_id: str,
    payload: ConnectorMatchBody,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty import connector as connector_svc

    result = connector_svc.match_claim(db, claim_id, payload.work_id, user, admin=True)
    log_admin_action(db, admin_id=user.id, action="match_connector_claim", target=claim_id, detail=result)
    return result


@router.post("/distribution/deliveries/{delivery_id}/status")
def admin_delivery_status(
    delivery_id: str,
    payload: DeliveryStatusBody,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.distribution.service import admin_set_delivery_status

    result = admin_set_delivery_status(
        db,
        delivery_id,
        payload.status,
        payload.reason,
        store_url=payload.store_url,
        external_id=payload.external_id,
    )
    log_admin_action(db, admin_id=user.id, action="delivery_status", target=delivery_id, detail=payload.model_dump())
    return result


@router.post("/distribution/releases/{release_id}/mark-live")
def admin_release_live(
    release_id: str,
    payload: MarkReleaseLiveBody,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.distribution.service import admin_mark_release_live

    result = admin_mark_release_live(db, release_id, payload.store_url)
    log_admin_action(db, admin_id=user.id, action="release_mark_live", target=release_id, detail=result)
    return result


@router.post("/distribution/analytics/sync")
def admin_sync_analytics(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.sync import sync_chartmetric_all, sync_youtube_all

    result = {"youtube": sync_youtube_all(db), "licensed": sync_chartmetric_all(db)}
    log_admin_action(db, admin_id=user.id, action="sync_analytics", target="platform", detail=result)
    return result


@router.get("/distribution/partners")
def admin_distribution_partners(user: User = Depends(require_admin)):
    from app.services.distribution.catalog import partner_payee_status

    return partner_payee_status()


@router.get("/distribution/reports")
def admin_list_reports(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.ingest import list_report_imports

    return {"imports": list_report_imports(db, user, admin=True)}


@router.get("/distribution/reports/unmatched")
def admin_unmatched_official(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.ingest import list_isrc_unmatched_snapshots

    return {"snapshots": list_isrc_unmatched_snapshots(db)}


@router.post("/distribution/reports/snapshots/{snapshot_id}/attach")
def admin_attach_official_snapshot(
    snapshot_id: str,
    work_id: str = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.ingest import attach_snapshot_to_work

    result = attach_snapshot_to_work(db, user, snapshot_id, work_id, admin=True)
    log_admin_action(db, admin_id=user.id, action="attach_official_snapshot", target=snapshot_id, detail=result)
    return result


@router.get("/harvest/unmatched")
def admin_harvest_unmatched(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.harvest.unmatched import list_unmatched

    return {"rows": list_unmatched(db, user, admin=True)}


@router.post("/harvest/unmatched/{unmatched_id}/attach")
def admin_attach_harvest_unmatched(
    unmatched_id: str,
    work_id: str = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.harvest.unmatched import attach_unmatched

    result = attach_unmatched(db, user, unmatched_id, work_id, admin=True)
    log_admin_action(db, admin_id=user.id, action="attach_harvest_unmatched", target=unmatched_id, detail=result)
    return result


@router.post("/distribution/reports")
async def admin_import_report(
    file: UploadFile = File(...),
    source: str = Form("distributor_export"),
    distributor_code: str | None = Form(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.ingest import ingest_report

    content = await file.read()
    result = ingest_report(
        db,
        user=user,
        content=content,
        filename=file.filename or "admin-report.csv",
        source=source,
        distributor_code=distributor_code,
    )
    log_admin_action(db, admin_id=user.id, action="import_report", target=result.get("import_id"), detail=result)
    return result


@router.get("/settlement/batches")
def admin_batches(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.settlement import list_batches

    return {"batches": list_batches(db)}


@router.get("/settlement/batches/{batch_id}")
def admin_batch_detail(batch_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.settlement import get_batch_detail

    return get_batch_detail(db, batch_id)


@router.get("/settlement/preview")
def admin_settlement_preview(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.settlement import preview_settlement

    return preview_settlement(db)


@router.post("/settlement/run")
def admin_run_settlement(
    payload: SettlementRunBody | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.settlement import run_settlement

    result = run_settlement(db, period_key=payload.period_key if payload else None)
    log_admin_action(db, admin_id=user.id, action="run_settlement", target=result.get("batch_id"), detail=result)
    return result


@router.post("/settlement/{batch_id}/confirm")
def admin_confirm_settlement(batch_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.settlement import confirm_settlement

    result = confirm_settlement(db, batch_id)
    log_admin_action(db, admin_id=user.id, action="confirm_settlement", target=batch_id, detail=result)
    return result


@router.post("/settlement/{batch_id}/void")
def admin_void_settlement(batch_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.settlement import void_settlement

    result = void_settlement(db, batch_id)
    log_admin_action(db, admin_id=user.id, action="void_settlement", target=batch_id, detail=result)
    return result


@router.get("/settlement/withdrawals")
def admin_withdrawals(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.royalty.wallet import admin_list_withdrawals

    rows = admin_list_withdrawals(db)
    return {"withdrawals": rows, "pending_count": sum(1 for row in rows if row.get("status") == "pending")}


@router.post("/settlement/withdrawals/{withdrawal_id}/review")
def admin_review_withdrawal(
    withdrawal_id: str,
    payload: WithdrawalReviewBody,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_audit import log_admin_action
    from app.services.royalty.wallet import review_withdrawal

    result = review_withdrawal(db, withdrawal_id, approve=payload.approve, admin_note=payload.admin_note)
    log_admin_action(db, admin_id=user.id, action="review_withdrawal", target=withdrawal_id, detail=payload.model_dump())
    return result


class VendorKeyCreate(BaseModel):
    vendor: str = Field(min_length=2, max_length=32)
    capability: str = Field(min_length=2, max_length=24)
    api_key: str = Field(min_length=8, max_length=2048)
    base_url: str | None = None
    model: str | None = None
    weight: int = Field(default=10, ge=1, le=100)
    max_inflight: int | None = Field(default=None, ge=1, le=32)
    daily_quota: int | None = Field(default=None, ge=1, le=100000)


class VendorKeyPatch(BaseModel):
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=100)
    max_inflight: int | None = Field(default=None, ge=1, le=32)
    daily_quota: int | None = Field(default=None, ge=1, le=100000)


@router.get("/vendor-keys")
def admin_list_vendor_keys(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.integrations.vendors.pool import ensure_env_keys, public_row
    from app.models.schemas import VendorKey

    ensure_env_keys(db)
    rows = db.query(VendorKey).order_by(VendorKey.vendor, VendorKey.capability).all()
    return {"keys": [public_row(row) for row in rows]}


@router.post("/vendor-keys")
def admin_create_vendor_key(
    payload: VendorKeyCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.integrations.vendors.pool import add_key, public_row
    from app.services.admin_audit import log_admin_action

    row = add_key(
        db,
        vendor=payload.vendor,
        capability=payload.capability,
        api_key=payload.api_key,
        base_url=payload.base_url,
        model=payload.model,
        weight=payload.weight,
        max_inflight=payload.max_inflight,
        daily_quota=payload.daily_quota,
    )
    log_admin_action(db, admin_id=user.id, action="vendor_key_create", target=str(row.id), detail={"vendor": row.vendor})
    return public_row(row)


@router.patch("/vendor-keys/{key_id}")
def admin_patch_vendor_key(
    key_id: str,
    payload: VendorKeyPatch,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.integrations.vendors.pool import public_row
    from app.models.schemas import VendorKey

    row = db.query(VendorKey).filter(VendorKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="vendor key not found")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.weight is not None:
        row.weight = payload.weight
    if payload.max_inflight is not None:
        row.max_inflight = payload.max_inflight
    if payload.daily_quota is not None:
        row.daily_quota = payload.daily_quota
    db.commit()
    db.refresh(row)
    return public_row(row)


@router.get("/ops/dashboard")
def ops_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from app.services.ops_dashboard import ops_daily_digest

    return ops_daily_digest(db)


@router.post("/ops/batch")
def ops_batch_action(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    action = payload.get("action")
    ids = payload.get("ids", [])
    if action not in ("retry_deliveries", "approve_kyc"):
        raise HTTPException(status_code=400, detail=f"Unknown batch action: {action}")
    if not isinstance(ids, list) or len(ids) > 50:
        raise HTTPException(status_code=400, detail="ids must be a list of at most 50 items")

    if action == "retry_deliveries":
        from app.services.distribution.pipeline import process_one_delivery, dispatch_delivery
        from app.models.schemas import DistributionDelivery

        results = []
        for did in ids:
            try:
                row = db.query(DistributionDelivery).filter(DistributionDelivery.id == uuid.UUID(did)).first()
                if row and row.status not in ("live", "taken_down"):
                    row.status = "submitting"
                    row.next_retry_at = None
                    row.last_error = None
                    db.commit()
                    result = process_one_delivery(db, row, force=True, commit=True)
                    if result.get("status") == "submitting":
                        dispatch_delivery(str(row.id), str(row.release_id), process_now=False)
                    results.append(result)
            except Exception:
                pass
        return {"action": action, "processed": len(results)}

    if action == "approve_kyc":
        from app.services.admin_audit import log_admin_action

        processed = 0
        for uid in ids:
            try:
                u = db.query(User).filter(User.id == uuid.UUID(uid)).first()
                if u:
                    u.kyc_status = "verified"
                    processed += 1
            except Exception:
                pass
        db.commit()
        log_admin_action(
            db,
            admin_id=user.id,
            action="approve_kyc",
            target="batch",
            detail={"ids": [str(item) for item in ids], "processed": processed},
        )
        return {"action": action, "processed": processed}

    raise HTTPException(status_code=400, detail=f"Unknown batch action: {action}")


@router.post("/vendor-keys/{key_id}/probe")
async def admin_probe_vendor_key(
    key_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.integrations.vendors.pool import public_row
    from app.integrations.vendors.probe import probe_and_record
    from app.models.schemas import VendorKey
    from app.services.admin_audit import log_admin_action

    row = db.query(VendorKey).filter(VendorKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="vendor key not found")
    result = await probe_and_record(db, row)
    log_admin_action(db, admin_id=user.id, action="vendor_key_probe", target=str(row.id), detail={"ok": result.get("ok")})
    db.refresh(row)
    return {**public_row(row), "probe": {"ok": bool(result.get("ok")), "checked": result.get("checked"), "error": result.get("error")}}
