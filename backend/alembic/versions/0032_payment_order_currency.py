"""Payment order currency + provider reference (Stripe orders)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_payment_order_currency"
down_revision = "0031_vendor_key_inflight"
branch_labels = None
depends_on = None

PROVIDER_REF_INDEX = "ix_payment_orders_provider_ref"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "payment_orders" not in set(insp.get_table_names()):
        return

    cols = {c["name"] for c in insp.get_columns("payment_orders")}
    if "currency" not in cols:
        op.add_column(
            "payment_orders",
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        )
        # Stripe charges USD cents; every pre-existing order was a CN channel in fen.
        op.execute(sa.text("UPDATE payment_orders SET currency = 'USD' WHERE channel LIKE 'stripe%'"))
    if "provider_ref" not in cols:
        op.add_column("payment_orders", sa.Column("provider_ref", sa.String(length=128), nullable=True))

    existing = {ix["name"] for ix in insp.get_indexes("payment_orders")}
    if PROVIDER_REF_INDEX not in existing:
        op.create_index(PROVIDER_REF_INDEX, "payment_orders", ["provider_ref"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "payment_orders" not in set(insp.get_table_names()):
        return
    existing = {ix["name"] for ix in insp.get_indexes("payment_orders")}
    if PROVIDER_REF_INDEX in existing:
        op.drop_index(PROVIDER_REF_INDEX, table_name="payment_orders")
    cols = {c["name"] for c in insp.get_columns("payment_orders")}
    if "provider_ref" in cols:
        op.drop_column("payment_orders", "provider_ref")
    if "currency" in cols:
        op.drop_column("payment_orders", "currency")
