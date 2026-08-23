"""Insert-only persistence schema for non-executable e-book operation recipes."""

from __future__ import annotations

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

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _sha(table: str, column: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column}) = 64 AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{table}_{column}_sha256",
    )


ebook_operation_recipe_candidates = Table(
    "ebook_operation_recipe_candidates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer_version", Text, nullable=False),
    Column("operation_kind", ENUM, nullable=False),
    Column("source_count", Integer, nullable=False),
    Column("target_kind", ENUM, nullable=False),
    Column("target_scope_id", ID, nullable=False),
    Column("target_relative_locator", Text, nullable=False),
    Column("target_state_fingerprint", Text, nullable=False),
    Column("output_identity_kind", ENUM, nullable=False),
    Column("output_format_label", ENUM, nullable=False),
    Column("output_expected_full_sha256", Text, nullable=False),
    Column("output_expected_size_bytes", Integer, nullable=False),
    Column("output_specification_fingerprint", Text, nullable=False),
    Column("collision_policy", ENUM, nullable=False),
    Column("workspace_mode", ENUM, nullable=False),
    Column("recovery_mode", ENUM, nullable=False),
    Column("processor_kind", ENUM, nullable=False),
    Column("processor_profile", Text, nullable=False),
    Column("processor_configuration_fingerprint", Text, nullable=False),
    Column("processor_material_fingerprint", Text, nullable=False),
    Column("processor_provider_id", Text),
    Column("processor_tool_version", Text),
    Column("processor_adapter_version", Text),
    Column("dependency_count", Integer, nullable=False),
    Column("verification_count", Integer, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    Column("workspace_requirement_fingerprint", Text, nullable=False),
    Column("recovery_requirement_fingerprint", Text, nullable=False),
    Column("verification_fingerprint", Text, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile = 'ebook-operation-recipe-candidate/v1' "
        "AND serializer_version = 'canonical-json/v1'",
        name="ck_ebook_operation_recipe_candidates_profile",
    ),
    CheckConstraint(
        "operation_kind IN ('FILE_RENAME','FILE_REORGANIZE','FILE_IMPORT',"
        "'FILE_EXPORT','FORMAT_TRANSFORM','ARCHIVE_REWRITE')",
        name="ck_ebook_operation_recipe_candidates_operation",
    ),
    CheckConstraint(
        "target_kind IN ('MANAGED_SCAN_ROOT_FILE','EXTERNAL_ENDPOINT_FILE',"
        "'GENERATED_FILE','SOURCE_REPLACEMENT') "
        "AND output_identity_kind IN "
        "('BYTE_IDENTICAL_TO_PRIMARY','EXPECTED_FULL_SHA256')",
        name="ck_ebook_operation_recipe_candidates_target_output",
    ),
    CheckConstraint(
        "collision_policy IN ('REQUIRE_TARGET_ABSENT','REQUIRE_EXACT_SOURCE') "
        "AND workspace_mode IN ('NOT_REQUIRED','PRIVATE_STAGING_REQUIRED') "
        "AND recovery_mode IN "
        "('REVERSE_RELOCATION','SOURCE_UNCHANGED','ORIGINAL_PRESERVED')",
        name="ck_ebook_operation_recipe_candidates_safety_shape",
    ),
    CheckConstraint(
        "processor_kind IN ('FOLIOTONE_NATIVE','TOOL_PROVIDER') AND "
        "((processor_kind = 'FOLIOTONE_NATIVE' AND processor_provider_id IS NULL "
        "AND processor_tool_version IS NULL AND processor_adapter_version IS NULL) OR "
        "(processor_kind = 'TOOL_PROVIDER' AND processor_provider_id IS NOT NULL "
        "AND processor_tool_version IS NOT NULL AND processor_adapter_version IS NOT NULL))",
        name="ck_ebook_operation_recipe_candidates_processor",
    ),
    CheckConstraint(
        "source_count BETWEEN 1 AND 32 AND dependency_count = 5 "
        "AND verification_count BETWEEN 5 AND 9 "
        "AND evidence_count BETWEEN 1 AND 256 "
        "AND output_expected_size_bytes >= 0",
        name="ck_ebook_operation_recipe_candidates_bounds",
    ),
    CheckConstraint(
        "length(target_relative_locator) BETWEEN 1 AND 1024 "
        "AND length(output_format_label) BETWEEN 1 AND 32",
        name="ck_ebook_operation_recipe_candidates_text_bounds",
    ),
    _sha("ebook_operation_recipe_candidates", "target_state_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "output_expected_full_sha256"),
    _sha("ebook_operation_recipe_candidates", "output_specification_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "processor_configuration_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "processor_material_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "workspace_requirement_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "recovery_requirement_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "verification_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "evidence_fingerprint"),
    _sha("ebook_operation_recipe_candidates", "content_hash"),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_ebook_operation_recipe_candidates_content",
    ),
)

