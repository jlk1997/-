from datetime import datetime, timedelta

import pytest

from app.integrations.vendors.pool import add_key, mark_ok, pick_key, public_row, release_key
from app.models.schemas import VendorKey

SKIP_ENV_MUSIC = ["tokenhub", "minimax", "mureka", "lyria", "elevenlabs", "fun_music"]


@pytest.mark.requires_db
def test_pick_key_skips_minimax_on_instrumental_remelt(db):
    db.query(VendorKey).filter(VendorKey.capability == "instrumental").delete()
    db.commit()
    add_key(db, vendor="stability", capability="instrumental", api_key="stab-test-key-123456")
    add_key(db, vendor="minimax", capability="instrumental", api_key="minimax-test-key-123456")
    picked = pick_key(db, "instrumental", remelt=True, avoid_vendor="minimax", skip_vendors=["tokenhub"])
    assert picked is not None
    assert picked.vendor == "stability"


@pytest.mark.requires_db
def test_remelt_keeps_minimax_when_others_cooling(db):
    db.query(VendorKey).filter(VendorKey.capability == "music").delete()
    db.commit()
    other = add_key(db, vendor="mureka", capability="music", api_key="mureka-cool-key-123456")
    add_key(db, vendor="minimax", capability="music", api_key="minimax-keep-key-123456")
    other.cooldown_until = datetime.utcnow() + timedelta(minutes=10)
    db.commit()
    picked = pick_key(db, "music", remelt=True, avoid_vendor="minimax", skip_vendors=["tokenhub"])
    assert picked is not None
    assert picked.vendor == "minimax"


@pytest.mark.requires_db
def test_pick_key_skips_minimax_on_remelt(db):
    db.query(VendorKey).filter(VendorKey.capability == "music").delete()
    db.commit()
    add_key(db, vendor="mureka", capability="music", api_key="mureka-test-key-123456")
    add_key(db, vendor="minimax", capability="music", api_key="minimax-test-key-123456")
    picked = pick_key(db, "music", remelt=True, avoid_vendor="minimax", skip_vendors=["tokenhub"])
    assert picked is not None
    assert picked.vendor == "mureka"
    shown = public_row(picked)
    assert "api_key" not in shown
    assert shown["key_prefix"] == "mureka"


@pytest.mark.requires_db
def test_pick_key_respects_cooldown(db):
    db.query(VendorKey).filter(VendorKey.capability == "music").delete()
    db.commit()
    row = add_key(db, vendor="lyria", capability="music", api_key="lyria-test-key-123456")
    row.cooldown_until = datetime.utcnow() + timedelta(minutes=10)
    db.commit()
    assert pick_key(db, "music", skip_vendors=["tokenhub", "minimax", "mureka"]) is None
    row.cooldown_until = None
    db.commit()
    picked = pick_key(db, "music", skip_vendors=["tokenhub", "minimax", "mureka"])
    assert picked is not None
    assert picked.vendor == "lyria"


@pytest.mark.requires_db
def test_vendor_key_not_plaintext(db):
    row = add_key(db, vendor="qwen", capability="lyrics", api_key="sk-super-secret-qwen")
    stored = db.query(VendorKey).filter(VendorKey.id == row.id).one()
    assert "super-secret" not in stored.ciphertext
    assert stored.key_prefix == "sk-sup"


@pytest.mark.requires_db
def test_pick_key_skips_id_then_same_vendor(db):
    db.query(VendorKey).filter(VendorKey.capability == "music").delete()
    db.commit()
    first = add_key(db, vendor="minimax", capability="music", api_key="aaa-minimax-key-123456")
    second = add_key(db, vendor="minimax", capability="music", api_key="bbb-minimax-key-123456")
    others = [
        str(row.id)
        for row in db.query(VendorKey).filter(VendorKey.capability == "music", VendorKey.id != second.id).all()
    ]
    assert str(first.id) in others
    picked = pick_key(db, "music", skip_ids=others)
    assert picked is not None
    assert str(picked.id) == str(second.id)


