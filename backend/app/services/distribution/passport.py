"""Release passport — shareable identity + live store links."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import DistributionDelivery, Release, ReleaseMetadata, Work
from app.services.c2pa import c2pa_state
from app.services.distribution.catalog import (
    channel_display_name,
    channel_sop,
    channel_upload_url,
    clip_windows,
    has_live_receipt,
    list_portal_channels,
)
from app.services.distribution.service import _license_rate, _release_metadata_payload, user_delivery_status


def workbench_human_edits(prov) -> list[dict]:
    """Passport rights: include MixGraph bounce as a human-edit stamp, not a store stem."""
    edits: list[dict] = []
    if not prov:
        return edits
    if isinstance(prov.output_meta, dict):
        edits.extend([row for row in (prov.output_meta.get("human_edits") or []) if isinstance(row, dict)])
    req = prov.music_request if isinstance(getattr(prov, "music_request", None), dict) else {}
    if getattr(prov, "record_type", None) == "workbench" or req.get("graph_hash"):
        if not any(row.get("kind") == "workbench" for row in edits):
            edits.append(
                {
                    "kind": "workbench",
                    "section": "master",
                    "note": "beautify_master",
                    "graph_hash": req.get("graph_hash"),
                    "pack_id": req.get("pack_id"),
                    "exit": req.get("exit") or "stereo_master",
                    "not_store_multitrack": True,
                }
            )
    return edits


def live_store_counts(db: Session, work_ids: list) -> dict:
    if not work_ids:
        return {}
    from app.services.distribution.catalog import has_live_receipt

    rows = (
        db.query(
            DistributionDelivery.work_id,
            DistributionDelivery.channel_code,
            DistributionDelivery.store_url,
            DistributionDelivery.external_id,
        )
        .filter(DistributionDelivery.work_id.in_(work_ids), DistributionDelivery.status == "live")
        .all()
    )
    counts: dict = {}
    seen: set = set()
    for work_id, channel, store_url, external_id in rows:
        if not has_live_receipt(store_url=store_url, external_id=external_id, channel_code=channel):
            continue
        key = (work_id, channel)
        if key in seen:
            continue
        seen.add(key)
        counts[work_id] = counts.get(work_id, 0) + 1
        counts[str(work_id)] = counts[work_id]
    return counts


def live_store_count(db: Session, work_id) -> int:
    mapped = live_store_counts(db, [work_id])
    return int(mapped.get(work_id, mapped.get(str(work_id), 0)))


def _release_for_work(db: Session, work: Work) -> Release | None:
    return (
        db.query(Release)
        .filter(Release.work_id == work.id)
        .order_by(Release.updated_at.desc())
        .first()
    )


def build_passport(db: Session, *, work_id: str | None = None, release_id: str | None = None) -> dict:
    release = None
    work = None
    if release_id:
        try:
            import uuid

            rid = uuid.UUID(release_id)
        except ValueError as exc:
            raise HTTPException(400, "Invalid release id") from exc
        release = db.query(Release).filter(Release.id == rid).first()
        if not release:
            raise HTTPException(404, "Release not found")
        work = db.query(Work).filter(Work.id == release.work_id).first()
    elif work_id:
        try:
            import uuid

            wid = uuid.UUID(work_id)
        except ValueError as exc:
            raise HTTPException(400, "Invalid work id") from exc
        work = db.query(Work).filter(Work.id == wid).first()
        if not work:
            raise HTTPException(404, "Work not found")
        release = _release_for_work(db, work)
    else:
        raise HTTPException(400, "work_id or release_id required")

    deliveries = []
    if release:
        deliveries = db.query(DistributionDelivery).filter(DistributionDelivery.release_id == release.id).all()
    elif work:
        deliveries = db.query(DistributionDelivery).filter(DistributionDelivery.work_id == work.id).all()
    from app.services.distribution.reject import humanize_reject

    stores = []
    for d in deliveries:
        receipt = has_live_receipt(store_url=d.store_url, external_id=d.external_id, channel_code=d.channel_code)
        stores.append({
            "channel_code": d.channel_code,
            "name": channel_display_name(d.channel_code),
            "status": d.status,
            "user_status": user_delivery_status(
                d.status,
                d.last_error,
                has_receipt=receipt if d.status == "live" else None,
            ),
            "has_receipt": receipt,
            "store_url": d.store_url,
            "external_id": d.external_id,
            "delivery_tier": getattr(d, "delivery_tier", None),
            "upload_url": channel_upload_url(d.channel_code),
            "sop": channel_sop(d.channel_code),
            "reject_reason": d.reject_reason,
            "reject_next": humanize_reject(d.reject_reason or d.last_error, status=d.status),
        })
    live = [row for row in stores if row["status"] == "live" and row.get("has_receipt")]
    meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first() if release else None
    payload = _release_metadata_payload(db, release, meta) if release else {
        "title": work.title if work else None,
        "artist_name": None,
        "isrc": work.isrc if work else None,
        "upc": None,
        "cover_url": work.cover_url if work else None,
        "ai_disclosed": False,
    }
    pps = (work.post_process_status or {}) if work else {}
    from app.services.royalty.sync_desk import enabled_tiers, listing_enabled, rights_certificate_for_work
    from app.services.distribution.asset_profiles import release_asset_status

    commercial = bool(work and listing_enabled(work))
    human_edits = []
    if work:
        from app.models.schemas import ProvenanceRecord

        prov = db.query(ProvenanceRecord).filter(ProvenanceRecord.work_id == work.id).first()
        human_edits = workbench_human_edits(prov)
    sync_tiers = enabled_tiers(work) if work and commercial else []
    return {
        "work_id": str(work.id) if work else None,
        "release_id": str(release.id) if release else None,
        "mode": release.mode if release else None,
        "title": payload.get("title"),
        "artist_name": payload.get("artist_name"),
        "isrc": payload.get("isrc"),
        "upc": payload.get("upc"),
        "cover_url": payload.get("cover_url"),
        "ai_disclosed": bool(payload.get("ai_disclosed", False)),
        "c2pa_verified": c2pa_state(pps) == "embedded",
        "c2pa_state": c2pa_state(pps),
        "commission_rate": _license_rate(db, release) if release else None,
        "live_stores": len(live),
        "store_count": len(stores),
        "stores": stores,
        "share_line": _share_line(payload.get("title"), len(live), trial=_radio_trial_live(work)),
        "asset_status": release_asset_status(work, release.selected_channels if release else None) if work else None,
        "needs_ai_musician": bool(
            work
            and (
                (release and "netease" in (release.selected_channels or []))
                or any(d.channel_code == "netease" for d in deliveries)
            )
        ),
        "clip_windows": (pps.get("clip_windows") if isinstance(pps.get("clip_windows"), list) else None)
        or clip_windows(getattr(work, "duration", None)),
        "portal_channels": list_portal_channels(),
        "commercial": commercial,
        "sync_tiers": sync_tiers,
        "human_edits": human_edits,
        "next_store_action": next(
            (row["reject_next"] for row in stores if row.get("status") == "rejected" and row.get("reject_next", {}).get("next")),
            None,
        ),
        "rights_certificate": rights_certificate_for_work(
            work,
            db=db,
            extra={
                "ai_disclosed": bool(payload.get("ai_disclosed", False)),
                "human_edits": human_edits,
                "commission_rate": _license_rate(db, release) if release else None,
                "sync_tiers": sync_tiers,
            },
        ),
    }


def _radio_trial_live(work: Work | None) -> bool:
    if not work:
        return False
    try:
        from app.services.radio.network import _trial_live

        return bool(_trial_live(work))
    except Exception:
        raw = (work.post_process_status or {}).get("radio_trial") or {}
        return raw.get("status") == "live"


def _share_line(title: str | None, live: int, trial: bool = False) -> str:
    name = title or "未命名作品"
    if live > 0 and trial:
        return f"「{name}」已上架 {live} 店 / 试听局进行中"
    if live > 0:
        return f"「{name}」已上架 {live} 店"
    if trial:
        return f"「{name}」试听局进行中"
    return f"「{name}」正在发行 · 比特音发行护照"


def reveal_passport(db: Session, *, work_id: str | None = None, release_id: str | None = None, viewer=None) -> dict:
    data = build_passport(db, work_id=work_id, release_id=release_id)
    work = None
    if data.get("work_id"):
        import uuid

        work = db.query(Work).filter(Work.id == uuid.UUID(data["work_id"])).first()
    public = bool(data.get("live_stores")) or bool(work and work.visibility == "public")
    if public:
        return data
    if viewer and work and (viewer.id == work.owner_id or getattr(viewer, "is_admin", False)):
        return data
    raise HTTPException(404, "Passport not found")
