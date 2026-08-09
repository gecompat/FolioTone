"""Add persisted absence state for conservative deletion confirmation.

Revision ID: 0003_deletion_confirmation
Revises: 0002_incremental_index
Created: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_deletion_confirmation"
down_revision: str | None = "0002_incremental_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATETIME = sa.String(40)


def upgrade() -> None:
    op.add_column(
        "file_records",
        sa.Column("missing_since_at", DATETIME, nullable=True),
    )
    op.add_column(
        "file_records",
        sa.Column(
            "consecutive_missing_scans",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("file_records", "consecutive_missing_scans")
    op.drop_column("file_records", "missing_since_at")
