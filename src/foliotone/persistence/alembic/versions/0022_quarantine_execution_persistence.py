"""Add immutable ADR-0056 quarantine persistence.

Revision ID: 0022_quarantine_execution_persistence
Revises: 0021_archive_sidecar_inventory
"""
# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.quarantine_schema import QUARANTINE_TABLES

revision: str = "0022_quarantine_execution_persistence"
down_revision: str | None = "0021_archive_sidecar_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OWNER_CHECK = "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND acquired_at IS NULL) OR (lease_token IS NOT NULL AND lease_token <> '' AND owner_kind IN ('SCAN_RUN', 'EBOOK_CANDIDATE_HASH_RUN', 'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS', 'ARCHIVE_COLLECTION_RUN') AND owner_run_id IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND acquired_at IS NOT NULL AND fence_epoch >= 1 AND acquired_at <= heartbeat_at AND heartbeat_at < lease_expires_at)"
_NEW_OWNER_CHECK = _OLD_OWNER_CHECK.replace(
    "'ARCHIVE_COLLECTION_RUN'", "'ARCHIVE_COLLECTION_RUN', 'CONSOLIDATION_QUARANTINE_RUN'"
)


def upgrade() -> None:
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _NEW_OWNER_CHECK)
    bind = op.get_bind()
    for table in QUARANTINE_TABLES:
        table.create(bind)
    for table_name in ("quarantine_authorizations", "quarantine_execution_runs"):
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_update BEFORE UPDATE ON {table_name} BEGIN SELECT RAISE(ABORT, 'immutable quarantine record'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table_name}_no_delete BEFORE DELETE ON {table_name} BEGIN SELECT RAISE(ABORT, 'immutable quarantine record'); END"
            )
        )
    bind.execute(
        sa.text(
            "CREATE TRIGGER quarantine_execution_events_append_only BEFORE INSERT ON quarantine_execution_events WHEN NEW.sequence_no <> COALESCE((SELECT MAX(sequence_no) + 1 FROM quarantine_execution_events WHERE run_id=NEW.run_id), 1) BEGIN SELECT RAISE(ABORT, 'quarantine events must be gapless'); END"
        )
    )
    for action in ("UPDATE", "DELETE"):
        bind.execute(
            sa.text(
                f"CREATE TRIGGER quarantine_execution_events_no_{action.lower()} BEFORE {action} ON quarantine_execution_events BEGIN SELECT RAISE(ABORT, 'immutable quarantine event'); END"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    occupied = bind.execute(
        sa.text(
            "SELECT 1 FROM quarantine_authorizations UNION ALL SELECT 1 FROM quarantine_execution_runs UNION ALL SELECT 1 FROM quarantine_execution_events LIMIT 1"
        )
    ).first()
    if occupied is not None:
        raise RuntimeError("quarantine state prevents migration downgrade")
    for trigger in (
        "quarantine_execution_events_no_delete",
        "quarantine_execution_events_no_update",
        "quarantine_execution_events_append_only",
        "quarantine_execution_runs_no_delete",
        "quarantine_execution_runs_no_update",
        "quarantine_authorizations_no_delete",
        "quarantine_authorizations_no_update",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(QUARANTINE_TABLES):
        table.drop(bind)
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _OLD_OWNER_CHECK)
