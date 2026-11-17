from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_desk_and_banners_open_ship_band():
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    reveal = (CLIENT / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    winner = (CLIENT / "components" / "community" / "WinnerReleaseBanner.tsx").read_text(encoding="utf-8")
    week = (CLIENT / "components" / "community" / "WeekDropBanner.tsx").read_text(encoding="utf-8")
    assert "confirmQuickRelease" not in desk
    assert "function openReleaseDesk" in desk
    assert "CREATOR_SHIP_WORK_KEY" in desk
    assert "focusShipCompleteBand" in desk
    assert "confirmQuickRelease" not in reveal
    assert "ShipCompleteCard" in reveal
    assert "confirmQuickRelease" not in winner
    assert "confirmQuickRelease" not in week
    assert "goShipBand(work.work_id)" in winner
    assert "goShipBand(work.work_id)" in week


def test_desk_money_and_weapp_glance_are_honest():
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    assert "formatPayoutCountdown(data.payout_calendar, c)" in desk
    assert "formatWarmup(sourceSplit.radio_minor, c.warmupNotCash)" in desk
    assert "formatWarmup(sourceSplit?.radio_minor, c.warmupNotCash)" in desk
    assert "<AuthDesk" in desk
    assert "weapp ? (" in desk
    assert "AuthDesk" in desk.split("creator-weapp-glance")[1]


def test_withdraw_and_discover_copy():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert 'withdrawNow: "去钱包申请提现"' in zh
    assert 'withdrawNow: "Request payout in wallet"' in en
    assert 'emptyTitle: "发现页还没热起来"' in zh
    assert 'activityEmpty: "暂无发现动态"' in zh
    assert 'loadError: "暂时无法加载发现内容"' in zh
    assert 'chartsTitle: "发现榜单"' in zh
    assert 'duelNeedPublish: "请先把作品发到发现"' in zh
    assert 'duelNeedPublish: "Publish a work to Discover first"' in en


def test_player_and_feed_touch_targets():
    mini = (CLIENT / "components" / "player" / "MiniPlayerBar.scss").read_text(encoding="utf-8")
    now = (CLIENT / "packageStack" / "pages" / "now-playing" / "index.scss").read_text(encoding="utf-8")
    feed = (CLIENT / "pages" / "feed" / "index.scss").read_text(encoding="utf-8")
    assert "width: 88rpx" in mini
    assert "height: 88rpx" in mini
    assert ".now-playing__action {\n  width: 88rpx;\n  height: 88rpx;" in now.replace("\r\n", "\n")
    assert "min-height: 88rpx" in feed.split(".feed-head__activity")[1][:160]
    assert "width: 88rpx" in feed.split(".feed-head__search")[1][:80]
