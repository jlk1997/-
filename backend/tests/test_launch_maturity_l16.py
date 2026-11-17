from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_publish_celebration_primary_is_ship():
    sheet = (CLIENT / "components" / "ui" / "CelebrationSheet.tsx").read_text(encoding="utf-8")
    progress = (CLIENT / "components" / "studio" / "GenerationProgress.tsx").read_text(encoding="utf-8")
    assert "variant === \"publish\" && Boolean(releaseLabel && onRelease && !releaseDisabled)" in sheet
    primary = sheet.split("{publishPrimary ? (")[1].split("firstTrackPrimary")[0]
    assert "{releaseLabel}" in primary
    assert "onRelease" in primary
    assert "onCommunity" not in primary
    celebrate = progress.split("<CelebrationSheet")[1]
    assert "releaseDisabled={preflightFail}" in celebrate
    assert "releaseHint={preflightFail ? g.preflightFail : undefined}" in celebrate
    assert 'communityLabel={celebrateVariant !== "publish" && singleWorkId ? copy.celebrationUi.goCommunity : undefined}' in celebrate


def test_reveal_ship_waits_for_qc():
    reveal = (CLIENT / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    scss = (CLIENT / "components" / "studio" / "GenerationReveal.scss").read_text(encoding="utf-8")
    verbs = reveal.split("gen-reveal__verbs")[1]
    assert "ShipCompleteCard" in verbs
    assert "qcReady={qcReady}" in verbs
    assert "shipQcGate" in (CLIENT.parent.parent.parent / "packages" / "i18n" / "src" / "locales" / "zh.ts").read_text(encoding="utf-8")
    assert 'size="sm"' not in verbs.split("gen-reveal__verb-hint")[0]
    assert "min-height: 88rpx" in scss.split(".gen-reveal__verbs")[1][:220]


def test_friday_and_help_copy_name_request_desk():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "今天周五申请提现日" in zh
    assert "距周五申请提现还有 {n} 天" in zh
    assert "下次申请提现 {d}" in zh
    assert "Friday is request-payout day" in en
    assert "until Friday request-payout day" in en
    assert "Next request-payout day {d}" in en
    assert "周五打款日" not in zh
    assert "距周五打款" not in zh
    assert "发行台点上店发行" in zh
    assert "上架商店要从发行台开始" in zh
    assert "ship it from Release desk" in en
    assert "Store listings start from Release desk." in en
    assert 'packsCommunity: "社区配方"' in zh
    assert 'packsCommunity: "Discover packs"' in en
    assert 'goRelease: "上店发行"' in zh
    assert "商店上架请点上店发行" in zh


def test_weapp_desk_writes_copy_h5_link():
    wallet = (CLIENT / "packageCreator" / "pages" / "wallet" / "index.tsx").read_text(encoding="utf-8")
    accounts = (CLIENT / "packageCreator" / "pages" / "accounts" / "index.tsx").read_text(encoding="utf-8")
    settlements = (CLIENT / "packageCreator" / "pages" / "settlements" / "index.tsx").read_text(encoding="utf-8")
    data_import = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    kit = (CLIENT / "packageCreator" / "kitAction.ts").read_text(encoding="utf-8")
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    withdraw = wallet.split("async function withdraw")[1]
    assert "copyWeappCreatorLink(CREATOR_PAGE_ROUTES.wallet)" in withdraw
    bind = accounts.split("async function bind")[1]
    assert "copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts)" in bind
    mint = accounts.split("async function mintToken")[1]
    assert "copyWeappCreatorLink(CREATOR_PAGE_ROUTES.accounts)" in mint
    statement = settlements.split("async function exportStatement")[1]
    assert "copyWeappCreatorLink(creatorPage(\"settlements\"))" in statement
    pick = data_import.split("async function pick")[1]
    assert "copyWeappCreatorLink(CREATOR_PAGE_ROUTES.dataImport)" in pick
    assert "await copyWeappCreatorLink(path)" in kit
    auto = desk.split("async function toggleAutoRelease")[1]
    assert "copyWeappCreatorLink(CREATOR_TAB_ROUTE)" in auto


def test_desk_empties_have_create_cta():
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    recent_empty = desk.split("(data?.recent || []).length === 0")[1]
    assert "actionLabel={c.goCreate}" in recent_empty[:500]
    assert "c.emptyRadioTrial" in desk
    assert "c.emptyClips" in desk
    assert "c.emptyReleaseHint" not in desk.split('releaseInbox === "trials"')[1].split('releaseInbox === "clips"')[0]
    assert 'emptyRadioTrial: "还没有电台试听"' in zh
    assert 'emptyClips: "还没有账本切片"' in zh
    assert "emptyRadioTrial:" in en
    assert "emptyClips:" in en


def test_checkin_primary_meets_touch_target():
    sheet = (CLIENT / "components" / "engagement" / "ListenCheckinSheet.tsx").read_text(encoding="utf-8")
    scss = (CLIENT / "components" / "engagement" / "ListenCheckinSheet.scss").read_text(encoding="utf-8")
    bridge = (CLIENT / "packageCreator" / "WeappH5Bridge.tsx").read_text(encoding="utf-8")
    assert '<Button variant="primary" block loading>' in sheet
    assert '<Button variant="primary" block loading={trialBusy}' in sheet
    assert '<Button variant="primary" block onClick={goRadio}>' in sheet
    assert 'size="sm" variant="primary"' not in sheet
    assert "min-height: 88rpx" in scss.split(".listen-checkin__mood {")[1][:80]
    assert 'size="sm"' not in bridge.split("<Button")[1].split(">")[0]
