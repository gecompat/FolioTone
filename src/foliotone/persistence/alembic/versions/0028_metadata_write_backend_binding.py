"""Bind each executing metadata-write run to the fixed Linux backend.

Revision ID: 0028_metadata_write_backend
Revises: 0027_metadata_write_operations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.metadata_write_schema import (
    metadata_write_backend_bindings,
)

revision: str = "0028_metadata_write_backend"
down_revision: str | None = "0027_metadata_write_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata_write_backend_bindings.create(bind)
    bind.execute(
        sa.text(
            "CREATE TRIGGER metadata_write_backend_bindings_no_update "
            "BEFORE UPDATE ON metadata_write_backend_bindings "
            "BEGIN SELECT RAISE(ABORT, 'immutable metadata write backend binding'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER metadata_write_backend_bindings_no_delete "
            "BEFORE DELETE ON metadata_write_backend_bindings "
            "BEGIN SELECT RAISE(ABORT, 'immutable metadata write backend binding'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(
        sa.text("SELECT 1 FROM metadata_write_backend_bindings LIMIT 1")
    ).first()
    if occupied is not None:
        raise RuntimeError("metadata write backend binding prevents migration downgrade")
    bind.execute(sa.text("DROP TRIGGER metadata_write_backend_bindings_no_delete"))
    bind.execute(sa.text("DROP TRIGGER metadata_write_backend_bindings_no_update"))
    metadata_write_backend_bindings.drop(bind)
