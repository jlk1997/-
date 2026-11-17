from types import SimpleNamespace

from app.services.distribution.direct import maybe_link_direct_binding
from app.services.royalty.youtube import extract_youtube_id


def test_extract_youtube_id_from_watch_url():
    assert extract_youtube_id("https://www.youtube.com/watch?v=abc123xyz") == "abc123xyz"
    assert extract_youtube_id("https://youtu.be/abc123xyz") == "abc123xyz"


def test_soundcloud_binding_url_does_not_mark_live(monkeypatch):
    delivery = SimpleNamespace(
        status="session_wait",
        store_url=None,
        channel_code="soundcloud",
        owner_id="u1",
        attempt_meta={},
        external_id=None,
        last_error="x",
        reject_reason="y",
    )
    binding = SimpleNamespace(
        external_release_id="https://soundcloud.com/artist/night-drive",
        official_token="t",
        status="active",
        provider="soundcloud",
    )
    class Q:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return binding

    db = SimpleNamespace(query=lambda model: Q())
    assert maybe_link_direct_binding(db, delivery, None) is False
    assert delivery.status == "session_wait"
    assert delivery.store_url is None


def test_youtube_title_match_marks_live(monkeypatch):
    delivery = SimpleNamespace(
        status="session_wait",
        store_url=None,
        channel_code="youtube_music",
        owner_id="u1",
        work_id="w1",
        attempt_meta={},
        external_id=None,
        last_error=None,
        reject_reason=None,
    )
    release = SimpleNamespace(id="r1")
    binding = SimpleNamespace(official_token="t", status="active", provider="youtube")

    class BindingQ:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return binding

    class MetaQ:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(title="Night Drive")

    class WorkQ:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(title="Night Drive")

    from app.models.schemas import CreatorIdentityBinding, ReleaseMetadata, Work

    def query(model):
        if model is CreatorIdentityBinding:
            return BindingQ()
        if model is ReleaseMetadata:
            return MetaQ()
        if model is Work:
            return WorkQ()
        return BindingQ()

    db = SimpleNamespace(query=query)
    monkeypatch.setattr("app.services.royalty.youtube.configured", lambda: True)
    monkeypatch.setattr("app.services.royalty.youtube._access_token_for", lambda db, row: "tok")
    monkeypatch.setattr(
        "app.services.royalty.youtube._list_mine_videos",
        lambda token: [{"id": "vid99", "title": "Night Drive"}],
    )
    assert maybe_link_direct_binding(db, delivery, release) is True
    assert delivery.status == "live"
    assert delivery.external_id == "vid99"
    assert "watch?v=vid99" in delivery.store_url
