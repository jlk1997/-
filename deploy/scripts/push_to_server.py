"""Push the working tree to a Linux host and bring the stack up. Secrets come from env / local .env."""

from __future__ import annotations

import io
import os
import secrets
import sys
import tarfile
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("VIBE_SSH_HOST", "139.199.90.218")
USER = os.environ.get("VIBE_SSH_USER", "root")
REMOTE = "/opt/bittune"
CERT_REMOTE = f"{REMOTE}/certs"
PUBLIC_HOST = os.environ.get("VIBE_PUBLIC_HOST", "superformersmusic.com")
IP_ORIGIN = f"http://{HOST}"
BUNDLE_NAME = "superformersmusic.com_bundle.pem"
KEY_NAME = "superformersmusic.com.key"
MISSING_ENV_DEFAULTS = {
    "SEAT_VAULT_KEY": "",
    "KYC_API_URL": "",
    "KYC_API_KEY": "",
    "KYC_PROVIDER": "",
    "KYC_WEBHOOK_SECRET": "",
    "INSTALL_PLAYWRIGHT": "false",
    "VIBE_FARM_NAVIGATE": "0",
}

SKIP_DIR_NAMES = {
    ".git",
    ".cursor",
    "node_modules",
    "dist",
    "dist-h5",
    ".swc",
    ".venv",
    ".backend_venv",
    "__pycache__",
    ".pytest_cache",
    "agent-transcripts",
    "certs",
}
SKIP_FILE_SUFFIXES = {".pyc", ".log"}
SKIP_FILE_NAMES = {".env", ".env.production"}


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def pick(local: dict[str, str], key: str, default: str = "") -> str:
    return (local.get(key) or default).strip()


def resolve_ssh_password(local: dict[str, str]) -> str:
    return (os.environ.get("VIBE_SSH_PASS") or local.get("VIBE_SSH_PASS") or "").strip()


def upsert_env_line(existing: str, key: str, value: str) -> str:
    lines = existing.splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw and raw.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1] != "":
            out.append("")
        out.append(f"{key}={value}")
    body = "\n".join(out)
    return body if body.endswith("\n") else f"{body}\n"


def public_origin(use_tls: bool) -> str:
    forced = (os.environ.get("VIBE_PUBLIC_ORIGIN") or "").strip()
    if forced:
        return forced.rstrip("/")
    scheme = "https" if use_tls else "http"
    return f"{scheme}://{PUBLIC_HOST}"


def cors_origins_for(origin: str) -> list[str]:
    needed = [
        origin,
        f"https://{PUBLIC_HOST}",
        f"https://www.{PUBLIC_HOST}",
        f"http://{PUBLIC_HOST}",
        f"http://www.{PUBLIC_HOST}",
        IP_ORIGIN,
    ]
    out: list[str] = []
    for item in needed:
        if item and item not in out:
            out.append(item)
    return out


def align_public_origins(existing: str, origin: str) -> str:
    """Point public URLs at the live domain; keep HTTP + IP as CORS extras."""
    text = existing
    text = upsert_env_line(text, "FRONTEND_BASE_URL", origin)
    text = upsert_env_line(text, "API_PUBLIC_URL", f"{origin}/api/v1")
    text = upsert_env_line(text, "S3_PUBLIC_ENDPOINT", origin)
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and line.split("=", 1)[0].strip() == "CORS_ORIGINS":
            current = line.split("=", 1)[1].strip()
            break
    origins = [item.strip() for item in current.split(",") if item.strip()]
    for item in cors_origins_for(origin):
        if item not in origins:
            origins.append(item)
    return upsert_env_line(text, "CORS_ORIGINS", ",".join(origins))


def local_tls_dir() -> Path | None:
    raw = (os.environ.get("VIBE_TLS_DIR") or "").strip()
    candidates = [Path(raw)] if raw else []
    candidates.extend(
        [
            Path.home() / "Downloads" / "superformersmusic.com_nginx_unzip" / "superformersmusic.com_nginx",
            Path.home() / "Downloads" / "superformersmusic.com_nginx",
            ROOT / "deploy" / "certs" / "superformersmusic.com",
        ]
    )
    for path in candidates:
        if (path / BUNDLE_NAME).is_file() and (path / KEY_NAME).is_file():
            return path
    return None


