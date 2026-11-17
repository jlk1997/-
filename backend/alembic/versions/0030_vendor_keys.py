"""Platform vendor API key pool."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030_vendor_keys"
down_revision = "0029_harvest_unmatched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "vendor_keys" in set(insp.get_table_names()):
        return
    op.create_table(
        "vendor_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("weight", sa.Integer(), server_default="10"),
        sa.Column("daily_quota", sa.Integer(), nullable=True),
        sa.Column("max_inflight", sa.Integer(), server_default="2"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_vendor_keys_vendor", "vendor_keys", ["vendor"])
    op.create_index("ix_vendor_keys_capability", "vendor_keys", ["capability"])
    op.create_index("ix_vendor_keys_enabled", "vendor_keys", ["enabled"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "vendor_keys" not in set(insp.get_table_names()):
        return
    op.drop_index("ix_vendor_keys_enabled", table_name="vendor_keys")
    op.drop_index("ix_vendor_keys_capability", table_name="vendor_keys")
    op.drop_index("ix_vendor_keys_vendor", table_name="vendor_keys")
    op.drop_table("vendor_keys")
