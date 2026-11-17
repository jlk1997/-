from pathlib import Path
from types import SimpleNamespace

from app.services.distribution.catalog import delivery_has_live_receipt, has_live_receipt
from app.services.distribution.pipeline import delivery_progress
from app.services.distribution.service import user_delivery_status

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_live_without_receipt_stays_publishing():
    ghost = SimpleNamespace(status="live", store_url=None, external_id=None, channel_code="spotify")
    portal = SimpleNamespace(
        status="live",
        store_url="https://artists.spotify.com/",
        external_id=None,
        channel_code="spotify",
    )
    real = SimpleNamespace(
        status="live",
        store_url="https://open.spotify.com/track/abc",
        external_id="abc",
        channel_code="spotify",
    )
    assert delivery_has_live_receipt(ghost) is False
    assert delivery_has_live_receipt(portal) is False
    assert delivery_has_live_receipt(real) is True
    assert has_live_receipt(store_url="https://soundcloud.com/you/insights", channel_code="soundcloud") is False
    assert user_delivery_status("live", has_receipt=False) == "publishing"
    ghost_plan = delivery_progress([ghost])
    assert ghost_plan["live"] == 0
    assert ghost_plan["release_status"] == "delivering"
    assert delivery_progress([real])["release_status"] == "live"


def test_serialize_and_passport_expose_receipt():
    service = (ROOT / "backend" / "app" / "services" / "distribution" / "service.py").read_text(encoding="utf-8")
    passport = (ROOT / "backend" / "app" / "services" / "distribution" / "passport.py").read_text(encoding="utf-8")
    hub = (ROOT / "backend" / "app" / "services" / "royalty" / "hub.py").read_text(encoding="utf-8")
    assert '"has_receipt": receipt' in service
    assert "has_receipt=receipt if d.status == \"live\" else None" in service
    assert 'row.get("has_receipt")' in passport
    assert "delivery_has_live_receipt" in hub
    assert "waiting_for_statement" in hub


def test_weapp_desk_gates_commune_clips_and_packs():
    creator = (ROOT / "backend" / "app" / "api" / "routes" / "creator.py").read_text(encoding="utf-8")
    for handler in (
        "def post_commune(",
        "def post_commune_invite(",
        "def post_commune_leave(",
        "def share_work_passport(",
        "def post_work_clip_drop(",
        "def download_clip_pack(",
        "def download_originality_pack(",
    ):
        assert handler in creator
        idx = creator.index(handler)
        assert "require_h5_desk" in creator[idx : idx + 420]
    releases = (ROOT / "backend" / "app" / "api" / "routes" / "releases.py").read_text(encoding="utf-8")
    distribution = (ROOT / "backend" / "app" / "api" / "routes" / "distribution.py").read_text(encoding="utf-8")
    assert "def download_kit(" in releases
    idx = releases.index("def download_kit(")
    assert "require_h5_desk" in releases[idx : idx + 360]
    assert "def youtube_oauth_url(" in distribution
    idx = distribution.index("def youtube_oauth_url(")
    assert "require_h5_desk" in distribution[idx : idx + 360]


def test_client_live_helpers_need_receipt():
    lib = (CLIENT / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    deliveries = (CLIENT / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    remote = (CLIENT / "packageCreator" / "pages" / "remote-login" / "index.tsx").read_text(encoding="utf-8")
    commune = (CLIENT / "packageCreator" / "pages" / "commune" / "index.tsx").read_text(encoding="utf-8")
    kit = (CLIENT / "packageCreator" / "kitAction.ts").read_text(encoding="utf-8")
    feed = (CLIENT / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    winner = (CLIENT / "components" / "community" / "WinnerReleaseBanner.tsx").read_text(encoding="utf-8")
    assert "export function isLiveDelivery" in lib
    assert "export function hasLiveReceipt" in lib
    assert "deliveries.filter((d) => isLiveDelivery(d))" in lib
    assert "Number(work?.live_stores) > 0 || live > 0" in work
    assert "dels.some((d) => isLiveDelivery(d))" in deliveries
    assert "start && !weapp" in remote
    assert "copyWeappCreatorLink" in commune
    assert "blockWeappDesk" in kit
    assert "empty={!sameStyleError}" in feed
    assert "setLoadError(true)" in winner
    assert "d.retry" in winner


def test_radio_and_weekly_copy_stay_warmup():
    notes = (ROOT / "backend" / "app" / "services" / "notifications.py").read_text(encoding="utf-8")
    digest = (ROOT / "backend" / "app" / "services" / "creator_weekly_digest.py").read_text(encoding="utf-8")
    settlement = (ROOT / "backend" / "app" / "services" / "royalty" / "settlement.py").read_text(encoding="utf-8")
    wallet = (CLIENT / "packageCreator" / "pages" / "wallet" / "index.tsx").read_text(encoding="utf-8")
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    notifications = (CLIENT / "packageStack" / "pages" / "notifications" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "电台已记" not in notes
    assert "发现预热展示，不可提现" in notes
    assert "发现预热展示" in digest
    assert "可结算" in digest
    assert "不含电台预热" in settlement
    assert "formatFen(payload?.source_split?.radio_minor" not in wallet
    assert "formatFen(data.money_timeline.sources.radio_minor" not in work
    assert "formatWarmup(Number(s.radio_minor" in notifications
    assert "发现预热 {radio}" in zh
    assert "discovery warmup {radio}" in en
    assert "patrolFailed" in zh
    assert "risingCreatorsEmpty" in zh


def test_ops_patrol_failed_is_actionable():
    ops = (ROOT / "backend" / "app" / "services" / "ops_dashboard.py").read_text(encoding="utf-8")
    farm = (ROOT / "backend" / "app" / "services" / "seats" / "farm.py").read_text(encoding="utf-8")
    admin_api = (ROOT / "backend" / "app" / "api" / "routes" / "admin.py").read_text(encoding="utf-8")
    admin_ui = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    assert '"patrol_failed": int(patrol_failed)' in ops
    assert '"patrol_failed": patrol_failed' in farm
    assert '"patrol_failed": patrol_failed' in admin_api
    assert "patrol_failed" in admin_ui
    assert "a.patrolFailed" in admin_ui
