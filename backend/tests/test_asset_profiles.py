from types import SimpleNamespace
from zipfile import ZipFile
import io

from app.services.distribution.asset_profiles import (
    aggregate_needs,
    profile_for,
    release_asset_status,
    review_stems_ready,
)
from app.services.stem_assets import INSTRUMENTAL_TITLE_SUFFIX, _instrumental_title, try_demucs_stems
from app.services.stem_separator import separate_stems


def test_global_dsp_is_master_only():
    spotify = profile_for("spotify")
    assert spotify.needs_master is True
    assert spotify.needs_stems_evidence is False
    assert spotify.group == "dsp_global"
    apple = profile_for("apple_music")
    assert apple.needs_stems_evidence is False


def test_cn_catalog_wants_evidence_and_tme_wants_instrumental():
    netease = profile_for("netease")
    assert netease.needs_stems_evidence is True
    assert netease.needs_instrumental is False
    kugou = profile_for("kugou")
    assert kugou.needs_stems_evidence is True
    assert kugou.needs_instrumental is True
    qq = profile_for("qq_music")
    assert qq.group == "cn_tme_onboard"


def test_short_video_wants_clips():
    douyin = profile_for("douyin_musician")
    assert douyin.needs_clips is True
    assert douyin.needs_stems_evidence is False


def test_aggregate_needs_mixes_channels():
    needs = aggregate_needs(["spotify", "netease", "douyin_musician"])
    assert needs["needs_master"] is True
    assert needs["needs_stems_evidence"] is True
    assert needs["needs_clips"] is True


def test_review_stems_ready_requires_zip():
    work = SimpleNamespace(post_process_status={"stems": {"quality": "demucs"}})
    assert review_stems_ready(work) is False
    work.post_process_status = {"stems": {"quality": "demucs", "originality_zip_key": "k"}}
    assert review_stems_ready(work) is True


def test_clips_ready_requires_clip_pack_key():
    bare = SimpleNamespace(duration=90, audio_url="http://x/a.mp3", hls_url=None, post_process_status={})
    status = release_asset_status(bare, ["douyin_musician"])
    assert status["clips"]["needed"] is True
    assert status["clips"]["ready"] is False
    ready = SimpleNamespace(
        duration=90,
        audio_url="http://x/a.mp3",
        hls_url=None,
        post_process_status={"clips": {"clip_pack_key": "works/1/clip-pack.zip", "clip_pack_url": "http://x/clip-pack.zip"}},
    )
    status = release_asset_status(ready, ["douyin_musician"])
    assert status["clips"]["ready"] is True
    assert status["clips"]["key"] == "works/1/clip-pack.zip"
    dsp = release_asset_status(ready, ["spotify"])
    assert dsp["clips"]["needed"] is False


def test_listing_ready_requires_master_wav():
    mix_only = SimpleNamespace(audio_url="http://x/a.mp3", storage_key="works/1/mix.mp3", post_process_status={})
    status = release_asset_status(mix_only, ["spotify"])
    assert status["listing"]["ready"] is False
    assert status["listing"]["wav"] is False
    with_wav = SimpleNamespace(
        audio_url="http://x/a.mp3",
        storage_key="works/1/mix.mp3",
        post_process_status={"master": {"key": "works/1/master.wav", "url": "http://x/master.wav"}},
    )
    status = release_asset_status(with_wav, ["spotify"])
    assert status["listing"]["ready"] is True
    assert status["listing"]["wav"] is True


def test_instrumental_lamp_from_child_ref():
    work = SimpleNamespace(
        id="p1",
        post_process_status={
            "instrumental_sku": {"work_id": "c1", "title": "Night Drive (伴奏 / Instrumental)"},
            "stems": {"quality": "demucs", "originality_zip_key": "k"},
        },
    )
    status = release_asset_status(work, ["qq_music"])
    assert status["instrumental"]["needed"] is True
    assert status["instrumental"]["ready"] is True
    assert status["instrumental"]["work_id"] == "c1"
    assert status["instrumental"]["can_spawn"] is False
    assert status["evidence"]["ready"] is True


def test_cn_evidence_missing_does_not_block_global_qc():
    from app.services.distribution.asset_profiles import cn_originality_qc_note, sku_gap_for_channel

    work = SimpleNamespace(
        post_process_status={"master": {"key": "works/1/master.wav"}, "stems": {"quality": "preview"}},
    )
    note = cn_originality_qc_note(work, ["netease", "spotify"])
    assert note["blocks_qc"] is False
    assert sku_gap_for_channel(work, "spotify") is None
    assert sku_gap_for_channel(work, "netease") == "evidence"


def test_review_stems_ready_requires_demucs():
    work = SimpleNamespace(post_process_status={"stems": {"quality": "preview"}}, audio_url="http://x")
    assert review_stems_ready(work) is False
    work.post_process_status = {"stems": {"quality": "demucs", "originality_zip_key": "k", "originality_zip_url": "http://x/o.zip"}}
    assert review_stems_ready(work) is True


