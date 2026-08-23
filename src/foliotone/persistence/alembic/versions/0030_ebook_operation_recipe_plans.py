"""Persist immutable, non-executable e-book operation recipe snapshots.

Revision ID: 0030_ebook_operation_recipe_plans
Revises: 0029_metadata_write_reconciliation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence import consolidation_schema as consolidation
from foliotone.persistence import ebook_operation_recipe_schema as recipe
from foliotone.persistence import metadata_correction_schema as correction
from foliotone.persistence import resolution_review_schema as review
from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0030_ebook_operation_recipe_plans"
down_revision: str | None = "0029_metadata_write_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECIPE_TABLE_NAMES = tuple(table.name for table in recipe.EBOOK_OPERATION_RECIPE_TABLES)
_REVIEW_BACKUPS = (
    (consolidation.consolidation_plan_reviews, "_0030_consolidation_plan_reviews"),
    (correction.metadata_correction_plan_reviews, "_0030_metadata_correction_plan_reviews"),
    (review.review_decisions, "_0030_review_decisions"),
    (review.review_items, "_0030_review_items"),
)


def _review_items_table(*, ebook_operation_recipe: bool) -> sa.Table:
    metadata = sa.MetaData()
    review_types = (
        "'AUTHORITY_RESOLUTION', 'CLASSIFICATION', 'MATCH_RELATION', "
        "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', 'METADATA_CORRECTION'"
    )
    candidate_kinds = (
        "'RESOLUTION_CANDIDATE', 'CLASSIFICATION_ASSERTION', 'RELATION', "
        "'KEEP_PREFERENCE', 'CONSOLIDATION_CANDIDATE', "
        "'METADATA_CORRECTION_CANDIDATE'"
    )
    if ebook_operation_recipe:
        review_types += ", 'EBOOK_OPERATION_RECIPE'"
        candidate_kinds += ", 'EBOOK_OPERATION_RECIPE_CANDIDATE'"
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
        sa.CheckConstraint(
            "(review_type = 'METADATA_CORRECTION' "
            "AND candidate_kind = 'METADATA_CORRECTION_CANDIDATE') OR "
            "(review_type <> 'METADATA_CORRECTION' "
            "AND candidate_kind <> 'METADATA_CORRECTION_CANDIDATE')",
            name="ck_review_items_metadata_correction_pair",
        ),
        *(
            (
                sa.CheckConstraint(
                    "(review_type = 'EBOOK_OPERATION_RECIPE' "
                    "AND candidate_kind = 'EBOOK_OPERATION_RECIPE_CANDIDATE') OR "
                    "(review_type <> 'EBOOK_OPERATION_RECIPE' "
                    "AND candidate_kind <> 'EBOOK_OPERATION_RECIPE_CANDIDATE')",
                    name="ck_review_items_ebook_operation_recipe_pair",
                ),
            )
            if ebook_operation_recipe
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


def _backup_table(
    bind: sa.Connection,
    table: sa.Table,
    backup: str,
) -> tuple[str, ...]:
    trigger_sql = tuple(
        str(row.sql)
        for row in bind.execute(
            sa.text(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = :table_name AND sql IS NOT NULL ORDER BY name"
            ),
            {"table_name": table.name},
        )
    )
    columns = _quoted_columns(table)
    bind.exec_driver_sql(
        f'CREATE TEMPORARY TABLE "{backup}" AS SELECT {columns} FROM "{table.name}"'
    )
    table.drop(bind)
    return trigger_sql


def _restore_table(
    bind: sa.Connection,
    table: sa.Table,
    backup: str,
    trigger_sql: tuple[str, ...],
) -> None:
    columns = _quoted_columns(table)
    bind.exec_driver_sql(
        f'INSERT INTO "{table.name}" ({columns}) SELECT {columns} FROM "{backup}"'
    )
    bind.exec_driver_sql(f'DROP TABLE "{backup}"')
    for statement in trigger_sql:
        bind.exec_driver_sql(statement)


def _rebuild_review_constraints(
    bind: sa.Connection,
    *,
    ebook_operation_recipe: bool,
) -> None:
    triggers = {
        table.name: _backup_table(bind, table, backup)
        for table, backup in _REVIEW_BACKUPS
    }

    rebuilt_items = _review_items_table(
        ebook_operation_recipe=ebook_operation_recipe,
    )
    rebuilt_items.create(bind)
    _restore_table(
        bind,
        rebuilt_items,
        "_0030_review_items",
        triggers[review.review_items.name],
    )

    review.review_decisions.create(bind)
    _restore_table(
        bind,
        review.review_decisions,
        "_0030_review_decisions",
        triggers[review.review_decisions.name],
    )

    for table, backup in _REVIEW_BACKUPS[:2]:
        table.create(bind)
        _restore_table(bind, table, backup, triggers[table.name])


def _create_immutable_triggers(bind: sa.Connection) -> None:
    for table_name in _RECIPE_TABLE_NAMES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_update BEFORE UPDATE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, "
                "'e-book operation recipe rows are immutable'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_delete BEFORE DELETE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, "
                "'e-book operation recipe rows are immutable'); END"
            )
        )


def _create_bounded_triggers(bind: sa.Connection) -> None:
    statements = {
        "ebook_operation_recipe_sources_bounded_insert": (
            "ebook_operation_recipe_sources",
            "NEW.ordinal >= COALESCE((SELECT source_count FROM "
            "ebook_operation_recipe_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "ebook_operation_recipe_dependencies_bounded_insert": (
            "ebook_operation_recipe_dependencies",
            "NEW.ordinal >= COALESCE((SELECT dependency_count FROM "
            "ebook_operation_recipe_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "ebook_operation_recipe_verifications_bounded_insert": (
            "ebook_operation_recipe_verifications",
            "NEW.ordinal >= COALESCE((SELECT verification_count FROM "
            "ebook_operation_recipe_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "ebook_operation_recipe_evidence_bounded_insert": (
            "ebook_operation_recipe_evidence",
            "NEW.ordinal >= COALESCE((SELECT evidence_count FROM "
            "ebook_operation_recipe_candidates WHERE id = NEW.candidate_id), 0)",
        ),
        "ebook_operation_recipe_plan_reviews_bounded_insert": (
            "ebook_operation_recipe_plan_reviews",
            "COALESCE((SELECT review_count FROM ebook_operation_recipe_plans "
            "WHERE id = NEW.plan_id), 0) <> 1",
        ),
        "ebook_operation_recipe_plan_preconditions_bounded_insert": (
            "ebook_operation_recipe_plan_preconditions",
            "NEW.ordinal >= COALESCE((SELECT precondition_count FROM "
            "ebook_operation_recipe_plans WHERE id = NEW.plan_id), 0)",
        ),
        "ebook_operation_recipe_plan_blockers_bounded_insert": (
            "ebook_operation_recipe_plan_blockers",
            "NEW.ordinal >= COALESCE((SELECT blocker_count FROM "
            "ebook_operation_recipe_plans WHERE id = NEW.plan_id), 0)",
        ),
        "ebook_operation_recipe_plan_blocker_evidence_bounded_insert": (
            "ebook_operation_recipe_plan_blocker_evidence",
            "NEW.ordinal >= COALESCE((SELECT evidence_count FROM "
            "ebook_operation_recipe_plan_blockers WHERE plan_id = NEW.plan_id "
            "AND ordinal = NEW.blocker_ordinal), 0)",
        ),
    }
    for trigger_name, (table_name, condition) in statements.items():
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON {table_name} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT, "
                "'e-book operation recipe child exceeds parent count'); END"
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    _rebuild_review_constraints(bind, ebook_operation_recipe=True)
    for table in recipe.EBOOK_OPERATION_RECIPE_TABLES:
        table.create(bind)
    _create_immutable_triggers(bind)
    _create_bounded_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table_name}" for table_name in _RECIPE_TABLE_NAMES
    )
    occupied = bind.execute(sa.text(f"{union} LIMIT 1")).first()
    recipe_review = bind.execute(
        sa.text(
            "SELECT 1 FROM review_items "
            "WHERE review_type = 'EBOOK_OPERATION_RECIPE' "
            "OR candidate_kind = 'EBOOK_OPERATION_RECIPE_CANDIDATE' LIMIT 1"
        )
    ).first()
    if occupied is not None or recipe_review is not None:
        raise RuntimeError("e-book operation recipe data prevents migration downgrade")

    for table in reversed(recipe.EBOOK_OPERATION_RECIPE_TABLES):
        table.drop(bind)
    _rebuild_review_constraints(bind, ebook_operation_recipe=False)
