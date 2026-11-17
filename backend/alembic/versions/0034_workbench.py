"""MixGraph workbench sessions and effect packs."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_workbench"
down_revision = "0033_delivery_tier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()

    if "effect_packs" not in tables:
        op.create_table(
            "effect_packs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("slug", sa.String(64), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("mix_graph", json_type, nullable=True),
            sa.Column("price_credits", sa.Integer(), server_default="0"),
            sa.Column("is_official", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("status", sa.String(20), server_default="draft"),
            sa.Column("purchase_count", sa.Integer(), server_default="0"),
            sa.Column("preview_url", sa.String(512), nullable=True),
            sa.Column("tags", json_type, nullable=True),
            sa.Column("locale_titles", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_effect_packs_slug", "effect_packs", ["slug"], unique=True)
        op.create_index("ix_effect_packs_owner_id", "effect_packs", ["owner_id"])
        op.create_index("ix_effect_packs_is_official", "effect_packs", ["is_official"])
        op.create_index("ix_effect_packs_status", "effect_packs", ["status"])
        op.create_index("ix_effect_packs_status_official", "effect_packs", ["status", "is_official"])

    if "effect_pack_purchases" not in tables:
        op.create_table(
            "effect_pack_purchases",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("pack_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("effect_packs.id"), nullable=False),
            sa.Column("buyer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("credits_paid", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("pack_id", "buyer_id", name="uq_effect_pack_buyer"),
        )

    if "workbench_sessions" not in tables:
        op.create_table(
            "workbench_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("source_work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
            sa.Column("mix_graph", json_type, nullable=True),
            sa.Column("intensity", sa.Float(), server_default="1"),
            sa.Column("applied_pack_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("effect_packs.id"), nullable=True),
            sa.Column("edit_lanes", json_type, nullable=True),
            sa.Column("preview_url", sa.String(512), nullable=True),
            sa.Column("last_render_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_jobs.id"), nullable=True),
            sa.Column("last_result_work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workbench_sessions_owner_id", "workbench_sessions", ["owner_id"])
        op.create_index("ix_workbench_sessions_source_work_id", "workbench_sessions", ["source_work_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "workbench_sessions" in tables:
        op.drop_table("workbench_sessions")
    if "effect_pack_purchases" in tables:
        op.drop_table("effect_pack_purchases")
    if "effect_packs" in tables:
        op.drop_table("effect_packs")
