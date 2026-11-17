from types import SimpleNamespace

from app.services.audio_distance import av_distance, remelt_av_nudge
from app.services.harvest.official_csv import parse_official_csv
from app.services.harvest.playbooks import PLATFORM_SEAT_CHANNELS
from app.services.radio.network import radio_trial_next_action
from app.services.reference_track import av_mood_embedding
from app.workers.tasks import variation_sub_config, variation_sub_payload


def test_official_csv_beats_empty_and_stamps_confidence():
    rows = parse_official_csv(
        "Title,Streams,Revenue\nNight Drive [VSAAAAAAAABBBB],1200,36.50\n",
        "netease",
    )
    assert len(rows) == 1
    assert rows[0]["track_code"] == "VSAAAAAAAABBBB"
    assert rows[0]["revenue_minor"] == 3650
    assert rows[0]["confidence"] == 0.95
    assert parse_official_csv("", "netease") == []


def test_first_remelt_clears_too_close_band():
    from app.services.audio_distance import remelt_record

    offset = remelt_av_nudge(1)
    parent = SimpleNamespace(arousal=5, valence=5)
    child = SimpleNamespace(arousal=5 + offset["arousal"], valence=5 + offset["valence"])
    record = remelt_record(parent, child, offset)
    assert record["explain"] == "av_distance"
    assert record["too_close"] is False
    assert record["distance"] >= 0.15
    still_close = remelt_record(parent, SimpleNamespace(arousal=5.1, valence=5.1), offset)
    assert still_close["too_close"] is True


def test_guest_personalized_feed_ranks_listen_heat():
    from app.services.recommendation import explain_post_recommendation, rank_posts_with_context

    class Q:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a, **k):
            return self

        def all(self):
            return self.rows

    hot = SimpleNamespace(id="hot", work_id="hot", listen_completes=40)
    cold = SimpleNamespace(id="cold", work_id="cold", listen_completes=1)

    class Db:
        def query(self, model):
            return Q([hot, cold])

    hot_post = SimpleNamespace(work_id="hot", like_count=0, comment_count=0, created_at=1, author_id="a")
    cold_post = SimpleNamespace(work_id="cold", like_count=9, comment_count=0, created_at=2, author_id="b")
    ranked, ctx = rank_posts_with_context(Db(), [cold_post, hot_post], user=None, sort="personalized")
    assert ranked[0].work_id == "hot"
    reason = explain_post_recommendation(
        hot_post,
        SimpleNamespace(id="hot", moods=[], genres=[]),
        moods=[],
        genres=[],
        following_ids=set(),
        work_embs={},
        user_emb=None,
        heats=ctx["heats"],
    )
    assert reason == "heat"


def test_remelt_nudge_changes_av_and_seed():
    sub = variation_sub_config({"title": "Song", "seed_work_id": "x", "credits_charged": 1}, 1, 10)
    assert sub["remelt"] is True
    assert "credits_charged" not in sub
    assert sub["distance_nudge"] is True
    assert sub["reference"]["av_offset"] == remelt_av_nudge(1)
    assert sub["seed"] != 10
    close = av_distance(
        SimpleNamespace(arousal=5, valence=5),
        SimpleNamespace(arousal=5.1, valence=5.1),
    )
    far = av_distance(
        SimpleNamespace(arousal=2, valence=2),
        SimpleNamespace(arousal=8, valence=8),
    )
    assert close < far


def test_ended_trial_defaults_to_release(db=None):
    work = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", post_process_status={"radio_trial": {"status": "ended"}})

    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self):
            return None

    class FakeDb:
        def query(self, *a, **k):
            return FakeQuery()

    assert radio_trial_next_action(FakeDb(), work, live=False, status="ended") == "release"
    assert radio_trial_next_action(FakeDb(), work, live=True, status="live") == "watch_trial"


def test_coverage_order_starts_cn_then_global():
    assert PLATFORM_SEAT_CHANNELS[:4] == ["netease", "qq_music", "spotify", "youtube_music"]
    assert "qishui" in PLATFORM_SEAT_CHANNELS
    assert "apple_music" in PLATFORM_SEAT_CHANNELS


def test_popular_feed_ranks_by_listen_heat():
    from app.services.recommendation import rank_posts_with_context

    class Q:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a, **k):
            return self

        def all(self):
            return self.rows

    hot = SimpleNamespace(id="hot", work_id="hot", listen_completes=40)
    cold = SimpleNamespace(id="cold", work_id="cold", listen_completes=1)

    class Db:
        def query(self, model):
            return Q([hot, cold])

    hot_post = SimpleNamespace(work_id="hot", like_count=1, comment_count=0, created_at=1, author_id="a")
    cold_post = SimpleNamespace(work_id="cold", like_count=9, comment_count=0, created_at=2, author_id="b")
    ranked, ctx = rank_posts_with_context(Db(), [cold_post, hot_post], user=None, sort="popular")
    assert ranked[0].work_id == "hot"
    assert ctx["heats"]["hot"] > ctx["heats"]["cold"]


