from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pytest import CaptureFixture
from sqlalchemy import Engine, inspect, text

import foliotone.index.scanner as scanner_module
from foliotone.cli.main import main
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
    ScanLeaseError,
    ScanRootBinding,
    SQLiteIndexStore,
    discover_files,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)


def _environment(tmp_path: Path) -> tuple[Engine, SQLiteIndexStore, ScanRoot, Path]:
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
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
    assert interrupted.lease_token is None
    assert interrupted.lease_expires_at is None
    assert len(repository(engine, FileRecord).list_all()) == 1
    assert len(repository(engine, Fingerprint).list_all()) == 1

    monkeypatch.setattr(scanner_module, "discover_files", real_discover)
    resumed = scanner.scan(root, binding, resume_from=interrupted)

    assert resumed.run.status is ScanRunStatus.COMPLETED
    assert resumed.run.id != interrupted.id
    assert resumed.run.resumed_from_run_id == interrupted.id
    assert resumed.run.lease_token is None
    assert resumed.run.lease_expires_at is None
    assert resumed.counts == {
        FileChangeState.NEW: 1,
        FileChangeState.UNCHANGED: 1,
    }
    assert len(repository(engine, FileRecord).list_all()) == 2
    assert len(repository(engine, Fingerprint).list_all()) == 3


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


def test_expired_scan_lease_is_recovered_once_and_can_be_resumed(tmp_path: Path) -> None:
    _engine, store, root, media = _environment(tmp_path)
    (media / "A.epub").write_bytes(b"alpha")
    running = store.start_scan(
        root,
        NOW,
        lease_token="stale-scan-lease",
        lease_expires_at=NOW + timedelta(minutes=30),
    )

    with pytest.raises(ScanLeaseError, match="active lease"):
        store.recover_latest_stale_run(root, NOW + timedelta(minutes=29))

    recovered = store.recover_latest_stale_run(root, NOW + timedelta(minutes=31))
    assert recovered.id == running.run.id
    assert recovered.status is ScanRunStatus.INTERRUPTED
    assert recovered.completed_at == NOW + timedelta(minutes=31)
    assert recovered.lease_token is None
    assert recovered.lease_expires_at is None

    with pytest.raises(ScanLeaseError, match="ownership|owned"):
        store.finish_scan(
            running,
            ScanRunStatus.COMPLETED,
            NOW + timedelta(minutes=31),
        )

    with pytest.raises(ValueError, match="no RUNNING"):
        store.recover_latest_stale_run(root, NOW + timedelta(minutes=32))

    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.NONE,
        clock=lambda: NOW + timedelta(minutes=33),
    )
    resumed = scanner.scan(root, ScanRootBinding(media), resume_from=recovered)
    assert resumed.run.status is ScanRunStatus.COMPLETED
    assert resumed.run.resumed_from_run_id == recovered.id


def test_legacy_unleased_running_scan_is_explicitly_recoverable(tmp_path: Path) -> None:
    engine, store, root, _media = _environment(tmp_path)
    legacy = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        status=ScanRunStatus.RUNNING,
    )
    repository(engine, ScanRun).save(legacy)

    with pytest.raises(ScanLeaseError, match="not recoverable"):
        store.recover_latest_stale_run(root, NOW + timedelta(hours=1))
    assert repository(engine, ScanRun).get(legacy.id) == legacy


def test_scan_cli_rejects_unfenced_stale_run_and_preserves_source(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    engine, _store, root, media = _environment(tmp_path)
    source = media / "A.epub"
    source.write_bytes(b"alpha")
    stale = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        status=ScanRunStatus.RUNNING,
    )
    repository(engine, ScanRun).save(stale)

    result = main(
        [
            "scan",
            "--name",
            root.name,
            "--path",
            str(media),
            "--media-type",
            "ebook",
            "--database",
            str(tmp_path / "foliotone.db"),
            "--hash",
            "none",
            "--recover-stale-running",
        ]
    )
    output = capsys.readouterr().out

    assert result == 2
    assert "ScanRoot writer is not recoverable" in output
    assert repository(engine, ScanRun).get(stale.id) == stale
    assert source.read_bytes() == b"alpha"


def test_scan_resume_migrations_add_lineage_and_lease_contract(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("scan_runs")}
    indexes = {index["name"] for index in inspector.get_indexes("scan_runs")}

    assert "resumed_from_run_id" in columns
    assert "lease_token" in columns
    assert "lease_expires_at" in columns
    assert "ix_scan_runs_resumed_from_run_id" in indexes
    assert "ix_scan_runs_root_status_lease" in indexes


def test_migration_refuses_a_live_legacy_writer_before_ddl(tmp_path: Path) -> None:
    database = tmp_path / "legacy-running.db"
    migrate(database, "0008_ebook_collection_reports")
    engine = create_sqlite_engine(database)
    root_id = "00000000-0000-0000-0000-000000000101"
    run_id = "00000000-0000-0000-0000-000000000102"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id, name, media_type, enabled) "
                "VALUES (:id, :name, :media_type, :enabled)"
            ),
            {
                "id": root_id,
                "name": "legacy-running",
                "media_type": "EBOOK",
                "enabled": True,
            },
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id, scan_root_id, started_at, status, completed_at, "
                "resumed_from_run_id) VALUES "
                "(:id, :scan_root_id, :started_at, :status, NULL, NULL)"
            ),
            {
                "id": run_id,
                "scan_root_id": root_id,
                "started_at": NOW.isoformat(),
                "status": "RUNNING",
            },
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="quiescent"):
        migrate(database)

    upgraded = create_sqlite_engine(database)
    with upgraded.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        table_exists = connection.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'scan_root_write_leases'"
            )
        ).scalar_one_or_none()
    assert revision == "0011_candidate_hash_run_leases"
    assert table_exists is None
