from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect

import foliotone.index.scanner as scanner_module
from foliotone.core import (
    EntityId,
    FileChangeState,
    FileRecord,
    Fingerprint,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index import (
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
    discover_files,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository

NOW = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)


def _environment(tmp_path: Path) -> tuple[Engine, SQLiteIndexStore, ScanRoot, Path]:
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("resume-test", MediaType.EBOOK)
    return engine, store, root, media


def test_interrupted_first_scan_resumes_without_rehashing_completed_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, store, root, media = _environment(tmp_path)
    (media / "A.epub").write_bytes(b"alpha")
    (media / "B.epub").write_bytes(b"bravo")
    scanner = IncrementalScanner(
        store,
        batch_size=1,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    binding = ScanRootBinding(media)
    real_discover = discover_files

    def interrupted_discovery(binding: ScanRootBinding):
        iterator = real_discover(binding)
        yield next(iterator)
        raise KeyboardInterrupt

    monkeypatch.setattr(scanner_module, "discover_files", interrupted_discovery)
    with pytest.raises(KeyboardInterrupt):
        scanner.scan(root, binding)

    runs = repository(engine, ScanRun).list_all()
    assert len(runs) == 1
    interrupted = runs[0]
    assert interrupted.status is ScanRunStatus.INTERRUPTED
    assert interrupted.resumed_from_run_id is None
    assert len(repository(engine, FileRecord).list_all()) == 1
    assert len(repository(engine, Fingerprint).list_all()) == 1

    monkeypatch.setattr(scanner_module, "discover_files", real_discover)
    resumed = scanner.scan(root, binding, resume_from=interrupted)

    assert resumed.run.status is ScanRunStatus.COMPLETED
    assert resumed.run.id != interrupted.id
    assert resumed.run.resumed_from_run_id == interrupted.id
    assert resumed.counts == {
        FileChangeState.NEW: 1,
        FileChangeState.UNCHANGED: 1,
    }
    assert len(repository(engine, FileRecord).list_all()) == 2
    assert len(repository(engine, Fingerprint).list_all()) == 2


def test_interrupted_scan_does_not_mark_unseen_known_files_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, store, root, media = _environment(tmp_path)
    (media / "A.epub").write_bytes(b"alpha")
    (media / "B.epub").write_bytes(b"bravo")
    scanner = IncrementalScanner(
        store,
        batch_size=1,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)
    real_discover = discover_files

    def interrupted_discovery(binding: ScanRootBinding):
        iterator = real_discover(binding)
        yield next(iterator)
        raise KeyboardInterrupt

    monkeypatch.setattr(scanner_module, "discover_files", interrupted_discovery)
    with pytest.raises(KeyboardInterrupt):
        scanner.scan(root, binding)

    records = repository(engine, FileRecord).list_all()
    assert len(records) == 2
    assert {record.presence_state for record in records} == {PresenceState.PRESENT}


def test_only_persisted_interrupted_run_of_same_root_is_resumable(tmp_path: Path) -> None:
    engine, store, root, _media = _environment(tmp_path)
    other_root = store.get_or_create_root("other", MediaType.EBOOK)
    interrupted = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.INTERRUPTED,
    )
    completed = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRun).save(interrupted)
    repository(engine, ScanRun).save(completed)

    assert store.get_resumable_run(root, interrupted.id) == interrupted
    with pytest.raises(ValueError, match="different ScanRoot"):
        store.get_resumable_run(other_root, interrupted.id)
    with pytest.raises(ValueError, match="only an INTERRUPTED"):
        store.get_resumable_run(root, completed.id)
    with pytest.raises(ValueError, match="does not exist"):
        store.get_resumable_run(root, EntityId.new())


def test_resume_migration_adds_lineage_column_and_index(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("scan_runs")}
    indexes = {index["name"] for index in inspector.get_indexes("scan_runs")}

    assert "resumed_from_run_id" in columns
    assert "ix_scan_runs_resumed_from_run_id" in indexes
