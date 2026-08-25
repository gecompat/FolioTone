"""Add append-only book-only fixity baseline persistence.

Revision ID: 0035_ebook_fixity_baseline
Revises: 0034_ebook_rename_operator_jobs
"""
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.fixity_schema import EBOOK_FIXITY_BASELINE_TABLES

revision: str = "0035_ebook_fixity_baseline"
down_revision: str | None = "0034_ebook_rename_operator_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OWNER_CHECK = "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND acquired_at IS NULL) OR (lease_token IS NOT NULL AND lease_token <> '' AND owner_kind IN ('SCAN_RUN', 'EBOOK_CANDIDATE_HASH_RUN', 'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS', 'ARCHIVE_COLLECTION_RUN', 'CONSOLIDATION_QUARANTINE_RUN', 'METADATA_WRITE_PREPARATION', 'METADATA_WRITE_RUN', 'EBOOK_RENAME_PREPARATION', 'EBOOK_RENAME_RUN') AND owner_run_id IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL AND acquired_at IS NOT NULL AND fence_epoch >= 1 AND acquired_at <= heartbeat_at AND heartbeat_at < lease_expires_at)"
_NEW_OWNER_CHECK = _OLD_OWNER_CHECK.replace(
    "'EBOOK_RENAME_RUN'",
    "'EBOOK_RENAME_RUN', 'EBOOK_FIXITY_BASELINE'",
)


