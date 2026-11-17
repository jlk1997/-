"""Workbench sessions, effect packs, and bounce jobs. Credits stay off the fiat ledger."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.mix_graph import (
    MAX_HISTORY,
    REGEN_NODE_TYPES,
    activate_take,
    apply_pack_graph,
    default_edit_lanes,
    empty_graph,
    graph_has_ai,
    graph_has_edits,
    graph_hash,
    light_editor_nodes,
    official_pack_defs,
    pack_kind_from_graph,
    pack_visible_on_surface,
    publish_preflight,
    set_master_trim,
    suggest_need_tags,
    upsert_node,
    upsert_region,
    validate_mix_graph,
)
from app.models.schemas import EffectPack, EffectPackPurchase, PackDemand, User, Work, WorkbenchSession
from app.services.credit_estimates import WORKBENCH_AI_COST, WORKBENCH_RENDER_COST, estimate_credits
from app.services.credits import GENERATION_COST, deduct_credits
from app.services.ecosystem import TEMPLATE_PLATFORM_FEE_RATE, _wallet_credit, ensure_catalog_owner
from app.services.generation_gate import charge_generation_credits, with_credits_charged
from app.services.generation_jobs import create_generation_job
from app.services.royalty.hub import is_workbench_master
from app.services.work_access import get_owned_work

_SHIPPING = frozenset({"queued", "delivering", "live"})


def session_source_id(work: Any) -> Any:
    """Beautify sessions live on Work A. Opening bounced Work B continues the parent."""
    if is_workbench_master(work) and getattr(work, "parent_work_id", None):
        return work.parent_work_id
    return work.id


def walk_to_session_root(work: Any, load_parent: Any) -> Any:
    """Walk Work B → C → … until a non-master song. Cycle-safe."""
    current = work
    seen: set[str] = set()
    while is_workbench_master(current) and getattr(current, "parent_work_id", None):
        token = str(current.id)
        if token in seen:
            break
        seen.add(token)
        parent = load_parent(current.parent_work_id)
        if parent is None:
            break
        current = parent
    return current


def resolve_session_source(db: Session, user: User, work: Work) -> Work:
    """Walk Work B/C… back to the root song the MixGraph session lives on."""
    return walk_to_session_root(
        work,
        lambda parent_id: db.query(Work).filter(Work.id == parent_id, Work.owner_id == user.id).first(),
    )


def next_core_door(*, release_status: str | None, has_result: bool, degraded: bool = False) -> str:
    """After bounce, the dock follows the same ship circuit as reveal / creator OS."""
    status = str(release_status or "")
    if not has_result:
        return "beautify"
    if status in _SHIPPING:
        return "deliveries"
    if degraded:
        return "fix"
    if status == "qc_ready":
        return "release"
    return "radio"


def detach_work_from_sessions(db: Session, user_id: Any, work_id: Any) -> None:
    """Null bounce pointers, or drop the session if the source song is deleted."""
    rows = db.query(WorkbenchSession).filter(WorkbenchSession.owner_id == user_id).all()
    for row in rows:
        if row.source_work_id == work_id:
            db.delete(row)
            continue
        if row.last_result_work_id == work_id:
            row.last_result_work_id = None
        if row.previous_result_work_id == work_id:
            row.previous_result_work_id = None


def _pps_degraded(pps: Any) -> bool:
    blob = pps if isinstance(pps, dict) else {}
    state = str(blob.get("state") or "").lower()
    if state in {"ready", "ok", "passed", "complete", "completed", "pending", "running"}:
        return False
    return state == "degraded" or bool(blob.get("failed") or blob.get("last_error"))


def _load_session_work(db: Session, user: User, work_id: Any) -> Work | None:
    if not work_id:
        return None
    return db.query(Work).filter(Work.id == work_id, Work.owner_id == user.id).first()


def _load_session_result(db: Session, user: User, row: WorkbenchSession) -> Work | None:
    result = _load_session_work(db, user, row.last_result_work_id)
    if result is None or result.id == row.source_work_id:
        return None
    if not is_workbench_master(result):
        return None
    return result


def _next_action_payload(result: Work | None, source: Work | None) -> dict[str, Any]:
    target = result or source
    door = next_core_door(
        release_status=getattr(result, "release_status", None) if result else None,
        has_result=result is not None,
        degraded=_pps_degraded(getattr(result, "post_process_status", None) if result else None),
    )
    pps = (result.post_process_status if result and isinstance(result.post_process_status, dict) else {}) or {}
    return {
        "door": door,
        "work_id": str(target.id) if target else None,
        "title": target.title if target else None,
        "release_status": getattr(result, "release_status", None) if result else None,
        "qc_ready": str(getattr(result, "release_status", "") or "") in {"qc_ready", *_SHIPPING},
        "from_workbench": bool(pps.get("workbench")),
        "degraded": _pps_degraded(pps),
        "cover_url": result.cover_url if result else None,
    }

PACK_PRICE_MAX = 50


def seed_official_effect_packs(db: Session) -> int:
    owner = ensure_catalog_owner(db)
    existing = {row.slug for row in db.query(EffectPack).filter(EffectPack.slug.isnot(None)).all()}
    created = 0
    for item in official_pack_defs():
        row = db.query(EffectPack).filter(EffectPack.slug == item["slug"]).first()
        if row:
            if not row.need_tags:
                row.need_tags = item.get("need_tags") or item.get("tags") or []
            if not row.kind:
                row.kind = item.get("kind") or "scene"
            continue
        if item["slug"] in existing:
            continue
        db.add(
            EffectPack(
                owner_id=owner.id,
                slug=item["slug"],
                title=item["title"],
                description=item["description"],
                mix_graph=item["mix_graph"],
                price_credits=0,
                is_official=True,
                status="published",
                tags=item.get("tags") or [],
                need_tags=item.get("need_tags") or item.get("tags") or [],
                kind=item.get("kind") or "scene",
                locale_titles={"zh": item["title"], "en": item["title_en"]},
            )
        )
        created += 1
    return created


def _pack_public(row: EffectPack, *, owned: bool = False, username: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "title": row.title,
        "description": row.description,
        "price_credits": row.price_credits or 0,
        "is_official": bool(row.is_official),
        "status": row.status,
        "purchase_count": row.purchase_count or 0,
        "preview_url": row.preview_url,
        "tags": list(row.tags or []),
        "need_tags": list(row.need_tags or row.tags or []),
        "kind": row.kind or pack_kind_from_graph(row.mix_graph or {}),
        "apply_count": row.apply_count or 0,
        "bounce_count": row.bounce_count or 0,
        "locale_titles": dict(row.locale_titles or {}),
        "mix_graph": validate_mix_graph(row.mix_graph or {}),
        "owned": owned or bool(row.is_official) or (row.price_credits or 0) == 0,
        "author_username": username,
        "graph_hash": graph_hash(row.mix_graph or {}),
    }


def _session_public(
    row: WorkbenchSession,
    *,
    work: Work | None = None,
    pack: EffectPack | None = None,
    result: Work | None = None,
    continued_from_result: bool = False,
) -> dict[str, Any]:
    graph = validate_mix_graph(row.mix_graph or {}, work_id=str(row.source_work_id))
    lanes = row.edit_lanes if isinstance(row.edit_lanes, dict) else {}
    return {
        "id": str(row.id),
        "source_work_id": str(row.source_work_id),
        "source_title": work.title if work else None,
        "source_audio_url": work.audio_url if work else None,
        "source_cover_url": work.cover_url if work else None,
        "source_waveform_url": ((work.post_process_status or {}) if work and isinstance(work.post_process_status, dict) else {}).get(
            "waveform_url"
        ),
        "mix_graph": graph,
        "graph_hash": graph_hash(graph),
        "intensity": float(row.intensity or graph.get("intensity") or 1),
        "applied_pack_id": str(row.applied_pack_id) if row.applied_pack_id else None,
        "applied_pack_slug": pack.slug if pack else None,
        "edit_lanes": {
            "grade": "edit",
            "quality": lanes.get("quality"),
            "label": lanes.get("label") or ("分轨" if lanes.get("quality") == "demucs" else "预览近似"),
            "stems": list((lanes.get("urls") or {}).keys()) if isinstance(lanes.get("urls"), dict) else [],
            "urls": dict(lanes.get("urls") or {}) if isinstance(lanes.get("urls"), dict) else {},
            "flac_urls": dict(lanes.get("flac_urls") or {}) if isinstance(lanes.get("flac_urls"), dict) else {},
            "marks": list(lanes.get("marks") or []) if isinstance(lanes.get("marks"), list) else [],
            "ready": bool(lanes.get("urls")),
            "not_review_stems": True,
            "not_store_tracks": True,
            "copied_from_review": bool(lanes.get("copied_from_review")),
        },
        "preview_url": row.preview_url,
        "last_render_job_id": str(row.last_render_job_id) if row.last_render_job_id else None,
        "last_result_work_id": str(result.id) if result else None,
        "last_result_audio_url": result.audio_url if result else None,
        "last_result_title": result.title if result else None,
        "previous_result_work_id": None,
        "previous_result_audio_url": None,
        "can_undo": bool(getattr(row, "op_stack", None)),
        "has_clips": bool(graph.get("clips")),
        "desktop_edits": bool(graph.get("clips")),
        "lane_pack_degraded": bool(
            pack
            and (pack.kind == "lane" or pack_kind_from_graph(pack.mix_graph or {}) == "lane")
            and not (isinstance(row.edit_lanes, dict) and (row.edit_lanes or {}).get("urls"))
        ),
        "source_hls_url": work.hls_url if work else None,
        "source_duration": work.duration if work else None,
        "source_moods": list(work.moods or []) if work else [],
        "source_release_status": work.release_status if work else None,
        "last_result_release_status": result.release_status if result else None,
        "last_result_cover_url": result.cover_url if result else None,
        "continued_from_result": bool(continued_from_result),
        "next_action": _next_action_payload(result, work),
        "credit_estimate": estimate_session_cost(graph, pack),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _push_op_stack(row: WorkbenchSession) -> None:
    stack = list(row.op_stack or [])
    stack.append(validate_mix_graph(row.mix_graph or {}, work_id=str(row.source_work_id)))
    row.op_stack = stack[-MAX_HISTORY:]


def _session_with_previous(db: Session, payload: dict[str, Any], row: WorkbenchSession, user: User) -> dict[str, Any]:
    payload["previous_result_work_id"] = None
    payload["previous_result_audio_url"] = None
    payload["previous_result_title"] = None
    if not row.previous_result_work_id:
        return payload
    prev = db.query(Work).filter(Work.id == row.previous_result_work_id, Work.owner_id == user.id).first()
    if prev:
        payload["previous_result_work_id"] = str(prev.id)
        payload["previous_result_audio_url"] = prev.audio_url
        payload["previous_result_title"] = prev.title
    return payload


def estimate_session_cost(graph: dict[str, Any], pack: EffectPack | None = None) -> dict[str, Any]:
    bounce = WORKBENCH_AI_COST if graph_has_ai(graph) and not (pack and pack.is_official) else WORKBENCH_RENDER_COST
    return {
        "bounce": bounce,
        "regen": GENERATION_COST,
        "ai": WORKBENCH_AI_COST if graph_has_ai(graph) else 0,
        "ledger": "credits",
        "fiat": False,
        **estimate_credits(mode="workbench_ai" if bounce else "workbench"),
    }


def _get_session(db: Session, session_id: str, user: User) -> WorkbenchSession:
    try:
        sid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session id") from exc
    row = (
        db.query(WorkbenchSession)
        .filter(WorkbenchSession.id == sid, WorkbenchSession.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


def _owned_pack_ids(db: Session, user: User) -> set[uuid.UUID]:
    rows = db.query(EffectPackPurchase.pack_id).filter(EffectPackPurchase.buyer_id == user.id).all()
    return {row[0] for row in rows}


def list_effect_packs(
    db: Session,
    user: User | None,
    *,
    scope: str = "all",
    surface: str = "h5",
    need: str | None = None,
) -> list[dict[str, Any]]:
    if seed_official_effect_packs(db):
        db.commit()
    weapp = surface == "weapp"
    q = db.query(EffectPack)
    if weapp or scope == "official":
        q = q.filter(EffectPack.is_official == True, EffectPack.status == "published")
    elif scope == "community":
        q = q.filter(EffectPack.is_official == False, EffectPack.status == "published")
    elif scope == "mine" and user:
        q = q.filter(EffectPack.owner_id == user.id)
    else:
        if user:
            q = q.filter((EffectPack.status == "published") | (EffectPack.owner_id == user.id))
        else:
            q = q.filter(EffectPack.status == "published")
    rows = q.order_by(EffectPack.is_official.desc(), EffectPack.purchase_count.desc(), EffectPack.created_at.desc()).limit(80).all()
    owned = _owned_pack_ids(db, user) if user else set()
    owners = {row.owner_id for row in rows if row.owner_id}
    names: dict[uuid.UUID, str] = {}
    if owners:
        for uid, username, display in (
            db.query(User.id, User.username, User.display_name).filter(User.id.in_(owners)).all()
        ):
            names[uid] = display or username
    out = []
    for row in rows:
        is_owned = bool(row.is_official) or (user and row.owner_id == user.id) or row.id in owned or (row.price_credits or 0) == 0
        if not pack_visible_on_surface(official=bool(row.is_official), surface=surface):
            continue
        public = _pack_public(row, owned=bool(is_owned), username=names.get(row.owner_id) if row.owner_id else "比特音")
        if need:
            tags = {str(tag).lower() for tag in (public.get("need_tags") or public.get("tags") or [])}
            if need.lower() not in tags:
                continue
        out.append(public)
    return out


def get_or_create_session(db: Session, user: User, work_id: str) -> dict[str, Any]:
    opened = get_owned_work(db, work_id, user)
    work = resolve_session_source(db, user, opened)
    row = (
        db.query(WorkbenchSession)
        .filter(WorkbenchSession.owner_id == user.id, WorkbenchSession.source_work_id == work.id)
        .order_by(WorkbenchSession.updated_at.desc())
        .first()
    )
    if not row:
        row = WorkbenchSession(
            owner_id=user.id,
            source_work_id=work.id,
            mix_graph=empty_graph(str(work.id)),
            intensity=1.0,
            edit_lanes={"grade": "edit", "not_review_stems": True, "not_store_tracks": True},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    pack = db.query(EffectPack).filter(EffectPack.id == row.applied_pack_id).first() if row.applied_pack_id else None
    result = _load_session_result(db, user, row)
    return _session_with_previous(
        db,
        _session_public(
            row,
            work=work,
            pack=pack,
            result=result,
            continued_from_result=opened.id != work.id or result is not None,
        ),
        row,
        user,
    )


def get_session(db: Session, user: User, session_id: str) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    work = _load_session_work(db, user, row.source_work_id)
    pack = db.query(EffectPack).filter(EffectPack.id == row.applied_pack_id).first() if row.applied_pack_id else None
    result = _load_session_result(db, user, row)
    return _session_with_previous(
        db,
        _session_public(row, work=work, pack=pack, result=result, continued_from_result=result is not None),
        row,
        user,
    )


def patch_session(
    db: Session,
    user: User,
    session_id: str,
    *,
    mix_graph: dict | None = None,
    intensity: float | None = None,
    lanes: list[dict] | None = None,
) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    _push_op_stack(row)
    graph = validate_mix_graph(mix_graph or row.mix_graph or {}, work_id=str(row.source_work_id))
    if lanes:
        graph["lanes"] = validate_mix_graph(
            {"lanes": lanes, "nodes": graph["nodes"], "clips": graph["clips"], "regions": graph["regions"]},
            work_id=str(row.source_work_id),
        )["lanes"]
    if intensity is not None:
        graph["intensity"] = max(0.0, min(1.5, float(intensity)))
        row.intensity = graph["intensity"]
    row.mix_graph = graph
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, session_id)


def _can_use_pack(db: Session, user: User, pack: EffectPack) -> bool:
    if pack.is_official or (pack.price_credits or 0) == 0:
        return True
    if pack.owner_id == user.id:
        return True
    hit = (
        db.query(EffectPackPurchase)
        .filter(EffectPackPurchase.pack_id == pack.id, EffectPackPurchase.buyer_id == user.id)
        .first()
    )
    return bool(hit)


def apply_pack(db: Session, user: User, session_id: str, pack_id: str, intensity: float = 1.0) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    try:
        pid = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pack id") from exc
    pack = db.query(EffectPack).filter(EffectPack.id == pid).first()
    if not pack or pack.status not in ("published", "pending"):
        raise HTTPException(status_code=404, detail="Pack not found")
    if pack.status == "pending" and pack.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Pack not found")
    if not _can_use_pack(db, user, pack):
        raise HTTPException(status_code=402, detail="Pack locked")
    _push_op_stack(row)
    lanes_ready = bool(isinstance(row.edit_lanes, dict) and (row.edit_lanes or {}).get("urls"))
    graph = apply_pack_graph(
        pack.mix_graph,
        work_id=str(row.source_work_id),
        intensity=intensity,
        existing=row.mix_graph,
        lanes_ready=lanes_ready,
    )
    row.mix_graph = graph
    row.intensity = graph["intensity"]
    row.applied_pack_id = pack.id
    pack.apply_count = (pack.apply_count or 0) + 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, session_id)


def purchase_pack(db: Session, user: User, pack_id: str) -> dict[str, Any]:
    try:
        pid = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pack id") from exc
    pack = db.query(EffectPack).filter(EffectPack.id == pid, EffectPack.status == "published").first()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    if pack.is_official or pack.owner_id == user.id or (pack.price_credits or 0) == 0:
        return {"owned": True, "pack_id": str(pack.id), "credits_paid": 0, "mix_graph": validate_mix_graph(pack.mix_graph or {})}
    existing = (
        db.query(EffectPackPurchase)
        .filter(EffectPackPurchase.pack_id == pid, EffectPackPurchase.buyer_id == user.id)
        .first()
    )
    if existing:
        return {"owned": True, "pack_id": str(pack.id), "credits_paid": 0, "mix_graph": validate_mix_graph(pack.mix_graph or {})}
    price = max(0, min(PACK_PRICE_MAX, pack.price_credits or 0))
    if price > 0:
        if not deduct_credits(db, user.id, price, source="effect_pack_purchase"):
            raise HTTPException(status_code=402, detail="Insufficient credits")
        if pack.owner_id:
            platform_fee = max(1, int(price * TEMPLATE_PLATFORM_FEE_RATE)) if price >= 2 else 0
            creator_share = max(0, price - platform_fee)
            if creator_share:
                _wallet_credit(db, pack.owner_id, creator_share, source="effect_pack_sale")
    db.add(EffectPackPurchase(pack_id=pid, buyer_id=user.id, credits_paid=price))
    pack.purchase_count = (pack.purchase_count or 0) + 1
    db.commit()
    return {"purchased": True, "pack_id": str(pack.id), "credits_paid": price, "mix_graph": validate_mix_graph(pack.mix_graph or {})}


def publish_pack(
    db: Session,
    user: User,
    session_id: str,
    *,
    title: str,
    description: str | None = None,
    price_credits: int = 0,
    surface: str = "h5",
    need_tags: list[str] | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    if surface == "weapp":
        raise HTTPException(status_code=403, detail="Pro bench is H5 only")
    row = _get_session(db, session_id, user)
    preflight = publish_preflight(row.mix_graph or {}, need_tags=need_tags)
    if preflight.get("forbids_external_audio"):
        raise HTTPException(status_code=400, detail="Packs cannot include IR or remote samples")
    if not preflight["ok"]:
        raise HTTPException(status_code=400, detail="Pack needs a bounceable chain")
    graph = preflight["mix_graph"]
    name = (title or "").strip()[:80]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Title required")
    price = max(0, min(PACK_PRICE_MAX, int(price_credits)))
    status = "published" if user.is_admin else "pending"
    pack = EffectPack(
        owner_id=user.id,
        title=name,
        description=(description or "").strip()[:400] or None,
        mix_graph=graph,
        price_credits=price,
        is_official=False,
        status=status,
        tags=["community", *(graph.get("need_tags") or [])],
        need_tags=list(graph.get("need_tags") or []),
        kind=kind if kind in {"scene", "lane", "demand"} else preflight["kind"],
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return _pack_public(pack, owned=True, username=user.display_name or user.username)


def review_pack(db: Session, admin: User, pack_id: str, *, status: str) -> dict[str, Any]:
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    if status not in ("published", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        pid = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pack id") from exc
    pack = db.query(EffectPack).filter(EffectPack.id == pid).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.status = status
    pack.updated_at = datetime.utcnow()
    db.commit()
    return _pack_public(pack)


def _render_cost(graph: dict[str, Any], pack: EffectPack | None) -> int:
    if pack and pack.is_official:
        return 0
    if graph_has_ai(graph):
        return WORKBENCH_AI_COST
    return WORKBENCH_RENDER_COST


def list_pending_packs(db: Session, admin: User) -> list[dict[str, Any]]:
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    rows = (
        db.query(EffectPack)
        .filter(EffectPack.status == "pending", EffectPack.is_official == False)
        .order_by(EffectPack.created_at.desc())
        .limit(50)
        .all()
    )
    return [_pack_public(row) for row in rows]


def sync_light_editor(
    db: Session,
    user: User,
    work_id: str,
    *,
    semitones: float = 0,
    tempo: float = 1.0,
    master: bool = False,
) -> dict[str, Any]:
    session = get_or_create_session(db, user, work_id)
    row = _get_session(db, session["id"], user)
    graph = validate_mix_graph(row.mix_graph or {}, work_id=str(row.source_work_id))
    for node in light_editor_nodes(semitones=semitones, tempo=tempo, master=master):
        graph = upsert_node(graph, node)
    row.mix_graph = graph
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, str(row.id))


def queue_regen(
    db: Session,
    user: User,
    session_id: str,
    *,
    kind: str,
    seconds: int = 15,
    idempotency_key: str | None = None,
    region_start: float | None = None,
    region_end: float | None = None,
    region_id: str | None = None,
) -> dict[str, Any]:
    """Reuse generate_single / extend / remelt without leaving the MixGraph session."""
    from app.services.generation_gate import charge_generation_credits, with_credits_charged
    from app.services.job_dispatch import dispatch_single

    if kind not in ("extend", "remelt", "same_style"):
        raise HTTPException(status_code=400, detail="Invalid regen kind")
    row = _get_session(db, session_id, user)
    work = get_owned_work(db, str(row.source_work_id), user)
    seed = _load_session_result(db, user, row) or work
    charged = charge_generation_credits(db, user.id, cost=GENERATION_COST, defer_commit=True)
    if kind == "extend":
        dur = 15 if seconds < 23 else 30
        config = {
            "text_intent": (
                f"Continue the song “{seed.title}” from the ending for about {dur} seconds. "
                "Keep the same melody, mood, and vocal timbre. Do not restart the arrangement."
            ),
            "title": f"{seed.title} · +{dur}s",
            "record_type": "extend",
            "extend": True,
            "extend_seconds": dur,
        }
        node_type = "regen_extend"
    elif kind == "remelt":
        config = {
            "text_intent": f"Another take of “{seed.title}”, same mood, slightly different arrangement.",
            "title": f"{seed.title} · 换一版",
            "record_type": "remelt",
            "remelt": True,
            "distance_nudge": True,
        }
        node_type = "regen_remelt"
    else:
        config = {
            "text_intent": f"Same style as “{seed.title}”. Keep the feel, write a new track.",
            "title": f"{seed.title} · 同款",
            "record_type": "same_style",
            "remix_intent": "same_style",
        }
        node_type = "regen_same_style"
    config.update(
        {
            "source_work_id": str(work.id),
            "seed_work_id": str(seed.id),
            "reference": {"work_id": str(seed.id)},
            "workbench_session_id": str(row.id),
            "workbench_take": True,
            "instrumental": False,
            "moods": list(seed.moods or []),
            "genres": list(seed.genres or []),
        }
    )
    if kind == "remelt":
        from app.services.audio_distance import remelt_av_nudge

        prior = seed.post_process_status if isinstance(seed.post_process_status, dict) else {}
        remelt = prior.get("remelt") if isinstance(prior.get("remelt"), dict) else {}
        config["reference"] = {
            "work_id": str(seed.id),
            "av_offset": remelt_av_nudge(2 if remelt.get("too_close") else 1),
        }
        config["distance_nudge"] = True
    if region_start is not None:
        config["region_start"] = float(region_start)
        config["region_end"] = float(region_end if region_end is not None else region_start + 8)
        config["region_id"] = (region_id or "sel")[:32]
    job = create_generation_job(
        db,
        user,
        job_type="single",
        config=with_credits_charged(config, charged),
        status_message="会话内再生成…",
        idempotency_key=idempotency_key,
    )
    graph = validate_mix_graph(row.mix_graph or {}, work_id=str(row.source_work_id))
    if region_start is not None:
        graph = upsert_region(
            graph,
            {
                "id": region_id or "sel",
                "start": region_start,
                "end": region_end if region_end is not None else region_start + 8,
                "label": kind,
            },
        )
    graph = upsert_node(
        graph,
        {
            "id": node_type,
            "type": node_type,
            "target": "master",
            "origin": "regen",
            "params": {"job": str(job.id)[:32], "start": region_start or 0, "end": region_end or 0},
        },
    )
    row.mix_graph = graph
    row.last_render_job_id = job.id
    row.updated_at = datetime.utcnow()
    db.commit()
    dispatch_single(db, user.id, str(job.id), job.config or config)
    return {"job_id": str(job.id), "session_id": str(row.id), "kind": kind, "credits": GENERATION_COST}


def stamp_regen_failed(graph: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Mark the matching regen node failed. Does not touch last_result_work_id."""
    token = str(job_id).replace("-", "")[:8]
    nodes = []
    for node in graph.get("nodes") or []:
        if str(node.get("type")) in REGEN_NODE_TYPES:
            params = dict(node.get("params") or {})
            job_token = str(params.get("job") or "").replace("-", "")
            if token and job_token.startswith(token):
                params["failed"] = True
                node = {**node, "params": params}
        nodes.append(node)
    return {**graph, "nodes": nodes}


