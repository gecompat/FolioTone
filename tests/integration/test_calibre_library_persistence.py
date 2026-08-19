from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, inspect, select

from foliotone.core import (
    EntityId,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    CalibreLibraryStoreError,
    SQLiteCalibreLibraryStore,
    SQLiteScanRootWriteLeaseStore,
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
)
from foliotone.persistence import calibre_library_schema as cs
from foliotone.persistence.scan_root_lease import ScanRootWriteOwnerKind
from foliotone.workflows.calibre_reconciliation import (
    CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySnapshot,
    CalibreLibrarySnapshotStatus,
    CalibreReconciliationFinding,
    CalibreReconciliationFindingCode,
    CalibreReconciliationFindingRef,
    CalibreReconciliationFindingRefKind,
    CalibreReconciliationFindingRefRole,
)

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _graph(path: Path):
    migrate(path)
    engine = create_sqlite_engine(path)
    root = ScanRoot(EntityId.new(), "synthetic-calibre", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        root.id,
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
        EntityId.new(),
        lease_token="synthetic-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    snapshot = CalibreLibrarySnapshot(
        EntityId.new(),
        root.id,
        scan.id,
        CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
        "calibredb-library/1",
        "9.13.0",
        "calibre-library-parser/1",
        DIGEST,
        DIGEST,
        DIGEST,
        CalibreLibrarySnapshotStatus.COMPLETED,
        NOW,
        NOW,
    )
    record = CalibreLibraryRecordSnapshot(EntityId.new(), snapshot.id, 1, DIGEST)
    finding = CalibreReconciliationFinding(
        EntityId.new(),
        snapshot.id,
        CalibreReconciliationFindingCode.CALIBRE_RECORD_WITHOUT_FILE,
        DIGEST,
        True,
        NOW,
    )
    ref = CalibreReconciliationFindingRef(
        EntityId.new(),
        finding.id,
        0,
        CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
        record.id,
        CalibreReconciliationFindingRefRole.PRIMARY,
        DIGEST,
    )
    return engine, lease, snapshot, record, finding, ref


def test_calibre_snapshot_graph_is_insert_only_idempotent_and_fenced(tmp_path: Path) -> None:
    engine, lease, snapshot, record, finding, ref = _graph(tmp_path / "calibre.db")
    store = SQLiteCalibreLibraryStore(engine)
    assert (
        store.create_or_get(snapshot, (record,), (), (), (finding,), (ref,), lease=lease, now=NOW)
        == snapshot
    )
    retry_record = CalibreLibraryRecordSnapshot(EntityId.new(), snapshot.id, 1, DIGEST)
    retry_finding = CalibreReconciliationFinding(
        EntityId.new(), snapshot.id, finding.code, DIGEST, True, NOW
    )
    retry_ref = CalibreReconciliationFindingRef(
        EntityId.new(),
        retry_finding.id,
        0,
        ref.ref_kind,
        retry_record.id,
        ref.role,
        DIGEST,
    )
    assert (
        store.create_or_get(
            snapshot,
            (retry_record,),
            (),
            (),
            (retry_finding,),
            (retry_ref,),
            lease=lease,
            now=NOW,
        )
        == snapshot
    )
    assert (
        store.create_or_get(snapshot, (record,), (), (), (finding,), (ref,), lease=lease, now=NOW)
        == snapshot
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(cs.calibre_library_records)
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                select(func.count()).select_from(cs.calibre_reconciliation_finding_refs)
            ).scalar_one()
            == 1
        )


def test_snapshot_requires_latest_completed_scan_and_exact_observation_locator(
    tmp_path: Path,
) -> None:
    engine, lease, snapshot, record, finding, ref = _graph(tmp_path / "lineage.db")
    file_record = FileRecord(
        EntityId.new(),
        snapshot.scan_root_id,
        "Author/Book.epub",
        10,
        NOW,
        MediaType.EBOOK,
        PresenceState.PRESENT,
        NOW,
        NOW,
    )
    observation = FileObservation(
        EntityId.new(),
        file_record.id,
        snapshot.source_scan_run_id,
        file_record.relative_path,
        file_record.size_bytes,
        NOW,
        NOW,
    )
    repository(engine, FileRecord).save(file_record)
    repository(engine, FileObservation).save(observation)
    wrong_locator = CalibreLibraryFormatSnapshot(
        EntityId.new(), record.id, "EPUB", "Elsewhere/Book.epub", 10, observation.id
    )
    store = SQLiteCalibreLibraryStore(engine)
    with pytest.raises(CalibreLibraryStoreError, match="outside the source scan"):
        store.create_or_get(
            snapshot,
            (record,),
            (wrong_locator,),
            (),
            (finding,),
            (ref,),
            lease=lease,
            now=NOW,
        )

    newer = ScanRun(
        EntityId.new(),
        snapshot.scan_root_id,
        NOW + timedelta(minutes=1),
        ScanRunStatus.COMPLETED,
        completed_at=NOW + timedelta(minutes=1),
    )
    repository(engine, ScanRun).save(newer)
    with pytest.raises(CalibreLibraryStoreError, match="latest completed"):
        store.create_or_get(
            snapshot, (record,), (), (), (finding,), (ref,), lease=lease, now=NOW
        )


def test_invalid_ref_or_lease_loss_rolls_back_entire_graph(tmp_path: Path) -> None:
    engine, lease, snapshot, record, finding, ref = _graph(tmp_path / "rollback.db")
    store = SQLiteCalibreLibraryStore(engine)
    bad_ref = CalibreReconciliationFindingRef(
        ref.id, ref.finding_id, 0, ref.ref_kind, EntityId.new(), ref.role, DIGEST
    )
    with pytest.raises(CalibreLibraryStoreError):
        store.create_or_get(
            snapshot, (record,), (), (), (finding,), (bad_ref,), lease=lease, now=NOW
        )
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(cs.calibre_library_snapshots)
            ).scalar_one()
            == 0
        )
    with pytest.raises(CalibreLibraryStoreError):
        store.create_or_get(
            snapshot,
            (record,),
            (),
            (),
            (finding,),
            (ref,),
            lease=lease,
            now=NOW + timedelta(minutes=6),
        )

    incompatible_ref = CalibreReconciliationFindingRef(
        EntityId.new(),
        finding.id,
        0,
        CalibreReconciliationFindingRefKind.FILE_OBSERVATION,
        EntityId.new(),
        CalibreReconciliationFindingRefRole.PRIMARY,
        DIGEST,
    )
    with pytest.raises(CalibreLibraryStoreError, match="incompatible reference kind"):
        store.create_or_get(
            snapshot,
            (record,),
            (),
            (),
            (finding,),
            (incompatible_ref,),
            lease=lease,
            now=NOW,
        )


def test_migration_downgrade_refuses_data_in_any_new_table(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    migrate(database, "0014_relation_candidates")
    legacy = create_sqlite_engine(database)
    assert cs.calibre_library_snapshots.name not in inspect(legacy).get_table_names()
    legacy.dispose()
    engine, lease, snapshot, record, finding, ref = _graph(database)
    SQLiteCalibreLibraryStore(engine).create_or_get(
        snapshot, (record,), (), (), (finding,), (ref,), lease=lease, now=NOW
    )
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(database), "0014_relation_candidates")
