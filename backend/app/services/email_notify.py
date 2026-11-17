"""Email notification channel — transactional emails for key events."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def formatted_from() -> str:
    address = (settings.email_from or settings.smtp_user or "").strip()
    if not address:
        address = f"noreply@{settings.app_name or 'bittune'}"
    if "<" in address:
        return address
    name = settings.app_name or "比特音"
    return f"{name} <{address}>"


async def send_email(
    to: str,
    subject: str,
    body_html: str,
    *,
    body_text: str | None = None,
) -> bool:
    """Send a transactional email via configured SMTP relay or API.

    Returns True if sent successfully, False otherwise.
    """
    if not settings.smtp_host and not settings.email_api_url:
        logger.debug("Email not configured, skipping: to=%s subject=%s", to, subject)
        return False

    if settings.email_api_url:
        return await _send_via_api(to, subject, body_html, body_text)
    import asyncio
    return await asyncio.to_thread(_send_via_smtp, to, subject, body_html, body_text)


async def _send_via_api(to: str, subject: str, body_html: str, body_text: str | None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                settings.email_api_url,
                json={
                    "to": to,
                    "from": formatted_from(),
                    "subject": subject,
                    "html": body_html,
                    "text": body_text or "",
                },
                headers={"Authorization": f"Bearer {settings.email_api_key}"},
            )
            return resp.status_code < 400
    except Exception as exc:
        logger.warning("Email API send failed: %s", exc)
        return False


def _send_via_smtp(to: str, subject: str, body_html: str, body_text: str | None) -> bool:
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["From"] = formatted_from()
        msg["To"] = to
        msg["Subject"] = subject
        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 587) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password or "")
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("SMTP send failed: %s", exc)
        return False
