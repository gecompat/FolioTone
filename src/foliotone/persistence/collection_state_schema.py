"""Insert-only SQLite schema for book-only CollectionState v1."""

from typing import Any

from sqlalchemy import (
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

_SHA_CHECK = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"
_ITEM_STATE_CHECK = (
    "{name} IN ('CURRENT','CURRENT_CONFLICT','STALE','STALE_CONFLICT',"
    "'UNSCOPED','UNSCOPED_CONFLICT','MISSING')"
)
_COMPONENTS = (
    "'ANALYSIS','RESOLUTION','CLASSIFICATION','MATCHING','REVIEW',"
    "'CALIBRE','ARCHIVE','CONSOLIDATION','QUARANTINE'"
)


collection_state_snapshots = Table(
    "collection_state_snapshots",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("total_size_bytes", Integer, nullable=False),
    Column("items_digest", Text, nullable=False),
    Column("content_digest", Text, nullable=False),
    CheckConstraint(
        "profile='collection-state/v1' AND serializer='canonical-json/v1'",
        name="ck_collection_state_snapshots_contract",
    ),
    CheckConstraint(
        "item_count>=0 AND total_size_bytes>=0",
        name="ck_collection_state_snapshots_counts",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="items_digest"),
        name="ck_collection_state_snapshots_items_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="content_digest"),
        name="ck_collection_state_snapshots_content_digest",
    ),
    UniqueConstraint("profile", "content_digest", name="uq_collection_state_snapshots_content"),
)

collection_state_components = Table(
    "collection_state_components",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("collection_state_snapshots.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("component", ENUM, nullable=False),
    Column("profile_versions_json", Text, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    Column("current_item_count", Integer, nullable=False),
    Column("stale_item_count", Integer, nullable=False),
    Column("unscoped_item_count", Integer, nullable=False),
    Column("missing_item_count", Integer, nullable=False),
    Column("conflict_item_count", Integer, nullable=False),
    Column("coverage_state", ENUM, nullable=False),
    Column("freshness_state", ENUM, nullable=False),
    Column("conflict_state", ENUM, nullable=False),
    Column("truncation_state", ENUM, nullable=False),
    Column("evidence_digest", Text, nullable=False),
    CheckConstraint("ordinal BETWEEN 0 AND 8", name="ck_collection_state_components_ordinal"),
    CheckConstraint(
        f"component IN ({_COMPONENTS})", name="ck_collection_state_components_component"
    ),
    CheckConstraint(
        "length(profile_versions_json) BETWEEN 2 AND 262144",
        name="ck_collection_state_components_profiles",
    ),
    CheckConstraint(
        "evidence_count>=0 AND current_item_count>=0 AND stale_item_count>=0 "
        "AND unscoped_item_count>=0 AND missing_item_count>=0 AND conflict_item_count>=0",
        name="ck_collection_state_components_counts",
    ),
    CheckConstraint(
        "coverage_state IN ('COMPLETE','PARTIAL','NONE')",
        name="ck_collection_state_components_coverage",
    ),
    CheckConstraint(
        "freshness_state IN ('CURRENT','STALE','MIXED','UNKNOWN')",
        name="ck_collection_state_components_freshness",
    ),
    CheckConstraint(
        "conflict_state IN ('NONE','PRESENT')",
        name="ck_collection_state_components_conflict",
    ),
    CheckConstraint(
        "truncation_state IN ('NONE','PROFILE_VERSIONS')",
        name="ck_collection_state_components_truncation",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="evidence_digest"),
        name="ck_collection_state_components_digest",
    ),
    UniqueConstraint("snapshot_id", "component", name="uq_collection_state_components_name"),
)

collection_state_counts = Table(
    "collection_state_counts",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("collection_state_snapshots.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("count_key", Text, nullable=False),
    Column("count_value", Integer, nullable=False),
    CheckConstraint("ordinal>=0", name="ck_collection_state_counts_ordinal"),
    CheckConstraint(
        "length(count_key) BETWEEN 1 AND 128 AND count_key NOT GLOB '*[^a-z0-9._-]*'",
        name="ck_collection_state_counts_key",
    ),
    CheckConstraint("count_value>=0", name="ck_collection_state_counts_value"),
    UniqueConstraint("snapshot_id", "count_key", name="uq_collection_state_counts_key"),
)


def _dimension_columns(component: str) -> tuple[Column[Any], Column[Any]]:
    state_name = f"{component}_state"
    digest_name = f"{component}_digest"
    return (
        Column(state_name, ENUM, nullable=False),
        Column(digest_name, Text),
    )


collection_state_items = Table(
    "collection_state_items",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("collection_state_snapshots.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("format_name", ENUM, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("technical_digest", Text, nullable=False),
    *_dimension_columns("analysis"),
    *_dimension_columns("resolution"),
    *_dimension_columns("classification"),
    *_dimension_columns("matching"),
    *_dimension_columns("review"),
    *_dimension_columns("calibre"),
    *_dimension_columns("archive"),
    *_dimension_columns("consolidation"),
    *_dimension_columns("quarantine"),
    Column("item_digest", Text, nullable=False),
    CheckConstraint("ordinal>=0 AND size_bytes>=0", name="ck_collection_state_items_counts"),
    CheckConstraint(
        "format_name IN ('EPUB','MOBI','AZW','AZW3','PDF','OTHER')",
        name="ck_collection_state_items_format",
    ),
    *(
        CheckConstraint(
            _ITEM_STATE_CHECK.format(name=f"{component}_state"),
            name=f"ck_collection_state_items_{component}_state",
        )
        for component in (
            "analysis",
            "resolution",
            "classification",
            "matching",
            "review",
            "calibre",
            "archive",
            "consolidation",
            "quarantine",
        )
    ),
    *(
        CheckConstraint(
            f"(({component}_state='MISSING' AND {component}_digest IS NULL) OR "
            f"({component}_state<>'MISSING' AND {_SHA_CHECK.format(name=f'{component}_digest')}))",
            name=f"ck_collection_state_items_{component}_digest",
        )
        for component in (
            "analysis",
            "resolution",
            "classification",
            "matching",
            "review",
            "calibre",
            "archive",
            "consolidation",
            "quarantine",
        )
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="technical_digest"),
        name="ck_collection_state_items_technical_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="item_digest"), name="ck_collection_state_items_item_digest"
    ),
    UniqueConstraint("snapshot_id", "file_id", name="uq_collection_state_items_file"),
    UniqueConstraint("snapshot_id", "observation_id", name="uq_collection_state_items_observation"),
)

Index(
    "ix_collection_state_snapshots_root_created",
    collection_state_snapshots.c.scan_root_id,
    collection_state_snapshots.c.created_at,
    collection_state_snapshots.c.id,
)
Index(
    "ix_collection_state_snapshots_source_scan",
    collection_state_snapshots.c.source_scan_run_id,
    collection_state_snapshots.c.id,
)
Index(
    "ix_collection_state_items_file_snapshot",
    collection_state_items.c.file_id,
    collection_state_items.c.snapshot_id,
)
Index(
    "ix_collection_state_items_observation_snapshot",
    collection_state_items.c.observation_id,
    collection_state_items.c.snapshot_id,
)

COLLECTION_STATE_TABLES = (
    collection_state_snapshots,
    collection_state_components,
    collection_state_counts,
    collection_state_items,
)
