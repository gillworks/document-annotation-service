"""add annotation tasks

Revision ID: 202604240003
Revises: 202604240002
Create Date: 2026-04-24 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "202604240003"
down_revision: Union[str, None] = "202604240002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_jobs",
        sa.Column(
            "annotation_tasks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("document_jobs", "annotation_tasks")
