from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError, OperationalError

from foliotone.core import EntityId
from foliotone.fixity import (
    EbookFixityBaselineBuildStatus,
    EbookFixityBaselineEntry,
    expected_fixity_baseline_confirmation,
)
from foliotone.persistence import (
    EbookFixityBaselineStoreError,
    SQLiteEbookFixityBaselineProjection,
    SQLiteEbookFixityBaselineStore,
    alembic_config,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
)
from foliotone.workflows.fixity_baseline import EbookFixityBaselineBuilder

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
FIXITY_TABLES = {
    "ebook_fixity_baseline_builds",
    "ebook_fixity_baseline_build_events",
    "ebook_fixity_baseline_entries",
    "ebook_fixity_baseline_manifests",
    "ebook_fixity_baseline_activations",
}


def _secure_open_supported() -> bool:
    return (
        int(getattr(os, "O_NOFOLLOW", 0)) != 0
        and int(getattr(os, "O_DIRECTORY", 0)) != 0
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _seed_completed_scan(
    database: Path,
    *,
    relative_locator: str = "book.epub",
    content: bytes = b"book",
    modified_at: datetime = NOW,
) -> tuple[EntityId, EntityId, EntityId, EntityId]:
    root_id = EntityId.new()
    scan_id = EntityId.new()
    file_id = EntityId.new()
    observation_id = EntityId.new()
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id,name,media_type,enabled) VALUES (:id,'books','EBOOK',1)"
            ),
            {"id": str(root_id)},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'COMPLETED',:completed)"
            ),
            {
                "id": str(scan_id),
                "root": str(root_id),
                "started": (NOW - timedelta(minutes=2)).isoformat(),
                "completed": (NOW - timedelta(minutes=1)).isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO file_records "
                "(id,scan_root_id,relative_path,size_bytes,modified_at,media_type,"
                "presence_state,first_seen_at,last_seen_at,missing_since_at,"
                "consecutive_missing_scans) VALUES "
                "(:id,:root,:path,:size,:modified,'EBOOK','PRESENT',:seen,:seen,NULL,0)"
            ),
            {
                "id": str(file_id),
                "root": str(root_id),
                "path": relative_locator,
                "size": len(content),
                "modified": modified_at.isoformat(),
                "seen": NOW.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO file_observations "
                "(id,file_id,scan_run_id,relative_path,size_bytes,modified_at,observed_at) "
                "VALUES (:id,:file,:scan,:path,:size,:modified,:observed)"
            ),
            {
                "id": str(observation_id),
                "file": str(file_id),
                "scan": str(scan_id),
                "path": relative_locator,
                "size": len(content),
                "modified": modified_at.isoformat(),
                "observed": NOW.isoformat(),
            },
        )
    engine.dispose()
    return root_id, scan_id, file_id, observation_id


def test_0035_migration_adds_fixity_tables_owner_and_immutable_triggers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixity-migration.db"
    migrate(database, "0034_ebook_rename_operator_jobs")
    legacy = create_sqlite_engine(database)
    assert FIXITY_TABLES.isdisjoint(inspect(legacy).get_table_names())
    legacy.dispose()

    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    assert FIXITY_TABLES <= set(inspector.get_table_names())
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        lease_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scan_root_write_leases'"
            )
        ).scalar_one()
        triggers = {
            str(value)
            for value in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'ebook_fixity%'"
                )
            ).scalars()
        }
    engine.dispose()

    assert revision == "0037_ebook_fixity_surface_jobs"
    assert "EBOOK_FIXITY_BASELINE" in lease_sql
    assert "ebook_fixity_entries_gapless" in triggers
    assert "ebook_fixity_activation_ready" in triggers
    assert all(f"{table}_no_update" in triggers for table in FIXITY_TABLES)


