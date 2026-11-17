from types import SimpleNamespace

from app.services.distribution.adapters import DistroKidAdapter, TuneCoreAdapter, RouteNoteAdapter, DistributorAdapter
from app.services.distribution.reject import humanize_reject
from app.services.royalty.priority import should_promote_connector


def test_partner_submit_without_endpoint_goes_to_ops_queue(monkeypatch):
    monkeypatch.setattr("app.services.distribution.adapters.settings", SimpleNamespace(distrokid_api_key="k", distrokid_api_base=""))
    result = DistroKidAdapter().submit({"channel": "spotify"})
    assert result.ok is True
    assert result.status == "ops_queue"
    assert result.kit_required is True
    assert "不是故障" in (result.message or "")
    note = humanize_reject(result.message, status=result.status)
    assert note["code"] == "ops_queue"
    cover = humanize_reject("Cover artwork missing")
    assert cover["code"] == "cover"
    assert cover["next"] == "补封面"


def test_partner_submit_posts_to_configured_base(monkeypatch):
    monkeypatch.setattr(
        "app.services.distribution.adapters.settings",
        SimpleNamespace(distrokid_api_key="k", distrokid_api_base="https://partner.example"),
    )

    class FakeResp:
        status_code = 200
        content = b'{"status":"in_review","external_id":"dk_1"}'
        text = '{"status":"in_review","external_id":"dk_1"}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "in_review", "external_id": "dk_1"}

    monkeypatch.setattr("app.services.distribution.adapters.httpx.post", lambda *args, **kwargs: FakeResp())
    result = DistroKidAdapter().submit({"channel": "spotify"})
    assert result.ok is True
    assert result.status == "in_review"
    assert result.external_id == "dk_1"
    assert result.kit_required is False


def test_should_promote_connector_blocks_when_official_covers():
    official = SimpleNamespace(source="distributor_export", usable_for_settlement=True, revenue_minor=10)
    assert should_promote_connector([]) is True
    assert should_promote_connector([official]) is False


def test_query_status_maps_store_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.distribution.adapters.settings",
        SimpleNamespace(distrokid_api_key="k", distrokid_api_base="https://partner.example"),
    )

    class FakeResp:
        status_code = 200
        content = b'{"status":"live","external_id":"dk_1","store_url":"https://open.spotify.com/track/x"}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "live", "external_id": "dk_1", "store_url": "https://open.spotify.com/track/x"}

    monkeypatch.setattr("app.services.distribution.adapters.httpx.get", lambda *args, **kwargs: FakeResp())
    result = DistroKidAdapter().query_status("dk_1")
    assert result.ok is True
    assert result.status == "live"
    assert result.store_url == "https://open.spotify.com/track/x"


def test_distrokid_build_payload_structure():
    adapter = DistroKidAdapter()
    release = {"upc": "123456789012", "release_date": "2026-09-01", "territories": ["US", "CN"]}
    delivery = {"id": "del_1", "track_code": "ISRC001"}
    work = {
        "title": "Night Drive",
        "artist_name": "TestArtist",
        "isrc": "ISRC002",
        "audio_url": "https://cdn.example/audio.mp3",
        "cover_url": "https://cdn.example/cover.jpg",
        "genres": ["Electronic", "Ambient"],
        "language": "zh",
        "duration_ms": 240000,
        "explicit": False,
    }
    result = adapter.build_payload(release, delivery, work)
    assert result["provider"] == "distrokid"
    assert result["album"]["title"] == "Night Drive"
    assert result["album"]["artist"] == "TestArtist"
    assert result["album"]["isrc"] == "ISRC002"
    assert result["album"]["upc"] == "123456789012"
    assert result["album"]["genre"] == "Electronic"
    assert result["album"]["subgenre"] == "Ambient"
    assert result["tracks"][0]["audio_url"] == "https://cdn.example/audio.mp3"
    assert result["tracks"][0]["duration_ms"] == 240000
    assert result["delivery_id"] == "del_1"
    assert len(result["tracks"]) == 1
    assert "stems" not in result
    assert "originality" not in result


