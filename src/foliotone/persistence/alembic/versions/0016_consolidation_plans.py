"""Persist immutable consolidation quality and plan snapshots.

Revision ID: 0016_consolidation_plans
Revises: 0015_calibre_library_reconciliation
"""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.consolidation_schema import CONSOLIDATION_TABLES

revision: str = "0016_consolidation_plans"
down_revision: str | None = "0015_calibre_library_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in CONSOLIDATION_TABLES:
        table.create(bind)
    op.create_index("ix_consolidation_plans_root_scan", "consolidation_plans", ["scan_root_id", "source_scan_run_id", "created_at", "id"])
    op.create_index("ix_consolidation_quality_observation", "consolidation_quality_evidence", ["observation_id", "source_scan_run_id", "id"])


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(f"SELECT 1 FROM {table.name}" for table in CONSOLIDATION_TABLES)
    if bind.execute(sa.text(f"{union} LIMIT 1")).first() is not None:
        raise RuntimeError("consolidation data prevents migration downgrade")
    op.drop_index("ix_consolidation_quality_observation", table_name="consolidation_quality_evidence")
    op.drop_index("ix_consolidation_plans_root_scan", table_name="consolidation_plans")
    for table in reversed(CONSOLIDATION_TABLES):
        table.drop(bind)
