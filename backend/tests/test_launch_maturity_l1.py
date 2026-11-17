from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_friday_copy_is_request_day_not_auto_payout():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert 'payoutToday: "今天是周五申请日，不会自动打款"' in zh
    assert "每周五申请提现" in zh
    assert "radio warmup" in en or "not withdrawable" in en
    assert "不进可提现" in zh
    assert "会进本周电台结算" not in zh
    calendar = (ROOT / "backend" / "app" / "services" / "royalty" / "payout_calendar.py").read_text(encoding="utf-8")
    assert "申请提现日" in calendar
    assert "不会自动打款" in calendar
    digest = (ROOT / "backend" / "app" / "services" / "creator_weekly_digest.py").read_text(encoding="utf-8")
    assert "发现预热展示" in digest
    assert "0 可提现" in digest
    assert "电台预热约" not in digest
    assert "电台可结算" not in digest
    assert "不会自动打款" in digest


def test_weapp_wallet_and_release_stay_read_only():
    wallet = (CLIENT / "packageCreator" / "pages" / "wallet" / "index.tsx").read_text(encoding="utf-8")
    release = (CLIENT / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    accounts = (CLIENT / "packageCreator" / "pages" / "accounts" / "index.tsx").read_text(encoding="utf-8")
    harvest = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    assert 'process.env.TARO_ENV === "weapp"' in wallet
    assert "walletOn && !weapp" in wallet
    assert "weappDeskHint" in wallet
    assert "weappDeskHint" in release
    assert "AuthDesk" in release
    assert "receiptNeedLogin" in release
    assert "catalogError" in release
    assert "async function loadCatalog" in release
    assert "catalogLoadFail" in release
    assert "weappDeskHint" in accounts
    assert 'if (process.env.TARO_ENV === "weapp")' in accounts
    assert "weapp ? null : (data?.accounts || []).length === 0" not in accounts
    assert "{!weapp ? (" in accounts
    assert "weappDeskHint" in harvest
    assert "if (weapp)" in harvest


def test_tab_legal_footer_and_honest_icp_copy():
    shell = (CLIENT / "components" / "PageShell.tsx").read_text(encoding="utf-8")
    library = (CLIENT / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "LegalFooter" in shell
    assert 'tabVariant && process.env.TARO_ENV === "h5"' in shell
    assert "tabVariant" in library
    assert "尚未公示备案号" in zh
    assert "不会先编一个号" in zh
    assert "No ICP filing number is published yet" in en
    assert "店有回执" in zh
    assert "stores with receipts" in en
    assert "不是已上架" in zh
    assert "not live yet" in en
    assert "连接器或运营会继续发" in zh


def test_predicted_revenue_hidden_without_harvest():
    hub = (ROOT / "backend" / "app" / "services" / "royalty" / "hub.py").read_text(encoding="utf-8")
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "show_prediction = has_real_data" in hub
    assert "show_prediction = has_label_statement" in hub
    assert "or int(total_revenue or 0) > 0" not in hub
    assert "or int(label_revenue or 0) > 0" not in hub
    assert 'wk.pop("predicted_revenue", None)' in hub
    assert "const hasHarvestMoney" in work
    assert "hasHarvestMoney && (data?.predicted_revenue" in work


def test_live_store_count_requires_receipt():
    passport = (ROOT / "backend" / "app" / "services" / "distribution" / "passport.py").read_text(encoding="utf-8")
    assert "has_live_receipt" in passport
    assert "DistributionDelivery.store_url" in passport


def test_soundcloud_insights_and_profile_are_not_live():
    from app.services.distribution.catalog import has_live_receipt, looks_like_store_page

    assert has_live_receipt(store_url="https://soundcloud.com/you/insights", channel_code="soundcloud") is False
    assert has_live_receipt(store_url="https://soundcloud.com/artist", channel_code="soundcloud") is False
    assert has_live_receipt(store_url="https://soundcloud.com/pages/contact", channel_code="soundcloud") is False
    assert looks_like_store_page("https://soundcloud.com/you/insights", "soundcloud") is False
    assert has_live_receipt(store_url="https://soundcloud.com/artist/night-drive", channel_code="soundcloud") is True


def test_checkin_release_opens_wizard_not_one_tap():
    sheet = (CLIENT / "components" / "engagement" / "ListenCheckinSheet.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    assert "confirmQuickRelease" not in sheet
    assert "creatorPage(\"release\"" in sheet
    assert "发行不会从这里自动提交" in zh
    assert "checkinReleaseHint" in sheet


def test_radio_enters_on_tap_not_autoplay():
    radio = (CLIENT / "packageSocial" / "pages" / "radio" / "index.tsx").read_text(encoding="utf-8")
    assert "Station enter is tap-to-play" in radio
    assert "Only a deep-linked track auto-starts" in radio
    assert "playTrack" in radio


def test_work_ledger_does_not_treat_delivering_as_live():
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "const liveNow" in work
    assert "const inFlight" in work
    assert "Number(work?.live_stores) > 0 || live > 0" in work
    assert '["live", "delivering", "queued"].includes(work?.release_status' not in work


def test_legal_view_strips_placeholder_hotline():
    view = (CLIENT / "components" / "legal" / "LegalDocumentView.tsx").read_text(encoding="utf-8")
    assert "applyLiveContacts" in view
    assert "400-000-0000" in view
    assert "useLegalMeta" in view


def test_distribution_and_auto_release_fan_out():
    pipeline = (ROOT / "backend" / "app" / "services" / "distribution" / "pipeline.py").read_text(encoding="utf-8")
    auto = (ROOT / "backend" / "app" / "services" / "distribution" / "automation.py").read_text(encoding="utf-8")
    notify = (ROOT / "backend" / "app" / "services" / "notifications.py").read_text(encoding="utf-8")
    assert "notify_key_event_sync" in pipeline
    assert "不是已上架" in auto
    assert "_fresh_external" in notify
    celery = (ROOT / "backend" / "app" / "celery_app.py").read_text(encoding="utf-8")
    assert "manual-payout-friday-audit" in celery
    assert "auto-payout-friday" not in celery
