"""Insert-only persistence schema for metadata correction candidates and plans."""

from __future__ import annotations

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
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _sha(table: str, column: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{table}_{column}_sha256",
    )


metadata_correction_candidates = Table(
    "metadata_correction_candidates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer_version", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("source_scan_run_status", ENUM, nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("format_label", ENUM, nullable=False),
    Column("expected_presence_state", ENUM, nullable=False),
    Column("expected_full_sha256", Text, nullable=False),
    Column("expected_size_bytes", Integer, nullable=False),
    Column("expected_modified_at", DATETIME, nullable=False),
    Column("expected_observed_at", DATETIME, nullable=False),
    Column("metadata_evidence_fingerprint", Text, nullable=False),
    Column("target_carrier", ENUM, nullable=False),
    Column("target_reference_kind", ENUM, nullable=False),
    Column("target_reference_id", ID, nullable=False),
    Column("target_state_fingerprint", Text, nullable=False),
    Column("writer_profile", Text, nullable=False),
    Column("writer_format_label", ENUM, nullable=False),
    Column("writer_target_carrier", ENUM, nullable=False),
    Column("writer_material_fingerprint", Text, nullable=False),
    Column("field_count", Integer, nullable=False),
    Column("dependency_count", Integer, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile = 'metadata-correction-candidate/v1' AND serializer_version = 'canonical-json/v1'",
        name="ck_metadata_correction_candidates_profile",
    ),
    CheckConstraint(
        "source_scan_run_status = 'COMPLETED' AND expected_presence_state = 'PRESENT'",
        name="ck_metadata_correction_candidates_source_state",
    ),
    CheckConstraint(
        "format_label IN ('EPUB','MOBI','AZW','AZW3','PDF') AND writer_format_label = format_label",
        name="ck_metadata_correction_candidates_format",
    ),
    CheckConstraint(
        "target_carrier IN "
        "('FOLIOTONE_PROJECTION','SIDECAR','SOURCE_METADATA','CALIBRE_LIBRARY',"
        "'EXTERNAL_TOOL') AND writer_target_carrier = target_carrier",
        name="ck_metadata_correction_candidates_target_carrier",
    ),
    CheckConstraint(
        "(target_carrier = 'FOLIOTONE_PROJECTION' "
        "AND target_reference_kind = 'DOMAIN_ENTITY') OR "
        "(target_carrier = 'SIDECAR' AND target_reference_kind = 'SIDECAR_SLOT') OR "
        "(target_carrier = 'SOURCE_METADATA' "
        "AND target_reference_kind = 'SOURCE_FILE' AND target_reference_id = file_id) OR "
        "(target_carrier = 'CALIBRE_LIBRARY' "
        "AND target_reference_kind = 'CALIBRE_RECORD') OR "
        "(target_carrier = 'EXTERNAL_TOOL' "
        "AND target_reference_kind = 'EXTERNAL_RECORD')",
        name="ck_metadata_correction_candidates_target_reference",
    ),
    CheckConstraint(
        "writer_profile = 'ebook-metadata-write-intent/v1'",
        name="ck_metadata_correction_candidates_writer_profile",
    ),
    CheckConstraint(
        "expected_size_bytes >= 0 AND field_count BETWEEN 1 AND 64 "
        "AND dependency_count = 3 AND evidence_count BETWEEN 1 AND 512",
        name="ck_metadata_correction_candidates_bounds",
    ),
    _sha("metadata_correction_candidates", "expected_full_sha256"),
    _sha("metadata_correction_candidates", "metadata_evidence_fingerprint"),
    _sha("metadata_correction_candidates", "target_state_fingerprint"),
    _sha("metadata_correction_candidates", "writer_material_fingerprint"),
    _sha("metadata_correction_candidates", "evidence_fingerprint"),
    _sha("metadata_correction_candidates", "content_hash"),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_metadata_correction_candidates_content",
    ),
)

