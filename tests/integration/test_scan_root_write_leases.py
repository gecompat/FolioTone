from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from foliotone.core import (
    EbookCandidateHashRunStatus,
    EntityId,
    EntityKind,
    Fingerprint,
    MediaType,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index.store import ScanLeaseError, SQLiteIndexStore
from foliotone.persistence import (
    EbookCandidateHashLeaseError,
    EbookCollectionStoreError,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteEbookCandidateHashRunStore,
    SQLiteEbookCollectionStore,
    SQLiteScanRootWriteLeaseStore,
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
    scan_root_write_scope,
    schema,
)

NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)


def _root(database: Path, name: str = "synthetic") -> ScanRoot:
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name=name, media_type=MediaType.EBOOK)
    repository(engine, ScanRoot).save(root)
    engine.dispose()
    return root


def test_exactly_one_concurrent_writer_acquires_a_root(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"
    migrate(database)
    root = _root(database)
    barrier = Barrier(2)
    lock = Lock()
    acquired: list[int] = []
    blocked: list[str] = []

    def acquire(index: int) -> None:
        store = SQLiteScanRootWriteLeaseStore(create_sqlite_engine(database))
        barrier.wait()
        try:
            lease = store.acquire(
                root.id,
                ScanRootWriteOwnerKind.SCAN_RUN,
                EntityId.new(),
                lease_token=f"owner-{index}",
                acquired_at=NOW,
                lease_expires_at=NOW + timedelta(minutes=30),
            )
        except ScanRootWriteLeaseError as error:
            with lock:
                blocked.append(str(error))
        else:
            with lock:
                acquired.append(lease.fence_epoch)

    threads = [Thread(target=acquire, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads)

    assert acquired == [1]
    assert blocked == ["an active writer already owns this ScanRoot"]


def test_stale_takeover_increments_epoch_and_fences_old_owner(tmp_path: Path) -> None:
    database = tmp_path / "takeover.db"
    migrate(database)
    root = _root(database)
    engine = create_sqlite_engine(database)
    store = SQLiteScanRootWriteLeaseStore(engine)
    old = store.acquire(
        root.id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="old",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ScanRootWriteLeaseError):
        store.acquire(
            root.id,
            ScanRootWriteOwnerKind.EBOOK_CANDIDATE_HASH_RUN,
            EntityId.new(),
            lease_token="cross-kind",
            acquired_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
        )
    replacement = store.takeover_expired(
        old,
        EntityId.new(),
        lease_token="replacement",
        acquired_at=NOW + timedelta(minutes=2),
        lease_expires_at=NOW + timedelta(minutes=32),
    )

    assert replacement.fence_epoch == old.fence_epoch + 1
    with pytest.raises(ScanRootWriteLeaseError):
        store.heartbeat(
            old,
            heartbeat_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
        )
    with engine.begin() as connection, pytest.raises(ScanRootWriteLeaseError):
        store.fence(connection, old, NOW + timedelta(minutes=2))


def test_fence_and_root_write_rollback_together_after_takeover(tmp_path: Path) -> None:
    database = tmp_path / "atomic.db"
    migrate(database)
    root = _root(database)
    engine = create_sqlite_engine(database)
    store = SQLiteScanRootWriteLeaseStore(engine)
    old = store.acquire(
        root.id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="old",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    store.takeover_expired(
        old,
        EntityId.new(),
        lease_token="replacement",
        acquired_at=NOW + timedelta(minutes=2),
        lease_expires_at=NOW + timedelta(minutes=32),
    )

    with pytest.raises(ScanRootWriteLeaseError):
        with engine.begin() as connection:
            store.fence(connection, old, NOW + timedelta(minutes=2))
            connection.execute(
                schema.scan_roots.update()
                .where(schema.scan_roots.c.id == str(root.id))
                .values(enabled=False)
            )

    persisted = repository(engine, ScanRoot).get(root.id)
    assert persisted is not None
    assert persisted.enabled is True


def test_release_preserves_epoch_for_the_next_owner(tmp_path: Path) -> None:
    database = tmp_path / "release.db"
    migrate(database)
    root = _root(database)
    store = SQLiteScanRootWriteLeaseStore(create_sqlite_engine(database))
    first = store.acquire(
        root.id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="first",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    renewed = store.heartbeat(
        first,
        heartbeat_at=NOW + timedelta(minutes=1),
        lease_expires_at=NOW + timedelta(minutes=31),
    )
    store.release(renewed, released_at=NOW + timedelta(minutes=2))
    second = store.acquire(
        root.id,
        ScanRootWriteOwnerKind.EBOOK_COLLECTION_RUN,
        EntityId.new(),
        lease_token="second",
        acquired_at=NOW + timedelta(minutes=3),
        lease_expires_at=NOW + timedelta(minutes=33),
    )

    assert second.fence_epoch == first.fence_epoch + 1
    assert "first" not in repr(first)
    with store._engine.connect() as connection:
        row = connection.execute(
            select(schema.scan_root_write_leases).where(
                schema.scan_root_write_leases.c.scan_root_id == str(root.id)
            )
        ).mappings().one()
    assert row["owner_kind"] == "EBOOK_COLLECTION_RUN"
    assert row["fence_epoch"] == 2


def test_cross_workflow_ownership_blocks_scan_candidate_and_collection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cross-workflow.db"
    migrate(database)
    root = _root(database)
    engine = create_sqlite_engine(database)
    scan_store = SQLiteIndexStore(engine)
    candidate_store = SQLiteEbookCandidateHashRunStore(engine)
    collection_store = SQLiteEbookCollectionStore(engine)
    completed_scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW - timedelta(minutes=2),
        completed_at=NOW - timedelta(minutes=1),
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRun).save(completed_scan)
    active_scan = scan_store.start_scan(
        root,
        NOW,
        lease_token="scan-owner",
        lease_expires_at=NOW + timedelta(minutes=30),
    )

    with pytest.raises(EbookCandidateHashLeaseError, match="another write workflow"):
        candidate_store.acquire(
            root.id,
            completed_scan.id,
            "ebook-duplicate-hash/v1",
            lease_token="candidate-owner",
            started_at=NOW + timedelta(seconds=1),
            lease_expires_at=NOW + timedelta(minutes=30),
        )
    with pytest.raises(EbookCollectionStoreError, match="another write workflow"):
        collection_store.create_run(
            root.id,
            profile="ebook-collection-analysis/v1",
            analysis_profile="ebook-analysis/v1",
            fresh=False,
            worker_count=1,
            started_at=NOW + timedelta(seconds=1),
            lease_token="collection-owner",
            lease_expires_at=NOW + timedelta(minutes=30),
        )
    assert candidate_store.latest(root.id) is None
    scan_store.finish_scan(
        active_scan,
        ScanRunStatus.INTERRUPTED,
        NOW + timedelta(seconds=2),
    )
    source_after = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW + timedelta(seconds=3),
        completed_at=NOW + timedelta(seconds=4),
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRun).save(source_after)

    candidate = candidate_store.acquire(
        root.id,
        source_after.id,
        "ebook-duplicate-hash/v1",
        lease_token="candidate-owner",
        started_at=NOW + timedelta(seconds=5),
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    with pytest.raises(ScanLeaseError, match="another write workflow"):
        scan_store.start_scan(
            root,
            NOW + timedelta(seconds=6),
            lease_token="second-scan",
            lease_expires_at=NOW + timedelta(minutes=30),
        )
    candidate_store.finish(
        candidate.id,
        "candidate-owner",
        EbookCandidateHashRunStatus.INTERRUPTED,
        finished_at=NOW + timedelta(seconds=7),
    )


def test_scoped_generic_repository_write_is_fenced_after_takeover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-write.db"
    migrate(database)
    root = _root(database)
    engine = create_sqlite_engine(database)
    store = SQLiteScanRootWriteLeaseStore(engine)
    owner_id = EntityId.new()
    old = store.acquire(
        root.id,
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
        owner_id,
        lease_token="same-token",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    replacement = store.takeover_expired(
        old,
        owner_id,
        lease_token="same-token",
        acquired_at=NOW + timedelta(minutes=2),
        lease_expires_at=NOW + timedelta(minutes=32),
    )
    fingerprint = Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=EntityId.new(),
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="1",
        value="must-not-persist",
        created_at=NOW + timedelta(minutes=2),
    )

    with scan_root_write_scope(old, lambda: NOW + timedelta(minutes=2)):
        with pytest.raises(ScanRootWriteLeaseError):
            repository(engine, Fingerprint).save(fingerprint)
    assert repository(engine, Fingerprint).get(fingerprint.id) is None
    assert replacement.fence_epoch == old.fence_epoch + 1


def test_schema_rejects_partial_or_unknown_active_lease_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "lease-constraints.db"
    migrate(database)
    root = _root(database)
    engine = create_sqlite_engine(database)

    invalid_rows = (
        {
            "root": str(root.id),
            "kind": "UNKNOWN",
            "run": str(EntityId.new()),
            "token": "token",
            "epoch": 1,
            "acquired": NOW.isoformat(),
            "heartbeat": NOW.isoformat(),
            "expires": (NOW + timedelta(minutes=1)).isoformat(),
        },
        {
            "root": str(root.id),
            "kind": "SCAN_RUN",
            "run": str(EntityId.new()),
            "token": None,
            "epoch": 1,
            "acquired": NOW.isoformat(),
            "heartbeat": NOW.isoformat(),
            "expires": (NOW + timedelta(minutes=1)).isoformat(),
        },
    )
    statement = text(
        "INSERT INTO scan_root_write_leases "
        "(scan_root_id, owner_kind, owner_run_id, lease_token, fence_epoch, "
        "acquired_at, heartbeat_at, lease_expires_at) VALUES "
        "(:root, :kind, :run, :token, :epoch, :acquired, :heartbeat, :expires)"
    )
    for row in invalid_rows:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(statement, row)


def test_downgrade_refuses_an_active_root_writer(tmp_path: Path) -> None:
    database = tmp_path / "active-downgrade.db"
    migrate(database)
    root = _root(database)
    store = SQLiteScanRootWriteLeaseStore(create_sqlite_engine(database))
    store.acquire(
        root.id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="active",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=30),
    )

    with pytest.raises(RuntimeError, match="active root writers"):
        command.downgrade(alembic_config(database), "0011_candidate_hash_run_leases")

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "0012_scan_root_write_leases"
