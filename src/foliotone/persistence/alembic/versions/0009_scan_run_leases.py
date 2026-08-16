"""Add recoverable scan-run leases.

Revision ID: 0009_scan_run_leases
Revises: 0008_ebook_collection_reports
Created: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_scan_run_leases"
down_revision: str | None = "0008_ebook_collection_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATETIME = sa.String(40)


def upgrade() -> None:
    with op.batch_alter_table("scan_runs") as batch:
        batch.add_column(sa.Column("lease_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", DATETIME, nullable=True))
    op.create_index(
        "ix_scan_runs_root_status_lease",
        "scan_runs",
        ["scan_root_id", "status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_runs_root_status_lease", table_name="scan_runs")
    with op.batch_alter_table("scan_runs") as batch:
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_token")
