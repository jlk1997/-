"""Radio station checkins and short-video clip drops."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0027_radio_play"
down_revision = "0026_commune_payout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "listen_checkins" in tables:
        cols = {c["name"] for c in insp.get_columns("listen_checkins")}
        if "station" not in cols:
            op.add_column("listen_checkins", sa.Column("station", sa.String(32), nullable=True))
            op.create_index("ix_listen_checkins_station", "listen_checkins", ["station"])
    if "clip_drops" not in tables:
        op.create_table(
            "clip_drops",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False, index=True),
            sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("portal_code", sa.String(32), nullable=False, index=True),
            sa.Column("url", sa.String(512), nullable=False),
            sa.Column("clip_length", sa.Integer(), server_default="15"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "clip_drops" in tables:
        op.drop_table("clip_drops")
    if "listen_checkins" in tables:
        cols = {c["name"] for c in insp.get_columns("listen_checkins")}
        if "station" in cols:
            op.drop_index("ix_listen_checkins_station", table_name="listen_checkins")
            op.drop_column("listen_checkins", "station")
