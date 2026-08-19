from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest
from pytest import CaptureFixture
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from foliotone.cli.main import main
from foliotone.core import (
    EbookCandidateHashPhase,
    EbookCandidateHashRunStatus,
    EntityId,
    EntityKind,
    Fingerprint,
    MediaType,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    EbookCandidateHashLeaseError,
    SQLiteEbookCandidateHashRunStore,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
    w3_schema,
)

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
PROFILE = "ebook-duplicate-hash/v1"


def _completed_scan(database: Path, name: str) -> tuple[ScanRoot, ScanRun]:
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name=name, media_type=MediaType.EBOOK)
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW - timedelta(minutes=2),
        completed_at=NOW - timedelta(minutes=1),
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    engine.dispose()
    return root, scan


def test_candidate_hash_acquire_has_exactly_one_concurrent_owner(
    head_database: Path,
) -> None:
    database = head_database
    root, scan = _completed_scan(database, "concurrent")
    other_root, other_scan = _completed_scan(database, "concurrent-other-root")
    barrier = Barrier(2)
    result_lock = Lock()
    acquired: list[EntityId] = []
    blocked: list[str] = []

    def acquire(token: str) -> None:
        store = SQLiteEbookCandidateHashRunStore(create_sqlite_engine(database))
        barrier.wait()
        try:
            run = store.acquire(
                root.id,
                scan.id,
                PROFILE,
                lease_token=token,
                started_at=NOW,
                lease_expires_at=NOW + timedelta(minutes=30),
            )
        except EbookCandidateHashLeaseError as error:
            with result_lock:
                blocked.append(str(error))
        else:
            with result_lock:
                acquired.append(run.id)

    threads = [Thread(target=acquire, args=(f"owner-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(acquired) == 1
    assert blocked == ["another write workflow owns this ScanRoot"]
    latest = SQLiteEbookCandidateHashRunStore(
        create_sqlite_engine(database)
    ).latest(root.id)
    assert latest is not None
    assert latest.id == acquired[0]
    assert latest.status is EbookCandidateHashRunStatus.RUNNING
    assert latest.phase is EbookCandidateHashPhase.SELECTING
    assert latest.candidate_observations is None
    other = SQLiteEbookCandidateHashRunStore(
        create_sqlite_engine(database)
    ).acquire(
        other_root.id,
        other_scan.id,
        PROFILE,
        lease_token="other-root-owner",
        started_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    assert other.scan_root_id == other_root.id


def test_candidate_hash_stale_takeover_fences_old_owner_writes(
    head_database: Path,
) -> None:
    database = head_database
    root, scan = _completed_scan(database, "stale")
    engine = create_sqlite_engine(database)
    store = SQLiteEbookCandidateHashRunStore(engine)
    old = store.acquire(
        root.id,
        scan.id,
        PROFILE,
        lease_token="old-owner",
        started_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    replacement = store.acquire(
        root.id,
        scan.id,
        PROFILE,
        lease_token="replacement-owner",
        started_at=NOW + timedelta(minutes=2),
        lease_expires_at=NOW + timedelta(minutes=32),
    )
    fingerprint = Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=EntityId.new(),
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="1",
        value="fenced-value",
        created_at=NOW + timedelta(minutes=2),
    )

    with pytest.raises(EbookCandidateHashLeaseError):
        store.heartbeat(
            old.id,
            "old-owner",
            heartbeat_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
        )
    with pytest.raises(EbookCandidateHashLeaseError):
        store.commit_batch(
            old.id,
            "old-owner",
            (fingerprint,),
            committed_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
            processed_delta=1,
            failure_delta=0,
        )

    with engine.connect() as connection:
        old_row = connection.execute(
            select(
                w3_schema.ebook_candidate_hash_runs.c.status,
                w3_schema.ebook_candidate_hash_runs.c.heartbeat_at,
            ).where(
                w3_schema.ebook_candidate_hash_runs.c.id == str(old.id)
            )
        ).one()
        stored = connection.execute(
            select(schema.fingerprints.c.id).where(
                schema.fingerprints.c.value == "fenced-value"
            )
        ).all()
    assert old_row.status == EbookCandidateHashRunStatus.INTERRUPTED.value
    assert old_row.heartbeat_at == (NOW + timedelta(minutes=2)).isoformat()
    assert replacement.status is EbookCandidateHashRunStatus.RUNNING
    assert stored == []


def test_candidate_hash_heartbeat_extends_ownership(head_database: Path) -> None:
    database = head_database
    root, scan = _completed_scan(database, "heartbeat")
    store = SQLiteEbookCandidateHashRunStore(create_sqlite_engine(database))
    run = store.acquire(
        root.id,
        scan.id,
        PROFILE,
        lease_token="owner",
        started_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    store.heartbeat(
        run.id,
        "owner",
        heartbeat_at=NOW + timedelta(seconds=30),
        lease_expires_at=NOW + timedelta(minutes=30),
    )

    with pytest.raises(EbookCandidateHashLeaseError):
        store.acquire(
            root.id,
            scan.id,
            PROFILE,
            lease_token="other",
            started_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
        )

    latest = store.latest(root.id)
    assert latest is not None
    assert latest.id == run.id
    assert latest.heartbeat_at == NOW + timedelta(seconds=30)
    assert latest.lease_expires_at == NOW + timedelta(minutes=30)


def test_candidate_hash_batch_progress_and_fingerprints_are_atomic(
    head_database: Path,
) -> None:
    database = head_database
    root, scan = _completed_scan(database, "atomic")
    engine = create_sqlite_engine(database)
    store = SQLiteEbookCandidateHashRunStore(engine)
    run = store.acquire(
        root.id,
        scan.id,
        PROFILE,
        lease_token="owner",
        started_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    store.record_selection(
        run.id,
        "owner",
        heartbeat_at=NOW + timedelta(seconds=1),
        lease_expires_at=NOW + timedelta(minutes=30),
        candidate_groups=1,
        candidate_observations=1,
        already_hashed=0,
        remaining_count=1,
    )
    invalid = Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=EntityId.new(),
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="1",
        value="must-rollback",
        created_at=NOW + timedelta(seconds=2),
        tool_execution_id=EntityId.new(),
    )

    with pytest.raises(IntegrityError):
        store.commit_batch(
            run.id,
            "owner",
            (invalid,),
            committed_at=NOW + timedelta(seconds=2),
            lease_expires_at=NOW + timedelta(minutes=30),
            processed_delta=1,
            failure_delta=0,
        )

    latest = store.latest(root.id)
    assert latest is not None
    assert latest.processed_count == 0
    assert latest.hashed_count == 0
    assert latest.failure_count == 0
    assert latest.remaining_count == 1
    with engine.connect() as connection:
        assert connection.execute(
            select(schema.fingerprints.c.id).where(
                schema.fingerprints.c.value == "must-rollback"
            )
        ).all() == []


def test_candidate_hash_status_is_read_only_on_an_older_schema(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database = tmp_path / "older-status.db"
    migrate(database, "0010_candidate_hash_lookup_index")
    _completed_scan(database, "older-status")

    assert main(
        [
            "ebook-hash-status",
            "--scan-root",
            "older-status",
            "--database",
            str(database),
        ]
    ) == 2
    output = capsys.readouterr().out
    assert "database schema is unavailable" in output
    assert str(tmp_path) not in output

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "0010_candidate_hash_lookup_index"


def test_candidate_hash_json_status_returns_path_free_schema_error(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database = tmp_path / "older-json-status.db"
    migrate(database, "0010_candidate_hash_lookup_index")
    _completed_scan(database, "older-json-status")

    assert main(
        [
            "ebook-hash-status",
            "--scan-root",
            "older-json-status",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "schema_version": 1,
        "command": "ebook-hash-status",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }
    assert str(tmp_path) not in output
