"""Persist relation candidates and their feature evidence.

Revision ID: 0014_relation_candidates
Revises: 0013_resolution_review_core
Created: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0014_relation_candidates"
down_revision: str | None = "0013_resolution_review_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "relation_candidates",
        sa.Column("id", ID, primary_key=True),
        sa.Column("scan_root_id", ID, sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column("source_scan_run_id", ID, sa.ForeignKey("scan_runs.id"), nullable=False),
        sa.Column("left_kind", ENUM, nullable=False),
        sa.Column("left_id", ID, nullable=False),
        sa.Column("right_kind", ENUM, nullable=False),
        sa.Column("right_id", ID, nullable=False),
        sa.Column("relation_type", ENUM, nullable=False),
        sa.Column("matcher_name", sa.Text(), nullable=False),
        sa.Column("matcher_version", sa.Text(), nullable=False),
        sa.Column("decision_compatibility_version", sa.Text(), nullable=False),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("candidate_set_fingerprint", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("created_at", DATETIME, nullable=False),
        sa.CheckConstraint("left_id < right_id", name="ck_relation_candidates_canonical_pair"),
        sa.CheckConstraint(
            "confidence BETWEEN 0.0 AND 1.0", name="ck_relation_candidates_confidence"
        ),
        sa.CheckConstraint(
            "status IN ('CONFIRMED','REVIEW_REQUIRED','REJECTED')",
            name="ck_relation_candidates_status",
        ),
        sa.CheckConstraint(
            "(relation_type = 'EXACT_DUPLICATE' AND left_kind = 'FILE' "
            "AND right_kind = 'FILE') "
            "OR (relation_type = 'SAME_EDITION' AND left_kind = 'EDITION' "
            "AND right_kind = 'EDITION') "
            "OR (relation_type = 'SAME_WORK' AND left_kind = 'WORK' "
            "AND right_kind = 'WORK')",
            name="ck_relation_candidates_type_level",
        ),
        sa.CheckConstraint(
            "length(matcher_name) > 0 AND length(matcher_version) > 0 "
            "AND length(decision_compatibility_version) > 0",
            name="ck_relation_candidates_versions",
        ),
        sa.CheckConstraint(
            "status <> 'CONFIRMED' OR relation_type = 'EXACT_DUPLICATE'",
            name="ck_relation_candidates_confirmation",
        ),
        sa.CheckConstraint(
            "length(evidence_fingerprint)=64 "
            "AND evidence_fingerprint NOT GLOB '*[^0-9a-f]*' "
            "AND length(candidate_set_fingerprint)=64 "
            "AND candidate_set_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_relation_candidates_fingerprints",
        ),
        sa.UniqueConstraint(
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
    op.create_table(
        "relation_candidate_evidence",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "relation_candidate_id",
            ID,
            sa.ForeignKey("relation_candidates.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("feature_code", ENUM, nullable=False),
        sa.Column("feature_state", ENUM, nullable=False),
        sa.Column("material_fingerprint", sa.Text(), nullable=False),
        sa.Column("evidence_kind", ENUM),
        sa.Column("evidence_id", ID),
        sa.CheckConstraint("ordinal >= 0", name="ck_relation_candidate_evidence_ordinal"),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "feature_state IN ('PRESENT','ABSENT')",
            name="ck_relation_candidate_evidence_state",
        ),
        sa.CheckConstraint(
            "evidence_kind IS NULL OR evidence_kind IN "
            "('FINGERPRINT','VALUE_ASSERTION','EXTERNAL_IDENTIFIER',"
            "'RESOLUTION_CANDIDATE','TOOL_RESULT','CLASSIFICATION_ASSERTION',"
            "'REVIEW_DECISION')",
            name="ck_relation_candidate_evidence_kind",
        ),
        sa.CheckConstraint(
            "(evidence_kind IS NULL) = (evidence_id IS NULL)",
            name="ck_relation_candidate_evidence_reference",
        ),
        sa.CheckConstraint(
            "length(material_fingerprint)=64 AND material_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_relation_candidate_evidence_fingerprint",
        ),
        sa.UniqueConstraint(
            "relation_candidate_id",
            "ordinal",
            name="uq_relation_candidate_evidence_ordinal",
        ),
    )
    op.create_index(
        "ix_relation_candidates_pair_created",
        "relation_candidates",
        [
            "scan_root_id",
            "source_scan_run_id",
            "left_kind",
            "left_id",
            "right_id",
            "created_at",
            "id",
        ],
    )
    op.create_index(
        "ix_relation_candidates_reuse",
        "relation_candidates",
        [
            "left_kind",
            "left_id",
            "right_kind",
            "right_id",
            "relation_type",
            "matcher_name",
            "decision_compatibility_version",
            "evidence_fingerprint",
            "candidate_set_fingerprint",
        ],
    )
    op.create_index(
        "ix_relation_candidate_evidence_source",
        "relation_candidate_evidence",
        ["evidence_kind", "evidence_id", "relation_candidate_id"],
    )


def downgrade() -> None:
    populated = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM relation_candidates UNION ALL "
                "SELECT 1 FROM relation_candidate_evidence LIMIT 1"
            )
        )
        .first()
    )
    if populated is not None:
        raise RuntimeError("relation candidate data prevents migration downgrade")
    op.drop_index("ix_relation_candidate_evidence_source", table_name="relation_candidate_evidence")
    op.drop_index("ix_relation_candidates_reuse", table_name="relation_candidates")
    op.drop_index("ix_relation_candidates_pair_created", table_name="relation_candidates")
    op.drop_table("relation_candidate_evidence")
    op.drop_table("relation_candidates")
