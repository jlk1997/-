"""Operational alerting — one call site for anything a human must look at.

Every alert lands in the structured log. When configured it also reaches Sentry and an
ops webhook (Slack / Feishu / DingTalk incoming-webhook shape). Alerts are deduplicated
in the shared cache so a stuck loop does not page anyone a thousand times.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger("vibe.alert")

Severity = Literal["info", "warning", "error", "critical"]

_LOG_LEVELS: dict[str, int] = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _dedupe(kind: str, dedupe_key: str | None, window_seconds: int) -> bool:
    """Return True when this alert was already sent inside the window."""
    if not dedupe_key or window_seconds <= 0:
        return False
    try:
        from app.services.cache import cache_get, cache_set

        cache_key = f"alert:{kind}:{dedupe_key}"
        if cache_get(cache_key):
            return True
        cache_set(cache_key, "1", window_seconds)
    except Exception:
        return False
    return False


def _to_sentry(kind: str, message: str, severity: str, context: dict[str, Any]) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("alert_kind", kind)
            for key, value in context.items():
                scope.set_extra(key, value)
            sentry_sdk.capture_message(message, level="error" if severity == "critical" else severity)
    except Exception:
        logger.debug("sentry alert delivery failed", exc_info=True)


def _to_webhook(kind: str, message: str, severity: str, context: dict[str, Any]) -> None:
    url = (settings.ops_alert_webhook_url or "").strip()
    if not url:
        return
    try:
        import httpx

        text = f"[{severity.upper()}] {settings.app_name} · {kind}\n{message}"
        if context:
            text += f"\n```{json.dumps(context, ensure_ascii=False, default=str)[:1500]}```"
        httpx.post(url, json={"text": text, "msgtype": "text", "content": {"text": text}}, timeout=5)
    except Exception:
        logger.debug("ops webhook alert delivery failed", exc_info=True)


def alert(
    kind: str,
    message: str,
    *,
    severity: Severity = "warning",
    context: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    dedupe_seconds: int = 300,
) -> bool:
    """Record an operational alert. Returns False when suppressed as a duplicate.

    `kind` is a stable machine-readable slug (``post_process_failed``,
    ``selector_broke``…) used for dedupe keys, Sentry tags, and log filtering.
    """
    payload = dict(context or {})
    if _dedupe(kind, dedupe_key, dedupe_seconds):
        return False

    logger.log(
        _LOG_LEVELS.get(severity, logging.WARNING),
        "alert kind=%s message=%s context=%s",
        kind,
        message,
        json.dumps(payload, ensure_ascii=False, default=str)[:2000],
    )
    _to_sentry(kind, message, severity, payload)
    _to_webhook(kind, message, severity, payload)
    return True
