"""Add fenced candidate-hash runs with durable path-free heartbeats.

Revision ID: 0011_candidate_hash_run_leases
Revises: 0010_candidate_hash_lookup_index
Created: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0011_candidate_hash_run_leases"
down_revision: str | None = "0010_candidate_hash_lookup_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ebook_candidate_hash_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "scan_root_id",
            ID,
            sa.ForeignKey("scan_roots.id"),
            nullable=False,
        ),
        sa.Column(
            "source_scan_run_id",
            ID,
            sa.ForeignKey("scan_runs.id"),
            nullable=False,
        ),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("phase", ENUM, nullable=False),
        sa.Column("started_at", DATETIME, nullable=False),
        sa.Column("heartbeat_at", DATETIME, nullable=False),
        sa.Column("finished_at", DATETIME),
        sa.Column("lease_token", sa.Text()),
        sa.Column("lease_expires_at", DATETIME),
        sa.Column("candidate_groups", sa.Integer()),
        sa.Column("candidate_observations", sa.Integer()),
        sa.Column("already_hashed", sa.Integer()),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("hashed_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("remaining_count", sa.Integer()),
    )
    op.create_index(
        "uq_ebook_candidate_hash_runs_active_root",
        "ebook_candidate_hash_runs",
        ["scan_root_id"],
        unique=True,
        sqlite_where=sa.text("status = 'RUNNING'"),
    )
    op.create_index(
        "ix_ebook_candidate_hash_runs_root_started",
        "ebook_candidate_hash_runs",
        ["scan_root_id", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ebook_candidate_hash_runs_root_started",
        table_name="ebook_candidate_hash_runs",
    )
    op.drop_index(
        "uq_ebook_candidate_hash_runs_active_root",
        table_name="ebook_candidate_hash_runs",
    )
    op.drop_table("ebook_candidate_hash_runs")