def test_0035_migration_empty_downgrade_and_occupied_guard(tmp_path: Path) -> None:
    empty_database = tmp_path / "fixity-empty-downgrade.db"
    migrate(empty_database)
    command.downgrade(
        alembic_config(empty_database),
        "0034_ebook_rename_operator_jobs",
    )
    empty_engine = create_sqlite_engine(empty_database)
    empty_inspector = inspect(empty_engine)
    assert FIXITY_TABLES.isdisjoint(empty_inspector.get_table_names())
    with empty_engine.connect() as connection:
        lease_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scan_root_write_leases'"
            )
        ).scalar_one()
    assert "EBOOK_FIXITY_BASELINE" not in lease_sql
    empty_engine.dispose()

    occupied_database = tmp_path / "fixity-occupied-downgrade.db"
    migrate(occupied_database)
    _seed_completed_scan(occupied_database)
    occupied_engine = create_sqlite_engine(occupied_database)
    with occupied_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ebook_fixity_baseline_builds "
                "(manifest_id,profile,serializer,scan_root_id,source_scan_run_id,started_at) "
                "SELECT :manifest,'ebook-fixity-baseline/v1','canonical-json/v1',"
                "scan_root_id,id,:started FROM scan_runs LIMIT 1"
            ),
            {"manifest": str(EntityId.new()), "started": NOW.isoformat()},
        )
    occupied_engine.dispose()
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(
            alembic_config(occupied_database),
            "0034_ebook_rename_operator_jobs",
        )


def test_store_seals_activates_once_and_exposes_path_free_status(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    read_only = create_sqlite_read_only_engine(head_database)
    projection = SQLiteEbookFixityBaselineProjection(read_only)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        projection.enabled_ebook_root_id(),
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    with projection.open_latest(root_id) as source:
        projected = tuple(item for batch in source.iter_batches() for item in batch)
    assert len(projected) == 1
    assert projected[0].observation_id == observation_id
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)
    entry = EbookFixityBaselineEntry(
        ordinal=0,
        file_id=file_id,
        observation_id=observation_id,
        expected_size_bytes=4,
        relative_locator="book.epub",
        expected_sha256=hashlib.sha256(b"book").hexdigest(),
    )
    store.append_entries(
        manifest_id,
        (entry,),
        lease=lease,
        committed_at=NOW + timedelta(seconds=5),
    )
    manifest = store.finalize_manifest(
        manifest_id,
        prepared_at=NOW + timedelta(seconds=10),
        expires_at=NOW + timedelta(minutes=15, seconds=10),
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=11))

    with pytest.raises(ValueError, match="does not match"):
        store.activate(manifest_id, "ACCEPT", activated_at=NOW + timedelta(minutes=1))
    activation = store.activate(
        manifest_id,
        expected_fixity_baseline_confirmation(manifest_id),
        activated_at=NOW + timedelta(minutes=1),
    )
    status = store.read_status(manifest_id)

    assert manifest.item_count == 1
    assert activation.manifest_content_digest == manifest.content_digest
    assert activation.confirmation_digest not in repr(activation)
    assert activation.confirmation_digest in activation.material_payload().values()
    assert status is not None
    assert status.status is EbookFixityBaselineBuildStatus.ACTIVE
    assert "book.epub" not in repr(status)
    assert entry.expected_sha256 not in repr(status)
    with pytest.raises(EbookFixityBaselineStoreError, match="active fixity baseline"):
        second_id = EntityId.new()
        second_lease = store.acquire_lease(
            root_id,
            second_id,
            acquired_at=NOW + timedelta(minutes=2),
            lease_duration=timedelta(minutes=5),
        )
        try:
            store.start_build(
                second_id,
                scan_id,
                started_at=NOW + timedelta(minutes=2),
                lease=second_lease,
            )
        finally:
            store.release(second_lease, released_at=NOW + timedelta(minutes=2))

    with engine.begin() as connection, pytest.raises(DatabaseError):
        connection.execute(
            text("UPDATE ebook_fixity_baseline_manifests SET item_count=2 WHERE manifest_id=:id"),
            {"id": str(manifest_id)},
        )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT lease_token FROM scan_root_write_leases WHERE scan_root_id=:root"),
                {"root": str(root_id)},
            ).scalar_one()
            is None
        )
    read_only.dispose()
    engine.dispose()


