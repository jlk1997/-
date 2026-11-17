from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
BACKEND = ROOT / "backend" / "app"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_generation_and_release_serialize_creates():
    limit = (BACKEND / "services" / "active_job_limit.py").read_text(encoding="utf-8")
    draft = (BACKEND / "services" / "distribution" / "release_ready.py").read_text(encoding="utf-8")
    service = (BACKEND / "services" / "distribution" / "service.py").read_text(encoding="utf-8")
    create = (CLIENT / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    quick = (CLIENT / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    assert "db.query(User).filter(User.id == user.id).with_for_update()" in limit
    assert "with_for_update().first()" in draft
    assert "if release.status in ACTIVE_RELEASE:" in service.split("def submit_release")[1][:500]
    assert "generateLatchRef.current = true;" in create.split("async function executeGenerate")[1][:400]
    assert "generateIdempotencyRef" in create
    assert "releaseInflight" in quick


def test_harvest_post_notify_and_resume_lock():
    unmatched = (BACKEND / "services" / "harvest" / "unmatched.py").read_text(encoding="utf-8")
    community = (BACKEND / "api" / "routes" / "community.py").read_text(encoding="utf-8")
    notify = (BACKEND / "services" / "notifications.py").read_text(encoding="utf-8")
    seats = (BACKEND / "services" / "seats" / "service.py").read_text(encoding="utf-8")
    attach = unmatched.split("def attach_unmatched")[1][:700]
    assert ".with_for_update()" in attach
    assert "Work already published" in community
    assert "with_for_update().first() or work" in community
    assert "if dedupe_key and _dedupe_exists" in notify
    assert "q.with_for_update().limit(40)" in seats


def test_client_query_and_double_tap_guards():
    query = (CLIENT / "hooks" / "useAsyncQuery.ts").read_text(encoding="utf-8")
    publish = (CLIENT / "components" / "community" / "PublishDialog.tsx").read_text(encoding="utf-8")
    wallet = (CLIENT / "packageCreator" / "pages" / "wallet" / "index.tsx").read_text(encoding="utf-8")
    progress = (CLIENT / "components" / "studio" / "GenerationProgress.tsx").read_text(encoding="utf-8")
    assert "const my = ++seq.current;" in query
    assert "if (my !== seq.current)" in query
    assert "if (loading) return;" in publish
    assert "if (busy) return;" in wallet.split("async function withdraw")[1][:200]
    assert "current?.jobId === jobId && !isTerminalJobStatus(current.status)" in progress


def test_remaining_ship_paths_open_release_desk():
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    release = (CLIENT / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    notes = (CLIENT / "packageStack" / "pages" / "notifications" / "index.tsx").read_text(encoding="utf-8")
    desk = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "confirmQuickRelease" not in work
    assert "confirmQuickRelease" not in release
    assert "confirmQuickRelease" not in notes
    assert "confirmQuickRelease" not in desk
    assert "ShipCompleteCard" in work
    assert "ShipCompleteCard" in release
    assert "goShipBand(workId)" in notes


def test_following_empty_and_weapp_sync_copy():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    feed = (CLIENT / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    sync = (CLIENT / "packageCommerce" / "pages" / "sync-desk" / "index.tsx").read_text(encoding="utf-8")
    accounts = (CLIENT / "packageCreator" / "pages" / "accounts" / "index.tsx").read_text(encoding="utf-8")
    assert "emptyFollowingFeed" in zh
    assert "emptyFollowingFeed" in en
    assert "emptyFollowingFeed" in feed
    assert "copyWeappCreatorLink(commercePage(\"syncDesk\"" in sync
    assert "resumePendingQuickRelease" in accounts
    assert "hasHandedVolumeStore" in accounts
