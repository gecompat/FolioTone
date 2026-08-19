"""Persist immutable book-classification lineage and projections.

Revision ID: 0018_book_classification_projection
Revises: 0017_provider_cache_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.classification_schema import CLASSIFICATION_PROJECTION_TABLES

revision: str = "0018_book_classification_projection"
down_revision: str | None = "0017_provider_cache_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in CLASSIFICATION_PROJECTION_TABLES:
        table.create(bind)
    op.create_index(
        "ix_classification_assertions_target_id",
        "classification_assertions",
        ["target_kind", "target_id", "id"],
    )
    op.create_index(
        "ix_book_classification_lineage_profile_assertion",
        "book_classification_assertion_lineage",
        ["assertion_profile_version", "assertion_id"],
    )
    op.create_index(
        "ix_book_classification_projections_target_profile_created",
        "book_classification_projections",
        ["target_kind", "target_id", "projection_profile_version", "created_at", "id"],
    )
    op.create_index(
        "ix_book_classification_projection_values_projection_dimension_ordinal",
        "book_classification_projection_values",
        ["projection_id", "dimension", "ordinal"],
    )
    op.create_index(
        "ix_book_classification_projection_assertions_assertion_projection",
        "book_classification_projection_assertions",
        ["assertion_id", "projection_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in CLASSIFICATION_PROJECTION_TABLES
    )
    if bind.execute(sa.text(f"{union} LIMIT 1")).first() is not None:
        raise RuntimeError("book-classification data prevents migration downgrade")
    op.drop_index(
        "ix_book_classification_projection_assertions_assertion_projection",
        table_name="book_classification_projection_assertions",
    )
    op.drop_index(
        "ix_book_classification_projection_values_projection_dimension_ordinal",
        table_name="book_classification_projection_values",
    )
    op.drop_index(
        "ix_book_classification_projections_target_profile_created",
        table_name="book_classification_projections",
    )
    op.drop_index(
        "ix_book_classification_lineage_profile_assertion",
        table_name="book_classification_assertion_lineage",
    )
    op.drop_index(
        "ix_classification_assertions_target_id",
        table_name="classification_assertions",
    )
    for table in reversed(CLASSIFICATION_PROJECTION_TABLES):
        table.drop(bind)
