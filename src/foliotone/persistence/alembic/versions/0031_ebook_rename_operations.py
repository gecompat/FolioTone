"""Add immutable ADR-0066 e-book rename authority and journal state.

Revision ID: 0031_ebook_rename_operations
Revises: 0030_ebook_operation_recipe_plans
"""
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.ebook_rename_schema import EBOOK_RENAME_TABLES

revision: str = "0031_ebook_rename_operations"
down_revision: str | None = "0030_ebook_operation_recipe_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OWNER_CHECK = "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND acquired_at IS NULL) OR (lease_token IS NOT NULL AND lease_token <> '' AND owner_kind IN ('SCAN_RUN', 'EBOOK_CANDIDATE_HASH_RUN', 'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS', 'ARCHIVE_COLLECTION_RUN', 'CONSOLIDATION_QUARANTINE_RUN', 'METADATA_WRITE_PREPARATION', 'METADATA_WRITE_RUN') AND owner_run_id IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND acquired_at IS NOT NULL AND fence_epoch >= 1 AND acquired_at <= heartbeat_at AND heartbeat_at < lease_expires_at)"
_NEW_OWNER_CHECK = _OLD_OWNER_CHECK.replace(
    "'METADATA_WRITE_RUN'",
    "'METADATA_WRITE_RUN', 'EBOOK_RENAME_PREPARATION', 'EBOOK_RENAME_RUN'",
)


def upgrade() -> None:
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _NEW_OWNER_CHECK)
    bind = op.get_bind()
    for table in EBOOK_RENAME_TABLES:
        table.create(bind)
    for table in EBOOK_RENAME_TABLES:
        if table.name == "ebook_rename_events":
            continue
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_update BEFORE UPDATE ON {table.name} BEGIN SELECT RAISE(ABORT, 'immutable e-book rename record'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_delete BEFORE DELETE ON {table.name} BEGIN SELECT RAISE(ABORT, 'immutable e-book rename record'); END"
            )
        )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_rename_events_append_only BEFORE INSERT ON ebook_rename_events WHEN NEW.sequence_no <> COALESCE((SELECT MAX(sequence_no) + 1 FROM ebook_rename_events WHERE run_id=NEW.run_id), 1) BEGIN SELECT RAISE(ABORT, 'e-book rename events must be gapless'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_rename_events_transition BEFORE INSERT ON ebook_rename_events WHEN NEW.sequence_no > 1 AND NOT EXISTS (SELECT 1 FROM ebook_rename_events AS previous WHERE previous.run_id=NEW.run_id AND previous.sequence_no=NEW.sequence_no-1 AND ((previous.status='PREPARED' AND NEW.status IN ('RELOCATED','RECOVERY_RELOCATED','CANCELLED','MANUAL_RECOVERY_REQUIRED')) OR (previous.status='RELOCATED' AND NEW.status IN ('IMMEDIATE_VERIFIED','RECOVERY_RELOCATED','RECOVERY_VERIFIED','MANUAL_RECOVERY_REQUIRED')) OR (previous.status='IMMEDIATE_VERIFIED' AND NEW.status IN ('SCAN_HANDOFF','MANUAL_RECOVERY_REQUIRED')) OR (previous.status='RECOVERY_RELOCATED' AND NEW.status IN ('RECOVERY_VERIFIED','MANUAL_RECOVERY_REQUIRED')) OR (previous.status='RECOVERY_VERIFIED' AND NEW.status IN ('SCAN_HANDOFF','MANUAL_RECOVERY_REQUIRED')) OR (previous.status='SCAN_HANDOFF' AND NEW.status IN ('VERIFIED','RECOVERED','MANUAL_RECOVERY_REQUIRED')))) BEGIN SELECT RAISE(ABORT, 'invalid e-book rename event transition'); END"
        )
    )
    for action in ("UPDATE", "DELETE"):
        bind.execute(
            sa.text(
                f"CREATE TRIGGER ebook_rename_events_no_{action.lower()} BEFORE {action} ON ebook_rename_events BEGIN SELECT RAISE(ABORT, 'immutable e-book rename event'); END"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in EBOOK_RENAME_TABLES
    )
    occupied = bind.execute(sa.text(f"{table_union} LIMIT 1")).first()
    active_lease = bind.execute(
        sa.text(
            "SELECT 1 FROM scan_root_write_leases WHERE owner_kind IN ('EBOOK_RENAME_PREPARATION','EBOOK_RENAME_RUN') LIMIT 1"
        )
    ).first()
    if occupied is not None or active_lease is not None:
        raise RuntimeError("e-book rename state prevents migration downgrade")
    for trigger in (
        "ebook_rename_events_no_delete",
        "ebook_rename_events_no_update",
        "ebook_rename_events_transition",
        "ebook_rename_events_append_only",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(EBOOK_RENAME_TABLES):
        if table.name != "ebook_rename_events":
            bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_delete"))
            bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_update"))
        table.drop(bind)
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _OLD_OWNER_CHECK)
