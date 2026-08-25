"""Focused migration and store coverage for ADR-0055."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from foliotone.archive.sidecars import ArchiveSidecarKind
from foliotone.core import EntityId
from foliotone.persistence import (
    alembic_config,
    archive_schema,
    create_sqlite_engine,
    migrate,
    schema,
)
from foliotone.persistence.archive import (
    ARCHIVE_OBSERVATION_PROFILE,
    ArchiveEvidenceStoreError,
    SQLiteArchiveEvidenceStore,
    _content_fingerprint_from_rows,
    _content_hash_for_graph,
    _insert_graph,
    _PersistedArchiveEvidenceGraph,
    _row_tuple,
    _volume_fingerprint_from_rows,
)
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("10000000-0000-0000-0000-000000000001")
RUN_ID = EntityId.parse("10000000-0000-0000-0000-000000000002")
OWNER_ID = EntityId.parse("10000000-0000-0000-0000-000000000003")


def test_migration_0021_adds_exact_sidecar_schema_and_safe_empty_downgrade(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sidecar-upgrade.db"
    migrate(database, "0020_archive_collection_runs")
    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        plan = " ".join(
            str(row[-1])
            for row in connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM file_observations "
                    "WHERE scan_run_id=:run AND relative_path>=:low "
                    "AND relative_path<:high ORDER BY relative_path LIMIT 33"
                ),
                {"run": str(RUN_ID), "low": "books/", "high": "books/\U0010ffff"},
            )
        )
    assert revision == "0034_ebook_rename_operator_jobs"
    assert {table.name for table in archive_schema.ARCHIVE_SIDECAR_TABLES} <= set(
        inspector.get_table_names()
    )
    assert "ix_file_observations_run_path" in plan
    engine.dispose()

    command.downgrade(alembic_config(database), "0020_archive_collection_runs")
    downgraded = create_sqlite_engine(database)
    assert not (
        {table.name for table in archive_schema.ARCHIVE_SIDECAR_TABLES}
        & set(inspect(downgraded).get_table_names())
    )
    downgraded.dispose()


def test_sidecar_inventory_derives_complete_direct_set_and_exact_retry(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_scan(engine)
    archive_id = EntityId.parse("10000000-0000-0000-0000-000000000010")
    archive_file = _seed_file(engine, 20, "books/archive.zip")
    expected_sidecars = {
        ArchiveSidecarKind.NFO: _seed_file(engine, 21, "books/readme.nfo"),
        ArchiveSidecarKind.TEXT: _seed_file(engine, 22, "books/notes.txt"),
        ArchiveSidecarKind.DIZ: _seed_file(engine, 23, "books/release.diz"),
        ArchiveSidecarKind.INFO: _seed_file(engine, 24, "books/details.info"),
        ArchiveSidecarKind.URL: _seed_file(engine, 25, "books/source.url"),
        ArchiveSidecarKind.HTML: _seed_file(engine, 26, "books/index.html"),
        ArchiveSidecarKind.SFV: _seed_file(engine, 27, "books/checks.sfv"),
        ArchiveSidecarKind.README: _seed_file(engine, 28, "books/README"),
        ArchiveSidecarKind.PASSWORD: _seed_file(engine, 29, "books/PASSWORD"),
    }
    _seed_file(engine, 40, "books/nested/password.txt")
    _seed_file(engine, 41, "other/info.txt")
    _seed_archive_graph(engine, archive_id, archive_file)

    empty_archive_id = EntityId.parse("10000000-0000-0000-0000-000000000030")
    empty_archive_file = _seed_file(engine, 31, "empty/archive.zip")
    _seed_archive_graph(engine, empty_archive_id, empty_archive_file)

    bounded_archive_id = EntityId.parse("30000000-0000-0000-0000-000000000090")
    bounded_archive_file = _seed_file(engine, 90, "bounded/archive.zip")
    _seed_archive_graph(engine, bounded_archive_id, bounded_archive_file)
    for suffix in range(100, 133):
        _seed_file(engine, suffix, f"bounded/sidecar-{suffix}.nfo")

    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN,
        OWNER_ID,
        lease_token="synthetic-sidecar-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    store = SQLiteArchiveEvidenceStore(engine)
    first = store.create_or_get_sidecar_inventory(archive_id, lease, NOW + timedelta(seconds=1))
    assert [(item.sidecar_kind, item.sidecar_file_observation_id) for item in first.items] == [
        (kind, expected_sidecars[kind])
        for kind in sorted(expected_sidecars, key=lambda item: item.value)
    ]
    assert (
        store.create_or_get_sidecar_inventory(archive_id, lease, NOW + timedelta(seconds=2))
        == first
    )
    assert store.get_sidecar_inventory(archive_id) == first

    empty = store.create_or_get_sidecar_inventory(
        empty_archive_id, lease, NOW + timedelta(seconds=3)
    )
    assert empty.items == ()
    assert empty.id != first.id
    with pytest.raises(ArchiveEvidenceStoreError, match="exceeds the bound"):
        store.create_or_get_sidecar_inventory(bounded_archive_id, lease, NOW + timedelta(seconds=4))
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM archive_sidecar_inventories")
            ).scalar_one()
            == 2
        )
        assert connection.execute(
            text("SELECT COUNT(*) FROM archive_sidecar_inventory_items")
        ).scalar_one() == len(expected_sidecars)

    SQLiteScanRootWriteLeaseStore(engine).release(lease, released_at=NOW + timedelta(seconds=5))
    with pytest.raises(ArchiveEvidenceStoreError, match="write failed"):
        store.create_or_get_sidecar_inventory(archive_id, lease, NOW + timedelta(seconds=6))
    engine.dispose()


def _seed_scan(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            schema.scan_roots.insert(),
            {"id": str(ROOT_ID), "name": "synthetic-root", "media_type": "EBOOK", "enabled": True},
        )
        connection.execute(
            schema.scan_runs.insert(),
            {
                "id": str(RUN_ID),
                "scan_root_id": str(ROOT_ID),
                "started_at": NOW.isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
            },
        )


def _seed_file(engine: Engine, suffix: int, relative_path: str) -> EntityId:
    file_id = EntityId.parse(f"10000000-0000-0000-0000-{suffix:012d}")
    observation_id = EntityId.parse(f"20000000-0000-0000-0000-{suffix:012d}")
    with engine.begin() as connection:
        connection.execute(
            schema.file_records.insert(),
            {
                "id": str(file_id),
                "scan_root_id": str(ROOT_ID),
                "relative_path": relative_path,
                "size_bytes": 1,
                "modified_at": NOW.isoformat(),
                "media_type": "EBOOK",
                "presence_state": "PRESENT",
                "first_seen_at": NOW.isoformat(),
                "last_seen_at": NOW.isoformat(),
                "missing_since_at": None,
                "consecutive_missing_scans": 0,
            },
        )
        connection.execute(
            schema.file_observations.insert(),
            {
                "id": str(observation_id),
                "file_id": str(file_id),
                "scan_run_id": str(RUN_ID),
                "relative_path": relative_path,
                "size_bytes": 1,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            },
        )
    return observation_id


def _seed_archive_graph(
    engine: Engine, archive_id: EntityId, archive_file_observation_id: EntityId
) -> None:
    source = _row_tuple(
        {
            "archive_observation_id": str(archive_id),
            "source_ordinal": 0,
            "file_observation_id": str(archive_file_observation_id),
            "source_full_sha256": "b" * 64,
            "source_size_bytes": 1,
            "staging_name": "archive",
        }
    )
    parent: dict[str, Any] = {
        "id": str(archive_id),
        "profile": ARCHIVE_OBSERVATION_PROFILE,
        "content_hash": "0" * 64,
        "scan_root_id": str(ROOT_ID),
        "source_scan_run_id": str(RUN_ID),
        "observed_at": NOW.isoformat(),
        "archive_full_sha256": "b" * 64,
        "archive_content_fingerprint": _content_fingerprint_from_rows((dict(source),)),
        "volume_group_fingerprint": _volume_fingerprint_from_rows((dict(source),)),
        "signature_profile": "archive-signature-observer/v2",
        "compatibility_profile": "archive-publication-storage-compatibility/v1",
        "container_class": "GENERIC_ARCHIVE",
        "suffix_kind": "ZIP",
        "publication_kind": "NONE",
        "storage_family": "ZIP",
        "outer_compression_kind": "NONE",
        "recognition_status": "MATCHED",
        "inspected_bytes": 4,
        "structural_confirmation_required": False,
        "provider_profile": "archive-7zip-provider/v1",
        "runner_profile": "archive-linux-container-runner/v1",
        "parser_profile": "archive-7zip-slt-parser/v3",
        "parser_status": None,
        "format_case_kind": None,
        "format_lock_profile": "archive-7zip-format-lock/v1",
        "format_lock_sha256": "4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061",
        "listing_profile": "archive-listing/v1",
        "integrity_profile": "archive-integrity/v1",
        "extraction_profile": "archive-extraction/v1",
        "safety_profile": "archive-safety-policy/v1",
        "secret_version": "NONE",
        "listing_status": "NOT_ATTEMPTED",
        "encryption_status": "UNKNOWN",
        "integrity_status": "NOT_TESTED",
        "extraction_status": "NOT_ATTEMPTED",
        "password_attempt_status": "NOT_ATTEMPTED",
        "extraction_policy_status": "POLICY_REJECTED",
        "member_count": 0,
        "writer_owner_kind": "ARCHIVE_COLLECTION_RUN",
        "writer_owner_run_id": str(OWNER_ID),
        "writer_fence_epoch": 1,
    }
    provisional = object.__new__(_PersistedArchiveEvidenceGraph)
    object.__setattr__(provisional, "parent", _row_tuple(parent))
    object.__setattr__(provisional, "sources", (source,))
    object.__setattr__(provisional, "executions", ())
    object.__setattr__(provisional, "members", ())
    object.__setattr__(provisional, "wrapper", None)
    parent["content_hash"] = _content_hash_for_graph(provisional)
    graph = _PersistedArchiveEvidenceGraph(_row_tuple(parent), (source,), (), (), None)
    with engine.begin() as connection:
        _insert_graph(connection, graph)