def test_asset_status_labels():
    work = SimpleNamespace(
        audio_url="http://x/a.mp3",
        storage_key="k",
        duration=120,
        post_process_status={"stems": {"quality": "preview"}},
    )
    status = release_asset_status(work, ["netease"])
    assert status["listing"]["label"] == "上架文件：母带"
    assert status["evidence"]["ready"] is False
    assert "未就绪" in status["evidence"]["label"]
    assert status["needs_ai_musician"] is True


def test_listing_master_prefers_persisted_wav():
    from app.services.distribution.asset_profiles import listing_master_ref

    work = SimpleNamespace(
        audio_url="http://x/a.mp3",
        storage_key="works/1/mix.mp3",
        post_process_status={"master": {"key": "works/1/master.wav", "url": "http://x/master.wav"}},
    )
    ref = listing_master_ref(work)
    assert ref["audio_url"] == "http://x/master.wav"
    assert ref["wav_key"] == "works/1/master.wav"


def test_cn_originality_note_never_blocks_qc():
    from app.services.distribution.asset_profiles import cn_originality_qc_note

    work = SimpleNamespace(post_process_status={"stems": {"quality": "preview"}})
    note = cn_originality_qc_note(work, ["netease", "spotify"])
    assert note["needed"] is True
    assert note["ready"] is False
    assert note["blocks_qc"] is False


def test_persist_master_wav(monkeypatch):
    from app.services import stem_assets as sa

    monkeypatch.setattr(sa, "transcode_audio", lambda *a, **k: b"RIFF")
    monkeypatch.setattr(
        sa,
        "get_storage_service",
        lambda: SimpleNamespace(upload_bytes=lambda data, key, mime: (key, "https://cdn/" + key)),
    )
    work = SimpleNamespace(id="w1", post_process_status={})
    out = sa.persist_master_wav(work, b"mp3")
    assert out["key"] == "works/w1/master.wav"
    assert out["sample_rate"] == 44100
    assert out["bit_depth"] == 16
    assert work.post_process_status["master"]["key"] == "works/w1/master.wav"


def test_qishui_wants_clips_and_evidence():
    qishui = profile_for("qishui")
    assert qishui.group == "cn_catalog"
    assert qishui.needs_stems_evidence is True
    assert qishui.needs_clips is True
    assert qishui.needs_instrumental is False


def test_originality_pack_ref_requires_demucs():
    from app.services.stem_assets import originality_pack_ref

    preview = SimpleNamespace(post_process_status={"stems": {"quality": "preview", "originality_zip_url": "http://x/o.zip"}})
    assert originality_pack_ref(preview)["ready"] is False
    ready = SimpleNamespace(
        post_process_status={"stems": {"quality": "demucs", "originality_zip_url": "http://x/o.zip", "originality_zip_key": "k"}}
    )
    ref = originality_pack_ref(ready)
    assert ref["ready"] is True
    assert ref["listing_asset"] == "master"


def test_farm_materialize_prefers_wav_key(tmp_path, monkeypatch):
    from app.services.seats import farm as farm_mod

    monkeypatch.setattr(farm_mod, "profile_dir", lambda seat: tmp_path)
    seen = []

    def fake_bytes(key):
        seen.append(key)
        return b"WAV" if str(key).endswith("master.wav") else b"MP3"

    monkeypatch.setattr(
        "app.services.storage.get_storage_service",
        lambda: SimpleNamespace(get_object_bytes=fake_bytes),
    )
    out = farm_mod._materialize_upload_files(
        SimpleNamespace(),
        {
            "master_wav_key": "works/1/master.wav",
            "master_storage_key": "works/1/mix.mp3",
            "audio_url": "http://x/a.mp3",
        },
    )
    assert seen[0] == "works/1/master.wav"
    assert (tmp_path / "listing-master.bin").read_bytes() == b"WAV"
    assert out["master_path"]


def test_review_path_never_returns_ffmpeg(monkeypatch):
    monkeypatch.setattr("app.services.stem_separator.DemucsSeparator.separate", lambda self, src: (_ for _ in ()).throw(RuntimeError("demucs_unavailable")))
    stems, quality = try_demucs_stems(b"mix")
    assert stems == {}
    assert quality == "preview"


def test_separate_stems_can_refuse_ffmpeg(monkeypatch):
    monkeypatch.setattr("app.services.stem_separator.DemucsSeparator.separate", lambda self, src: (_ for _ in ()).throw(RuntimeError("demucs_unavailable")))
    monkeypatch.setattr("app.services.stem_separator._ffmpeg_filter", lambda *a, **k: b"fake")
    stems, isolation = separate_stems(b"mix", preferred="demucs", allow_ffmpeg_fallback=False)
    assert stems == {}
    assert isolation == "preview"


def test_instrumental_title_is_separate_sku():
    assert INSTRUMENTAL_TITLE_SUFFIX in _instrumental_title("Night Drive")
    assert _instrumental_title("Night Drive (伴奏 / Instrumental)").count(INSTRUMENTAL_TITLE_SUFFIX) == 1
