"""Add resumable e-book collection batch state.

Revision ID: 0007_ebook_collection_batches
Revises: 0006_ebook_evidence_lookup_indexes
Created: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ebook_collection_batches"
down_revision: str | None = "0006_ebook_evidence_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)
ENUM = sa.String(48)
DATETIME = sa.String(40)


def upgrade() -> None:
    op.create_table(
        "ebook_collection_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_root_id", ID, sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column(
            "source_scan_run_id",
            ID,
            sa.ForeignKey("scan_runs.id"),
            nullable=False,
        ),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("analysis_profile", sa.Text(), nullable=False),
        sa.Column("fresh", sa.Boolean(), nullable=False),
        sa.Column("worker_count", sa.Integer(), nullable=False),
        sa.Column("started_at", DATETIME, nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("completed_at", DATETIME),
        sa.Column("lease_token", sa.Text()),
        sa.Column("lease_expires_at", DATETIME),
    )
    op.create_table(
        "ebook_collection_items",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "run_id",
            ID,
            sa.ForeignKey("ebook_collection_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            ID,
            sa.ForeignKey("file_observations.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("format_name", sa.Text(), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", DATETIME),
        sa.Column("completed_at", DATETIME),
        sa.Column("quality_status", sa.Text()),
        sa.Column("reused_step_count", sa.Integer(), nullable=False),
        sa.Column("executed_step_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.UniqueConstraint(
            "run_id",
            "observation_id",
            name="uq_ebook_collection_items_run_observation",
        ),
        sa.UniqueConstraint(
            "run_id",
            "ordinal",
            name="uq_ebook_collection_items_run_ordinal",
        ),
    )
    op.create_index(
        "ix_ebook_collection_runs_root_status",
        "ebook_collection_runs",
        ["scan_root_id", "status"],
    )
    op.create_index(
        "ix_ebook_collection_items_run_status_ordinal",
        "ebook_collection_items",
        ["run_id", "status", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ebook_collection_items_run_status_ordinal",
        table_name="ebook_collection_items",
    )
    op.drop_index(
        "ix_ebook_collection_runs_root_status",
        table_name="ebook_collection_runs",
    )
    op.drop_table("ebook_collection_items")
    op.drop_table("ebook_collection_runs")
