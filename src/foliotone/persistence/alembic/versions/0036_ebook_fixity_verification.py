"""Add immutable book-only fixity verification and expectation revisions.

Revision ID: 0036_ebook_fixity_verification
Revises: 0035_ebook_fixity_baseline
"""
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.fixity_verification_schema import (
    EBOOK_FIXITY_VERIFICATION_TABLES,
)

revision: str = "0036_ebook_fixity_verification"
down_revision: str | None = "0035_ebook_fixity_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OWNER_CHECK = "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND acquired_at IS NULL) OR (lease_token IS NOT NULL AND lease_token <> '' AND owner_kind IN ('SCAN_RUN', 'EBOOK_CANDIDATE_HASH_RUN', 'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS', 'ARCHIVE_COLLECTION_RUN', 'CONSOLIDATION_QUARANTINE_RUN', 'METADATA_WRITE_PREPARATION', 'METADATA_WRITE_RUN', 'EBOOK_RENAME_PREPARATION', 'EBOOK_RENAME_RUN', 'EBOOK_FIXITY_BASELINE') AND owner_run_id IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND acquired_at IS NOT NULL AND fence_epoch >= 1 AND acquired_at <= heartbeat_at AND heartbeat_at < lease_expires_at)"
_NEW_OWNER_CHECK = _OLD_OWNER_CHECK.replace(
    "'EBOOK_FIXITY_BASELINE'",
    "'EBOOK_FIXITY_BASELINE', 'EBOOK_FIXITY_VERIFICATION'",
)

_OLD_REVIEW_TYPES = "review_type IN ('AUTHORITY_RESOLUTION', 'CLASSIFICATION', 'MATCH_RELATION', 'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', 'METADATA_CORRECTION', 'EBOOK_OPERATION_RECIPE')"
_NEW_REVIEW_TYPES = _OLD_REVIEW_TYPES.replace(
    "'EBOOK_OPERATION_RECIPE'",
    "'EBOOK_OPERATION_RECIPE', 'FIXITY_EXPECTATION'",
)
_OLD_CANDIDATE_KINDS = "candidate_kind IN ('RESOLUTION_CANDIDATE', 'CLASSIFICATION_ASSERTION', 'RELATION', 'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', 'METADATA_CORRECTION_CANDIDATE', 'EBOOK_OPERATION_RECIPE_CANDIDATE')"
_NEW_CANDIDATE_KINDS = _OLD_CANDIDATE_KINDS.replace(
    "'EBOOK_OPERATION_RECIPE_CANDIDATE'",
    "'EBOOK_OPERATION_RECIPE_CANDIDATE', 'FIXITY_RESULT'",
)
_FIXITY_REVIEW_PAIR = "(review_type='FIXITY_EXPECTATION' AND candidate_kind='FIXITY_RESULT' AND subject_kind='FILE') OR (review_type<>'FIXITY_EXPECTATION' AND candidate_kind<>'FIXITY_RESULT')"