ebook_operation_recipe_sources = Table(
    "ebook_operation_recipe_sources",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("ebook_operation_recipe_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("role", ENUM, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("source_scan_run_status", ENUM, nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("relative_locator", Text, nullable=False),
    Column("format_label", ENUM, nullable=False),
    Column("expected_presence_state", ENUM, nullable=False),
    Column("expected_full_sha256", Text, nullable=False),
    Column("expected_size_bytes", Integer, nullable=False),
    Column("expected_modified_at", DATETIME, nullable=False),
    Column("expected_observed_at", DATETIME, nullable=False),
    Column("source_evidence_fingerprint", Text, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 31 AND role IN ('PRIMARY','COMPANION') "
        "AND source_scan_run_status = 'COMPLETED' "
        "AND expected_presence_state = 'PRESENT' AND expected_size_bytes >= 0",
        name="ck_ebook_operation_recipe_sources_shape",
    ),
    CheckConstraint(
        "length(relative_locator) BETWEEN 1 AND 1024 "
        "AND length(format_label) BETWEEN 1 AND 32",
        name="ck_ebook_operation_recipe_sources_text_bounds",
    ),
    _sha("ebook_operation_recipe_sources", "expected_full_sha256"),
    _sha("ebook_operation_recipe_sources", "source_evidence_fingerprint"),
    UniqueConstraint(
        "candidate_id",
        "file_id",
        "observation_id",
        name="uq_ebook_operation_recipe_sources_identity",
    ),
)

ebook_operation_recipe_dependencies = Table(
    "ebook_operation_recipe_dependencies",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("ebook_operation_recipe_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("state", ENUM, nullable=False),
    Column("snapshot_kind", Text, nullable=False),
    Column("snapshot_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 4 AND kind IN "
        "('CALIBRE','SIDECAR','ARCHIVE','VOLUME_GROUP','EXTERNAL_LIBRARY') "
        "AND state IN ('KNOWN_NONE','KNOWN_PRESENT','UNKNOWN','NOT_APPLICABLE')",
        name="ck_ebook_operation_recipe_dependencies_shape",
    ),
    _sha("ebook_operation_recipe_dependencies", "material_fingerprint"),
    UniqueConstraint(
        "candidate_id",
        "kind",
        name="uq_ebook_operation_recipe_dependencies_kind",
    ),
)

ebook_operation_recipe_verifications = Table(
    "ebook_operation_recipe_verifications",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("ebook_operation_recipe_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 8 AND code IN "
        "('INPUT_IDENTITY_RECHECKED','TARGET_STATE_RECHECKED',"
        "'OUTPUT_FULL_SHA256_MATCHES','OUTPUT_SIZE_MATCHES',"
        "'SOURCE_PRESENCE_VERIFIED','FORMAT_READABLE','DEPENDENCIES_RECONCILED',"
        "'RESCAN_COMPLETED','COLLECTION_STATE_RECONCILED')",
        name="ck_ebook_operation_recipe_verifications_shape",
    ),
    UniqueConstraint(
        "candidate_id",
        "code",
        name="uq_ebook_operation_recipe_verifications_code",
    ),
)

ebook_operation_recipe_evidence = Table(
    "ebook_operation_recipe_evidence",
    metadata,
    Column(
        "candidate_id",
        ID,
        ForeignKey("ebook_operation_recipe_candidates.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 255 AND length(kind) BETWEEN 1 AND 64",
        name="ck_ebook_operation_recipe_evidence_shape",
    ),
    _sha("ebook_operation_recipe_evidence", "material_fingerprint"),
    UniqueConstraint(
        "candidate_id",
        "kind",
        "ref_id",
        name="uq_ebook_operation_recipe_evidence_reference",
    ),
)

ebook_operation_recipe_plans = Table(
    "ebook_operation_recipe_plans",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer_version", Text, nullable=False),
    Column(
        "candidate_id",
        ID,
        ForeignKey("ebook_operation_recipe_candidates.id"),
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
        "profile = 'ebook-operation-recipe-plan/v1' "
        "AND serializer_version = 'canonical-json/v1'",
        name="ck_ebook_operation_recipe_plans_profile",
    ),
    CheckConstraint(
        "review_count = 1 AND precondition_count BETWEEN 8 AND 9 "
        "AND blocker_count BETWEEN 0 AND 12",
        name="ck_ebook_operation_recipe_plans_bounds",
    ),
    CheckConstraint(
        "status IN ('BLOCKED','REVIEW_REQUIRED','APPROVED_NON_EXECUTABLE') "
        "AND execution_state = 'NOT_EXECUTABLE'",
        name="ck_ebook_operation_recipe_plans_state",
    ),
    CheckConstraint(
        "(status = 'BLOCKED' AND blocker_count >= 1) OR "
        "(status <> 'BLOCKED' AND blocker_count = 0)",
        name="ck_ebook_operation_recipe_plans_blockers",
    ),
    _sha("ebook_operation_recipe_plans", "content_hash"),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_ebook_operation_recipe_plans_content",
    ),
)

ebook_operation_recipe_plan_reviews = Table(
    "ebook_operation_recipe_plan_reviews",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("ebook_operation_recipe_plans.id"),
        primary_key=True,
    ),
    Column("candidate_id", ID, ForeignKey("ebook_operation_recipe_candidates.id"), nullable=False),
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
        "review_type = 'EBOOK_OPERATION_RECIPE' "
        "AND candidate_kind = 'EBOOK_OPERATION_RECIPE_CANDIDATE' "
        "AND producer_name = 'ebook-operation-recipe' "
        "AND producer_version = '1' "
        "AND decision_compatibility_version = 'ebook-operation-recipe-decision/v1'",
        name="ck_ebook_operation_recipe_plan_reviews_profile",
    ),
    CheckConstraint(
        "(state = 'MISSING' AND review_item_id IS NULL AND decision_id IS NULL "
        "AND decision_sequence_no IS NULL) OR "
        "(state IN ('PENDING','DEFERRED','STALE') AND review_item_id IS NOT NULL "
        "AND decision_id IS NULL AND decision_sequence_no IS NULL) OR "
        "(state IN ('ACCEPTED','REJECTED') AND review_item_id IS NOT NULL "
        "AND decision_id IS NOT NULL AND decision_sequence_no >= 1)",
        name="ck_ebook_operation_recipe_plan_reviews_state",
    ),
    _sha("ebook_operation_recipe_plan_reviews", "evidence_fingerprint"),
    _sha("ebook_operation_recipe_plan_reviews", "candidate_set_fingerprint"),
)