metadata_correction_fields = Table(
    "metadata_correction_fields",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("metadata_correction_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("field_path", Text, nullable=False),
    Column("operation", ENUM, nullable=False),
    Column("selection_fingerprint", Text, nullable=False),
    Column("observed_count", Integer, nullable=False),
    Column("selected_count", Integer, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    CheckConstraint("ordinal >= 0", name="ck_metadata_correction_fields_ordinal"),
    CheckConstraint(
        "operation IN ('REPLACE','REMOVE') AND observed_count BETWEEN 0 AND 256 "
        "AND selected_count BETWEEN 0 AND 256 AND evidence_count BETWEEN 0 AND 64 "
        "AND ((operation = 'REPLACE' AND selected_count >= 1) "
        "OR (operation = 'REMOVE' AND selected_count = 0))",
        name="ck_metadata_correction_fields_shape",
    ),
    _sha("metadata_correction_fields", "selection_fingerprint"),
    UniqueConstraint(
        "candidate_id",
        "field_path",
        name="uq_metadata_correction_fields_path",
    ),
)

metadata_correction_values = Table(
    "metadata_correction_values",
    metadata,
    Column("candidate_id", ID, primary_key=True),
    Column("field_ordinal", Integer, primary_key=True),
    Column("value_set", ENUM, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("value_state", ENUM, nullable=False),
    Column("source_kind", ENUM, nullable=False),
    Column("source_id", ID, nullable=False),
    Column("source_material_fingerprint", Text, nullable=False),
    Column("value", Text, nullable=False),
    ForeignKeyConstraint(
        ("candidate_id", "field_ordinal"),
        ("metadata_correction_fields.candidate_id", "metadata_correction_fields.ordinal"),
    ),
    CheckConstraint(
        "field_ordinal >= 0 AND ordinal >= 0 AND value_set IN ('OBSERVED','SELECTED')",
        name="ck_metadata_correction_values_ordinal",
    ),
    CheckConstraint(
        "value_state IN ('OBSERVED','DERIVED','EXTERNAL','CANONICAL','USER_CONFIRMED') "
        "AND (value_set <> 'SELECTED' "
        "OR value_state IN ('CANONICAL','USER_CONFIRMED'))",
        name="ck_metadata_correction_values_state",
    ),
    CheckConstraint(
        "length(value) BETWEEN 1 AND 65536",
        name="ck_metadata_correction_values_private_value",
    ),
    _sha("metadata_correction_values", "source_material_fingerprint"),
)

metadata_correction_field_evidence = Table(
    "metadata_correction_field_evidence",
    metadata,
    Column("candidate_id", ID, primary_key=True),
    Column("field_ordinal", Integer, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    ForeignKeyConstraint(
        ("candidate_id", "field_ordinal"),
        ("metadata_correction_fields.candidate_id", "metadata_correction_fields.ordinal"),
    ),
    CheckConstraint(
        "field_ordinal >= 0 AND ordinal >= 0",
        name="ck_metadata_correction_field_evidence_ordinal",
    ),
    _sha("metadata_correction_field_evidence", "material_fingerprint"),
)

metadata_correction_evidence = Table(
    "metadata_correction_evidence",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("metadata_correction_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint("ordinal >= 0", name="ck_metadata_correction_evidence_ordinal"),
    _sha("metadata_correction_evidence", "material_fingerprint"),
)

metadata_correction_dependencies = Table(
    "metadata_correction_dependencies",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("metadata_correction_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("state", ENUM, nullable=False),
    Column("snapshot_kind", Text, nullable=False),
    Column("snapshot_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint("ordinal BETWEEN 0 AND 2", name="ck_metadata_correction_dependencies_ordinal"),
    CheckConstraint(
        "kind IN ('CALIBRE','SIDECAR','ARCHIVE') "
        "AND state IN ('KNOWN_NONE','KNOWN_PRESENT','UNKNOWN','NOT_APPLICABLE')",
        name="ck_metadata_correction_dependencies_state",
    ),
    _sha("metadata_correction_dependencies", "material_fingerprint"),
    UniqueConstraint(
        "candidate_id",
        "kind",
        name="uq_metadata_correction_dependencies_kind",
    ),
)

metadata_correction_plans = Table(
    "metadata_correction_plans",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer_version", Text, nullable=False),
    Column(
        "candidate_id",
        ID,
        ForeignKey("metadata_correction_candidates.id"),
        nullable=False,
    ),
    Column("review_count", Integer, nullable=False),
    Column("precondition_count", Integer, nullable=False),
    Column("blocker_count", Integer, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("execution_state", ENUM, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile = 'metadata-correction-plan/v1' AND serializer_version = 'canonical-json/v1'",
        name="ck_metadata_correction_plans_profile",
    ),
    CheckConstraint(
        "review_count BETWEEN 0 AND 1 AND precondition_count BETWEEN 0 AND 11 "
        "AND blocker_count BETWEEN 0 AND 11",
        name="ck_metadata_correction_plans_bounds",
    ),
    CheckConstraint(
        "status IN ('BLOCKED','REVIEW_REQUIRED','APPROVED_NON_EXECUTABLE') "
        "AND execution_state = 'NOT_EXECUTABLE'",
        name="ck_metadata_correction_plans_state",
    ),
    CheckConstraint(
        "(status = 'BLOCKED' AND blocker_count >= 1) "
        "OR (status <> 'BLOCKED' AND blocker_count = 0)",
        name="ck_metadata_correction_plans_blockers",
    ),
    _sha("metadata_correction_plans", "content_hash"),
    UniqueConstraint("profile", "content_hash", name="uq_metadata_correction_plans_content"),
)

metadata_correction_plan_reviews = Table(
    "metadata_correction_plan_reviews",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_plans.id"),
        primary_key=True,
    ),
    Column("candidate_id", ID, ForeignKey("metadata_correction_candidates.id"), nullable=False),
    Column("state", ENUM, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("producer_name", Text, nullable=False),
    Column("producer_version", Text, nullable=False),
    Column("decision_compatibility_version", Text, nullable=False),
    Column("review_type", ENUM, nullable=False),
    Column("candidate_kind", ENUM, nullable=False),
    Column("review_item_id", ID, ForeignKey("review_items.id")),
    Column("decision_id", ID, ForeignKey("review_decisions.id")),
    Column("decision_sequence_no", Integer),
    CheckConstraint(
        "review_type = 'METADATA_CORRECTION' "
        "AND candidate_kind = 'METADATA_CORRECTION_CANDIDATE' "
        "AND producer_name = 'ebook-metadata-correction' "
        "AND producer_version = '1' "
        "AND decision_compatibility_version = 'ebook-metadata-correction-decision/v1'",
        name="ck_metadata_correction_plan_reviews_profile",
    ),
    CheckConstraint(
        "(state = 'MISSING' AND review_item_id IS NULL AND decision_id IS NULL "
        "AND decision_sequence_no IS NULL) OR "
        "(state IN ('PENDING','DEFERRED','STALE') AND review_item_id IS NOT NULL "
        "AND decision_id IS NULL AND decision_sequence_no IS NULL) OR "
        "(state IN ('ACCEPTED','REJECTED') AND review_item_id IS NOT NULL "
        "AND decision_id IS NOT NULL AND decision_sequence_no >= 1)",
        name="ck_metadata_correction_plan_reviews_state",
    ),
    _sha("metadata_correction_plan_reviews", "evidence_fingerprint"),
    _sha("metadata_correction_plan_reviews", "candidate_set_fingerprint"),
)

metadata_correction_plan_preconditions = Table(
    "metadata_correction_plan_preconditions",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_plans.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    Column("expected_fingerprint", Text, nullable=False),
    CheckConstraint(
        "ordinal >= 0 AND code IN "
        "('FILE_RECORD_UNCHANGED','FILE_OBSERVATION_CURRENT','PRESENCE_IS_PRESENT',"
        "'FULL_SHA256_MATCHES','SIZE_MATCHES','MODIFIED_AT_MATCHES',"
        "'METADATA_EVIDENCE_UNCHANGED','TARGET_CARRIER_UNCHANGED',"
        "'DEPENDENCIES_UNCHANGED','REVIEW_APPROVAL_UNCHANGED',"
        "'WRITER_REQUIREMENT_UNCHANGED')",
        name="ck_metadata_correction_plan_preconditions_code",
    ),
    _sha("metadata_correction_plan_preconditions", "expected_fingerprint"),
    UniqueConstraint(
        "plan_id",
        "code",
        name="uq_metadata_correction_plan_preconditions_code",
    ),
)

metadata_correction_verifications = Table(
    "metadata_correction_verifications",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_plans.id"),
        primary_key=True,
    ),
    Column("profile", Text, nullable=False),
    Column("analysis_profile", Text, nullable=False),
    Column("format_label", ENUM, nullable=False),
    Column("target_carrier", ENUM, nullable=False),
    Column("expected_selected_fields_fingerprint", Text, nullable=False),
    Column("preserved_fields_fingerprint", Text, nullable=False),
    Column("changed_field_count", Integer, nullable=False),
    Column("format_validation_required", Boolean, nullable=False),
    Column("readability_validation_required", Boolean, nullable=False),
    Column("dependency_count", Integer, nullable=False),
    CheckConstraint(
        "profile = 'metadata-correction-verification/v1' "
        "AND format_label IN ('EPUB','MOBI','AZW','AZW3','PDF')",
        name="ck_metadata_correction_verifications_profile",
    ),
    CheckConstraint(
        "target_carrier IN "
        "('FOLIOTONE_PROJECTION','SIDECAR','SOURCE_METADATA','CALIBRE_LIBRARY',"
        "'EXTERNAL_TOOL') AND changed_field_count BETWEEN 1 AND 64 "
        "AND dependency_count BETWEEN 0 AND 3 "
        "AND format_validation_required = 1 AND readability_validation_required = 1",
        name="ck_metadata_correction_verifications_shape",
    ),
    _sha("metadata_correction_verifications", "expected_selected_fields_fingerprint"),
    _sha("metadata_correction_verifications", "preserved_fields_fingerprint"),
)

metadata_correction_verification_fields = Table(
    "metadata_correction_verification_fields",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_verifications.plan_id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("field_path", Text, nullable=False),
    CheckConstraint(
        "ordinal >= 0",
        name="ck_metadata_correction_verification_fields_ordinal",
    ),
    UniqueConstraint(
        "plan_id",
        "field_path",
        name="uq_metadata_correction_verification_fields_path",
    ),
)

metadata_correction_verification_dependencies = Table(
    "metadata_correction_verification_dependencies",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_verifications.plan_id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    CheckConstraint(
        "ordinal >= 0 AND kind IN ('CALIBRE','SIDECAR','ARCHIVE')",
        name="ck_metadata_correction_verification_dependencies_kind",
    ),
    UniqueConstraint(
        "plan_id",
        "kind",
        name="uq_metadata_correction_verification_dependencies_kind",
    ),
)

metadata_correction_plan_blockers = Table(
    "metadata_correction_plan_blockers",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("metadata_correction_plans.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    CheckConstraint(
        "ordinal >= 0 AND evidence_count BETWEEN 0 AND 64 AND code IN "
        "('LINEAGE_MISMATCH','SOURCE_EVIDENCE_INCOMPLETE','FIELD_SELECTION_INVALID',"
        "'TARGET_CARRIER_INVALID','WRITER_REQUIREMENT_INVALID',"
        "'DEPENDENCY_EVIDENCE_INCOMPLETE','PRECONDITION_INCOMPLETE',"
        "'VERIFICATION_CONTRACT_INCOMPLETE','REVIEW_MISSING','REVIEW_REJECTED',"
        "'REVIEW_STALE')",
        name="ck_metadata_correction_plan_blockers_code",
    ),
    UniqueConstraint(
        "plan_id",
        "code",
        name="uq_metadata_correction_plan_blockers_code",
    ),
)

metadata_correction_plan_blocker_evidence = Table(
    "metadata_correction_plan_blocker_evidence",
    metadata,
    Column("plan_id", ID, primary_key=True),
    Column("blocker_ordinal", Integer, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    ForeignKeyConstraint(
        ("plan_id", "blocker_ordinal"),
        ("metadata_correction_plan_blockers.plan_id", "metadata_correction_plan_blockers.ordinal"),
    ),
    CheckConstraint(
        "blocker_ordinal >= 0 AND ordinal >= 0",
        name="ck_metadata_correction_plan_blocker_evidence_ordinal",
    ),
    _sha("metadata_correction_plan_blocker_evidence", "material_fingerprint"),
)

Index(
    "ix_metadata_correction_candidates_source",
    metadata_correction_candidates.c.scan_root_id,
    metadata_correction_candidates.c.source_scan_run_id,
    metadata_correction_candidates.c.file_id,
    metadata_correction_candidates.c.created_at,
    metadata_correction_candidates.c.id,
)
Index(
    "ix_metadata_correction_evidence_reference",
    metadata_correction_evidence.c.kind,
    metadata_correction_evidence.c.ref_id,
    metadata_correction_evidence.c.candidate_id,
)
Index(
    "ix_metadata_correction_plans_candidate",
    metadata_correction_plans.c.candidate_id,
    metadata_correction_plans.c.created_at,
    metadata_correction_plans.c.id,
)

METADATA_CORRECTION_TABLES = (
    metadata_correction_candidates,
    metadata_correction_fields,
    metadata_correction_values,
    metadata_correction_field_evidence,
    metadata_correction_evidence,
    metadata_correction_dependencies,
    metadata_correction_plans,
    metadata_correction_plan_reviews,
    metadata_correction_plan_preconditions,
    metadata_correction_verifications,
    metadata_correction_verification_fields,
    metadata_correction_verification_dependencies,
    metadata_correction_plan_blockers,
    metadata_correction_plan_blocker_evidence,
)

__all__ = [
    "METADATA_CORRECTION_TABLES",
    "metadata_correction_candidates",
    "metadata_correction_dependencies",
    "metadata_correction_evidence",
    "metadata_correction_field_evidence",
    "metadata_correction_fields",
    "metadata_correction_plan_blocker_evidence",
    "metadata_correction_plan_blockers",
    "metadata_correction_plan_preconditions",
    "metadata_correction_plan_reviews",
    "metadata_correction_plans",
    "metadata_correction_values",
    "metadata_correction_verification_dependencies",
    "metadata_correction_verification_fields",
    "metadata_correction_verifications",
]
