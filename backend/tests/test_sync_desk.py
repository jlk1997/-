from types import SimpleNamespace

from app.services.embed_engagement import is_certified, visitor_key
from app.services.royalty.ingest import _norm_title
from app.services.royalty.sync_desk import (
    DEFAULT_TIERS,
    PLATFORM_RATE,
    SYNC_TIERS,
    _quote,
    ensure_default_sync_listing,
    listing_enabled,
    list_tiers,
)


def test_sync_tiers_cover_plan_uses():
    ids = {row["id"] for row in list_tiers()}
    assert {"personal", "short_video", "ads", "game", "film"} <= ids
    quote = _quote("short_video")
    assert quote["gross_minor"] == SYNC_TIERS["short_video"]["fiat_minor"]
    assert quote["platform_minor"] == int(round(quote["gross_minor"] * PLATFORM_RATE))
    assert quote["seller_minor"] + quote["parent_minor"] + quote["platform_minor"] == quote["gross_minor"]


def test_trial_end_does_not_auto_list_without_qc():
    work = SimpleNamespace(
        release_status="draft",
        post_process_status={"radio_trial": {"status": "ended"}},
        commercial_cleared_at=None,
    )
    assert ensure_default_sync_listing(work) is None
    assert listing_enabled(work) is False


def test_default_listing_opens_after_qc():
    work = SimpleNamespace(release_status="qc_ready", post_process_status={}, commercial_cleared_at=None)
    payload = ensure_default_sync_listing(work)
    assert payload["enabled"] is True
    assert list(payload["tiers"]) == list(DEFAULT_TIERS)
    assert listing_enabled(work) is True
    again = ensure_default_sync_listing(work)
    assert again["enabled"] is True


def test_norm_title_fuzzy():
    assert _norm_title("Night Drive!") == _norm_title("night-drive")
    assert len(_norm_title("Hi")) < 4


def test_listing_rights_certificate_is_non_exclusive():
    from app.services.royalty.sync_desk import rights_certificate_for_work, serialize_listing

    work = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        title="Night",
        cover_url=None,
        audio_url="/a.mp3",
        owner_id="u1",
        commercial_cleared_at=None,
        is_ai_generated=True,
        post_process_status={"sync_listing": {"enabled": True, "tiers": ["personal"]}, "c2pa_done": True},
    )
    row = serialize_listing(work)
    assert row["from_workbench"] is False
    cert = row["rights_certificate"]
    assert cert["exclusive"] is False
    assert cert["non_exclusive"] is True
    assert cert["ai_disclosed"] is True
    # A sidecar manifest is not an embedded credential, so the buyer-facing stamp stays off.
    assert cert["c2pa_verified"] is False
    assert cert["c2pa_state"] == "sidecar"
    assert rights_certificate_for_work(work)["exclusive"] is False

    work.post_process_status = {**work.post_process_status, "c2pa_embedded": True}
    embedded = serialize_listing(work)["rights_certificate"]
    assert embedded["c2pa_verified"] is True
    assert embedded["c2pa_state"] == "embedded"


def test_embed_visitor_and_certify():
    user = SimpleNamespace(id="u1")
    assert visitor_key(user=user, visitor="x", host="h").startswith("user:")
    assert visitor_key(user=None, visitor="abc", host=None) == visitor_key(user=None, visitor="abc", host="other")
    assert is_certified(user) is True
    assert is_certified(None) is False
