"""Store the contracted commission rate on each settlement line."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_settlement_commission_rate"
down_revision = "0022_delivery_retry_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "settlement_lines" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("settlement_lines")}
    if "commission_rate" not in cols:
        op.add_column("settlement_lines", sa.Column("commission_rate", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "settlement_lines" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("settlement_lines")}
    if "commission_rate" in cols:
        op.drop_column("settlement_lines", "commission_rate")
