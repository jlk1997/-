from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.distribution.service import _claim_state
from app.services.royalty.priority import filter_settlement_snapshots, official_covers


def test_money_bucket_puts_harvest_on_dsp_path():
    from app.services.royalty.subjects import AUTO_CONFIRM_SOURCES, money_bucket

    assert money_bucket("seat_harvest") == "dsp"
    assert money_bucket("farm_harvest") == "dsp"
    assert money_bucket("user_connector") == "dsp"
    assert money_bucket("ops_connector") == "dsp"
    assert money_bucket("distributor_export") == "dsp"
    assert money_bucket("first_party_radio") == "radio"
    assert money_bucket("sync_license") == "sync"
    assert money_bucket("first_party_embed") == "embed"
    assert "seat_harvest" in AUTO_CONFIRM_SOURCES
    assert "user_connector" not in AUTO_CONFIRM_SOURCES
    assert "ops_connector" not in AUTO_CONFIRM_SOURCES


def test_official_covers_requires_usable_or_revenue():
    assert official_covers(SimpleNamespace(source="distributor_export", usable_for_settlement=True, revenue_minor=0))
    assert official_covers(SimpleNamespace(source="official_api", usable_for_settlement=False, revenue_minor=250))
    assert not official_covers(SimpleNamespace(source="official_api", usable_for_settlement=False, revenue_minor=0))
    assert not official_covers(SimpleNamespace(source="ops_connector", usable_for_settlement=True, revenue_minor=800))


def test_filter_prefers_harvest_over_official_same_key():
    official = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=1000,
    )
    harvest = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="seat_harvest",
        usable_for_settlement=True,
        revenue_minor=800,
        raw={"confidence": 0.95},
    )
    other = SimpleNamespace(
        user_id="u",
        work_id="w2",
        channel_code="netease",
        period_key="2026-08",
        source="ops_connector",
        usable_for_settlement=True,
        revenue_minor=500,
    )
    zero = SimpleNamespace(
        user_id="u",
        work_id="w3",
        channel_code="spotify",
        period_key="2026-08",
        source="official_api",
        usable_for_settlement=True,
        revenue_minor=0,
    )
    out = filter_settlement_snapshots([official, harvest, other, zero])
    assert harvest in out
    assert official not in out
    assert other in out
    assert zero not in out


def test_filter_harvest_beats_fatter_official():
    official = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=9000,
    )
    harvest = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="user_connector",
        usable_for_settlement=True,
        revenue_minor=100,
        raw={"confidence": 0.95},
    )
    assert filter_settlement_snapshots([official, harvest]) == [harvest]


def test_filter_official_csv_beats_dom_harvest():
    official = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=900,
        raw={"confidence": 0.95},
    )
    harvest = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="seat_harvest",
        usable_for_settlement=True,
        revenue_minor=1200,
        raw={"confidence": 0.75},
    )
    assert filter_settlement_snapshots([official, harvest]) == [official]


def test_filter_keeps_one_official_money_statement():
    export = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=1000,
    )
    api = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="official_api",
        usable_for_settlement=True,
        revenue_minor=200,
    )
    out = filter_settlement_snapshots([export, api])
    assert out == [export]


def test_filter_tie_breaks_to_higher_rank():
    export = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="distributor_export",
        usable_for_settlement=True,
        revenue_minor=500,
    )
    api = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="spotify",
        period_key="2026-08",
        source="official_api",
        usable_for_settlement=True,
        revenue_minor=500,
    )
    out = filter_settlement_snapshots([export, api])
    assert out == [api]


def test_filter_never_settles_connector_only():
    connector = SimpleNamespace(
        user_id="u",
        work_id="w",
        channel_code="netease",
        period_key="2026-08",
        source="ops_connector",
        usable_for_settlement=True,
        revenue_minor=800,
    )
    assert filter_settlement_snapshots([connector]) == [connector]


def test_claim_state_expires_after_ttl():
    assert _claim_state({})["claim_active"] is False
    stale = {
        "claimed_by": "admin-1",
        "claimed_email": "ops@test.local",
        "claimed_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
    }
    assert _claim_state(stale)["claim_active"] is False
    fresh = {
        "claimed_by": "admin-1",
        "claimed_email": "ops@test.local",
        "claimed_at": datetime.utcnow().isoformat(),
    }
    state = _claim_state(fresh)
    assert state["claim_active"] is True
    assert state["claimed_email"] == "ops@test.local"
