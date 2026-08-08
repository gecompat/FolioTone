"""Create the initial FolioTone persistence schema.

Revision ID: 0001_initial
Revises: none
Created: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)
ENUM = sa.String(48)
DATETIME = sa.String(40)


def _provenance_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text()),
        sa.Column("observed_at", DATETIME, nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "scan_roots",
        sa.Column("id", ID, primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", ENUM, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "scan_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_root_id", ID, sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column("started_at", DATETIME, nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("completed_at", DATETIME),
    )
    op.create_table(
        "file_records",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_root_id", ID, sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("modified_at", DATETIME, nullable=False),
        sa.Column("media_type", ENUM, nullable=False),
        sa.Column("presence_state", ENUM, nullable=False),
        sa.Column("first_seen_at", DATETIME, nullable=False),
        sa.Column("last_seen_at", DATETIME, nullable=False),
        sa.UniqueConstraint("scan_root_id", "relative_path", name="uq_file_root_path"),
    )
    op.create_table(
        "file_observations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("file_id", ID, sa.ForeignKey("file_records.id"), nullable=False),
        sa.Column("scan_run_id", ID, sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("modified_at", DATETIME, nullable=False),
        sa.Column("observed_at", DATETIME, nullable=False),
    )
    op.create_table(
        "value_assertions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("state", ENUM, nullable=False),
        *_provenance_columns(),
        sa.Column("confidence", sa.Float()),
        sa.Column("explanation", sa.Text()),
    )
    op.create_table(
        "agents",
        sa.Column("id", ID, primary_key=True),
        sa.Column("agent_type", ENUM, nullable=False),
    )
    op.create_table(
        "agent_names",
        sa.Column("id", ID, primary_key=True),
        sa.Column("agent_id", ID, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name_type", ENUM, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text()),
        sa.Column("language", sa.String(32)),
        sa.Column("script", sa.String(32)),
        *_provenance_columns(),
    )
    op.create_table(
        "external_identifiers",
        sa.Column("id", ID, primary_key=True),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        *_provenance_columns(),
        sa.UniqueConstraint(
            "target_kind",
            "target_id",
            "namespace",
            "value",
            name="uq_external_identifier",
        ),
    )
    op.create_table(
        "contributions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("agent_id", ID, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("credited_as", sa.Text()),
        *_provenance_columns(),
    )
    op.create_table(
        "works",
        sa.Column("id", ID, primary_key=True),
        sa.Column("canonical_title", sa.Text()),
    )
    op.create_table(
        "editions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("work_id", ID, sa.ForeignKey("works.id"), nullable=False),
        sa.Column("canonical_title", sa.Text()),
        sa.Column("language", sa.String(32)),
    )
    op.create_table(
        "series",
        sa.Column("id", ID, primary_key=True),
        sa.Column("canonical_name", sa.Text()),
    )
    op.create_table(
        "series_memberships",
        sa.Column("id", ID, primary_key=True),
        sa.Column("series_id", ID, sa.ForeignKey("series.id"), nullable=False),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("position", sa.Text()),
    )
    op.create_table(
        "music_works",
        sa.Column("id", ID, primary_key=True),
        sa.Column("canonical_title", sa.Text()),
    )
    op.create_table(
        "music_work_relations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("source_work_id", ID, sa.ForeignKey("music_works.id"), nullable=False),
        sa.Column("target_work_id", ID, sa.ForeignKey("music_works.id"), nullable=False),
        sa.Column("relation_type", ENUM, nullable=False),
    )
    op.create_table(
        "catalog_designations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("music_work_id", ID, sa.ForeignKey("music_works.id"), nullable=False),
        sa.Column("system", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "music_work_id",
            "system",
            "value",
            name="uq_catalog_designation",
        ),
    )
    op.create_table(
        "recordings",
        sa.Column("id", ID, primary_key=True),
        sa.Column("canonical_title", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
    )
    op.create_table(
        "release_groups",
        sa.Column("id", ID, primary_key=True),
        sa.Column("canonical_title", sa.Text()),
    )
    op.create_table(
        "releases",
        sa.Column("id", ID, primary_key=True),
        sa.Column("release_group_id", ID, sa.ForeignKey("release_groups.id")),
        sa.Column("canonical_title", sa.Text()),
        sa.Column("release_date", sa.Text()),
    )
    op.create_table(
        "release_recordings",
        sa.Column("id", ID, primary_key=True),
        sa.Column("release_id", ID, sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("recording_id", ID, sa.ForeignKey("recordings.id"), nullable=False),
        sa.Column("disc_number", sa.Integer()),
        sa.Column("track_number", sa.Integer()),
        sa.Column("observed_title", sa.Text()),
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("capability", ENUM, nullable=False),
        sa.Column("input_identity", sa.Text(), nullable=False),
        sa.Column("config_identity", sa.Text()),
        sa.Column("started_at", DATETIME, nullable=False),
        sa.Column("finished_at", DATETIME),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("error_summary", sa.Text()),
    )
    op.create_table(
        "tool_results",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "execution_id",
            ID,
            sa.ForeignKey("tool_executions.id"),
            nullable=False,
        ),
        sa.Column("result_type", sa.Text(), nullable=False),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("explanation", sa.Text()),
    )
    op.create_table(
        "classification_assertions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("taxonomy", sa.Text()),
        sa.Column("confidence", sa.Float()),
        *_provenance_columns(),
    )
    op.create_table(
        "fingerprints",
        sa.Column("id", ID, primary_key=True),
        sa.Column("target_kind", ENUM, nullable=False),
        sa.Column("target_id", ID, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.Column("tool_execution_id", ID, sa.ForeignKey("tool_executions.id")),
    )
    op.create_table(
        "relations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("left_kind", ENUM, nullable=False),
        sa.Column("left_id", ID, nullable=False),
        sa.Column("right_kind", ENUM, nullable=False),
        sa.Column("right_id", ID, nullable=False),
        sa.Column("relation_type", ENUM, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column("id", ID, primary_key=True),
        sa.Column("relation_id", ID, sa.ForeignKey("relations.id"), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("strength", sa.Float()),
        sa.Column("tool_execution_id", ID, sa.ForeignKey("tool_executions.id")),
        *_provenance_columns(),
    )


def downgrade() -> None:
    for table_name in (
        "evidence",
        "relations",
        "fingerprints",
        "classification_assertions",
        "tool_results",
        "tool_executions",
        "release_recordings",
        "releases",
        "release_groups",
        "recordings",
        "catalog_designations",
        "music_work_relations",
        "music_works",
        "series_memberships",
        "series",
        "editions",
        "works",
        "contributions",
        "external_identifiers",
        "agent_names",
        "agents",
        "value_assertions",
        "file_observations",
        "file_records",
        "scan_runs",
        "scan_roots",
    ):
        op.drop_table(table_name)