def upgrade() -> None:
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _NEW_OWNER_CHECK)

    bind = op.get_bind()
    for table in EBOOK_FIXITY_BASELINE_TABLES:
        table.create(bind)
    for table in EBOOK_FIXITY_BASELINE_TABLES:
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_update BEFORE UPDATE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable e-book fixity record'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {table.name}_no_delete BEFORE DELETE ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'immutable e-book fixity record'); END"
            )
        )

    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_build_events_gapless BEFORE INSERT ON "
            "ebook_fixity_baseline_build_events WHEN NEW.ordinal <> COALESCE((SELECT "
            "MAX(ordinal)+1 FROM ebook_fixity_baseline_build_events WHERE "
            "manifest_id=NEW.manifest_id),0) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity build events must be gapless'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_build_events_terminal BEFORE INSERT ON "
            "ebook_fixity_baseline_build_events WHEN NEW.ordinal=1 AND "
            "((NEW.event_kind='MANIFEST_READY' AND NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_baseline_manifests WHERE manifest_id=NEW.manifest_id)) OR "
            "(NEW.event_kind='FAILED' AND EXISTS (SELECT 1 FROM "
            "ebook_fixity_baseline_manifests WHERE manifest_id=NEW.manifest_id))) "
            "BEGIN SELECT RAISE(ABORT, 'invalid e-book fixity terminal event'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_entries_gapless BEFORE INSERT ON "
            "ebook_fixity_baseline_entries WHEN NEW.ordinal <> COALESCE((SELECT "
            "MAX(ordinal)+1 FROM ebook_fixity_baseline_entries WHERE "
            "manifest_id=NEW.manifest_id),0) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity entries must be gapless'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_entries_open_build BEFORE INSERT ON "
            "ebook_fixity_baseline_entries WHEN EXISTS (SELECT 1 FROM "
            "ebook_fixity_baseline_build_events WHERE manifest_id=NEW.manifest_id "
            "AND ordinal=1) OR EXISTS (SELECT 1 FROM ebook_fixity_baseline_manifests "
            "WHERE manifest_id=NEW.manifest_id) BEGIN SELECT RAISE(ABORT, "
            "'e-book fixity build is terminal'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_manifest_complete BEFORE INSERT ON "
            "ebook_fixity_baseline_manifests WHEN EXISTS (SELECT 1 FROM "
            "ebook_fixity_baseline_build_events WHERE manifest_id=NEW.manifest_id "
            "AND ordinal=1) OR NEW.item_count <> (SELECT COUNT(*) FROM "
            "ebook_fixity_baseline_entries WHERE manifest_id=NEW.manifest_id) OR "
            "NEW.total_size_bytes <> COALESCE((SELECT SUM(expected_size_bytes) FROM "
            "ebook_fixity_baseline_entries WHERE manifest_id=NEW.manifest_id),0) "
            "OR NOT EXISTS (SELECT 1 FROM ebook_fixity_baseline_builds AS build JOIN "
            "scan_roots AS root ON root.id=build.scan_root_id JOIN scan_runs AS source "
            "ON source.id=build.source_scan_run_id AND source.scan_root_id=build.scan_root_id "
            "WHERE build.manifest_id=NEW.manifest_id AND root.media_type='EBOOK' AND "
            "root.enabled=1 AND source.status='COMPLETED' AND source.completed_at IS NOT NULL "
            "AND source.id=(SELECT latest.id FROM scan_runs AS latest WHERE "
            "latest.scan_root_id=build.scan_root_id ORDER BY latest.started_at DESC, "
            "latest.id DESC LIMIT 1) AND (SELECT COUNT(*) FROM scan_roots WHERE "
            "media_type='EBOOK' AND enabled=1)=1) "
            "OR NEW.item_count <> (SELECT COUNT(*) FROM file_records AS record JOIN "
            "ebook_fixity_baseline_builds AS build ON build.manifest_id=NEW.manifest_id "
            "WHERE record.scan_root_id=build.scan_root_id AND record.media_type='EBOOK' "
            "AND record.presence_state='PRESENT') OR NEW.item_count <> (SELECT COUNT(*) "
            "FROM file_observations AS observation JOIN file_records AS record ON "
            "record.id=observation.file_id JOIN ebook_fixity_baseline_builds AS build ON "
            "build.manifest_id=NEW.manifest_id WHERE observation.scan_run_id="
            "build.source_scan_run_id AND record.scan_root_id=build.scan_root_id AND "
            "record.media_type='EBOOK' AND record.presence_state='PRESENT' AND "
            "record.relative_path=observation.relative_path AND record.size_bytes="
            "observation.size_bytes AND record.modified_at=observation.modified_at) OR "
            "NEW.item_count <> (SELECT COUNT(*) FROM ebook_fixity_baseline_entries AS "
            "entry JOIN file_observations AS observation ON observation.id="
            "entry.observation_id AND observation.file_id=entry.file_id JOIN file_records "
            "AS record ON record.id=entry.file_id JOIN ebook_fixity_baseline_builds AS "
            "build ON build.manifest_id=NEW.manifest_id WHERE entry.manifest_id="
            "NEW.manifest_id AND observation.scan_run_id=build.source_scan_run_id AND "
            "record.scan_root_id=build.scan_root_id AND record.media_type='EBOOK' AND "
            "record.presence_state='PRESENT' AND entry.relative_locator="
            "observation.relative_path AND entry.relative_locator=record.relative_path "
            "AND entry.expected_size_bytes=observation.size_bytes AND "
            "entry.expected_size_bytes=record.size_bytes AND record.modified_at="
            "observation.modified_at) "
            "BEGIN SELECT RAISE(ABORT, 'incomplete e-book fixity manifest'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_activation_ready BEFORE INSERT ON "
            "ebook_fixity_baseline_activations WHEN NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_baseline_manifests AS manifest JOIN "
            "ebook_fixity_baseline_build_events AS event ON "
            "event.manifest_id=manifest.manifest_id AND event.ordinal=1 AND "
            "event.event_kind='MANIFEST_READY' WHERE manifest.manifest_id=NEW.manifest_id "
            "AND manifest.content_digest=NEW.manifest_content_digest AND "
            "julianday(NEW.activated_at) IS NOT NULL AND "
            "julianday(manifest.prepared_at)<=julianday(NEW.activated_at) AND "
            "julianday(NEW.activated_at)<julianday(manifest.expires_at)) "
            "BEGIN SELECT RAISE(ABORT, 'e-book fixity manifest is not activatable'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    table_union = " UNION ALL ".join(
        f"SELECT 1 FROM {table.name}" for table in EBOOK_FIXITY_BASELINE_TABLES
    )
    occupied = bind.execute(sa.text(f"{table_union} LIMIT 1")).first()
    active_lease = bind.execute(
        sa.text(
            "SELECT 1 FROM scan_root_write_leases WHERE owner_kind='EBOOK_FIXITY_BASELINE' LIMIT 1"
        )
    ).first()
    if occupied is not None or active_lease is not None:
        raise RuntimeError("e-book fixity state prevents migration downgrade")

    for trigger in (
        "ebook_fixity_activation_ready",
        "ebook_fixity_manifest_complete",
        "ebook_fixity_entries_open_build",
        "ebook_fixity_entries_gapless",
        "ebook_fixity_build_events_terminal",
        "ebook_fixity_build_events_gapless",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(EBOOK_FIXITY_BASELINE_TABLES):
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_delete"))
        bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_update"))
        table.drop(bind)

    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _OLD_OWNER_CHECK)
