"""Unique metric snapshots when work_id is NULL."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_metric_snapshot_null_work"
down_revision = "0018_distribution_royalty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "platform_metric_snapshots" not in sa.inspect(bind).get_table_names():
        return
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_metric_user_work_channel_period_source "
            "ON platform_metric_snapshots ("
            "user_id, COALESCE(work_id, '00000000-0000-0000-0000-000000000000'::uuid), "
            "channel_code, period_key, source)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_metric_user_work_channel_period_source"))
