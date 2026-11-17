from datetime import datetime, timedelta
from types import SimpleNamespace
import io
import json
import zipfile

from app.services.distribution.adapters import AdapterResult, DistributorAdapter
from fastapi import HTTPException

from app.services.distribution.catalog import CHANNEL_SPECS, all_channel_codes, channel_upload_url, default_volume_channels
from app.services.distribution.service import normalize_store_url
from app.services.distribution.pipeline import adapter_submit_safe, apply_query_result, backoff_delta, delivery_progress, replay_plan


def test_store_url_and_channel_portals():
    assert normalize_store_url("https://open.spotify.com/track/x") == "https://open.spotify.com/track/x"
    try:
        normalize_store_url("not-a-url")
        assert False
    except HTTPException as exc:
        assert exc.status_code == 400
    assert all(channel_upload_url(spec["code"]) for spec in CHANNEL_SPECS)


def test_backoff_grows_and_caps():
    assert backoff_delta(1).total_seconds() == 30
    assert backoff_delta(2).total_seconds() == 60
    assert backoff_delta(8).total_seconds() <= 3600
    assert backoff_delta(20).total_seconds() == 3600


def test_adapter_submit_safe_swallows_exception():
    class Boom(DistributorAdapter):
        provider = "boom"

        def submit(self, payload: dict) -> AdapterResult:
            raise RuntimeError("distributor down")

    from app.services.distribution import adapters

    adapters.ADAPTERS["boom"] = Boom()
    try:
        result = adapter_submit_safe("boom", {"channel": "netease"})
        assert result.ok is False
        assert "distributor down" in (result.message or "")
    finally:
        adapters.ADAPTERS.pop("boom", None)


def test_replay_plan_stale_forces_even_if_backoff_future():
    now = datetime(2026, 8, 19, 4, 0, 0)
    row = SimpleNamespace(
        next_retry_at=now + timedelta(hours=1),
        last_attempt_at=now - timedelta(minutes=3),
    )
    should, force = replay_plan(row, now)
    assert should is True
    assert force is True


def test_replay_plan_respects_fresh_backoff():
    now = datetime(2026, 8, 19, 4, 0, 0)
    row = SimpleNamespace(
        next_retry_at=now + timedelta(seconds=20),
        last_attempt_at=now,
    )
    should, force = replay_plan(row, now)
    assert should is False
    assert force is False


def test_replay_plan_due_without_force():
    now = datetime(2026, 8, 19, 4, 0, 0)
    row = SimpleNamespace(next_retry_at=now - timedelta(seconds=1), last_attempt_at=now - timedelta(seconds=10))
    should, force = replay_plan(row, now)
    assert should is True
    assert force is False


def test_apply_query_result_writes_store_url_and_live():
    delivery = SimpleNamespace(status="in_review", store_url=None, external_id="dk_1", channel_code="spotify")
    result = AdapterResult(
        ok=True,
        status="live",
        external_id="dk_1",
        store_url="https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
    )
    assert apply_query_result(delivery, result) is True
    assert delivery.status == "live"
    assert delivery.store_url == "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
    assert apply_query_result(delivery, result) is False


def test_apply_query_result_rejects_live_without_receipt():
    delivery = SimpleNamespace(status="in_review", store_url=None, external_id=None, channel_code="spotify")
    result = AdapterResult(ok=True, status="live")
    assert apply_query_result(delivery, result) is False
    assert delivery.status == "in_review"


