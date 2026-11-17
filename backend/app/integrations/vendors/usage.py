"""One ApiUsageLog row per music-provider attempt. Never stores the API key."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.models.schemas import ApiUsageLog


def record_provider_attempt(
    db: Session | None,
    *,
    user_id: str | None,
    provider: str,
    model: str,
    endpoint: str,
    tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    if db is None:
        return
    owner = None
    if user_id:
        try:
            owner = uuid.UUID(str(user_id))
        except ValueError:
            owner = None
    slot = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()
    try:
        slot.add(
            ApiUsageLog(
                user_id=owner,
                provider=(provider or "unknown")[:50],
                model=(model or "unknown")[:100],
                endpoint=(endpoint or "/music_generation")[:255],
                tokens_used=int(tokens or 0),
                extra_data=dict(metadata or {}),
            )
        )
        slot.commit()
    except Exception:
        slot.rollback()
    finally:
        slot.close()
