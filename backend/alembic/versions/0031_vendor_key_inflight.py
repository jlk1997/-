"""Vendor key inflight accounting and one-open harvest job."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_vendor_key_inflight"
down_revision = "0030_vendor_keys"
branch_labels = None
depends_on = None

VENDOR_UNIQUE = "uq_vendor_keys_vendor_cap_prefix"
SEAT_UNIQUE = "uq_seat_job_open_non_upload"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "vendor_keys" in tables:
        cols = {c["name"] for c in insp.get_columns("vendor_keys")}
        if "inflight" not in cols:
            op.add_column("vendor_keys", sa.Column("inflight", sa.Integer(), server_default="0"))
        if "daily_used" not in cols:
            op.add_column("vendor_keys", sa.Column("daily_used", sa.Integer(), server_default="0"))
        if "quota_date" not in cols:
            op.add_column("vendor_keys", sa.Column("quota_date", sa.Date(), nullable=True))
        op.execute(
            sa.text(
                "DELETE FROM vendor_keys a USING vendor_keys b "
                "WHERE a.ctid < b.ctid AND a.vendor = b.vendor "
                "AND a.capability = b.capability AND a.key_prefix = b.key_prefix"
            )
        )
        existing = {ix["name"] for ix in insp.get_indexes("vendor_keys")}
        existing.update({c["name"] for c in insp.get_unique_constraints("vendor_keys")})
        if VENDOR_UNIQUE not in existing:
            op.create_index(VENDOR_UNIQUE, "vendor_keys", ["vendor", "capability", "key_prefix"], unique=True)

    if "seat_jobs" in tables:
        op.execute(
            sa.text(
                "DELETE FROM seat_jobs a USING seat_jobs b "
                "WHERE a.kind <> 'upload' AND b.kind <> 'upload' "
                "AND a.status IN ('queued', 'leased') AND b.status IN ('queued', 'leased') "
                "AND a.seat_id = b.seat_id AND a.kind = b.kind AND a.ctid < b.ctid"
            )
        )
        existing = {ix["name"] for ix in insp.get_indexes("seat_jobs")}
        if SEAT_UNIQUE not in existing:
            op.create_index(
                SEAT_UNIQUE,
                "seat_jobs",
                ["seat_id", "kind"],
                unique=True,
                postgresql_where=sa.text("status IN ('queued', 'leased') AND kind <> 'upload'"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "seat_jobs" in tables:
        existing = {ix["name"] for ix in insp.get_indexes("seat_jobs")}
        if SEAT_UNIQUE in existing:
            op.drop_index(SEAT_UNIQUE, table_name="seat_jobs")
    if "vendor_keys" in tables:
        existing = {ix["name"] for ix in insp.get_indexes("vendor_keys")}
        if VENDOR_UNIQUE in existing:
            op.drop_index(VENDOR_UNIQUE, table_name="vendor_keys")
        cols = {c["name"] for c in insp.get_columns("vendor_keys")}
        if "quota_date" in cols:
            op.drop_column("vendor_keys", "quota_date")
        if "daily_used" in cols:
            op.drop_column("vendor_keys", "daily_used")
        if "inflight" in cols:
            op.drop_column("vendor_keys", "inflight")
