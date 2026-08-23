"""Add local auth, audit, job, event, and lease persistence.

Revision ID: 0033_local_surface_foundation
Revises: 0032_ebook_rename_reconciliation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.surface_schema import (
    application_job_events,
    application_jobs,
    surface_audit_events,
    surface_auth_attempts,
    surface_bootstrap_tokens,
    surface_grants,
    surface_sessions,
    surface_users,
)

revision: str = "0033_local_surface_foundation"
down_revision: str | None = "0032_ebook_rename_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    surface_users,
    surface_bootstrap_tokens,
    surface_auth_attempts,
    surface_sessions,
    surface_grants,
    surface_audit_events,
    application_jobs,
    application_job_events,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        table.create(bind)
    for table_name in ("surface_audit_events", "application_job_events"):
        for action in ("UPDATE", "DELETE"):
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {table_name}_no_{action.lower()} "
                    f"BEFORE {action} ON {table_name} "
                    f"BEGIN SELECT RAISE(ABORT, 'append-only local surface record'); END"
                )
            )
    bind.execute(
        sa.text(
            "CREATE TRIGGER application_job_events_gapless BEFORE INSERT ON "
            "application_job_events WHEN NEW.sequence_no <> COALESCE((SELECT "
            "MAX(sequence_no) + 1 FROM application_job_events WHERE "
            "job_id=NEW.job_id), 1) BEGIN SELECT RAISE(ABORT, 'application "
            "job events must be gapless'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = " UNION ALL ".join(f"SELECT 1 FROM {table.name}" for table in _TABLES)
    if bind.execute(sa.text(f"{occupied} LIMIT 1")).first() is not None:
        raise RuntimeError("local surface persistence prevents migration downgrade")
    for trigger in (
        "application_job_events_gapless",
        "application_job_events_no_delete",
        "application_job_events_no_update",
        "surface_audit_events_no_delete",
        "surface_audit_events_no_update",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(_TABLES):
        table.drop(bind)
