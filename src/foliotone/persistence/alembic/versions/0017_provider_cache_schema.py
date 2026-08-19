"""Persist provider-cache source metadata and slot state.

Revision ID: 0017_provider_cache_schema
Revises: 0016_consolidation_plans
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.w3_schema import provider_cache_entries

revision: str = "0017_provider_cache_schema"
down_revision: str | None = "0016_consolidation_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    provider_cache_entries.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM provider_cache_entries LIMIT 1")).first() is not None:
        raise RuntimeError("provider-cache data prevents migration downgrade")
    op.drop_index(
        "ix_provider_cache_entries_retention_until_source_cache_key",
        table_name="provider_cache_entries",
    )
    op.drop_index("ix_provider_cache_entries_status_expires", table_name="provider_cache_entries")
    op.drop_index("ix_provider_cache_entries_provider_query", table_name="provider_cache_entries")
    op.drop_index("ix_provider_cache_entries_generation", table_name="provider_cache_entries")
    provider_cache_entries.drop(bind)
