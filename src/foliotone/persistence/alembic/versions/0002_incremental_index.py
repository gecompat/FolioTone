"""Add incremental scan bookkeeping and tool runtime artifacts.

Revision ID: 0002_incremental_index
Revises: 0001_initial
Created: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_incremental_index"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)
ENUM = sa.String(48)
DATETIME = sa.String(40)


def upgrade() -> None:
    op.create_table(
        "file_scan_events",
        sa.Column("id", ID, primary_key=True),
        sa.Column("file_id", ID, sa.ForeignKey("file_records.id"), nullable=False),
        sa.Column("scan_run_id", ID, sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("change_state", ENUM, nullable=False),
        sa.Column("recorded_at", DATETIME, nullable=False),
        sa.Column("previous_relative_path", sa.Text()),
        sa.Column("current_relative_path", sa.Text()),
    )
    op.create_table(
        "tool_artifacts",
        sa.Column("id", ID, primary_key=True),
        sa.Column("execution_id", ID, sa.ForeignKey("tool_executions.id"), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_file_scan_events_run_state",
        "file_scan_events",
        ["scan_run_id", "change_state"],
    )
    op.create_index(
        "ix_file_observations_run_file",
        "file_observations",
        ["scan_run_id", "file_id"],
    )
    op.create_index(
        "ix_tool_artifacts_execution",
        "tool_artifacts",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_artifacts_execution", table_name="tool_artifacts")
    op.drop_index("ix_file_observations_run_file", table_name="file_observations")
    op.drop_index("ix_file_scan_events_run_state", table_name="file_scan_events")
    op.drop_table("tool_artifacts")
    op.drop_table("file_scan_events")
