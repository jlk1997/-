"""Wave 18: remix credits are not royalties; notifications stay observable; docs stay honest."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_remix_split_is_credits_not_fiat():
    eco = (BACKEND / "services" / "ecosystem.py").read_text(encoding="utf-8")
    wallet = eco.split("def get_creator_wallet")[1]
    assert '"remix_credits_7d": remix_credits_7d' in wallet
    assert '"ledger": "credits"' in wallet
    earnings = (CLIENT / "packageCommerce" / "pages" / "creator-earnings" / "index.tsx").read_text(encoding="utf-8")
    assert "remixCredits > 0" in earnings
    assert "e.remixCreditsHint" in earnings
    assert "showFiat" in earnings
    zh = ZH.read_text(encoding="utf-8")
    assert "不是法币版税" in zh.split("remixCreditsHint")[1][:80]
    assert "Remix credit split this week" in EN.read_text(encoding="utf-8")


def test_key_event_fanout_is_observable():
    notify = (BACKEND / "services" / "notifications.py").read_text(encoding="utf-8")
    wrapper = notify.split("def notify_key_event_sync")[1]
    assert "_track_fanout" in wrapper
    assert "add_done_callback" in notify
    assert "_FANOUT_TASKS" in notify
    assert "LAST_FANOUT" in notify
    assert "except Exception:\n        pass" not in wrapper.split("return {")[0]


def test_next_card_names_who_and_where():
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    card = (CLIENT / "packageCreator" / "NextActionCard.tsx").read_text(encoding="utf-8")
    lib = (CLIENT / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    assert "parkedStepCopy(step, c)" in desk
    assert "creator-next__park" in card
    assert "stopReceipt" in lib
    assert "stopPayout" in lib
    zh = ZH.read_text(encoding="utf-8")
    assert 'parkYou: "下一步是你"' in zh
    assert 'stopReceipt: "停在店页回执"' in zh
    assert "fridayQueueWho:" in zh
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    assert "a.fridayQueueWho" in admin


def test_release_desk_says_store_is_not_discover():
    release = (CLIENT / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    onboarding = (CLIENT / "utils" / "onboarding.ts").read_text(encoding="utf-8")
    assert "c.storeNotDiscover" in release
    assert 'AUTO_COACH_PAGES: CoachPage[] = ["create", "creator"]' in onboarding
    assert "发到发现不是上店" in ZH.read_text(encoding="utf-8")
    assert "没有店页回执不会标 live" in ZH.read_text(encoding="utf-8")


def test_roadmap_does_not_resell_closed_gaps():
    roadmap = (ROOT / "PRODUCT_ROADMAP_v5.md").read_text(encoding="utf-8")
    assert "已闭环 / 停住 / 等密钥" in roadmap
    section = roadmap.split("### 1.2")[1].split("## 2.")[0]
    assert "不要再写「Playlist 必须 seed / 搜索未做」" in section
    assert "prompt_journey" in section
    assert "无回执不得 live" in section
    assert "| **P0** |" not in section