def test_projection_is_query_only_and_rejects_newer_interrupted_scan(
    head_database: Path,
) -> None:
    root_id, _scan_id, _file_id, _observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'INTERRUPTED',:completed)"
            ),
            {
                "id": str(EntityId.new()),
                "root": str(root_id),
                "started": NOW.isoformat(),
                "completed": (NOW + timedelta(seconds=1)).isoformat(),
            },
        )
    engine.dispose()
    read_only = create_sqlite_read_only_engine(head_database)
    projection = SQLiteEbookFixityBaselineProjection(read_only)

    with read_only.connect() as connection:
        assert connection.execute(text("PRAGMA query_only")).scalar_one() == 1
        with pytest.raises(OperationalError):
            connection.execute(
                text(
                    "INSERT INTO scan_roots (id,name,media_type,enabled) VALUES ('x','x','EBOOK',1)"
                )
            )
    with pytest.raises(EbookFixityBaselineStoreError, match="newest ScanRun"):
        with projection.open_latest(root_id):
            pass
    read_only.dispose()


def test_failed_partial_build_has_no_manifest_and_rejects_more_entries(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)
    wrong = EbookFixityBaselineEntry(
        ordinal=0,
        file_id=file_id,
        observation_id=observation_id,
        expected_size_bytes=4,
        relative_locator="different.epub",
        expected_sha256=hashlib.sha256(b"book").hexdigest(),
    )
    with pytest.raises(EbookFixityBaselineStoreError, match="not bound"):
        store.append_entries(
            manifest_id,
            (wrong,),
            lease=lease,
            committed_at=NOW + timedelta(seconds=1),
        )
    store.fail_build(
        manifest_id,
        "SOURCE_CHANGED",
        failed_at=NOW + timedelta(seconds=2),
        lease=lease,
    )
    status = store.read_status(manifest_id)

    assert status is not None
    assert status.status is EbookFixityBaselineBuildStatus.FAILED
    assert store.get_manifest(manifest_id) is None
    with pytest.raises(EbookFixityBaselineStoreError):
        store.append_entries(
            manifest_id,
            (
                EbookFixityBaselineEntry(
                    ordinal=0,
                    file_id=file_id,
                    observation_id=observation_id,
                    expected_size_bytes=4,
                    relative_locator="book.epub",
                    expected_sha256=hashlib.sha256(b"book").hexdigest(),
                ),
            ),
            lease=lease,
            committed_at=NOW + timedelta(seconds=3),
        )
    store.release(lease, released_at=NOW + timedelta(seconds=4))
    engine.dispose()


def test_finalize_rejects_incomplete_source_and_schema_bypass(
    head_database: Path,
) -> None:
    root_id, scan_id, _file_id, _observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)

    with pytest.raises(EbookFixityBaselineStoreError, match="complete current source scan"):
        store.finalize_manifest(
            manifest_id,
            prepared_at=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=15, seconds=1),
            lease=lease,
        )
    with engine.begin() as connection, pytest.raises(DatabaseError):
        connection.execute(
            text(
                "INSERT INTO ebook_fixity_baseline_manifests "
                "(manifest_id,prepared_at,expires_at,item_count,total_size_bytes,"
                "entries_digest,content_digest) VALUES "
                "(:manifest,:prepared,:expires,0,0,:digest,:digest)"
            ),
            {
                "manifest": str(manifest_id),
                "prepared": (NOW + timedelta(seconds=1)).isoformat(),
                "expires": (NOW + timedelta(minutes=15, seconds=1)).isoformat(),
                "digest": hashlib.sha256(b"").hexdigest(),
            },
        )
    store.fail_build(
        manifest_id,
        "INCOMPLETE_SOURCE",
        failed_at=NOW + timedelta(seconds=2),
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=3))
    engine.dispose()


