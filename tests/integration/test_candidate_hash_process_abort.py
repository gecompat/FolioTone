"""Process-boundary recovery tests for candidate-hash run leases."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from foliotone.core import (
    EbookCandidateHashRunStatus,
    EntityId,
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

_ACQUIRE_AND_ABORT = """
import os
import sys
from datetime import datetime
from pathlib import Path

from foliotone.core import EntityId
from foliotone.persistence import SQLiteEbookCandidateHashRunStore, create_sqlite_engine

database, root_id, scan_id, started_at, lease_expires_at = sys.argv[1:]
store = SQLiteEbookCandidateHashRunStore(create_sqlite_engine(Path(database)))
store.acquire(
    EntityId.parse(root_id),
    EntityId.parse(scan_id),
    "ebook-duplicate-hash/v1",
    lease_token="aborted-child-owner",
    started_at=datetime.fromisoformat(started_at),
    lease_expires_at=datetime.fromisoformat(lease_expires_at),
)
os._exit(17)
"""


def test_hard_process_abort_is_recovered_only_after_lease_expiry(
    tmp_path: Path,
) -> None:
    database = tmp_path / "hard-abort.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(
        id=EntityId.new(),
        name="synthetic-hard-abort",
        media_type=MediaType.EBOOK,
    )
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

    initial_expiry = NOW + timedelta(minutes=1)
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            _ACQUIRE_AND_ABORT,
            str(database),
            str(root.id),
            str(scan.id),
            NOW.isoformat(),
            initial_expiry.isoformat(),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 17

    engine = create_sqlite_engine(database)
    store = SQLiteEbookCandidateHashRunStore(engine)
    abandoned = store.latest(root.id)
    assert abandoned is not None
    assert abandoned.status is EbookCandidateHashRunStatus.RUNNING
    assert abandoned.lease_expires_at == initial_expiry

    before_expiry = NOW + timedelta(seconds=30)
    with pytest.raises(EbookCandidateHashLeaseError, match="active candidate-hash lease"):
        store.acquire(
            root.id,
            scan.id,
            PROFILE,
            lease_token="too-early-parent-owner",
            started_at=before_expiry,
            lease_expires_at=before_expiry + timedelta(minutes=30),
        )

    takeover_at = initial_expiry + timedelta(seconds=1)
    replacement = store.acquire(
        root.id,
        scan.id,
        PROFILE,
        lease_token="replacement-parent-owner",
        started_at=takeover_at,
        lease_expires_at=takeover_at + timedelta(minutes=30),
    )
    selected_at = takeover_at + timedelta(seconds=1)
    store.record_selection(
        replacement.id,
        "replacement-parent-owner",
        heartbeat_at=selected_at,
        lease_expires_at=selected_at + timedelta(minutes=30),
        candidate_groups=0,
        candidate_observations=0,
        already_hashed=0,
        remaining_count=0,
    )
    store.finish(
        replacement.id,
        "replacement-parent-owner",
        EbookCandidateHashRunStatus.COMPLETED,
        finished_at=selected_at + timedelta(seconds=1),
    )

    with engine.connect() as connection:
        runs = connection.execute(
            select(w3_schema.ebook_candidate_hash_runs).order_by(
                w3_schema.ebook_candidate_hash_runs.c.started_at,
                w3_schema.ebook_candidate_hash_runs.c.id,
            )
        ).mappings().all()
        fingerprint_count = connection.execute(
            select(func.count()).select_from(schema.fingerprints)
        ).scalar_one()

    assert len(runs) == 2
    assert {row["id"] for row in runs} == {
        str(abandoned.id),
        str(replacement.id),
    }
    old_row = next(row for row in runs if row["id"] == str(abandoned.id))
    new_row = next(row for row in runs if row["id"] == str(replacement.id))
    assert old_row["status"] == EbookCandidateHashRunStatus.INTERRUPTED.value
    assert old_row["finished_at"] == takeover_at.isoformat()
    assert old_row["lease_token"] is None
    assert old_row["lease_expires_at"] is None
    assert new_row["status"] == EbookCandidateHashRunStatus.COMPLETED.value
    assert new_row["processed_count"] == 0
    assert new_row["hashed_count"] == 0
    assert new_row["failure_count"] == 0
    assert fingerprint_count == 0

    latest = store.latest(root.id)
    assert latest is not None
    assert latest.id == replacement.id
    assert latest.status is EbookCandidateHashRunStatus.COMPLETED
    engine.dispose()