def remote_tls_ready(client: paramiko.SSHClient) -> bool:
    try:
        run(client, f"test -s {CERT_REMOTE}/{BUNDLE_NAME} && test -s {CERT_REMOTE}/{KEY_NAME}", timeout=20)
        return True
    except RuntimeError:
        return False


def upload_tls_bundle(client: paramiko.SSHClient, source: Path) -> None:
    run(client, f"mkdir -p {CERT_REMOTE} && chmod 750 {CERT_REMOTE}", timeout=20)
    put_bytes(client, (source / BUNDLE_NAME).read_bytes(), f"{CERT_REMOTE}/{BUNDLE_NAME}")
    put_bytes(client, (source / KEY_NAME).read_bytes(), f"{CERT_REMOTE}/{KEY_NAME}")
    run(
        client,
        f"chmod 644 {CERT_REMOTE}/{BUNDLE_NAME} && chmod 600 {CERT_REMOTE}/{KEY_NAME} && chown root:root {CERT_REMOTE}/{BUNDLE_NAME} {CERT_REMOTE}/{KEY_NAME}",
        timeout=20,
    )
    print(f"uploaded TLS bundle from {source}", flush=True)


def install_host_nginx(client: paramiko.SSHClient, use_tls: bool) -> None:
    run(client, "mkdir -p /etc/nginx/snippets /var/www/certbot /etc/nginx/conf.d", timeout=20)
    put_bytes(
        client,
        (ROOT / "deploy" / "nginx" / "app_locations.inc").read_bytes(),
        "/etc/nginx/snippets/bittune_locations.inc",
    )
    name = "https.superformersmusic.com.conf" if use_tls else "ip.conf"
    put_bytes(client, (ROOT / "deploy" / "nginx" / name).read_text(encoding="utf-8").encode("utf-8"), "/etc/nginx/conf.d/bittune.conf")
    if use_tls:
        run(client, "command -v ufw >/dev/null && ufw allow 443/tcp || true", timeout=20)
        run(client, "command -v firewall-cmd >/dev/null && firewall-cmd --permanent --add-service=https && firewall-cmd --reload || true", timeout=30)
    run(client, "nginx -t && (systemctl enable --now nginx || true) && (systemctl reload nginx || nginx -s reload)")
    print(f"installed {'HTTPS' if use_tls else 'HTTP'} nginx from {name}", flush=True)


def merge_missing_env(existing: str, extras: dict[str, str]) -> str:
    present: set[str] = set()
    for raw in existing.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        present.add(line.split("=", 1)[0].strip())
    additions = [f"{key}={value}" for key, value in extras.items() if key not in present]
    if not additions:
        return existing
    body = existing if existing.endswith("\n") else f"{existing}\n"
    return body + "\n".join(additions) + "\n"


