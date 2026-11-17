"""Indexes for listWorks and unread notification counts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_list_hot_indexes"
down_revision = "0035_workbench_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "works" in tables:
        existing = {idx["name"] for idx in insp.get_indexes("works")}
        if "ix_works_owner_id" not in existing:
            op.create_index("ix_works_owner_id", "works", ["owner_id"], unique=False)

    if "notifications" in tables:
        existing = {idx["name"] for idx in insp.get_indexes("notifications")}
        if "ix_notifications_user_id_read_at" not in existing:
            op.create_index(
                "ix_notifications_user_id_read_at",
                "notifications",
                ["user_id", "read_at"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "notifications" in tables:
        existing = {idx["name"] for idx in insp.get_indexes("notifications")}
        if "ix_notifications_user_id_read_at" in existing:
            op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")

    if "works" in tables:
        existing = {idx["name"] for idx in insp.get_indexes("works")}
        if "ix_works_owner_id" in existing:
            op.drop_index("ix_works_owner_id", table_name="works")
