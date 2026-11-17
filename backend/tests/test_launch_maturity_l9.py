from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_friday_copy_is_request_day():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "今天是周五申请提现日，不会自动打款" in zh
    assert "Friday is request day — no automatic payout" in en
    assert "payoutToday: \"今天是周五申请日，不会自动打款\"" in zh
    assert "payoutToday: \"Friday request day — no automatic payout\"" in en


def test_three_verbs_stay_honest():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert 'homeDeckDiscover: "发到发现"' in zh
    assert 'homeDeckRelease: "上店发行"' in zh
    assert 'homeDeckSync: "商用授权"' in zh
    assert 'publishToDiscover: "发到发现"' in zh
    assert 'shipToStores: "上店发行"' in zh
    assert 'syncLicense: "商用授权"' in zh
    assert 'publishToCommunity: "发到发现"' in zh
    assert 'viewInCommunity: "在发现页查看"' in zh
    assert 'publishToCommunity: "Publish to Discover"' in en
    assert "discoverNotStore" in zh


def test_reveal_exposes_labeled_verbs():
    reveal = (CLIENT / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    scss = (CLIENT / "components" / "studio" / "GenerationReveal.scss").read_text(encoding="utf-8")
    assert "gen-reveal__verbs" in reveal
    assert "gen-reveal__verbs" in scss
    assert 'commercePage("syncDesk"' in reveal
    assert "ShipCompleteCard" in reveal
    assert "r.publishToDiscover || r.publishCommunity" in reveal
    assert "copy.discoverUi.discoverNotStore" in reveal
    assert 'openStackPage(stackPage("work"' not in reveal


def test_passport_live_needs_receipt():
    passport = (CLIENT / "packageCreator" / "pages" / "passport" / "index.tsx").read_text(encoding="utf-8")
    lib = (CLIENT / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    assert "isLiveDelivery(store)" in passport
    assert "store_url" not in passport.split("creator-channel--live")[0][-80:]
    assert "d.status === \"live\" && hasLiveReceipt(d)" in lib


def test_release_weapp_copies_h5_link():
    release = (CLIENT / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    assert "weapp && step >= 2" in release
    assert "weappGoRelease" in release
    assert "copyWeappCreatorLink(creatorPage(\"release\", { workId }))" in release


def test_create_home_deck_opens_discover_and_store():
    create = (CLIENT / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    assert "homeDeckDiscover" in create
    assert "homeDeckRelease" in create
    assert "homeDeckSync" in create
    assert "setPublishOpen(true)" in create
    assert "goShipBand(recentWork.id)" in create
    assert 'commercePage("syncDesk", { workId: recentWork.id })' in create
    assert "<PublishDialog" in create
    assert "vibeApi.createPost(recentWork.id" in create


def test_profile_weekly_money_is_split_honestly():
    profile = (CLIENT / "pages" / "profile" / "index.tsx").read_text(encoding="utf-8")
    assert "weeklyFiatSplit" in profile
    assert "formatWarmup(weeklySummary.wallet_split.radio_minor" in profile
    assert "formatFen(weeklySummary.wallet_split.sync_minor)" in profile
    assert "formatPayoutCountdown(weeklySummary.payout_calendar" in profile


def test_timeline_primary_is_go_only():
    timeline = (CLIENT / "components" / "studio" / "WorkReleaseTimeline.tsx").read_text(encoding="utf-8")
    assert "{copy.go}" in timeline
    assert "nextAction?.label" in timeline
    assert "onClick={() => onAction?.(action)}" in timeline


def test_asset_lanes_use_buttons():
    lanes = (CLIENT / "components" / "studio" / "AssetLanes.tsx").read_text(encoding="utf-8")
    scss = (CLIENT / "components" / "studio" / "AssetLanes.scss").read_text(encoding="utf-8")
    assert 'className="asset-lane__action"' in lanes
    assert "<Button" in lanes
    assert 'size="sm"' in lanes
    assert 'variant="ghost"' in lanes
    assert "min-height: 88rpx" in scss


def test_auth_desk_ready_is_receipt_honest():
    desk = (CLIENT / "packageCreator" / "AuthDesk.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "authDeskReady" in desk
    assert "StatusLine" in desk
    assert "handed ?" in desk
    assert "authDeskReady" in zh
