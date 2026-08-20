from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import Engine, delete, event

import foliotone.index.hashing as hashing_module
from foliotone.core import (
    FileChangeState,
    FileObservation,
    FileRecord,
    FileRelocationCandidate,
    Fingerprint,
    MediaType,
    PresenceState,
    RelocationCandidateKind,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index import (
    DeletionConfirmationPolicy,
    DiscoveredFile,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    RelocationCandidateDetector,
    ScanProgressPhase,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.index.store import OwnedScanRun
from foliotone.persistence import create_sqlite_engine, repository, schema
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class IndexEnvironment:
    engine: Engine
    root: ScanRoot
    media: Path
    scanner: IncrementalScanner


class CoordinatedFingerprintWriter(FingerprintWriter):
    """Prove two calculations overlap while retaining the real batch write."""

    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self._barrier = Barrier(2)
        self.saved_batch_sizes: list[int] = []

    def calculate(
        self,
        observation: FileObservation,
        physical_path: Path,
        mode: HashMode,
        created_at: datetime,
    ) -> tuple[Fingerprint, ...]:
        self._barrier.wait(timeout=2)
        return super().calculate(observation, physical_path, mode, created_at)

    def save_many(
        self,
        fingerprints: Sequence[Fingerprint],
        *,
        write_lease: OwnedScanRootWriteLease,
        committed_at: datetime,
    ) -> None:
        self.saved_batch_sizes.append(len(fingerprints))
        super().save_many(
            fingerprints,
            write_lease=write_lease,
            committed_at=committed_at,
        )


@pytest.fixture
def index_environment(tmp_path: Path, head_database: Path) -> IndexEnvironment:
    database = head_database
    media = tmp_path / "media"
    media.mkdir()
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("test", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        batch_size=2,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        relocation_detector=RelocationCandidateDetector(engine),
        clock=lambda: NOW,
    )
    return IndexEnvironment(engine, root, media, scanner)


def test_logical_scan_root_is_reused_by_name(index_environment: IndexEnvironment) -> None:
    store = SQLiteIndexStore(index_environment.engine)
    resolved = store.get_or_create_root("test", MediaType.EBOOK)
    assert resolved == index_environment.root
    assert len(repository(index_environment.engine, ScanRoot).list_all()) == 1


def test_hash_workers_overlap_calculation_and_persist_one_batch(
    tmp_path: Path, head_database: Path
) -> None:
    database = head_database
    media = tmp_path / "media"
    media.mkdir()
    (media / "A.epub").write_bytes(b"alpha")
    (media / "B.epub").write_bytes(b"bravo")
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("parallel-hash", MediaType.EBOOK)
    writer = CoordinatedFingerprintWriter(engine)
    scanner = IncrementalScanner(
        store,
        batch_size=2,
        hash_mode=HashMode.QUICK,
        hash_workers=2,
        fingerprint_writer=writer,
        clock=lambda: NOW,
    )

    summary = scanner.scan(
        root,
        ScanRootBinding(media, include_suffixes=frozenset({"epub"})),
    )

    assert summary.counts == {FileChangeState.NEW: 2}
    assert writer.saved_batch_sizes == [2]
    assert len(repository(engine, Fingerprint).list_all()) == 2


def test_scan_reports_cumulative_path_free_progress(
    tmp_path: Path, head_database: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "A.epub").write_bytes(b"alpha")
    (media / "B.epub").write_bytes(b"bravo!")
    engine = create_sqlite_engine(head_database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("progress", MediaType.EBOOK)
    progress = []
    scanner = IncrementalScanner(
        store,
        batch_size=1,
        hash_mode=HashMode.NONE,
        clock=lambda: NOW,
        progress=progress.append,
    )

    scanner.scan(root, ScanRootBinding(media))

    assert [(item.phase, item.processed_files, item.processed_bytes) for item in progress] == [
        (ScanProgressPhase.DISCOVERING, 1, 5),
        (ScanProgressPhase.DISCOVERING, 2, 11),
        (ScanProgressPhase.FINALIZING, 2, 11),
        (ScanProgressPhase.COMPLETED, 2, 11),
    ]


def test_index_store_persists_each_discovery_batch_with_set_writes(
    tmp_path: Path, head_database: Path
) -> None:
    database = head_database
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("set-write", MediaType.EBOOK)
    discovered = tuple(
        DiscoveredFile(
            relative_path=f"book-{index:03}.epub",
            size_bytes=index,
            modified_at=NOW,
            physical_path=tmp_path / f"book-{index:03}.epub",
        )
        for index in range(200)
    )

    def statement_count(run: OwnedScanRun) -> tuple[int, tuple[FileChangeState, ...]]:
        count = 0

        def count_statement(*_args: object) -> None:
            nonlocal count
            count += 1

        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            outcome = store.process_batch(root, run, discovered, NOW)
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)
        return count, tuple(item.change_state for item in outcome.events)

    initial_run = store.start_scan(root, NOW)
    initial_statements, initial_states = statement_count(initial_run)
    assert initial_statements == 6
    assert set(initial_states) == {FileChangeState.NEW}
    store.finish_scan(initial_run, ScanRunStatus.COMPLETED, NOW + timedelta(seconds=1))

    unchanged_run = store.start_scan(root, NOW + timedelta(seconds=2))
    unchanged_statements, unchanged_states = statement_count(unchanged_run)
    assert unchanged_statements == 6
    assert set(unchanged_states) == {FileChangeState.UNCHANGED}


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
    assert len(repository(engine, Fingerprint).list_all()) == 4

    first.write_bytes(b"alpha-modified")
    second.unlink()
    changed = scanner.scan(root, binding)
    assert changed.counts == {
        FileChangeState.MODIFIED: 1,
        FileChangeState.MISSING: 1,
    }
    assert len(repository(engine, Fingerprint).list_all()) == 5

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
    assert len(repository(engine, Fingerprint).list_all()) == 7
    recovered = next(
        record
        for record in repository(engine, FileRecord).list_all()
        if record.relative_path == "B.epub"
    )
    assert recovered.presence_state is PresenceState.PRESENT
    assert recovered.missing_since_at is None
    assert recovered.consecutive_missing_scans == 0


def test_unchanged_scan_reuses_only_complete_latest_hash_evidence(
    index_environment: IndexEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    source = media / "A.epub"
    source.write_bytes(b"alpha")
    binding = ScanRootBinding(media, include_suffixes=frozenset({"epub"}))

    scanner.scan(root, binding)

    def unexpected_hash(_path: Path, _mode: HashMode, **_options: object):
        raise AssertionError("unchanged source must not be re-hashed")

    with monkeypatch.context() as context:
        context.setattr(hashing_module, "calculate_hashes", unexpected_hash)
        reused = scanner.scan(root, binding)

    assert reused.counts == {FileChangeState.UNCHANGED: 1}
    observations = repository(engine, FileObservation).list_all()
    reused_observation = next(
        observation
        for observation in observations
        if observation.scan_run_id == reused.run.id
    )
    assert any(
        fingerprint.target_id == reused_observation.id
        for fingerprint in repository(engine, Fingerprint).list_all()
    )

    with engine.begin() as connection:
        connection.execute(
            delete(schema.fingerprints).where(
                schema.fingerprints.c.target_id == str(reused_observation.id)
            )
        )
    calculated_paths: list[Path] = []
    real_calculate = hashing_module.calculate_hashes

    def record_hash(path: Path, mode: HashMode, **options: object):
        calculated_paths.append(path)
        return real_calculate(path, mode, **options)

    monkeypatch.setattr(hashing_module, "calculate_hashes", record_hash)
    recovered = scanner.scan(root, binding)

    assert recovered.counts == {FileChangeState.UNCHANGED: 1}
    assert calculated_paths == [source]


def test_per_file_hash_io_failure_is_isolated_and_retried_selectively(
    index_environment: IndexEnvironment,
    monkeypatch: pytest.MonkeyPatch,
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
    real_calculate = hashing_module.calculate_hashes

    def fail_one(path: Path, mode: HashMode, **options: object):
        if path == first:
            raise FileNotFoundError(path)
        return real_calculate(path, mode, **options)

    monkeypatch.setattr(hashing_module, "calculate_hashes", fail_one)
    partial = scanner.scan(root, binding)

    assert partial.run.status is ScanRunStatus.COMPLETED
    assert partial.hash_failures == 1
    assert len(repository(engine, Fingerprint).list_all()) == 1

    retried_paths: list[Path] = []

    def record_retry(path: Path, mode: HashMode, **options: object):
        retried_paths.append(path)
        return real_calculate(path, mode, **options)

    monkeypatch.setattr(hashing_module, "calculate_hashes", record_retry)
    recovered = scanner.scan(root, binding)

    assert recovered.counts == {FileChangeState.UNCHANGED: 2}
    assert recovered.hash_failures == 0
    assert retried_paths == [first]
    assert len(repository(engine, Fingerprint).list_all()) == 3


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


def test_deletion_confirmation_requires_missing_count_and_age(
    tmp_path: Path, head_database: Path
) -> None:
    database = head_database
    media = tmp_path / "media"
    media.mkdir()
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


def test_failed_scan_does_not_advance_deletion_confirmation(
    tmp_path: Path, head_database: Path
) -> None:
    database = head_database
    media = tmp_path / "media"
    media.mkdir()
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


def test_rename_candidate_preserves_distinct_file_records(
    index_environment: IndexEnvironment,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    original = media / "A.epub"
    renamed = media / "B.epub"
    original.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)

    original.rename(renamed)
    summary = scanner.scan(root, binding)

    assert summary.counts == {
        FileChangeState.NEW: 1,
        FileChangeState.MISSING: 1,
    }
    assert len(summary.relocation_candidates) == 1
    candidate = summary.relocation_candidates[0]
    assert candidate.kind is RelocationCandidateKind.RENAMED
    assert candidate.source_relative_path == "A.epub"
    assert candidate.target_relative_path == "B.epub"
    assert candidate.fingerprint_kind == "QUICK_FILE"
    assert candidate.source_file_id != candidate.target_file_id
    assert repository(engine, FileRelocationCandidate).list_all() == [candidate]


def test_move_and_move_rename_candidate_shapes(
    index_environment: IndexEnvironment,
) -> None:
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    source_dir = media / "old"
    source_dir.mkdir()
    original = source_dir / "A.epub"
    original.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)

    move_dir = media / "moved"
    move_dir.mkdir()
    moved = move_dir / "A.epub"
    original.rename(moved)
    moved_summary = scanner.scan(root, binding)
    assert moved_summary.relocation_candidates[0].kind is RelocationCandidateKind.MOVED

    final_dir = media / "final"
    final_dir.mkdir()
    moved_and_renamed = final_dir / "B.epub"
    moved.rename(moved_and_renamed)
    final_summary = scanner.scan(root, binding)
    assert len(final_summary.relocation_candidates) == 1
    assert (
        final_summary.relocation_candidates[0].kind
        is RelocationCandidateKind.MOVED_AND_RENAMED
    )


def test_ambiguous_duplicate_fingerprint_does_not_create_relocation_candidate(
    index_environment: IndexEnvironment,
) -> None:
    engine = index_environment.engine
    root = index_environment.root
    media = index_environment.media
    scanner = index_environment.scanner
    first = media / "A.epub"
    second = media / "B.epub"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)

    first.unlink()
    second.unlink()
    (media / "C.epub").write_bytes(b"same")
    summary = scanner.scan(root, binding)

    assert summary.counts == {
        FileChangeState.NEW: 1,
        FileChangeState.MISSING: 2,
    }
    assert summary.relocation_candidates == ()
    assert repository(engine, FileRelocationCandidate).list_all() == []


def test_full_hash_is_preferred_as_relocation_evidence(
    tmp_path: Path, head_database: Path
) -> None:
    database = head_database
    media = tmp_path / "media"
    media.mkdir()
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("test", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.FULL,
        fingerprint_writer=FingerprintWriter(engine),
        relocation_detector=RelocationCandidateDetector(engine),
        clock=lambda: NOW,
    )
    original = media / "A.epub"
    original.write_bytes(b"alpha")
    binding = ScanRootBinding(media)
    scanner.scan(root, binding)

    original.rename(media / "B.epub")
    summary = scanner.scan(root, binding)

    assert len(summary.relocation_candidates) == 1
    assert summary.relocation_candidates[0].fingerprint_kind == "FILE_SHA256"


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
