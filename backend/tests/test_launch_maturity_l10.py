from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_wallet_hero_shows_warmup_and_friday():
    wallet = (CLIENT / "packageCreator" / "pages" / "wallet" / "index.tsx").read_text(encoding="utf-8")
    assert "source_split?.radio_minor" in wallet
    assert "formatWarmup(payload?.source_split?.radio_minor, c.warmupNotCash)" in wallet
    assert "formatPayoutCountdown(payload.payout_calendar, c)" in wallet
    hero = wallet.split("creator-wallet-hero")[1][:2200]
    assert "weappDeskHint" in hero or "warmupNotCash" in wallet


def test_withdraw_now_is_request_day_in_english():
    en = EN.read_text(encoding="utf-8")
    assert 'withdrawNow: "Request payout in wallet"' in en
    assert 'withdrawNow: "Withdraw now"' not in en


def test_library_menu_has_three_verbs():
    library = (CLIENT / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    assert "homeDeckDiscover" in library
    assert "homeDeckRelease" in library
    assert "homeDeckSync" in library
    assert "<PublishDialog" in library
    assert "vibeApi.createPost(publishWork.id" in library
    assert "goShipBand(menuWork.id)" in library
    assert 'commercePage("syncDesk"' in library


def test_track_row_touch_targets():
    scss = (CLIENT / "components" / "ui" / "TrackRow.scss").read_text(encoding="utf-8")
    assert "min-height: 112rpx" in scss
    assert "width: 88rpx" in scss
    assert "height: 88rpx" in scss


def test_radio_chart_is_display_only():
    radio = (CLIENT / "packageSocial" / "pages" / "radio" / "index.tsx").read_text(encoding="utf-8")
    assert "radioDisplayOnly" in radio
    assert "radioDiscoveryOnly" in radio


def test_celebration_release_navigates_to_desk():
    progress = (CLIENT / "components" / "studio" / "GenerationProgress.tsx").read_text(encoding="utf-8")
    assert "confirmQuickRelease" not in progress
    assert "goShipBand(singleWorkId)" in progress
    assert "shipToStores" in progress


def test_sync_desk_weapp_blocks_buy():
    desk = (CLIENT / "packageCommerce" / "pages" / "sync-desk" / "index.tsx").read_text(encoding="utf-8")
    buy = desk.split("async function buy(")[1][:400]
    assert 'process.env.TARO_ENV === "weapp"' in buy
    assert "copyWeappCreatorLink" in buy
    assert "WeappH5Bridge" in desk


def test_discover_copy_replaces_community_leftovers():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    row = (CLIENT / "components" / "community" / "WorkRow.tsx").read_text(encoding="utf-8")
    assert 'community: "发现"' in zh
    assert 'posts: "发现动态"' in zh
    assert 'posts: "Discover posts"' in en
    assert "w.embedAction" in row
    assert 'label: "Embed"' not in row
    assert 'embedAction: "嵌入播放"' in zh
