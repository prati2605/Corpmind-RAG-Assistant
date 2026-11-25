"""Add chunks.injection_flagged so the RAG prompt can warn about suspicious chunks.

Revision ID: b7d8e9f0a1b2
Revises: a1c2e3f4d5b6
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d8e9f0a1b2"
down_revision: str | None = "a1c2e3f4d5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("injection_flagged", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("chunks", "injection_flagged")
