from pathlib import Path

from app.services.distribution.timeline import _aggregate_delivery_status

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_aggregate_delivery_status_needs_receipt():
    ghost = {"status": "live", "store_url": None, "external_id": None, "channel_code": "spotify"}
    portal = {
        "status": "live",
        "store_url": "https://artists.spotify.com/",
        "external_id": None,
        "channel_code": "spotify",
    }
    real = {
        "status": "live",
        "store_url": "https://open.spotify.com/track/abc",
        "external_id": "abc",
        "channel_code": "spotify",
    }
    assert _aggregate_delivery_status([]) == "not_started"
    assert _aggregate_delivery_status([ghost]) == "in_progress"
    assert _aggregate_delivery_status([portal]) == "in_progress"
    assert _aggregate_delivery_status([real]) == "live"
    assert _aggregate_delivery_status([{"status": "rejected"}]) == "rejected"


def test_journey_stores_done_only_with_receipt():
    journey = (CLIENT / "packageCreator" / "JourneyProgress.tsx").read_text(encoding="utf-8")
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    deliveries = (CLIENT / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    assert "const storesDone = Boolean(state.hasLive);" in journey
    assert "state.delivering || state.hasLive" not in journey
    assert "d.status === \"live\" && !isLiveDelivery(d)" in desk
    assert '["queued", "delivering", "live"].includes(r.status' not in desk
    assert "buckets.login + buckets.upload + buckets.pushing > 0" in deliveries
    assert "delivering: allDeliveries.length > 0" not in deliveries


def test_timeline_and_desk_money_stay_honest():
    timeline = (ROOT / "backend" / "app" / "services" / "distribution" / "timeline.py").read_text(encoding="utf-8")
    desk = (CLIENT / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    feed = (CLIENT / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    harvest = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "money_bucket" in timeline
    assert "has_live_receipt" in timeline
    assert "wk.has_real" in desk
    assert "displayOnlyBadge" in desk
    assert "risingCreators.length > 0 && <RisingCreatorsRow" not in feed
    assert "<RisingCreatorsRow creators={risingCreators} />" in feed
    assert "unmatchedBadge" in harvest
    assert 'tone="success"' not in harvest.split("harvestRows.map")[1][:800]
    assert "healCopied" in admin
    assert "unmatchedBadge" in zh
    assert "unmatchedBadge" in en
    assert "healCopied" in zh
