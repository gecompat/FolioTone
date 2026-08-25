"""Persist immutable operation-specific rename worker job binders.

Revision ID: 0034_ebook_rename_operator_jobs
Revises: 0033_local_surface_foundation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.surface_schema import (
    ebook_rename_operator_job_binders,
    ebook_rename_operator_job_results,
    surface_command_receipts,
)

revision: str = "0034_ebook_rename_operator_jobs"
down_revision: str | None = "0033_local_surface_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    surface_command_receipts,
    ebook_rename_operator_job_binders,
    ebook_rename_operator_job_results,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        table.create(bind)
    for table in _TABLES[1:]:
        for action in ("UPDATE", "DELETE"):
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {table.name}_no_{action.lower()} "
                    f"BEFORE {action} ON {table.name} "
                    f"BEGIN SELECT RAISE(ABORT, 'immutable e-book rename operator job'); END"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = " UNION ALL ".join(f"SELECT 1 FROM {table.name}" for table in _TABLES)
    if bind.execute(sa.text(f"{occupied} LIMIT 1")).first() is not None:
        raise RuntimeError("e-book rename operator jobs prevent migration downgrade")
    for table in reversed(_TABLES[1:]):
        for action in ("DELETE", "UPDATE"):
            bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_{action.lower()}"))
        table.drop(bind)
    surface_command_receipts.drop(bind)
