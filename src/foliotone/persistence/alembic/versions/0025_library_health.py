"""Add the immutable book-only Library Health projection.

Revision ID: 0025_library_health
Revises: 0024_collection_state_diff_query
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.library_health_schema import LIBRARY_HEALTH_TABLES

revision: str = "0025_library_health"
down_revision: str | None = "0024_collection_state_diff_query"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_NAMES = tuple(table.name for table in LIBRARY_HEALTH_TABLES)


def upgrade() -> None:
    bind = op.get_bind()
    for table in LIBRARY_HEALTH_TABLES:
        table.create(bind)

    for table_name in _TABLE_NAMES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_update "
                f"BEFORE UPDATE ON {table_name} BEGIN "
                "SELECT RAISE(ABORT, 'Library Health rows are immutable'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_delete "
                f"BEFORE DELETE ON {table_name} BEGIN "
                "SELECT RAISE(ABORT, 'Library Health rows are immutable'); END"
            )
        )

    bind.execute(
        sa.text(
            "CREATE TRIGGER library_health_dimensions_bounded_insert "
            "BEFORE INSERT ON library_health_dimensions "
            "WHEN NEW.ordinal >= ("
            "SELECT dimension_count FROM library_health_snapshots WHERE id=NEW.snapshot_id"
            ") BEGIN SELECT RAISE(ABORT, 'Library Health dimension exceeds parent count'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER library_health_findings_bounded_insert "
            "BEFORE INSERT ON library_health_findings "
            "WHEN NEW.ordinal >= ("
            "SELECT finding_count FROM library_health_dimensions "
            "WHERE snapshot_id=NEW.snapshot_id AND ordinal=NEW.dimension_ordinal"
            ") BEGIN SELECT RAISE(ABORT, 'Library Health finding exceeds parent count'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER library_health_samples_bounded_insert "
            "BEFORE INSERT ON library_health_samples "
            "WHEN NEW.ordinal >= ("
            "SELECT sample_count FROM library_health_findings "
            "WHERE snapshot_id=NEW.snapshot_id "
            "AND dimension_ordinal=NEW.dimension_ordinal "
            "AND ordinal=NEW.finding_ordinal"
            ") BEGIN SELECT RAISE(ABORT, 'Library Health sample exceeds parent count'); END"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    occupied = connection.execute(
        sa.text(
            "SELECT 1 FROM library_health_snapshots "
            "UNION ALL SELECT 1 FROM library_health_dimensions "
            "UNION ALL SELECT 1 FROM library_health_findings "
            "UNION ALL SELECT 1 FROM library_health_samples LIMIT 1"
        )
    ).first()
    if occupied is not None:
        raise RuntimeError("Refusing to drop non-empty Library Health tables")

    for trigger_name in (
        "library_health_dimensions_bounded_insert",
        "library_health_findings_bounded_insert",
        "library_health_samples_bounded_insert",
    ):
        connection.execute(sa.text(f"DROP TRIGGER {trigger_name}"))
    for table_name in reversed(_TABLE_NAMES):
        connection.execute(sa.text(f"DROP TRIGGER {table_name}_no_delete"))
        connection.execute(sa.text(f"DROP TRIGGER {table_name}_no_update"))
    for table in reversed(LIBRARY_HEALTH_TABLES):
        table.drop(connection)
