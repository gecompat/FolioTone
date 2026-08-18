"""EB-06 persisted relation-candidate schema."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

relation_candidates = Table(
    "relation_candidates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("left_kind", ENUM, nullable=False),
    Column("left_id", ID, nullable=False),
    Column("right_kind", ENUM, nullable=False),
    Column("right_id", ID, nullable=False),
    Column("relation_type", ENUM, nullable=False),
    Column("matcher_name", Text, nullable=False),
    Column("matcher_version", Text, nullable=False),
    Column("decision_compatibility_version", Text, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint("left_id < right_id", name="ck_relation_candidates_canonical_pair"),
    CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_relation_candidates_confidence"),
    CheckConstraint(
        "status IN ('CONFIRMED','REVIEW_REQUIRED','REJECTED')", name="ck_relation_candidates_status"
    ),
    CheckConstraint(
        "(relation_type = 'EXACT_DUPLICATE' AND left_kind = 'FILE' AND right_kind = 'FILE') "
        "OR (relation_type = 'SAME_EDITION' AND left_kind = 'EDITION' "
        "AND right_kind = 'EDITION') "
        "OR (relation_type = 'SAME_WORK' AND left_kind = 'WORK' AND right_kind = 'WORK')",
        name="ck_relation_candidates_type_level",
    ),
    CheckConstraint(
        "length(matcher_name) > 0 AND length(matcher_version) > 0 "
        "AND length(decision_compatibility_version) > 0",
        name="ck_relation_candidates_versions",
    ),
    CheckConstraint(
        "status <> 'CONFIRMED' OR relation_type = 'EXACT_DUPLICATE'",
        name="ck_relation_candidates_confirmation",
    ),
    CheckConstraint(
        "length(evidence_fingerprint)=64 "
        "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
        "AND length(candidate_set_fingerprint)=64 "
        "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_relation_candidates_fingerprints",
    ),
    UniqueConstraint(
        "scan_root_id",
        "source_scan_run_id",
        "left_kind",
        "left_id",
        "right_kind",
        "right_id",
        "relation_type",
        "matcher_name",
        "matcher_version",
        "decision_compatibility_version",
        "evidence_fingerprint",
        "candidate_set_fingerprint",
        name="uq_relation_candidates_snapshot",
    ),
)

relation_candidate_evidence = Table(
    "relation_candidate_evidence",
    metadata,
    Column("id", ID, primary_key=True),
    Column("relation_candidate_id", ID, ForeignKey("relation_candidates.id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("feature_code", ENUM, nullable=False),
    Column("feature_state", ENUM, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    Column("evidence_kind", ENUM),
    Column("evidence_id", ID),
    CheckConstraint("ordinal >= 0", name="ck_relation_candidate_evidence_ordinal"),
    CheckConstraint(
        "feature_code IN ('FILE_SHA256_EQUAL','FILE_SHA256_DIFFERENT',"
        "'NORMALIZED_TEXT_EQUAL','NORMALIZED_TEXT_DIFFERENT',"
        "'MATERIAL_TEXT_CONTRADICTORY','EDITION_IDENTIFIER_COMPATIBLE',"
        "'EDITION_IDENTIFIER_CONTRADICTORY','RESOLVED_EDITION_EQUAL',"
        "'RESOLVED_EDITION_DIFFERENT','RESOLVED_WORK_EQUAL',"
        "'RESOLVED_WORK_DIFFERENT','RESOLVED_AGENT_EQUAL','TITLE_COMPATIBLE',"
        "'TITLE_CONTRADICTORY','LANGUAGE_COMPATIBLE','LANGUAGE_CONTRADICTORY',"
        "'FORMAT_DIFFERENT')",
        name="ck_relation_candidate_evidence_feature",
    ),
    CheckConstraint(
        "feature_state IN ('PRESENT','ABSENT')", name="ck_relation_candidate_evidence_state"
    ),
    CheckConstraint(
        "evidence_kind IS NULL OR evidence_kind IN "
        "('FINGERPRINT','VALUE_ASSERTION','EXTERNAL_IDENTIFIER','RESOLUTION_CANDIDATE',"
        "'TOOL_RESULT','CLASSIFICATION_ASSERTION','REVIEW_DECISION')",
        name="ck_relation_candidate_evidence_kind",
    ),
    CheckConstraint(
        "(evidence_kind IS NULL) = (evidence_id IS NULL)",
        name="ck_relation_candidate_evidence_reference",
    ),
    CheckConstraint(
        "length(material_fingerprint)=64 AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_relation_candidate_evidence_fingerprint",
    ),
    UniqueConstraint(
        "relation_candidate_id", "ordinal", name="uq_relation_candidate_evidence_ordinal"
    ),
)

Index(
    "ix_relation_candidates_pair_created",
    relation_candidates.c.scan_root_id,
    relation_candidates.c.source_scan_run_id,
    relation_candidates.c.left_kind,
    relation_candidates.c.left_id,
    relation_candidates.c.right_id,
    relation_candidates.c.created_at,
    relation_candidates.c.id,
)
Index(
    "ix_relation_candidates_reuse",
    relation_candidates.c.left_kind,
    relation_candidates.c.left_id,
    relation_candidates.c.right_kind,
    relation_candidates.c.right_id,
    relation_candidates.c.relation_type,
    relation_candidates.c.matcher_name,
    relation_candidates.c.decision_compatibility_version,
    relation_candidates.c.evidence_fingerprint,
    relation_candidates.c.candidate_set_fingerprint,
)
Index(
    "ix_relation_candidate_evidence_source",
    relation_candidate_evidence.c.evidence_kind,
    relation_candidate_evidence.c.evidence_id,
    relation_candidate_evidence.c.relation_candidate_id,
)
