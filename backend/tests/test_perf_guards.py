"""Guards for the H5 nav + hotspot cache work — no JS runner in this repo."""

from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client"


def test_open_stack_page_requires_visible_dom_and_skips_blind_heal():
    text = (CLIENT / "src" / "utils" / "navigation.ts").read_text(encoding="utf-8")
    assert "h5StackPageVisible(target)" in text
    assert "setNavPending" in text
    assert "setTimeout" not in text
    workbench = (CLIENT / "src" / "utils" / "workbenchNav.ts").read_text(encoding="utf-8")
    doors = (CLIENT / "src" / "utils" / "coreDoorNav.ts").read_text(encoding="utf-8")
    release = (CLIENT / "src" / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    assert "openStackPage(workbenchUrl" in workbench
    assert "openStackPage" in doors
    assert "redirectTo({ url: resolved })" in text
    path = (CLIENT / "src" / "utils" / "h5Path.ts").read_text(encoding="utf-8")
    loc = path.split("export function h5LocationMatches", 1)[1]
    assert "hash === target" in loc
    assert "openReleaseDesk" not in release
    assert "openCreatorDesk(\"today\")" in release
    assert "isNeedsAuth" in release
    assert "openDeliveries" in release
    assert "rememberPendingRelease" in release
    assert "skipConfirm" in release


def test_profile_first_paint_drops_duplicate_gets():
    text = (CLIENT / "src" / "pages" / "profile" / "index.tsx").read_text(encoding="utf-8")
    assert "getMyProfile" not in text
    assert "getSubscription" not in text
    assert 'listWorks("newest", undefined, 8)' in text
    assert "fetchUnreadCount" in text
    assert "creditsCtx?.subscription" in text


def test_create_reuses_credits_subscription():
    text = (CLIENT / "src" / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    assert "getSubscription" not in text
    assert 'listWorks("newest", undefined, 12)' in text


def test_notifications_list_skips_second_unread_query_when_short():
    text = (ROOT / "backend" / "app" / "api" / "routes" / "notifications.py").read_text(encoding="utf-8")
    assert "sum(1 for n in rows if n.read_at is None)" in text


def test_library_loads_active_lane_only():
    text = (CLIENT / "src" / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    assert "lane: Tab" in text
    assert "listPlaylists" in text
    assert "worksLoadedRef" in text
    assert text.index("if (lane === \"works\")") < text.index("listPlaylists")


def test_feed_did_show_skips_fresh_cache():
    text = (CLIENT / "src" / "pages" / "feed" / "index.tsx").read_text(encoding="utf-8")
    show = text.split("useDidShow", 1)[1]
    assert "readPageCache" in show
    assert "{ background: true }" not in show


def test_radio_caps_refetch_on_show():
    text = (CLIENT / "src" / "packageSocial" / "pages" / "radio" / "index.tsx").read_text(encoding="utf-8")
    assert "staleMs: 15_000" in text
    assert 'listWorks("newest", undefined, 40)' in text


def test_nav_pending_times_out():
    text = (CLIENT / "src" / "utils" / "navPending.ts").read_text(encoding="utf-8")
    assert "8000" in text


def test_header_unread_uses_light_badge_not_full_list():
    header = (CLIENT / "src" / "components" / "AppHeader.tsx").read_text(encoding="utf-8")
    assert "fetchUnreadCount" in header
    assert "getNotifications(" not in header
    assert "prefetchCoreChunks" in header
    unread = (CLIENT / "src" / "utils" / "unreadBadge.ts").read_text(encoding="utf-8")
    assert "getNotificationUnread" in unread


def test_webpack_splits_social_studio_creator():
    cfg = (CLIENT / "config" / "index.js").read_text(encoding="utf-8")
    assert 'name: "chunk-social"' in cfg
    assert 'name: "chunk-studio"' in cfg
    assert 'name: "chunk-creator"' in cfg
    assert 'chunks: "async"' in cfg
    assert "[contenthash:8]" in cfg
    assert 'filename: "css/[name].[contenthash:8].css"' in cfg
    assert "miniCssExtractPlugin" in cfg
    pkg = (CLIENT / "package.json").read_text(encoding="utf-8")
    assert "hash-unhashed-css.mjs" in pkg


def test_index_html_drops_google_fonts_and_uses_small_touch_icon():
    html = (CLIENT / "src" / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "apple-touch-icon.png" in html
    assert "<title>比特音</title>" in html
    icon = CLIENT / "src" / "assets" / "brand" / "apple-touch-icon.png"
    assert icon.is_file()
    assert icon.stat().st_size < 32 * 1024


def test_nginx_immutable_js_css():
    container = (CLIENT / "nginx.conf").read_text(encoding="utf-8")
    host = (ROOT / "deploy" / "nginx" / "app_locations.inc").read_text(encoding="utf-8")
    for text in (container, host):
        assert "max-age=31536000" in text
        assert "immutable" in text
        assert r"\.[0-9a-f]{8,}\.(?:js|css)$" in text
        assert r'location ~* "\.[0-9a-f]{8,}\.(?:js|css)$"' in text
        assert "no-cache" in text
    assert "include /etc/nginx/snippets/bittune_locations.inc" in (
        ROOT / "deploy" / "nginx" / "ip.conf"
    ).read_text(encoding="utf-8")


def test_unread_route_registered_before_list():
    text = (ROOT / "backend" / "app" / "api" / "routes" / "notifications.py").read_text(encoding="utf-8")
    assert text.index('@router.get("/unread")') < text.index('@router.get("")')


def test_creator_hub_short_cache(monkeypatch):
    from app.services.royalty import hub as hub_mod

    hub_mod.invalidate_creator_hub()
    calls = {"n": 0}

    def compute(_db, _user):
        calls["n"] += 1
        return {"n": calls["n"]}

    monkeypatch.setattr(hub_mod, "_compute_creator_hub", compute)
    user = SimpleNamespace(id="user-cache")
    first = hub_mod.build_creator_hub(None, user)
    second = hub_mod.build_creator_hub(None, user)
    assert first == {"n": 1}
    assert second == {"n": 1}
    assert calls["n"] == 1
    forced = hub_mod.build_creator_hub(None, user, force=True)
    assert forced == {"n": 2}
    other = hub_mod.build_creator_hub(None, SimpleNamespace(id="user-other"))
    assert other == {"n": 3}
    hub_mod.invalidate_creator_hub()


def test_creator_tab_lazy_loads_desk():
    text = (CLIENT / "src" / "pages" / "creator" / "index.tsx").read_text(encoding="utf-8")
    assert "lazy(() =>" in text
    assert "packageCreator/CreatorDesk" in text
    desk = (CLIENT / "src" / "packageCreator" / "CreatorDesk.tsx").read_text(encoding="utf-8")
    assert "await reload(true)" in desk
    assert "usePullDownRefresh" in desk


def test_create_page_lazy_loads_heavy_studio():
    text = (CLIENT / "src" / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    for name in (
        "CreateFormulaPanel",
        "LyricsChatPanel",
        "PromptPreviewBar",
        "GenerationProgress",
        "ReferenceTrackPicker",
        "WorkTitleSheet",
    ):
        assert f"lazy(() =>" in text
        assert f'import("../../components/studio/{name}")' in text


@pytest.mark.requires_db
def test_unread_endpoint_is_count_only():
    import uuid
    from datetime import datetime

    from fastapi.testclient import TestClient

    from app.database import SessionLocal
    from app.main import app
    from app.models.schemas import Notification, User
    from app.services.auth import create_access_token, hash_password

    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    user_id = None
    try:
        user = User(
            email=f"unread_{suffix}@test.local",
            username=f"unread_{suffix}",
            hashed_password=hash_password("testpass123"),
            ai_notice_accepted_at=datetime.utcnow(),
        )
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(Notification(user_id=user.id, type="test", payload={}))
        db.add(Notification(user_id=user.id, type="test", payload={}, read_at=datetime.utcnow()))
        db.commit()
        token = create_access_token(str(user.id))
        client = TestClient(app)
        res = client.get("/api/v1/notifications/unread", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body == {"unread_count": 1}
        assert "items" not in body
    finally:
        if user_id:
            db.query(Notification).filter(Notification.user_id == user_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_me_process_cache(monkeypatch):
    from app.api.routes import auth as auth_mod

    auth_mod.invalidate_me_cache()
    calls = {"n": 0}

    def consent_status(_user):
        calls["n"] += 1
        return {"deletion_scheduled_at": None, "missing": []}

    monkeypatch.setattr("app.services.legal.consent_status", consent_status)
    user = SimpleNamespace(
        id="me-1",
        email="a@test.local",
        username="a",
        display_name="A",
        bio=None,
        avatar_url=None,
        tenant_id="default",
        is_tenant_admin=False,
        is_admin=False,
    )
    first = auth_mod.me(user)
    second = auth_mod.me(user)
    assert first.id == "me-1"
    assert second is first
    assert calls["n"] == 1
    auth_mod.invalidate_me_cache("me-1")
    third = auth_mod.me(user)
    assert calls["n"] == 2
    assert third.id == "me-1"
    auth_mod.invalidate_me_cache()
