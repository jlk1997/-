from app.services.royalty.ingest import parse_report_csv, revenue_to_minor, settlement_row_usable
from app.services.distribution.catalog import SETTLEMENT_SOURCES, normalize_store
from app.services.royalty.settlement import commission_rate, pick_commission_rate, split_amounts
from app.services.distribution.service import user_delivery_status


def test_parse_distrokid_like_csv():
    raw = (
        "ISRC,Title,Store,Streams,Revenue,Currency,Period\n"
        "US-XXX-00-00001,Night Drive,Spotify,1200,12.50,USD,2026-08\n"
        "US-XXX-00-00001,Night Drive,Apple Music,800,9.20,USD,2026-08\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert len(rows) == 2
    assert rows[0]["channel_code"] == "spotify"
    assert rows[0]["streams"] == 1200
    assert rows[0]["revenue_minor"] == 1250
    assert rows[1]["channel_code"] == "apple_music"


def test_parse_distrokid_sales_headers():
    raw = (
        "Sale Month,Store,Title,ISRC,Quantity,Earnings (USD)\n"
        "2026-08,Spotify,Night Drive,USXXX0000001,1500,18.40\n"
        "2026-08,iTunes,Night Drive,USXXX0000001,90,3.10\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert rows[0]["channel_code"] == "spotify"
    assert rows[0]["streams"] == 1500
    assert rows[0]["revenue_minor"] == 1840
    assert rows[1]["channel_code"] == "apple_music"


def test_parse_cn_label_headers_and_preamble():
    raw = (
        "导出说明,请勿修改表头\n"
        "平台,曲名,ISRC,播放量,收益,币种,账期\n"
        "网易云音乐,夜车,CN-Z11-26-00001,880,6.20,CNY,2026-08\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert len(rows) == 1
    assert rows[0]["channel_code"] == "netease"
    assert rows[0]["streams"] == 880
    assert rows[0]["revenue_minor"] == 620


def test_parse_rejects_unknown_headers():
    try:
        parse_report_csv(b"foo,bar\n1,2\n")
        assert False, "should raise"
    except ValueError:
        pass


def test_settlement_sources_never_include_sandbox():
    assert "sandbox" not in SETTLEMENT_SOURCES
    assert "ops_connector" in SETTLEMENT_SOURCES
    assert "official_api" in SETTLEMENT_SOURCES
    assert "user_connector" in SETTLEMENT_SOURCES
    assert "first_party_radio" not in SETTLEMENT_SOURCES
    assert settlement_row_usable(source="ops_connector", release=None, match_kind="isrc") is True
    assert settlement_row_usable(source="user_connector", release=None, match_kind="isrc") is True
    assert normalize_store("网易云音乐") == "netease"
    assert normalize_store("iTunes") == "apple_music"
    assert normalize_store("Tencent Music") == "qq_music"
    assert user_delivery_status("ops_queue") == "ops_handling"
    assert user_delivery_status("awaiting_manual") == "needs_upload"
    assert user_delivery_status("session_wait") == "waiting_login"
    assert user_delivery_status("session_wait", "farm_or_extension_lease_wait") == "assisting"
    assert user_delivery_status("session_wait", "needs_challenge") == "needs_challenge"
    assert user_delivery_status("needs_challenge") == "needs_challenge"
    assert user_delivery_status("session_running") == "assisting"
    assert user_delivery_status("submitting") == "publishing"
    assert user_delivery_status("in_review") == "in_review"
    assert user_delivery_status("live") == "live"
    assert user_delivery_status("live", has_receipt=False) == "publishing"
    assert user_delivery_status("live", has_receipt=True) == "live"


def test_parse_tunecore_semicolon():
    raw = (
        "Posted Date;Store Name;Song Title;ISRC;Quantity;Net Earnings;Currency\n"
        "2026-08-01;YouTube Music;Night Drive;USXXX0000001;400;2.20;USD\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert rows[0]["channel_code"] == "youtube_music"
    assert rows[0]["streams"] == 400
    assert rows[0]["revenue_minor"] == 220


def test_release_metadata_fallback_never_none():
    from types import SimpleNamespace
    from app.services.distribution.service import _release_metadata_payload

    class _Q:
        def filter(self, *_a, **_k):
            return self

        def first(self):
            return SimpleNamespace(title="Night Drive", isrc=None, cover_url="https://x/c.png", lyrics=None)

    class _Db:
        def query(self, *_a, **_k):
            return _Q()

    release = SimpleNamespace(work_id="w1")
    payload = _release_metadata_payload(_Db(), release, None)
    assert payload["title"] == "Night Drive"
    assert payload["cover_url"] == "https://x/c.png"
    assert payload["language"] == "zh"


def test_parse_spotify_for_artists_without_store():
    raw = (
        "Song Name,ISRC,Streams,Listeners,Spotify URI\n"
        "Night Drive,USXXX0000001,2400,180,spotify:track:abc\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert rows[0]["channel_code"] == "spotify"
    assert rows[0]["streams"] == 2400
    assert rows[0]["saves"] == 180


def test_parse_youtube_studio_views():
    raw = (
        "Video title,Views\n"
        "Night Drive (Official),3200\n"
    ).encode()
    rows = parse_report_csv(raw)
    assert rows[0]["channel_code"] == "youtube_music"
    assert rows[0]["streams"] == 3200
    assert rows[0]["title"] == "Night Drive (Official)"


def test_bounds_for_period_key_uses_csv_month():
    from datetime import date
    from app.services.royalty.settlement import bounds_for_period_key

    start, end = bounds_for_period_key("2026-07", date(2026, 8, 1), date(2026, 8, 31))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_summarize_unsettled_periods_groups_revenue():
    from types import SimpleNamespace
    from app.services.royalty.settlement import summarize_unsettled_periods

    rows = summarize_unsettled_periods(
        [
            SimpleNamespace(period_key="2026-07", revenue_minor=500),
            SimpleNamespace(period_key="2026-07", revenue_minor=200),
            SimpleNamespace(period_key="2026-08", revenue_minor=100),
        ]
    )
    july = next(item for item in rows if item["period_key"] == "2026-07")
    assert july["count"] == 2
    assert july["revenue_minor"] == 700


def test_revenue_to_minor_keeps_large_integers():
    assert revenue_to_minor(12.5, "12.50") == 1250
    assert revenue_to_minor(1840, "1840") == 1840
    assert revenue_to_minor(18, "18") == 1800
    assert revenue_to_minor(0.5, "0.50") == 50


def test_youtube_skips_channel_when_videos_matched():
    from app.services.royalty.youtube import should_write_channel_snapshot

    assert should_write_channel_snapshot(9000, []) is True
    assert should_write_channel_snapshot(9000, [0, 0]) is True
    assert should_write_channel_snapshot(9000, [3200]) is False
    assert should_write_channel_snapshot(0, []) is False


def test_statement_source_split_separates_embed():
    from app.services.royalty.settlement import _statement_source_split

    split = _statement_source_split(
        [
            {
                "lines": [
                    {"source": "first_party_radio", "net_minor": 3},
                    {"source": "sync_license", "net_minor": 80},
                    {"source": "first_party_embed", "net_minor": 5},
                    {"source": "distributor_export", "net_minor": 20},
                    {"source": "seat_harvest", "net_minor": 64},
                ]
            }
        ]
    )
    assert split["radio_minor"] == 3
    assert split["sync_minor"] == 80
    assert split["embed_minor"] == 5
    assert split["dsp_minor"] == 84
    assert split["harvest_minor"] == 64
    assert split["net_minor"] == 172


def test_hub_skips_channel_level_display_when_work_level_exists():
    from types import SimpleNamespace
    from app.api.routes.creator import display_work_level_keys, include_display_snapshot

    snaps = [
        SimpleNamespace(work_id=None, usable_for_settlement=False, channel_code="youtube_music", source="official_api", period_key="latest"),
        SimpleNamespace(work_id="w1", usable_for_settlement=False, channel_code="youtube_music", source="official_api", period_key="latest"),
    ]
    keys = display_work_level_keys(snaps)
    assert include_display_snapshot(snaps[0], keys) is False
    assert include_display_snapshot(snaps[1], keys) is True


def test_youtube_title_and_url_match():
    from types import SimpleNamespace
    from app.services.royalty.youtube import extract_youtube_id, match_work_by_title

    works = [SimpleNamespace(title="Night Drive"), SimpleNamespace(title="Other")]
    assert match_work_by_title("Night Drive (Official Audio)", works).title == "Night Drive"
    assert extract_youtube_id("https://youtu.be/abc123xyz") == "abc123xyz"
    assert extract_youtube_id("https://www.youtube.com/watch?v=abc123xyz&t=3") == "abc123xyz"


def test_youtube_oauth_state_roundtrip():
    from app.services.royalty.youtube import _read_state, _sign_state

    uid = "11111111-1111-1111-1111-111111111111"
    assert _read_state(_sign_state(uid)) == uid


def test_fresh_kit_url_falls_back_without_storage_key():
    from types import SimpleNamespace
    from app.services.distribution.service import _fresh_kit_url

    release = SimpleNamespace(kit_storage_key=None, kit_url="https://cdn.example/kit.zip")
    assert _fresh_kit_url(release) == "https://cdn.example/kit.zip"


def test_split_and_pick_commission_rate():
    assert split_amounts(1000, 30) == (300, 700)
    assert split_amounts(333, 30) == (100, 233)
    assert split_amounts(0, 20) == (0, 0)
    assert split_amounts(50, 200) == (50, 0)
    assert pick_commission_rate(30, 20) == 30
    assert pick_commission_rate(15, 10) == 10
    assert pick_commission_rate(None, None) == 20


def test_confirmable_status_and_statement_csv():
    from app.services.royalty.settlement import confirmable_status, line_dedupe_key, render_statement_csv

    assert confirmable_status("draft") == "ok"
    assert confirmable_status("confirmed") == "already"
    assert confirmable_status("voided") == "blocked"
    assert line_dedupe_key("u1", None, "spotify") == ("u1", "", "spotify")
    csv_text = render_statement_csv(
        [
            {
                "period_key": "2026-08",
                "status": "confirmed",
                "lines": [
                    {
                        "work_title": "Night Drive",
                        "channel_code": "spotify",
                        "source": "distributor_export",
                        "commission_rate": 20,
                        "currency": "USD",
                        "gross_minor": 1000,
                        "commission_minor": 200,
                        "net_minor": 800,
                    }
                ],
            }
        ]
    )
    assert "Night Drive" in csv_text
    assert "spotify" in csv_text
    assert "800" in csv_text


def test_official_settlement_requires_isrc_match():
    from types import SimpleNamespace
    from app.services.royalty.ingest import settlement_row_usable
    from app.services.royalty.priority import filter_settlement_snapshots

    label = SimpleNamespace(mode="label")
    self_rel = SimpleNamespace(mode="self_release")
    assert settlement_row_usable(source="distributor_export", release=label, match_kind="isrc") is True
    assert settlement_row_usable(source="distributor_export", release=label, match_kind="title") is False
    assert settlement_row_usable(source="distributor_export", release=label, match_kind="") is False
    assert settlement_row_usable(source="user_export", release=label, match_kind="title") is False
    assert settlement_row_usable(source="user_connector", release=label, match_kind="isrc") is True
    assert settlement_row_usable(source="distributor_export", release=self_rel, match_kind="isrc") is False
    assert settlement_row_usable(source="first_party_radio", release=None, match_kind="") is False

    usable = SimpleNamespace(
        user_id="u1",
        work_id="w1",
        channel_code="spotify",
        period_key="2026-08",
        source="distributor_export",
        revenue_minor=500,
        usable_for_settlement=True,
    )
    title_only = SimpleNamespace(
        user_id="u1",
        work_id="w1",
        channel_code="spotify",
        period_key="2026-08",
        source="distributor_export",
        revenue_minor=800,
        usable_for_settlement=False,
    )
    chosen = filter_settlement_snapshots([usable, title_only])
    assert chosen == [usable]


def test_allowed_label_rates_floor_standard():
    from types import SimpleNamespace
    from app.services.royalty.settlement import allowed_label_rates

    class _Q:
        def filter(self, *_a, **_k):
            return self

        def all(self):
            return []

    class _Db:
        def query(self, *_a, **_k):
            return _Q()

    assert allowed_label_rates(_Db(), SimpleNamespace(creator_level="standard")) == [20, 30]


def test_partner_payee_unconfigured_uses_ops_csv():
    from app.services.distribution.catalog import partner_payee_status

    status = partner_payee_status()
    assert status["partners"]
    for row in status["partners"]:
        if row.get("configured"):
            assert row["settlement_path"] == "partner_api"
        else:
            assert row["settlement_path"] == "ops_csv"


def test_append_delivery_event_shows_on_serialize():
    from datetime import datetime
    from types import SimpleNamespace
    from app.services.distribution.service import serialize_delivery
    from app.services.distribution.submit_log import append_delivery_event

    delivery = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        release_id="22222222-2222-2222-2222-222222222222",
        work_id="33333333-3333-3333-3333-333333333333",
        channel_code="spotify",
        distributor_code="distrokid",
        status="ops_queue",
        reject_reason=None,
        external_id=None,
        store_url=None,
        retry_count=0,
        last_error=None,
        last_attempt_at=None,
        next_retry_at=None,
        updated_at=None,
        created_at=datetime.utcnow(),
        attempt_meta={},
    )
    append_delivery_event(delivery, event="platform_submit", actor="platform", message="平台主体交歌")
    payload = serialize_delivery(delivery)
    assert payload["submissions"]
    assert payload["submissions"][0]["event"] == "platform_submit"
    assert payload["submissions"][0]["ticket_id"] == str(delivery.id)


def test_expected_statement_window_is_t45_t90():
    from datetime import date
    from app.services.royalty.payout_calendar import expected_harvest_window, expected_statement_window

    window = expected_statement_window(date(2026, 8, 1), today=date(2026, 8, 20))
    assert window["earliest"] == "2026-09-15"
    assert window["latest"] == "2026-10-30"
    assert window["waiting"] is True
    harvest = expected_harvest_window(today=date(2026, 8, 21))
    assert harvest["earliest"] == "2026-08-21"
    assert harvest["latest"] == "2026-08-22"
    assert harvest["mode"] == "seat_harvest"
    assert harvest["waiting"] is False


def test_commission_rate_defaults(db):
    from app.services.distribution.catalog import seed_distribution_catalog

    seed_distribution_catalog(db)
    db.commit()
    assert commission_rate(db, mode="label", channel_code="spotify", user_level="standard") == 20
    assert commission_rate(db, mode="label", channel_code="spotify", user_level="pro") == 10
    assert commission_rate(db, mode="self_release", channel_code="spotify", user_level="standard") == 10
