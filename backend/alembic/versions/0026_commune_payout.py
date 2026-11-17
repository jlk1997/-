"""Creator commune and withdrawal receipt numbers."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0026_commune_payout"
down_revision = "0025_sync_desk_embed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "creator_communes" not in tables:
        op.create_table(
            "creator_communes",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("invite_code", sa.String(16), nullable=False, unique=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if "creator_commune_members" not in tables:
        op.create_table(
            "creator_commune_members",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("commune_id", UUID(as_uuid=True), sa.ForeignKey("creator_communes.id"), nullable=False, index=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
            sa.Column("role", sa.String(16), server_default="member"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("commune_id", "user_id", name="uq_commune_member"),
        )
    if "withdrawals" in tables:
        cols = {c["name"] for c in insp.get_columns("withdrawals")}
        if "receipt_no" not in cols:
            op.add_column("withdrawals", sa.Column("receipt_no", sa.String(40), nullable=True))
            op.create_index("ix_withdrawals_receipt_no", "withdrawals", ["receipt_no"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "withdrawals" in tables:
        cols = {c["name"] for c in insp.get_columns("withdrawals")}
        if "receipt_no" in cols:
            op.drop_index("ix_withdrawals_receipt_no", table_name="withdrawals")
            op.drop_column("withdrawals", "receipt_no")
    if "creator_commune_members" in tables:
        op.drop_table("creator_commune_members")
    if "creator_communes" in tables:
        op.drop_table("creator_communes")
