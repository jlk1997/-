"""Ops console roles. Platform admins keep full access."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from app.api.deps import get_current_user
from app.models.schemas import User

OPS_ROLES = ("distribution", "finance", "moderation", "admin")

ROLE_MODULES = {
    "distribution": ("inbox", "orders", "label_accounts", "automation"),
    "finance": ("inbox", "settlements", "withdrawals", "reconciliation"),
    "moderation": ("inbox", "users", "reports"),
    "admin": ("inbox", "orders", "users", "label_accounts", "settlements", "withdrawals", "reconciliation", "automation", "audit"),
}


def user_ops_role(user: User | None) -> str | None:
    if user is None:
        return None
    if getattr(user, "is_admin", False):
        return "admin"
    role = str(getattr(user, "ops_role", "") or "").strip()
    return role if role in OPS_ROLES else None


def user_can(user: User | None, *roles: str) -> bool:
    role = user_ops_role(user)
    if role == "admin":
        return True
    return role in roles


def require_ops_role(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user_can(user, *roles):
            return user
        raise HTTPException(403, "ops role required")

    return _dep
