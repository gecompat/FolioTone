"""S-EB08-06 insert-only consolidation schema."""
# ruff: noqa: E501

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata


def _sha(name: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{name}_sha256",
    )


def _nullable_sha(name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{name} IS NULL OR (length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*')",
        name=f"ck_{name}_nullable_sha256",
    )


consolidation_quality_evidence = Table(
    "consolidation_quality_evidence", metadata,
    Column("id", ID, primary_key=True), Column("profile", Text, nullable=False),
    Column("collection_run_id", ID, ForeignKey("ebook_collection_runs.id"), nullable=False),
    Column("collection_item_id", ID, ForeignKey("ebook_collection_items.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("collection_profile", Text, nullable=False), Column("analysis_profile", Text, nullable=False),
    Column("quality_profile", Text, nullable=False), Column("format_label", ENUM, nullable=False),
    Column("item_status", ENUM, nullable=False), Column("aggregate_quality_status", ENUM, nullable=False),
    Column("reused_step_count", Integer, nullable=False), Column("executed_step_count", Integer, nullable=False), Column("finding_count", Integer, nullable=False),
    Column("metadata_status", ENUM, nullable=False), Column("text_status", ENUM, nullable=False), Column("cover_status", ENUM, nullable=False), Column("structure_status", ENUM, nullable=False), Column("format_risk_status", ENUM, nullable=False),
    Column("assessment_fingerprint", Text, nullable=False), Column("created_at", DATETIME, nullable=False),
    CheckConstraint("profile='consolidation-quality-evidence/v1' AND collection_profile='ebook-collection-analysis/v1' AND analysis_profile='ebook-analysis-workflow/v3' AND quality_profile='ebook-quality/v1'", name="ck_consolidation_quality_profiles"),
    CheckConstraint("format_label IN ('EPUB','MOBI','AZW','AZW3','PDF')", name="ck_consolidation_quality_format"),
    CheckConstraint("item_status IN ('SUCCEEDED','PARTIAL_FAILURE','FAILED') AND aggregate_quality_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE')", name="ck_consolidation_quality_status"),
    CheckConstraint("metadata_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE') AND text_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE') AND cover_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE') AND structure_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE') AND format_risk_status IN ('OK','REVIEW','ACTION_REQUIRED','INCOMPLETE','NOT_APPLICABLE')", name="ck_consolidation_quality_dimensions"),
    CheckConstraint("reused_step_count>=0 AND executed_step_count>=0 AND finding_count>=0", name="ck_consolidation_quality_counts"),
    _sha("assessment_fingerprint"),
    UniqueConstraint("collection_item_id", "profile", "quality_profile", name="uq_consolidation_quality_item_profile"),
)

consolidation_keep_preferences = Table(
    "consolidation_keep_preferences", metadata,
    Column("id", ID, primary_key=True), Column("profile", Text, nullable=False), Column("profile_version", Text, nullable=False),
    Column("left_file_id", ID, ForeignKey("file_records.id"), nullable=False), Column("left_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("right_file_id", ID, ForeignKey("file_records.id"), nullable=False), Column("right_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("left_quality_evidence_id", ID, ForeignKey("consolidation_quality_evidence.id"), nullable=False), Column("right_quality_evidence_id", ID, ForeignKey("consolidation_quality_evidence.id"), nullable=False),
    Column("status", ENUM, nullable=False), Column("keeper_file_id", ID, ForeignKey("file_records.id")), Column("candidate_file_id", ID, ForeignKey("file_records.id")),
    Column("configuration_fingerprint", Text, nullable=False), Column("evidence_fingerprint", Text, nullable=False), Column("candidate_set_fingerprint", Text, nullable=False), Column("created_at", DATETIME, nullable=False),
    CheckConstraint("profile='ebook-keep-preference/v1' AND profile_version='1' AND status IN ('PREFERRED','TIED','BLOCKED')", name="ck_consolidation_preference_contract"),
    CheckConstraint("left_file_id<>right_file_id AND left_observation_id<>right_observation_id AND left_quality_evidence_id<>right_quality_evidence_id", name="ck_consolidation_preference_distinct"),
    CheckConstraint("(status='PREFERRED' AND keeper_file_id IS NOT NULL AND candidate_file_id IS NOT NULL AND keeper_file_id<>candidate_file_id AND ((keeper_file_id=left_file_id AND candidate_file_id=right_file_id) OR (keeper_file_id=right_file_id AND candidate_file_id=left_file_id))) OR (status IN ('TIED','BLOCKED') AND keeper_file_id IS NULL AND candidate_file_id IS NULL)", name="ck_consolidation_preference_direction"),
    _sha("configuration_fingerprint"), _sha("evidence_fingerprint"), _sha("candidate_set_fingerprint"),
)
consolidation_keep_preference_reasons = Table("consolidation_keep_preference_reasons", metadata, Column("preference_id", ID, ForeignKey("consolidation_keep_preferences.id"), primary_key=True), Column("ordinal", Integer, primary_key=True), Column("code", ENUM, nullable=False), CheckConstraint("ordinal>=0 AND code IN ('FEWER_INCOMPLETE_DIMENSIONS','FEWER_ACTION_REQUIRED_DIMENSIONS','FEWER_REVIEW_DIMENSIONS','PREFERRED_FORMAT','SIZE_TIE_BREAKER','TIED','HARD_CONSTRAINT')", name="ck_consolidation_preference_reason"))
consolidation_keep_preference_evidence = Table(
    "consolidation_keep_preference_evidence", metadata,
    Column("preference_id", ID, ForeignKey("consolidation_keep_preferences.id"), primary_key=True),
    Column("ordinal", Integer, primary_key=True), Column("role", ENUM, nullable=False),
    Column("kind", ENUM, nullable=False), Column("ref_id", ID, ForeignKey("consolidation_quality_evidence.id"), nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint("ordinal IN (0,1)", name="ck_consolidation_preference_evidence_ordinal"),
    CheckConstraint("role IN ('KEEPER','CANDIDATE') AND kind='QUALITY_EVIDENCE'", name="ck_consolidation_preference_evidence_kind"),
    _sha("material_fingerprint"),
)

consolidation_candidates = Table(
    "consolidation_candidates", metadata,
    Column("id", ID, primary_key=True), Column("profile", Text, nullable=False), Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False), Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("relation_candidate_id", ID, ForeignKey("relation_candidates.id"), nullable=False), Column("relation_fingerprint", Text, nullable=False), Column("keep_preference_id", ID, ForeignKey("consolidation_keep_preferences.id"), nullable=False), Column("keep_preference_fingerprint", Text, nullable=False),
    Column("keeper_file_id", ID, ForeignKey("file_records.id"), nullable=False), Column("candidate_file_id", ID, ForeignKey("file_records.id"), nullable=False), Column("dependency_fingerprint", Text, nullable=False), Column("precondition_fingerprint", Text, nullable=False), Column("evidence_fingerprint", Text, nullable=False), Column("candidate_set_fingerprint", Text, nullable=False), Column("created_at", DATETIME, nullable=False),
    CheckConstraint("profile='ebook-consolidation-candidate/v1' AND keeper_file_id<>candidate_file_id", name="ck_consolidation_candidate_contract"),
    _sha("relation_fingerprint"), _sha("keep_preference_fingerprint"), _sha("dependency_fingerprint"), _sha("precondition_fingerprint"), _sha("evidence_fingerprint"), _sha("candidate_set_fingerprint"),
    UniqueConstraint("profile", "scan_root_id", "source_scan_run_id", "relation_candidate_id", "relation_fingerprint", "keep_preference_id", "keep_preference_fingerprint", "keeper_file_id", "candidate_file_id", "dependency_fingerprint", "precondition_fingerprint", "evidence_fingerprint", "candidate_set_fingerprint", name="uq_consolidation_candidate_snapshot"),
)
consolidation_candidate_intents = Table("consolidation_candidate_intents", metadata, Column("consolidation_candidate_id", ID, ForeignKey("consolidation_candidates.id"), primary_key=True), Column("ordinal", Integer, primary_key=True), Column("code", ENUM, nullable=False), Column("file_role", ENUM, nullable=False), CheckConstraint("ordinal>=0 AND file_role IN ('KEEPER','CANDIDATE') AND ((code='KEEP' AND file_role='KEEPER') OR (code IN ('QUARANTINE','VERIFY','ROLLBACK','PURGE','CALIBRE_RECONCILE','SIDECAR_RECONCILE','ARCHIVE_RECONCILE','EMPTY_DIRECTORY_REVIEW') AND file_role='CANDIDATE'))", name="ck_consolidation_candidate_intent"))

consolidation_plans = Table(
    "consolidation_plans", metadata,
    Column("id", ID, primary_key=True), Column("profile", Text, nullable=False), Column("plan_version", Integer, nullable=False), Column("serializer_version", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False), Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("relation_candidate_id", ID, ForeignKey("relation_candidates.id")), Column("keep_preference_id", ID, ForeignKey("consolidation_keep_preferences.id")), Column("consolidation_candidate_id", ID, ForeignKey("consolidation_candidates.id")),
    Column("keeper_file_id", ID, ForeignKey("file_records.id")), Column("keeper_observation_id", ID, ForeignKey("file_observations.id")), Column("candidate_file_id", ID, ForeignKey("file_records.id")), Column("candidate_observation_id", ID, ForeignKey("file_observations.id")),
    Column("status", ENUM, nullable=False), Column("execution_state", ENUM, nullable=False), Column("content_hash", Text, nullable=False), Column("created_at", DATETIME, nullable=False),
    CheckConstraint("profile='consolidation-plan/v1' AND plan_version=1 AND serializer_version='canonical-json/v1' AND status IN ('BLOCKED','REVIEW_REQUIRED','APPROVED_NON_EXECUTABLE') AND execution_state='NOT_EXECUTABLE'", name="ck_consolidation_plan_contract"), _sha("content_hash"), UniqueConstraint("profile", "content_hash", name="uq_consolidation_plan_content"),
)

def _plan_child(name: str, *columns: Column[Any]) -> Table:
    return Table(name, metadata, Column("plan_id", ID, ForeignKey("consolidation_plans.id"), primary_key=True), Column("ordinal", Integer, primary_key=True), *columns, CheckConstraint("ordinal>=0", name=f"ck_{name}_ordinal"))


consolidation_plan_evidence = _plan_child("consolidation_plan_evidence", Column("role", ENUM, nullable=False), Column("kind", ENUM, nullable=False), Column("ref_id", ID, nullable=False), Column("material_fingerprint", Text, nullable=False))
consolidation_plan_dependencies = _plan_child("consolidation_plan_dependencies", Column("file_role", ENUM, nullable=False), Column("kind", ENUM, nullable=False), Column("state", ENUM, nullable=False), Column("snapshot_kind", Text), Column("snapshot_id", ID), Column("material_fingerprint", Text, nullable=False))
consolidation_plan_reviews = _plan_child("consolidation_plan_reviews", Column("review_type", ENUM, nullable=False), Column("state", ENUM, nullable=False), Column("review_item_id", ID, ForeignKey("review_items.id")), Column("decision_id", ID, ForeignKey("review_decisions.id")), Column("decision_sequence_no", Integer), Column("producer_name", Text, nullable=False), Column("producer_version", Text, nullable=False), Column("decision_compatibility_version", Text, nullable=False), Column("evidence_fingerprint", Text, nullable=False), Column("candidate_set_fingerprint", Text, nullable=False))
consolidation_plan_preconditions = _plan_child("consolidation_plan_preconditions", Column("file_role", ENUM, nullable=False), Column("code", ENUM, nullable=False), Column("expected_file_id", ID, ForeignKey("file_records.id"), nullable=False), Column("expected_observation_id", ID, ForeignKey("file_observations.id"), nullable=False), Column("expected_scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False), Column("expected_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False), Column("expected_presence_state", ENUM, nullable=False), Column("expected_full_sha256", Text, nullable=False), Column("expected_size_bytes", Integer, nullable=False), Column("expected_modified_at", DATETIME, nullable=False), Column("expected_observed_at", DATETIME, nullable=False), Column("dependency_kind", ENUM), Column("dependency_state", ENUM), Column("dependency_fingerprint", Text), Column("dependency_snapshot_kind", Text), Column("dependency_snapshot_id", ID), Column("review_item_id", ID), Column("review_decision_id", ID), Column("review_decision_sequence_no", Integer), Column("review_decision_compatibility_version", Text), Column("review_evidence_fingerprint", Text), Column("review_candidate_set_fingerprint", Text))
consolidation_plan_intents = _plan_child("consolidation_plan_intents", Column("code", ENUM, nullable=False), Column("file_role", ENUM, nullable=False))
consolidation_plan_blockers = _plan_child("consolidation_plan_blockers", Column("code", ENUM, nullable=False))
consolidation_plan_blocker_evidence = Table("consolidation_plan_blocker_evidence", metadata, Column("plan_id", ID, ForeignKey("consolidation_plans.id"), primary_key=True), Column("blocker_ordinal", Integer, primary_key=True), Column("evidence_ordinal", Integer, primary_key=True), Column("evidence_plan_ordinal", Integer, nullable=False), CheckConstraint("blocker_ordinal>=0 AND evidence_ordinal>=0 AND evidence_plan_ordinal>=0", name="ck_consolidation_blocker_evidence_ordinals"), ForeignKeyConstraint(("plan_id", "blocker_ordinal"), ("consolidation_plan_blockers.plan_id", "consolidation_plan_blockers.ordinal")), ForeignKeyConstraint(("plan_id", "evidence_plan_ordinal"), ("consolidation_plan_evidence.plan_id", "consolidation_plan_evidence.ordinal")))

consolidation_plan_evidence.append_constraint(CheckConstraint("role IN ('IDENTITY','KEEPER_QUALITY','CANDIDATE_QUALITY','KEEP_PREFERENCE','DEPENDENCY','REVIEW') AND kind IN ('RELATION_CANDIDATE','RELATION_CANDIDATE_EVIDENCE','REVIEW_DECISION','FINGERPRINT','TOOL_EXECUTION','TOOL_RESULT','EBOOK_COLLECTION_ITEM','EBOOK_COLLECTION_FINDING','QUALITY_EVIDENCE','CALIBRE_SNAPSHOT','CALIBRE_FINDING','CALIBRE_FORMAT','CALIBRE_SIDECAR')", name="ck_consolidation_plan_evidence_literals"))
consolidation_plan_evidence.append_constraint(_sha("material_fingerprint"))
consolidation_plan_dependencies.append_constraint(CheckConstraint("file_role IN ('KEEPER','CANDIDATE') AND kind IN ('CALIBRE','SIDECAR','ARCHIVE') AND state IN ('KNOWN_NONE','KNOWN_PRESENT','UNKNOWN','NOT_APPLICABLE') AND ((snapshot_kind IS NULL AND snapshot_id IS NULL) OR (snapshot_kind IS NOT NULL AND snapshot_id IS NOT NULL))", name="ck_consolidation_plan_dependency_contract"))
consolidation_plan_dependencies.append_constraint(_sha("material_fingerprint"))
consolidation_plan_reviews.append_constraint(CheckConstraint("review_type IN ('KEEP_PREFERENCE','CONSOLIDATION_CANDIDATE') AND ((state='MISSING' AND review_item_id IS NULL AND decision_id IS NULL AND decision_sequence_no IS NULL) OR (state IN ('PENDING','DEFERRED','STALE') AND review_item_id IS NOT NULL AND decision_id IS NULL AND decision_sequence_no IS NULL) OR (state IN ('ACCEPTED','REJECTED') AND review_item_id IS NOT NULL AND decision_id IS NOT NULL AND decision_sequence_no>=1))", name="ck_consolidation_plan_review_contract"))
consolidation_plan_reviews.append_constraint(_sha("evidence_fingerprint"))
consolidation_plan_reviews.append_constraint(_sha("candidate_set_fingerprint"))
consolidation_plan_preconditions.append_constraint(CheckConstraint("file_role IN ('KEEPER','CANDIDATE') AND code IN ('FILE_RECORD_UNCHANGED','FILE_OBSERVATION_CURRENT','PRESENCE_IS_PRESENT','FULL_SHA256_MATCHES','SIZE_MATCHES','MODIFIED_AT_MATCHES','KEEPER_READABLE','CALIBRE_RELATIONSHIP_UNCHANGED','SIDECAR_RELATIONSHIP_UNCHANGED','ARCHIVE_RELATIONSHIP_UNCHANGED','REVIEW_APPROVALS_UNCHANGED') AND expected_presence_state='PRESENT' AND expected_size_bytes>=0", name="ck_consolidation_plan_precondition_contract"))
consolidation_plan_preconditions.append_constraint(_sha("expected_full_sha256"))
consolidation_plan_preconditions.append_constraint(CheckConstraint("((code IN ('CALIBRE_RELATIONSHIP_UNCHANGED','SIDECAR_RELATIONSHIP_UNCHANGED','ARCHIVE_RELATIONSHIP_UNCHANGED')) AND ((code='CALIBRE_RELATIONSHIP_UNCHANGED' AND dependency_kind='CALIBRE') OR (code='SIDECAR_RELATIONSHIP_UNCHANGED' AND dependency_kind='SIDECAR') OR (code='ARCHIVE_RELATIONSHIP_UNCHANGED' AND dependency_kind='ARCHIVE')) AND dependency_state IS NOT NULL AND dependency_fingerprint IS NOT NULL AND ((dependency_state='KNOWN_NONE' AND dependency_snapshot_kind IS NULL AND dependency_snapshot_id IS NULL) OR (dependency_state<>'KNOWN_NONE' AND dependency_snapshot_kind IS NOT NULL AND dependency_snapshot_id IS NOT NULL))) OR ((code NOT IN ('CALIBRE_RELATIONSHIP_UNCHANGED','SIDECAR_RELATIONSHIP_UNCHANGED','ARCHIVE_RELATIONSHIP_UNCHANGED')) AND dependency_kind IS NULL AND dependency_state IS NULL AND dependency_fingerprint IS NULL AND dependency_snapshot_kind IS NULL AND dependency_snapshot_id IS NULL)", name="ck_consolidation_plan_precondition_dependency"))
consolidation_plan_preconditions.append_constraint(CheckConstraint("((code='REVIEW_APPROVALS_UNCHANGED') AND review_item_id IS NOT NULL AND review_decision_id IS NOT NULL AND review_decision_sequence_no>=1 AND review_decision_compatibility_version IS NOT NULL AND review_evidence_fingerprint IS NOT NULL AND review_candidate_set_fingerprint IS NOT NULL) OR ((code<>'REVIEW_APPROVALS_UNCHANGED') AND review_item_id IS NULL AND review_decision_id IS NULL AND review_decision_sequence_no IS NULL AND review_decision_compatibility_version IS NULL AND review_evidence_fingerprint IS NULL AND review_candidate_set_fingerprint IS NULL)", name="ck_consolidation_plan_precondition_review"))
consolidation_plan_preconditions.append_constraint(_nullable_sha("dependency_fingerprint"))
consolidation_plan_preconditions.append_constraint(_nullable_sha("review_evidence_fingerprint"))
consolidation_plan_preconditions.append_constraint(_nullable_sha("review_candidate_set_fingerprint"))
consolidation_plan_intents.append_constraint(CheckConstraint("file_role IN ('KEEPER','CANDIDATE') AND ((code='KEEP' AND file_role='KEEPER') OR (code IN ('QUARANTINE','VERIFY','ROLLBACK','PURGE','CALIBRE_RECONCILE','SIDECAR_RECONCILE','ARCHIVE_RECONCILE','EMPTY_DIRECTORY_REVIEW') AND file_role='CANDIDATE'))", name="ck_consolidation_plan_intent"))
consolidation_plan_blockers.append_constraint(CheckConstraint("code IN ('IDENTITY_NOT_ACTIONABLE','IDENTITY_NOT_CONFIRMED','LINEAGE_MISMATCH','PRECONDITION_INCOMPLETE','PROTECTED_SOURCE_ROOT','QUALITY_EVIDENCE_INCOMPLETE','KEEP_PREFERENCE_UNRESOLVED','KEEP_PREFERENCE_REVIEW_MISSING','KEEP_PREFERENCE_REVIEW_REJECTED','CONSOLIDATION_REVIEW_MISSING','CONSOLIDATION_REVIEW_REJECTED','CALIBRE_RELATIONSHIP_UNKNOWN','CALIBRE_OWNERSHIP_PRESENT','SIDECAR_RELATIONSHIP_UNKNOWN','SIDECAR_DEPENDENCY_PRESENT','ARCHIVE_RELATIONSHIP_UNKNOWN','ARCHIVE_MEMBERSHIP_PRESENT')", name="ck_consolidation_plan_blocker_code"))

CONSOLIDATION_TABLES = (consolidation_quality_evidence, consolidation_keep_preferences, consolidation_keep_preference_reasons, consolidation_keep_preference_evidence, consolidation_candidates, consolidation_candidate_intents, consolidation_plans, consolidation_plan_evidence, consolidation_plan_dependencies, consolidation_plan_reviews, consolidation_plan_preconditions, consolidation_plan_intents, consolidation_plan_blockers, consolidation_plan_blocker_evidence)
