from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_playbook_health_exposes_heal_candidates():
    from app.services.harvest.playbooks import heal_candidates

    heal = heal_candidates("netease")
    assert heal["statsUrls"]
    assert "alternateSelectors" in heal
    from types import SimpleNamespace

    from app.services.seats.farm import classify_empty_harvest

    broke = classify_empty_harvest(
        has_session=True,
        seat_status="live",
        seat=SimpleNamespace(id="s1", channel_code="netease"),
    )
    assert broke["selector_broke"] is True
    assert broke["heal_candidates"]["statsUrls"]


def test_farm_url_allowlist_and_platform_scopes():
    from app.services.seats.consent import PLATFORM_SCOPES
    from app.services.seats.farm import farm_url_allowed

    assert PLATFORM_SCOPES["upload"] is False
    assert PLATFORM_SCOPES["settle"] is False
    assert PLATFORM_SCOPES["metrics"] is True
    assert farm_url_allowed("https://music.163.com/st/musician", "netease") is True
    assert farm_url_allowed("https://evil.example/steal", "netease") is False


def test_route_delivery_repicks_configured_aggregator(monkeypatch):
    from types import SimpleNamespace

    from app.services.distribution.assist import route_delivery

    monkeypatch.setattr(
        "app.services.distribution.catalog.pick_configured_aggregator",
        lambda code: None,
    )

    class _Adapter:
        def configured(self):
            return False

    monkeypatch.setattr("app.services.distribution.adapters.get_adapter", lambda code: _Adapter())
    delivery = SimpleNamespace(channel_code="spotify", distributor_code="distrokid")
    assert route_delivery(delivery) == "metrics"


def test_emotion_analyze_is_degraded_without_models(monkeypatch):
    from app.core.emotion_engine import EmotionEngine

    monkeypatch.setattr("app.health._check_essentia_models", lambda: {"status": "degraded"})
    engine = EmotionEngine()
    result = engine.analyze("missing.wav")
    assert result["degraded"] is True
    assert result["moods"] == []
    assert result.get("reason") == "essentia_not_ready"


def test_l3_l5_source_contracts():
    client = ROOT / "apps" / "client" / "src"
    feed = (client / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    assert "ChallengesRow" in feed and "DuelsRow" in feed
    lib = (client / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    assert "LAUNCH_HANDOFF_CHANNELS" in lib
    assert "wechat_channels" in lib
    auth = (client / "packageCreator" / "AuthDesk.tsx").read_text(encoding="utf-8")
    assert "first_page" in auth
    assert "authDeskFirstPage" not in auth
    assert "permissions.join" not in auth
    assert "creator-lamp" in auth
    assert "SeatScopeToggles" in auth
    reveal = (client / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    assert reveal.index("{r.libraryNext}") > reveal.index("{r.more}")
    assert "publishToDiscover" in reveal
    picker = (client / "components" / "studio" / "VariationPicker.tsx").read_text(encoding="utf-8")
    assert "abHint" in picker
    assert "上店发行" in (client / "packageCreator" / "pages" / "release" / "index.config.ts").read_text(encoding="utf-8")
    assert "{!loading && <OfficialListenShelf />}" in feed
    runner = (ROOT / "packages" / "dsp-playbooks" / "runner.js").read_text(encoding="utf-8")
    assert "healCandidates" in runner
    assert "trySelectors" in runner
    celery = (ROOT / "backend" / "app" / "celery_app.py").read_text(encoding="utf-8")
    assert "rematch_unattached_daily_task" in celery
    assert "lapsed_user_recall_task" in celery
    assert "ops_daily_digest_task" in celery
    ops = (ROOT / "backend" / "app" / "services" / "ops_dashboard.py").read_text(encoding="utf-8")
    assert "harvest_unmatched" in ops
    assert "session_expired" in ops
    assert "harvest_failed" in ops
    assert "count_stale_session_jobs" in ops
    assert "ops_daily_digest" in ops
    assert "alert(" in ops
    growth = (ROOT / "backend" / "app" / "services" / "growth.py").read_text(encoding="utf-8")
    assert "Work.owner_id" in growth
    assert "AnalyticsEvent" not in growth
    assert "notify_key_event_sync" in (
        ROOT / "backend" / "app" / "services" / "royalty" / "settlement.py"
    ).read_text(encoding="utf-8")
    assert "notify_key_event_sync" in (
        ROOT / "backend" / "app" / "services" / "royalty" / "payout_calendar.py"
    ).read_text(encoding="utf-8")
    startup = (ROOT / "backend" / "app" / "startup_checks.py").read_text(encoding="utf-8")
    assert "SEAT_VAULT_KEY is empty" in startup
    health = (ROOT / "backend" / "app" / "health.py").read_text(encoding="utf-8")
    assert "seat_vault" in health
    wallet = (ROOT / "backend" / "app" / "services" / "royalty" / "wallet.py").read_text(encoding="utf-8")
    assert "notify_key_event_sync" in wallet
    assert "提现已申请" in wallet
    farm = (ROOT / "backend" / "app" / "services" / "seats" / "farm.py").read_text(encoding="utf-8")
    assert "check_seat_health_proactive" in farm
    assert "farm_url_allowed" in farm
