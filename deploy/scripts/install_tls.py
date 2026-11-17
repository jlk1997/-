"""Install the commercial superformersmusic.com nginx bundle and switch the live origin to HTTPS."""

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
    install_host_nginx,
    load_dotenv,
    local_tls_dir,
    merge_remote_env,
    public_origin,
    remote_tls_ready,
    resolve_ssh_password,
    run,
    ssh_client,
    upload_tls_bundle,
)


def restart_origin_services(client) -> None:
    compose = "docker compose"
    try:
        run(client, "docker compose version", timeout=20)
    except Exception:
        compose = "docker-compose"
    run(
        client,
        f"cd {REMOTE} && {compose} -f docker-compose.yml -f docker-compose.deploy.yml "
        "up -d --no-build --force-recreate api worker worker-post worker-dist beat browser-farm",
        timeout=180,
    )


def main() -> int:
    local = load_dotenv(ROOT / ".env")
    password = resolve_ssh_password(local)
    if not password:
        print("VIBE_SSH_PASS is required", file=sys.stderr)
        return 2

    source = local_tls_dir()
    if source is None:
        print("TLS bundle not found. Set VIBE_TLS_DIR to the unzipped nginx folder.", file=sys.stderr)
        return 2

    print(f"connecting {USER}@{HOST}", flush=True)
    client = ssh_client(password)
    try:
        upload_tls_bundle(client, source)
        if not remote_tls_ready(client):
            print("remote TLS files missing after upload", file=sys.stderr)
            return 2
        origin = public_origin(True)
        merge_remote_env(client, origin)
        install_host_nginx(client, True)
        restart_origin_services(client)
        run(client, "ss -lnt | sed -n '1p;/[:.]80 /p;/[:.]443 /p' || netstat -lnt | sed -n '1p;/[:.]80 /p;/[:.]443 /p' || true", timeout=20)
        run(client, "curl -sSI -m 12 -H 'Host: superformersmusic.com' http://127.0.0.1/ | head -n 12 || true", timeout=20)
        run(
            client,
            "curl -sSI -m 15 --resolve superformersmusic.com:443:127.0.0.1 https://superformersmusic.com/ | head -n 16 || true",
            timeout=30,
        )
        run(client, "curl -sS -m 15 --resolve superformersmusic.com:443:127.0.0.1 https://superformersmusic.com/livez || true", timeout=30)
        print(f"public origin {origin}", flush=True)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