def test_apply_query_result_extracts_store_id_from_url():
    delivery = SimpleNamespace(status="session_wait", store_url=None, external_id=None, channel_code="spotify")
    result = AdapterResult(ok=True, status="live", store_url="https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
    assert apply_query_result(delivery, result) is True
    assert delivery.status == "live"
    assert delivery.external_id == "4uLU6hMCjMI75M1A2tKUQC"


def test_delivery_progress_partial_live_and_all_rejected():
    live = SimpleNamespace(status="live", store_url=None, external_id="dk_1", channel_code="spotify")
    ghost = SimpleNamespace(status="live", store_url=None, external_id=None, channel_code="spotify")
    rejected = SimpleNamespace(status="rejected")
    publishing = SimpleNamespace(status="ops_queue")
    taken = SimpleNamespace(status="taken_down")
    mixed = delivery_progress([live, rejected])
    assert mixed["release_status"] == "live"
    assert mixed["live"] == 1
    assert mixed["can_takedown"] is True
    assert delivery_progress([ghost])["release_status"] == "delivering"
    assert delivery_progress([ghost])["live"] == 0
    assert delivery_progress([ghost])["publishing"] == 1
    assert delivery_progress([rejected, rejected])["release_status"] == "rejected"
    assert delivery_progress([publishing, live])["release_status"] == "delivering"
    assert delivery_progress([taken, taken])["release_status"] == "taken_down"
    assert delivery_progress([])["release_status"] is None


def test_extract_store_ref_and_channel_hosts():
    from app.services.distribution.catalog import channel_hosts, extract_store_ref, has_live_receipt

    assert extract_store_ref("https://music.163.com/song?id=88", "netease") == "88"
    assert extract_store_ref("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "spotify") == "4uLU6hMCjMI75M1A2tKUQC"
    assert extract_store_ref("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube_music") == "dQw4w9WgXcQ"
    assert extract_store_ref("https://music.apple.com/us/album/foo/1440870373?i=1440870380", "apple_music") == "1440870380"
    assert extract_store_ref("https://y.qq.com/n/ryqq/songDetail/001234abcd", "qq_music") == "001234abcd"
    assert extract_store_ref("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili") == "BV1xx411c7mD"
    assert has_live_receipt(store_url=None, external_id=None) is False
    assert has_live_receipt(external_id="dk_1") is True
    netease_hosts = channel_hosts("netease")
    spotify_hosts = channel_hosts("spotify")
    amazon_hosts = channel_hosts("amazon_music")
    assert "music.163.com" in netease_hosts
    assert "open.spotify.com" in spotify_hosts
    assert "music.amazon.com" in amazon_hosts
    assert "music.163.com" not in amazon_hosts
    assert "music.amazon.com" not in netease_hosts


def test_looks_like_store_page_rejects_portals():
    from app.services.distribution.catalog import looks_like_store_page, volume_rank

    assert looks_like_store_page("https://music.163.com/song?id=88", "netease") is True
    assert looks_like_store_page("https://music.163.com/st/musician", "netease") is False
    assert looks_like_store_page("https://artists.spotify.com/", "spotify") is False
    assert looks_like_store_page("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "spotify") is True
    assert looks_like_store_page("https://studio.youtube.com/", "youtube_music") is False
    assert looks_like_store_page("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube_music") is True
    assert looks_like_store_page("https://music.example/t", "spotify") is False
    from app.services.distribution.catalog import is_known_upload_portal

    assert is_known_upload_portal("https://artists.spotify.com/") is True
    assert is_known_upload_portal("https://y.qq.com/portal/") is True
    assert is_known_upload_portal("https://creator.douyin.com/") is True
    assert is_known_upload_portal("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC") is False
    assert looks_like_store_page("https://y.qq.com/portal/", "qq_music") is False
    assert looks_like_store_page("https://www.kugou.com/musician/", "kugou") is False
    assert volume_rank("netease") == 0
    assert volume_rank("unknown_store") == 99


def test_apply_query_result_ignores_upload_portal_url():
    delivery = SimpleNamespace(status="in_review", store_url=None, external_id="dk_1", channel_code="spotify")
    result = AdapterResult(ok=True, status="live", external_id="dk_1", store_url="https://artists.spotify.com/")
    assert apply_query_result(delivery, result) is True
    assert delivery.status == "live"
    assert delivery.store_url is None


def test_apply_query_result_ignores_junk_url_when_external_id():
    delivery = SimpleNamespace(status="in_review", store_url=None, external_id="dk_1", channel_code="spotify")
    result = AdapterResult(ok=True, status="live", external_id="dk_1", store_url="https://music.example/t")
    assert apply_query_result(delivery, result) is True
    assert delivery.status == "live"
    assert delivery.store_url is None


def test_catalog_covers_cn_and_global_one_click_channels():
    codes = set(all_channel_codes())
    assert {"netease", "qq_music", "kugou", "spotify", "apple_music"}.issubset(codes)
    assert all(spec["distributor_code"] for spec in CHANNEL_SPECS)
    volume = default_volume_channels()
    from app.services.distribution.catalog import DEFAULT_UPLOAD_CHANNELS, pick_configured_aggregator

    if not any(pick_configured_aggregator(code) for code in codes):
        assert volume == list(DEFAULT_UPLOAD_CHANNELS)
        assert "spotify" not in volume
    assert set(volume) <= codes
    filled = default_volume_channels(connected=["netease", "spotify", "wechat_channels"])
    assert filled == ["netease", "spotify", "wechat_channels"]


def test_kit_survives_broken_transcode(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-1"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None

    class Release:
        id = "rel-1"
        mode = "label"
        selected_channels = ["netease", "spotify"]

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ffmpeg missing")))
    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-1/kit.zip", "https://cdn/kit.zip")

    monkeypatch.setattr(
        kit_mod,
        "get_storage_service",
        lambda: SimpleNamespace(upload_bytes=_upload),
    )
    out = kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"not-really-audio")
    assert out["key"] == "releases/rel-1/kit.zip"
    assert out["bytes"] > 0
    import zipfile, io
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.read("README.txt").decode("utf-8")
    meta_csv = zipped.read("metadata.csv").decode("utf-8")
    assert "网易云音乐" in names
    assert "Channel SOP" in names
    assert "spotify" in names.lower()
    assert "cover_url" in meta_csv


def test_clip_pack_writes_windows_and_readme(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-clips"
        title = "Night Drive"
        duration = 120
        storage_key = None

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        captured["key"] = key
        return (key, "https://cdn/clips.zip")

    monkeypatch.setattr(kit_mod, "cut_audio_clip", lambda *args, **kwargs: b"clip-bytes")
    monkeypatch.setattr(
        kit_mod,
        "get_storage_service",
        lambda: SimpleNamespace(upload_bytes=_upload),
    )
    out = kit_mod.build_clip_pack(work=Work(), audio_bytes=b"fake-audio")
    assert out["key"].endswith("clip-pack.zip")
    assert out["bytes"] > 0
    import io
    import zipfile

    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.namelist()
    assert "README.txt" in names
    assert "clip_windows.json" in names
    assert any(name.startswith("clips/clip_") and name.endswith(".mp3") for name in names)
    readme = zipped.read("README.txt").decode("utf-8")
    assert "自己的账号" in readme
    assert "Display-only" in readme


def test_ensure_clip_pack_stamps_key(monkeypatch):
    from app.services.distribution import kit as kit_mod

    work = SimpleNamespace(id="w-clip", title="Night", duration=90, storage_key="works/w-clip/mix.mp3", post_process_status={})
    captured = {}

    def _upload(data, key, content_type):
        captured["key"] = key
        return (key, "https://cdn/clip-pack.zip")

    monkeypatch.setattr(kit_mod, "cut_audio_clip", lambda *args, **kwargs: b"clip-bytes")
    monkeypatch.setattr(
        kit_mod,
        "get_storage_service",
        lambda: SimpleNamespace(
            upload_bytes=_upload,
            get_object_bytes=lambda key: b"fake-audio" if key == "works/w-clip/mix.mp3" else (b"zip" if key == captured.get("key") else None),
        ),
    )
    data, url = kit_mod.ensure_work_clip_pack(work)
    assert data == b"zip"
    assert url == "https://cdn/clip-pack.zip"
    assert work.post_process_status["clips"]["clip_pack_key"].endswith("clip-pack.zip")


def test_kit_readme_separates_master_from_stems(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-1"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None
        audio_url = "http://x/a.mp3"
        storage_key = None
        duration = 90
        post_process_status = {"stems": {"quality": "preview"}}

    class Release:
        id = "rel-1"
        mode = "label"
        selected_channels = ["netease", "spotify"]

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-1/kit.zip", "https://cdn/kit.zip")

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: None)
    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"not-really-audio")
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.namelist()
    assert not any(n.startswith("originality/") for n in names)
    readme = zipped.read("README.txt").decode("utf-8")
    assert "立体声母带" in readme
    assert "无审核级分轨" in readme
    checklist = zipped.read("ops_checklist.json").decode("utf-8")
    assert "master_only" in checklist


def test_kit_writes_per_channel_folders(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-4"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None
        audio_url = "http://x/a.mp3"
        storage_key = None
        duration = 90
        post_process_status = {"stems": {"quality": "preview"}}

    class Release:
        id = "rel-4"
        mode = "label"
        selected_channels = ["netease", "spotify"]

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-4/kit.zip", "https://cdn/kit.zip")

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: None)
    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"mix")
    names = zipfile.ZipFile(io.BytesIO(captured["data"])).namelist()
    assert "channels/netease/README.txt" in names
    assert "channels/spotify/README.txt" in names
    netease = zipfile.ZipFile(io.BytesIO(captured["data"])).read("channels/netease/README.txt").decode("utf-8")
    assert "originality/" in netease
    spotify = zipfile.ZipFile(io.BytesIO(captured["data"])).read("channels/spotify/README.txt").decode("utf-8")
    assert "evidence: none" in spotify


def test_kit_includes_demucs_originality(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-2"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None
        audio_url = "http://x/a.mp3"
        storage_key = None
        duration = 90
        post_process_status = {"stems": {"quality": "demucs", "keys": {"vocal": "k", "accompaniment": "a"}, "originality_zip_key": "o"}}

    class Release:
        id = "rel-2"
        mode = "self_release"
        selected_channels = ["kugou"]

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-2/kit.zip", "https://cdn/kit.zip")

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: b"AUDIO")
    monkeypatch.setattr("app.services.stem_assets.transcode_audio", lambda *args, **kwargs: b"AUDIO")
    monkeypatch.setattr(kit_mod, "load_review_stem_bytes", lambda work: {"vocal": b"ID3vocal", "accompaniment": b"RIFF"})
    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"mix")
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.namelist()
    assert "originality/README-网易-腾讯.txt" in names
    assert "originality/provenance.json" in names
    assert "originality/stems/vocal.mp3" in names
    assert "originality/accompaniment.wav" in names
    assert not any(n.startswith("audio/vocal") for n in names)


def test_kit_short_video_accompaniment_clip(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-3"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None
        audio_url = "http://x/a.mp3"
        storage_key = None
        duration = 90
        post_process_status = {"stems": {"quality": "demucs", "keys": {"accompaniment": "a"}, "originality_zip_key": "o"}}

    class Release:
        id = "rel-3"
        mode = "self_release"
        selected_channels = ["douyin_musician"]

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-3/kit.zip", "https://cdn/kit.zip")

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: b"AUDIO")
    monkeypatch.setattr(kit_mod, "cut_audio_clip", lambda *args, **kwargs: b"CLIP")
    monkeypatch.setattr(kit_mod, "load_review_stem_bytes", lambda work: {"accompaniment": b"RIFF"})
    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"mix")
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.namelist()
    assert "audio/clips/accompaniment_32s.mp3" in names
    assert not any(n.startswith("originality/") for n in names)


