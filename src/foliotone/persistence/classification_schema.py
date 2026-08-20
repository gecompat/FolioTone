"""Immutable book-classification lineage and projection schema from ADR-0037."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _sha256(name: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({name}) = 64 AND {name} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{name}_sha256",
    )


_UUID_OR_SHA256 = (
    "(length(source_reference) = 64 "
    "AND source_reference NOT GLOB '*[^0-9a-f]*') OR "
    "(length(source_reference) = 36 "
    "AND substr(source_reference, 9, 1) = '-' "
    "AND substr(source_reference, 14, 1) = '-' "
    "AND substr(source_reference, 19, 1) = '-' "
    "AND substr(source_reference, 24, 1) = '-' "
    "AND length(replace(source_reference, '-', '')) = 32 "
    "AND replace(source_reference, '-', '') NOT GLOB '*[^0-9a-f]*')"
)


book_classification_assertion_lineage = Table(
    "book_classification_assertion_lineage",
    metadata,
    Column("assertion_id", ID, ForeignKey("classification_assertions.id"), primary_key=True),
    Column("assertion_key", Text, nullable=False),
    Column("assertion_profile_version", Text, nullable=False),
    Column("source_kind", ENUM, nullable=False),
    Column("source_reference_kind", ENUM, nullable=False),
    Column("source_reference", Text, nullable=False),
    Column("priority_tier", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "assertion_profile_version = 'book-classification-assertion/v1'",
        name="ck_book_classification_lineage_profile",
    ),
    CheckConstraint(
        "source_kind IN ('LOCAL_DERIVED','TOOL_PROVIDER','KNOWLEDGE_PROVIDER','USER_CONFIRMED')",
        name="ck_book_classification_lineage_source_kind",
    ),
    CheckConstraint(
        "source_reference_kind IN "
        "('LOCAL_RULE_RUN','TOOL_RESULT','PROVIDER_MAPPING_OUTPUT','REVIEW_DECISION')",
        name="ck_book_classification_lineage_reference_kind",
    ),
    CheckConstraint(
        "(source_kind = 'LOCAL_DERIVED' AND source_reference_kind = 'LOCAL_RULE_RUN') "
        "OR (source_kind = 'TOOL_PROVIDER' AND source_reference_kind = 'TOOL_RESULT') "
        "OR (source_kind = 'KNOWLEDGE_PROVIDER' "
        "AND source_reference_kind = 'PROVIDER_MAPPING_OUTPUT') "
        "OR (source_kind = 'USER_CONFIRMED' AND source_reference_kind = 'REVIEW_DECISION')",
        name="ck_book_classification_lineage_source_reference_pair",
    ),
    CheckConstraint(
        "priority_tier IN ('AUTOMATED','USER_CONFIRMED') "
        "AND ((source_kind = 'USER_CONFIRMED' AND priority_tier = 'USER_CONFIRMED') "
        "OR (source_kind <> 'USER_CONFIRMED' AND priority_tier = 'AUTOMATED'))",
        name="ck_book_classification_lineage_priority",
    ),
    CheckConstraint(_UUID_OR_SHA256, name="ck_book_classification_lineage_reference_shape"),
    _sha256("assertion_key"),
    UniqueConstraint("assertion_key", name="uq_book_classification_lineage_assertion_key"),
)


book_classification_projections = Table(
    "book_classification_projections",
    metadata,
    Column("id", ID, primary_key=True),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("assertion_profile_version", Text, nullable=False),
    Column("projection_profile_version", Text, nullable=False),
    Column("input_fingerprint", Text, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "target_kind IN ('WORK','EDITION')",
        name="ck_book_classification_projection_target",
    ),
    CheckConstraint(
        "assertion_profile_version = 'book-classification-assertion/v1' "
        "AND projection_profile_version = 'book-classification-projection/v1'",
        name="ck_book_classification_projection_profiles",
    ),
    CheckConstraint(
        "status IN ('EMPTY','PROJECTED','REVIEW_REQUIRED')",
        name="ck_book_classification_projection_status",
    ),
    _sha256("input_fingerprint"),
    UniqueConstraint(
        "target_kind",
        "target_id",
        "projection_profile_version",
        "input_fingerprint",
        name="uq_book_classification_projection_identity",
    ),
)


book_classification_projection_values = Table(
    "book_classification_projection_values",
    metadata,
    Column("projection_id", ID, ForeignKey("book_classification_projections.id"), primary_key=True),
    Column("dimension", ENUM, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("taxonomy", Text),
    Column("normalized_value", Text),
    Column("facet_status", ENUM, nullable=False),
    Column("conflict_code", ENUM),
    CheckConstraint("ordinal >= 0", name="ck_book_classification_projection_value_ordinal"),
    CheckConstraint(
        "dimension IN ('domain','genre','subgenre','topic','audience','language','form')",
        name="ck_book_classification_projection_value_dimension",
    ),
    CheckConstraint(
        "facet_status IN ('EMPTY','PROJECTED','CONFLICT')",
        name="ck_book_classification_projection_value_status",
    ),
    CheckConstraint(
        "conflict_code IS NULL OR conflict_code IN "
        "('MULTIPLE_EXCLUSIVE_VALUES','CARDINALITY_EXCEEDED','CONFIRMED_CONTRADICTION')",
        name="ck_book_classification_projection_value_conflict_code",
    ),
    CheckConstraint(
        "(facet_status = 'PROJECTED' AND taxonomy IS NOT NULL "
        "AND normalized_value IS NOT NULL AND conflict_code IS NULL) "
        "OR (facet_status = 'EMPTY' AND ordinal = 0 AND taxonomy IS NULL "
        "AND normalized_value IS NULL AND conflict_code IS NULL) "
        "OR (facet_status = 'CONFLICT' AND ordinal = 0 AND taxonomy IS NULL "
        "AND normalized_value IS NULL AND conflict_code IS NOT NULL)",
        name="ck_book_classification_projection_value_shape",
    ),
    CheckConstraint(
        "taxonomy IS NULL OR (length(taxonomy) BETWEEN 1 AND 128 "
        "AND taxonomy = lower(taxonomy) "
        "AND substr(taxonomy, 1, 1) GLOB '[a-z0-9]' "
        "AND taxonomy NOT GLOB '*[^a-z0-9._-]*')",
        name="ck_book_classification_projection_value_taxonomy",
    ),
    CheckConstraint(
        "normalized_value IS NULL OR length(normalized_value) BETWEEN 1 AND 512",
        name="ck_book_classification_projection_value_normalized_value",
    ),
)


book_classification_projection_assertions = Table(
    "book_classification_projection_assertions",
    metadata,
    Column("projection_id", ID, ForeignKey("book_classification_projections.id"), primary_key=True),
    Column(
        "assertion_id",
        ID,
        ForeignKey("book_classification_assertion_lineage.assertion_id"),
        primary_key=True,
    ),
    Column("link_role", ENUM, nullable=False),
    Column("conflict_code", ENUM),
    CheckConstraint(
        "link_role IN ('SELECTED','CONSIDERED','CONFLICTING')",
        name="ck_book_classification_projection_assertion_role",
    ),
    CheckConstraint(
        "conflict_code IS NULL OR conflict_code IN "
        "('MULTIPLE_EXCLUSIVE_VALUES','CARDINALITY_EXCEEDED','CONFIRMED_CONTRADICTION')",
        name="ck_book_classification_projection_assertion_conflict_code",
    ),
    CheckConstraint(
        "(link_role = 'CONFLICTING' AND conflict_code IS NOT NULL) "
        "OR (link_role IN ('SELECTED','CONSIDERED') AND conflict_code IS NULL)",
        name="ck_book_classification_projection_assertion_shape",
    ),
)


CLASSIFICATION_PROJECTION_TABLES = (
    book_classification_assertion_lineage,
    book_classification_projections,
    book_classification_projection_values,
    book_classification_projection_assertions,
)
