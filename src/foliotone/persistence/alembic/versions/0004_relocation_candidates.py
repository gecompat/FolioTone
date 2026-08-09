"""Add persisted file relocation candidates.

Revision ID: 0004_relocation_candidates
Revises: 0003_deletion_confirmation
Created: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_relocation_candidates"
down_revision: str | None = "0003_deletion_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)
ENUM = sa.String(48)
DATETIME = sa.String(40)


def upgrade() -> None:
    op.create_table(
        "file_relocation_candidates",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_run_id", ID, sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("source_file_id", ID, sa.ForeignKey("file_records.id"), nullable=False),
        sa.Column("target_file_id", ID, sa.ForeignKey("file_records.id"), nullable=False),
        sa.Column("kind", ENUM, nullable=False),
        sa.Column("source_relative_path", sa.Text(), nullable=False),
        sa.Column("target_relative_path", sa.Text(), nullable=False),
        sa.Column(
            "source_fingerprint_id",
            ID,
            sa.ForeignKey("fingerprints.id"),
            nullable=False,
        ),
        sa.Column(
            "target_fingerprint_id",
            ID,
            sa.ForeignKey("fingerprints.id"),
            nullable=False,
        ),
        sa.Column("fingerprint_kind", sa.Text(), nullable=False),
        sa.Column("fingerprint_algorithm", sa.Text(), nullable=False),
        sa.Column("fingerprint_algorithm_version", sa.Text(), nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.UniqueConstraint(
            "scan_run_id",
            "source_file_id",
            "target_file_id",
            name="uq_relocation_candidate_run_pair",
        ),
    )
    op.create_index(
        "ix_file_relocation_candidates_run",
        "file_relocation_candidates",
        ["scan_run_id"],
    )
    op.create_index(
        "ix_file_relocation_candidates_source_target",
        "file_relocation_candidates",
        ["source_file_id", "target_file_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_file_relocation_candidates_source_target",
        table_name="file_relocation_candidates",
    )
    op.drop_index(
        "ix_file_relocation_candidates_run",
        table_name="file_relocation_candidates",
    )
    op.drop_table("file_relocation_candidates")
