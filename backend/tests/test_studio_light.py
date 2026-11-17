from app.services.media import atempo_chain, waveform_png_from_peaks
from app.services.stem_separator import FfmpegBandSeparator, FfmpegMidSideSeparator, get_separator


def test_atempo_chain_stays_in_ffmpeg_window():
    assert "atempo=1.250000" in atempo_chain(1.25)
    chained = atempo_chain(3.0)
    assert "atempo=2.0" in chained
    assert all(0.5 <= float(part.split("=")[1]) <= 2.0 for part in chained.split(",") if part.startswith("atempo="))


def test_separator_factory_defaults_to_bands():
    assert isinstance(get_separator("auto"), FfmpegBandSeparator)
    assert isinstance(get_separator("mid_side"), FfmpegMidSideSeparator)
    assert get_separator("ffmpeg_bands").name == "ffmpeg_bands"


def test_waveform_png_from_peaks_is_png():
    blob = waveform_png_from_peaks([0.1, 0.8, 0.2, 0.5])
    assert blob.startswith(b"\x89PNG")
    assert len(blob) > 80


def test_empty_source_stays_honest_without_ffmpeg(monkeypatch):
    monkeypatch.setattr("app.services.stem_separator._ffmpeg_filter", lambda *a, **k: None)
    stems = FfmpegBandSeparator().separate(b"not-audio")
    assert stems == {}


def test_demucs_failure_is_preview_not_bands(monkeypatch):
    from app.services.stem_separator import DemucsSeparator, separate_stems

    monkeypatch.setattr(DemucsSeparator, "separate", lambda self, src: (_ for _ in ()).throw(RuntimeError("demucs_unavailable")))
    stems, name = separate_stems(b"x", preferred="demucs", allow_ffmpeg_fallback=False)
    assert stems == {}
    assert name == "preview"
