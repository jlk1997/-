from app.services.credit_estimates import (
    WORKBENCH_AI_COST,
    WORKBENCH_RENDER_COST,
    estimate_credits,
    variation_credit_cost,
)
from app.services.credits import GENERATION_COST, PLAYLIST_COST


def test_two_takes_is_one_bundled_credit():
    assert variation_credit_cost(2) == GENERATION_COST
    bundled = estimate_credits(mode="twoTakes", variations=2)
    assert bundled["credits"] == GENERATION_COST
    assert bundled["mode"] == "twoTakes"


def test_variation_lab_still_bills_per_take():
    assert variation_credit_cost(3) == 3 * GENERATION_COST
    assert variation_credit_cost(5) == 5 * GENERATION_COST
    est = estimate_credits(mode="variation", variations=3)
    assert est["credits"] == 3 * GENERATION_COST


def test_variation_count_two_uses_bundle():
    est = estimate_credits(mode="variation", variations=2)
    assert est["credits"] == GENERATION_COST
    assert est["breakdown"][0]["label"] == "twoTakes"


def test_playlist_estimate_unchanged():
    est = estimate_credits(mode="playlist")
    assert est["credits"] == PLAYLIST_COST


def test_public_platform_config_hides_vendor_block(monkeypatch):
    from app.api.routes import config as config_routes

    monkeypatch.setattr(config_routes, "cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(config_routes, "cache_set", lambda *_a, **_k: None)
    response = config_routes.platform_info(user=None)
    data = response.body
    import json

    payload = json.loads(data)
    assert "minimax" not in payload
    assert "lyrics_optimizer_default" in payload["studio"]
    assert "cover_mode_default" in payload["studio"]


def test_workbench_estimates_stay_on_credits_ledger():
    bounce = estimate_credits(mode="workbench")
    assert bounce["credits"] == WORKBENCH_RENDER_COST
    assert bounce["fiat"] is False
    assert bounce["ledger"] == "credits"
    ai = estimate_credits(mode="workbench_ai")
    assert ai["credits"] == WORKBENCH_AI_COST
    assert ai["fiat"] is False
    regen = estimate_credits(mode="workbench_regen")
    assert regen["credits"] == GENERATION_COST
    assert regen["fiat"] is False
    pack = estimate_credits(mode="effect_pack")
    assert pack["credits"] == 0
    assert pack["fiat"] is False
