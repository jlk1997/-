"""Map partner / store reject codes to one next step — not a status wall."""

from __future__ import annotations

REJECT_NEXT = {
    "cover": {"code": "cover", "next": "补封面"},
    "ai_disclose": {"code": "ai_disclose", "next": "补 AI 披露"},
    "loudness": {"code": "loudness", "next": "换母带响度"},
    "isrc": {"code": "isrc", "next": "补曲目编码"},
    "master": {"code": "master", "next": "等母带 WAV 落库"},
    "ops_queue": {"code": "ops_queue", "next": "进运营队列，不是故障"},
}


def humanize_reject(reason: str | None, *, status: str | None = None) -> dict:
    text = str(reason or "").lower()
    status_key = str(status or "").lower()
    if status_key == "ops_queue" or "ops_queue" in text or "运营代发" in text or "未配置" in text:
        return {**REJECT_NEXT["ops_queue"], "message": reason or REJECT_NEXT["ops_queue"]["next"]}
    if "cover" in text or "artwork" in text or "封面" in text:
        return {**REJECT_NEXT["cover"], "message": reason}
    if "disclos" in text or "ai label" in text or "ai_generated" in text or "披露" in text:
        return {**REJECT_NEXT["ai_disclose"], "message": reason}
    if "loud" in text or "lufs" in text or "响度" in text:
        return {**REJECT_NEXT["loudness"], "message": reason}
    if "isrc" in text or "upc" in text or "曲目编码" in text:
        return {**REJECT_NEXT["isrc"], "message": reason}
    if "waiting_master_wav" in text or "master.wav" in text:
        return {**REJECT_NEXT["master"], "message": reason}
    if not text:
        return {"code": "none", "next": None, "message": None}
    return {"code": "other", "next": str(reason)[:80], "message": reason}


def writeback_catalog_codes(db, delivery, *, isrc: str | None = None, upc: str | None = None) -> dict:
    from app.models.schemas import Release, ReleaseMetadata, Work

    written = {"isrc": False, "upc": False}
    clean_isrc = str(isrc or "").strip().upper()[:15] or None
    clean_upc = str(upc or "").strip()[:32] or None
    work = None
    if getattr(delivery, "work_id", None):
        work = db.query(Work).filter(Work.id == delivery.work_id).first()
    if work and clean_isrc and not work.isrc:
        work.isrc = clean_isrc
        written["isrc"] = True
    release = None
    if getattr(delivery, "release_id", None):
        release = db.query(Release).filter(Release.id == delivery.release_id).first()
    if release:
        if clean_upc and not getattr(release, "upc", None):
            release.upc = clean_upc
            written["upc"] = True
        meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
        if meta:
            if clean_isrc and not meta.isrc:
                meta.isrc = clean_isrc
                written["isrc"] = True
            if clean_upc and not meta.upc:
                meta.upc = clean_upc
                written["upc"] = True
    return written
