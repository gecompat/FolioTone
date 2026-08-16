from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from pytest import CaptureFixture
from sqlalchemy import Engine, event

from foliotone.cli.main import main
from foliotone.core import (
    EbookCandidateHashRunStatus,
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    MediaType,
    ScanRoot,
)
from foliotone.index import (
    DuplicateHashCandidateError,
    DuplicateHashCandidateService,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import (
    SQLiteEbookCandidateHashRunStore,
    create_sqlite_engine,
    migrate,
    repository,
)

NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)


class _BlockingFingerprintWriter(FingerprintWriter):
    def __init__(self, engine: Engine, hashing_started: Event, release: Event) -> None:
        super().__init__(engine)
        self._hashing_started = hashing_started
        self._release = release

    def calculate_full(
        self,
        observation: FileObservation,
        physical_path: Path,
        created_at: datetime,
    ) -> Fingerprint:
        self._hashing_started.set()
        if not self._release.wait(timeout=5):
            raise AssertionError("candidate-hash test release was not signalled")
        return super().calculate_full(observation, physical_path, created_at)


class _KeeperFailureStore(SQLiteEbookCandidateHashRunStore):
    def __init__(self, engine: Engine, hashing_started: Event, failed: Event) -> None:
        super().__init__(engine)
        self._hashing_started = hashing_started
        self._failed = failed

    def heartbeat(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> None:
        if self._hashing_started.is_set():
            self._failed.set()
            raise RuntimeError("private sentinel must never reach the operator")
        super().heartbeat(
            run_id,
            lease_token,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )


class _SignallingHeartbeatStore(SQLiteEbookCandidateHashRunStore):
    def __init__(self, engine: Engine, hashing_started: Event, renewed: Event) -> None:
        super().__init__(engine)
        self._hashing_started = hashing_started
        self._renewed = renewed
        self.renewed_until: datetime | None = None

    def heartbeat(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> None:
        super().heartbeat(
            run_id,
            lease_token,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )
        if self._hashing_started.is_set():
            self.renewed_until = lease_expires_at
            self._renewed.set()


class _InterruptingFingerprintWriter(FingerprintWriter):
    def calculate_full(
        self,
        observation: FileObservation,
        physical_path: Path,
        created_at: datetime,
    ) -> Fingerprint:
        raise KeyboardInterrupt


def _candidate_case(
    tmp_path: Path,
    name: str,
) -> tuple[Path, Engine, ScanRoot]:
    media = tmp_path / name
    media.mkdir()
    for filename in ("a.epub", "b.epub"):
        (media / filename).write_bytes(b"same candidate bytes")
    database = tmp_path / f"{name}.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root(name, MediaType.EBOOK)
    IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    ).scan(root, ScanRootBinding(media))
    return media, engine, root


def test_candidate_hash_cli_is_selective_path_free_and_restartable(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "private-media"
    media.mkdir()
    sources = {
        media / "a.epub": b"same e-book bytes",
        media / "b.epub": b"same e-book bytes",
        media / "unique.pdf": b"different bytes",
    }
    for path, content in sources.items():
        path.write_bytes(content)
    database = tmp_path / "foliotone.db"

    assert main(
        [
            "scan",
            "--name",
            "candidate-hash-cli",
            "--path",
            str(media),
            "--media-type",
            "ebook",
            "--database",
            str(database),
            "--hash",
            "quick",
            "--suffix",
            "epub",
            "--suffix",
            "pdf",
        ]
    ) == 0
    capsys.readouterr()
    base_args = [
        "ebook-hash-candidates",
        "--root",
        str(media),
        "--scan-root",
        "candidate-hash-cli",
        "--database",
        str(database),
        "--workers",
        "2",
        "--batch-size",
        "1",
    ]

    assert main([*base_args, "--max-items", "1"]) == 3
    first_output = capsys.readouterr().out
    assert "Candidate hashing progress: candidate selection started." in first_output
    assert "Candidate hashing progress: candidate selection completed:" in first_output
    assert "Candidate hashing progress: full hashing:" in first_output
    assert "Quick candidate groups: 1" in first_output
    assert "Quick candidate observations: 2" in first_output
    assert "Full-hashed this invocation: 1" in first_output
    assert "Candidate hash run:" in first_output
    assert "Remaining candidates: 1" in first_output
    assert "Status: INTERRUPTED" in first_output
    assert str(media) not in first_output

    status_args = [
        "ebook-hash-status",
        "--scan-root",
        "candidate-hash-cli",
        "--database",
        str(database),
    ]
    assert main(status_args) == 0
    first_status = capsys.readouterr().out
    assert "Status: INTERRUPTED" in first_status
    assert "Phase: FINALIZING" in first_status
    assert "Processed: 1" in first_status
    assert "Full-hashed: 1" in first_status
    assert "Remaining candidates: 1" in first_status
    assert str(media) not in first_status

    assert main([*status_args, "--output", "json"]) == 0
    first_json_text = capsys.readouterr().out
    first_json = json.loads(first_json_text)
    assert first_json["schema_version"] == 1
    assert first_json["command"] == "ebook-hash-status"
    assert first_json["ok"] is True
    assert first_json["scan_root"] == "candidate-hash-cli"
    assert first_json["run"]["phase"] == "FINALIZING"
    assert first_json["run"]["lease_state"] == "NONE"
    assert first_json["run"]["progress"]["processed"] == 1
    assert first_json["run"]["progress"]["hashed"] == 1
    assert first_json["run"]["progress"]["remaining"] == 1
    assert "lease_token" not in first_json_text
    assert str(media) not in first_json_text

    assert main(base_args) == 0
    resumed_output = capsys.readouterr().out
    assert "Already full-hashed: 1" in resumed_output
    assert "Full-hashed this invocation: 1" in resumed_output
    assert "Remaining candidates: 0" in resumed_output
    assert "Status: COMPLETED" in resumed_output
    assert str(media) not in resumed_output

    assert main(status_args) == 0
    completed_status = capsys.readouterr().out
    assert "Status: COMPLETED" in completed_status
    assert "Processed: 1" in completed_status
    assert "Remaining candidates: 0" in completed_status
    assert str(media) not in completed_status

    engine = create_sqlite_engine(database)
    root = next(
        root
        for root in repository(engine, ScanRoot).list_all()
        if root.name == "candidate-hash-cli"
    )
    latest_run = SQLiteEbookCandidateHashRunStore(engine).latest(root.id)
    assert latest_run is not None
    assert latest_run.status is EbookCandidateHashRunStatus.COMPLETED
    assert latest_run.candidate_groups == 1
    assert latest_run.candidate_observations == 2
    assert latest_run.already_hashed == 1
    assert latest_run.processed_count == 1
    assert latest_run.hashed_count == 1
    assert latest_run.failure_count == 0
    assert latest_run.remaining_count == 0
    observations = repository(engine, FileObservation).list_all()
    duplicate_ids = {
        observation.id
        for observation in observations
        if observation.relative_path in {"a.epub", "b.epub"}
    }
    full_hashes = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]
    assert {fingerprint.target_id for fingerprint in full_hashes} == duplicate_ids
    assert len({fingerprint.value for fingerprint in full_hashes}) == 1
    assert all(path.read_bytes() == content for path, content in sources.items())


def test_candidate_hash_materializes_only_the_current_snapshot_once(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    for name, content in {
        "a.epub": b"same",
        "b.epub": b"same",
        "unique.pdf": b"unique",
    }.items():
        (media / name).write_bytes(content)
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("snapshot-once", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    for _ in range(3):
        scanner.scan(root, ScanRootBinding(media))

    materializations: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if (
            "INSERT INTO" in statement.upper()
            and "_foliotone_duplicate_hash_candidates" in statement
            and "current_quick_observations" in statement
        ):
            materializations.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        summary = DuplicateHashCandidateService(engine).enrich(
            root,
            media,
            batch_size=1,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 2
    assert summary.remaining == 0
    assert len(materializations) == 1
    quick_hashes = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "QUICK_FILE"
    ]
    assert len(quick_hashes) == 9


def test_candidate_hash_counts_multiple_existing_full_hashes(tmp_path: Path) -> None:
    media, engine, root = _candidate_case(tmp_path, "already-full-hashed")
    writer = FingerprintWriter(engine)
    observations = repository(engine, FileObservation).list_all()
    writer.save_many(
        tuple(
            writer.calculate_full(
                observation,
                media / observation.relative_path,
                NOW,
            )
            for observation in observations
        )
    )

    summary = DuplicateHashCandidateService(engine).enrich(root, media)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.already_hashed == 2
    assert summary.hashed_this_invocation == 0
    assert summary.hash_failures == 0
    assert summary.remaining == 0
    latest = SQLiteEbookCandidateHashRunStore(engine).latest(root.id)
    assert latest is not None
    assert latest.status is EbookCandidateHashRunStatus.COMPLETED
    assert latest.remaining_count == 0
    full_hashes = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]
    assert len(full_hashes) == 2


def test_candidate_hash_excludes_inconsistent_current_quick_evidence(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    for name in ("a.epub", "b.epub", "conflicting.epub"):
        (media / name).write_bytes(b"same")
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("conflicting-quick", MediaType.EBOOK)
    IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    ).scan(root, ScanRootBinding(media))
    conflicting = next(
        observation
        for observation in repository(engine, FileObservation).list_all()
        if observation.relative_path == "conflicting.epub"
    )
    repository(engine, Fingerprint).save(
        Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=conflicting.id,
            kind="QUICK_FILE",
            algorithm="sha256-head-tail",
            algorithm_version="1",
            value="0" * 64,
            created_at=NOW,
        )
    )

    summary = DuplicateHashCandidateService(engine).enrich(root, media)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 2
    full_hash_targets = {
        fingerprint.target_id
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    }
    assert conflicting.id not in full_hash_targets


def test_candidate_hash_isolates_a_source_changed_after_scan(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first = media / "a.epub"
    second = media / "b.epub"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("changed-candidate", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    scanner.scan(root, ScanRootBinding(media))
    first.write_bytes(b"changed after scan")

    summary = DuplicateHashCandidateService(
        engine,
        clock=lambda: NOW + timedelta(minutes=1),
    ).enrich(root, media, worker_count=2)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 1
    assert summary.hash_failures == 1
    assert summary.remaining == 1
    (full_hash,) = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]
    observations = repository(engine, FileObservation).list_all()
    second_observation = next(
        observation
        for observation in observations
        if observation.relative_path == "b.epub"
    )
    assert full_hash.target_id == second_observation.id


def test_keeper_failure_during_a_long_hash_is_path_free_and_fences_the_batch(
    tmp_path: Path,
) -> None:
    media, engine, root = _candidate_case(tmp_path, "keeper-failure")
    hashing_started = Event()
    keeper_failed = Event()
    run_store = _KeeperFailureStore(engine, hashing_started, keeper_failed)
    service = DuplicateHashCandidateService(
        engine,
        fingerprint_writer=_BlockingFingerprintWriter(
            engine,
            hashing_started,
            keeper_failed,
        ),
        run_store=run_store,
        lease_duration=timedelta(milliseconds=600),
    )

    with pytest.raises(
        DuplicateHashCandidateError,
        match="candidate-hash lease is unavailable or expired",
    ) as captured:
        service.enrich(root, media, batch_size=1)

    assert keeper_failed.is_set()
    assert "private sentinel" not in str(captured.value)
    latest = run_store.latest(root.id)
    assert latest is not None
    assert latest.status is EbookCandidateHashRunStatus.FAILED
    assert latest.processed_count == 0
    assert latest.hashed_count == 0
    assert latest.lease_token is None
    assert not [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]


def test_keeper_renews_while_one_full_hash_is_blocked(tmp_path: Path) -> None:
    media, engine, root = _candidate_case(tmp_path, "long-hash-heartbeat")
    hashing_started = Event()
    renewed = Event()
    run_store = _SignallingHeartbeatStore(engine, hashing_started, renewed)
    lease_duration = timedelta(milliseconds=600)
    service = DuplicateHashCandidateService(
        engine,
        fingerprint_writer=_BlockingFingerprintWriter(
            engine,
            hashing_started,
            renewed,
        ),
        run_store=run_store,
        lease_duration=lease_duration,
    )

    summary = service.enrich(root, media, batch_size=1)

    assert renewed.is_set()
    assert summary.hashed_this_invocation == 2
    assert summary.remaining == 0
    assert run_store.renewed_until is not None
    latest = run_store.latest(root.id)
    assert latest is not None
    assert run_store.renewed_until > latest.started_at + lease_duration
    assert latest.status is EbookCandidateHashRunStatus.COMPLETED
    assert latest.hashed_count == 2
    assert latest.remaining_count == 0


def test_keyboard_interrupt_releases_the_run_and_rerun_hashes_only_missing(
    tmp_path: Path,
) -> None:
    media, engine, root = _candidate_case(tmp_path, "keyboard-interrupt")
    run_store = SQLiteEbookCandidateHashRunStore(engine)
    interrupted_service = DuplicateHashCandidateService(
        engine,
        fingerprint_writer=_InterruptingFingerprintWriter(engine),
        run_store=run_store,
    )

    with pytest.raises(KeyboardInterrupt):
        interrupted_service.enrich(root, media, batch_size=1)

    interrupted = run_store.latest(root.id)
    assert interrupted is not None
    assert interrupted.status is EbookCandidateHashRunStatus.INTERRUPTED
    assert interrupted.processed_count == 0
    assert interrupted.lease_token is None
    assert not [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]

    summary = DuplicateHashCandidateService(engine).enrich(root, media, batch_size=1)
    assert summary.already_hashed == 0
    assert summary.hashed_this_invocation == 2
    assert summary.remaining == 0
