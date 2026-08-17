from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from pytest import CaptureFixture
from sqlalchemy import Engine, event, insert, select, text

from foliotone.cli.main import main
from foliotone.core import (
    EbookCandidateHashRunStatus,
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
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
    schema,
)

NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)
SYNTHETIC_HISTORY_SCAN_COUNT = 6
SYNTHETIC_HISTORY_RECORDS_PER_SCAN = 250


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


def _seed_scale_dataset(
    tmp_path: Path,
    engine: Engine,
    *,
    root_name: str = "synthetic-scale",
    history_scans: int = SYNTHETIC_HISTORY_SCAN_COUNT,
    history_records_per_scan: int = SYNTHETIC_HISTORY_RECORDS_PER_SCAN,
    duplicate_group_size: int = 4,
    extra_current_uniques: int = 12,
) -> tuple[ScanRoot, ScanRun]:
    media = tmp_path / "scale-media"
    media.mkdir()
    root = ScanRoot(id=EntityId.new(), name=root_name, media_type=MediaType.EBOOK)
    repository(engine, ScanRoot).save(root)
    scan_rows: list[ScanRun] = []
    records: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    quick_rows: list[dict[str, object]] = []
    timestamp = NOW

    def add_observation(
        scan_id: EntityId,
        *, relative_path: str, size_bytes: int, payload: bytes, quick_value: str
    ) -> None:
        file_id = str(EntityId.new())
        observation_id = str(EntityId.new())
        records.append(
            {
                "id": file_id,
                "scan_root_id": str(root.id),
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "modified_at": timestamp.isoformat(),
                "media_type": MediaType.EBOOK.value,
                "presence_state": PresenceState.PRESENT.value,
                "first_seen_at": timestamp.isoformat(),
                "last_seen_at": timestamp.isoformat(),
                "missing_since_at": None,
                "consecutive_missing_scans": 0,
            }
        )
        observations.append(
            {
                "id": observation_id,
                "file_id": file_id,
                "scan_run_id": str(scan_id),
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "modified_at": timestamp.isoformat(),
                "observed_at": timestamp.isoformat(),
            }
        )
        quick_rows.append(
            {
                "id": str(EntityId.new()),
                "target_kind": EntityKind.FILE_OBSERVATION.value,
                "target_id": observation_id,
                "kind": "QUICK_FILE",
                "algorithm": "sha256-head-tail",
                "algorithm_version": "1",
                "value": quick_value,
                "created_at": timestamp.isoformat(),
                "tool_execution_id": None,
            }
        )
        if relative_path.startswith("current/"):
            media_file = media / relative_path
            media_file.parent.mkdir(parents=True, exist_ok=True)
            source_bytes = (payload * ((size_bytes // len(payload)) + 1))[:size_bytes]
            media_file.write_bytes(source_bytes)
            media_timestamp = timestamp.timestamp()
            os.utime(media_file, (media_timestamp, media_timestamp))

    for index in range(history_scans):
        scan = ScanRun(
            id=EntityId.new(),
            scan_root_id=root.id,
            started_at=timestamp - timedelta(days=2) + timedelta(minutes=index),
            completed_at=timestamp - timedelta(days=2) + timedelta(minutes=index + 1),
            status=ScanRunStatus.COMPLETED,
        )
        scan_rows.append(scan)
        for generation in range(history_records_per_scan):
            add_observation(
                scan.id,
                relative_path=f"history/{index:03d}/row-{generation:05d}.epub",
                size_bytes=1_000 + generation,
                payload=b"historical",
                quick_value=f"history-{index:03d}-{generation:05d}",
            )

    latest_scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=timestamp - timedelta(minutes=1),
        completed_at=timestamp,
        status=ScanRunStatus.COMPLETED,
    )
    scan_rows.append(latest_scan)
    for group in range(2):
        for index in range(duplicate_group_size):
            add_observation(
                latest_scan.id,
                relative_path=f"current/duplicate-{group:02d}-{index:03d}.epub",
                size_bytes=10_000 + group,
                payload=f"duplicate-{group}".encode(),
                quick_value=f"duplicate-group-{group:02d}",
            )
    for index in range(extra_current_uniques):
        add_observation(
            latest_scan.id,
            relative_path=f"current/unique-{index:03d}.epub",
            size_bytes=15_000 + index,
            payload=f"unique-{index}".encode(),
            quick_value=f"unique-{index:03d}",
        )
    scan_repository = repository(engine, ScanRun)
    for scan_row in scan_rows:
        scan_repository.save(scan_row)
    with engine.begin() as connection:
        connection.execute(insert(schema.file_records), records)
        connection.execute(insert(schema.file_observations), observations)
        connection.execute(insert(schema.fingerprints), quick_rows)
    return root, latest_scan


def _ordered_candidate_observations(
    root: ScanRoot,
    scan: ScanRun,
    engine: Engine,
    include_hashed: bool = False,
) -> tuple[EntityId, ...]:
    service = DuplicateHashCandidateService(engine)
    current, groups, full_hash_targets = service._candidate_tables(root, scan)
    statement = (
        select(current.c.observation_id)
        .select_from(
            current.join(
                groups, groups.c.quick_value == current.c.quick_value
            ).outerjoin(
                full_hash_targets,
                full_hash_targets.c.observation_id == current.c.observation_id,
            )
        )
        .order_by(current.c.quick_value, current.c.observation_id)
    )
    if not include_hashed:
        statement = statement.where(full_hash_targets.c.observation_id.is_(None))
    with engine.connect() as connection:
        rows = connection.execute(statement).scalars().all()
    return tuple(EntityId.parse(row) for row in rows)


def _snapshot_candidates_plan(
    service: DuplicateHashCandidateService,
    root: ScanRoot,
    scan: ScanRun,
    engine: Engine,
) -> str:
    current, groups, full_hash_targets = service._candidate_tables(root, scan)
    candidate_query = (
        select(current.c.observation_id, current.c.quick_value)
        .select_from(
            current.join(
                groups,
                groups.c.quick_value == current.c.quick_value,
            ).outerjoin(
                full_hash_targets,
                full_hash_targets.c.observation_id == current.c.observation_id,
            )
        )
        .where(full_hash_targets.c.observation_id.is_(None))
    )
    with engine.connect() as connection:
        compile_kwargs = {"literal_binds": True}
        query_plan = candidate_query.compile(
            dialect=connection.dialect,
            compile_kwargs=compile_kwargs,
        )
        plan_rows = connection.execute(
            text(f"EXPLAIN QUERY PLAN {query_plan}")
        ).all()
        return " ".join(str(value) for row in plan_rows for value in row)


def _full_hashed_observations(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(schema.fingerprints.c.target_id).where(
                schema.fingerprints.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                schema.fingerprints.c.kind == "FILE_SHA256",
            )
        ).scalars().all()
    return {str(row) for row in rows}


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
    for observation in observations:
        repository(engine, Fingerprint).save(
            writer.calculate_full(
                observation,
                media / observation.relative_path,
                NOW,
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


def test_candidate_hash_scale_dataset_uses_single_candidate_materialization_and_indexed_plan(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scale.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root, scan = _seed_scale_dataset(tmp_path, engine)

    materializations: list[str] = []

    def observe_statement(
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
            and "CURRENT_QUICK_OBSERVATIONS" in statement.upper()
        ):
            materializations.append(statement)

    event.listen(engine, "before_cursor_execute", observe_statement)
    try:
        summary = DuplicateHashCandidateService(engine).enrich(
            root,
            tmp_path / "scale-media",
            worker_count=2,
            batch_size=4,
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe_statement)
    assert len(materializations) == 1
    assert summary.candidate_groups == 2
    assert summary.candidate_observations == 8
    assert summary.hashed_this_invocation == 8
    assert summary.remaining == 0

    candidate_plan = _snapshot_candidates_plan(
        DuplicateHashCandidateService(engine),
        root,
        scan,
        engine,
    )
    assert "ix_fingerprints_target_profile_id_value" in candidate_plan


def test_candidate_hash_scale_restart_with_max_items_is_deterministic(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scale-restart.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root, scan = _seed_scale_dataset(tmp_path, engine)
    ordered_observations = _ordered_candidate_observations(root, scan, engine)
    assert len(ordered_observations) == 8

    service = DuplicateHashCandidateService(engine)
    first = service.enrich(
        root,
        tmp_path / "scale-media",
        batch_size=4,
        max_items=3,
    )
    assert first.hashed_this_invocation == 3
    assert first.remaining == 5
    assert _full_hashed_observations(engine) == {
        str(ordered_observations[index]) for index in range(3)
    }

    second = DuplicateHashCandidateService(engine).enrich(
        root,
        tmp_path / "scale-media",
        batch_size=4,
        max_items=3,
    )
    assert second.hashed_this_invocation == 3
    assert second.remaining == 2
    assert _full_hashed_observations(engine) == {
        str(ordered_observations[index]) for index in range(6)
    }

    completed = DuplicateHashCandidateService(engine).enrich(
        root,
        tmp_path / "scale-media",
        batch_size=4,
    )
    assert completed.hashed_this_invocation == 2
    assert completed.remaining == 0
    assert _full_hashed_observations(engine) == {
        str(ordered_observations[index]) for index in range(8)
    }
