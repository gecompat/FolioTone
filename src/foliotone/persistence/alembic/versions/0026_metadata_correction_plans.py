"""Persist immutable metadata correction candidates and plans.

Revision ID: 0026_metadata_correction_plans
Revises: 0025_library_health
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence import consolidation_schema as consolidation
from foliotone.persistence import metadata_correction_schema as correction
from foliotone.persistence import resolution_review_schema as review
from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0026_metadata_correction_plans"
down_revision: str | None = "0025_library_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_METADATA_TABLE_NAMES = tuple(table.name for table in correction.METADATA_CORRECTION_TABLES)
_REVIEW_BACKUPS = (
    (consolidation.consolidation_plan_reviews, "_0026_consolidation_plan_reviews"),
    (review.review_decisions, "_0026_review_decisions"),
    (review.review_items, "_0026_review_items"),
)


def _review_items_table(*, metadata_correction: bool) -> sa.Table:
    metadata = sa.MetaData()
    review_types = (
        "'AUTHORITY_RESOLUTION', 'CLASSIFICATION', 'MATCH_RELATION', "
        "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE'"
    )
    candidate_kinds = (
        "'RESOLUTION_CANDIDATE', 'CLASSIFICATION_ASSERTION', 'RELATION', "
        "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE'"
    )
    if metadata_correction:
        review_types += ", 'METADATA_CORRECTION'"
        candidate_kinds += ", 'METADATA_CORRECTION_CANDIDATE'"
    table = sa.Table(
        "review_items",
        metadata,
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
            f"review_type IN ({review_types})",
            name="ck_review_items_type",
        ),
        sa.CheckConstraint(
            f"candidate_kind IN ({candidate_kinds})",
            name="ck_review_items_candidate_kind",
        ),
        *(
            (
                sa.CheckConstraint(
                    "(review_type = 'METADATA_CORRECTION' "
                    "AND candidate_kind = 'METADATA_CORRECTION_CANDIDATE') OR "
                    "(review_type <> 'METADATA_CORRECTION' "
                    "AND candidate_kind <> 'METADATA_CORRECTION_CANDIDATE')",
                    name="ck_review_items_metadata_correction_pair",
                ),
            )
            if metadata_correction
            else ()
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
    sa.Index(
        "ix_review_items_queue",
        table.c.state,
        table.c.review_type,
        table.c.created_at,
        table.c.id,
    )
    sa.Index(
        "ix_review_items_subject_history",
        table.c.review_type,
        table.c.subject_kind,
        table.c.subject_id,
        table.c.created_at,
        table.c.id,
    )
    return table


def _quoted_columns(table: sa.Table) -> str:
    return ", ".join(f'"{column.name}"' for column in table.columns)


def _backup_table(bind: sa.Connection, table: sa.Table, backup: str) -> None:
    columns = _quoted_columns(table)
    bind.exec_driver_sql(
        f'CREATE TEMPORARY TABLE "{backup}" AS SELECT {columns} FROM "{table.name}"'
    )
    table.drop(bind)


def _restore_table(bind: sa.Connection, table: sa.Table, backup: str) -> None:
    columns = _quoted_columns(table)
    bind.exec_driver_sql(f'INSERT INTO "{table.name}" ({columns}) SELECT {columns} FROM "{backup}"')
    bind.exec_driver_sql(f'DROP TABLE "{backup}"')


def _rebuild_review_constraints(bind: sa.Connection, *, metadata_correction: bool) -> None:
    for table, backup in _REVIEW_BACKUPS:
        _backup_table(bind, table, backup)

    rebuilt_items = _review_items_table(metadata_correction=metadata_correction)
    rebuilt_items.create(bind)
    _restore_table(bind, rebuilt_items, "_0026_review_items")

    review.review_decisions.create(bind)
    _restore_table(bind, review.review_decisions, "_0026_review_decisions")

    consolidation.consolidation_plan_reviews.create(bind)
    _restore_table(
        bind,
        consolidation.consolidation_plan_reviews,
        "_0026_consolidation_plan_reviews",
    )


def _create_immutable_triggers(bind: sa.Connection) -> None:
    for table_name in _METADATA_TABLE_NAMES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_update BEFORE UPDATE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, 'metadata correction rows are immutable'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_delete BEFORE DELETE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, 'metadata correction rows are immutable'); END"
            )
        )


def _create_bounded_triggers(bind: sa.Connection) -> None:
    statements = {
        "metadata_correction_fields_bounded_insert": (
            "metadata_correction_fields",
            "NEW.ordinal >= COALESCE((SELECT field_count FROM "
            "metadata_correction_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "metadata_correction_values_bounded_insert": (
            "metadata_correction_values",
            "NEW.ordinal >= COALESCE((SELECT CASE NEW.value_set "
            "WHEN 'OBSERVED' THEN observed_count ELSE selected_count END FROM "
            "metadata_correction_fields WHERE candidate_id = NEW.candidate_id "
            "AND ordinal = NEW.field_ordinal), 0)",
        ),
        "metadata_correction_field_evidence_bounded_insert": (
            "metadata_correction_field_evidence",
            "NEW.ordinal >= COALESCE((SELECT evidence_count FROM metadata_correction_fields "
            "WHERE candidate_id = NEW.candidate_id AND ordinal = NEW.field_ordinal), 0)",
        ),
        "metadata_correction_evidence_bounded_insert": (
            "metadata_correction_evidence",
            "NEW.ordinal >= COALESCE((SELECT evidence_count FROM "
            "metadata_correction_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "metadata_correction_dependencies_bounded_insert": (
            "metadata_correction_dependencies",
            "NEW.ordinal >= COALESCE((SELECT dependency_count FROM "
            "metadata_correction_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "metadata_correction_plan_reviews_bounded_insert": (
            "metadata_correction_plan_reviews",
            "COALESCE((SELECT review_count FROM metadata_correction_plans "
            "WHERE id = NEW.plan_id), 0) <> 1",
        ),
        "metadata_correction_plan_preconditions_bounded_insert": (
            "metadata_correction_plan_preconditions",
            "NEW.ordinal >= COALESCE((SELECT precondition_count FROM "
            "metadata_correction_plans WHERE id = NEW.plan_id), 0)",
        ),
        "metadata_correction_verification_fields_bounded_insert": (
            "metadata_correction_verification_fields",
            "NEW.ordinal >= COALESCE((SELECT changed_field_count FROM "
            "metadata_correction_verifications WHERE plan_id = NEW.plan_id), 0)",
        ),
        "metadata_correction_verification_dependencies_bounded_insert": (
            "metadata_correction_verification_dependencies",
            "NEW.ordinal >= COALESCE((SELECT dependency_count FROM "
            "metadata_correction_verifications WHERE plan_id = NEW.plan_id), 0)",
        ),
        "metadata_correction_plan_blockers_bounded_insert": (
            "metadata_correction_plan_blockers",
            "NEW.ordinal >= COALESCE((SELECT blocker_count FROM metadata_correction_plans "
            "WHERE id = NEW.plan_id), 0)",
        ),
        "metadata_correction_plan_blocker_evidence_bounded_insert": (
            "metadata_correction_plan_blocker_evidence",
            "NEW.ordinal >= COALESCE((SELECT evidence_count FROM "
            "metadata_correction_plan_blockers WHERE plan_id = NEW.plan_id "
            "AND ordinal = NEW.blocker_ordinal), 0)",
        ),
    }
    for trigger_name, (table_name, condition) in statements.items():
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON {table_name} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, "
                "'metadata correction child exceeds parent count'); END"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    _rebuild_review_constraints(bind, metadata_correction=True)
    for table in correction.METADATA_CORRECTION_TABLES:
        table.create(bind)
    _create_immutable_triggers(bind)
    _create_bounded_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table_name}" for table_name in _METADATA_TABLE_NAMES
    )
    occupied = bind.execute(sa.text(f"{union} LIMIT 1")).first()
    metadata_review = bind.execute(
        sa.text(
            "SELECT 1 FROM review_items WHERE review_type = 'METADATA_CORRECTION' "
            "OR candidate_kind = 'METADATA_CORRECTION_CANDIDATE' LIMIT 1"
        )
    ).first()
    if occupied is not None or metadata_review is not None:
        raise RuntimeError("metadata correction data prevents migration downgrade")

    for table in reversed(correction.METADATA_CORRECTION_TABLES):
        table.drop(bind)
    _rebuild_review_constraints(bind, metadata_correction=False)
