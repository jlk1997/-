"""Zip the Chrome connector for unpacked install. No store listing required."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "creator-connector"
OUT = ROOT / "dist" / "bityin-connector.zip"

INCLUDE = {
    "manifest.json",
    "background.js",
    "popup.html",
    "popup.js",
    "bridge.js",
    "harvest-core.js",
    "runner-core.js",
    "upload-core.js",
    "extract.js",
    "playbooks.js",
    "assist.js",
    "README.md",
    "INSTALL.md",
    "STORE_LISTING.md",
    "install.html",
    "ui-shared.js",
    "desk.html",
    "desk.js",
    "overlay.js",
}

SKIP_DIRS = {"node_modules"}
FIXTURE_KEEP = {"self-test.html", "sample-rows.json"}


def extra_origins() -> list[str]:
    origins = [
        "http://139.199.90.218/*",
        "http://superformersmusic.com/*",
        "http://www.superformersmusic.com/*",
        "https://superformersmusic.com/*",
        "https://www.superformersmusic.com/*",
    ]
    for key in ("FRONTEND_BASE_URL", "VIBE_FRONTEND_BASE_URL", "API_PUBLIC_URL", "VIBE_API_PUBLIC_URL"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        if parsed.scheme and parsed.netloc:
            origins.append(f"{parsed.scheme}://{parsed.netloc}/*")
    return origins


def patch_manifest(src: Path) -> bytes:
    data = json.loads(src.read_text(encoding="utf-8"))
    extras = extra_origins()
    if extras:
        hosts = list(data.get("host_permissions") or [])
        for origin in extras:
            if origin not in hosts:
                hosts.append(origin)
        data["host_permissions"] = hosts
        matches = list((data.get("externally_connectable") or {}).get("matches") or [])
        for origin in extras:
            if origin not in matches:
                matches.append(origin)
        data.setdefault("externally_connectable", {})["matches"] = matches
        scripts = data.get("content_scripts") or []
        if scripts:
            bridge = list(scripts[0].get("matches") or [])
            for origin in extras:
                if origin not in bridge:
                    bridge.append(origin)
            scripts[0]["matches"] = bridge
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


PLAYBOOK_COPIES = {
    "harvest.js": "harvest-core.js",
    "upload.js": "upload-core.js",
    "runner.js": "runner-core.js",
}


def sync_playbooks() -> None:
    src_dir = ROOT / "packages" / "dsp-playbooks"
    for name, dest in PLAYBOOK_COPIES.items():
        source = src_dir / name
        target = SRC / dest
        if source.is_file():
            target.write_bytes(source.read_bytes())


def collect() -> list[Path]:
    files: list[Path] = []
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SRC)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if "fixtures" in rel.parts and rel.name not in FIXTURE_KEEP:
            continue
        if rel.as_posix() in INCLUDE or rel.parts[0] in {"playbooks", "icons", "fixtures"}:
            files.append(path)
    return files


def main() -> int:
    sync_playbooks()
    files = collect()
    if not files:
        raise SystemExit("no connector files")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arc = Path("bityin-connector") / path.relative_to(SRC)
            if path.name == "manifest.json":
                zf.writestr(str(arc).replace("\\", "/"), patch_manifest(path))
            else:
                zf.write(path, arc)
    print(OUT, len(files), "files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