def test_partner_work_payload_uses_master_wav():
    from app.services.distribution.pipeline import partner_work_payload

    work = SimpleNamespace(
        title="T",
        isrc="I",
        audio_url="http://mp3",
        cover_url=None,
        genres=["pop"],
        duration=90,
        is_ai_generated=True,
        post_process_status={"master": {"url": "http://wav", "key": "k"}, "sku_kind": None},
    )
    meta = SimpleNamespace(
        title=None,
        artist_name="A",
        isrc=None,
        cover_url=None,
        genres=None,
        language="zh",
        ai_disclosed=True,
    )
    payload = partner_work_payload(work, meta, SimpleNamespace())
    assert payload["audio_url"] == "http://wav"
    assert payload["master_wav_url"] == "http://wav"
    assert payload["ai_generated"] is True
    assert "stems" not in payload


def test_kit_writes_tunecore_24bit_master(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-24"
        title = "Night Drive"
        isrc = None
        genres = []
        cover_url = None
        cover_storage_key = None
        audio_url = "http://x/a.mp3"
        storage_key = None
        duration = 90
        post_process_status = {}

    class Release:
        id = "rel-24"
        mode = "label"
        selected_channels = ["spotify"]

    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return ("releases/rel-24/kit.zip", "https://cdn/kit.zip")

    def fake_tc(*args, **kwargs):
        if kwargs.get("fmt") == "wav" and kwargs.get("bit_depth") == 24:
            return b"WAV24"
        if kwargs.get("fmt") == "wav":
            return b"WAV16"
        return b"MP3"

    monkeypatch.setattr(kit_mod, "transcode_audio", fake_tc)
    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=None, audio_bytes=b"mix")
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    names = zipped.namelist()
    assert "audio/master.wav" in names
    assert "audio/master_24bit.wav" in names
    assert zipped.read("audio/master_24bit.wav") == b"WAV24"
    checklist = json.loads(zipped.read("ops_checklist.json"))
    assert checklist["listing_asset"] == "audio/master.wav"
    assert checklist["tunecore_preferred"] == "audio/master_24bit.wav"
    assert checklist["partner_tracks"] == "master_only"


def test_ops_steps_split_listing_from_evidence():
    from app.services.distribution.service import _ops_steps_for

    row = SimpleNamespace(channel_code="kugou", status="ops_queue", distributor_code="cn_label", owner_id="x")
    steps = _ops_steps_for(SimpleNamespace(), row, {"title": "Night Drive"})
    blob = "\n".join(steps)
    assert "audio/master.wav" in blob
    assert "originality.zip" in blob
    assert "vocal/drums" in blob

