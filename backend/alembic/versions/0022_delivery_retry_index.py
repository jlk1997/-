"""Index delivery status + next_retry_at for reconcile scans."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_delivery_retry_index"
down_revision = "0021_delivery_reliability"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_distribution_deliveries_status_retry"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "distribution_deliveries" not in insp.get_table_names():
        return
    existing = {ix["name"] for ix in insp.get_indexes("distribution_deliveries")}
    if INDEX_NAME not in existing:
        op.create_index(INDEX_NAME, "distribution_deliveries", ["status", "next_retry_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "distribution_deliveries" not in insp.get_table_names():
        return
    existing = {ix["name"] for ix in insp.get_indexes("distribution_deliveries")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="distribution_deliveries")
