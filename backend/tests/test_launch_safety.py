from types import SimpleNamespace

from app.services.billing import list_payment_methods
from app.services.distribution.automation import AUTO_CONFIRM_MAX_NET_MINOR, AUTO_CONFIRM_MIN_CONFIDENCE
from app.services.harvest.ingest import _row_confidence
from app.services.harvest.playbooks import estimate_revenue_minor
from app.services.legal import apply_legal_contacts
from app.services.royalty.settlement import _snapshot_auto_confirmable
from app.services.royalty.subjects import AUTO_CONFIRM_SOURCES, HARVEST_AUTO_CONFIRM_SOURCES
from app.services.seats.farm import classify_empty_harvest


def test_estimate_never_invents_revenue_from_streams():
    assert estimate_revenue_minor("spotify", 10000, 0) == 0
    assert estimate_revenue_minor("netease", 12, 340) == 340


def test_user_connector_is_not_auto_confirm():
    assert "user_connector" not in AUTO_CONFIRM_SOURCES
    assert "ops_connector" not in AUTO_CONFIRM_SOURCES
    assert "seat_harvest" in AUTO_CONFIRM_SOURCES


def test_dom_harvest_confidence_is_below_auto_confirm_floor():
    assert _row_confidence({}, seated=True) < AUTO_CONFIRM_MIN_CONFIDENCE
    assert _row_confidence({"confidence": 0.95}, seated=True) >= AUTO_CONFIRM_MIN_CONFIDENCE


def test_first_party_snapshot_auto_confirmable_without_confidence():
    radio = SimpleNamespace(source="first_party_radio", raw={})
    sync = SimpleNamespace(source="sync_license", raw=None)
    embed = SimpleNamespace(source="first_party_embed", raw={"confidence": 0.1})
    assert "first_party_radio" not in AUTO_CONFIRM_SOURCES
    assert _snapshot_auto_confirmable(radio) is True
    assert _snapshot_auto_confirmable(sync) is True
    assert _snapshot_auto_confirmable(embed) is True


def test_harvest_snapshot_needs_high_confidence_to_auto_confirm():
    assert HARVEST_AUTO_CONFIRM_SOURCES <= AUTO_CONFIRM_SOURCES
    low = SimpleNamespace(source="seat_harvest", raw={"confidence": 0.75})
    farm_low = SimpleNamespace(source="farm_harvest", raw={})
    high = SimpleNamespace(source="seat_harvest", raw={"confidence": 0.95})
    assert _snapshot_auto_confirmable(low) is False
    assert _snapshot_auto_confirmable(farm_low) is False
    assert _snapshot_auto_confirmable(high) is True
    assert AUTO_CONFIRM_MAX_NET_MINOR == 20000


def test_empty_farm_harvest_is_login_wall_or_selector_broke():
    wall = classify_empty_harvest(has_session=False, seat_status="live")
    assert wall["error"] == "needs_challenge"
    assert wall["selector_broke"] is False
    broke = classify_empty_harvest(has_session=True, seat_status="live")
    assert broke["error"] == "selector_broke"
    assert broke["selector_broke"] is True


def test_payment_methods_only_lists_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "wechat_app_id", "")
    monkeypatch.setattr(settings, "wechat_app_secret", "")
    monkeypatch.setattr(settings, "wechat_pay_mch_id", "")
    monkeypatch.setattr(settings, "wechat_pay_api_key", "")
    monkeypatch.setattr(settings, "wechat_offer_id", "")
    monkeypatch.setattr(settings, "alipay_app_id", "")
    monkeypatch.setattr(settings, "alipay_private_key", "")
    monkeypatch.setattr(settings, "alipay_public_key", "")
    monkeypatch.setattr(settings, "wechat_vpay_appkey_prod", "")
    monkeypatch.setattr(settings, "wechat_vpay_appkey_sandbox", "")
    payload = list_payment_methods()
    assert payload["channels"] == []


def test_legal_contacts_replace_placeholders(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "legal_company_name", "比特音")
    monkeypatch.setattr(settings, "legal_contact_email", "support@bittune.app")
    monkeypatch.setattr(settings, "legal_contact_phone", "400-800-0000")
    text = apply_legal_contacts("炼金音坊 客服 privacy@vibe-sorcery.com 电话 400-000-0000")
    assert "比特音" in text
    assert "support@bittune.app" in text
    assert "400-800-0000" in text
    assert "privacy@vibe-sorcery.com" not in text
