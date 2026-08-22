"""Add immutable book-only CollectionState persistence.

Revision ID: 0023_collection_state
Revises: 0022_quarantine_execution_persistence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.collection_state_schema import COLLECTION_STATE_TABLES

revision: str = "0023_collection_state"
down_revision: str | None = "0022_quarantine_execution_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in COLLECTION_STATE_TABLES:
        table.create(bind)
    for table in COLLECTION_STATE_TABLES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_update BEFORE UPDATE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable collection state'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_delete BEFORE DELETE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable collection state'); END"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(
        sa.text(
            "SELECT 1 FROM collection_state_snapshots "
            "UNION ALL SELECT 1 FROM collection_state_components "
            "UNION ALL SELECT 1 FROM collection_state_counts "
            "UNION ALL SELECT 1 FROM collection_state_items LIMIT 1"
        )
    ).first()
    if occupied is not None:
        raise RuntimeError("CollectionState data prevents migration downgrade")
    for table in reversed(COLLECTION_STATE_TABLES):
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_delete"))
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_update"))
        table.drop(bind)