def test_schema_rejects_overlong_or_stale_scan_manifest(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)
    store.append_entries(
        manifest_id,
        (
            EbookFixityBaselineEntry(
                ordinal=0,
                file_id=file_id,
                observation_id=observation_id,
                expected_size_bytes=4,
                relative_locator="book.epub",
                expected_sha256=hashlib.sha256(b"book").hexdigest(),
            ),
        ),
        lease=lease,
        committed_at=NOW + timedelta(seconds=1),
    )
    values = {
        "manifest": str(manifest_id),
        "prepared": (NOW + timedelta(seconds=2)).isoformat(),
        "expires": (NOW + timedelta(minutes=16, seconds=2)).isoformat(),
        "digest": hashlib.sha256(b"manifest").hexdigest(),
    }
    statement = text(
        "INSERT INTO ebook_fixity_baseline_manifests "
        "(manifest_id,prepared_at,expires_at,item_count,total_size_bytes,"
        "entries_digest,content_digest) VALUES "
        "(:manifest,:prepared,:expires,1,4,:digest,:digest)"
    )
    with engine.begin() as connection, pytest.raises(DatabaseError):
        connection.execute(statement, values)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'INTERRUPTED',:completed)"
            ),
            {
                "id": str(EntityId.new()),
                "root": str(root_id),
                "started": (NOW + timedelta(seconds=3)).isoformat(),
                "completed": (NOW + timedelta(seconds=4)).isoformat(),
            },
        )
    values["expires"] = (NOW + timedelta(minutes=15, seconds=2)).isoformat()
    with engine.begin() as connection, pytest.raises(DatabaseError):
        connection.execute(statement, values)

    store.fail_build(
        manifest_id,
        "SOURCE_SCAN_STALE",
        failed_at=NOW + timedelta(seconds=5),
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=6))
    engine.dispose()


def test_expired_takeover_marks_partial_build_failed_and_bounds_batches(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    expired_manifest_id = EntityId.new()
    expired = store.acquire_lease(
        root_id,
        expired_manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(seconds=1),
    )
    store.start_build(expired_manifest_id, scan_id, started_at=NOW, lease=expired)

    next_owner_id = EntityId.new()
    recovered = store.acquire_lease(
        root_id,
        next_owner_id,
        acquired_at=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=1),
    )
    expired_status = store.read_status(expired_manifest_id)
    assert expired_status is not None
    assert expired_status.status is EbookFixityBaselineBuildStatus.FAILED
    store.release(recovered, released_at=NOW + timedelta(seconds=3))

    fresh_manifest_id = EntityId.new()
    fresh = store.acquire_lease(
        root_id,
        fresh_manifest_id,
        acquired_at=NOW + timedelta(seconds=4),
        lease_duration=timedelta(minutes=1),
    )
    store.start_build(
        fresh_manifest_id,
        scan_id,
        started_at=NOW + timedelta(seconds=4),
        lease=fresh,
    )
    oversized = tuple(
        EbookFixityBaselineEntry(
            ordinal=ordinal,
            file_id=file_id,
            observation_id=observation_id,
            expected_size_bytes=4,
            relative_locator="book.epub",
            expected_sha256=hashlib.sha256(b"book").hexdigest(),
        )
        for ordinal in range(257)
    )
    with pytest.raises(ValueError, match="bounded maximum"):
        store.append_entries(
            fresh_manifest_id,
            oversized,
            lease=fresh,
            committed_at=NOW + timedelta(seconds=5),
        )
    store.fail_build(
        fresh_manifest_id,
        "BATCH_TOO_LARGE",
        failed_at=NOW + timedelta(seconds=6),
        lease=fresh,
    )
    store.release(fresh, released_at=NOW + timedelta(seconds=7))
    engine.dispose()


def test_activation_rejects_exact_expiry_boundary(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)
    store.append_entries(
        manifest_id,
        (
            EbookFixityBaselineEntry(
                ordinal=0,
                file_id=file_id,
                observation_id=observation_id,
                expected_size_bytes=4,
                relative_locator="book.epub",
                expected_sha256=hashlib.sha256(b"book").hexdigest(),
            ),
        ),
        lease=lease,
        committed_at=NOW + timedelta(seconds=1),
    )
    prepared_at = NOW + timedelta(seconds=2)
    expires_at = prepared_at + timedelta(minutes=15)
    store.finalize_manifest(
        manifest_id,
        prepared_at=prepared_at,
        expires_at=expires_at,
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=3))

    with pytest.raises(EbookFixityBaselineStoreError, match="window expired"):
        store.activate(
            manifest_id,
            expected_fixity_baseline_confirmation(manifest_id),
            activated_at=expires_at,
        )
    status = store.read_status(manifest_id)
    assert status is not None
    assert status.status is EbookFixityBaselineBuildStatus.READY
    engine.dispose()


