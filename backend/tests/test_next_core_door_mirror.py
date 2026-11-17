"""Keep the client `nextCoreDoor` mirror honest — no JS runner in this repo."""

from pathlib import Path

from app.services.workbench import next_core_door

CLIENT = Path(__file__).resolve().parents[2] / "apps" / "client" / "src" / "utils" / "nextCoreDoor.ts"
CREATOR_STEP = Path(__file__).resolve().parents[2] / "apps" / "client" / "src" / "packageCreator" / "lib.ts"

CASES = [
    ({"has_result": False, "release_status": "qc_ready", "degraded": False}, "beautify"),
    ({"has_result": True, "release_status": "live", "degraded": True}, "deliveries"),
    ({"has_result": True, "release_status": "queued", "degraded": False}, "deliveries"),
    ({"has_result": True, "release_status": "qc_ready", "degraded": True}, "fix"),
    ({"has_result": True, "release_status": None, "degraded": True}, "fix"),
    ({"has_result": True, "release_status": "qc_ready", "degraded": False}, "release"),
    ({"has_result": True, "release_status": None, "degraded": False}, "radio"),
]


def test_client_next_core_door_encodes_same_order():
    text = CLIENT.read_text(encoding="utf-8")
    assert 'if (!opts.hasResult) return "beautify"' in text
    assert 'if (SHIPPING.has(status)) return "deliveries"' in text
    assert 'if (opts.degraded) return "fix"' in text
    assert 'if (status === "qc_ready") return "release"' in text
    assert 'return "radio"' in text
    assert text.index('return "beautify"') < text.index('return "deliveries"')
    assert text.index('return "deliveries"') < text.index('return "fix"')
    assert text.index('return "fix"') < text.index('return "release"')


def test_backend_door_table_matches_reveal_contract():
    for opts, door in CASES:
        assert next_core_door(**opts) == door


def test_job_restore_uses_workbench_url_not_lite_hardcode():
    root = Path(__file__).resolve().parents[2] / "apps" / "client" / "src"
    hydrator = (root / "components" / "ActiveJobHydrator.tsx").read_text(encoding="utf-8")
    restore = (root / "utils" / "restoreGeneration.ts").read_text(encoding="utf-8")
    assert "workbenchUrl(" in hydrator
    assert "workbenchUrl(" in restore
    assert hydrator.count("workbench-lite") == 0
    assert 'workbench-lite/index?workId=' not in restore


def test_workbench_url_stays_on_the_phone_beautify_desk():
    text = (Path(__file__).resolve().parents[2] / "apps" / "client" / "src" / "utils" / "workbenchNav.ts").read_text(
        encoding="utf-8"
    )
    assert 'studioPage("workbenchLite"' in text
    assert "workbench-pro" not in text
    assert "isDesktopWorkbench() && prefer" not in text


def test_creator_next_step_beautify_before_release():
    text = CREATOR_STEP.read_text(encoding="utf-8")
    assert 'if ((state.needsBeautifyCount || 0) > 0) return "beautify"' in text
    assert 'if (unpublished) return "release"' in text
    assert text.index('return "beautify"') < text.index('return "release"')
    assert text.index('return "reprocess"') < text.index('return "beautify"')
    assert text.index('if (unpublished) return "release"') < text.index('if (loginWait && state.delivering) return "connector"')


