"""Connector ingest tokens, batches, and claim queue."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020_connector_ingest"
down_revision = "0019_metric_snapshot_null_work"
branch_labels = None
depends_on = None


def _table_exists(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "connector_ingest_tokens"):
        op.create_table(
            "connector_ingest_tokens",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("role", sa.String(16), server_default="user"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_connector_ingest_tokens_user_id", "connector_ingest_tokens", ["user_id"])
        op.create_index("ix_connector_ingest_tokens_token_hash", "connector_ingest_tokens", ["token_hash"], unique=True)
    if not _table_exists(bind, "connector_ingest_batches"):
        op.create_table(
            "connector_ingest_batches",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("status", sa.String(24), server_default="pending_review"),
            sa.Column("row_count", sa.Integer(), server_default="0"),
            sa.Column("matched_count", sa.Integer(), server_default="0"),
            sa.Column("unmatched_count", sa.Integer(), server_default="0"),
            sa.Column("extra", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_connector_ingest_batches_uploaded_by", "connector_ingest_batches", ["uploaded_by"])
        op.create_index("ix_connector_ingest_batches_source", "connector_ingest_batches", ["source"])
    if not _table_exists(bind, "connector_claims"):
        op.create_table(
            "connector_claims",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("connector_ingest_batches.id"), nullable=False),
            sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("platform_metric_snapshots.id"), nullable=True),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
            sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=True),
            sa.Column("channel_code", sa.String(32), nullable=False),
            sa.Column("period_key", sa.String(32), nullable=False),
            sa.Column("external_track_id", sa.String(128), nullable=True),
            sa.Column("title", sa.String(255), nullable=True),
            sa.Column("isrc", sa.String(32), nullable=True),
            sa.Column("streams", sa.Integer(), server_default="0"),
            sa.Column("saves", sa.Integer(), server_default="0"),
            sa.Column("comments", sa.Integer(), server_default="0"),
            sa.Column("revenue_minor", sa.Integer(), server_default="0"),
            sa.Column("currency", sa.String(8), server_default="CNY"),
            sa.Column("confidence", sa.Float(), server_default="0.5"),
            sa.Column("raw", JSONB, nullable=True),
            sa.Column("status", sa.String(24), server_default="unclaimed"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_connector_claims_batch_id", "connector_claims", ["batch_id"])
        op.create_index("ix_connector_claims_user_id", "connector_claims", ["user_id"])
        op.create_index("ix_connector_claims_status", "connector_claims", ["status"])


def downgrade() -> None:
    op.drop_table("connector_claims")
    op.drop_table("connector_ingest_batches")
    op.drop_table("connector_ingest_tokens")
