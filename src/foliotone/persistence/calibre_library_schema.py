"""EB-07 immutable Calibre library reconciliation schema."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

calibre_library_snapshots = Table(
    "calibre_library_snapshots",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("profile", Text, nullable=False),
    Column("adapter_version", Text, nullable=False),
    Column("tool_version", Text, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("library_identity_digest", Text, nullable=False),
    Column("initial_inventory_digest", Text),
    Column("final_inventory_digest", Text),
    Column("status", ENUM, nullable=False),
    Column("started_at", DATETIME, nullable=False),
    Column("completed_at", DATETIME),
    CheckConstraint(
        "status IN ('RUNNING','COMPLETED','INVALIDATED','FAILED')",
        name="ck_calibre_library_snapshots_status",
    ),
    CheckConstraint(
        "profile = 'calibre-library-snapshot/v1' "
        "AND adapter_version = 'calibredb-library/1' "
        "AND parser_version = 'calibre-library-parser/1'",
        name="ck_calibre_library_snapshots_contract",
    ),
    CheckConstraint(
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
calibre_library_records = Table(
    "calibre_library_records",
    metadata,
    Column("id", ID, primary_key=True),
    Column("snapshot_id", ID, ForeignKey("calibre_library_snapshots.id"), nullable=False),
    Column("calibre_record_id", Integer, nullable=False),
    Column("metadata_fingerprint", Text, nullable=False),
    Column("calibre_uuid", Text),
    Column("title", Text),
    Column("authors_json", Text, nullable=False),
    Column("identifiers_json", Text, nullable=False),
    Column("last_modified_at", DATETIME),
    CheckConstraint("calibre_record_id >= 0", name="ck_calibre_library_records_calibre_id"),
    CheckConstraint(
        "length(metadata_fingerprint) = 64 "
        "AND metadata_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_calibre_library_records_fingerprint",
    ),
    UniqueConstraint(
        "snapshot_id", "calibre_record_id", name="uq_calibre_library_records_snapshot_record"
    ),
)
calibre_library_formats = Table(
    "calibre_library_formats",
    metadata,
    Column("id", ID, primary_key=True),
    Column("record_snapshot_id", ID, ForeignKey("calibre_library_records.id"), nullable=False),
    Column("format_label", ENUM, nullable=False),
    Column("relative_locator", Text, nullable=False),
    Column("declared_size_bytes", Integer),
    Column("observation_id", ID, ForeignKey("file_observations.id")),
    CheckConstraint(
        "declared_size_bytes IS NULL OR declared_size_bytes >= 0",
        name="ck_calibre_library_formats_size",
    ),
    CheckConstraint(
        "length(format_label) BETWEEN 1 AND 16 "
        "AND format_label NOT GLOB '*[^A-Z0-9]*'",
        name="ck_calibre_library_formats_label",
    ),
    UniqueConstraint(
        "record_snapshot_id",
        "format_label",
        "relative_locator",
        name="uq_calibre_library_formats_record_locator",
    ),
)
calibre_library_sidecars = Table(
    "calibre_library_sidecars",
    metadata,
    Column("id", ID, primary_key=True),
    Column("record_snapshot_id", ID, ForeignKey("calibre_library_records.id"), nullable=False),
    Column("kind", ENUM, nullable=False),
    Column("relative_locator", Text, nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id")),
    CheckConstraint(
        "kind IN ('METADATA_OPF','COVER','EXTRA_DATA','KNOWN_SIDECAR','UNKNOWN_SIDECAR')",
        name="ck_calibre_library_sidecars_kind",
    ),
    UniqueConstraint(
        "record_snapshot_id",
        "kind",
        "relative_locator",
        name="uq_calibre_library_sidecars_record_locator",
    ),
)
calibre_reconciliation_findings = Table(
    "calibre_reconciliation_findings",
    metadata,
    Column("id", ID, primary_key=True),
    Column("snapshot_id", ID, ForeignKey("calibre_library_snapshots.id"), nullable=False),
    Column("code", ENUM, nullable=False),
    Column("finding_fingerprint", Text, nullable=False),
    Column("review_required", Boolean, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "code IN ('FILESYSTEM_ONLY','CALIBRE_RECORD_WITHOUT_FILE',"
        "'CALIBRE_DUPLICATE_RECORD_CANDIDATE','CALIBRE_MULTI_FORMAT_RECORD',"
        "'CALIBRE_METADATA_CONFLICT','CALIBRE_AUTHORITY_CONFLICT',"
        "'CALIBRE_SIDECAR_DEPENDENCY')",
        name="ck_calibre_reconciliation_findings_code",
    ),
    CheckConstraint(
        "length(finding_fingerprint) = 64 "
        "AND finding_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_calibre_reconciliation_findings_fingerprint",
    ),
    UniqueConstraint(
        "snapshot_id",
        "code",
        "finding_fingerprint",
        name="uq_calibre_reconciliation_findings_semantic",
    ),
)
calibre_reconciliation_finding_refs = Table(
    "calibre_reconciliation_finding_refs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("finding_id", ID, ForeignKey("calibre_reconciliation_findings.id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("ref_kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("role", ENUM, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint("ordinal >= 0", name="ck_calibre_reconciliation_finding_refs_ordinal"),
    CheckConstraint(
        "ref_kind IN ('CALIBRE_RECORD','CALIBRE_FORMAT','CALIBRE_SIDECAR',"
        "'FILE_OBSERVATION','VALUE_ASSERTION','FINGERPRINT','TOOL_RESULT',"
        "'RESOLUTION_CANDIDATE','REVIEW_ITEM')",
        name="ck_calibre_reconciliation_finding_refs_kind",
    ),
    CheckConstraint(
        "role IN ('PRIMARY','RELATED','SUPPORTING','CONTRADICTING','REVIEW')",
        name="ck_calibre_reconciliation_finding_refs_role",
    ),
    CheckConstraint(
        "length(material_fingerprint) = 64 "
        "AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_calibre_reconciliation_finding_refs_fingerprint",
    ),
    UniqueConstraint(
        "finding_id", "ordinal", name="uq_calibre_reconciliation_finding_refs_ordinal"
    ),
)
Index(
    "ix_calibre_library_snapshots_root_scan_created",
    calibre_library_snapshots.c.scan_root_id,
    calibre_library_snapshots.c.source_scan_run_id,
    calibre_library_snapshots.c.started_at,
    calibre_library_snapshots.c.id,
)
Index(
    "ix_calibre_library_formats_observation",
    calibre_library_formats.c.observation_id,
    calibre_library_formats.c.record_snapshot_id,
)
Index(
    "ix_calibre_library_sidecars_observation",
    calibre_library_sidecars.c.observation_id,
    calibre_library_sidecars.c.record_snapshot_id,
)
Index(
    "ix_calibre_reconciliation_findings_snapshot_created",
    calibre_reconciliation_findings.c.snapshot_id,
    calibre_reconciliation_findings.c.created_at,
    calibre_reconciliation_findings.c.id,
)
Index(
    "ix_calibre_reconciliation_finding_refs_reference",
    calibre_reconciliation_finding_refs.c.ref_kind,
    calibre_reconciliation_finding_refs.c.ref_id,
    calibre_reconciliation_finding_refs.c.finding_id,
)
