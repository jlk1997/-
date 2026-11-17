from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
BACKEND = ROOT / "backend" / "app"
ALEMBIC = ROOT / "backend" / "alembic" / "versions"


def test_generate_keeps_job_guard_until_registered():
    create = (CLIENT / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    execute = create.split("async function executeGenerate")[1]
    assert "generateJobRef.current" in execute
    assert "if (jobId) generateJobRef.current = jobId;" in execute.split("} finally {")[1]
    assert "if (!jobId)" in execute.split("} finally {")[1]
    assert "generateLatchRef.current || generateJobRef.current" in create


def test_resume_retries_after_failed_handoff():
    quick = (CLIENT / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    auth = (CLIENT / "packageCreator" / "AuthDesk.tsx").read_text(encoding="utf-8")
    assert "lastResumeTry" not in quick
    assert "alreadyPublishing" in quick.split("releaseInflight.has")[1][:400]
    assert "resumePendingQuickRelease" in auth
    assert "[handed, weapp]" in auth
    resume = auth.split("void resumePendingQuickRelease")[1][:500]
    assert "locale.adminUi.actionFail" in resume
    assert "copy.adminUi.actionFail" not in resume


def test_discover_republish_opens_existing_post():
    library = (CLIENT / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    create = (CLIENT / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    assert "community_post_id" in library
    assert "openCommunityPost(menuWork.community_post_id)" in library
    assert "viewInCommunity" in library
    assert "openCommunityPost(recentWork.community_post_id)" in create
    assert "isAlreadyPublished" in library
    assert "isAlreadyPublished" in create
    core = (ROOT / "packages" / "api-client" / "src" / "core.ts").read_text(encoding="utf-8")
    assert "export function isAlreadyPublished" in core


def test_timeline_live_requires_receipt():
    timeline = (CLIENT / "components" / "studio" / "WorkReleaseTimeline.tsx").read_text(encoding="utf-8")
    backend = (BACKEND / "services" / "distribution" / "timeline.py").read_text(encoding="utf-8")
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "has_receipt?: boolean" in timeline
    assert "s === \"live\" && hasReceipt === false" in timeline
    assert '"has_receipt": dist_status == "live"' in backend
    assert "busy={reprocessing}" in work
    assert "setReleasing" not in work


def test_posts_work_id_is_unique():
    model = (BACKEND / "models" / "schemas.py").read_text(encoding="utf-8")
    migration = (ALEMBIC / "0037_posts_work_unique.py").read_text(encoding="utf-8")
    assert 'UniqueConstraint("work_id", name="uq_posts_work_id")' in model
    assert "0036_list_hot_indexes" in migration
    assert 'op.create_index("uq_posts_work_id"' in migration


def test_earnings_and_feed_honesty():
    earnings = (CLIENT / "packageCommerce" / "pages" / "creator-earnings" / "index.tsx").read_text(encoding="utf-8")
    feed = (CLIENT / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    assert "remix_credits_7d ?? wallet?.estimated_weekly_royalty" in earnings
    assert "e.remixCreditsHint" in earnings
    assert '<LaunchHonestyBanner surface="feed" />' in feed