def test_activation_trigger_uses_numeric_time_window(
    head_database: Path,
) -> None:
    root_id, scan_id, file_id, observation_id = _seed_completed_scan(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    store.start_build(manifest_id, scan_id, started_at=NOW, lease=lease)
    store.append_entries(
        manifest_id,
        (
            EbookFixityBaselineEntry(
                ordinal=0,
                file_id=file_id,
                observation_id=observation_id,
                expected_size_bytes=4,
                relative_locator="book.epub",
                expected_sha256=hashlib.sha256(b"book").hexdigest(),
            ),
        ),
        lease=lease,
        committed_at=NOW + timedelta(seconds=1),
    )
    prepared_at = NOW + timedelta(seconds=2)
    expires_at = prepared_at + timedelta(minutes=15)
    manifest = store.finalize_manifest(
        manifest_id,
        prepared_at=prepared_at,
        expires_at=expires_at,
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=3))
    statement = text(
        "INSERT INTO ebook_fixity_baseline_activations "
        "(activation_id,manifest_id,scan_root_id,profile,activated_at,"
        "manifest_content_digest,confirmation_digest,activation_digest) VALUES "
        "(:activation,:manifest,:root,'ebook-fixity-baseline/v1',:activated,"
        ":manifest_digest,:confirmation_digest,:activation_digest)"
    )
    values = {
        "manifest": str(manifest_id),
        "root": str(root_id),
        "manifest_digest": manifest.content_digest,
        "confirmation_digest": hashlib.sha256(b"confirmation").hexdigest(),
        "activation_digest": hashlib.sha256(b"activation").hexdigest(),
    }
    invalid_times = (
        "not-a-timestamp",
        "2026-08-25T10:10:02-12:00",
        expires_at.isoformat(),
    )
    for activated_at in invalid_times:
        with engine.begin() as connection, pytest.raises(DatabaseError):
            connection.execute(
                statement,
                {
                    **values,
                    "activation": str(EntityId.new()),
                    "activated": activated_at,
                },
            )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM ebook_fixity_baseline_activations")
            ).scalar_one()
            == 0
        )
    engine.dispose()


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_builder_hashes_synthetic_source_with_two_bounded_workers(
    head_database: Path,
    tmp_path: Path,
) -> None:
    source_root = (tmp_path / "media").resolve()
    source_root.mkdir()
    path = source_root / "book.epub"
    path.write_bytes(b"book")
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    root_id, _scan_id, _file_id, _observation_id = _seed_completed_scan(
        head_database,
        content=b"book",
        modified_at=modified_at,
    )
    engine = create_sqlite_engine(head_database)
    read_only = create_sqlite_read_only_engine(head_database)
    builder = EbookFixityBaselineBuilder(
        SQLiteEbookFixityBaselineProjection(read_only, batch_size=1),
        SQLiteEbookFixityBaselineStore(engine),
        clock=lambda: NOW,
        lease_duration=timedelta(minutes=1),
    )

    manifest = builder.build(source_root, worker_count=2)

    assert manifest.scan_root_id == root_id
    assert manifest.item_count == 1
    assert manifest.total_size_bytes == 4
    read_only.dispose()
    engine.dispose()


@pytest.mark.skipif(not _secure_open_supported(), reason="requires Linux dir_fd no-follow")
def test_builder_ready_commit_is_not_masked_by_cleanup_failure(
    head_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = (tmp_path / "media").resolve()
    source_root.mkdir()
    path = source_root / "book.epub"
    path.write_bytes(b"book")
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    _seed_completed_scan(
        head_database,
        content=b"book",
        modified_at=modified_at,
    )
    engine = create_sqlite_engine(head_database)
    read_only = create_sqlite_read_only_engine(head_database)
    store = SQLiteEbookFixityBaselineStore(engine)
    real_read_status = store.read_status

    def unexpected_status_read(_manifest_id: EntityId) -> None:
        raise AssertionError("READY cleanup must not re-read status")

    def failed_release(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected post-commit cleanup failure")

    monkeypatch.setattr(store, "read_status", unexpected_status_read)
    monkeypatch.setattr(store, "release", failed_release)
    builder = EbookFixityBaselineBuilder(
        SQLiteEbookFixityBaselineProjection(read_only, batch_size=1),
        store,
        clock=lambda: NOW,
        lease_duration=timedelta(minutes=1),
    )

    manifest = builder.build(source_root, worker_count=1)

    status = real_read_status(manifest.manifest_id)
    assert status is not None
    assert status.status is EbookFixityBaselineBuildStatus.READY
    read_only.dispose()
    engine.dispose()