def mark_session_job_failed(db: Session, session_id: str, job_id: str) -> None:
    """Stamp a regen node failed without moving last_result off Work B."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return
    row = db.query(WorkbenchSession).filter(WorkbenchSession.id == sid).first()
    if not row:
        return
    last_result = row.last_result_work_id
    row.mix_graph = stamp_regen_failed(validate_mix_graph(row.mix_graph or {}), job_id)
    row.last_result_work_id = last_result
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()


def queue_render(db: Session, user: User, session_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
    from app.services.job_dispatch import dispatch_workbench

    row = _get_session(db, session_id, user)
    work = get_owned_work(db, str(row.source_work_id), user)
    graph = validate_mix_graph(row.mix_graph or {}, work_id=str(work.id))
    if not graph_has_edits(graph):
        raise HTTPException(status_code=400, detail="Empty mix graph")
    pack = db.query(EffectPack).filter(EffectPack.id == row.applied_pack_id).first() if row.applied_pack_id else None
    if pack and not _can_use_pack(db, user, pack):
        raise HTTPException(status_code=402, detail="Pack locked")
    cost = _render_cost(graph, pack)
    charged = charge_generation_credits(db, user.id, cost=cost, defer_commit=True) if cost else None
    config = {
        "session_id": str(row.id),
        "workbench_session_id": str(row.id),
        "source_work_id": str(work.id),
        "mix_graph": graph,
        "pack_id": str(pack.id) if pack else None,
        "graph_hash": graph_hash(graph),
        "intensity": graph.get("intensity", 1),
        "title": f"{work.title} · 美化",
    }
    if charged:
        config = with_credits_charged(config, charged)
    job = create_generation_job(
        db,
        user,
        job_type="workbench_render",
        config=config,
        status_message="正在打成新母带…",
        idempotency_key=idempotency_key,
    )
    row.last_render_job_id = job.id
    db.commit()
    dispatch_workbench(db, user.id, str(job.id), job.config or config)
    return {"job_id": str(job.id), "session_id": str(row.id), "graph_hash": config["graph_hash"]}


def queue_lane_separate(db: Session, user: User, session_id: str, *, profile: str = "full") -> dict[str, Any]:
    from app.services.job_dispatch import dispatch_lane_separate

    row = _get_session(db, session_id, user)
    work = get_owned_work(db, str(row.source_work_id), user)
    existing = row.edit_lanes if isinstance(row.edit_lanes, dict) else {}
    if existing.get("urls"):
        return {"ready": True, "session": get_session(db, user, session_id)}
    copied = _copy_review_stems_as_edit_lanes(db, work)
    if copied:
        row.edit_lanes = copied
        _ensure_lane_graph(row)
        db.commit()
        return {"ready": True, "copied_from_review": True, "session": get_session(db, user, session_id)}
    job = create_generation_job(
        db,
        user,
        job_type="lane_separate",
        config={"session_id": str(row.id), "source_work_id": str(work.id), "profile": "vocals2" if profile == "vocals2" else "full"},
        status_message="正在准备编辑分轨…",
    )
    db.commit()
    dispatch_lane_separate(db, user.id, str(job.id), job.config or {})
    return {"job_id": str(job.id), "ready": False}


def preview_source_allowed(
    *,
    job_owner_id: uuid.UUID | str,
    source_owner_id: uuid.UUID | str,
    official: bool,
    catalog_owner_id: uuid.UUID | str | None,
) -> bool:
    if str(source_owner_id) == str(job_owner_id):
        return True
    return bool(official and catalog_owner_id and str(source_owner_id) == str(catalog_owner_id))


def resolve_pack_preview_source(db: Session, user: User, pack: EffectPack) -> Work | None:
    """Prefer the user's song; official packs may bake from the catalog demo."""
    session = (
        db.query(WorkbenchSession)
        .filter(WorkbenchSession.owner_id == user.id)
        .order_by(WorkbenchSession.updated_at.desc())
        .first()
    )
    if session:
        work = db.query(Work).filter(Work.id == session.source_work_id, Work.audio_url.isnot(None)).first()
        if work:
            return work
    latest = (
        db.query(Work)
        .filter(Work.owner_id == user.id, Work.audio_url.isnot(None))
        .order_by(Work.created_at.desc())
        .first()
    )
    if latest:
        return latest
    if pack.is_official:
        owner = ensure_catalog_owner(db)
        return (
            db.query(Work)
            .filter(Work.owner_id == owner.id, Work.audio_url.isnot(None))
            .order_by(Work.created_at.desc())
            .first()
        )
    return None


