from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "client" / "src"
BACKEND = ROOT / "backend" / "app"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_wav_export_does_not_fallback_to_mp3():
    eco = (BACKEND / "services" / "ecosystem.py").read_text(encoding="utf-8")
    wav = eco.split("def _wav_or_raise")[1]
    assert '"fallback": True' not in wav.split("def export_work")[0]
    assert 'detail="WAV export needs the master file"' in wav
    assert "wav_bytes, extra_meta = _wav_or_raise(work)" in eco
    assert eco.index("wav_bytes, extra_meta = _wav_or_raise") < eco.index('source=f"export_{export_type}"')
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert "exportWavNotReady" in work
    assert "res.meta?.fallback" in work


def test_resume_cools_down_same_pending_work():
    quick = (CLIENT / "packageCreator" / "quickReleaseAction.ts").read_text(encoding="utf-8")
    assert "RESUME_COOLDOWN_MS" in quick
    assert "lastResumeWork" in quick
    assert "lastResumeTry" not in quick
    resume = quick.split("export async function resumePendingQuickRelease")[1]
    assert "Date.now() - lastResumeAt < RESUME_COOLDOWN_MS" in resume


def test_mv_export_maps_honest_errors():
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    mv = work.split("async function doExportMv")[1]
    assert "exportUnavailable" in mv
    assert "exportNoContent" in mv
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "exportUnavailable:" in zh
    assert "exportUnavailable:" in en
    assert "exportNoContent:" in zh
    assert "exportWavNotReady:" in zh
    assert "exportWavNotReady:" in en


def test_remaining_desk_writes_guard_busy():
    data_import = (CLIENT / "packageCreator" / "pages" / "data-import" / "index.tsx").read_text(encoding="utf-8")
    deliveries = (CLIENT / "packageCreator" / "pages" / "deliveries" / "index.tsx").read_text(encoding="utf-8")
    remote = (CLIENT / "packageCreator" / "pages" / "remote-login" / "index.tsx").read_text(encoding="utf-8")
    settlements = (CLIENT / "packageCreator" / "pages" / "settlements" / "index.tsx").read_text(encoding="utf-8")
    for fn in ("pick", "rematchNow", "syncNow"):
        assert "if (busy) return;" in data_import.split(f"async function {fn}")[1][:180]
    for fn in ("saveUrl", "retry", "takedown", "downloadKit"):
        assert "if (busyId) return;" in deliveries.split(f"async function {fn}")[1][:200]
    assert "if (busy) return;" in remote.split("async function ackLoggedIn")[1][:160]
    assert "if (busy) return;" in settlements.split("async function exportStatement")[1][:160]
    assert "if (busy) return;" in settlements.split("async function exportPro")[1][:160]


def test_work_ledger_and_ship_titles_are_honest():
    work = (CLIENT / "packageCreator" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    hub = (CLIENT / "packageCreator" / "pages" / "hub" / "index.config.ts").read_text(encoding="utf-8")
    assert "labelMinor > 0 ? formatFen(labelMinor) : c.waitHarvestShort" in work
    assert 'creator: "发行台"' in zh
    assert 'creator: "Release desk"' in en
    assert "上店进发行台" in zh
    assert "Ship tab is for stores" in en
    assert 'navigationBarTitleText: "发行台"' in hub
