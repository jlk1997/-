from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
BACKEND = ROOT / "backend" / "app"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_stems_export_does_not_fake_a_zip():
    eco = (BACKEND / "services" / "ecosystem.py").read_text(encoding="utf-8")
    stems = eco.split("def _stem_pack_or_raise")[1]
    assert "download_url = work.audio_url" not in stems
    assert 'detail="Stem export needs the master file"' in stems
    assert "if cost > 0 and not deduct_credits" in eco.split("stem_pack, extra_meta = _stem_pack_or_raise")[1][:400]
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "exportStemsComingSoon" in work
    assert 'isolation === "unavailable"' in work


def test_mv_export_charges_after_render():
    mv = (BACKEND / "services" / "mood_visual_export.py").read_text(encoding="utf-8")
    body = mv.split("def export_mood_visual_video")[1]
    assert body.index("if not ffmpeg_available()") < body.index('source="export_mv_video"')
    assert body.index("render_mood_visual_mp4") < body.index('source="export_mv_video"')
    assert "export_mv_video_refund" in body


def test_notify_async_skips_empty_ref_dedupe():
    notify = (BACKEND / "services" / "notifications.py").read_text(encoding="utf-8")
    async_fn = notify.split("async def notify_key_event")[1]
    assert 'dedupe_key = f"{event_type}:{ref}" if ref else None' in async_fn
    assert "if dedupe_key and _dedupe_exists" in async_fn
    assert "event_type}:{(data or {}).get('ref', '')}" not in async_fn


def test_release_and_accounts_guard_busy():
    release = (CLIENT / "packageCreator" / "pages" / "release" / "index.tsx").read_text(encoding="utf-8")
    accounts = (CLIENT / "packageCreator" / "pages" / "accounts" / "index.tsx").read_text(encoding="utf-8")
    assert "if (busy) return;" in release.split("async function submit")[1][:160]
    for fn in ("bind", "unbind", "removePayout", "addPayout", "mintToken", "sendToExtension"):
        assert "if (busy) return;" in accounts.split(f"async function {fn}")[1][:220]


def test_discover_republish_resolves_post_id():
    nav = (CLIENT / "utils" / "communityNav.ts").read_text(encoding="utf-8")
    library = (CLIENT / "pages" / "library" / "index.tsx").read_text(encoding="utf-8")
    create = (CLIENT / "pages" / "create" / "index.tsx").read_text(encoding="utf-8")
    card = (CLIENT / "components" / "community" / "WorkCard.tsx").read_text(encoding="utf-8")
    assert "export async function openExistingDiscoverPost" in nav
    assert "openExistingDiscoverPost(publishWork.id" in library
    assert "openExistingDiscoverPost(recentWork.id" in create
    assert '["live", "delivering", "queued"]' not in card
    assert '["delivering", "queued"]' in card


def test_ship_tab_uses_release_verb():
    config = (CLIENT / "app.config.ts").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert 'text: "发行"' in config
    assert 'creator: "发行"' in zh
    assert 'creator: "Ship"' in en
    assert 'hubTitle: "发行台"' in zh
    assert 'hubTitle: "Release desk"' in en
