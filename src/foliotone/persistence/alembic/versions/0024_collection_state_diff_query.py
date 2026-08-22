"""Add immutable CollectionState query projections and local metadata FTS.

Revision ID: 0024_collection_state_diff_query
Revises: 0023_collection_state
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.collection_query_schema import COLLECTION_QUERY_TABLES

revision: str = "0024_collection_state_diff_query"
down_revision: str | None = "0023_collection_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in COLLECTION_QUERY_TABLES:
        table.create(bind)
    bind.execute(
        sa.text(
            "CREATE VIRTUAL TABLE collection_query_values_fts USING fts5("
            "normalized_value, content='collection_query_values', content_rowid='row_id', "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER collection_query_values_fts_insert "
            "AFTER INSERT ON collection_query_values "
            "WHEN new.value_kind='METADATA_CANDIDATE' BEGIN "
            "INSERT INTO collection_query_values_fts(rowid, normalized_value) "
            "VALUES (new.row_id, new.normalized_value); END"
        )
    )
    for table in COLLECTION_QUERY_TABLES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_update BEFORE UPDATE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable collection query index'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_delete BEFORE DELETE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable collection query index'); END"
            )
        )
    bind.execute(
        sa.text(
            "CREATE TRIGGER collection_query_documents_bounded_insert "
            "BEFORE INSERT ON collection_query_documents WHEN new.ordinal >= COALESCE("
            "(SELECT document_count FROM collection_query_indexes "
            "WHERE snapshot_id=new.snapshot_id), 0) "
            "BEGIN SELECT RAISE(ABORT, 'sealed collection query document range'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER collection_query_values_bounded_insert "
            "BEFORE INSERT ON collection_query_values WHEN new.ordinal >= COALESCE("
            "(SELECT value_count FROM collection_query_documents "
            "WHERE snapshot_id=new.snapshot_id AND ordinal=new.document_ordinal), 0) "
            "BEGIN SELECT RAISE(ABORT, 'sealed collection query value range'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(
        sa.text(
            "SELECT 1 FROM collection_query_indexes "
            "UNION ALL SELECT 1 FROM collection_query_documents "
            "UNION ALL SELECT 1 FROM collection_query_values LIMIT 1"
        )
    ).first()
    if occupied is not None:
        raise RuntimeError("Collection query data prevents migration downgrade")
    bind.execute(sa.text("DROP TRIGGER collection_query_values_bounded_insert"))
    bind.execute(sa.text("DROP TRIGGER collection_query_documents_bounded_insert"))
    for table in reversed(COLLECTION_QUERY_TABLES):
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_delete"))
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_update"))
    bind.execute(sa.text("DROP TRIGGER collection_query_values_fts_insert"))
    bind.execute(sa.text("DROP TABLE collection_query_values_fts"))
    for table in reversed(COLLECTION_QUERY_TABLES):
        table.drop(bind)
