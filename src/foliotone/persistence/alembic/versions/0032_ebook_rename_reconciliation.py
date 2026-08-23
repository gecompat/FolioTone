"""Bind e-book rename outcomes to exact post-operation collection state.

Revision ID: 0032_ebook_rename_reconciliation
Revises: 0031_ebook_rename_operations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.ebook_rename_schema import (
    ebook_rename_reconciliations,
)

revision: str = "0032_ebook_rename_reconciliation"
down_revision: str | None = "0031_ebook_rename_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    ebook_rename_reconciliations.create(bind)
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_rename_reconciliations_no_update "
            "BEFORE UPDATE ON ebook_rename_reconciliations "
            "BEGIN SELECT RAISE(ABORT, 'immutable e-book rename reconciliation'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_rename_reconciliations_no_delete "
            "BEFORE DELETE ON ebook_rename_reconciliations "
            "BEGIN SELECT RAISE(ABORT, 'immutable e-book rename reconciliation'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(
        sa.text("SELECT 1 FROM ebook_rename_reconciliations LIMIT 1")
    ).first()
    if occupied is not None:
        raise RuntimeError("e-book rename reconciliation prevents migration downgrade")
    bind.execute(sa.text("DROP TRIGGER ebook_rename_reconciliations_no_delete"))
    bind.execute(sa.text("DROP TRIGGER ebook_rename_reconciliations_no_update"))
    ebook_rename_reconciliations.drop(bind)
