"""add users table and customer user link

Revision ID: 0003_users_auth_roles
Revises: 0002_customer_company_nullable
Create Date: 2026-02-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_users_auth_roles"
down_revision = "0002_customer_company_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.add_column("customers", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_customers_user_id", "customers", ["user_id"])
    op.create_foreign_key("fk_customers_user_id", "customers", "users", ["user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_customers_user_id", "customers", type_="foreignkey")
    op.drop_constraint("uq_customers_user_id", "customers", type_="unique")
    op.drop_column("customers", "user_id")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
