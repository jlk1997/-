"""Add users.email_verified_at for OTP-verified accounts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_email_verified_at"
down_revision = "0037_posts_work_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "email_verified_at" not in cols:
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "email_verified_at" in cols:
        op.drop_column("users", "email_verified_at")