def test_needs_beautify_master_blocks_raw_one_tap():
    root = Path(__file__).resolve().parents[2] / "apps" / "client" / "src"
    helper = (root / "utils" / "workbenchWorks.ts").read_text(encoding="utf-8")
    detail = (root / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "export function needsBeautifyMaster" in helper
    assert "!isWorkbenchMaster(work) && !work.superseded_by_work_id" in helper
    assert "needsBeautifyMaster" in detail
    assert "!needsBeautify && !isPostProcessDegraded" in detail
    assert "BeautifyDoorCard" in detail
    create = (root / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    library = (root / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    profile = (root / "pages" / "profile" / "index.tsx").read_text(encoding="utf-8")
    assert "needsBeautifyMaster(recentWork)" in create
    assert "goShipBand(recentWork.superseded_by_work_id || recentWork.id)" in create
    assert "BeautifyDoorCard" in profile
    assert "activeJobId && progressOpen" in create
    assert "liteShoreHint" in (
        Path(__file__).resolve().parents[2] / "apps" / "client" / "src" / "packageStudio" / "workbench" / "shells" / "LiteConsole.tsx"
    ).read_text(encoding="utf-8")
    reveal = (root / "components" / "studio" / "GenerationReveal.tsx").read_text(encoding="utf-8")
    assert "rawTake ?" in reveal
    assert "r.beautify" in reveal
    progress = (root / "components" / "studio" / "GenerationProgress.tsx").read_text(encoding="utf-8")
    assert "!celebrateOpen &&" not in progress
    session = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "client"
        / "src"
        / "packageStudio"
        / "workbench"
        / "hooks"
        / "useWorkbenchSession.ts"
    ).read_text(encoding="utf-8")
    assert 'variant === "pro" && isWeapp' in session
    assert "ShipCompleteCard" in (root / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    assert "ShipCompleteCard" in reveal
    picker = (root / "components" / "studio" / "VariationPicker.tsx").read_text(encoding="utf-8")
    assert "nextBeautify" in picker
    assert "hasResult: Boolean(nextWork?.from_workbench)" in picker
    banner = (root / "components" / "GlobalJobBanner.tsx").read_text(encoding="utf-8")
    assert "openWorkbench(job.workId)" in banner
    tabs = (root / "app.config.ts").read_text(encoding="utf-8")
    assert tabs.count("pagePath:") == 5
    assert 'pagePath: "pages/library/index"' in tabs
    zh = Path(__file__).resolve().parents[2] / "packages" / "i18n" / "src" / "locales" / "zh.ts"
    zh_text = zh.read_text(encoding="utf-8")
    assert "去美化台（工作台）" in zh_text
    assert "做好了，去美化台（工作台）" in zh_text
    desk = (root / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    assert "AuthDesk" in desk
    auth = (root / "packageCreator" / "AuthDesk.tsx").read_text(encoding="utf-8")
    assert "connectorLoadHint" in auth
    assert "authDeskNextStore" in auth
    assert "authDeskEmpty" in auth
    assert "pickNextAuthStore" in auth
    assert "resumePendingQuickRelease" in auth
    assert "CREATOR_TAB_ROUTE" in auth
    assert "openReleaseDesk" not in (root / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    lib = (root / "packageCreator" / "lib.ts").read_text(encoding="utf-8")
    assert "export function pickNextAuthStore" in lib
    assert "export function hasHandedVolumeStore" in lib
    quick = (root / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    assert "skipConfirm" in quick
    assert "rememberPendingRelease" in quick
    assert "nextAuthFirst" in (root / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    release = (root / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    assert "channelWaitGroup" in release
    assert "channelLinkGroup" in release
    library = (root / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    assert "goWorkCoreDoor(w, works)" in library
    assert "coreDoorActionLabel" in library
    bridge = (root / "packageCreator" / "WeappH5Bridge.tsx").read_text(encoding="utf-8")
    assert "creatorOsH5Ready" in bridge
    connector = (
        Path(__file__).resolve().parents[2] / "apps" / "creator-connector" / "background.js"
    ).read_text(encoding="utf-8")
    assert "function watchChallengeResume(settings, seatId, url, channel)" in connector
    assert "registerWebBaseBridge" in connector
    assert "watchStoreReceipt" in connector
    manifest = (
        Path(__file__).resolve().parents[2] / "apps" / "creator-connector" / "manifest.json"
    ).read_text(encoding="utf-8")
    assert "139.199.90.218" in manifest
    assert "superformersmusic.com" in manifest
    assert '"version": "0.14.0"' in manifest
    assert "resume_auth_held_releases" in (
        Path(__file__).resolve().parents[1] / "app" / "services" / "seats" / "service.py"
    ).read_text(encoding="utf-8")
    assert "resume_waiting_uploads" in (
        Path(__file__).resolve().parents[1] / "app" / "services" / "distribution" / "handoff.py"
    ).read_text(encoding="utf-8")
