"""Add auditable scan resume lineage.

Revision ID: 0005_scan_resume_lineage
Revises: 0004_relocation_candidates
Created: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_scan_resume_lineage"
down_revision: str | None = "0004_relocation_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)


def upgrade() -> None:
    with op.batch_alter_table("scan_runs") as batch:
        batch.add_column(sa.Column("resumed_from_run_id", ID, nullable=True))
        batch.create_foreign_key(
            "fk_scan_runs_resumed_from_run_id",
            "scan_runs",
            ["resumed_from_run_id"],
            ["id"],
        )
    op.create_index(
        "ix_scan_runs_resumed_from_run_id",
        "scan_runs",
        ["resumed_from_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_runs_resumed_from_run_id", table_name="scan_runs")
    with op.batch_alter_table("scan_runs") as batch:
        batch.drop_constraint("fk_scan_runs_resumed_from_run_id", type_="foreignkey")
        batch.drop_column("resumed_from_run_id")
