"""Hashed email one-time codes for register, login, and password reset."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from typing import Literal

from fastapi import HTTPException, status

from app.config import settings
from app.services.redis_rate_limit import _get_redis

logger = logging.getLogger(__name__)

OTP_PURPOSES = ("register", "login", "reset", "rebind", "bind")
OtpPurpose = Literal["register", "login", "reset", "rebind", "bind"]
PLACEHOLDER_EMAIL_SUFFIX = "@wechat.local"
OTP_TTL_SECONDS = 600
OTP_COOLDOWN_SECONDS = 60
OTP_RE = re.compile(r"^\d{6}$")

_memory_otp: dict[str, tuple[str, float]] = {}
_memory_cd: dict[str, float] = {}
_force_memory = False


def reset_otp_state_for_tests() -> None:
    global _force_memory
    _force_memory = True
    _memory_otp.clear()
    _memory_cd.clear()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_placeholder_email(email: str) -> bool:
    return normalize_email(email).endswith(PLACEHOLDER_EMAIL_SUFFIX)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(purpose: str, email: str, code: str) -> str:
    payload = f"{purpose}:{normalize_email(email)}:{code.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def email_delivery_ready() -> bool:
    return bool((settings.smtp_host or "").strip() or (settings.email_api_url or "").strip())


def _otp_key(purpose: str, email: str) -> str:
    return f"otp:{purpose}:{normalize_email(email)}"


def _cd_key(email: str) -> str:
    return f"otp:cd:{normalize_email(email)}"


def _raise_unavailable(reason: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="otp_unavailable",
    )


def store_otp(purpose: str, email: str, code: str) -> None:
    if purpose not in OTP_PURPOSES:
        raise HTTPException(status_code=400, detail="otp_invalid")
    if not OTP_RE.match((code or "").strip()):
        raise HTTPException(status_code=400, detail="otp_invalid")
    key = _otp_key(purpose, email)
    digest = hash_otp(purpose, email, code)
    redis = None if _force_memory else _get_redis()
    if redis is not None:
        redis.setex(key, OTP_TTL_SECONDS, digest)
        return
    if settings.rate_limit_fail_closed and not _force_memory:
        _raise_unavailable("redis")
    _memory_otp[key] = (digest, time.monotonic() + OTP_TTL_SECONDS)


def consume_otp(purpose: str, email: str, code: str) -> None:
    if purpose not in OTP_PURPOSES or not OTP_RE.match((code or "").strip()):
        raise HTTPException(status_code=400, detail="otp_invalid")
    key = _otp_key(purpose, email)
    expected = hash_otp(purpose, email, code)
    redis = None if _force_memory else _get_redis()
    stored = None
    if redis is not None:
        stored = redis.get(key)
        if stored == expected:
            redis.delete(key)
            return
        raise HTTPException(status_code=400, detail="otp_invalid")
    if settings.rate_limit_fail_closed and not _force_memory:
        _raise_unavailable("redis")
    row = _memory_otp.get(key)
    if row and row[1] >= time.monotonic() and row[0] == expected:
        _memory_otp.pop(key, None)
        return
    _memory_otp.pop(key, None)
    raise HTTPException(status_code=400, detail="otp_invalid")


def assert_send_cooldown(email: str) -> None:
    key = _cd_key(email)
    redis = None if _force_memory else _get_redis()
    if redis is not None:
        if redis.exists(key):
            raise HTTPException(status_code=429, detail="otp_cooldown")
        return
    if settings.rate_limit_fail_closed and not _force_memory:
        _raise_unavailable("redis")
    expires = _memory_cd.get(key, 0)
    if expires > time.monotonic():
        raise HTTPException(status_code=429, detail="otp_cooldown")


def mark_send_cooldown(email: str) -> None:
    key = _cd_key(email)
    redis = None if _force_memory else _get_redis()
    if redis is not None:
        redis.setex(key, OTP_COOLDOWN_SECONDS, "1")
        return
    _memory_cd[key] = time.monotonic() + OTP_COOLDOWN_SECONDS


def drop_otp(purpose: str, email: str) -> None:
    key = _otp_key(purpose, email)
    redis = None if _force_memory else _get_redis()
    if redis is not None:
        redis.delete(key)
        return
    _memory_otp.pop(key, None)


_OTP_SUBJECT = {
    "register": "注册验证码",
    "login": "登录验证码",
    "reset": "重置密码验证码",
    "rebind": "验证当前邮箱",
    "bind": "绑定新邮箱",
}


def otp_email_copy(code: str, purpose: str = "login") -> tuple[str, str, str]:
    name = settings.app_name or "比特音"
    label = _OTP_SUBJECT.get(purpose, "验证码")
    subject = f"{name} {label} {code}"
    text = f"你的验证码是 {code}，10 分钟内有效。也请检查垃圾箱。如果不是你本人操作，请忽略这封邮件。"
    html = (
        f"<p>你的验证码是 <strong>{code}</strong>。</p>"
        f"<p>10 分钟内有效。也请检查垃圾箱。如果不是你本人操作，请忽略这封邮件。</p>"
    )
    return subject, html, text
