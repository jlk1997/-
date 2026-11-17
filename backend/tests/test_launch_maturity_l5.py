import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_all_seventeen_playbooks_have_heal_and_health():
    from app.services.harvest.playbooks import PLAYBOOKS, heal_candidates, playbook_health

    assert len(PLAYBOOKS) == 17
    for code in PLAYBOOKS:
        heal = heal_candidates(code)
        assert heal["statsUrls"], code
        report = playbook_health(code)
        assert report["ok"] is True, (code, report.get("issues"))


def test_js_python_playbook_keys_and_heal_hosts_align():
    from app.services.harvest.playbooks import PLAYBOOKS, heal_candidates
    from app.services.seats.farm import farm_url_allowed

    js = (ROOT / "packages" / "dsp-playbooks" / "index.js").read_text(encoding="utf-8")
    js_keys = set(re.findall(r"^\s{2}([a-z_]+): \{ name:", js, re.M))
    assert js_keys == set(PLAYBOOKS)

    runner = (ROOT / "packages" / "dsp-playbooks" / "runner.js").read_text(encoding="utf-8")
    core = (ROOT / "apps" / "creator-connector" / "runner-core.js").read_text(encoding="utf-8")
    assert "artists.amazonmusic.com" in runner
    assert "artists.amazonmusic.com" in core
    assert runner.count("healCandidates") == core.count("healCandidates")

    for code in PLAYBOOKS:
        urls = heal_candidates(code)["statsUrls"]
        assert urls, code
        assert farm_url_allowed(urls[0], code) is True, (code, urls[0])


def test_amazon_portal_is_not_a_live_receipt():
    from app.services.distribution.catalog import is_known_upload_portal, looks_like_store_page

    assert is_known_upload_portal("https://artists.amazon.com/") is True
    assert is_known_upload_portal("https://artists.amazonmusic.com/analytics") is True
    assert looks_like_store_page("https://artists.amazon.com/", "amazon_music") is False
    assert looks_like_store_page("https://music.amazon.com/albums/B0TESTALBUM", "amazon_music") is True


def test_stale_session_helpers_are_shared():
    source = (ROOT / "backend" / "app" / "services" / "distribution" / "assist.py").read_text(encoding="utf-8")
    assert "def _stale_session_reason" in source
    assert "def count_stale_session_jobs" in source
    assert source.index("def _stale_session_reason") < source.index("def expire_stale_session_jobs")
    assert "_stale_session_reason(db, row, now=now)" in source


def test_recall_copy_is_creation_not_listen():
    tasks = (ROOT / "backend" / "app" / "workers" / "tasks.py").read_text(encoding="utf-8")
    assert "没有创作" in tasks
    celery = (ROOT / "backend" / "app" / "celery_app.py").read_text(encoding="utf-8")
    assert "ops_daily_digest_task" in celery
    growth = (ROOT / "backend" / "app" / "services" / "growth.py").read_text(encoding="utf-8")
    assert "last_made" in growth
    assert "Work.owner_id" in growth
