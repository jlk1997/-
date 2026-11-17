"""Persist unmatched harvest rows for the ops exception desk."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0029_harvest_unmatched"
down_revision = "0028_seat_os"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "harvest_unmatched" in tables:
        return
    op.create_table(
        "harvest_unmatched",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("seat_id", UUID(as_uuid=True), sa.ForeignKey("creator_seats.id"), nullable=True),
        sa.Column("channel_code", sa.String(32), nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("isrc", sa.String(32), nullable=True),
        sa.Column("streams", sa.Integer(), server_default="0"),
        sa.Column("revenue_minor", sa.Integer(), server_default="0"),
        sa.Column("currency", sa.String(8), server_default="CNY"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="unclaimed"),
        sa.Column("matched_work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_harvest_unmatched_seat_id", "harvest_unmatched", ["seat_id"])
    op.create_index("ix_harvest_unmatched_channel_code", "harvest_unmatched", ["channel_code"])
    op.create_index("ix_harvest_unmatched_period_key", "harvest_unmatched", ["period_key"])
    op.create_index("ix_harvest_unmatched_isrc", "harvest_unmatched", ["isrc"])
    op.create_index("ix_harvest_unmatched_fingerprint", "harvest_unmatched", ["fingerprint"])
    op.create_index("ix_harvest_unmatched_status", "harvest_unmatched", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "harvest_unmatched" in set(insp.get_table_names()):
        op.drop_table("harvest_unmatched")
