import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.schemas import User, Work

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

ALLOWED_AUDIO_MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/flac", "audio/aac", "audio/mp4", "audio/x-m4a"}
AUDIO_MAGIC_BYTES = {
    b"ID3": "audio/mpeg",           # MP3 with ID3 tag
    b"\xff\xfb": "audio/mpeg",      # MP3 sync word
    b"\xff\xf3": "audio/mpeg",      # MP3 sync word
    b"\xff\xf2": "audio/mpeg",      # MP3 sync word
    b"RIFF": "audio/wav",           # WAV
    b"OggS": "audio/ogg",           # OGG
    b"fLaC": "audio/flac",          # FLAC
}


def validate_audio_upload(content: bytes, content_type: str | None = None) -> str | None:
    """Return error message if upload is invalid, None if OK."""
    if len(content) > MAX_UPLOAD_BYTES:
        return f"File too large ({len(content)} bytes, max {MAX_UPLOAD_BYTES})"
    if len(content) < 128:
        return "File too small to be valid audio"

    # MIME type check
    if content_type and content_type.lower() not in ALLOWED_AUDIO_MIMES:
        return f"Unsupported content type: {content_type}"

    # Magic bytes check
    header = content[:4]
    matched = False
    for magic, _mime in AUDIO_MAGIC_BYTES.items():
        if header[:len(magic)] == magic:
            matched = True
            break
    # Also check for MP4/M4A (ftyp atom)
    if not matched and len(content) >= 8 and content[4:8] == b"ftyp":
        matched = True
    if not matched:
        return "File does not appear to be a valid audio file (magic bytes mismatch)"
    return None


def parse_uuid(value: str, *, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def can_view_work(work: Work, user: User | None) -> bool:
    if user is not None and work.owner_id == user.id:
        return True
    from app.services.tenant import is_multi_tenant_enabled, tenant_id_for_user

    if is_multi_tenant_enabled() and user is not None and work.tenant_id and work.tenant_id != tenant_id_for_user(user):
        return False
    if work.visibility in ("public", "unlisted"):
        return True
    return False


def _resolve_owner_id(user: User | uuid.UUID) -> uuid.UUID:
    return user.id if isinstance(user, User) else user


def can_use_work_as_seed(work: Work, user: User | uuid.UUID, db: Session | None = None) -> bool:
    owner_id = _resolve_owner_id(user)
    if work.owner_id == owner_id:
        return True
    from app.services.tenant import is_multi_tenant_enabled, tenant_id_for_user

    resolved_user = user if isinstance(user, User) else None
    if resolved_user is None and db is not None:
        resolved_user = db.query(User).filter(User.id == owner_id).first()
    if resolved_user and is_multi_tenant_enabled(db) and work.tenant_id != tenant_id_for_user(resolved_user):
        return False
    return work.visibility == "public"


def can_remix_work(work: Work) -> bool:
    if work.allow_remix is False:
        return False
    license_key = (work.license or "allow_remix").lower()
    if license_key in ("no_derivatives", "no_remix"):
        return False
    return True


def requires_attribution(work: Work) -> bool:
    license_key = (work.license or "allow_remix").lower()
    return license_key in ("attribution", "attribution_required")


def get_owned_work(db: Session, work_id: str, user: User) -> Work:
    work = db.query(Work).filter(Work.id == parse_uuid(work_id, field="work_id")).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if work.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return work


def get_viewable_work(db: Session, work_id: str, user: User) -> Work:
    work = db.query(Work).filter(Work.id == parse_uuid(work_id, field="work_id")).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if not can_view_work(work, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return work


def get_viewable_work_optional(db: Session, work_id: str, user: User | None) -> Work:
    work = db.query(Work).filter(Work.id == parse_uuid(work_id, field="work_id")).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    if not can_view_work(work, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return work


def get_work_or_404(db: Session, work_id: str) -> Work:
    """Fetch a work by id without view gating.

    For media streaming endpoints (audio/HLS) the request carries no auth header,
    so authorization is delegated to the short-lived playback ticket via
    ``validate_playback_access``. View permission must NOT be enforced here or a
    valid ticket could never grant access to a private/just-generated work.
    """
    work = db.query(Work).filter(Work.id == parse_uuid(work_id, field="work_id")).first()
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


def assert_seed_rights(db: Session, work_id: str, user: User) -> Work:
    """Own works always; others need an open remix license."""
    work = get_seed_work(db, work_id, user)
    if work.owner_id != user.id and not can_remix_work(work):
        raise HTTPException(status_code=403, detail="原作者未开放二次创作")
    return work


def get_seed_work(db: Session, work_id: str, user: User) -> Work:
    work = db.query(Work).filter(Work.id == parse_uuid(work_id, field="work_id")).first()
    if not work:
        raise HTTPException(status_code=404, detail="Seed work not found")
    if not can_use_work_as_seed(work, user, db):
        raise HTTPException(status_code=403, detail="Cannot use this work as seed")
    return work
