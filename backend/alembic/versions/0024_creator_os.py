"""Work split sheets for multi-party settlement."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0024_creator_os"
down_revision = "0023_settlement_commission_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "work_split_shares" in insp.get_table_names():
        return
    op.create_table(
        "work_split_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role", sa.String(24), nullable=False, server_default="owner"),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("work_id", "user_id", name="uq_work_split_user"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "work_split_shares" in insp.get_table_names():
        op.drop_table("work_split_shares")