def build_server_env(local: dict[str, str], origin: str) -> str:
    jwt = secrets.token_urlsafe(48)
    pg = secrets.token_urlsafe(24).replace("-", "")
    minio_user = "bittune" + secrets.token_hex(4)
    minio_pass = secrets.token_urlsafe(24).replace("-", "")
    lines = [
        f"DEBUG=false",
        f"DEV_MOCK_GENERATION=false",
        f"RUN_ALEMBIC_ON_STARTUP=false",
        f"APP_NAME={pick(local, 'APP_NAME', '比特音')}",
        f"APP_VERSION={pick(local, 'APP_VERSION', '3.0.0')}",
        f"API_PREFIX=/api/v1",
        f"POSTGRES_PASSWORD={pg}",
        f"MINIO_ROOT_USER={minio_user}",
        f"MINIO_ROOT_PASSWORD={minio_pass}",
        f"DATABASE_URL=postgresql://vibe:{pg}@postgres:5432/vibe_sorcery",
        f"REDIS_URL=redis://redis:6379/0",
        f"CELERY_BROKER_URL=redis://redis:6379/1",
        f"CELERY_RESULT_BACKEND=redis://redis:6379/2",
        f"JWT_SECRET={jwt}",
        f"JWT_ALGORITHM=HS256",
        f"JWT_EXPIRE_MINUTES=10080",
        f"ADMIN_BOOTSTRAP_EMAIL={pick(local, 'ADMIN_BOOTSTRAP_EMAIL')}",
        f"MINIMAX_API_KEY={pick(local, 'MINIMAX_API_KEY')}",
        f"MINIMAX_API_BASE={pick(local, 'MINIMAX_API_BASE', 'https://api.minimaxi.com/v1')}",
        f"MINIMAX_MUSIC_MODEL={pick(local, 'MINIMAX_MUSIC_MODEL', 'music-2.6')}",
        f"MINIMAX_MUSIC_COVER_MODEL={pick(local, 'MINIMAX_MUSIC_COVER_MODEL', 'music-cover')}",
        f"MINIMAX_CHAT_MODEL={pick(local, 'MINIMAX_CHAT_MODEL', 'MiniMax-M3')}",
        f"MINIMAX_IMAGE_MODEL={pick(local, 'MINIMAX_IMAGE_MODEL', 'image-01')}",
        f"MINIMAX_MUSIC_OUTPUT_FORMAT={pick(local, 'MINIMAX_MUSIC_OUTPUT_FORMAT', 'hex')}",
        f"MINIMAX_MUSIC_STREAM={pick(local, 'MINIMAX_MUSIC_STREAM', 'true')}",
        f"PARTNER_STUB_ENABLED=false",
        f"VIBE_FARM_NAVIGATE=0",
        f"S3_ENDPOINT=http://minio:9000",
        f"S3_PUBLIC_ENDPOINT={origin}",
        f"S3_ACCESS_KEY={minio_user}",
        f"S3_SECRET_KEY={minio_pass}",
        f"S3_BUCKET=vibe-sorcery",
        f"S3_REGION=us-east-1",
        f"S3_USE_SSL=false",
        f"API_PUBLIC_URL={origin}/api/v1",
        f"FRONTEND_BASE_URL={origin}",
        f"CORS_ORIGINS={','.join(cors_origins_for(origin))}",
        f"CREDITS_GATE_ENABLED=true",
        f"WELCOME_CREDITS={pick(local, 'WELCOME_CREDITS', '15')}",
        f"RATE_LIMIT_FAIL_CLOSED=true",
        f"C2PA_ENABLED=true",
        f"LEGAL_COMPANY_NAME={pick(local, 'LEGAL_COMPANY_NAME', '比特音')}",
        f"LEGAL_ICP_NUMBER={pick(local, 'LEGAL_ICP_NUMBER')}",
        f"LEGAL_CONTACT_EMAIL={pick(local, 'LEGAL_CONTACT_EMAIL')}",
        f"LEGAL_CONTACT_PHONE={pick(local, 'LEGAL_CONTACT_PHONE')}",
        f"WECHAT_APP_ID={pick(local, 'WECHAT_APP_ID')}",
        f"WECHAT_APP_SECRET={pick(local, 'WECHAT_APP_SECRET')}",
        f"WECHAT_PAY_MCH_ID={pick(local, 'WECHAT_PAY_MCH_ID')}",
        f"WECHAT_PAY_API_KEY={pick(local, 'WECHAT_PAY_API_KEY')}",
        f"WECHAT_OFFER_ID={pick(local, 'WECHAT_OFFER_ID')}",
        f"WECHAT_VPAY_APPKEY_PROD={pick(local, 'WECHAT_VPAY_APPKEY_PROD')}",
        f"WECHAT_VPAY_APPKEY_SANDBOX={pick(local, 'WECHAT_VPAY_APPKEY_SANDBOX')}",
        f"WECHAT_VPAY_ENV={pick(local, 'WECHAT_VPAY_ENV', '1')}",
        f"WECHAT_PUSH_TOKEN={pick(local, 'WECHAT_PUSH_TOKEN')}",
        f"PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple",
    ]
    return "\n".join(lines) + "\n"


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_NAMES:
        return True
    if path.parts and path.parts[0] == "models":
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix in SKIP_FILE_SUFFIXES:
        return True
    return False


def make_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
            for name in filenames:
                full = Path(dirpath) / name
                rel = full.relative_to(ROOT)
                if should_skip(rel):
                    continue
                tar.add(full, arcname=str(rel).replace("\\", "/"))
    return buf.getvalue()


