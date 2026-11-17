"""Immutable platform-as-submitter events on a delivery. No partner scrape."""

from __future__ import annotations

from datetime import datetime


def append_delivery_event(
    delivery,
    *,
    event: str,
    actor: str | None = None,
    receipt_url: str | None = None,
    external_id: str | None = None,
    message: str | None = None,
) -> None:
    meta = dict(getattr(delivery, "attempt_meta", None) or {})
    rows = list(meta.get("submissions") or [])
    rows.append(
        {
            "at": datetime.utcnow().isoformat(),
            "event": event,
            "ticket_id": str(delivery.id),
            "channel_code": delivery.channel_code,
            "distributor": delivery.distributor_code,
            "actor": actor,
            "receipt_url": receipt_url or delivery.store_url,
            "external_id": external_id or delivery.external_id,
            "status": delivery.status,
            "message": (message or "")[:240] or None,
        }
    )
    meta["submissions"] = rows[-20:]
    delivery.attempt_meta = meta