ebook_operation_recipe_plan_preconditions = Table(
    "ebook_operation_recipe_plan_preconditions",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("ebook_operation_recipe_plans.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    Column("expected_fingerprint", Text, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 8 AND code IN "
        "('SOURCE_LINEAGE_UNCHANGED','SOURCE_BYTES_UNCHANGED',"
        "'TARGET_STATE_UNCHANGED','DEPENDENCIES_UNCHANGED',"
        "'PROCESSOR_REQUIREMENT_UNCHANGED','OUTPUT_EXPECTATION_UNCHANGED',"
        "'RECOVERY_REQUIREMENT_UNCHANGED','VERIFICATION_REQUIREMENT_UNCHANGED',"
        "'REVIEW_APPROVAL_UNCHANGED')",
        name="ck_ebook_operation_recipe_plan_preconditions_shape",
    ),
    _sha("ebook_operation_recipe_plan_preconditions", "expected_fingerprint"),
    UniqueConstraint(
        "plan_id",
        "code",
        name="uq_ebook_operation_recipe_plan_preconditions_code",
    ),
)

ebook_operation_recipe_plan_blockers = Table(
    "ebook_operation_recipe_plan_blockers",
    metadata,
    Column(
        "plan_id",
        ID,
        ForeignKey("ebook_operation_recipe_plans.id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("code", ENUM, nullable=False),
    Column("evidence_count", Integer, nullable=False),
    CheckConstraint(
        "ordinal BETWEEN 0 AND 11 AND evidence_count BETWEEN 0 AND 256 AND code IN "
        "('LINEAGE_MISMATCH','SOURCE_EVIDENCE_INCOMPLETE','TARGET_INVALID',"
        "'OUTPUT_IDENTITY_INVALID','PROCESSOR_REQUIREMENT_INVALID',"
        "'DEPENDENCY_EVIDENCE_INCOMPLETE','PRECONDITION_INCOMPLETE',"
        "'RECOVERY_CONTRACT_INCOMPLETE','VERIFICATION_CONTRACT_INCOMPLETE',"
        "'REVIEW_MISSING','REVIEW_REJECTED','REVIEW_STALE')",
        name="ck_ebook_operation_recipe_plan_blockers_shape",
    ),
    UniqueConstraint(
        "plan_id",
        "code",
        name="uq_ebook_operation_recipe_plan_blockers_code",
    ),
)

ebook_operation_recipe_plan_blocker_evidence = Table(
    "ebook_operation_recipe_plan_blocker_evidence",
    metadata,
    Column("plan_id", ID, primary_key=True),
    Column("blocker_ordinal", Integer, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", ENUM, nullable=False),
    Column("ref_id", ID, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    ForeignKeyConstraint(
        ("plan_id", "blocker_ordinal"),
        (
            "ebook_operation_recipe_plan_blockers.plan_id",
            "ebook_operation_recipe_plan_blockers.ordinal",
        ),
    ),
    CheckConstraint(
        "blocker_ordinal BETWEEN 0 AND 11 AND ordinal BETWEEN 0 AND 255 "
        "AND length(kind) BETWEEN 1 AND 64",
        name="ck_ebook_operation_recipe_plan_blocker_evidence_shape",
    ),
    _sha("ebook_operation_recipe_plan_blocker_evidence", "material_fingerprint"),
)

Index(
    "ix_ebook_operation_recipe_sources_lineage",
    ebook_operation_recipe_sources.c.scan_root_id,
    ebook_operation_recipe_sources.c.source_scan_run_id,
    ebook_operation_recipe_sources.c.file_id,
    ebook_operation_recipe_sources.c.observation_id,
)
Index(
    "ix_ebook_operation_recipe_evidence_reference",
    ebook_operation_recipe_evidence.c.kind,
    ebook_operation_recipe_evidence.c.ref_id,
    ebook_operation_recipe_evidence.c.candidate_id,
)
Index(
    "ix_ebook_operation_recipe_plans_candidate",
    ebook_operation_recipe_plans.c.candidate_id,
    ebook_operation_recipe_plans.c.created_at,
    ebook_operation_recipe_plans.c.id,
)

EBOOK_OPERATION_RECIPE_TABLES = (
    ebook_operation_recipe_candidates,
    ebook_operation_recipe_sources,
    ebook_operation_recipe_dependencies,
    ebook_operation_recipe_verifications,
    ebook_operation_recipe_evidence,
    ebook_operation_recipe_plans,
    ebook_operation_recipe_plan_reviews,
    ebook_operation_recipe_plan_preconditions,
    ebook_operation_recipe_plan_blockers,
    ebook_operation_recipe_plan_blocker_evidence,
)

__all__ = [
    "EBOOK_OPERATION_RECIPE_TABLES",
    "ebook_operation_recipe_candidates",
    "ebook_operation_recipe_dependencies",
    "ebook_operation_recipe_evidence",
    "ebook_operation_recipe_plan_blocker_evidence",
    "ebook_operation_recipe_plan_blockers",
    "ebook_operation_recipe_plan_preconditions",
    "ebook_operation_recipe_plan_reviews",
    "ebook_operation_recipe_plans",
    "ebook_operation_recipe_sources",
    "ebook_operation_recipe_verifications",
]