def queue_pack_preview(db: Session, user: User, pack_id: str) -> dict[str, Any]:
    from app.services.job_dispatch import dispatch_pack_preview

    try:
        pid = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid pack id") from exc
    pack = db.query(EffectPack).filter(EffectPack.id == pid).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    if pack.preview_url:
        return {"preview_url": pack.preview_url, "ready": True, "baked": True}
    source = resolve_pack_preview_source(db, user, pack)
    if not source:
        raise HTTPException(status_code=400, detail="Open a workbench session first")
    session = (
        db.query(WorkbenchSession)
        .filter(WorkbenchSession.owner_id == user.id)
        .order_by(WorkbenchSession.updated_at.desc())
        .first()
    )
    official_demo = bool(pack.is_official and source.owner_id != user.id)
    job = create_generation_job(
        db,
        user,
        job_type="pack_preview",
        config={
            "pack_id": str(pack.id),
            "source_work_id": str(source.id),
            "session_id": str(session.id) if session else None,
            "official_demo": official_demo,
        },
        status_message="正在预听效果包…",
    )
    dispatch_pack_preview(db, user.id, str(job.id), job.config or {})
    return {"job_id": str(job.id), "ready": False, "official_demo": official_demo}


def _copy_review_stems_as_edit_lanes(db: Session, work: Work) -> dict[str, Any] | None:
    pps = work.post_process_status if isinstance(work.post_process_status, dict) else {}
    stems = pps.get("stems") if isinstance(pps.get("stems"), dict) else {}
    urls = stems.get("urls") if isinstance(stems.get("urls"), dict) else {}
    keys = stems.get("keys") if isinstance(stems.get("keys"), dict) else {}
    if stems.get("quality") != "demucs" or not urls:
        return None
    return {
        "grade": "edit",
        "quality": stems.get("quality"),
        "urls": dict(urls),
        "keys": dict(keys),
        "copied_from_review": True,
        "not_review_stems": True,
        "not_store_tracks": True,
        "updated_at": datetime.utcnow().isoformat(),
    }


