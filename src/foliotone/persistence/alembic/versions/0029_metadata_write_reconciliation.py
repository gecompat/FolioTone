"""Bind metadata-write outcomes to one exact post-write collection state.

Revision ID: 0029_metadata_write_reconciliation
Revises: 0028_metadata_write_backend
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.metadata_write_schema import (
    metadata_write_reconciliations,
)

revision: str = "0029_metadata_write_reconciliation"
down_revision: str | None = "0028_metadata_write_backend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata_write_reconciliations.create(bind)
    bind.execute(
        sa.text(
            "CREATE TRIGGER metadata_write_reconciliations_no_update "
            "BEFORE UPDATE ON metadata_write_reconciliations "
            "BEGIN SELECT RAISE(ABORT, 'immutable metadata write reconciliation'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER metadata_write_reconciliations_no_delete "
            "BEFORE DELETE ON metadata_write_reconciliations "
            "BEGIN SELECT RAISE(ABORT, 'immutable metadata write reconciliation'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(sa.text("SELECT 1 FROM metadata_write_reconciliations LIMIT 1")).first()
    if occupied is not None:
        raise RuntimeError("metadata write reconciliation prevents migration downgrade")
    bind.execute(sa.text("DROP TRIGGER metadata_write_reconciliations_no_delete"))
    bind.execute(sa.text("DROP TRIGGER metadata_write_reconciliations_no_update"))
    metadata_write_reconciliations.drop(bind)
