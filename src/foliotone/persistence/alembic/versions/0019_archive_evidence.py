"""Persist immutable archive evidence graphs.

Revision ID: 0019_archive_evidence
Revises: 0018_book_classification_projection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.archive_schema import ARCHIVE_EVIDENCE_TABLES

revision: str = "0019_archive_evidence"
down_revision: str | None = "0018_book_classification_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ARCHIVE_EVIDENCE_TABLES:
        table.create(bind)
    op.create_index(
        "ix_archive_observations_scan_run_observed",
        "archive_observations",
        ["scan_root_id", "source_scan_run_id", "observed_at", "id"],
    )
    reuse_baseline = [
        "archive_full_sha256",
        "volume_group_fingerprint",
        "provider_profile",
        "runner_profile",
        "parser_profile",
        "format_lock_sha256",
        "listing_profile",
        "extraction_profile",
        "safety_profile",
        "secret_version",
    ]
    op.create_index(
        "ix_archive_observations_listing_reuse",
        "archive_observations",
        [*reuse_baseline, "listing_status", "observed_at", "id"],
    )
    op.create_index(
        "ix_archive_observations_member_reuse",
        "archive_observations",
        [*reuse_baseline, "extraction_status", "observed_at", "id"],
    )
    op.create_index(
        "ix_archive_observation_sources_file",
        "archive_observation_sources",
        ["file_observation_id", "archive_observation_id"],
    )
    op.create_index(
        "ix_archive_observation_executions_tool",
        "archive_observation_executions",
        ["tool_execution_id", "archive_observation_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in ARCHIVE_EVIDENCE_TABLES
    )
    if bind.execute(sa.text(f"{union} LIMIT 1")).first() is not None:
        raise RuntimeError("archive evidence prevents migration downgrade")
    op.drop_index(
        "ix_archive_observation_executions_tool",
        table_name="archive_observation_executions",
    )
    op.drop_index(
        "ix_archive_observation_sources_file",
        table_name="archive_observation_sources",
    )
    op.drop_index(
        "ix_archive_observations_member_reuse",
        table_name="archive_observations",
    )
    op.drop_index(
        "ix_archive_observations_listing_reuse",
        table_name="archive_observations",
    )
    op.drop_index(
        "ix_archive_observations_scan_run_observed",
        table_name="archive_observations",
    )
    for table in reversed(ARCHIVE_EVIDENCE_TABLES):
        table.drop(bind)
