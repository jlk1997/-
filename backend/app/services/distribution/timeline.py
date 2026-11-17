"""Work release timeline — unified view of where each song is in the pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, GenerationJob, ProvenanceRecord, Release, Work

logger = logging.getLogger(__name__)


def work_timeline(db: Session, work_id: str, user_id: str) -> dict[str, Any]:
    """Build a timeline for a single work showing all pipeline stages."""
    import uuid

    try:
        wid = uuid.UUID(work_id)
        uid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        return {"error": "invalid_id"}

    work = db.query(Work).filter(Work.id == wid, Work.owner_id == uid).first()
    if not work:
        return {"error": "work_not_found"}

    stages: list[dict[str, Any]] = []

    # Stage 1: Generation (single / workbench bounce / regen all stamp work_id or work_ids)
    job = _generation_job_for_work(db, work)
    pps_early = dict(work.post_process_status or {})
    gen_label = "美化母带" if pps_early.get("workbench") or (job and job.job_type == "workbench_render") else "生成"
    gen_stage = {
        "stage": "generation",
        "label": gen_label,
        "status": "completed" if work.audio_url else "pending",
        "completed_at": job.updated_at.isoformat() if job and job.status == "completed" else None,
    }
    stages.append(gen_stage)

    # Stage 2: Post-processing
    pps = dict(work.post_process_status or {})
    pp_state = pps.get("state", "pending")
    pp_stage = {
        "stage": "post_process",
        "label": "后处理",
        "status": pp_state,
        "hls_done": pps.get("hls_done", False),
        "cover_done": pps.get("cover_done", False),
        "can_rerun": pp_state == "degraded",
    }
    stages.append(pp_stage)

    from app.services.distribution.asset_profiles import (
        aggregate_needs,
        clips_ready,
        instrumental_sku_ref,
        listing_master_ref,
        review_stems_ready,
        stems_quality,
    )

    release = db.query(Release).filter(Release.work_id == work.id).first()
    listing = listing_master_ref(work)
    quality = stems_quality(work)
    needs = aggregate_needs(list(release.selected_channels or []) if release else [])
    listing_ok = bool(listing.get("wav_key"))
    evidence_ok = (not needs.get("needs_stems_evidence")) or review_stems_ready(work)
    clips_ok = (not needs.get("needs_clips")) or clips_ready(work)
    inst_ok = (not needs.get("needs_instrumental")) or bool(instrumental_sku_ref(work).get("ready"))
    assets_stage = {
        "stage": "release_assets",
        "label": "发行资产",
        "status": "ready" if listing_ok and evidence_ok and clips_ok and inst_ok else "pending",
        "master_ready": listing_ok,
        "master_wav": bool(listing.get("wav_key")),
        "stems_quality": quality or "none",
        "evidence_ready": review_stems_ready(work),
        "evidence_needed": bool(needs.get("needs_stems_evidence")),
        "clips_ready": clips_ready(work),
        "instrumental_ready": bool(instrumental_sku_ref(work).get("ready")),
    }
    stages.append(assets_stage)

    # Stage 3: QC
    qc_result = pps.get("release_qc_result") or {}
    qc_stage = {
        "stage": "qc",
        "label": "质检",
        "status": "passed" if qc_result.get("passed") else ("failed" if qc_result else "pending"),
        "release_status": work.release_status,
    }
    stages.append(qc_stage)

    # Stage 4: Distribution
    deliveries = []
    if release:
        delivery_rows = db.query(DistributionDelivery).filter(
            DistributionDelivery.release_id == release.id
        ).all()
        for d in delivery_rows:
            deliveries.append({
                "channel_code": d.channel_code,
                "status": d.status,
                "tier": getattr(d, "delivery_tier", None),
                "store_url": d.store_url,
                "external_id": d.external_id,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            })

    dist_status = _aggregate_delivery_status(deliveries)
    dist_stage = {
        "stage": "distribution",
        "label": "分发",
        "status": dist_status,
        "has_receipt": dist_status == "live",
        "deliveries": deliveries,
    }
    stages.append(dist_stage)

    # Stage 5: Revenue — only label statements, never radio warmup display rows
    from app.models.schemas import PlatformMetricSnapshot
    from app.services.royalty.subjects import money_bucket

    snapshots = (
        db.query(PlatformMetricSnapshot)
        .filter(PlatformMetricSnapshot.work_id == work.id, PlatformMetricSnapshot.revenue_minor > 0)
        .all()
    )
    official = [s for s in snapshots if s.usable_for_settlement and money_bucket(s.source) == "dsp"]
    revenue_stage = {
        "stage": "revenue",
        "label": "收入",
        "status": "earning" if official else "waiting",
        "total_revenue_minor": sum(s.revenue_minor or 0 for s in official),
        "currency": official[0].currency if official else None,
    }
    stages.append(revenue_stage)

    # Next action
    next_action = _compute_next_action(stages, work)

    return {
        "work_id": str(work.id),
        "title": work.title,
        "stages": stages,
        "next_action": next_action,
        "current_stage": _current_stage(stages),
    }


def _aggregate_delivery_status(deliveries: list[dict]) -> str:
    if not deliveries:
        return "not_started"
    from app.services.distribution.catalog import has_live_receipt

    receipt_live = any(
        d.get("status") == "live"
        and has_live_receipt(
            store_url=d.get("store_url"),
            external_id=d.get("external_id"),
            channel_code=d.get("channel_code"),
        )
        for d in deliveries
    )
    statuses = {d.get("status") for d in deliveries}
    if receipt_live:
        return "live"
    if "live" in statuses or any(s in statuses for s in ("in_review", "session_running", "submitting", "ops_queue", "session_wait")):
        return "in_progress"
    if statuses == {"rejected"}:
        return "rejected"
    return "pending"


def _current_stage(stages: list[dict]) -> str:
    for stage in reversed(stages):
        if stage["status"] not in ("pending", "not_started", "waiting"):
            return stage["stage"]
    return "generation"


def _generation_job_for_work(db: Session, work: Work) -> GenerationJob | None:
    """Find the job that created this work. Bounce jobs store work_id; playlists store work_ids."""
    prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
    if prov and prov.job_id:
        hit = db.query(GenerationJob).filter(GenerationJob.id == prov.job_id).first()
        if hit:
            return hit
    wid = str(work.id)
    return (
        db.query(GenerationJob)
        .filter(GenerationJob.owner_id == work.owner_id)
        .filter(
            or_(
                GenerationJob.result["work_id"].astext.contains(wid),
                GenerationJob.result["work_ids"].astext.contains(wid),
            )
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )


def _compute_next_action(stages: list[dict], work) -> dict[str, Any]:
    """Return the single highest-priority next action."""
    pp = next((s for s in stages if s["stage"] == "post_process"), {})
    if pp.get("can_rerun"):
        return {"action": "reprocess", "label": "重新后处理", "priority": 1}

    qc = next((s for s in stages if s["stage"] == "qc"), {})
    dist = next((s for s in stages if s["stage"] == "distribution"), {})
    pps = work.post_process_status if isinstance(getattr(work, "post_process_status", None), dict) else {}
    already_bounced = bool(pps.get("workbench"))
    if (
        not already_bounced
        and getattr(work, "audio_url", None)
        and dist.get("status") == "not_started"
        and qc.get("status") == "pending"
        and not pp.get("can_rerun")
    ):
        return {
            "action": "beautify",
            "label": "先美化再发行",
            "hint": "打成新母带再上架，原曲保留。店端仍是一首立体声。",
            "priority": 2,
        }

    if qc.get("status") == "pending" and pp.get("status") in ("completed", "ready"):
        return {"action": "run_qc", "label": "运行质检", "priority": 2}

    assets = next((s for s in stages if s["stage"] == "release_assets"), {})
    if dist.get("status") == "not_started" and qc.get("status") == "passed":
        go = {"action": "release", "label": "发行", "priority": 3}
        if assets.get("evidence_needed") and not assets.get("evidence_ready"):
            go["hint"] = "国内原创证明包未就绪，不影响全球 DSP 上架"
        return go

    if dist.get("status") in ("pending", "in_progress"):
        wait = {"action": "wait", "label": "等待上架", "priority": 10}
        if assets.get("evidence_needed") and not assets.get("evidence_ready"):
            wait["hint"] = "国内原创证明包未就绪，不影响全球 DSP 上架"
        return wait

    if dist.get("status") == "live":
        rev = next((s for s in stages if s["stage"] == "revenue"), {})
        if rev.get("status") == "waiting":
            return {"action": "wait_revenue", "label": "等待收入", "priority": 10}
        return {"action": "done", "label": "收入已到账", "priority": 99}

    return {"action": "generate", "label": "开始创作", "priority": 0}
