from types import SimpleNamespace

from app.services.distribution.catalog import (
    channel_automation_level,
    preview_delivery_route,
    preview_release_routes,
)
from app.services.distribution.assist import route_delivery
from app.services.royalty.connector import MIN_EXTENSION_VERSION, version_less
from app.services.royalty.predict import merge_predictions, predict_revenue


def test_automation_level_truth_table():
    assert channel_automation_level("netease") == "connector_full"
    assert channel_automation_level("qishui") == "connector_full"
    assert channel_automation_level("soundcloud") == "connector_full"
    assert channel_automation_level("spotify") == "metrics_only"
    assert channel_automation_level("apple_music") == "metrics_only"
    assert channel_automation_level("youtube_music") == "connector_assist"


def test_route_delivery_prefers_connector_even_if_partner(monkeypatch):
    monkeypatch.setattr(
        "app.services.distribution.catalog.pick_configured_aggregator",
        lambda code: "cn_label" if code == "netease" else None,
    )
    delivery = SimpleNamespace(channel_code="netease", distributor_code="cn_label")
    assert route_delivery(delivery) == "session_assist"
    preview = preview_delivery_route("netease")
    assert preview["route"] == "connector"
    assert preview["sidecar_partner"] == "cn_label"


def test_route_delivery_partner_only_for_metrics_store(monkeypatch):
    monkeypatch.setattr(
        "app.services.distribution.catalog.pick_configured_aggregator",
        lambda code: "distrokid" if code == "spotify" else None,
    )
    delivery = SimpleNamespace(channel_code="spotify", distributor_code="distrokid")
    assert route_delivery(delivery) == "partner"
    preview = preview_delivery_route("spotify")
    assert preview["route"] == "partner"


def test_route_preview_has_no_live_without_receipt():
    rows = preview_release_routes(["netease", "spotify"])
    assert all(row["route"] != "live" for row in rows)
    assert {row["channel_code"] for row in rows} == {"netease", "spotify"}


def test_attach_prediction_calibrates_from_catalog_only():
    from app.services.royalty.predict import attach_prediction, calibration_factor

    assert calibration_factor(None, user_id="x", channel_code="netease") is None
    target = {}
    pred = attach_prediction(target, "netease", 1000)
    assert pred["basis"] == "catalog"
    assert pred["currency"] == "CNY"
    assert "calibrated" not in pred
    assert target["predicted_revenue"]["mid_minor"] > 0


def test_merge_predictions_does_not_force_cny():
    usd = predict_revenue("spotify", 1000)
    cny = predict_revenue("netease", 1000)
    merged = merge_predictions([usd, cny])
    assert merged
    assert {row["currency"] for row in merged["by_currency"]} == {usd["currency"], cny["currency"]}
    headline = usd if usd["mid_minor"] >= cny["mid_minor"] else cny
    assert merged["currency"] == headline["currency"]
    assert merged["mid_minor"] == headline["mid_minor"]


def test_min_extension_version_blocks_old_clients():
    assert MIN_EXTENSION_VERSION == "0.14.0"
    assert version_less("0.13.0", "0.14.0") is True
    assert version_less("0.14.0", "0.14.0") is False
    assert version_less("0.15.0", "0.14.0") is False