def test_fun_music_stays_off_until_invited():
    from app.config import settings
    from app.integrations.vendors.router import MUSIC_DISPATCH, _music_dispatch

    assert "fun_music" not in MUSIC_DISPATCH
    if not settings.fun_music_enabled:
        assert "fun_music" not in _music_dispatch()


def test_no_unofficial_music_wrappers():
    from app.integrations.vendors.router import MUSIC_DISPATCH

    banned = {"suno", "udio", "sunoapi", "ttapi"}
    assert banned.isdisjoint(MUSIC_DISPATCH)


def test_first_audio_url_from_nested_payload():
    from app.integrations.vendors.adapters import first_audio_url

    assert first_audio_url({"choices": [{"url": "https://cdn.example/a.mp3"}]}) == "https://cdn.example/a.mp3"
    assert first_audio_url({"songs": [{"audio_url": "https://cdn.example/b.mp3"}]}) == "https://cdn.example/b.mp3"
    assert first_audio_url({"url": "https://cdn.example/c.mp3"}) == "https://cdn.example/c.mp3"
    assert first_audio_url({"url": "not-a-url", "audio_url": "https://cdn.example/d.mp3"}) == "https://cdn.example/d.mp3"
    assert first_audio_url({}) == ""


def test_first_image_url_from_nested_payload():
    from app.integrations.vendors.adapters import first_image_url

    assert first_image_url({"image_url": "https://cdn.example/a.png"}) == "https://cdn.example/a.png"
    assert first_image_url({"output": {"results": [{"url": "https://cdn.example/b.png"}]}}) == "https://cdn.example/b.png"
    assert first_image_url({"output": {"choices": [{"message": {"content": [{"image": "https://cdn.example/c.png"}]}}]}}) == "https://cdn.example/c.png"
    assert first_image_url({}) == ""


@pytest.mark.requires_db
def test_pick_key_respects_max_inflight(db):
    db.query(VendorKey).filter(VendorKey.capability == "music", VendorKey.vendor == "stability").delete()
    db.commit()
    add_key(db, vendor="stability", capability="music", api_key="stab-inflight-key-123456", max_inflight=1)
    first = pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC)
    second = pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC)
    assert first is not None
    assert second is None
    mark_ok(db, first)
    third = pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC)
    assert third is not None
    assert str(third.id) == str(first.id)
    release_key(db, third)


@pytest.mark.requires_db
def test_pick_key_respects_daily_quota(db):
    db.query(VendorKey).filter(VendorKey.capability == "music", VendorKey.vendor == "stability").delete()
    db.commit()
    add_key(
        db,
        vendor="stability",
        capability="music",
        api_key="stab-quota-key-123456",
        max_inflight=4,
        daily_quota=1,
    )
    first = pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC)
    assert first is not None
    mark_ok(db, first)
    assert pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC) is None


@pytest.mark.requires_db
def test_pick_key_does_not_commit_caller_session(db):
    db.query(VendorKey).filter(VendorKey.capability == "music", VendorKey.vendor == "stability").delete()
    db.commit()
    row = add_key(db, vendor="stability", capability="music", api_key="stab-isolate-key-123456", max_inflight=2)
    dirty = VendorKey(
        vendor="stability",
        capability="lyrics",
        ciphertext="pending-not-committed",
        key_prefix="PENDIN",
        enabled=True,
    )
    db.add(dirty)
    picked = pick_key(db, "music", skip_vendors=SKIP_ENV_MUSIC)
    assert picked is not None
    db.rollback()
    assert db.query(VendorKey).filter(VendorKey.key_prefix == "PENDIN").first() is None
    stored = db.query(VendorKey).filter(VendorKey.id == row.id).one()
    assert int(stored.inflight or 0) == 1
    release_key(db, stored)
    db.expire(stored)
    assert int(stored.inflight or 0) == 0


def test_chunk_reply_splits_text():
    from app.integrations.vendors.router import chunk_reply

    assert list(chunk_reply("abcdefghijkl", step=5)) == ["abcde", "fghij", "kl"]
    assert list(chunk_reply("")) == []
