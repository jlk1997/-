"""Add delivery_tier to distribution_deliveries."""
import sqlalchemy as sa
from alembic import op

revision = "0033_delivery_tier"
down_revision = "0032_payment_order_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "distribution_deliveries" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("distribution_deliveries")}
    if "delivery_tier" not in cols:
        op.add_column("distribution_deliveries", sa.Column("delivery_tier", sa.String(24), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "distribution_deliveries" not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns("distribution_deliveries")}
    if "delivery_tier" in cols:
        op.drop_column("distribution_deliveries", "delivery_tier")
