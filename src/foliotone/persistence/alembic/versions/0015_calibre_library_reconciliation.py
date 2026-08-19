"""Persist immutable Calibre library reconciliation evidence.

Revision ID: 0015_calibre_library_reconciliation
Revises: 0014_relation_candidates
Created: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0015_calibre_library_reconciliation"
down_revision: str | None = "0014_relation_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calibre_library_snapshots",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_root_id", ID, sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column("source_scan_run_id", ID, sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("library_identity_digest", sa.Text(), nullable=False),
        sa.Column("initial_inventory_digest", sa.Text()),
        sa.Column("final_inventory_digest", sa.Text()),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("started_at", DATETIME, nullable=False),
        sa.Column("completed_at", DATETIME),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','INVALIDATED','FAILED')",
            name="ck_calibre_library_snapshots_status",
        ),
        sa.CheckConstraint(
            "profile = 'calibre-library-snapshot/v1' "
            "AND adapter_version = 'calibredb-library/1' "
            "AND parser_version = 'calibre-library-parser/1'",
            name="ck_calibre_library_snapshots_contract",
        ),
        sa.CheckConstraint(
            "length(library_identity_digest) = 64 "
            "AND library_identity_digest NOT GLOB '*[^0-9a-f]*' "
            "AND (initial_inventory_digest IS NULL OR "
            "(length(initial_inventory_digest) = 64 "
            "AND initial_inventory_digest NOT GLOB '*[^0-9a-f]*')) "
            "AND (final_inventory_digest IS NULL OR "
            "(length(final_inventory_digest) = 64 "
            "AND final_inventory_digest NOT GLOB '*[^0-9a-f]*'))",
            name="ck_calibre_library_snapshots_digests",
        ),
    )
    op.create_table(
        "calibre_library_records",
        sa.Column("id", ID, primary_key=True),
        sa.Column("snapshot_id", ID, sa.ForeignKey("calibre_library_snapshots.id"), nullable=False),
        sa.Column("calibre_record_id", sa.Integer(), nullable=False),
        sa.Column("metadata_fingerprint", sa.Text(), nullable=False),
        sa.Column("calibre_uuid", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("authors_json", sa.Text(), nullable=False),
        sa.Column("identifiers_json", sa.Text(), nullable=False),
        sa.Column("last_modified_at", DATETIME),
        sa.CheckConstraint("calibre_record_id >= 0", name="ck_calibre_library_records_calibre_id"),
        sa.CheckConstraint(
            "length(metadata_fingerprint) = 64 "
            "AND metadata_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_calibre_library_records_fingerprint",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "calibre_record_id", name="uq_calibre_library_records_snapshot_record"
        ),
    )
    op.create_table(
        "calibre_library_formats",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "record_snapshot_id", ID, sa.ForeignKey("calibre_library_records.id"), nullable=False
        ),
        sa.Column("format_label", ENUM, nullable=False),
        sa.Column("relative_locator", sa.Text(), nullable=False),
        sa.Column("declared_size_bytes", sa.Integer()),
        sa.Column("observation_id", ID, sa.ForeignKey("file_observations.id")),
        sa.CheckConstraint(
            "declared_size_bytes IS NULL OR declared_size_bytes >= 0",
            name="ck_calibre_library_formats_size",
        ),
        sa.CheckConstraint(
            "length(format_label) BETWEEN 1 AND 16 "
            "AND format_label NOT GLOB '*[^A-Z0-9]*'",
            name="ck_calibre_library_formats_label",
        ),
        sa.UniqueConstraint(
            "record_snapshot_id",
            "format_label",
            "relative_locator",
            name="uq_calibre_library_formats_record_locator",
        ),
    )
    op.create_table(
        "calibre_library_sidecars",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "record_snapshot_id", ID, sa.ForeignKey("calibre_library_records.id"), nullable=False
        ),
        sa.Column("kind", ENUM, nullable=False),
        sa.Column("relative_locator", sa.Text(), nullable=False),
        sa.Column("observation_id", ID, sa.ForeignKey("file_observations.id")),
        sa.CheckConstraint(
            "kind IN ('METADATA_OPF','COVER','EXTRA_DATA','KNOWN_SIDECAR','UNKNOWN_SIDECAR')",
            name="ck_calibre_library_sidecars_kind",
        ),
        sa.UniqueConstraint(
            "record_snapshot_id",
            "kind",
            "relative_locator",
            name="uq_calibre_library_sidecars_record_locator",
        ),
    )
    op.create_table(
        "calibre_reconciliation_findings",
        sa.Column("id", ID, primary_key=True),
        sa.Column("snapshot_id", ID, sa.ForeignKey("calibre_library_snapshots.id"), nullable=False),
        sa.Column("code", ENUM, nullable=False),
        sa.Column("finding_fingerprint", sa.Text(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.CheckConstraint(
            "code IN ('FILESYSTEM_ONLY','CALIBRE_RECORD_WITHOUT_FILE',"
            "'CALIBRE_DUPLICATE_RECORD_CANDIDATE','CALIBRE_MULTI_FORMAT_RECORD',"
            "'CALIBRE_METADATA_CONFLICT','CALIBRE_AUTHORITY_CONFLICT',"
            "'CALIBRE_SIDECAR_DEPENDENCY')",
            name="ck_calibre_reconciliation_findings_code",
        ),
        sa.CheckConstraint(
            "length(finding_fingerprint) = 64 "
            "AND finding_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_calibre_reconciliation_findings_fingerprint",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "code",
            "finding_fingerprint",
            name="uq_calibre_reconciliation_findings_semantic",
        ),
    )
    op.create_table(
        "calibre_reconciliation_finding_refs",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "finding_id", ID, sa.ForeignKey("calibre_reconciliation_findings.id"), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("ref_kind", ENUM, nullable=False),
        sa.Column("ref_id", ID, nullable=False),
        sa.Column("role", ENUM, nullable=False),
        sa.Column("material_fingerprint", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_calibre_reconciliation_finding_refs_ordinal"),
        sa.CheckConstraint(
            "ref_kind IN ('CALIBRE_RECORD','CALIBRE_FORMAT','CALIBRE_SIDECAR',"
            "'FILE_OBSERVATION','VALUE_ASSERTION','FINGERPRINT','TOOL_RESULT',"
            "'RESOLUTION_CANDIDATE','REVIEW_ITEM')",
            name="ck_calibre_reconciliation_finding_refs_kind",
        ),
        sa.CheckConstraint(
            "role IN ('PRIMARY','RELATED','SUPPORTING','CONTRADICTING','REVIEW')",
            name="ck_calibre_reconciliation_finding_refs_role",
        ),
        sa.CheckConstraint(
            "length(material_fingerprint) = 64 "
            "AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_calibre_reconciliation_finding_refs_fingerprint",
        ),
        sa.UniqueConstraint(
            "finding_id", "ordinal", name="uq_calibre_reconciliation_finding_refs_ordinal"
        ),
    )
    op.create_index(
        "ix_calibre_library_snapshots_root_scan_created",
        "calibre_library_snapshots",
        ["scan_root_id", "source_scan_run_id", "started_at", "id"],
    )
    op.create_index(
        "ix_calibre_library_formats_observation",
        "calibre_library_formats",
        ["observation_id", "record_snapshot_id"],
    )
    op.create_index(
        "ix_calibre_library_sidecars_observation",
        "calibre_library_sidecars",
        ["observation_id", "record_snapshot_id"],
    )
    op.create_index(
        "ix_calibre_reconciliation_findings_snapshot_created",
        "calibre_reconciliation_findings",
        ["snapshot_id", "created_at", "id"],
    )
    op.create_index(
        "ix_calibre_reconciliation_finding_refs_reference",
        "calibre_reconciliation_finding_refs",
        ["ref_kind", "ref_id", "finding_id"],
    )


def downgrade() -> None:
    tables = (
        "calibre_library_snapshots",
        "calibre_library_records",
        "calibre_library_formats",
        "calibre_library_sidecars",
        "calibre_reconciliation_findings",
        "calibre_reconciliation_finding_refs",
    )
    populated = (
        op.get_bind()
        .execute(
            sa.text(" UNION ALL ".join(f"SELECT 1 FROM {table}" for table in tables) + " LIMIT 1")
        )
        .first()
    )
    if populated is not None:
        raise RuntimeError("calibre library reconciliation data prevents migration downgrade")
    op.drop_index(
        "ix_calibre_reconciliation_finding_refs_reference",
        table_name="calibre_reconciliation_finding_refs",
    )
    op.drop_index(
        "ix_calibre_reconciliation_findings_snapshot_created",
        table_name="calibre_reconciliation_findings",
    )
    op.drop_index("ix_calibre_library_sidecars_observation", table_name="calibre_library_sidecars")
    op.drop_index("ix_calibre_library_formats_observation", table_name="calibre_library_formats")
    op.drop_index(
        "ix_calibre_library_snapshots_root_scan_created", table_name="calibre_library_snapshots"
    )
    for table in reversed(tables):
        op.drop_table(table)
