import pytest

from app.services.catalog_seed import (
    OFFICIAL_TRACKS,
    SEED_RATE,
    list_official_tracks,
    official_track_by_slug,
    seed_official_catalog,
    synth_loop_wav,
)


def test_synth_loop_wav_is_riff():
    payload = synth_loop_wav(hz=220.0, seconds=1)
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WAVE"
    assert len(payload) > 1000


def test_pack_preview_wav_is_six_seconds():
    payload = synth_loop_wav(hz=196.0, seconds=6)
    assert payload[:4] == b"RIFF"
    data_size = int.from_bytes(payload[40:44], "little")
    assert data_size == 6 * SEED_RATE * 2


def test_list_official_tracks_is_public_and_filterable():
    all_rows = list_official_tracks()
    assert len(all_rows) == len(OFFICIAL_TRACKS)
    assert all(row["audio_url"].startswith("/catalog/audio/") for row in all_rows)
    assert all(row["discovery_only"] is True for row in all_rows)
    night = list_official_tracks(station="night")
    assert night
    assert all("night" in row["stations"] for row in night)


def test_official_track_lookup():
    assert official_track_by_slug("night-lofi.wav")["title"] == "深夜 lo-fi"
    assert official_track_by_slug("missing") is None
    assert len(OFFICIAL_TRACKS) >= 6


@pytest.mark.requires_db
def test_seed_official_catalog_is_idempotent(db):
    from app.models.schemas import Post, User, Work

    first = seed_official_catalog(db)
    db.commit()
    owner = db.query(User).filter(User.username == "bittune").first()
    assert owner is not None
    works = db.query(Work).filter(Work.owner_id == owner.id, Work.visibility == "public").all()
    assert len(works) >= len(OFFICIAL_TRACKS)
    posts = db.query(Post).filter(Post.author_id == owner.id).count()
    assert posts >= len(OFFICIAL_TRACKS)
    assert first["works"] >= 0
    second = seed_official_catalog(db)
    db.commit()
    assert second["works"] == 0
    assert second["posts"] == 0
