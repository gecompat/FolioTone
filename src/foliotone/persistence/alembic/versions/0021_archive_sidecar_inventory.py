"""Add immutable archive sidecar inventory snapshots.

Revision ID: 0021_archive_sidecar_inventory
Revises: 0020_archive_collection_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.archive_schema import (
    ARCHIVE_SIDECAR_TABLES,
    file_observations_run_path_index,
)

revision: str = "0021_archive_sidecar_inventory"
down_revision: str | None = "0020_archive_collection_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ARCHIVE_SIDECAR_TABLES:
        table.create(bind)
    file_observations_run_path_index.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in ARCHIVE_SIDECAR_TABLES
    )
    if bind.execute(sa.text(f"{union} LIMIT 1")).first() is not None:
        raise RuntimeError("archive sidecar inventory prevents migration downgrade")
    file_observations_run_path_index.drop(bind)
    for table in reversed(ARCHIVE_SIDECAR_TABLES):
        table.drop(bind)
