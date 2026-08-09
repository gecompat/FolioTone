from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

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
    DeletionConfirmationPolicy,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class IndexEnvironment:
    engine: Engine
    root: ScanRoot
    media: Path
    scanner: IncrementalScanner


@pytest.fixture
def index_environment(tmp_path: Path) -> IndexEnvironment:
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("test", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        batch_size=2,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    return IndexEnvironment(engine, root, media, scanner)


def test_logical_scan_root_is_reused_by_name(index_environment: IndexEnvironment) -> None:
    store = SQLiteIndexStore(index_environment.engine)
    resolved = store.get_or_create_root("test", MediaType.EBOOK)
    assert resolved == index_environment.root
    assert len(repository(index_environment.engine, ScanRoot).list_all()) == 1


def test_logical_scan_root_rejects_media_type_change(
    index_environment: IndexEnvironment,
) -> None:
    store = SQLiteIndexStore(index_environment.engine)
    with pytest.raises(ValueError, match="already exists with media type EBOOK"):
        store.get_or_create_root("test", MediaType.MUSIC)


def test_incremental_scan_tracks_new_unchanged_modified_missing_and_reappeared(
    index_environment: IndexEnvironment,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
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
    assert missing_record.missing_since_at == NOW
    assert missing_record.consecutive_missing_scans == 1

    second.write_bytes(b"bravo")
    reappeared = scanner.scan(root, binding)
    assert reappeared.counts == {
        FileChangeState.UNCHANGED: 1,
        FileChangeState.REAPPEARED: 1,
    }
    assert len(repository(engine, Fingerprint).list_all()) == 4
    recovered = next(
        record
        for record in repository(engine, FileRecord).list_all()
        if record.relative_path == "B.epub"
    )
    assert recovered.presence_state is PresenceState.PRESENT
    assert recovered.missing_since_at is None
    assert recovered.consecutive_missing_scans == 0


def test_deletion_confirmation_is_disabled_by_default(
    index_environment: IndexEnvironment,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    file_path = media / "A.epub"
    file_path.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)
    file_path.unlink()

    for expected_count in range(1, 5):
        summary = scanner.scan(root, binding)
        assert summary.counts == {FileChangeState.MISSING: 1}
        record = repository(engine, FileRecord).list_all()[0]
        assert record.presence_state is PresenceState.MISSING
        assert record.consecutive_missing_scans == expected_count


def test_deletion_confirmation_requires_missing_count_and_age(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("test", MediaType.EBOOK)
    current = [NOW]
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        deletion_policy=DeletionConfirmationPolicy(
            min_consecutive_missing_scans=2,
            min_missing_age=timedelta(hours=24),
        ),
        clock=lambda: current[0],
    )
    file_path = media / "A.epub"
    file_path.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)
    file_path.unlink()

    current[0] = NOW + timedelta(hours=1)
    first_missing = scanner.scan(root, binding)
    assert first_missing.counts == {FileChangeState.MISSING: 1}

    current[0] = NOW + timedelta(hours=2)
    count_reached_too_soon = scanner.scan(root, binding)
    assert count_reached_too_soon.counts == {FileChangeState.MISSING: 1}

    current[0] = NOW + timedelta(hours=25)
    confirmed = scanner.scan(root, binding)
    assert confirmed.counts == {FileChangeState.DELETED: 1}
    assert confirmed.observed_files == 0

    record = repository(engine, FileRecord).list_all()[0]
    assert record.presence_state is PresenceState.DELETED
    assert record.missing_since_at == NOW + timedelta(hours=1)
    assert record.consecutive_missing_scans == 3

    current[0] = NOW + timedelta(hours=26)
    still_absent = scanner.scan(root, binding)
    assert still_absent.counts == {}

    file_path.write_bytes(b"alpha")
    current[0] = NOW + timedelta(hours=27)
    reappeared = scanner.scan(root, binding)
    assert reappeared.counts == {FileChangeState.REAPPEARED: 1}
    record = repository(engine, FileRecord).list_all()[0]
    assert record.presence_state is PresenceState.PRESENT
    assert record.missing_since_at is None
    assert record.consecutive_missing_scans == 0


def test_failed_scan_does_not_advance_deletion_confirmation(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    media = tmp_path / "media"
    media.mkdir()
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("test", MediaType.EBOOK)
    current = [NOW]
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        deletion_policy=DeletionConfirmationPolicy(
            min_consecutive_missing_scans=3,
            min_missing_age=timedelta(minutes=1),
        ),
        clock=lambda: current[0],
    )
    file_path = media / "A.epub"
    file_path.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)
    file_path.unlink()

    current[0] = NOW + timedelta(hours=1)
    assert scanner.scan(root, binding).counts == {FileChangeState.MISSING: 1}

    current[0] = NOW + timedelta(hours=2)
    with pytest.raises(FileNotFoundError):
        scanner.scan(root, ScanRootBinding(media.parent / "unavailable"))

    current[0] = NOW + timedelta(hours=3)
    second_valid_absence = scanner.scan(root, binding)
    assert second_valid_absence.counts == {FileChangeState.MISSING: 1}
    record = repository(engine, FileRecord).list_all()[0]
    assert record.consecutive_missing_scans == 2

    current[0] = NOW + timedelta(hours=4)
    third_valid_absence = scanner.scan(root, binding)
    assert third_valid_absence.counts == {FileChangeState.DELETED: 1}


def test_unavailable_root_fails_run_without_marking_known_files_missing(
    index_environment: IndexEnvironment,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    (media / "A.epub").write_bytes(b"alpha")
    scanner.scan(root, ScanRootBinding(media))

    unavailable = media.parent / "not-mounted"
    with pytest.raises(FileNotFoundError):
        scanner.scan(root, ScanRootBinding(unavailable))

    records = repository(engine, FileRecord).list_all()
    assert [record.presence_state for record in records] == [PresenceState.PRESENT]
    runs = repository(engine, ScanRun).list_all()
    assert any(run.status is ScanRunStatus.FAILED for run in runs)
