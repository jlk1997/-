from types import SimpleNamespace

from app.services.royalty.subjects import SUBJECT_HARVEST, accounting_subject
from app.services.royalty.hub import (
    _accumulate,
    _empty_channel,
    _is_label_statement,
    _work_statement_window,
    build_hub_alerts,
    harvest_health,
    hub_connector_next_action,
    money_timeline,
    work_next_action,
)


def test_hub_alerts_prioritize_ops_and_money():
    alerts = build_hub_alerts(
        unpublished_count=2,
        publishing_count=3,
        rejected_count=1,
        unclaimed_count=4,
        unmatched_count=2,
        pending_confirm_count=5,
        missing_payout=True,
        kyc_none=True,
        available_minor=1200,
    )
    ids = [a["id"] for a in alerts]
    assert ids == ["unpublished", "publishing", "rejected", "pending_confirm", "no_payout", "kyc"]
    assert next(a["count"] for a in alerts if a["id"] == "rejected") == 1


def test_hub_alerts_hide_payout_kyc_when_no_balance():
    alerts = build_hub_alerts(missing_payout=True, kyc_none=True, available_minor=0)
    assert alerts == []


def test_hub_alerts_include_clip_inbox():
    alerts = build_hub_alerts(clip_drop_count=3)
    assert alerts == [{"id": "clip_inbox", "level": "info", "count": 3}]


def test_hub_alerts_include_trial_ending():
    alerts = build_hub_alerts(trial_ending_count=2)
    assert alerts == [{"id": "trial_ending", "level": "info", "count": 2}]


def test_hub_alerts_include_sla_and_friday_payout():
    alerts = build_hub_alerts(sla_overdue_count=2, payout_today=True, available_minor=800)
    ids = [a["id"] for a in alerts]
    assert ids == ["sla_overdue", "payout_today"]
    assert next(a["count"] for a in alerts if a["id"] == "sla_overdue") == 2


def test_hub_alerts_connector_offline_when_waiting():
    alerts = build_hub_alerts(session_wait_count=3, connector_online=False)
    assert alerts == [{"id": "connector_offline", "level": "warning", "count": 3}]
    assert build_hub_alerts(session_wait_count=3, connector_online=True) == []


def test_hub_alerts_hide_friday_payout_without_balance():
    alerts = build_hub_alerts(payout_today=True, available_minor=0)
    assert alerts == []


def test_hub_alerts_skip_ops_import_noise():
    alerts = build_hub_alerts(unclaimed_count=4, unmatched_count=2, isrc_blocked_count=3)
    assert alerts == []


def test_work_statement_window_empty_when_not_live():
    window = _work_statement_window([])
    assert window["waiting"] is False
    assert "expected_earliest" in window
    assert "expected_latest" in window
    assert window.get("mode") == "seat_harvest"


def test_work_statement_window_waits_until_harvest():
    from datetime import datetime

    live = SimpleNamespace(
        status="live",
        updated_at=datetime.utcnow(),
        store_url="https://music.163.com/#/song?id=123456",
        external_id=None,
        has_receipt=None,
    )
    assert _work_statement_window([live], has_harvest=False)["waiting"] is True
    assert _work_statement_window([live], has_harvest=True)["waiting"] is False


def test_work_statement_window_ignores_live_without_receipt():
    from datetime import datetime

    no_receipt = SimpleNamespace(
        status="live",
        updated_at=datetime.utcnow(),
        store_url=None,
        external_id=None,
        has_receipt=None,
    )
    assert _work_statement_window([no_receipt], has_harvest=False)["waiting"] is False


def test_hub_connector_next_action_mirrors_extension():
    assert hub_connector_next_action({"last_delivery": {"status": "needs_challenge"}}) == "needs_challenge"
    assert hub_connector_next_action({"last_delivery": {"event": "assisting"}}) == "assisting"
    assert hub_connector_next_action({}, session_wait_count=2) == "session_wait"
    assert hub_connector_next_action({}, upload_wait_count=1) == "needs_upload"
    assert hub_connector_next_action({"last_delivery": {"status": "live"}}) == "live"


def test_work_next_action_path():
    assert work_next_action(has_active_release=False, delivering=False, live=False, has_real=False, has_available=False) == "release"
    assert work_next_action(has_active_release=True, delivering=True, live=False, has_real=False, has_available=False) == "stores"
    assert work_next_action(has_active_release=True, delivering=False, live=False, has_real=False, has_available=False) == "stores"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=False, has_available=False) == "sync"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=False, has_available=False, label=False) == "sync"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=True, has_available=True) == "wallet"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=True, has_available=False) == "sync"
    assert work_next_action(has_active_release=True, delivering=True, live=False, has_real=False, has_available=False, unmatched_count=3) == "stores"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=False, has_available=False, unmatched_count=2) == "sync"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=False, has_available=False, needs_store_action=True) == "stores"
    assert work_next_action(has_active_release=True, delivering=True, live=True, has_real=True, has_available=True, sync_open=True) == "wallet"


