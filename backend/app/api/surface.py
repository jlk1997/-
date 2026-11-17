"""Honest client surface. WeChat may listen / make / check in / see money; desk writes stay H5."""

from __future__ import annotations

from fastapi import Header, HTTPException

WEAPP_SURFACES = frozenset({"weapp", "mini", "miniprogram"})


def is_weapp_surface(value: str | None) -> bool:
    return (value or "").strip().lower() in WEAPP_SURFACES


def require_h5_desk(x_vibe_surface: str | None = Header(default=None, alias="X-Vibe-Surface")) -> None:
    if is_weapp_surface(x_vibe_surface):
        raise HTTPException(403, "WEAPP_H5_DESK")