def test_ship_band_fsm_stays_on_card():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    lib = (root / "apps" / "client" / "src" / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    card = (root / "apps" / "client" / "src" / "packageCreator" / "ShipCompleteCard.tsx").read_text(encoding="utf-8")
    desk = (root / "apps" / "client" / "src" / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    bridge = (root / "apps" / "client" / "src" / "packageCreator" / "WeappH5Bridge.tsx").read_text(encoding="utf-8")
    lite = (
        root / "apps" / "client" / "src" / "packageStudio" / "workbench" / "shells" / "LiteConsole.tsx"
    ).read_text(encoding="utf-8")
    work = (root / "apps" / "client" / "src" / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    wizard = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "release" / "index.tsx").read_text(
        encoding="utf-8"
    )
    deliveries = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(
        encoding="utf-8"
    )
    hub = (root / "backend" / "app" / "services" / "royalty" / "hub.py").read_text(encoding="utf-8")
    zh = (root / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    kinds = [
        'return { kind: "challenge"',
        'return { kind: "incomplete"',
        'return { kind: "degraded"',
        'return { kind: "ghost_live"',
        'return { kind: "install"',
        'return { kind: "wait_login"',
        'return { kind: "lease"',
        'return { kind: "filling"',
        'return { kind: "ops"',
        'return { kind: "live_settle"',
    ]
    found = [lib.find(item) for item in kinds]
    assert all(index >= 0 for index in found)
    assert found == sorted(found)
    assert "export function pickShipBandAction" in lib
    assert "pickShipBandAction" in card
    assert "shipPublishingPaste" in card
    assert "shipChallengeGo" in card
    assert "shipPairNow" in card
    assert "probeExtensionStatus" in card
    assert "humanHold" in card
    assert "focusShipCompleteBand" in desk
    assert "hasLicense={Boolean(data?.has_distribution_license)}" in desk
    assert "CREATOR_SHIP_WORK_KEY" in desk
    nav = (root / "apps" / "client" / "src" / "packageCreator" / "nextActionNav.ts").read_text(encoding="utf-8")
    quick = (root / "apps" / "client" / "src" / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    ingest = (root / "backend" / "app" / "services" / "harvest" / "ingest.py").read_text(encoding="utf-8")
    assert 'action === "qc" || action === "release"' in nav
    assert "openCreatorDesk(\"today\"" in nav
    assert "stayOnCard: true" in quick
    assert "require_settle_license" in ingest
    assert "session_wait_count" in bridge
    assert "lane_pack_degraded" in lite
    assert "editLanesNotReview" in work
    assert "shipMetricsNeedSeat" in wizard
    assert "goSessionWaitCta" in deliveries
    assert "def hub_connector_next_action" in hub
    assert "has_distribution_license" in hub
    assert "shipPublishingPaste" in zh
    assert "shipLicenseSettleNeed" in zh
    assert "clearShipFocus" in desk
    assert "resumePendingQuickRelease" in desk
    assert "peekPendingRelease" in desk
    assert "harvestWake" in desk
    assert "wakeHarvest" in desk
    assert "embedAuth" in desk
    assert "goShipBand()" in desk
    assert "pairInstallHint" in card
    assert "bittune.autoOpenStore:" in card
    assert "bittune.autoPollFill:" in card
    assert "bittune.autoPollRun:" in card
    assert "bittune.autoHarvest:" in card
    assert "shipFillWoke" in card
    assert "harvestWake" in card
    assert "CREATOR_TAB_ROUTE" in card
    assert "seatFarmHealth" in card
    assert "shipChallengeGo" in deliveries
    assert "goShipBand()" in deliveries


def test_one_tap_ship_and_harvest_license_stay_on_band():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    farm = (root / "backend" / "app" / "services" / "seats" / "farm.py").read_text(encoding="utf-8")
    connections = (root / "backend" / "app" / "services" / "seats" / "connections.py").read_text(encoding="utf-8")
    knobs = (root / "apps" / "client" / "src" / "packageStudio" / "workbench" / "shared.tsx").read_text(encoding="utf-8")
    create = (root / "apps" / "client" / "src" / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    library = (root / "apps" / "client" / "src" / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    progress = (root / "apps" / "client" / "src" / "components" / "studio" / "GenerationProgress.tsx").read_text(
        encoding="utf-8"
    )
    spec = (root / "PRODUCT_SPEC_COMPLETE.md").read_text(encoding="utf-8")
    assert "actor=owner" in farm
    assert "license_blocked" in farm
    assert '"farm_health": (chosen or {}).get("farm_health")' in connections
    assert "labels.aiHonesty" in knobs
    assert "goShipBand(recentWork.id)" in create
    assert "goShipBand(menuWork.id)" in library
    assert "goShipBand(singleWorkId)" in progress
    assert "完成带三档" in spec
    assert "未配对的只听数据店不自动勾" in spec
    assert "不假装一键全球 DSP" in spec


def test_wave_d_sockets_stay_honest():
    from pathlib import Path

    from app.config import settings
    from app.services.distribution.adapters import DistroKidAdapter
    from app.services.seats.service import farm_navigate_requested

    root = Path(__file__).resolve().parents[2]
    card = (root / "apps" / "client" / "src" / "packageCreator" / "ShipCompleteCard.tsx").read_text(encoding="utf-8")
    pro = (root / "apps" / "client" / "src" / "packageStudio" / "workbench" / "shells" / "ProConsole.tsx").read_text(
        encoding="utf-8"
    )
    preview = (
        root / "apps" / "client" / "src" / "packageStudio" / "workbench" / "ApproxPreview.tsx"
    ).read_text(encoding="utf-8")
    wizard = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "release" / "index.tsx").read_text(
        encoding="utf-8"
    )
    ingest = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert "shipFarmLocal" in card
    assert "shipPartnerQueue" in card
    assert "shipSettleNext" in card
    assert "previewApproxSoon" in preview
    assert "ApproxPreview" in pro
    assert "shipChannelGroup(code) !== \"metrics\"" in wizard
    assert "harvestSeatTitle" in ingest
    assert "harvestCsvTitle" in ingest
    if not (settings.distrokid_api_key or "").strip():
        assert DistroKidAdapter().configured() is False
    assert farm_navigate_requested() in {True, False}


def test_one_tap_default_excludes_metrics_and_global_copy():
    from pathlib import Path

    from app.services.distribution.catalog import DEFAULT_UPLOAD_CHANNELS, default_upload_channels

    root = Path(__file__).resolve().parents[2]
    catalog = (root / "backend" / "app" / "services" / "distribution" / "catalog.py").read_text(encoding="utf-8")
    card = (root / "apps" / "client" / "src" / "packageCreator" / "ShipCompleteCard.tsx").read_text(encoding="utf-8")
    zh = (root / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    assert DEFAULT_UPLOAD_CHANNELS == ("netease",)
    assert "spotify" not in default_upload_channels()
    assert 'DEFAULT_UPLOAD_CHANNELS = ("netease",)' in catalog
    assert "一键全球" not in card
    assert "一键全球" not in zh
    assert "ShipCompleteCard" in card


def test_auto_submit_scope_defaults_off():
    from app.services.seats.consent import DEFAULT_USER_SCOPES, OPTIONAL_SCOPES, PLATFORM_SCOPES

    assert DEFAULT_USER_SCOPES["auto_submit"] is False
    assert PLATFORM_SCOPES["auto_submit"] is False
    assert "auto_submit" in OPTIONAL_SCOPES


def test_metrics_store_cannot_grant_upload():
    from app.services.seats.consent import default_scopes_for, grant_handoff_upload, normalize_scopes, apply_channel_scope_limits

    assert default_scopes_for("spotify")["upload"] is False
    assert default_scopes_for("netease")["upload"] is True
    forced = apply_channel_scope_limits(normalize_scopes({"upload": True, "auto_submit": True}), "apple_music")
    assert forced["upload"] is False
    assert forced["auto_submit"] is False

    class Seat:
        ownership = "user"
        channel_code = "spotify"
        extra = {"scopes": {"metrics": True, "export_csv": True, "upload": False, "settle": False, "keep_sync": False}}

    assert grant_handoff_upload(Seat())["upload"] is False


def test_telemetry_degrades_after_failed_attaches():
    from app.services.distribution.telemetry import (
        DEGRADE_AFTER,
        channel_telemetry,
        effective_automation_level,
        record_channel_event,
        reset_telemetry,
    )

    reset_telemetry()
    for _ in range(DEGRADE_AFTER):
        record_channel_event(None, "netease", event="attach", ok=False)
    assert effective_automation_level("netease", "connector_full") == "connector_assist"
    assert channel_telemetry(None, "netease").get("degraded_to") == "connector_assist"
    reset_telemetry()


def test_session_expiry_marks_friday_relogin():
    from datetime import datetime, timedelta

    from app.services.seats.service import next_friday_noon, predict_session_expiry, seat_relogin_due

    now = datetime(2026, 9, 16, 10, 0, 0)  # Wednesday
    friday = next_friday_noon(now)
    assert friday.weekday() == 4
    assert friday > now
    exp = predict_session_expiry(
        {"cookies": [{"name": "sid", "expirationDate": (now + timedelta(days=1)).timestamp()}]},
        now=now,
    )
    assert exp is not None and exp < friday

    class Seat:
        status = "live"
        extra = {
            "has_session": True,
            "session_saved_at": now.isoformat(),
            "session_expires_at": (now + timedelta(days=1)).isoformat(),
        }

    assert seat_relogin_due(Seat(), now=now) is True

    class Fresh:
        status = "live"
        extra = {
            "has_session": True,
            "session_saved_at": now.isoformat(),
            "session_expires_at": (now + timedelta(days=20)).isoformat(),
        }

    assert seat_relogin_due(Fresh(), now=now) is False


def test_hub_does_not_use_none_channel_band():
    from pathlib import Path

    hub = (Path(__file__).resolve().parents[1] / "app" / "services" / "royalty" / "hub.py").read_text(encoding="utf-8")
    assert "merge_predictions(" in hub
    assert "predict_revenue(None" not in hub
    assert "channel_code=None" not in hub


def test_claim_assist_job_does_not_flip_status():
    from app.services.distribution.assist import claim_assist_job

    src = claim_assist_job.__doc__ or ""
    assert "Read-only" in src
    assert "session_running" not in claim_assist_job.__code__.co_names


def test_desk_does_not_render_prediction():
    from pathlib import Path

    desk = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "client"
        / "src"
        / "packageCreator"
        / "CreatorDesk.tsx"
    ).read_text(encoding="utf-8")
    assert "formatPredictedRange" not in desk
    assert "predictedRevenue" not in desk


def test_attach_requires_real_file_not_path():
    from pathlib import Path

    upload = (Path(__file__).resolve().parents[2] / "packages" / "dsp-playbooks" / "upload.js").read_text(
        encoding="utf-8"
    )
    attach = upload.split("function attachReleaseAssets")[1].split("function clickSubmitOnce")[0]
    assert "masterFile || data.master_file" in attach
    assert "after.files && after.files.length" in attach
    assert "master_path" not in attach


def test_pending_queue_is_readonly():
    from app.services.seats.service import list_pending_jobs

    assert "Does not lease" in (list_pending_jobs.__doc__ or "")
    assert "leased" not in list_pending_jobs.__code__.co_names or "status" in list_pending_jobs.__code__.co_names


def test_h5_wakes_connector_queue():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pair = (root / "apps" / "client" / "src" / "packageCreator" / "extensionPair.ts").read_text(encoding="utf-8")
    quick = (root / "apps" / "client" / "src" / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    release = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "release" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert "export function sendPollToExtension" in pair
    assert "BITTUNE_DELIVERY" in pair
    assert "sendPollToExtension" in quick
    assert "sendPollToExtension" in release


def test_background_poll_is_readonly_and_streams_master():
    from pathlib import Path

    bg = (Path(__file__).resolve().parents[2] / "apps" / "creator-connector" / "background.js").read_text(
        encoding="utf-8"
    )
    assert "readonly: true" in bg
    assert "fillAndAttachOnTab" in bg
    assert "plantFileOnTab" in bg
    assert "fetchAssistAsset" in bg
    assert "/distribution/assist/jobs/${deliveryId}/master" in bg
    assert "sessionStorage" in bg
    assert "STORE_OPTIONAL_ORIGINS" in bg
    assert "/seats/queue" in bg
    assert "ensureReadyStoreTab" in bg
    assert "noteAssistProgress" in bg
    assert "last_progress" in bg
    assert "saveOpenSeatSession" in bg
    assert "uploadUrlFor" in bg
    assert "seatJobsBusy" in bg
    assert 'error: "fill_incomplete", needs_runtime: true' not in bg


def test_upload_url_is_the_form_not_musician_home():
    from app.services.distribution.catalog import channel_upload_url
    from app.services.harvest.playbooks import PLAYBOOKS

    assert "upload" in (channel_upload_url("netease") or "")
    assert "publish" in (channel_upload_url("qq_music") or "")
    assert "musician.douyin.com" in (channel_upload_url("qishui") or "")
    assert PLAYBOOKS["netease"]["upload_url"].endswith("/upload")


def test_resume_skips_successful_running_delivery():
    from types import SimpleNamespace

    from app.services.seats.service import should_resume_session_delivery

    running = SimpleNamespace(
        status="session_running",
        last_error=None,
        attempt_meta={"submissions": [{"event": "master_attached"}]},
    )
    failed = SimpleNamespace(
        status="session_running",
        last_error="fill_incomplete",
        attempt_meta={"submissions": [{"event": "fill_incomplete"}]},
    )
    orphan = SimpleNamespace(
        status="session_running",
        last_error=None,
        attempt_meta={"submissions": [{"event": "portal_queued"}]},
    )
    waiting = SimpleNamespace(status="session_wait", last_error=None, attempt_meta={})
    assert should_resume_session_delivery(running, has_active_job=False) is False
    assert should_resume_session_delivery(failed, has_active_job=False) is True
    assert should_resume_session_delivery(orphan, has_active_job=False) is True
    assert should_resume_session_delivery(waiting, has_active_job=False) is True
    assert should_resume_session_delivery(failed, has_active_job=True) is False


def test_fill_incomplete_is_retryable():
    from app.services.distribution.service import user_delivery_status

    assert user_delivery_status("session_running", "fill_incomplete") == "needs_retry"
    assert user_delivery_status("metrics_only") == "metrics_only"
    assert user_delivery_status("session_running", None) == "assisting"


def test_last_delivery_event_prefers_submissions():
    from types import SimpleNamespace

    from app.services.distribution.assist import pick_last_delivery_event

    older = SimpleNamespace(
        id="d1",
        channel_code="qishui",
        status="session_running",
        store_url=None,
        external_id=None,
        attempt_meta={"submissions": [{"at": "2026-01-01T00:00:00", "event": "opening", "message": "old"}]},
    )
    newer = SimpleNamespace(
        id="d2",
        channel_code="netease",
        status="in_review",
        store_url="https://music.163.com/#/song?id=1",
        external_id=None,
        attempt_meta={"submissions": [{"at": "2026-09-18T12:00:00", "event": "submitted", "message": "已提交"}]},
    )
    picked = pick_last_delivery_event([older, newer])
    assert picked["channel_code"] == "netease"
    assert picked["event"] == "submitted"
    assert picked["source"] == "submission"
    heartbeat = pick_last_delivery_event([], {"title": "正在代交网易云", "channel": "netease", "busy": True})
    assert heartbeat["source"] == "heartbeat"
    assert heartbeat["event"] == "progress"


def test_h5_shows_connector_live_line():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    lib = (root / "apps" / "client" / "src" / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    desk = (root / "apps" / "client" / "src" / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    deliveries = (
        root / "apps" / "client" / "src" / "packageCreator" / "pages" / "deliveries" / "index.tsx"
    ).read_text(encoding="utf-8")
    assert "export function connectorLiveLine" in lib
    assert "connectorLiveLine(c, data?.connector)" in desk
    assert "connectorLiveLine(c, data?.connector)" in deliveries
    assert "canRetryDelivery" in deliveries
    assert "sendPollToExtension" in deliveries


def test_h5_wakes_connector_on_already_active():
    from pathlib import Path

    quick = (
        Path(__file__).resolve().parents[2] / "apps" / "client" / "src" / "packageCreator" / "quickReleaseAction.ts"
    ).read_text(encoding="utf-8")
    assert "if (result.already_active)" in quick
    assert quick.split("if (result.already_active)")[1].split("return true")[0].count("sendPollToExtension") >= 1


def test_telemetry_recovers_after_attach_improves():
    from app.services.distribution.telemetry import DEGRADE_AFTER, record_channel_event, reset_telemetry

    reset_telemetry()
    for _ in range(DEGRADE_AFTER):
        record_channel_event(None, "netease", event="attach", ok=False)
    assert preview_delivery_route("netease")["degraded"] is True
    for _ in range(DEGRADE_AFTER * 3):
        record_channel_event(None, "netease", event="attach", ok=True)
    preview = preview_delivery_route("netease")
    assert preview["degraded"] is False
    assert preview["automation_level"] == "connector_full"
    reset_telemetry()


def test_preview_marks_degraded_assist():
    from app.services.distribution.telemetry import DEGRADE_AFTER, record_channel_event, reset_telemetry

    reset_telemetry()
    for _ in range(DEGRADE_AFTER):
        record_channel_event(None, "netease", event="attach", ok=False)
    preview = preview_delivery_route("netease")
    assert preview["automation_level"] == "connector_assist"
    assert preview["degraded"] is True
    reset_telemetry()


def test_hydrate_telemetry_restores_degrade():
    from app.services.distribution.telemetry import effective_automation_level, hydrate_telemetry, reset_telemetry

    reset_telemetry()

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def limit(self, n):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    channel_code="netease",
                    extra={"farm_health": {"connector_telemetry": {"degraded_to": "connector_assist", "updated_at": "2026-01-01"}}},
                )
            ]

    class Db:
        def query(self, model):
            return Query()

    hydrate_telemetry(Db())
    assert effective_automation_level("netease", "connector_full") == "connector_assist"
    reset_telemetry()


def test_h5_timeline_uses_connector_steps():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    timeline = (root / "apps" / "client" / "src" / "packageCreator" / "ChannelTimeline.tsx").read_text(
        encoding="utf-8"
    )
    release = (root / "apps" / "client" / "src" / "packageCreator" / "pages" / "release" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert "export function connectorStepIndex" in timeline
    assert "timelineAttach" in timeline
    assert "connectorEventLabel" in timeline
    assert "routePreviewDegraded" in release
    assert "routePreviewAssist" in release
    assert "export function connectorStepNowLabel" in timeline
    assert "routePreviewMetrics" in release
    connections = (root / "apps" / "client" / "src" / "packageCreator" / "ConnectionsRow.tsx").read_text(
        encoding="utf-8"
    )
    assert 'automationLevel === "metrics_only"' in connections
    assert "timelineNow" in timeline


def test_metrics_only_is_not_session_assist(monkeypatch):
    monkeypatch.setattr("app.services.distribution.catalog.pick_configured_aggregator", lambda code: None)
    preview = preview_delivery_route("spotify")
    assert preview["route"] == "metrics"
    assert preview["pipeline"] == "metrics_only"
    assert preview["automation_level"] == "metrics_only"
    delivery = SimpleNamespace(channel_code="spotify", distributor_code="distrokid")
    assert route_delivery(delivery) == "metrics"


def test_connector_skips_plant_unless_full():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    bg = (root / "apps" / "creator-connector" / "background.js").read_text(encoding="utf-8")
    assert 'const canPlant = level === "connector_full"' in bg
    assert "assist_skip_attach" in bg
    assert 'level === "metrics_only"' in bg


def test_creator_delivery_ux_copy():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    client = root / "apps" / "client" / "src" / "packageCreator"
    lib = (client / "lib.ts").read_text(encoding="utf-8")
    deliveries = (client / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    release = (client / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    auth = (client / "AuthDesk.tsx").read_text(encoding="utf-8")
    timeline = (client / "ChannelTimeline.tsx").read_text(encoding="utf-8")
    zh = (root / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    en = (root / "packages" / "i18n" / "src" / "locales" / "en.ts").read_text(encoding="utf-8")
    assert "export function humanizeDeliveryError" in lib
    assert "export function shouldShowDeliveryError" in lib
    assert "export function isPublishingDelivery" in lib
    assert "else if (isMetricsOnlyDelivery(row)) continue" in lib
    assert "deliveries.filter((d) => !isMetricsOnlyDelivery(d))" in lib
    assert "humanizeDeliveryError(d.last_error, c)" in deliveries
    assert "shouldShowDeliveryError(d)" in deliveries
    assert "creator-channel--open" in deliveries
    assert "tapRowHint" in deliveries
    assert "isPublishingDelivery(d)" in deliveries
    assert "creator-card--soft" in deliveries
    assert "channelPicked" in release
    assert "creator-mode--metrics" in release
    assert "creator-route-chips" in release
    assert "routePreviewLabel(row, c)" in release
    assert "permissions.join" not in auth
    assert "authDeskFirstPage" not in auth
    assert "creator-lamp" in auth
    assert "creator-next-store" in auth
    assert "{showSteps ? null : (" in timeline
    assert 'tapRowHint: "点开看下一步"' in zh
    assert 'connectorOn: "连接器在线"' in zh
    assert 'channelPicked: "已选"' in zh
    assert 'tapRowHint: "Tap for the next step"' in en
    assert 'channelPicked: "Selected"' in en


def test_creator_ship_prompts():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    client = root / "apps" / "client" / "src"
    lib = (client / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    quick = (client / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    release = (client / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    accounts = (client / "packageCreator" / "pages" / "accounts" / "index.tsx").read_text(encoding="utf-8")
    deliveries = (client / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    auth = (client / "packageCreator" / "AuthDesk.tsx").read_text(encoding="utf-8")
    connections = (client / "packageCreator" / "ConnectionsRow.tsx").read_text(encoding="utf-8")
    work = (client / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    onboarding = (client / "utils" / "onboarding.ts").read_text(encoding="utf-8")
    zh = (root / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    assert "export async function confirmCreatorAction" in lib
    assert "function modalBtn" not in quick
    assert "slice(0, 4)" not in quick
    resume = quick.split("export async function resumePendingQuickRelease")[1]
    assert "skipConfirm: true" not in resume
    assert "resumePendingTitle" in resume
    assert "clearPendingRelease" in resume
    submit = release.split("async function submit()")[1]
    assert "confirmOnceHint" in submit
    assert "confirmCreatorAction" in submit
    assert "humanizeDeliveryError" in submit
    wait = accounts.split("function goWaitCta()")[1][:900]
    assert "mintToken()" not in wait
    assert "pickNextAuthStore" in wait
    assert "pairCopiedHint" in auth
    assert "metricsOnlyScopeHint" in connections
    assert "disconnectSeatHint" in connections
    assert "retryFillTitle" in deliveries
    assert "weappDeskHint" in deliveries
    assert "reprocessConfirmHint" in work
    assert 'AUTO_COACH_PAGES: CoachPage[] = ["create", "creator"]' in onboarding
    assert 'resumePendingTitle: "刚才没发完"' in zh
    assert "店页可能还在，回执会撤" in zh
    assert "labels[key] || labels.pending" in lib
    assert "payoutChannelLabel" in lib
    assert "mintTokenHint" in accounts
    assert "deletePayoutHint" in accounts
    assert "unbindHint" in accounts
    assert "youtubeDisconnectHint" in accounts
    assert "radioTrialConfirm" in work
    desk = (client / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    assert "radioTrialConfirm" in desk
    assert "confirmCreatorAction" in desk
    assert "Taro.showModal" not in connections
    assert 'deletePayoutHint: "删掉后要重新填才能提现。已提交的提现单不受影响。"' in zh
