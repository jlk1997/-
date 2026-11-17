"""Read-only ops snapshot for the BitTune stack. Requires VIBE_SSH_PASS."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

import paramiko

HOST = os.environ.get("VIBE_SSH_HOST", "139.199.90.218")
USER = os.environ.get("VIBE_SSH_USER", "root")
PASSWORD = os.environ.get("VIBE_SSH_PASS", "")
REMOTE = "/opt/bittune"
PUBLIC = os.environ.get("VIBE_PUBLIC_ORIGIN", f"https://superformersmusic.com").rstrip("/")
PUBLIC_IP = f"http://{HOST}"
EXPECTED = [
    "bittune-api-1",
    "bittune-beat-1",
    "bittune-browser-farm-1",
    "bittune-frontend-1",
    "bittune-minio-1",
    "bittune-postgres-1",
    "bittune-redis-1",
    "bittune-worker-1",
    "bittune-worker-dist-1",
    "bittune-worker-post-1",
]


def fetch(url: str, timeout: int = 12) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, body or str(exc)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    if not PASSWORD:
        print("VIBE_SSH_PASS is required", file=sys.stderr)
        return 2

    print(f"=== public {PUBLIC} ===")
    worst = 0
    for label, base in (("https", PUBLIC), ("ip", PUBLIC_IP)):
        print(f"--- {label} {base} ---")
        for path in ("/", "/livez", "/health", "/api/v1/health"):
            status, body = fetch(base + path)
            snippet = body.replace("\n", " ")[:180]
            print(f"{path}: {status} {snippet}")
            if label == "ip":
                continue
            if path == "/" and status != 200:
                worst = 1
            if path == "/livez" and status != 200:
                worst = 1
            if path in {"/health", "/api/v1/health"}:
                if status not in {200, 503} or '"database":{"status":"ok"}' not in body.replace(" ", ""):
                    worst = 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    cmd = rf"""
set -e
echo '=== compose ==='
cd {REMOTE}
docker compose -f docker-compose.yml -f docker-compose.deploy.yml ps -a
echo '=== resources ==='
df -h / /var/lib/docker | tail -n +1
echo '---'
free -h
echo '=== restart counts ==='
docker inspect --format '{{{{.Name}}}} restarts={{{{.RestartCount}}}} status={{{{.State.Status}}}}' {' '.join(EXPECTED)} 2>/dev/null || true
echo '=== api last errors ==='
docker logs --since 10m bittune-api-1 2>&1 | grep -Ei 'error|exception|traceback' | tail -n 15 || true
"""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stdout.write(err)
    code = stdout.channel.recv_exit_status()
    client.close()
    if code != 0:
        worst = 1
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
