"""Create tenants and tickets tables.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'closed')", name="ck_tickets_status"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_tickets_priority"),
    )
    op.create_index("ix_tickets_tenant_id", "tickets", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_tenant_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_table("tenants")
