"""Add processing lease and persistent failure budget.

Revision ID: 20260817_0002
Revises: 20260817_0001
Create Date: 2026-08-17 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0002"
down_revision: str | None = "20260817_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("processing_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("processing_failures", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("payments", "processing_failures")
    op.drop_column("payments", "processing_lease_until")
    op.drop_column("payments", "processing_token")
