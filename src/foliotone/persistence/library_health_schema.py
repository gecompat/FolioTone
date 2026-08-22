"""Insert-only SQLite schema for book-only Library Health v1."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.collection_state.health import (
    LIBRARY_HEALTH_DIMENSION_ORDER,
    LIBRARY_HEALTH_FINDING_ORDER,
    MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING,
)
from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

_SHA_CHECK = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"
_DIMENSIONS = ",".join(f"'{value.value}'" for value in LIBRARY_HEALTH_DIMENSION_ORDER)
_FINDING_CODES = ",".join(f"'{value.value}'" for value in LIBRARY_HEALTH_FINDING_ORDER)


library_health_snapshots = Table(
    "library_health_snapshots",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "collection_state_snapshot_id",
        ID,
        ForeignKey("collection_state_snapshots.id"),
        nullable=False,
    ),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("dimension_count", Integer, nullable=False),
    Column("finding_count", Integer, nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("collection_state_content_digest", Text, nullable=False),
    Column("query_index_content_digest", Text, nullable=False),
    Column("dimensions_digest", Text, nullable=False),
    Column("content_digest", Text, nullable=False),
    CheckConstraint(
        "profile='library-health/v1' AND serializer='canonical-json/v1'",
        name="ck_library_health_snapshots_contract",
    ),
    CheckConstraint(
        f"item_count>=0 AND dimension_count={len(LIBRARY_HEALTH_DIMENSION_ORDER)} "
        "AND finding_count>=0 AND sample_count>=0",
        name="ck_library_health_snapshots_counts",
    ),
    *(
        CheckConstraint(
            _SHA_CHECK.format(name=name),
            name=f"ck_library_health_snapshots_{name}",
        )
        for name in (
            "collection_state_content_digest",
            "query_index_content_digest",
            "dimensions_digest",
            "content_digest",
        )
    ),
    UniqueConstraint(
        "collection_state_snapshot_id",
        name="uq_library_health_snapshots_collection_state",
    ),
    UniqueConstraint("profile", "content_digest", name="uq_library_health_snapshots_content"),
)


library_health_dimensions = Table(
    "library_health_dimensions",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("library_health_snapshots.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("dimension", ENUM, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("coverage_state", ENUM, nullable=False),
    Column("assessed_item_count", Integer, nullable=False),
    Column("covered_item_count", Integer, nullable=False),
    Column("affected_item_count", Integer, nullable=False),
    Column("finding_count", Integer, nullable=False),
    Column("evidence_categories_json", Text, nullable=False),
    Column("dimension_digest", Text, nullable=False),
    CheckConstraint(
        f"ordinal BETWEEN 0 AND {len(LIBRARY_HEALTH_DIMENSION_ORDER) - 1}",
        name="ck_library_health_dimensions_ordinal",
    ),
    CheckConstraint(
        f"dimension IN ({_DIMENSIONS})",
        name="ck_library_health_dimensions_dimension",
    ),
    CheckConstraint(
        "status IN ('CLEAR','OBSERVED','ATTENTION','INCOMPLETE','BLOCKED')",
        name="ck_library_health_dimensions_status",
    ),
    CheckConstraint(
        "coverage_state IN ('COMPLETE','PARTIAL','NONE')",
        name="ck_library_health_dimensions_coverage",
    ),
    CheckConstraint(
        "assessed_item_count>=0 AND covered_item_count>=0 "
        "AND affected_item_count>=0 AND finding_count>=0 "
        "AND covered_item_count<=assessed_item_count "
        "AND affected_item_count<=assessed_item_count",
        name="ck_library_health_dimensions_counts",
    ),
    CheckConstraint(
        "length(evidence_categories_json) BETWEEN 2 AND 4096",
        name="ck_library_health_dimensions_evidence_categories",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="dimension_digest"),
        name="ck_library_health_dimensions_digest",
    ),
    UniqueConstraint("snapshot_id", "dimension", name="uq_library_health_dimensions_name"),
)


library_health_findings = Table(
    "library_health_findings",
    metadata,
    Column("snapshot_id", ID, primary_key=True),
    Column("dimension_ordinal", Integer, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    Column("severity", ENUM, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("evidence_categories_json", Text, nullable=False),
    Column("finding_digest", Text, nullable=False),
    ForeignKeyConstraint(
        ("snapshot_id", "dimension_ordinal"),
        ("library_health_dimensions.snapshot_id", "library_health_dimensions.ordinal"),
    ),
    CheckConstraint("ordinal>=0", name="ck_library_health_findings_ordinal"),
    CheckConstraint(
        f"code IN ({_FINDING_CODES})",
        name="ck_library_health_findings_code",
    ),
    CheckConstraint(
        "severity IN ('INFO','ATTENTION','INCOMPLETE','BLOCKED')",
        name="ck_library_health_findings_severity",
    ),
    CheckConstraint(
        f"item_count>0 AND sample_count BETWEEN 0 AND "
        f"{MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING} AND sample_count<=item_count",
        name="ck_library_health_findings_counts",
    ),
    CheckConstraint(
        "length(evidence_categories_json) BETWEEN 2 AND 4096",
        name="ck_library_health_findings_evidence_categories",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="finding_digest"),
        name="ck_library_health_findings_digest",
    ),
    UniqueConstraint("snapshot_id", "code", name="uq_library_health_findings_code"),
)


library_health_samples = Table(
    "library_health_samples",
    metadata,
    Column("snapshot_id", ID, primary_key=True),
    Column("dimension_ordinal", Integer, primary_key=True),
    Column("finding_ordinal", Integer, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("sample_digest", Text, nullable=False),
    ForeignKeyConstraint(
        ("snapshot_id", "dimension_ordinal", "finding_ordinal"),
        (
            "library_health_findings.snapshot_id",
            "library_health_findings.dimension_ordinal",
            "library_health_findings.ordinal",
        ),
    ),
    CheckConstraint(
        f"ordinal BETWEEN 0 AND {MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING - 1}",
        name="ck_library_health_samples_ordinal",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="sample_digest"),
        name="ck_library_health_samples_digest",
    ),
    UniqueConstraint(
        "snapshot_id",
        "dimension_ordinal",
        "finding_ordinal",
        "file_id",
        name="uq_library_health_samples_file",
    ),
)

Index(
    "ix_library_health_snapshots_root_created",
    library_health_snapshots.c.scan_root_id,
    library_health_snapshots.c.created_at,
    library_health_snapshots.c.id,
)
Index(
    "ix_library_health_samples_file",
    library_health_samples.c.file_id,
    library_health_samples.c.snapshot_id,
)

LIBRARY_HEALTH_TABLES = (
    library_health_snapshots,
    library_health_dimensions,
    library_health_findings,
    library_health_samples,
)
