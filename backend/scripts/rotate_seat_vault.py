"""Re-encrypt seat and vendor ciphertext with the current SEAT_VAULT_KEY.

Old blobs stay readable via the JWT-derived fallback in secrets.decrypt_blob.
Run this once after SEAT_VAULT_KEY is set, then the fallback can be retired.
Does not print plaintext or the key.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.schemas import SeatSecret, VendorKey
from app.services.seats.secrets import decrypt_blob, encrypt_blob


def _rotate(rows) -> tuple[int, int]:
    changed = 0
    skipped = 0
    for row in rows:
        raw = getattr(row, "ciphertext", "") or ""
        if not raw:
            skipped += 1
            continue
        payload = decrypt_blob(raw)
        if not payload:
            skipped += 1
            continue
        fresh = encrypt_blob(payload)
        if fresh != raw:
            row.ciphertext = fresh
            changed += 1
    return changed, skipped


def main() -> int:
    db = SessionLocal()
    try:
        seat_changed, seat_skipped = _rotate(db.query(SeatSecret).all())
        vendor_changed, vendor_skipped = _rotate(db.query(VendorKey).all())
        db.commit()
    finally:
        db.close()
    print(
        f"rotated seat={seat_changed} vendor={vendor_changed} "
        f"skipped seat={seat_skipped} vendor={vendor_skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