def ssh_client(password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=password, timeout=30, allow_agent=False, look_for_keys=False)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    print(f"$ {command}", flush=True)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout, get_pty=True)
    out = []
    while True:
        line = stdout.readline()
        if not line:
            break
        text = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), end="", flush=True)
        out.append(text)
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"remote command failed ({code}): {command}\n{''.join(out)}\n{err}")
    return "".join(out)


def put_bytes(client: paramiko.SSHClient, data: bytes, remote_path: str) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "wb") as handle:
            handle.write(data)
    finally:
        sftp.close()


def assert_remote_production_env(client: paramiko.SSHClient) -> None:
    """Fail early if the kept production .env would make the API refuse startup."""
    script = """#!/bin/bash
set -eu
ENV=/opt/bittune/.env
test -f "$ENV" || { echo missing .env; exit 1; }
get() { awk -F= -v k="$1" '$1==k {sub(/^[^=]+=/,""); print; exit}' "$ENV"; }
phone=$(get LEGAL_CONTACT_PHONE)
email=$(get LEGAL_CONTACT_EMAIL)
jwt=$(get JWT_SECRET)
key=$(get MINIMAX_API_KEY)
stub=$(get PARTNER_STUB_ENABLED)
mock=$(get DEV_MOCK_GENERATION)
nav=$(get VIBE_FARM_NAVIGATE)
dbg=$(get DEBUG)
echo "farm_navigate_requested ${nav:-0}"
echo "debug ${dbg:-}"
err=""
[ -n "$key" ] || err="$err MINIMAX_API_KEY missing;"
[ -n "$phone" ] && [ "$phone" != "400-000-0000" ] || err="$err LEGAL_CONTACT_PHONE placeholder;"
[ -n "$email" ] && [ "$email" != "privacy@vibe-sorcery.com" ] || err="$err LEGAL_CONTACT_EMAIL placeholder;"
jwlen=$(printf %s "$jwt" | wc -c)
[ "$jwlen" -ge 32 ] && [ "$jwt" != "change-me-in-production" ] || err="$err JWT_SECRET weak;"
stubn=$(printf %s "$stub" | tr A-Z a-z)
mockn=$(printf %s "$mock" | tr A-Z a-z)
case "$stubn" in 1|true|yes) err="$err PARTNER_STUB_ENABLED on;";; esac
case "$mockn" in 1|true|yes) err="$err DEV_MOCK_GENERATION on;";; esac
if [ -n "$err" ]; then
  echo "production .env would refuse startup:$err"
  exit 1
fi
echo "production .env startup checks ok"
"""
    put_bytes(client, script.encode("utf-8"), "/tmp/bittune-env-check.sh")
    run(client, "bash /tmp/bittune-env-check.sh", timeout=30)


def merge_remote_env(client: paramiko.SSHClient, origin: str) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.file(f"{REMOTE}/.env", "r") as handle:
            raw = handle.read()
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        merged = align_public_origins(merge_missing_env(text, MISSING_ENV_DEFAULTS), origin)
        if merged != text:
            with sftp.file(f"{REMOTE}/.env", "w") as handle:
                handle.write(merged)
            print("merged missing honesty keys into production .env", flush=True)
    finally:
        sftp.close()


