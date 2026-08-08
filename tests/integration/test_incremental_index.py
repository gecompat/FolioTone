from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.core import (
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
    SQLiteIndexStore,
    ScanRootBinding,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)


@pytest.fixture
def index_environment(tmp_path: Path):
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=__import__("foliotone.core", fromlist=["EntityId"]).EntityId.new(), name="test", media_type=MediaType.EBOOK)
    scanner = IncrementalScanner(
        SQLiteIndexStore(engine),
        batch_size=2,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    return engine, root, media, scanner


def test_incremental_scan_tracks_new_unchanged_modified_missing_and_reappeared(
    index_environment,
) -> None:
    engine, root, media, scanner = index_environment
    first = media / "A.epub"
    second = media / "B.epub"
    first.write_bytes(b"alpha")
    second.write_bytes(b"bravo")
    binding = ScanRootBinding(media, include_suffixes=frozenset({"epub"}))

    initial = scanner.scan(root, binding)
    assert initial.run.status is ScanRunStatus.COMPLETED
    assert initial.counts == {FileChangeState.NEW: 2}
    assert len(repository(engine, Fingerprint).list_all()) == 2

    unchanged = scanner.scan(root, binding)
    assert unchanged.counts == {FileChangeState.UNCHANGED: 2}
    assert len(repository(engine, Fingerprint).list_all()) == 2

    first.write_bytes(b"alpha-modified")
    second.unlink()
    changed = scanner.scan(root, binding)
    assert changed.counts == {
        FileChangeState.MODIFIED: 1,
        FileChangeState.MISSING: 1,
    }
    assert len(repository(engine, Fingerprint).list_all()) == 3

    records = repository(engine, FileRecord).list_all()
    missing_record = next(record for record in records if record.relative_path == "B.epub")
    assert missing_record.presence_state is PresenceState.MISSING

    second.write_bytes(b"bravo")
    reappeared = scanner.scan(root, binding)
    assert reappeared.counts == {
        FileChangeState.UNCHANGED: 1,
        FileChangeState.REAPPEARED: 1,
    }
    assert len(repository(engine, Fingerprint).list_all()) == 4


def test_unavailable_root_fails_run_without_marking_known_files_missing(index_environment) -> None:
    engine, root, media, scanner = index_environment
    (media / "A.epub").write_bytes(b"alpha")
    scanner.scan(root, ScanRootBinding(media))

    unavailable = media.parent / "not-mounted"
    with pytest.raises(FileNotFoundError):
        scanner.scan(root, ScanRootBinding(unavailable))

    records = repository(engine, FileRecord).list_all()
    assert [record.presence_state for record in records] == [PresenceState.PRESENT]
    runs = repository(engine, ScanRun).list_all()
    assert any(run.status is ScanRunStatus.FAILED for run in runs)
