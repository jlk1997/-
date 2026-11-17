"""MixGraph v2 session stack, pack need tags, and demand briefs."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_workbench_v2"
down_revision = "0034_workbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()

    if "effect_packs" in tables:
        cols = {col["name"] for col in insp.get_columns("effect_packs")}
        if "need_tags" not in cols:
            op.add_column("effect_packs", sa.Column("need_tags", json_type, nullable=True))
        if "kind" not in cols:
            op.add_column("effect_packs", sa.Column("kind", sa.String(20), server_default="scene"))
            op.create_index("ix_effect_packs_kind", "effect_packs", ["kind"])
        if "apply_count" not in cols:
            op.add_column("effect_packs", sa.Column("apply_count", sa.Integer(), server_default="0"))
        if "bounce_count" not in cols:
            op.add_column("effect_packs", sa.Column("bounce_count", sa.Integer(), server_default="0"))

    if "workbench_sessions" in tables:
        cols = {col["name"] for col in insp.get_columns("workbench_sessions")}
        if "previous_result_work_id" not in cols:
            op.add_column(
                "workbench_sessions",
                sa.Column("previous_result_work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=True),
            )
        if "op_stack" not in cols:
            op.add_column("workbench_sessions", sa.Column("op_stack", json_type, nullable=True))

    if "pack_demands" not in tables:
        op.create_table(
            "pack_demands",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("works.id"), nullable=False),
            sa.Column("brief", sa.String(400), nullable=False),
            sa.Column("need_tags", json_type, nullable=True),
            sa.Column("bid_credits", sa.Integer(), server_default="0"),
            sa.Column("status", sa.String(20), server_default="open"),
            sa.Column("claimed_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("pack_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("effect_packs.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_pack_demands_owner_id", "pack_demands", ["owner_id"])
        op.create_index("ix_pack_demands_work_id", "pack_demands", ["work_id"])
        op.create_index("ix_pack_demands_status", "pack_demands", ["status"])
        op.create_index("ix_pack_demands_claimed_by_id", "pack_demands", ["claimed_by_id"])
        op.create_index("ix_pack_demands_status_created", "pack_demands", ["status", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "pack_demands" in tables:
        op.drop_table("pack_demands")
