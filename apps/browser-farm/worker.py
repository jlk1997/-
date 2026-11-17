"""Drain queued seat jobs. Profiles live in apps/browser-farm/profiles/."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def _interval(args: list[str]) -> int:
    for index, item in enumerate(args):
        if item == "--interval" and index + 1 < len(args):
            try:
                return max(5, min(int(args[index + 1]), 300))
            except ValueError:
                return 20
    return 20


def drain_once() -> dict:
    from app.database import SessionLocal
    from app.services.seats.farm import drain_queued
    from app.services.seats.service import enqueue_due_harvests, ensure_platform_seats

    db = SessionLocal()
    try:
        ensure_platform_seats(db)
        queued = enqueue_due_harvests(db, force=False)
        db.commit()
        result = drain_queued(db)
        return {"queued": queued, **result}
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    loop = "--loop" in args
    while True:
        result = drain_once()
        print(result)
        if not loop:
            return 0
        time.sleep(_interval(args))


if __name__ == "__main__":
    raise SystemExit(main())
