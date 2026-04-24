"""add extraction payload

Revision ID: 202604240002
Revises: 202604240001
Create Date: 2026-04-24 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "202604240002"
down_revision: Union[str, None] = "202604240001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_jobs",
        sa.Column("extraction", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_jobs", "extraction")
