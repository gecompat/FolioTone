"""Insert-only SQLite schema for the CollectionState metadata-query projection."""

from typing import Any

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

from foliotone.persistence.schema import ENUM, ID, metadata

_SHA_CHECK = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"
_ITEM_STATE_CHECK = (
    "{name} IN ('CURRENT','CURRENT_CONFLICT','STALE','STALE_CONFLICT',"
    "'UNSCOPED','UNSCOPED_CONFLICT','MISSING')"
)
_QUERY_FIELDS = ",".join(
    f"'{field}'"
    for field in (
        "file_id",
        "observation_id",
        "format",
        "analysis_status",
        "resolution_status",
        "classification_status",
        "matching_status",
        "review_status",
        "calibre_status",
        "archive_status",
        "consolidation_status",
        "quarantine_status",
        "finding_code",
        "title",
        "contributor",
        "identifier",
        "language",
        "publisher",
    )
)
_QUERY_METADATA_FIELDS = "'title','contributor','identifier','language','publisher'"
_QUERY_STATUS_FIELDS = (
    "'format','analysis_status','resolution_status','classification_status',"
    "'matching_status','review_status','calibre_status','archive_status',"
    "'consolidation_status','quarantine_status'"
)


collection_query_indexes = Table(
    "collection_query_indexes",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("collection_state_snapshots.id"),
        primary_key=True,
    ),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("document_count", Integer, nullable=False),
    Column("value_count", Integer, nullable=False),
    Column("metadata_value_count", Integer, nullable=False),
    Column("finding_value_count", Integer, nullable=False),
    Column("truncated_value_count", Integer, nullable=False),
    Column("coverage_state", ENUM, nullable=False),
    Column("truncation_state", ENUM, nullable=False),
    Column("values_digest", Text, nullable=False),
    Column("content_digest", Text, nullable=False),
    CheckConstraint(
        "profile='collection-query-index/v1' AND serializer='canonical-json/v1'",
        name="ck_collection_query_indexes_contract",
    ),
    CheckConstraint(
        "document_count>=0 AND value_count>=0 AND metadata_value_count>=0 "
        "AND finding_value_count>=0 AND truncated_value_count>=0 "
        "AND metadata_value_count<=value_count AND finding_value_count<=value_count",
        name="ck_collection_query_indexes_counts",
    ),
    CheckConstraint(
        "coverage_state IN ('COMPLETE','PARTIAL')",
        name="ck_collection_query_indexes_coverage",
    ),
    CheckConstraint(
        "truncation_state IN ('NONE','VALUE_LIMIT')",
        name="ck_collection_query_indexes_truncation",
    ),
    CheckConstraint(
        "(truncated_value_count=0 AND coverage_state='COMPLETE' "
        "AND truncation_state='NONE') OR "
        "(truncated_value_count>0 AND coverage_state='PARTIAL' "
        "AND truncation_state='VALUE_LIMIT')",
        name="ck_collection_query_indexes_coverage_shape",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="values_digest"),
        name="ck_collection_query_indexes_values_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="content_digest"),
        name="ck_collection_query_indexes_content_digest",
    ),
    UniqueConstraint("profile", "content_digest", name="uq_collection_query_indexes_content"),
)


def _state_column(name: str) -> Column[Any]:
    return Column(name, ENUM, nullable=False)


collection_query_documents = Table(
    "collection_query_documents",
    metadata,
    Column(
        "snapshot_id",
        ID,
        ForeignKey("collection_query_indexes.snapshot_id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("format_name", ENUM, nullable=False),
    _state_column("analysis_state"),
    _state_column("resolution_state"),
    _state_column("classification_state"),
    _state_column("matching_state"),
    _state_column("review_state"),
    _state_column("calibre_state"),
    _state_column("archive_state"),
    _state_column("consolidation_state"),
    _state_column("quarantine_state"),
    Column("value_count", Integer, nullable=False),
    Column("truncated_value_count", Integer, nullable=False),
    Column("document_digest", Text, nullable=False),
    CheckConstraint(
        "ordinal>=0 AND value_count>=0 AND truncated_value_count>=0",
        name="ck_collection_query_documents_ordinal",
    ),
    CheckConstraint(
        "format_name IN ('EPUB','MOBI','AZW','AZW3','PDF','OTHER')",
        name="ck_collection_query_documents_format",
    ),
    *(
        CheckConstraint(
            _ITEM_STATE_CHECK.format(name=f"{component}_state"),
            name=f"ck_collection_query_documents_{component}_state",
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
        _SHA_CHECK.format(name="document_digest"),
        name="ck_collection_query_documents_digest",
    ),
    UniqueConstraint("snapshot_id", "file_id", name="uq_collection_query_documents_file"),
    UniqueConstraint(
        "snapshot_id",
        "observation_id",
        name="uq_collection_query_documents_observation",
    ),
)


collection_query_values = Table(
    "collection_query_values",
    metadata,
    Column("row_id", Integer, primary_key=True, autoincrement=True),
    Column("snapshot_id", ID, nullable=False),
    Column("document_ordinal", Integer, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("field_name", ENUM, nullable=False),
    Column("value_kind", ENUM, nullable=False),
    Column("value", Text, nullable=False),
    Column("normalized_value", Text, nullable=False),
    Column("value_digest", Text, nullable=False),
    ForeignKeyConstraint(
        ("snapshot_id", "document_ordinal"),
        ("collection_query_documents.snapshot_id", "collection_query_documents.ordinal"),
    ),
    CheckConstraint(
        "document_ordinal>=0 AND ordinal>=0",
        name="ck_collection_query_values_ordinals",
    ),
    CheckConstraint(
        f"field_name IN ({_QUERY_FIELDS})",
        name="ck_collection_query_values_field",
    ),
    CheckConstraint(
        "value_kind IN ('OPAQUE_ID','STATUS','FINDING_CODE','METADATA_CANDIDATE')",
        name="ck_collection_query_values_kind",
    ),
    CheckConstraint(
        "(value_kind='OPAQUE_ID' AND field_name IN ('file_id','observation_id')) OR "
        f"(value_kind='STATUS' AND field_name IN ({_QUERY_STATUS_FIELDS})) OR "
        "(value_kind='FINDING_CODE' AND field_name='finding_code') OR "
        f"(value_kind='METADATA_CANDIDATE' AND field_name IN ({_QUERY_METADATA_FIELDS}))",
        name="ck_collection_query_values_field_kind",
    ),
    CheckConstraint(
        "length(value) BETWEEN 1 AND 4096 AND length(normalized_value) BETWEEN 1 AND 4096",
        name="ck_collection_query_values_bounded",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="value_digest"),
        name="ck_collection_query_values_digest",
    ),
    UniqueConstraint(
        "snapshot_id",
        "document_ordinal",
        "ordinal",
        name="uq_collection_query_values_ordinal",
    ),
)

Index(
    "ix_collection_query_documents_file",
    collection_query_documents.c.snapshot_id,
    collection_query_documents.c.file_id,
)
Index(
    "ix_collection_query_values_lookup",
    collection_query_values.c.snapshot_id,
    collection_query_values.c.field_name,
    collection_query_values.c.normalized_value,
    collection_query_values.c.document_ordinal,
)
Index(
    "ix_collection_query_values_document",
    collection_query_values.c.snapshot_id,
    collection_query_values.c.document_ordinal,
    collection_query_values.c.ordinal,
)

COLLECTION_QUERY_TABLES = (
    collection_query_indexes,
    collection_query_documents,
    collection_query_values,
)