def test_feed_explain_prefers_similarity_then_heat():
    from app.services.recommendation import explain_post_recommendation

    post = SimpleNamespace(author_id="u2")
    work = SimpleNamespace(id="w1", moods=["calm"], genres=["lofi"])
    reason = explain_post_recommendation(
        post,
        work,
        moods=["calm"],
        genres=["lofi"],
        following_ids=set(),
        work_embs={"w1": [1.0, 0.0]},
        user_emb=[1.0, 0.0],
        heats={"w1": 20},
    )
    assert reason == "similar_taste"
    heat_only = explain_post_recommendation(
        post,
        work,
        moods=[],
        genres=[],
        following_ids=set(),
        work_embs={},
        user_emb=None,
        heats={"w1": 8},
    )
    assert heat_only == "heat"


def test_draft_metadata_does_not_auto_attest_ai():
    from app.services.distribution.release_ready import draft_metadata

    class Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class Db:
        def query(self, *a, **k):
            return Q()

    meta = draft_metadata(
        Db(),
        SimpleNamespace(title="Night", genres=[], cover_url=None, isrc=None, id="w"),
        SimpleNamespace(display_name="A", username="a"),
    )
    assert meta["ai_disclosed"] is False


def test_same_style_score_prefers_mood_overlap():
    from app.services.recommendation import score_work_similarity

    close = SimpleNamespace(moods=["calm"], genres=["lofi"])
    far = SimpleNamespace(moods=["hype"], genres=["rock"])
    assert score_work_similarity(
        close, seed_emb=None, seed_moods=["calm"], seed_genres=["lofi"], work_emb=None, heat=0
    ) > score_work_similarity(
        far, seed_emb=None, seed_moods=["calm"], seed_genres=["lofi"], work_emb=None, heat=0
    )


def test_seed_recipes_are_creative_specs():
    from app.services.ecosystem import SEED_RECIPES

    assert len(SEED_RECIPES) >= 4
    for item in SEED_RECIPES:
        assert item["spec"]["moods"]
        assert item["spec"]["genres"]
        assert "text_intent" in item["spec"]


def test_av_mood_embedding_is_normalized_and_stable():
    work = SimpleNamespace(arousal=2, valence=7, moods=["calm", "night"])
    first = av_mood_embedding(work)
    second = av_mood_embedding(work)
    assert len(first) == 512
    assert first == second
    assert abs(sum(x * x for x in first) - 1.0) < 1e-6
    other = av_mood_embedding(SimpleNamespace(arousal=8, valence=2, moods=["hype"]))
    assert first != other


def test_recipe_spec_keeps_reference_work():
    from app.services.ecosystem import recipe_spec_from_work

    class Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class Db:
        def query(self, *a, **k):
            return Q()

    spec = recipe_spec_from_work(
        Db(),
        SimpleNamespace(id="w1", title="Night", genres=["lofi"], moods=["calm"], arousal=3, valence=6),
    )
    assert spec["reference_work_id"] == "w1"
    assert spec["moods"] == ["calm"]


def test_serialize_wall_item_includes_taste_chips():
    from app.services.recommendation import serialize_wall_item

    row = serialize_wall_item(
        SimpleNamespace(
            id="w",
            title="Night",
            cover_url=None,
            audio_url="/a.mp3",
            moods=["calm"],
            genres=["lofi"],
            owner=SimpleNamespace(username="ada"),
        )
    )
    assert row["moods"] == ["calm"]
    assert row["genres"] == ["lofi"]
    assert row["owner_username"] == "ada"


def test_seed_recipe_catalog_creates_steward_when_empty():
    from app.services.ecosystem import CATALOG_STEWARD_EMAIL, seed_recipe_catalog

    added = []

    class Q:
        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self):
            return None

        def limit(self, n):
            return self

        def all(self):
            return []

    class Db:
        def query(self, *a, **k):
            return Q()

        def add(self, obj):
            added.append(obj)

        def flush(self):
            if added and getattr(added[0], "id", None) is None:
                added[0].id = "steward"

    created = seed_recipe_catalog(Db())
    assert created == 4
    assert any(getattr(item, "email", None) == CATALOG_STEWARD_EMAIL for item in added)


def test_sync_listing_exposes_owner_and_audio():
    from app.services.royalty.sync_desk import serialize_listing

    row = serialize_listing(
        SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            title="Night",
            cover_url=None,
            audio_url="/a.mp3",
            owner_id="00000000-0000-0000-0000-000000000002",
            commercial_cleared_at=None,
            post_process_status={"sync_listing": {"enabled": True, "tiers": ["personal"]}},
        )
    )
    assert row["audio_url"] == "/a.mp3"
    assert row["owner_id"] == "00000000-0000-0000-0000-000000000002"
    assert row["enabled"] is True
    rights = row["rights_certificate"]
    assert rights["exclusive"] is False
    assert rights["non_exclusive"] is True
    assert rights["ai_disclosed"] is True


def test_variation_parent_accepts_audio_ready_take():
    ready = SimpleNamespace(status="audio_ready", result={"work_id": "w1", "title": "夜曲"})
    assert variation_sub_payload(ready)["work_id"] == "w1"
    assert variation_sub_payload(SimpleNamespace(status="post_processing", result={"work_id": "w2"}))["work_id"] == "w2"
    assert variation_sub_payload(SimpleNamespace(status="running", result={})) is None
    assert variation_sub_payload(None, {"work_id": "w3"})["work_id"] == "w3"
