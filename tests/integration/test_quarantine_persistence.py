"""Focused immutable persistence coverage for the S-W10-02 boundary."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from foliotone.core import EntityId
from foliotone.persistence import create_sqlite_engine, migrate, schema
from foliotone.persistence.quarantine import (
    QuarantineExecutionEvent,
    QuarantineExecutionRun,
    SQLiteQuarantineStore,
)
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import QuarantineAuthorizationSnapshot, QuarantineRunStatus
from foliotone.quarantine.contracts import _authorization_content_hash, _authorization_id
from foliotone.quarantine.executor import (
    InterimQuarantineError,
    InterimQuarantinePaths,
    execute_interim_quarantine,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
ROOT = EntityId.parse("10000000-0000-0000-0000-000000000001")
SCAN = EntityId.parse("10000000-0000-0000-0000-000000000002")
PLAN = EntityId.parse("10000000-0000-0000-0000-000000000003")
KEEPER = EntityId.parse("10000000-0000-0000-0000-000000000004")
CANDIDATE = EntityId.parse("10000000-0000-0000-0000-000000000005")
KEEPER_OBSERVATION = EntityId.parse("10000000-0000-0000-0000-000000000006")
CANDIDATE_OBSERVATION = EntityId.parse("10000000-0000-0000-0000-000000000007")
CAPABILITY = EntityId.parse("10000000-0000-0000-0000-000000000008")
RUN = EntityId.parse("10000000-0000-0000-0000-000000000009")
PLAN_HASH = "a" * 64
KEEPER_HASH = "b" * 64
CANDIDATE_HASH = "c" * 64
REVIEW_HASH = "d" * 64


def test_migration_0022_persists_only_immutable_gapless_quarantine_events(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quarantine.db"
    migrate(database, "0021_archive_sidecar_inventory")
    migrate(database)
    engine = create_sqlite_engine(database)
    _seed(engine)
    authorization = _authorization()
    store = SQLiteQuarantineStore(engine)
    assert store.create_or_get_authorization(authorization) == authorization
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        ROOT,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        RUN,
        lease_token="synthetic-quarantine-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    run = QuarantineExecutionRun(
        RUN,
        authorization.id,
        PLAN,
        ROOT,
        KEEPER,
        CANDIDATE,
        "e" * 64,
        NOW,
    )
    assert store.create_prepared_run(run, lease, NOW) == run
    for sequence, status in enumerate(
        (QuarantineRunStatus.MOVED, QuarantineRunStatus.VERIFIED, QuarantineRunStatus.COMPLETED),
        start=2,
    ):
        store.append_event(
            QuarantineExecutionEvent(RUN, sequence, status, NOW, lease.fence_epoch),
            lease,
        )
    assert [event.status for event in store.events_for_run(RUN)] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
        QuarantineRunStatus.COMPLETED,
    ]
    with engine.begin() as connection:
        with pytest.raises(Exception, match="immutable quarantine event"):
            connection.execute(text("DELETE FROM quarantine_execution_events"))
        with pytest.raises(Exception, match="gapless"):
            connection.execute(
                text(
                    "INSERT INTO quarantine_execution_events "
                    "(run_id, sequence_no, status, occurred_at) "
                    "VALUES (:run, 99, 'MANUAL_REVIEW', :at)"
                ),
                {"run": str(RUN), "at": NOW.isoformat()},
            )
    engine.dispose()


def test_interim_executor_renames_one_synthetic_candidate_and_persists_events(
    tmp_path: Path,
) -> None:
    engine = _head_engine_from_migration(tmp_path)
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    candidate_path = source_root / "candidate.epub"
    candidate_bytes = b"synthetic duplicate only"
    candidate_path.write_bytes(candidate_bytes)
    authorization = _authorization(hashlib.sha256(candidate_bytes).hexdigest())
    store = SQLiteQuarantineStore(engine)
    store.create_or_get_authorization(authorization)
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        ROOT,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        RUN,
        lease_token="synthetic-quarantine-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    run = _run(authorization)
    target_directory = tmp_path / "quarantine"
    target_directory.mkdir()

    result = execute_interim_quarantine(
        store=store,
        authorization=authorization,
        run=run,
        lease=lease,
        paths=InterimQuarantinePaths(candidate_path, source_root, target_directory),
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert result.status is QuarantineRunStatus.COMPLETED
    assert not candidate_path.exists()
    assert (target_directory / run.target_token).read_bytes() == candidate_bytes
    assert [event.status for event in store.events_for_run(RUN)] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
        QuarantineRunStatus.COMPLETED,
    ]
    engine.dispose()


def test_interim_executor_refuses_existing_target_without_touching_source(tmp_path: Path) -> None:
    engine = _head_engine_from_migration(tmp_path)
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    candidate_path = source_root / "candidate.epub"
    candidate_bytes = b"synthetic duplicate only"
    candidate_path.write_bytes(candidate_bytes)
    authorization = _authorization(hashlib.sha256(candidate_bytes).hexdigest())
    store = SQLiteQuarantineStore(engine)
    store.create_or_get_authorization(authorization)
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        ROOT,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        RUN,
        lease_token="synthetic-quarantine-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    run = _run(authorization)
    target_directory = tmp_path / "quarantine"
    target_directory.mkdir()
    (target_directory / run.target_token).write_bytes(b"must not be replaced")

    with pytest.raises(InterimQuarantineError, match="already exists"):
        execute_interim_quarantine(
            store=store,
            authorization=authorization,
            run=run,
            lease=lease,
            paths=InterimQuarantinePaths(candidate_path, source_root, target_directory),
            occurred_at=NOW + timedelta(seconds=1),
        )

    assert candidate_path.read_bytes() == candidate_bytes
    assert (target_directory / run.target_token).read_bytes() == b"must not be replaced"
    assert [event.status for event in store.events_for_run(RUN)] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.VALIDATION_FAILED,
    ]
    engine.dispose()


def _authorization(candidate_hash: str = CANDIDATE_HASH) -> QuarantineAuthorizationSnapshot:
    expires_at = NOW + timedelta(minutes=15)
    content_hash = _authorization_content_hash(
        PLAN,
        PLAN_HASH,
        ROOT,
        KEEPER,
        CANDIDATE,
        KEEPER_OBSERVATION,
        CANDIDATE_OBSERVATION,
        KEEPER_HASH,
        candidate_hash,
        CAPABILITY,
        REVIEW_HASH,
        NOW,
        expires_at,
    )
    return QuarantineAuthorizationSnapshot(
        _authorization_id(content_hash),
        PLAN,
        PLAN_HASH,
        ROOT,
        KEEPER,
        CANDIDATE,
        KEEPER_OBSERVATION,
        CANDIDATE_OBSERVATION,
        KEEPER_HASH,
        candidate_hash,
        CAPABILITY,
        REVIEW_HASH,
        NOW,
        expires_at,
        content_hash,
    )


def _run(authorization: QuarantineAuthorizationSnapshot) -> QuarantineExecutionRun:
    return QuarantineExecutionRun(
        RUN, authorization.id, PLAN, ROOT, KEEPER, CANDIDATE, "e" * 64, NOW
    )


def _head_engine_from_migration(tmp_path: Path):
    database = tmp_path / "quarantine.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    _seed(engine)
    return engine


def _seed(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            schema.scan_roots.insert(),
            {"id": str(ROOT), "name": "synthetic", "media_type": "EBOOK", "enabled": True},
        )
        connection.execute(
            schema.scan_runs.insert(),
            {
                "id": str(SCAN),
                "scan_root_id": str(ROOT),
                "started_at": NOW.isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
            },
        )
        for file_id, observation_id, path in (
            (KEEPER, KEEPER_OBSERVATION, "keeper.epub"),
            (CANDIDATE, CANDIDATE_OBSERVATION, "candidate.epub"),
        ):
            connection.execute(
                schema.file_records.insert(),
                {
                    "id": str(file_id),
                    "scan_root_id": str(ROOT),
                    "relative_path": path,
                    "size_bytes": 1,
                    "modified_at": NOW.isoformat(),
                    "media_type": "EBOOK",
                    "presence_state": "PRESENT",
                    "first_seen_at": NOW.isoformat(),
                    "last_seen_at": NOW.isoformat(),
                    "missing_since_at": None,
                    "consecutive_missing_scans": 0,
                },
            )
            connection.execute(
                schema.file_observations.insert(),
                {
                    "id": str(observation_id),
                    "file_id": str(file_id),
                    "scan_run_id": str(SCAN),
                    "relative_path": path,
                    "size_bytes": 1,
                    "modified_at": NOW.isoformat(),
                    "observed_at": NOW.isoformat(),
                },
            )
        connection.execute(
            text(  # noqa: E501
                "INSERT INTO consolidation_plans (id, profile, plan_version, serializer_version, scan_root_id, source_scan_run_id, keeper_file_id, keeper_observation_id, candidate_file_id, candidate_observation_id, status, execution_state, content_hash, created_at) VALUES (:id, 'consolidation-plan/v1', 1, 'canonical-json/v1', :root, :scan, :keeper, :keeper_observation, :candidate, :candidate_observation, 'APPROVED_NON_EXECUTABLE', 'NOT_EXECUTABLE', :hash, :created_at)"  # noqa: E501
            ),
            {
                "id": str(PLAN),
                "root": str(ROOT),
                "scan": str(SCAN),
                "keeper": str(KEEPER),
                "keeper_observation": str(KEEPER_OBSERVATION),
                "candidate": str(CANDIDATE),
                "candidate_observation": str(CANDIDATE_OBSERVATION),
                "hash": PLAN_HASH,
                "created_at": NOW.isoformat(),
            },
        )
