"""Seat session vault. Ciphertext only — never log plaintext."""

from __future__ import annotations

import base64
import hashlib
import json

from app.config import settings

FERNET_PREFIX = "v2:"


def _xor_key() -> bytes:
    return hashlib.sha256((settings.jwt_secret or "dev-seat-vault").encode()).digest()


def _fernet_from_material(raw: str):
    from cryptography.fernet import Fernet

    material = (raw or "").strip()
    if material:
        key = material.encode("ascii") if len(material) == 44 else base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    else:
        key = base64.urlsafe_b64encode(_xor_key())
    return Fernet(key)


def _fernet():
    """Current key. New ciphertext always uses this."""
    return _fernet_from_material(getattr(settings, "seat_vault_key", "") or "")


def _decrypt_fernets():
    """Current key first, then the JWT-derived key so a rotation can still open old blobs."""
    current = (getattr(settings, "seat_vault_key", "") or "").strip()
    fernets = [_fernet_from_material(current)]
    if current:
        fernets.append(_fernet_from_material(""))
    return fernets


def encrypt_blob(payload: dict | str) -> str:
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    token = _fernet().encrypt(raw.encode("utf-8")).decode("ascii")
    return f"{FERNET_PREFIX}{token}"


def _decrypt_xor(ciphertext: str) -> dict:
    key = _xor_key()
    mixed = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    raw = bytes(b ^ key[i % len(key)] for i, b in enumerate(mixed))
    text = raw.decode("utf-8")
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"value": text}
    except json.JSONDecodeError:
        return {"value": text}


def decrypt_blob(ciphertext: str) -> dict:
    if not ciphertext:
        return {}
    if ciphertext.startswith(FERNET_PREFIX):
        from cryptography.fernet import InvalidToken

        text = ""
        for fernet in _decrypt_fernets():
            try:
                text = fernet.decrypt(ciphertext[len(FERNET_PREFIX) :].encode("ascii")).decode("utf-8")
                break
            except (InvalidToken, ValueError):
                continue
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"value": text}
        except json.JSONDecodeError:
            return {"value": text}
    try:
        return _decrypt_xor(ciphertext)
    except Exception:
        return {}
