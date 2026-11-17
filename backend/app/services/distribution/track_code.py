"""Platform-minted track codes so label submit never waits on a human ISRC."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.models.schemas import Release, ReleaseMetadata, TrackCodeAlias, Work

_CODE_IN_TITLE = re.compile(r"\[?(VS[0-9A-F]{12})\]?", re.I)


def mint_track_code(work_id) -> str:
    hexed = uuid.UUID(str(work_id)).hex[:12].upper()
    return f"VS{hexed}"


def _norm(value: str | None) -> str:
    return (value or "").replace("-", "").replace(" ", "").upper()


def ensure_track_code(db: Session, work: Work, release: Release | None = None) -> str:
    code = _norm(work.isrc) or mint_track_code(work.id)
    if not code.startswith("VS") and not work.isrc:
        code = mint_track_code(work.id)
    if not work.isrc:
        work.isrc = code
    _remember_alias(db, work.id, work.isrc, source="work")
    _remember_alias(db, work.id, code, source="internal")
    if release:
        meta = db.query(ReleaseMetadata).filter(ReleaseMetadata.release_id == release.id).first()
        if meta and not meta.isrc:
            meta.isrc = work.isrc or code
        if meta and meta.isrc:
            _remember_alias(db, work.id, meta.isrc, source="release")
    return work.isrc or code


def register_alias(db: Session, work: Work, code: str, *, source: str = "alias") -> str:
    normed = _norm(code)
    if not normed:
        return work.isrc or mint_track_code(work.id)
    _remember_alias(db, work.id, normed, source=source)
    return normed


def title_with_code(title: str | None, code: str | None) -> str:
    base = (title or "").strip() or "Untitled"
    normed = _norm(code)
    if not normed:
        return base
    if normed in _norm(base):
        return base
    return f"{base} [{normed}]"


def extract_track_code(text: str | None) -> str | None:
    if not text:
        return None
    match = _CODE_IN_TITLE.search(text)
    return _norm(match.group(1)) if match else None


def work_id_for_code(db: Session, code: str | None):
    normed = _norm(code)
    if not normed:
        return None
    alias = db.query(TrackCodeAlias).filter(TrackCodeAlias.code == normed).first()
    if alias:
        return alias.work_id
    work = db.query(Work).filter(Work.isrc == normed).first()
    return work.id if work else None


def _remember_alias(db: Session, work_id, code: str | None, *, source: str) -> None:
    normed = _norm(code)
    if not normed:
        return
    row = db.query(TrackCodeAlias).filter(TrackCodeAlias.code == normed).first()
    if row:
        return
    for pending in db.new:
        if isinstance(pending, TrackCodeAlias) and pending.code == normed:
            return
    db.add(TrackCodeAlias(work_id=work_id, code=normed, source=source))
    db.flush()
