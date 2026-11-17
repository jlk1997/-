"""Offline drill for the music fallback policy. It does not call a provider or read secrets."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.vendors.errors import FAIL, RETRY_SAME, SWITCH, MusicProviderError, provider_failure_policy  # noqa: E402


def main() -> int:
    auth = MusicProviderError("auth", kind="auth", user_message="auth")
    limited = MusicProviderError("limit", kind="rate_limit", user_message="limit")
    server = MusicProviderError("down", kind="server", user_message="down")
    blocked = MusicProviderError("no", kind="moderation", user_message="no")
    checks = [
        provider_failure_policy(auth, attempts_on_vendor=1) == SWITCH,
        provider_failure_policy(limited, attempts_on_vendor=1) == SWITCH,
        provider_failure_policy(server, attempts_on_vendor=1) == RETRY_SAME,
        provider_failure_policy(server, attempts_on_vendor=2) == SWITCH,
        provider_failure_policy(blocked, attempts_on_vendor=1) == FAIL,
    ]
    print("fallback_drill", "ok" if all(checks) else "failed", sum(checks), "/", len(checks))
    print("Live drill: disable the TokenHub key in the vendor pool, generate one song, confirm the receipt vendor is minimax, then re-enable the key.")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
