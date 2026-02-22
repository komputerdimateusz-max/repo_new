"""order operational protections

Revision ID: 0004_order_ops_protections
Revises: 0003_users_auth_roles
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_order_ops_protections"
down_revision = "0003_users_auth_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("order_date", sa.Date(), nullable=True))
    op.execute("UPDATE orders SET order_date = date(created_at) WHERE order_date IS NULL")
    op.add_column("orders", sa.Column("order_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("order_seq", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("order_number", sa.String(length=16), nullable=True))
    op.add_column("orders", sa.Column("customer_edit_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    op.create_index(
        "uq_orders_customer_date_fingerprint",
        "orders",
        ["customer_id", "order_date", "order_fingerprint"],
        unique=True,
    )
    op.create_index("uq_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("uq_orders_order_date_seq", "orders", ["order_date", "order_seq"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_orders_order_date_seq", table_name="orders")
    op.drop_index("uq_orders_order_number", table_name="orders")
    op.drop_index("uq_orders_customer_date_fingerprint", table_name="orders")

    op.drop_column("orders", "customer_edit_count")
    op.drop_column("orders", "order_number")
    op.drop_column("orders", "order_seq")
    op.drop_column("orders", "order_fingerprint")
    op.drop_column("orders", "order_date")