def test_harvest_health_unmatched_is_attach():
    health = harvest_health(
        connections=[{"status": "settle"}],
        unmatched_count=3,
        pending_minor=0,
        available_minor=0,
    )
    assert health["state"] == "unmatched"
    assert health["cta"] == "attach"
    assert health["zero_rows_success"] is False


def test_harvest_health_draft_waits_for_ops_before_another_copy():
    waiting = harvest_health(
        connections=[{"status": "settle"}],
        pending_confirm_count=2,
        available_minor=0,
        pending_minor=0,
    )
    assert waiting["state"] == "draft"
    assert waiting["cta"] == "settlements"
    paid = harvest_health(
        connections=[{"status": "settle"}],
        pending_confirm_count=2,
        available_minor=100,
    )
    assert paid["state"] == "withdrawable"
    assert paid["cta"] == "wallet"


def test_harvest_health_never_succeeds_on_zero_rows():
    health = harvest_health(connections=[], unmatched_count=0, available_minor=0, pending_minor=0)
    assert health["state"] == "idle"
    assert health["farm_ok"] is False
    assert health["zero_rows_success"] is False


def test_money_timeline_stages():
    empty = money_timeline(live=False, revenue_minor=0, settlement_lines=[], paid=False)
    assert [s["id"] for s in empty["stages"]] == ["live", "amount", "commission", "withdrawable", "paid"]
    assert empty["stages"][0]["done"] is False
    assert empty["display_only_prediction"] is True
    filled = money_timeline(
        live=True,
        revenue_minor=800,
        settlement_lines=[{"gross_minor": 800, "commission_minor": 80, "commission_rate": 10, "withdrawable": True}],
        predicted={"low_minor": 100, "high_minor": 200},
        paid=False,
    )
    assert filled["stages"][0]["done"] is True
    assert filled["stages"][1]["done"] is True
    assert filled["stages"][2]["done"] is True
    assert filled["stages"][3]["done"] is True
    assert filled["stages"][4]["done"] is False
    assert filled["predicted"]["low_minor"] == 100
    assert filled["sources"]["dsp_minor"] == 800
    empty_sources = money_timeline(
        live=True,
        revenue_minor=0,
        settlement_lines=[{"source": "first_party_radio", "net_minor": 40, "gross_minor": 40}],
        warmup_minor=40,
    )
    assert empty_sources["sources"]["radio_minor"] == 40
    assert empty_sources["sources"]["dsp_minor"] == 0


def test_label_statement_excludes_radio_warmup():
    radio = SimpleNamespace(usable_for_settlement=True, source="first_party_radio")
    official = SimpleNamespace(usable_for_settlement=True, source="distributor_export")
    display = SimpleNamespace(usable_for_settlement=False, source="ops_connector")
    assert _is_label_statement(radio) is False
    assert _is_label_statement(official) is True
    assert _is_label_statement(display) is False
    assert _is_label_statement(SimpleNamespace(usable_for_settlement=True, source="ops_connector")) is True
    assert _is_label_statement(SimpleNamespace(usable_for_settlement=True, source="user_export")) is True
    assert accounting_subject("ops_connector") == SUBJECT_HARVEST
    assert accounting_subject("user_connector") == SUBJECT_HARVEST


def test_accumulate_keeps_radio_out_of_headline():
    ch = _empty_channel("spotify")
    _accumulate(
        ch,
        SimpleNamespace(
            usable_for_settlement=True,
            source="first_party_radio",
            streams=40,
            revenue_minor=80,
        ),
        in_period=True,
        work_level=set(),
    )
    assert ch["streams"] == 0
    assert ch["revenue_minor"] == 0
    assert ch["has_real"] is False
    assert ch["warmup_revenue_minor"] == 80
    _accumulate(
        ch,
        SimpleNamespace(
            usable_for_settlement=True,
            source="distributor_export",
            streams=12,
            revenue_minor=500,
        ),
        in_period=True,
        work_level=set(),
    )
    assert ch["streams"] == 12
    assert ch["revenue_minor"] == 500
    assert ch["label_revenue_minor"] == 500
    assert ch["has_real"] is True
    assert ch["warmup_revenue_minor"] == 80


def test_accumulate_skips_official_when_harvest_wins():
    official = SimpleNamespace(
        usable_for_settlement=True,
        source="distributor_export",
        streams=99,
        revenue_minor=9000,
    )
    harvest = SimpleNamespace(
        usable_for_settlement=True,
        source="seat_harvest",
        streams=12,
        revenue_minor=800,
    )
    ch = _empty_channel("netease")
    winners = [harvest]
    _accumulate(ch, official, in_period=True, work_level=set(), settlement_winners=winners)
    _accumulate(ch, harvest, in_period=True, work_level=set(), settlement_winners=winners)
    assert ch["revenue_minor"] == 800
    assert ch["streams"] == 12
    assert ch["label_revenue_minor"] == 800
