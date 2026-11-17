"""Maturity pass: release kit fields, next step, match rate, shared impulse."""

from __future__ import annotations

import io
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.core.preview_contract import EQ_HZ, FIDELITY, LIVE_LU_TOLERANCE
from app.core.studio_ir import ensure_studio_ir
from app.services.creator_next import next_for_work
from app.services.distribution.channel_fields import apply_listing_payload
from app.services.ops.channel_stats import match_rates_from_snapshots
from app.services.seats import secrets as secrets_mod


def test_listing_roundtrip_skips_column_fields():
    meta = SimpleNamespace(extra={})
    apply_listing_payload(meta, {"lyricist": "阿陈", "title": "不该进 listing", "composer": "阿陈"})
    assert meta.extra["listing"]["lyricist"] == "阿陈"
    assert "title" not in meta.extra["listing"]


def test_kit_csv_includes_listing_and_lyrics(monkeypatch):
    from app.services.distribution import kit as kit_mod

    class Work:
        id = "work-1"
        title = "夜车"
        isrc = "CNTEST000001"
        genres = ["pop"]
        cover_url = None
        cover_storage_key = None

    class Release:
        id = "rel-1"
        mode = "label"
        selected_channels = ["netease"]

    class Meta:
        title = "夜车"
        artist_name = "阿陈"
        isrc = "CNTEST000001"
        upc = ""
        cover_url = ""
        genres = ["pop"]
        language = "zh"
        ai_disclosed = True
        lyrics = "一句歌词"
        extra = {"listing": {"lyricist": "阿陈", "composer": "阿陈"}}

    monkeypatch.setattr(kit_mod, "transcode_audio", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no ffmpeg")))
    captured = {}

    def _upload(data, key, content_type):
        captured["data"] = data
        return (key, "https://cdn/kit.zip")

    monkeypatch.setattr(kit_mod, "get_storage_service", lambda: SimpleNamespace(upload_bytes=_upload))
    kit_mod.build_self_release_kit(work=Work(), release=Release(), meta=Meta(), audio_bytes=b"x")
    zipped = zipfile.ZipFile(io.BytesIO(captured["data"]))
    meta_csv = zipped.read("metadata.csv").decode("utf-8")
    assert "lyricist" in meta_csv
    assert "阿陈" in meta_csv
    assert "一句歌词" in zipped.read("lyrics.txt").decode("utf-8")


def test_next_for_work_asks_fields_before_release_and_release_before_stores():
    assert next_for_work(requested_fields=["lyrics"])["step"] == "fill_release"
    assert next_for_work(has_audio=True, has_release=False)["step"] == "release"
    assert next_for_work(has_audio=True, has_release=True, delivering=True, live=False)["step"] == "stores"


def test_match_rate_uses_statement_rows_only():
    rates = match_rates_from_snapshots(
        [
            {"channel_code": "netease", "source": "distributor_export", "work_id": "w1", "usable_for_settlement": True},
            {"channel_code": "netease", "source": "distributor_export", "work_id": None, "usable_for_settlement": False},
            {"channel_code": "netease", "source": "connector", "work_id": None, "usable_for_settlement": False},
        ]
    )
    assert rates["netease"] == 0.5


def test_new_vault_key_still_opens_old_ciphertext(monkeypatch):
    monkeypatch.setattr(secrets_mod.settings, "jwt_secret", "unit-test-secret")
    monkeypatch.setattr(secrets_mod.settings, "seat_vault_key", "")
    blob = secrets_mod.encrypt_blob({"session": {"ok": 1}})
    monkeypatch.setattr(secrets_mod.settings, "seat_vault_key", "independent-vault-material")
    assert secrets_mod.decrypt_blob(blob)["session"]["ok"] == 1
    fresh = secrets_mod.encrypt_blob({"session": {"ok": 2}})
    assert secrets_mod.decrypt_blob(fresh)["session"]["ok"] == 2


def test_studio_ir_is_a_stereo_wav(tmp_path, monkeypatch):
    path = ensure_studio_ir()
    assert path.exists()
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == 44100
        assert handle.getnframes() > 1000


def test_preview_contract_matches_browser_engine():
    root = Path(__file__).resolve().parents[2]
    text = (root / "apps/client/src/packageStudio/workbench/engine/contract.ts").read_text(encoding="utf-8")
    assert f"low: {EQ_HZ['low']}" in text
    assert 'eq: "live"' in text
    assert 'compress: "approx"' in text
    assert 'pitch: "render"' in text
    assert FIDELITY["reverb"] == "live"
    assert LIVE_LU_TOLERANCE == 0.5
