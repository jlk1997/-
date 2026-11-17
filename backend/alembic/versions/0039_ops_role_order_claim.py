"""Ops role and release-order assignment."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0039_ops_role_order_claim"
down_revision = "0038_email_verified_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "ops_role" not in cols:
            op.add_column("users", sa.Column("ops_role", sa.String(32), nullable=True))
    if "distribution_deliveries" in tables:
        cols = {c["name"] for c in insp.get_columns("distribution_deliveries")}
        if "ops_assignee_id" not in cols:
            op.add_column(
                "distribution_deliveries",
                sa.Column("ops_assignee_id", UUID(as_uuid=True), nullable=True),
            )
        if "ops_claimed_at" not in cols:
            op.add_column("distribution_deliveries", sa.Column("ops_claimed_at", sa.DateTime(), nullable=True))
        if "ops_note" not in cols:
            op.add_column("distribution_deliveries", sa.Column("ops_note", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "distribution_deliveries" in tables:
        cols = {c["name"] for c in insp.get_columns("distribution_deliveries")}
        for name in ("ops_note", "ops_claimed_at", "ops_assignee_id"):
            if name in cols:
                op.drop_column("distribution_deliveries", name)
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "ops_role" in cols:
            op.drop_column("users", "ops_role")
