"""Sync Desk orders and certified embed completes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0025_sync_desk_embed"
down_revision = "0024_creator_os"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "sync_license_orders" not in tables:
        op.create_table(
            "sync_license_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False, index=True),
            sa.Column("seller_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("tier", sa.String(32), nullable=False),
            sa.Column("pay_method", sa.String(16), nullable=False),
            sa.Column("status", sa.String(24), server_default="pending"),
            sa.Column("gross_credits", sa.Integer(), server_default="0"),
            sa.Column("gross_minor", sa.Integer(), server_default="0"),
            sa.Column("platform_minor", sa.Integer(), server_default="0"),
            sa.Column("seller_minor", sa.Integer(), server_default="0"),
            sa.Column("parent_minor", sa.Integer(), server_default="0"),
            sa.Column("currency", sa.String(8), server_default="CNY"),
            sa.Column("license_id", sa.String(64), nullable=True, index=True),
            sa.Column("agreement_version", sa.String(32), nullable=True),
            sa.Column("meta", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
        )
    if "embed_listen_events" not in tables:
        op.create_table(
            "embed_listen_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False, index=True),
            sa.Column("visitor_key", sa.String(64), nullable=False, index=True),
            sa.Column("entry_date", sa.Date(), nullable=False),
            sa.Column("listen_ratio", sa.Float(), server_default="0"),
            sa.Column("certified", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("usable_for_settlement", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("work_id", "visitor_key", "entry_date", name="uq_embed_visitor_day"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "embed_listen_events" in tables:
        op.drop_table("embed_listen_events")
    if "sync_license_orders" in tables:
        op.drop_table("sync_license_orders")