def _ensure_lane_graph(session: WorkbenchSession) -> None:
    graph = validate_mix_graph(session.mix_graph or {}, work_id=str(session.source_work_id))
    if not any(lane.get("kind") != "master" for lane in graph.get("lanes") or []):
        graph["lanes"] = default_edit_lanes()
        session.mix_graph = graph


def persist_edit_lanes(
    db: Session,
    session: WorkbenchSession,
    urls: dict[str, str],
    keys: dict[str, str],
    *,
    quality: str,
    marks: list | None = None,
    label: str | None = None,
    flac_urls: dict[str, str] | None = None,
) -> None:
    _ensure_lane_graph(session)
    session.edit_lanes = {
        "grade": "edit",
        "quality": quality,
        "label": label or ("分轨" if quality == "demucs" else "预览近似"),
        "urls": urls,
        "flac_urls": dict(flac_urls or {}),
        "keys": keys,
        "marks": list(marks or []),
        "copied_from_review": False,
        "not_review_stems": True,
        "not_store_tracks": True,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.updated_at = datetime.utcnow()
    db.add(session)


def attach_render_result(db: Session, session_id: str, work_id: uuid.UUID, job_id: uuid.UUID) -> None:
    row = db.query(WorkbenchSession).filter(WorkbenchSession.id == uuid.UUID(session_id)).first()
    if not row:
        return
    if row.last_result_work_id and row.last_result_work_id != work_id:
        row.previous_result_work_id = row.last_result_work_id
    row.last_result_work_id = work_id
    row.last_render_job_id = job_id
    row.updated_at = datetime.utcnow()
    if row.applied_pack_id:
        pack = db.query(EffectPack).filter(EffectPack.id == row.applied_pack_id).first()
        if pack:
            pack.bounce_count = (pack.bounce_count or 0) + 1
        result = db.query(Work).filter(Work.id == work_id).first()
        if result:
            pps = dict(result.post_process_status or {})
            token = str(row.applied_pack_id)
            pps.setdefault("pack_id", token)
            pps["applied_pack_id"] = token
            pps["tracks"] = 1
            tags = validate_mix_graph(row.mix_graph or {}).get("need_tags") or []
            if tags and not pps.get("need_tag"):
                pps["need_tag"] = tags[0]
            result.post_process_status = pps
            db.add(result)
    db.add(row)


def attach_regen_take(db: Session, session_id: str, work: Work, job_id: uuid.UUID, config: dict[str, Any] | None = None) -> None:
    """Drop a take clip onto the MixGraph. Never moves last_result_work_id."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return
    row = db.query(WorkbenchSession).filter(WorkbenchSession.id == sid).first()
    if not row:
        return
    last_result = row.last_result_work_id
    cfg = config or {}
    graph = validate_mix_graph(row.mix_graph or {}, work_id=str(row.source_work_id))
    start = float(cfg.get("region_start") or 0)
    end = float(cfg.get("region_end") or (start + float(work.duration or 15)))
    if cfg.get("record_type") == "extend" and cfg.get("region_start") is None:
        source = db.query(Work).filter(Work.id == row.source_work_id).first()
        start = float((source.duration if source else 0) or 0)
        end = start + float(work.duration or 15)
    clip_id = f"take{str(work.id).replace('-', '')[:8]}"
    clips = [clip for clip in graph["clips"] if clip["id"] != clip_id]
    if cfg.get("record_type") in {"remelt", "same_style"} and cfg.get("region_start") is not None:
        clips = [
            clip
            for clip in clips
            if clip.get("lane") != "master" or float(clip.get("end") or 0) <= start or float(clip.get("start") or 0) >= end
        ]
    clips.append(
        {
            "id": clip_id,
            "lane": "master",
            "src": f"take:{work.id}",
            "start": start,
            "end": end,
            "offset": 0,
            "fade_in": 0.02,
            "fade_out": 0.02,
            "gain": 1,
            "mute": False,
        }
    )
    graph["clips"] = clips
    region_id = str(cfg.get("region_id") or "sel")
    if cfg.get("region_start") is not None:
        existing = next((row_r for row_r in graph["regions"] if row_r["id"] == region_id), None)
        takes = list((existing or {}).get("takes") or [])
        takes.append({"id": clip_id, "work_id": str(work.id), "kind": str(cfg.get("record_type") or "remelt"), "audio_url": work.audio_url or ""})
        graph = upsert_region(graph, {**(existing or {}), "id": region_id, "start": start, "end": end, "active_take": clip_id, "takes": takes[-8:]})
        graph = activate_take(graph, region_id, clip_id)
    node_type = {"extend": "regen_extend", "remelt": "regen_remelt", "same_style": "regen_same_style"}.get(
        str(cfg.get("record_type") or ""), "regen_remelt"
    )
    graph = upsert_node(
        graph,
        {
            "id": node_type,
            "type": node_type,
            "target": "master",
            "origin": "regen",
            "params": {"job": str(job_id)[:32], "take_work_id": str(work.id), "start": start, "end": end},
        },
    )
    row.mix_graph = validate_mix_graph(graph, work_id=str(row.source_work_id))
    row.last_result_work_id = last_result
    row.last_render_job_id = job_id
    row.updated_at = datetime.utcnow()
    db.add(row)


def undo_session(db: Session, user: User, session_id: str) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    stack = list(row.op_stack or [])
    if stack:
        row.mix_graph = validate_mix_graph(stack.pop(), work_id=str(row.source_work_id))
        row.intensity = float((row.mix_graph or {}).get("intensity") or 1)
        row.op_stack = stack
    else:
        row.mix_graph = empty_graph(str(row.source_work_id))
        row.intensity = 1.0
        row.applied_pack_id = None
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, session_id)


def trim_session(db: Session, user: User, session_id: str, *, start: float, end: float) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    _push_op_stack(row)
    row.mix_graph = set_master_trim(row.mix_graph or {}, start=start, end=end)
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, session_id)


def activate_take_session(db: Session, user: User, session_id: str, *, region_id: str, take_id: str) -> dict[str, Any]:
    row = _get_session(db, session_id, user)
    _push_op_stack(row)
    row.mix_graph = activate_take(row.mix_graph or {}, region_id, take_id)
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_session(db, user, session_id)


def suggest_packs_for_work(db: Session, user: User | None, work_id: str, *, surface: str = "h5") -> list[dict[str, Any]]:
    work = get_owned_work(db, work_id, user) if user else None
    if work is None:
        from app.models.schemas import Work as WorkModel

        try:
            work = db.query(WorkModel).filter(WorkModel.id == uuid.UUID(work_id)).first()
        except ValueError:
            work = None
    tags = suggest_need_tags(list(work.moods or []) if work else [], list(work.genres or []) if work else [])
    packs = list_effect_packs(db, user, scope="official" if surface == "weapp" else "all", surface=surface)
    ranked: list[dict[str, Any]] = []
    for pack in packs:
        need = set(pack.get("need_tags") or pack.get("tags") or [])
        score = len(need.intersection(tags))
        if pack.get("is_official"):
            score += 0.2
        ranked.append({**pack, "suggest_score": score, "suggested_needs": tags})
    ranked.sort(key=lambda row: (-float(row.get("suggest_score") or 0), -(row.get("purchase_count") or 0)))
    top = [row for row in ranked if row.get("suggest_score", 0) > 0][:3]
    return top or ranked[:3]


def _demand_public(row: PackDemand, *, work_title: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "work_id": str(row.work_id),
        "work_title": work_title,
        "brief": row.brief,
        "need_tags": list(row.need_tags or []),
        "bid_credits": row.bid_credits or 0,
        "status": row.status,
        "owner_id": str(row.owner_id),
        "claimed_by_id": str(row.claimed_by_id) if row.claimed_by_id else None,
        "pack_id": str(row.pack_id) if row.pack_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def create_pack_demand(
    db: Session,
    user: User,
    *,
    work_id: str,
    brief: str,
    need_tags: list[str] | None = None,
    bid_credits: int = 0,
    reference_work_id: str | None = None,
) -> dict[str, Any]:
    work = resolve_session_source(db, user, get_owned_work(db, work_id, user))
    text = (brief or "").strip()[:400]
    if len(text) < 4:
        raise HTTPException(status_code=400, detail="Brief required")
    tags = list(dict.fromkeys([*(need_tags or []), *suggest_need_tags(list(work.moods or []), list(work.genres or []))]))[:8]
    if reference_work_id:
        from app.services.reference_track import assert_reference_rights

        ref = assert_reference_rights(db, reference_work_id, user)
        tags = list(dict.fromkeys([*tags, *suggest_need_tags(list(ref.moods or []), list(ref.genres or []))]))[:8]
    row = PackDemand(
        owner_id=user.id,
        work_id=work.id,
        brief=text,
        need_tags=tags,
        bid_credits=max(0, min(PACK_PRICE_MAX, int(bid_credits or 0))),
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _demand_public(row, work_title=work.title)


def list_pack_demands(db: Session, user: User, *, scope: str = "open") -> list[dict[str, Any]]:
    q = db.query(PackDemand)
    if scope == "mine":
        q = q.filter((PackDemand.owner_id == user.id) | (PackDemand.claimed_by_id == user.id))
    else:
        q = q.filter(PackDemand.status == "open")
    rows = q.order_by(PackDemand.created_at.desc()).limit(40).all()
    works = {row.id: row.title for row in db.query(Work).filter(Work.id.in_([item.work_id for item in rows])).all()} if rows else {}
    return [_demand_public(row, work_title=works.get(row.work_id)) for row in rows]


def claim_pack_demand(db: Session, user: User, demand_id: str) -> dict[str, Any]:
    try:
        did = uuid.UUID(demand_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid demand id") from exc
    row = db.query(PackDemand).filter(PackDemand.id == did).first()
    if not row or row.status != "open":
        raise HTTPException(status_code=404, detail="Demand not found")
    if row.owner_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot claim your own demand")
    row.claimed_by_id = user.id
    row.status = "claimed"
    row.updated_at = datetime.utcnow()
    db.commit()
    return _demand_public(row)


def deliver_pack_demand(db: Session, user: User, demand_id: str, *, pack_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    try:
        did = uuid.UUID(demand_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid demand id") from exc
    row = db.query(PackDemand).filter(PackDemand.id == did).first()
    if not row or row.claimed_by_id != user.id:
        raise HTTPException(status_code=404, detail="Demand not found")
    pack = None
    if pack_id:
        pack = db.query(EffectPack).filter(EffectPack.id == uuid.UUID(pack_id), EffectPack.owner_id == user.id).first()
    elif session_id:
        published = publish_pack(
            db,
            user,
            session_id,
            title=(row.brief or "定制包")[:80],
            description=row.brief,
            price_credits=row.bid_credits or 0,
            need_tags=list(row.need_tags or []),
            kind="demand",
        )
        pack = db.query(EffectPack).filter(EffectPack.id == uuid.UUID(published["id"])).first()
    if not pack:
        raise HTTPException(status_code=400, detail="Deliver a pack or session")
    pack.kind = "demand"
    if row.need_tags:
        pack.need_tags = list(row.need_tags)
    row.pack_id = pack.id
    row.status = "delivered"
    row.updated_at = datetime.utcnow()
    bid = row.bid_credits or 0
    if bid > 0 and row.owner_id != user.id:
        if deduct_credits(db, row.owner_id, bid, source="pack_demand"):
            platform_fee = max(1, int(bid * TEMPLATE_PLATFORM_FEE_RATE)) if bid >= 2 else 0
            creator_share = max(0, bid - platform_fee)
            if creator_share:
                _wallet_credit(db, user.id, creator_share, source="effect_pack_sale")
    owner = db.query(User).filter(User.id == row.owner_id).first()
    if owner:
        sess = get_or_create_session(db, owner, str(row.work_id))
        apply_pack(db, owner, sess["id"], str(pack.id), intensity=1.0)
    db.commit()
    return _demand_public(row)


def _released_count_for_pack(db: Session, pack_id: uuid.UUID) -> int:
    token = str(pack_id)
    return (
        db.query(Work)
        .filter(Work.release_status.in_(("live", "queued", "delivering")))
        .filter(
            or_(
                Work.post_process_status["pack_id"].astext == token,
                Work.post_process_status["applied_pack_id"].astext == token,
            )
        )
        .count()
    )


def pack_earnings(db: Session, user: User) -> dict[str, Any]:
    rows = db.query(EffectPack).filter(EffectPack.owner_id == user.id).order_by(EffectPack.created_at.desc()).limit(40).all()
    items = []
    for pack in rows:
        public = _pack_public(pack, owned=True, username=user.display_name or user.username)
        public["released_count"] = _released_count_for_pack(db, pack.id)
        items.append(public)
    return {
        "packs": items,
        "purchase_count": sum(int(item.get("purchase_count") or 0) for item in items),
        "apply_count": sum(int(item.get("apply_count") or 0) for item in items),
        "bounce_count": sum(int(item.get("bounce_count") or 0) for item in items),
        "released_count": sum(int(item.get("released_count") or 0) for item in items),
        "ledger": "credits",
        "fiat": False,
    }


def accept_browser_bounce(
    db: Session,
    user: User,
    session_id: str,
    audio: bytes,
    *,
    title: str = "",
) -> dict[str, Any]:
    """Store a browser-rendered stereo bounce as a new work. The source song is never overwritten."""
    import hashlib

    from app.config import settings
    from app.models.schemas import ProvenanceRecord
    from app.services.media import analyze_loudness, probe_audio
    from app.services.storage import get_storage_service
    from app.services.workbench_render import delivery_masters

    if not audio or len(audio) < 64:
        raise HTTPException(status_code=400, detail="empty_bounce")
    if len(audio) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="bounce_too_large")
    row = _get_session(db, session_id, user)
    source = get_owned_work(db, str(row.source_work_id), user)
    loudness = analyze_loudness(audio)
    masters = delivery_masters(audio, target="stream")
    bounced = masters.get("mp3") or audio
    content_hash = hashlib.sha256(bounced).hexdigest()
    storage = get_storage_service()
    key = storage.generate_work_key(str(user.id))
    storage_key, url = storage.upload_bytes(bounced, key)
    probed = probe_audio(bounced)
    work_title = (title or f"{source.title} · 调音台").strip()[:80]
    work = Work(
        owner_id=user.id,
        title=work_title,
        audio_url=url,
        storage_key=storage_key,
        cover_url=source.cover_url,
        visibility="private",
        content_hash=content_hash,
        parent_work_id=source.id,
        moods=list(source.moods or []),
        genres=list(source.genres or []),
        arousal=source.arousal,
        valence=source.valence,
        tenant_id=user.tenant_id or source.tenant_id,
        duration=probed.get("duration") or source.duration,
        preset_id=source.preset_id,
        allow_remix=source.allow_remix,
        license=source.license,
        post_process_status={
            "workbench": True,
            "browser_bounce": True,
            "parent_work_id": str(source.id),
            "tracks": 1,
            "not_store_multitrack": True,
            "loudness_target": "stream",
            "loudness_check": loudness,
        },
    )
    db.add(work)
    db.flush()
    wav_url = None
    if masters.get("wav"):
        wav_key, wav_url = storage.upload_bytes(masters["wav"], f"works/{work.id}/master.wav", "audio/wav")
        stamped = dict(work.post_process_status or {})
        stamped["master"] = {"key": wav_key, "url": wav_url, "sample_rate": 44100, "bit_depth": 24, "channels": 2}
        work.post_process_status = stamped
    db.add(
        ProvenanceRecord(
            work_id=work.id,
            parent_work_id=source.id,
            pipeline_version=settings.pipeline_version,
            step_index=0,
            record_type="workbench",
            music_request={
                "parent_work_id": str(source.id),
                "session_id": str(row.id),
                "exit": "stereo_master",
                "browser_bounce": True,
                "not_store_multitrack": True,
            },
            output_meta={"sha256": content_hash, "tracks": 1, "exit": "stereo_master"},
        )
    )
    if row.last_result_work_id and row.last_result_work_id != work.id:
        row.previous_result_work_id = row.last_result_work_id
    row.last_result_work_id = work.id
    row.updated_at = datetime.utcnow()
    db.commit()
    return {
        "work_id": str(work.id),
        "title": work.title,
        "audio_url": url,
        "wav_url": wav_url,
        "parent_work_id": str(source.id),
        "loudness": loudness,
        "tracks": 1,
    }