def main() -> int:
    local = load_dotenv(ROOT / ".env")
    password = resolve_ssh_password(local)
    if not password:
        print("VIBE_SSH_PASS is required", file=sys.stderr)
        return 2

    fresh = os.environ.get("VIBE_DEPLOY_FRESH") == "1"
    print(f"connecting {USER}@{HOST}", flush=True)
    client = ssh_client(password)
    try:
        run(client, "uname -a && nproc && free -h && df -h /")
        setup = (ROOT / "deploy" / "scripts" / "remote_setup.sh").read_text(encoding="utf-8")
        put_bytes(client, setup.encode("utf-8"), "/tmp/bittune-setup.sh")
        run(client, "bash /tmp/bittune-setup.sh", timeout=600)
        print("packing source…", flush=True)
        archive = make_tarball()
        print(f"archive {len(archive)} bytes", flush=True)
        put_bytes(client, archive, "/tmp/bittune.tgz")
        run(client, f"test -f {REMOTE}/.env && cp -a {REMOTE}/.env /tmp/bittune.env.bak || true")
        if fresh:
            run(client, f"rm -rf {REMOTE} && mkdir -p {REMOTE} && tar -xzf /tmp/bittune.tgz -C {REMOTE}")
        else:
            run(client, f"mkdir -p {REMOTE} && tar -xzf /tmp/bittune.tgz -C {REMOTE}")
        had_env = False
        try:
            run(client, "test -f /tmp/bittune.env.bak")
            run(client, f"cp -a /tmp/bittune.env.bak {REMOTE}/.env")
            had_env = True
            print("kept existing production .env", flush=True)
        except Exception:
            had_env = False
        tls_dir = local_tls_dir()
        if tls_dir is not None:
            upload_tls_bundle(client, tls_dir)
        use_tls = remote_tls_ready(client)
        origin = public_origin(use_tls)
        if had_env:
            try:
                merge_remote_env(client, origin)
            except Exception as exc:
                print(f"merge_remote_env failed; kept existing .env ({exc})", flush=True)
        if not had_env:
            if not pick(local, "MINIMAX_API_KEY"):
                print("local .env is missing MINIMAX_API_KEY; production API will refuse to start", file=sys.stderr)
                return 2
            if pick(local, "LEGAL_CONTACT_PHONE") in {"", "400-000-0000"}:
                print("local .env needs a real LEGAL_CONTACT_PHONE", file=sys.stderr)
                return 2
            put_bytes(client, build_server_env(local, origin).encode("utf-8"), f"{REMOTE}/.env")
            print("wrote first-time production .env", flush=True)
        install_host_nginx(client, use_tls)
        compose_bin = "docker compose"
        try:
            run(client, "docker compose version", timeout=30)
        except Exception:
            compose_bin = "docker-compose"
        assert_remote_production_env(client)
        run(
            client,
            "docker rm -f bittune-beat-1 vibe-sorcery-beat-1 bittune-beat-1 2>/dev/null || true",
            timeout=60,
        )
        compose = (
            f"cd {REMOTE} && COMPOSE_PROGRESS=plain {compose_bin} -f docker-compose.yml -f docker-compose.deploy.yml "
            "up -d --build --force-recreate"
        )
        try:
            run(client, compose, timeout=3600)
        except RuntimeError as exc:
            text = str(exc)
            if "Conflict" not in text and "already in use" not in text:
                raise
            run(
                client,
                f"cd {REMOTE} && {compose_bin} -f docker-compose.yml -f docker-compose.deploy.yml "
                "rm -f -s api worker worker-post worker-dist beat browser-farm frontend || true",
                timeout=180,
            )
            run(client, compose, timeout=3600)
        run(client, f"cd {REMOTE} && {compose_bin} -f docker-compose.yml -f docker-compose.deploy.yml ps", timeout=120)
        print("waiting for API…", flush=True)
        last = ""
        for _ in range(40):
            time.sleep(6)
            try:
                last = run(client, "curl -fsS http://127.0.0.1:8000/livez || true", timeout=30)
            except Exception as exc:
                last = str(exc)
            if "alive" in last.lower() or '"status"' in last:
                break
        run(client, "curl -fsSI http://127.0.0.1/ || true", timeout=30)
        run(client, "curl -sS -m 20 -w '\\nHTTP %{http_code}\\n' http://127.0.0.1/health || true", timeout=30)
        run(client, "curl -sS -m 20 http://127.0.0.1:8000/api/v1/catalog/tracks || true", timeout=30)
        run(client, "curl -sS -m 20 http://127.0.0.1:8000/api/v1/config/platform || true", timeout=30)
        run(client, "curl -sS -m 20 http://127.0.0.1:8000/api/v1/community/feed?limit=4 || true", timeout=30)
        run(client, "curl -sS -m 20 http://127.0.0.1:8000/api/v1/engagement/radio/stations?limit=4 || true", timeout=30)
        if use_tls:
            run(
                client,
                "curl -sSI -m 15 --resolve superformersmusic.com:443:127.0.0.1 https://superformersmusic.com/ || true",
                timeout=30,
            )
        print(f"public origin {origin}", flush=True)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
