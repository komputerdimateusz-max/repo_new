"""make customer company nullable

Revision ID: 0002_customer_company_nullable
Revises: 0001_mvp0_schema
Create Date: 2026-02-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_customer_company_nullable"
down_revision = "0001_mvp0_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch_op:
        batch_op.alter_column("company_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("customers") as batch_op:
        batch_op.alter_column("company_id", existing_type=sa.Integer(), nullable=False)
