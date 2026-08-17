"""Add persisted resolution candidates and append-only review decisions.

Revision ID: 0013_resolution_review_core
Revises: 0012_scan_root_write_leases
Created: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0013_resolution_review_core"
down_revision: str | None = "0012_scan_root_write_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resolution_candidates",
        sa.Column("id", ID, primary_key=True),
        sa.Column("subject_kind", ENUM, nullable=False),
        sa.Column("subject_id", ID, nullable=False),
        sa.Column("candidate_kind", ENUM, nullable=False),
        sa.Column("candidate_entity_id", ID, nullable=False),
        sa.Column("resolver_name", sa.Text(), nullable=False),
        sa.Column("resolver_version", sa.Text(), nullable=False),
        sa.Column("decision_compatibility_version", sa.Text(), nullable=False),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("candidate_set_fingerprint", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("disposition", ENUM, nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.CheckConstraint(
            "subject_kind IN ('FILE', 'FILE_OBSERVATION', 'AGENT', 'WORK', 'EDITION', 'SERIES')",
            name="ck_resolution_candidates_subject_kind",
        ),
        sa.CheckConstraint(
            "candidate_kind IN ('AGENT', 'WORK', 'EDITION', 'SERIES')",
            name="ck_resolution_candidates_candidate_kind",
        ),
        sa.CheckConstraint(
            "subject_kind NOT IN ('AGENT', 'WORK', 'EDITION', 'SERIES') "
            "OR (subject_kind = candidate_kind AND subject_id <> candidate_entity_id)",
            name="ck_resolution_candidates_level",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0.0 AND 1.0",
            name="ck_resolution_candidates_confidence",
        ),
        sa.CheckConstraint(
            "disposition IN ('AUTO_SAFE', 'REVIEW_REQUIRED')",
            name="ck_resolution_candidates_disposition",
        ),
        sa.CheckConstraint(
            "length(evidence_fingerprint) = 64 "
            "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
            "AND length(candidate_set_fingerprint) = 64 "
            "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_resolution_candidates_fingerprints",
        ),
        sa.UniqueConstraint(
            "subject_kind", "subject_id", "candidate_kind", "candidate_entity_id",
            "resolver_name", "resolver_version", "decision_compatibility_version",
            "evidence_fingerprint", "candidate_set_fingerprint",
            name="uq_resolution_candidates_snapshot",
        ),
    )
    op.create_table(
        "resolution_candidate_evidence",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "resolution_candidate_id",
            ID,
            sa.ForeignKey("resolution_candidates.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_kind", ENUM, nullable=False),
        sa.Column("evidence_id", ID, nullable=False),
        sa.Column("evidence_role", ENUM, nullable=False),
        sa.Column("asserted_entity_kind", ENUM, nullable=False),
        sa.Column("material_fingerprint", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_resolution_candidate_evidence_ordinal"),
        sa.CheckConstraint(
            "evidence_kind IN ('VALUE_ASSERTION', 'TOOL_RESULT', 'FINGERPRINT', "
            "'EXTERNAL_IDENTIFIER', 'CLASSIFICATION_ASSERTION', 'REVIEW_DECISION')",
            name="ck_resolution_candidate_evidence_kind",
        ),
        sa.CheckConstraint(
            "evidence_role IN ('SUPPORTS', 'CONTRADICTS')",
            name="ck_resolution_candidate_evidence_role",
        ),
        sa.CheckConstraint(
            "asserted_entity_kind IN ('AGENT', 'WORK', 'EDITION', 'SERIES')",
            name="ck_resolution_candidate_evidence_entity_kind",
        ),
        sa.CheckConstraint(
            "length(material_fingerprint) = 64 "
            "AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_resolution_candidate_evidence_fingerprint",
        ),
        sa.UniqueConstraint(
            "resolution_candidate_id", "ordinal",
            name="uq_resolution_candidate_evidence_ordinal",
        ),
        sa.UniqueConstraint(
            "resolution_candidate_id", "evidence_kind", "evidence_id", "evidence_role",
            "asserted_entity_kind", name="uq_resolution_candidate_evidence_record",
        ),
    )
    op.create_table(
        "review_items",
        sa.Column("id", ID, primary_key=True),
        sa.Column("review_type", ENUM, nullable=False),
        sa.Column("subject_kind", ENUM, nullable=False),
        sa.Column("subject_id", ID, nullable=False),
        sa.Column("candidate_kind", ENUM, nullable=False),
        sa.Column("candidate_id", ID, nullable=False),
        sa.Column("producer_name", sa.Text(), nullable=False),
        sa.Column("producer_version", sa.Text(), nullable=False),
        sa.Column("decision_compatibility_version", sa.Text(), nullable=False),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("candidate_set_fingerprint", sa.Text(), nullable=False),
        sa.Column("state", ENUM, nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.CheckConstraint(
            "review_type IN ('AUTHORITY_RESOLUTION', 'CLASSIFICATION', 'MATCH_RELATION', "
            "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE')",
            name="ck_review_items_type",
        ),
        sa.CheckConstraint(
            "candidate_kind IN ('RESOLUTION_CANDIDATE', 'CLASSIFICATION_ASSERTION', "
            "'RELATION', 'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE')",
            name="ck_review_items_candidate_kind",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'DECIDED', 'DEFERRED', 'STALE')",
            name="ck_review_items_state",
        ),
        sa.CheckConstraint(
            "length(evidence_fingerprint) = 64 "
            "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
            "AND length(candidate_set_fingerprint) = 64 "
            "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_review_items_fingerprints",
        ),
        sa.UniqueConstraint(
            "review_type", "subject_kind", "subject_id", "candidate_kind", "candidate_id",
            "producer_name", "decision_compatibility_version", "evidence_fingerprint",
            "candidate_set_fingerprint", name="uq_review_items_exact_case",
        ),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("review_item_id", ID, sa.ForeignKey("review_items.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("decision", ENUM, nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("candidate_set_fingerprint", sa.Text(), nullable=False),
        sa.Column("decision_compatibility_version", sa.Text(), nullable=False),
        sa.Column("actor_kind", ENUM, nullable=False),
        sa.Column("decided_at", DATETIME, nullable=False),
        sa.CheckConstraint("sequence_no >= 1", name="ck_review_decisions_sequence"),
        sa.CheckConstraint(
            "decision IN ('ACCEPT', 'REJECT', 'DEFER')",
            name="ck_review_decisions_value",
        ),
        sa.CheckConstraint("actor_kind IN ('USER', 'SYSTEM')", name="ck_review_decisions_actor"),
        sa.CheckConstraint(
            "decision_reason NOT GLOB '*[^A-Z0-9_]*' "
            "AND length(decision_reason) BETWEEN 1 AND 64",
            name="ck_review_decisions_reason",
        ),
        sa.CheckConstraint(
            "length(evidence_fingerprint) = 64 "
            "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
            "AND length(candidate_set_fingerprint) = 64 "
            "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_review_decisions_fingerprints",
        ),
        sa.UniqueConstraint(
            "review_item_id", "sequence_no", name="uq_review_decisions_item_sequence",
        ),
    )
    op.create_index(
        "ix_resolution_candidates_subject_created", "resolution_candidates",
        ["subject_kind", "subject_id", "candidate_kind", "created_at", "id"],
    )
    op.create_index(
        "ix_resolution_candidates_reuse", "resolution_candidates",
        ["subject_kind", "subject_id", "candidate_kind", "candidate_entity_id",
         "resolver_name", "decision_compatibility_version", "evidence_fingerprint",
         "candidate_set_fingerprint"],
    )
    op.create_index(
        "ix_resolution_candidate_evidence_source", "resolution_candidate_evidence",
        ["evidence_kind", "evidence_id", "resolution_candidate_id"],
    )
    op.create_index(
        "ix_review_items_queue", "review_items",
        ["state", "review_type", "created_at", "id"],
    )
    op.create_index(
        "ix_review_items_subject_history", "review_items",
        ["review_type", "subject_kind", "subject_id", "created_at", "id"],
    )
    op.create_index(
        "ix_review_decisions_item_sequence", "review_decisions",
        ["review_item_id", "sequence_no"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(
        sa.text(
            "SELECT 1 FROM resolution_candidates UNION ALL "
            "SELECT 1 FROM resolution_candidate_evidence UNION ALL "
            "SELECT 1 FROM review_items UNION ALL SELECT 1 FROM review_decisions LIMIT 1"
        )
    ).first()
    if populated is not None:
        raise RuntimeError("resolution or review data prevents migration downgrade")
    op.drop_index("ix_review_decisions_item_sequence", table_name="review_decisions")
    op.drop_index("ix_review_items_subject_history", table_name="review_items")
    op.drop_index("ix_review_items_queue", table_name="review_items")
    op.drop_index(
        "ix_resolution_candidate_evidence_source",
        table_name="resolution_candidate_evidence",
    )
    op.drop_index("ix_resolution_candidates_reuse", table_name="resolution_candidates")
    op.drop_index(
        "ix_resolution_candidates_subject_created",
        table_name="resolution_candidates",
    )
    op.drop_table("review_decisions")
    op.drop_table("review_items")
    op.drop_table("resolution_candidate_evidence")
    op.drop_table("resolution_candidates")
