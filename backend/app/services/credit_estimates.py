"""Credit cost estimation for pre-flight UI."""

from __future__ import annotations

from app.services.credits import (
    COVER_COST,
    GENERATION_COST,
    LYRICS_COST,
    PLAYLIST_COST,
    REMIX_COST,
)

WORKBENCH_RENDER_COST = 0
WORKBENCH_AI_COST = 1

_MODE_COSTS: dict[str, int] = {
    "single": GENERATION_COST,
    "quickTrack": GENERATION_COST,
    "twoTakes": GENERATION_COST,
    "playlist": PLAYLIST_COST,
    "remix": REMIX_COST,
    "cover": COVER_COST,
    "lyrics": LYRICS_COST,
    "variation": GENERATION_COST,
    "workbench": WORKBENCH_RENDER_COST,
    "workbench_ai": WORKBENCH_AI_COST,
    "workbench_regen": GENERATION_COST,
    "effect_pack": 0,
}


def model_generation_cost(model: str | None = None) -> int:
    """Both engines stay at one credit until a few weeks of token measurements exist."""
    del model
    return GENERATION_COST


def variation_credit_cost(count: int) -> int:
    """Default two-take is one bundled generation credit; 3–5 variants bill per take."""
    n = max(2, min(5, int(count or 2)))
    if n == 2:
        return GENERATION_COST
    return n * GENERATION_COST


def estimate_credits(
    *,
    mode: str = "single",
    count: int = 1,
    variations: int | None = None,
) -> dict:
    if mode in ("twoTakes", "two_takes"):
        return {
            "credits": GENERATION_COST,
            "mode": "twoTakes",
            "breakdown": [{"label": "twoTakes", "unit_cost": GENERATION_COST, "quantity": 1, "subtotal": GENERATION_COST}],
        }
    base = _MODE_COSTS.get(mode, GENERATION_COST)
    if mode == "variation" and variations is not None:
        n = max(2, min(5, variations))
        total = variation_credit_cost(n)
        return {
            "credits": total,
            "mode": mode,
            "breakdown": [
                {
                    "label": "twoTakes" if n == 2 else "variation",
                    "unit_cost": GENERATION_COST,
                    "quantity": 1 if n == 2 else n,
                    "subtotal": total,
                }
            ],
        }
    if mode in ("workbench", "workbench_ai", "workbench_regen", "effect_pack"):
        total = _MODE_COSTS[mode]
        return {
            "credits": total,
            "mode": mode,
            "ledger": "credits",
            "fiat": False,
            "breakdown": [{"label": mode, "unit_cost": total, "quantity": 1, "subtotal": total}],
        }
    if mode == "playlist":
        total = PLAYLIST_COST
        return {
            "credits": total,
            "mode": mode,
            "breakdown": [{"label": "playlist", "unit_cost": PLAYLIST_COST, "quantity": 1, "subtotal": total}],
        }
    qty = max(1, count)
    total = base * qty
    return {
        "credits": total,
        "mode": mode,
        "breakdown": [{"label": mode, "unit_cost": base, "quantity": qty, "subtotal": total}],
    }
