from pathlib import Path

from app.api.surface import is_weapp_surface, require_h5_desk

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_weapp_surface_rejects_desk_writes():
    assert is_weapp_surface("weapp") is True
    assert is_weapp_surface("miniprogram") is True
    assert is_weapp_surface("h5") is False
    assert is_weapp_surface(None) is False
    try:
        require_h5_desk("weapp")
        raise AssertionError("weapp must be rejected")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
        assert "WEAPP_H5_DESK" in str(exc.detail)
    require_h5_desk(None)
    require_h5_desk("h5")


def test_weapp_desk_writes_are_gated_in_routes_and_client():
    wallet = (ROOT / "backend" / "app" / "api" / "routes" / "wallet.py").read_text(encoding="utf-8")
    releases = (ROOT / "backend" / "app" / "api" / "routes" / "releases.py").read_text(encoding="utf-8")
    creator = (ROOT / "backend" / "app" / "api" / "routes" / "creator.py").read_text(encoding="utf-8")
    distribution = (ROOT / "backend" / "app" / "api" / "routes" / "distribution.py").read_text(encoding="utf-8")
    seats = (ROOT / "backend" / "app" / "api" / "routes" / "seats.py").read_text(encoding="utf-8")
    sync_desk = (ROOT / "backend" / "app" / "api" / "routes" / "sync_desk.py").read_text(encoding="utf-8")
    core = (ROOT / "packages" / "api-client" / "src" / "core.ts").read_text(encoding="utf-8")
    app = (CLIENT / "app.tsx").read_text(encoding="utf-8")
    quick = (CLIENT / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    harvest = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    settings = (CLIENT / "packageStack" / "pages" / "settings" / "index.tsx").read_text(encoding="utf-8")
    connections = (CLIENT / "packageCreator" / "ConnectionsRow.tsx").read_text(encoding="utf-8")
    assert "require_h5_desk" in wallet
    assert "require_h5_desk" in releases
    assert "require_h5_desk" in creator
    assert "require_h5_desk" in distribution
    assert "require_h5_desk" in seats
    assert "require_h5_desk" in sync_desk
    for handler in (
        "def create_release(",
        "def patch_release(",
        "def qc_release(",
        "def license_release(",
        "def submit(",
        "def auto_submit(",
        "def takedown(",
    ):
        assert handler in releases
        idx = releases.index(handler)
        assert "require_h5_desk" in releases[idx : idx + 360]
    for handler in (
        "def connect(",
        "def disconnect(",
        "def bind_session(",
        "def attach_row(",
        "def update_scopes(",
        "def harvest_now(",
        "def harvest_rows(",
        "def sync_rows(",
    ):
        assert handler in seats
        idx = seats.index(handler)
        assert "require_h5_desk" in seats[idx : idx + 360]
    assert "def save_listing" in sync_desk
    idx = sync_desk.index("def save_listing")
    assert "require_h5_desk" in sync_desk[idx : idx + 320]
    assert "def create_order(" in sync_desk
    idx = sync_desk.index("def create_order(")
    assert "require_h5_desk" in sync_desk[idx : idx + 320]
    for handler in (
        "def retry(",
        "def store_url(",
        "def bind(",
        "def unbind(",
        "def analytics_sync_now(",
        "def connector_match_claim(",
    ):
        assert handler in distribution
        idx = distribution.index(handler)
        assert "require_h5_desk" in distribution[idx : idx + 360]
    assert "def save_work_splits(" in creator
    idx = creator.index("def save_work_splits(")
    assert "require_h5_desk" in creator[idx : idx + 360]
    assert "is_weapp_surface" in creator
    assert "kick_user_due_harvests" in creator
    assert 'headers["X-Vibe-Surface"]' in core or "X-Vibe-Surface" in core
    assert "setClientSurface" in app
    assert 'process.env.TARO_ENV === "weapp"' in quick
    assert "weappDeskHint" in quick
    assert "if (weapp)" in harvest
    assert "attachHarvestUnmatched" in harvest
    assert "weappDeskHint" in settings
    assert 'process.env.TARO_ENV === "weapp"' in connections
    assert "copyWeappCreatorLink" in connections
    assert 'copyWeappCreatorLink(creatorPage("accounts"))' in connections


def test_first_visit_coach_waits_for_privacy_and_is_one_step():
    onboarding = (CLIENT / "utils" / "onboarding.ts").read_text(encoding="utf-8")
    coach = (CLIENT / "components" / "onboarding" / "CoachMarks.tsx").read_text(encoding="utf-8")
    assert "hasLocalPrivacyConsent" in onboarding
    assert "hasLocalPrivacyConsent" in coach
    assert "privacyReady" in coach
    assert "o.step2Title" in coach
    assert "anchor: \"prompt\"" in coach or "anchor: \"prompt\" as Anchor" in coach
    assert "anchor: \"generate\"" in coach or "anchor: \"generate\" as Anchor" in coach
    assert "measureAnchor" in coach
    assert "fallbackSpot" in coach
    assert "veilsAround" in coach
    assert "requiresLogin && !isLoggedIn()" in coach
    assert "requiresLogin || signedIn" in coach or "(!requiresLogin || signedIn)" in coach
    assert "legacyPageDone(page)" not in onboarding
    assert "AUTO_COACH_PAGES.includes(page) && !isLoggedIn()" in onboarding
    assert "ONBOARDING_RESET_EVENT" in onboarding
    assert "AUTH_EVENTS.login" in coach
    assert "AUTH_EVENTS.logout" in coach


def test_reveal_publishes_to_discover_not_work_stack():
    reveal = (CLIENT / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    assert "PublishDialog" in reveal
    assert "setPublishOpen(true)" in reveal
    assert "createPost" in reveal


def test_radio_copy_is_warmup_not_fiat_pay():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "创作者才能结算。自己听自己的不计" not in zh
    assert "发现预热" in zh
    assert "not withdrawable" in en
    assert "creator can be paid. Self-listens" not in en
    assert "电台已记" not in zh
    assert "radioListenSettled" in zh
    assert "不可提现" in zh
    assert "logged {n} fen" not in en
    assert "discovery warmup" in en
    digest = (ROOT / "backend" / "app" / "services" / "creator_weekly_digest.py").read_text(encoding="utf-8")
    assert "radio_minor = int(radio_completes)" not in digest
    assert "发现预热展示" in digest


def test_ops_digest_shows_unattached_snapshots():
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "unattached_snapshots" in admin
    assert "unattachedSnapshots" in zh


def test_client_env_example_does_not_force_lan_ip():
    example = (ROOT / "apps" / "client" / ".env.example").read_text(encoding="utf-8")
    assert "superformersmusic.com" in example
    active = [line for line in example.splitlines() if line.startswith("TARO_APP_API_URL=")]
    assert active == []


def test_variation_picker_publishes_to_discover_first():
    picker = (CLIENT / "components" / "studio" / "VariationPicker.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "PublishDialog" in picker
    assert "setPublishOpen(true)" in picker
    assert "createPost" in picker
    assert "publishToDiscover" in picker
    assert "先发到发现" in zh or "再发到发现" in zh


def test_official_listen_shelf_empty_is_honest():
    shelf = (CLIENT / "components" / "community" / "OfficialListenShelf.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "if (!tracks.length) return null" not in shelf
    assert "officialEmpty" in shelf
    assert "officialEmpty" in zh
    assert "officialEmpty" in en


def test_work_glance_does_not_sum_warmup_into_booked():
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "label_revenue_minor || 0) + (data?.warmup_revenue_minor" not in work
    assert "workGlanceWarmup" in work
    assert "has_label_statement" in work
    assert "不进可提现" in zh
    assert "not withdrawable" in en


def test_weapp_h5_origin_rejects_lan_and_localhost():
    platform = (CLIENT / "platform" / "platformConfig.ts").read_text(encoding="utf-8")
    bridge = (CLIENT / "packageCreator" / "WeappH5Bridge.tsx").read_text(encoding="utf-8")
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "export function isPublicFrontendOrigin" in platform
    assert "export function creatorOsH5Ready" in platform
    assert "127.0.0.1" in platform
    assert "if (isPublicFrontendOrigin(cleaned))" in platform
    assert "creatorOsH5Ready" in bridge
    assert "creatorOsH5Ready" in desk
    assert "superformersmusic.com" in zh


def test_ops_digest_chips_scroll_to_anchors():
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    assert "scrollIntoView" in admin
    assert "ops-anchor-harvest" in admin
    assert "ops-anchor-payouts" in admin
    assert "ops-anchor-kyc" in admin
    assert 'setTab("settlement")' in admin


def test_celebration_publish_is_discover_first():
    sheet = (CLIENT / "components" / "ui" / "CelebrationSheet.tsx").read_text(encoding="utf-8")
    assert "publishPrimary" in sheet
    assert "firstTrackPrimary" in sheet
    assert 'variant === "publish"' in sheet


def test_weapp_cannot_mutate_deliveries_or_splits():
    deliveries = (CLIENT / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    harvest = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    assert "copyWeappCreatorLink" in deliveries
    assert "async function saveUrl" in deliveries
    assert "async function retry" in deliveries
    assert "async function takedown" in deliveries
    assert deliveries.index("if (weapp)") < deliveries.index("setDeliveryStoreUrl")
    assert "saveWorkSplits" in work
    assert "copyWeappCreatorLink" in work
    assert "attachUnattachedSnapshot" in harvest
    assert harvest.count("if (weapp)") >= 2


def test_radio_warmup_is_not_formatted_as_cash():
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    settlements = (CLIENT / "packageCreator" / "pages" / "settlements" / "index.tsx").read_text(encoding="utf-8")
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    lib = (CLIENT / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "export function formatWarmup" in lib
    assert "formatWarmup(sourceSplit?.radio_minor" in desk
    assert "formatFen(sourceSplit?.radio_minor)" not in desk
    assert "formatWarmup(sources?.radio_minor" in settlements
    assert "formatFen(data?.warmup_revenue_minor)" not in work
    assert "warmupNotCash" in zh


def test_empty_connector_and_same_style_stay_visible():
    connections = (CLIENT / "packageCreator" / "ConnectionsRow.tsx").read_text(encoding="utf-8")
    wall = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "if (!ranked.length) return null" not in connections
    assert "connInstallHint" in connections
    assert "empty" in wall
    assert "<SameStyleWall" in wall


def test_daily_harvest_rematch_is_isrc_only():
    unmatched = (ROOT / "backend" / "app" / "services" / "harvest" / "unmatched.py").read_text(encoding="utf-8")
    tasks = (ROOT / "backend" / "app" / "workers" / "harvest_tasks.py").read_text(encoding="utf-8")
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    seats_health = (ROOT / "backend" / "app" / "api" / "routes" / "admin.py").read_text(encoding="utf-8")
    assert "def rematch_unmatched_harvest" in unmatched
    assert 'kind != "isrc"' in unmatched
    assert "rematch_unmatched_harvest" in tasks
    assert "playbook_health" in seats_health
    assert "healHint" in admin