def upgrade() -> None:
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _NEW_OWNER_CHECK)

    with op.batch_alter_table("review_items") as batch:
        batch.drop_constraint("ck_review_items_type", type_="check")
        batch.drop_constraint("ck_review_items_candidate_kind", type_="check")
        batch.create_check_constraint("ck_review_items_type", _NEW_REVIEW_TYPES)
        batch.create_check_constraint(
            "ck_review_items_candidate_kind",
            _NEW_CANDIDATE_KINDS,
        )
        batch.create_check_constraint("ck_review_items_fixity_pair", _FIXITY_REVIEW_PAIR)

    bind = op.get_bind()
    for table in EBOOK_FIXITY_VERIFICATION_TABLES:
        table.create(bind)
    for table in EBOOK_FIXITY_VERIFICATION_TABLES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_update BEFORE UPDATE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable e-book fixity verification record'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_delete BEFORE DELETE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable e-book fixity verification record'); END"
            )
        )

    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_verification_events_gapless BEFORE INSERT ON "
            "ebook_fixity_verification_events WHEN NEW.sequence_no <> COALESCE((SELECT "
            "MAX(sequence_no)+1 FROM ebook_fixity_verification_events WHERE "
            "run_id=NEW.run_id),0) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity verification events must be gapless'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_verification_events_transition BEFORE INSERT ON "
            "ebook_fixity_verification_events WHEN (NEW.sequence_no=0 AND "
            "NEW.status<>'RUNNING') OR (NEW.sequence_no=1 AND NOT EXISTS (SELECT 1 "
            "FROM ebook_fixity_verification_events AS previous WHERE "
            "previous.run_id=NEW.run_id AND previous.sequence_no=0 AND "
            "previous.status='RUNNING')) BEGIN SELECT RAISE(ABORT, "
            "'invalid e-book fixity verification event transition'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_verification_results_open_run BEFORE INSERT ON "
            "ebook_fixity_verification_results WHEN EXISTS (SELECT 1 FROM "
            "ebook_fixity_verification_events WHERE run_id=NEW.run_id AND "
            "sequence_no=1) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity verification run is terminal'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_verification_complete_coverage BEFORE INSERT ON "
            "ebook_fixity_verification_events WHEN NEW.sequence_no=1 AND "
            "NEW.status='COMPLETED' AND NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_verification_runs AS run WHERE run.id=NEW.run_id AND "
            "run.expected_result_count=(SELECT COUNT(*) FROM "
            "ebook_fixity_verification_results AS result WHERE result.run_id=NEW.run_id)) "
            "BEGIN SELECT RAISE(ABORT, 'incomplete e-book fixity verification'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_expectation_revisions_gapless BEFORE INSERT ON "
            "ebook_fixity_expectation_revisions WHEN NEW.revision_no <> COALESCE((SELECT "
            "MAX(revision_no)+1 FROM ebook_fixity_expectation_revisions WHERE "
            "scan_root_id=NEW.scan_root_id),1) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity expectation revisions must be gapless'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_expectation_revisions_predecessor BEFORE INSERT ON "
            "ebook_fixity_expectation_revisions WHEN (NEW.revision_no=1 AND NOT EXISTS "
            "(SELECT 1 FROM ebook_fixity_baseline_activations AS activation WHERE "
            "activation.activation_id=NEW.baseline_activation_id AND "
            "activation.scan_root_id=NEW.scan_root_id AND "
            "activation.activation_digest=NEW.previous_revision_digest)) OR "
            "(NEW.revision_no>1 AND NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_expectation_revisions AS previous WHERE "
            "previous.scan_root_id=NEW.scan_root_id AND "
            "previous.baseline_activation_id=NEW.baseline_activation_id AND "
            "previous.revision_no=NEW.revision_no-1 AND "
            "previous.revision_digest=NEW.previous_revision_digest)) "
            "BEGIN SELECT RAISE(ABORT, 'invalid e-book fixity expectation predecessor'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_expectation_revisions_semantics BEFORE INSERT ON "
            "ebook_fixity_expectation_revisions WHEN NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_verification_results AS result JOIN "
            "ebook_fixity_verification_runs AS run ON run.id=result.run_id JOIN "
            "ebook_fixity_verification_events AS terminal ON terminal.run_id=run.id "
            "AND terminal.sequence_no=1 AND terminal.status='COMPLETED' JOIN "
            "review_items AS item ON item.candidate_id=result.id JOIN "
            "review_decisions AS decision ON decision.review_item_id=item.id "
            "WHERE result.id=NEW.source_result_id AND result.file_id=NEW.file_id "
            "AND run.scan_root_id=NEW.scan_root_id "
            "AND run.baseline_activation_id=NEW.baseline_activation_id "
            "AND run.expectation_revision_no=NEW.revision_no-1 "
            "AND run.expectation_revision_digest=NEW.previous_revision_digest "
            "AND item.review_type='FIXITY_EXPECTATION' "
            "AND item.subject_kind='FILE' AND item.subject_id=NEW.file_id "
            "AND item.candidate_kind='FIXITY_RESULT' "
            "AND item.decision_compatibility_version='ebook-fixity-decision/v1' "
            "AND item.evidence_fingerprint=NEW.evidence_fingerprint "
            "AND item.candidate_set_fingerprint=NEW.candidate_set_fingerprint "
            "AND decision.id=NEW.review_decision_id AND decision.decision='ACCEPT' "
            "AND decision.evidence_fingerprint=NEW.evidence_fingerprint "
            "AND decision.candidate_set_fingerprint=NEW.candidate_set_fingerprint "
            "AND decision.decision_compatibility_version='ebook-fixity-decision/v1' "
            "AND decision.sequence_no=(SELECT MAX(latest.sequence_no) FROM "
            "review_decisions AS latest WHERE latest.review_item_id=item.id) "
            "AND ((NEW.action='ACCEPT_CURRENT' AND result.result_type IN "
            "('UNEXPECTED_BYTE_CHANGE','UNBASELINED') "
            "AND NEW.expected_observation_id=result.current_observation_id "
            "AND NEW.expected_size_bytes=result.current_size_bytes "
            "AND NEW.expected_sha256=result.current_sha256 "
            "AND NEW.expected_relative_locator=result.current_relative_locator) OR "
            "(NEW.action='RETIRE_MISSING' AND result.result_type='MISSING' "
            "AND NEW.expected_observation_id IS NULL AND NEW.expected_size_bytes IS NULL "
            "AND NEW.expected_sha256 IS NULL "
            "AND NEW.expected_relative_locator IS NULL))) "
            "BEGIN SELECT RAISE(ABORT, 'invalid e-book fixity expectation decision'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    table_union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in EBOOK_FIXITY_VERIFICATION_TABLES
    )
    occupied = bind.execute(sa.text(f"{table_union} LIMIT 1")).first()
    active_lease = bind.execute(
        sa.text(
            "SELECT 1 FROM scan_root_write_leases WHERE "
            "owner_kind='EBOOK_FIXITY_VERIFICATION' LIMIT 1"
        )
    ).first()
    if occupied is not None or active_lease is not None:
        raise RuntimeError("e-book fixity verification state prevents migration downgrade")

    for trigger in (
        "ebook_fixity_expectation_revisions_semantics",
        "ebook_fixity_expectation_revisions_predecessor",
        "ebook_fixity_expectation_revisions_gapless",
        "ebook_fixity_verification_complete_coverage",
        "ebook_fixity_verification_results_open_run",
        "ebook_fixity_verification_events_transition",
        "ebook_fixity_verification_events_gapless",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(EBOOK_FIXITY_VERIFICATION_TABLES):
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_delete"))
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_update"))
        table.drop(bind)

    with op.batch_alter_table("review_items") as batch:
        batch.drop_constraint("ck_review_items_fixity_pair", type_="check")
        batch.drop_constraint("ck_review_items_candidate_kind", type_="check")
        batch.drop_constraint("ck_review_items_type", type_="check")
        batch.create_check_constraint("ck_review_items_type", _OLD_REVIEW_TYPES)
        batch.create_check_constraint(
            "ck_review_items_candidate_kind",
            _OLD_CANDIDATE_KINDS,
        )

    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _OLD_OWNER_CHECK)
