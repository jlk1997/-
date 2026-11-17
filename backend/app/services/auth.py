import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import User


def assert_account_login_allowed(user: User | None) -> User:
    if not user or not user.is_active or getattr(user, "deleted_at", None):
        raise HTTPException(status_code=403, detail="Account banned")
    return user


def _normalize_password(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_normalize_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize_password(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError:
        return None


def find_user_by_email(db: Session, email: str) -> Optional[User]:
    normalized = (email or "").strip().lower()
    user = db.query(User).filter(User.email == normalized).first()
    if user:
        return user
    raw = (email or "").strip()
    if raw and raw != normalized:
        return db.query(User).filter(User.email == raw).first()
    return None


def allocate_username(db: Session, email: str, requested: str | None = None) -> str:
    candidate = (requested or "").strip()
    if 3 <= len(candidate) <= 100 and not db.query(User).filter(User.username == candidate).first():
        return candidate
    local = re.sub(r"[^a-z0-9_]+", "", (email or "").split("@", 1)[0].lower())
    if len(local) < 3:
        local = f"user{local}" or "user"
    local = local[:80]
    if not db.query(User).filter(User.username == local).first():
        return local
    for _ in range(16):
        name = f"{local}_{secrets.token_hex(2)}"
        if not db.query(User).filter(User.username == name).first():
            return name
    raise HTTPException(status_code=400, detail="Username already taken")


def mark_email_verified(user: User) -> None:
    if getattr(user, "email_verified_at", None) is None:
        user.email_verified_at = datetime.utcnow()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = find_user_by_email(db, email)
    if user and user.is_active and verify_password(password, user.hashed_password):
        return user
    return None
