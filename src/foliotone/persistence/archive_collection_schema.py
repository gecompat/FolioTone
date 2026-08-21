"""SQLAlchemy schema for restartable archive collection runs."""

from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
    ArchiveSuffixKind,
)
from foliotone.core import (
    ARCHIVE_COLLECTION_PLAN_PROFILE,
    ARCHIVE_COLLECTION_PROFILE,
    ArchiveCollectionDisposition,
    ArchiveCollectionItemStatus,
    ArchiveCollectionRunStatus,
)
from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _literals(values: type[StrEnum]) -> str:
    return ", ".join(f"'{item.value}'" for item in values)


archive_collection_runs = Table(
    "archive_collection_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("profile", Text, nullable=False),
    Column("plan_profile", Text, nullable=False),
    Column("worker_count", Integer, nullable=False),
    Column("plan_limit", Integer),
    Column("started_at", DATETIME, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("fence_epoch", Integer, nullable=False),
    Column("planned_count", Integer, nullable=False),
    Column("hash_evidence_missing_count", Integer, nullable=False),
    Column("missing_volume_count", Integer, nullable=False),
    Column("unsupported_volume_count", Integer, nullable=False),
    Column("ambiguous_volume_count", Integer, nullable=False),
    Column("name_collision_count", Integer, nullable=False),
    Column("orphan_volume_count", Integer, nullable=False),
    Column("plan_content_hash", Text),
    Column("completed_at", DATETIME),
    Column("heartbeat_at", DATETIME),
    Column("lease_token", Text),
    Column("lease_expires_at", DATETIME),
    CheckConstraint(
        f"profile = '{ARCHIVE_COLLECTION_PROFILE}' AND "
        f"plan_profile = '{ARCHIVE_COLLECTION_PLAN_PROFILE}'",
        name="ck_archive_collection_runs_profiles",
    ),
    CheckConstraint(
        "worker_count BETWEEN 1 AND 2 AND "
        "(plan_limit IS NULL OR plan_limit >= 1) AND fence_epoch >= 1",
        name="ck_archive_collection_runs_bounds",
    ),
    CheckConstraint(
        "planned_count >= 0 AND (plan_limit IS NULL OR planned_count <= plan_limit) "
        "AND hash_evidence_missing_count >= 0 "
        "AND missing_volume_count >= 0 AND unsupported_volume_count >= 0 "
        "AND ambiguous_volume_count >= 0 AND name_collision_count >= 0 "
        "AND orphan_volume_count >= 0",
        name="ck_archive_collection_runs_counts",
    ),
    CheckConstraint(
        f"status IN ({_literals(ArchiveCollectionRunStatus)})",
        name="ck_archive_collection_runs_status",
    ),
    CheckConstraint(
        "(plan_content_hash IS NULL OR "
        "(length(plan_content_hash)=64 AND plan_content_hash NOT GLOB '*[^0-9a-f]*')) "
        "AND (status = 'PLANNING' AND plan_content_hash IS NULL "
        "OR status = 'FAILED' "
        "OR status NOT IN ('PLANNING', 'FAILED') AND plan_content_hash IS NOT NULL)",
        name="ck_archive_collection_runs_plan",
    ),
    CheckConstraint(
        "(status IN ('FAILED', 'COMPLETED', 'COMPLETED_WITH_FAILURES') "
        "AND completed_at IS NOT NULL OR "
        "status NOT IN ('FAILED', 'COMPLETED', 'COMPLETED_WITH_FAILURES') "
        "AND completed_at IS NULL) AND "
        "(completed_at IS NULL OR started_at <= completed_at)",
        name="ck_archive_collection_runs_terminal",
    ),
    CheckConstraint(
        "(lease_token IS NULL AND heartbeat_at IS NULL AND lease_expires_at IS NULL "
        "AND status <> 'RUNNING') OR "
        "(lease_token IS NOT NULL AND lease_token <> '' AND heartbeat_at IS NOT NULL "
        "AND lease_expires_at IS NOT NULL AND status IN ('PLANNING', 'RUNNING') "
        "AND started_at <= heartbeat_at AND heartbeat_at < lease_expires_at)",
        name="ck_archive_collection_runs_lease",
    ),
)

Index(
    "uq_archive_collection_runs_active_root",
    archive_collection_runs.c.scan_root_id,
    unique=True,
    sqlite_where=text("status IN ('PLANNING', 'RUNNING', 'INTERRUPTED')"),
)

archive_collection_items = Table(
    "archive_collection_items",
    metadata,
    Column("id", ID, primary_key=True),
    Column("run_id", ID, ForeignKey("archive_collection_runs.id"), nullable=False),
    Column(
        "primary_file_observation_id",
        ID,
        ForeignKey("file_observations.id"),
        nullable=False,
    ),
    Column("plan_ordinal", Integer, nullable=False),
    Column("signature_profile", Text, nullable=False),
    Column("compatibility_profile", Text, nullable=False),
    Column("container_class", ENUM, nullable=False),
    Column("suffix_kind", ENUM, nullable=False),
    Column("publication_kind", ENUM, nullable=False),
    Column("storage_family", ENUM, nullable=False),
    Column("outer_compression_kind", ENUM, nullable=False),
    Column("recognition_status", ENUM, nullable=False),
    Column("inspected_bytes", Integer, nullable=False),
    Column("structural_confirmation_required", Boolean, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("started_at", DATETIME),
    Column("completed_at", DATETIME),
    Column("archive_observation_id", ID, ForeignKey("archive_observations.id")),
    Column("disposition", ENUM),
    Column("error_code", Text),
    UniqueConstraint("id", "run_id", name="uq_archive_collection_items_id_run"),
    UniqueConstraint("run_id", "plan_ordinal", name="uq_archive_collection_items_run_ordinal"),
    UniqueConstraint(
        "run_id",
        "primary_file_observation_id",
        name="uq_archive_collection_items_run_primary",
    ),
    UniqueConstraint(
        "run_id",
        "archive_observation_id",
        name="uq_archive_collection_items_run_archive_observation",
    ),
    CheckConstraint(
        "plan_ordinal >= 0 AND attempt_count BETWEEN 0 AND 65535 "
        "AND inspected_bytes BETWEEN 0 AND 512",
        name="ck_archive_collection_items_bounds",
    ),
    CheckConstraint(
        "signature_profile = 'archive-signature-observer/v2' "
        "AND compatibility_profile = 'archive-publication-storage-compatibility/v1' "
        f"AND container_class IN ({_literals(ArchiveContainerClass)}) "
        f"AND suffix_kind IN ({_literals(ArchiveSuffixKind)}) "
        f"AND publication_kind IN ({_literals(ArchivePublicationKind)}) "
        f"AND storage_family IN ({_literals(ArchiveStorageFamily)}) "
        f"AND outer_compression_kind IN ({_literals(ArchiveOuterCompressionKind)}) "
        f"AND recognition_status IN ({_literals(ArchiveRecognitionStatus)}) "
        "AND structural_confirmation_required IN (0, 1)",
        name="ck_archive_collection_items_signature",
    ),
    CheckConstraint(
        f"status IN ({_literals(ArchiveCollectionItemStatus)}) "
        f"AND (disposition IS NULL OR disposition IN ({_literals(ArchiveCollectionDisposition)}))",
        name="ck_archive_collection_items_literals",
    ),
    CheckConstraint(
        "(status = 'PENDING' AND started_at IS NULL AND completed_at IS NULL "
        "AND archive_observation_id IS NULL AND disposition IS NULL AND error_code IS NULL) "
        "OR (status = 'RUNNING' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND completed_at IS NULL AND archive_observation_id IS NULL "
        "AND disposition IS NULL AND error_code IS NULL) "
        "OR (status = 'SUCCEEDED' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND completed_at IS NOT NULL AND archive_observation_id IS NOT NULL "
        "AND disposition IN ('EXECUTED', 'REUSED') AND error_code IS NULL) "
        "OR (status = 'FAILED' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND completed_at IS NOT NULL AND archive_observation_id IS NOT NULL "
        "AND disposition = 'EXECUTED' AND error_code IS NOT NULL "
        "AND length(error_code) BETWEEN 1 AND 64 "
        "AND substr(error_code, 1, 1) GLOB '[A-Z]' "
        "AND error_code NOT GLOB '*[^A-Z0-9_]*') "
        "OR (status = 'ERROR' AND attempt_count >= 1 AND started_at IS NOT NULL "
        "AND completed_at IS NOT NULL AND archive_observation_id IS NULL "
        "AND disposition IS NULL AND error_code IS NOT NULL "
        "AND length(error_code) BETWEEN 1 AND 64 "
        "AND substr(error_code, 1, 1) GLOB '[A-Z]' "
        "AND error_code NOT GLOB '*[^A-Z0-9_]*')",
        name="ck_archive_collection_items_state",
    ),
    CheckConstraint(
        "completed_at IS NULL OR started_at <= completed_at",
        name="ck_archive_collection_items_timestamps",
    ),
)

Index(
    "ix_archive_collection_items_claim",
    archive_collection_items.c.run_id,
    archive_collection_items.c.status,
    archive_collection_items.c.plan_ordinal,
)
Index(
    "ix_archive_collection_items_observation",
    archive_collection_items.c.run_id,
    archive_collection_items.c.archive_observation_id,
)

archive_collection_item_sources = Table(
    "archive_collection_item_sources",
    metadata,
    Column("run_id", ID, ForeignKey("archive_collection_runs.id"), nullable=False),
    Column("item_id", ID, primary_key=True),
    Column("source_ordinal", Integer, primary_key=True),
    Column(
        "file_observation_id",
        ID,
        ForeignKey("file_observations.id"),
        nullable=False,
    ),
    Column("full_sha256", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("staging_name", Text, nullable=False),
    ForeignKeyConstraint(
        ("item_id", "run_id"),
        ("archive_collection_items.id", "archive_collection_items.run_id"),
    ),
    UniqueConstraint("item_id", "staging_name", name="uq_archive_collection_sources_staging"),
    UniqueConstraint(
        "run_id",
        "file_observation_id",
        name="uq_archive_collection_sources_run_observation",
    ),
    CheckConstraint(
        "source_ordinal >= 0 AND size_bytes >= 0 "
        "AND length(full_sha256)=64 AND full_sha256 NOT GLOB '*[^0-9a-f]*' "
        "AND (staging_name = 'archive' OR "
        "length(staging_name) BETWEEN 9 AND 32 "
        "AND staging_name GLOB 'archive.[A-Za-z0-9]*' "
        "AND substr(staging_name, 9) NOT GLOB '*[^A-Za-z0-9]*')",
        name="ck_archive_collection_sources_material",
    ),
)

Index(
    "ix_archive_collection_sources_observation",
    archive_collection_item_sources.c.file_observation_id,
    archive_collection_item_sources.c.run_id,
    archive_collection_item_sources.c.item_id,
)

ARCHIVE_COLLECTION_TABLES = (
    archive_collection_runs,
    archive_collection_items,
    archive_collection_item_sources,
)