def test_distrokid_prefers_master_wav_and_ignores_stems():
    adapter = DistroKidAdapter()
    work = {
        "title": "Night Drive",
        "artist_name": "A",
        "audio_url": "https://cdn.example/audio.mp3",
        "master_wav_url": "https://cdn.example/master.wav",
        "stems": {"vocal": "https://cdn.example/vocal.wav"},
        "originality_zip_url": "https://cdn.example/o.zip",
        "ai_generated": True,
        "ai_disclosed": True,
        "sku_kind": "instrumental",
        "genres": ["Electronic"],
    }
    result = adapter.build_payload({}, {"id": "d1"}, work)
    assert len(result["tracks"]) == 1
    assert result["tracks"][0]["audio_url"] == "https://cdn.example/master.wav"
    assert result["tracks"][0]["instrumental"] is True
    assert result["ai_generated"] is True
    assert result["ai_disclosed"] is True
    assert "stems" not in result
    assert "originality_zip_url" not in result


def test_distrokid_nested_submit_one_track(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.services.distribution.adapters.settings",
        SimpleNamespace(distrokid_api_key="k", distrokid_api_base="https://partner.example"),
    )

    class FakeResp:
        status_code = 200
        content = b'{"status":"in_review","external_id":"dk_1"}'
        text = ""

        def json(self):
            return {"status": "in_review", "external_id": "dk_1"}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs.get("json")
        return FakeResp()

    monkeypatch.setattr("app.services.distribution.adapters.httpx.post", fake_post)
    result = DistroKidAdapter().submit(
        {
            "release": {"upc": "1"},
            "delivery": {"id": "d1"},
            "work": {"title": "T", "audio_url": "http://a", "stems": {"vocal": "http://v"}},
        }
    )
    assert result.ok is True
    body = captured["json"]
    assert len(body["tracks"]) == 1
    assert "stems" not in body


def test_base_adapter_build_payload_generic():
    adapter = DistributorAdapter()
    work = {"title": "Song", "artist_name": "Art", "genres": ["Pop"]}
    result = adapter.build_payload({}, {}, work)
    assert result["title"] == "Song"
    assert result["artist_name"] == "Art"
    assert result["genres"] == ["Pop"]
    assert result["territories"] == ["worldwide"]


def test_routenote_build_payload_has_release_and_track():
    adapter = RouteNoteAdapter()
    result = adapter.build_payload(
        {"upc": "UPC1"}, {"track_code": "TC1"}, {"title": "T", "artist_name": "A", "genres": ["Rock"]}
    )
    assert "release" in result
    assert "track" in result
    assert result["track"]["isrc"] == "TC1"
    assert result["release"]["upc"] == "UPC1"


def test_partner_stub_polls_to_live(monkeypatch):
    from app.api.routes import partner_stub

    partner_stub._STORE.clear()
    monkeypatch.setattr(
        "app.api.routes.partner_stub.settings",
        SimpleNamespace(debug=True, partner_stub_enabled=True, distrokid_api_key="dev", tunecore_api_key="", routenote_api_key="", cn_label_api_key=""),
    )
    created = partner_stub.create_delivery(partner_stub.DeliveryIn(channel="spotify"), authorization="Bearer dev")
    assert created["status"] == "in_review"
    external_id = created["external_id"]
    polled = partner_stub.get_delivery(external_id, authorization="Bearer dev")
    assert polled["status"] == "live"
    assert polled["store_url"] == f"https://example.com/stub/{external_id}"


def test_webhook_empty_secret_fails_outside_debug(monkeypatch):
    from app.services.distribution import adapters as adapters_mod

    monkeypatch.setattr(adapters_mod.settings, "partner_webhook_secret", "", raising=False)
    monkeypatch.setattr(adapters_mod.settings, "debug", False, raising=False)
    assert DistroKidAdapter().verify_webhook_signature(b"{}", "sig") is False
    monkeypatch.setattr(adapters_mod.settings, "debug", True, raising=False)
    assert DistroKidAdapter().verify_webhook_signature(b"{}", "sig") is True
