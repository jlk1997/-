from app.api.routes.config import _partners_configured, catalog_audio, catalog_tracks, platform_info


def test_catalog_audio_serves_wav():
    res = catalog_audio("night-lofi")
    assert res.media_type == "audio/wav"
    assert res.body[:4] == b"RIFF"


def test_catalog_tracks_lists_official_loops():
    payload = catalog_tracks(None)
    assert payload["discovery_only"] is True
    assert len(payload["tracks"]) >= 6
    assert payload["tracks"][0]["audio_url"].startswith("/catalog/audio/")


def test_platform_info_exposes_honesty_fields(monkeypatch):
    from app.api.routes import config as config_mod
    from app.services.cache import cache_set

    cache_set("platform:info:v5", None, 0)
    monkeypatch.setattr(config_mod, "cache_get", lambda key: None)
    monkeypatch.setattr(config_mod, "cache_set", lambda *args, **kwargs: None)
    monkeypatch.setattr(config_mod, "_partners_configured", lambda: False)
    monkeypatch.setattr("app.health._check_essentia_models", lambda: {"status": "degraded"})
    monkeypatch.setattr("app.services.seats.service.farm_can_navigate", lambda: False)
    data = platform_info(None)
    body = data.body
    import json

    payload = json.loads(body)
    assert payload["payout_mode"] == "manual_only"
    assert payload["farm_navigate"] is False
    assert payload["partners_configured"] is False
    assert "essentia_ready" in payload
    assert "kyc_provider_configured" in payload
    assert _partners_configured() in {True, False}
