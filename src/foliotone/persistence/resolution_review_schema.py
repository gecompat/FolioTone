"""EB-02 entity-resolution and generic review persistence schema."""

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

resolution_candidates = Table(
    "resolution_candidates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("subject_kind", ENUM, nullable=False),
    Column("subject_id", ID, nullable=False),
    Column("candidate_kind", ENUM, nullable=False),
    Column("candidate_entity_id", ID, nullable=False),
    Column("resolver_name", Text, nullable=False),
    Column("resolver_version", Text, nullable=False),
    Column("decision_compatibility_version", Text, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("disposition", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "subject_kind IN ('FILE', 'FILE_OBSERVATION', 'AGENT', 'WORK', 'EDITION', 'SERIES')",
        name="ck_resolution_candidates_subject_kind",
    ),
    CheckConstraint(
        "candidate_kind IN ('AGENT', 'WORK', 'EDITION', 'SERIES')",
        name="ck_resolution_candidates_candidate_kind",
    ),
    CheckConstraint(
        "subject_kind NOT IN ('AGENT', 'WORK', 'EDITION', 'SERIES') "
        "OR (subject_kind = candidate_kind AND subject_id <> candidate_entity_id)",
        name="ck_resolution_candidates_level",
    ),
    CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_resolution_candidates_confidence"),
    CheckConstraint(
        "disposition IN ('AUTO_SAFE', 'REVIEW_REQUIRED')",
        name="ck_resolution_candidates_disposition",
    ),
    CheckConstraint(
        "length(evidence_fingerprint) = 64 "
        "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
        "AND length(candidate_set_fingerprint) = 64 "
        "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_resolution_candidates_fingerprints",
    ),
    UniqueConstraint(
        "subject_kind",
        "subject_id",
        "candidate_kind",
        "candidate_entity_id",
        "resolver_name",
        "resolver_version",
        "decision_compatibility_version",
        "evidence_fingerprint",
        "candidate_set_fingerprint",
        name="uq_resolution_candidates_snapshot",
    ),
)

resolution_candidate_evidence = Table(
    "resolution_candidate_evidence",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "resolution_candidate_id",
        ID,
        ForeignKey("resolution_candidates.id"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("evidence_kind", ENUM, nullable=False),
    Column("evidence_id", ID, nullable=False),
    Column("evidence_role", ENUM, nullable=False),
    Column("asserted_entity_kind", ENUM, nullable=False),
    Column("material_fingerprint", Text, nullable=False),
    CheckConstraint("ordinal >= 0", name="ck_resolution_candidate_evidence_ordinal"),
    CheckConstraint(
        "evidence_kind IN ('VALUE_ASSERTION', 'TOOL_RESULT', 'FINGERPRINT', "
        "'EXTERNAL_IDENTIFIER', 'CLASSIFICATION_ASSERTION', 'REVIEW_DECISION')",
        name="ck_resolution_candidate_evidence_kind",
    ),
    CheckConstraint(
        "evidence_role IN ('SUPPORTS', 'CONTRADICTS')",
        name="ck_resolution_candidate_evidence_role",
    ),
    CheckConstraint(
        "asserted_entity_kind IN ('AGENT', 'WORK', 'EDITION', 'SERIES')",
        name="ck_resolution_candidate_evidence_entity_kind",
    ),
    CheckConstraint(
        "length(material_fingerprint) = 64 AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_resolution_candidate_evidence_fingerprint",
    ),
    UniqueConstraint(
        "resolution_candidate_id",
        "ordinal",
        name="uq_resolution_candidate_evidence_ordinal",
    ),
    UniqueConstraint(
        "resolution_candidate_id",
        "evidence_kind",
        "evidence_id",
        "evidence_role",
        "asserted_entity_kind",
        name="uq_resolution_candidate_evidence_record",
    ),
)

review_items = Table(
    "review_items",
    metadata,
    Column("id", ID, primary_key=True),
    Column("review_type", ENUM, nullable=False),
    Column("subject_kind", ENUM, nullable=False),
    Column("subject_id", ID, nullable=False),
    Column("candidate_kind", ENUM, nullable=False),
    Column("candidate_id", ID, nullable=False),
    Column("producer_name", Text, nullable=False),
    Column("producer_version", Text, nullable=False),
    Column("decision_compatibility_version", Text, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("state", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "review_type IN ('AUTHORITY_RESOLUTION', 'CLASSIFICATION', 'MATCH_RELATION', "
        "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', 'METADATA_CORRECTION')",
        name="ck_review_items_type",
    ),
    CheckConstraint(
        "candidate_kind IN ('RESOLUTION_CANDIDATE', 'CLASSIFICATION_ASSERTION', "
        "'RELATION', 'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', "
        "'METADATA_CORRECTION_CANDIDATE')",
        name="ck_review_items_candidate_kind",
    ),
    CheckConstraint(
        "(review_type = 'METADATA_CORRECTION' "
        "AND candidate_kind = 'METADATA_CORRECTION_CANDIDATE') OR "
        "(review_type <> 'METADATA_CORRECTION' "
        "AND candidate_kind <> 'METADATA_CORRECTION_CANDIDATE')",
        name="ck_review_items_metadata_correction_pair",
    ),
    CheckConstraint(
        "state IN ('PENDING', 'DECIDED', 'DEFERRED', 'STALE')",
        name="ck_review_items_state",
    ),
    CheckConstraint(
        "length(evidence_fingerprint) = 64 "
        "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
        "AND length(candidate_set_fingerprint) = 64 "
        "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_review_items_fingerprints",
    ),
    UniqueConstraint(
        "review_type",
        "subject_kind",
        "subject_id",
        "candidate_kind",
        "candidate_id",
        "producer_name",
        "decision_compatibility_version",
        "evidence_fingerprint",
        "candidate_set_fingerprint",
        name="uq_review_items_exact_case",
    ),
)

review_decisions = Table(
    "review_decisions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("review_item_id", ID, ForeignKey("review_items.id"), nullable=False),
    Column("sequence_no", Integer, nullable=False),
    Column("decision", ENUM, nullable=False),
    Column("decision_reason", Text, nullable=False),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("decision_compatibility_version", Text, nullable=False),
    Column("actor_kind", ENUM, nullable=False),
    Column("decided_at", DATETIME, nullable=False),
    CheckConstraint("sequence_no >= 1", name="ck_review_decisions_sequence"),
    CheckConstraint(
        "decision IN ('ACCEPT', 'REJECT', 'DEFER')",
        name="ck_review_decisions_value",
    ),
    CheckConstraint("actor_kind IN ('USER', 'SYSTEM')", name="ck_review_decisions_actor"),
    CheckConstraint(
        "decision_reason NOT GLOB '*[^A-Z0-9_]*' AND length(decision_reason) BETWEEN 1 AND 64",
        name="ck_review_decisions_reason",
    ),
    CheckConstraint(
        "length(evidence_fingerprint) = 64 "
        "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
        "AND length(candidate_set_fingerprint) = 64 "
        "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_review_decisions_fingerprints",
    ),
    UniqueConstraint(
        "review_item_id",
        "sequence_no",
        name="uq_review_decisions_item_sequence",
    ),
)

Index(
    "ix_resolution_candidates_subject_created",
    resolution_candidates.c.subject_kind,
    resolution_candidates.c.subject_id,
    resolution_candidates.c.candidate_kind,
    resolution_candidates.c.created_at,
    resolution_candidates.c.id,
)
Index(
    "ix_resolution_candidates_reuse",
    resolution_candidates.c.subject_kind,
    resolution_candidates.c.subject_id,
    resolution_candidates.c.candidate_kind,
    resolution_candidates.c.candidate_entity_id,
    resolution_candidates.c.resolver_name,
    resolution_candidates.c.decision_compatibility_version,
    resolution_candidates.c.evidence_fingerprint,
    resolution_candidates.c.candidate_set_fingerprint,
)
Index(
    "ix_resolution_candidate_evidence_source",
    resolution_candidate_evidence.c.evidence_kind,
    resolution_candidate_evidence.c.evidence_id,
    resolution_candidate_evidence.c.resolution_candidate_id,
)
Index(
    "ix_review_items_queue",
    review_items.c.state,
    review_items.c.review_type,
    review_items.c.created_at,
    review_items.c.id,
)
Index(
    "ix_review_items_subject_history",
    review_items.c.review_type,
    review_items.c.subject_kind,
    review_items.c.subject_id,
    review_items.c.created_at,
    review_items.c.id,
)
Index(
    "ix_review_decisions_item_sequence",
    review_decisions.c.review_item_id,
    review_decisions.c.sequence_no,
)
