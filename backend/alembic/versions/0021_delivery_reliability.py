"""Delivery attempt tracking for reliable one-click distribution."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0021_delivery_reliability"
down_revision = "0020_connector_ingest"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "distribution_deliveries", "last_attempt_at"):
        op.add_column("distribution_deliveries", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
    if not _column_exists(bind, "distribution_deliveries", "next_retry_at"):
        op.add_column("distribution_deliveries", sa.Column("next_retry_at", sa.DateTime(), nullable=True))
    if not _column_exists(bind, "distribution_deliveries", "last_error"):
        op.add_column("distribution_deliveries", sa.Column("last_error", sa.Text(), nullable=True))
    if not _column_exists(bind, "distribution_deliveries", "attempt_meta"):
        op.add_column("distribution_deliveries", sa.Column("attempt_meta", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("distribution_deliveries", "attempt_meta")
    op.drop_column("distribution_deliveries", "last_error")
    op.drop_column("distribution_deliveries", "next_retry_at")
    op.drop_column("distribution_deliveries", "last_attempt_at")
