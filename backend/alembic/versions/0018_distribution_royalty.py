"""Distribution, royalty wallet, and settlement tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0018_distribution_royalty"
down_revision = "0017_social_enhancements"
branch_labels = None
depends_on = None


def _table_exists(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "users"):
        if not _column_exists(bind, "users", "creator_level"):
            op.add_column("users", sa.Column("creator_level", sa.String(32), server_default="standard"))
        if not _column_exists(bind, "users", "kyc_status"):
            op.add_column("users", sa.Column("kyc_status", sa.String(20), server_default="none"))

    if _table_exists(bind, "works"):
        if not _column_exists(bind, "works", "release_status"):
            op.add_column("works", sa.Column("release_status", sa.String(32), server_default="none"))
        if not _column_exists(bind, "works", "isrc"):
            op.add_column("works", sa.Column("isrc", sa.String(32), nullable=True))
        if not _column_exists(bind, "works", "commercial_cleared_at"):
            op.add_column("works", sa.Column("commercial_cleared_at", sa.DateTime(), nullable=True))

    tables = [
        (
            "releases",
            lambda: op.create_table(
                "releases",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
                sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("mode", sa.String(24), default="label"),
                sa.Column("status", sa.String(32), default="draft"),
                sa.Column("distributor_code", sa.String(32), nullable=True),
                sa.Column("selected_channels", JSONB, default=list),
                sa.Column("kit_storage_key", sa.String(512), nullable=True),
                sa.Column("kit_url", sa.String(512), nullable=True),
                sa.Column("qc_result", JSONB, default=dict),
                sa.Column("error_message", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "release_metadata",
            lambda: op.create_table(
                "release_metadata",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=False, unique=True),
                sa.Column("title", sa.String(255), nullable=False),
                sa.Column("artist_name", sa.String(255), nullable=True),
                sa.Column("lyrics", sa.Text(), nullable=True),
                sa.Column("isrc", sa.String(32), nullable=True),
                sa.Column("upc", sa.String(32), nullable=True),
                sa.Column("genres", JSONB, default=list),
                sa.Column("language", sa.String(16), default="zh"),
                sa.Column("copyright_year", sa.Integer(), nullable=True),
                sa.Column("ai_disclosed", sa.Boolean(), default=True),
                sa.Column("cover_url", sa.String(512), nullable=True),
                sa.Column("extra", JSONB, default=dict),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "distributor_accounts",
            lambda: op.create_table(
                "distributor_accounts",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("ownership", sa.String(16), default="platform"),
                sa.Column("display_name", sa.String(128), nullable=True),
                sa.Column("official_token", sa.Text(), nullable=True),
                sa.Column("external_account_id", sa.String(128), nullable=True),
                sa.Column("enabled", sa.Boolean(), default=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "distribution_channels",
            lambda: op.create_table(
                "distribution_channels",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("code", sa.String(32), unique=True, nullable=False),
                sa.Column("name", sa.String(128), nullable=False),
                sa.Column("region", sa.String(16), default="global"),
                sa.Column("distributor_code", sa.String(32), nullable=False),
                sa.Column("requirements", JSONB, default=dict),
                sa.Column("enabled", sa.Boolean(), default=True),
                sa.Column("sort_order", sa.Integer(), default=0),
            ),
        ),
        (
            "distribution_deliveries",
            lambda: op.create_table(
                "distribution_deliveries",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=False),
                sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
                sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("channel_code", sa.String(32), nullable=False),
                sa.Column("distributor_code", sa.String(32), nullable=False),
                sa.Column("status", sa.String(32), default="submitting"),
                sa.Column("reject_reason", sa.Text(), nullable=True),
                sa.Column("external_id", sa.String(128), nullable=True),
                sa.Column("store_url", sa.String(512), nullable=True),
                sa.Column("retry_count", sa.Integer(), default=0),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.UniqueConstraint("release_id", "channel_code", name="uq_delivery_release_channel"),
            ),
        ),
        (
            "creator_identity_bindings",
            lambda: op.create_table(
                "creator_identity_bindings",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("official_token", sa.Text(), nullable=True),
                sa.Column("external_release_id", sa.String(128), nullable=True),
                sa.Column("status", sa.String(24), default="active"),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.UniqueConstraint("user_id", "provider", name="uq_binding_user_provider"),
            ),
        ),
        (
            "distribution_licenses",
            lambda: op.create_table(
                "distribution_licenses",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=True),
                sa.Column("agreement_version", sa.String(32), nullable=False),
                sa.Column("commission_rate", sa.Integer(), default=20),
                sa.Column("signed_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "royalty_wallets",
            lambda: op.create_table(
                "royalty_wallets",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("pending_minor", sa.Integer(), default=0),
                sa.Column("available_minor", sa.Integer(), default=0),
                sa.Column("frozen_minor", sa.Integer(), default=0),
                sa.Column("lifetime_earned_minor", sa.Integer(), default=0),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
                sa.UniqueConstraint("user_id", "currency", name="uq_royalty_wallet_user_currency"),
            ),
        ),
        (
            "royalty_ledger_entries",
            lambda: op.create_table(
                "royalty_ledger_entries",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("wallet_id", UUID(as_uuid=True), sa.ForeignKey("royalty_wallets.id"), nullable=True),
                sa.Column("entry_type", sa.String(32), nullable=False),
                sa.Column("amount_minor", sa.Integer(), nullable=False),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("source", sa.String(32), nullable=True),
                sa.Column("ref_id", sa.String(64), nullable=True),
                sa.Column("note", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "settlement_batches",
            lambda: op.create_table(
                "settlement_batches",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("period_key", sa.String(32), nullable=False),
                sa.Column("period_start", sa.Date(), nullable=False),
                sa.Column("period_end", sa.Date(), nullable=False),
                sa.Column("status", sa.String(24), default="draft"),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "settlement_lines",
            lambda: op.create_table(
                "settlement_lines",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("batch_id", UUID(as_uuid=True), sa.ForeignKey("settlement_batches.id"), nullable=False),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
                sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=True),
                sa.Column("channel_code", sa.String(32), nullable=False),
                sa.Column("source", sa.String(32), nullable=False),
                sa.Column("gross_minor", sa.Integer(), default=0),
                sa.Column("commission_minor", sa.Integer(), default=0),
                sa.Column("net_minor", sa.Integer(), default=0),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("snapshot_id", UUID(as_uuid=True), nullable=True),
                sa.UniqueConstraint("batch_id", "user_id", "work_id", "channel_code", name="uq_settlement_line"),
            ),
        ),
        (
            "payout_accounts",
            lambda: op.create_table(
                "payout_accounts",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("channel", sa.String(32), nullable=False),
                sa.Column("account_name", sa.String(128), nullable=True),
                sa.Column("account_no", sa.String(128), nullable=False),
                sa.Column("extra", JSONB, default=dict),
                sa.Column("is_default", sa.Boolean(), default=False),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "withdrawals",
            lambda: op.create_table(
                "withdrawals",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("amount_minor", sa.Integer(), nullable=False),
                sa.Column("fee_minor", sa.Integer(), default=0),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("channel", sa.String(32), nullable=False),
                sa.Column("payout_account_id", UUID(as_uuid=True), sa.ForeignKey("payout_accounts.id"), nullable=True),
                sa.Column("status", sa.String(24), default="pending"),
                sa.Column("risk_flag", sa.Boolean(), default=False),
                sa.Column("admin_note", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "platform_metric_snapshots",
            lambda: op.create_table(
                "platform_metric_snapshots",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
                sa.Column("release_id", UUID(as_uuid=True), sa.ForeignKey("releases.id"), nullable=True),
                sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("channel_code", sa.String(32), nullable=False),
                sa.Column("distributor_code", sa.String(32), nullable=True),
                sa.Column("source", sa.String(32), nullable=False),
                sa.Column("usable_for_settlement", sa.Boolean(), default=False),
                sa.Column("period_key", sa.String(32), nullable=False),
                sa.Column("streams", sa.Integer(), default=0),
                sa.Column("saves", sa.Integer(), default=0),
                sa.Column("comments", sa.Integer(), default=0),
                sa.Column("revenue_minor", sa.Integer(), default=0),
                sa.Column("currency", sa.String(8), default="CNY"),
                sa.Column("settled", sa.Boolean(), default=False),
                sa.Column("raw", JSONB, default=dict),
                sa.Column("created_at", sa.DateTime(), nullable=True),
                sa.UniqueConstraint(
                    "work_id", "channel_code", "period_key", "source",
                    name="uq_metric_work_channel_period_source",
                ),
            ),
        ),
        (
            "royalty_report_imports",
            lambda: op.create_table(
                "royalty_report_imports",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("source", sa.String(32), nullable=False),
                sa.Column("distributor_code", sa.String(32), nullable=True),
                sa.Column("filename", sa.String(255), nullable=True),
                sa.Column("file_hash", sa.String(64), nullable=True),
                sa.Column("status", sa.String(24), default="parsed"),
                sa.Column("row_count", sa.Integer(), default=0),
                sa.Column("error_message", sa.Text(), nullable=True),
                sa.Column("storage_key", sa.String(512), nullable=True),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ),
        ),
        (
            "commission_rules",
            lambda: op.create_table(
                "commission_rules",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("mode", sa.String(24), default="label"),
                sa.Column("channel_code", sa.String(32), default="*"),
                sa.Column("user_level", sa.String(32), default="*"),
                sa.Column("rate_percent", sa.Integer(), default=20),
                sa.Column("enabled", sa.Boolean(), default=True),
            ),
        ),
        (
            "originality_checks",
            lambda: op.create_table(
                "originality_checks",
                sa.Column("id", UUID(as_uuid=True), primary_key=True),
                sa.Column("work_id", UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
                sa.Column("content_hash", sa.String(64), nullable=True),
                sa.Column("collision_count", sa.Integer(), default=0),
                sa.Column("risk_score", sa.Integer(), default=0),
                sa.Column("detail", JSONB, default=dict),
                sa.Column("created_at", sa.DateTime(), nullable=True),
            ),
        ),
    ]
    for name, create in tables:
        if not _table_exists(bind, name):
            create()


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "originality_checks",
        "commission_rules",
        "royalty_report_imports",
        "platform_metric_snapshots",
        "withdrawals",
        "payout_accounts",
        "settlement_lines",
        "settlement_batches",
        "royalty_ledger_entries",
        "royalty_wallets",
        "distribution_licenses",
        "creator_identity_bindings",
        "distribution_deliveries",
        "distribution_channels",
        "distributor_accounts",
        "release_metadata",
        "releases",
    ):
        if _table_exists(bind, table):
            op.drop_table(table)
    if _table_exists(bind, "works"):
        for col in ("commercial_cleared_at", "isrc", "release_status"):
            if _column_exists(bind, "works", col):
                op.drop_column("works", col)
    if _table_exists(bind, "users"):
        for col in ("kyc_status", "creator_level"):
            if _column_exists(bind, "users", col):
                op.drop_column("users", col)
