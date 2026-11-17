"""Upload current tree, write SMTP from env, rebuild api + frontend only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "deploy" / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "deploy" / "scripts"))

from push_to_server import (  # noqa: E402
    HOST,
    REMOTE,
    USER,
    load_dotenv,
    make_tarball,
    put_bytes,
    resolve_ssh_password,
    run,
    ssh_client,
    upsert_env_line,
)

SMTP_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_TLS", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM")


def write_smtp(client, values: dict[str, str]) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.file(f"{REMOTE}/.env", "r") as handle:
            raw = handle.read()
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        for key, value in values.items():
            if value:
                text = upsert_env_line(text, key, value)
        with sftp.file(f"{REMOTE}/.env", "w") as handle:
            handle.write(text)
    finally:
        sftp.close()
    print("merged SMTP keys into production .env", flush=True)


def main() -> int:
    import os

    local = load_dotenv(ROOT / ".env")
    password = resolve_ssh_password(local)
    if not password:
        print("VIBE_SSH_PASS is required", file=sys.stderr)
        return 2
    smtp = {key: (os.environ.get(key) or local.get(key) or "").strip() for key in SMTP_KEYS}

    client = ssh_client(password)
    try:
        print("packing source…", flush=True)
        archive = make_tarball()
        print(f"archive {len(archive)} bytes", flush=True)
        put_bytes(client, archive, "/tmp/bittune.tgz")
        run(client, f"test -f {REMOTE}/.env && cp -a {REMOTE}/.env /tmp/bittune.env.bak || true")
        run(client, f"mkdir -p {REMOTE} && tar -xzf /tmp/bittune.tgz -C {REMOTE}")
        run(client, f"test -f /tmp/bittune.env.bak && cp -a /tmp/bittune.env.bak {REMOTE}/.env || true")
        if any(smtp.values()):
            write_smtp(client, smtp)
        else:
            print("keeping existing production SMTP", flush=True)
        compose = "docker compose"
        try:
            run(client, "docker compose version", timeout=20)
        except Exception:
            compose = "docker-compose"
        # stems overlay keeps worker-stems on the Demucs image. Without it, recreate
        # falls back to the API image and stem separation loses Demucs.
        files = "-f docker-compose.yml -f docker-compose.deploy.yml -f docker-compose.stems.yml"
        run(
            client,
            f"cd {REMOTE} && COMPOSE_BAKE=false COMPOSE_PROGRESS=plain {compose} "
            f"{files} "
            "build api frontend",
            timeout=3600,
        )
        run(
            client,
            f"cd {REMOTE} && {compose} {files} "
            "up -d --no-deps --force-recreate api frontend worker worker-post worker-dist worker-stems beat",
            timeout=300,
        )
        run(
            client,
            f"cd {REMOTE} && {compose} {files} "
            "ps api frontend worker worker-post worker-dist worker-stems beat",
            timeout=40,
        )
        run(
            client,
            "if [ -f /etc/nginx/snippets/bittune_locations.inc ]; then "
            f"cp {REMOTE}/deploy/nginx/app_locations.inc /etc/nginx/snippets/bittune_locations.inc && "
            "nginx -t && nginx -s reload && echo NGINX_RELOADED || echo NGINX_SKIP; "
            "else echo NGINX_SKIP; fi",
            timeout=40,
        )
        print("AUTH_RELEASE_OK", flush=True)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
