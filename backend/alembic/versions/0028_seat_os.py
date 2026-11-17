"""Seat OS: creator seats, jobs, secrets, track code aliases."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0028_seat_os"
down_revision = "0027_radio_play"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "creator_seats" not in tables:
        op.create_table(
            "creator_seats",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("account_key", sa.String(128), nullable=False),
            sa.Column("ownership", sa.String(16), nullable=False),
            sa.Column("channel_code", sa.String(32), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("pool_index", sa.Integer(), server_default="0"),
            sa.Column("status", sa.String(24), server_default="connecting"),
            sa.Column("runtime", sa.String(16), server_default="either"),
            sa.Column("profile_id", sa.String(128), nullable=True),
            sa.Column("external_account_id", sa.String(128), nullable=True),
            sa.Column("last_harvest_at", sa.DateTime(), nullable=True),
            sa.Column("last_upload_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("extra", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_creator_seats_account_key", "creator_seats", ["account_key"], unique=True)
        op.create_index("ix_creator_seats_ownership", "creator_seats", ["ownership"])
        op.create_index("ix_creator_seats_channel_code", "creator_seats", ["channel_code"])
        op.create_index("ix_creator_seats_user_id", "creator_seats", ["user_id"])
        op.create_index("ix_creator_seats_status", "creator_seats", ["status"])
    if "seat_jobs" not in tables:
        op.create_table(
            "seat_jobs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("seat_id", UUID(as_uuid=True), sa.ForeignKey("creator_seats.id"), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("status", sa.String(24), server_default="queued"),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("lease_owner", sa.String(64), nullable=True),
            sa.Column("leased_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("result", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_seat_jobs_seat_id", "seat_jobs", ["seat_id"])
        op.create_index("ix_seat_jobs_kind", "seat_jobs", ["kind"])
        op.create_index("ix_seat_jobs_status", "seat_jobs", ["status"])
    if "seat_secrets" not in tables:
        op.create_table(
            "seat_secrets",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("seat_id", UUID(as_uuid=True), sa.ForeignKey("creator_seats.id"), nullable=False),
            sa.Column("kind", sa.String(24), server_default="cookie_jar"),
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_seat_secrets_seat_id", "seat_secrets", ["seat_id"], unique=True)
    if "track_code_aliases" not in tables:
        op.create_table(
            "track_code_aliases",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("source", sa.String(24), server_default="internal"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_track_code_aliases_work_id", "track_code_aliases", ["work_id"])
        op.create_index("ix_track_code_aliases_code", "track_code_aliases", ["code"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for name in ("track_code_aliases", "seat_secrets", "seat_jobs", "creator_seats"):
        if name in tables:
            op.drop_table(name)
