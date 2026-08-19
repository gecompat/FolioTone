from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pytest import CaptureFixture
from sqlalchemy import update

from foliotone.cli.main import main
from foliotone.core import (
    EbookCandidateHashRunStatus,
    EbookCollectionItemStatus,
    EbookCollectionRunStatus,
    EntityId,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    SQLiteEbookCandidateHashRunStore,
    SQLiteEbookCollectionStore,
    SQLiteEbookInventoryReportStore,
    create_sqlite_engine,
    migrate,
    repository,
    w3_schema,
)
from foliotone.workflows import (
    EBOOK_ANALYSIS_PROFILE,
    EBOOK_COLLECTION_PROFILE,
    EbookInventoryReportLimits,
    EbookInventoryReportService,
)

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
FORMATS = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")


def test_postscan_verify_is_complete_machine_readable_path_free_and_read_only(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database, report_root, report_sha256, collection_run_id, private_names = (
        _completed_postscan(tmp_path)
    )
    before_database = database.read_bytes()
    before_reports = _report_listing(report_root)

    result = main(
        _verify_args(
            database,
            report_root,
            report_sha256,
            collection_run_id,
            output="json",
        )
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert result == 0
    assert payload["schema_version"] == 1
    assert payload["command"] == "ebook-postscan-verify"
    assert payload["overall"] == "COMPLETE"
    assert set(payload["checks"]) == {
        "migration",
        "source_scan",
        "candidate_hash",
        "inventory_report",
        "collection_analysis",
    }
    assert all(
        check["state"] == "COMPLETE" for check in payload["checks"].values()
    )
    assert payload["checks"]["inventory_report"]["details"]["files_verified"] == 3
    assert str(tmp_path) not in output
    assert report_sha256 not in output
    assert "lease-token" not in output
    assert all(name not in output for name in private_names)
    assert database.read_bytes() == before_database
    assert _report_listing(report_root) == before_reports


def test_postscan_verify_distinguishes_missing_tampered_and_degraded_state(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database, report_root, report_sha256, collection_run_id, _private_names = (
        _completed_postscan(tmp_path)
    )
    missing_root = tmp_path / "not-persisted"
    assert main(
        _verify_args(
            database,
            missing_root,
            report_sha256,
            collection_run_id,
            output="json",
        )
    ) == 3
    pending = json.loads(capsys.readouterr().out)
    assert pending["overall"] == "PENDING"
    assert pending["checks"]["inventory_report"]["code"] == "INVENTORY_REPORT_MISSING"
    assert not missing_root.exists()

    report_file = next(report_root.rglob("inventory-report.json"))
    report_file.write_bytes(report_file.read_bytes() + b"\n")
    assert main(
        _verify_args(
            database,
            report_root,
            report_sha256,
            collection_run_id,
            output="json",
        )
    ) == 2
    invalid = json.loads(capsys.readouterr().out)
    assert invalid["overall"] == "INVALID"
    assert invalid["checks"]["inventory_report"]["code"] == "INVENTORY_REPORT_INVALID"

    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            update(w3_schema.ebook_collection_items)
            .where(w3_schema.ebook_collection_items.c.run_id == str(collection_run_id))
            .values(status=EbookCollectionItemStatus.PARTIAL_FAILURE.value)
        )
        connection.execute(
            update(w3_schema.ebook_collection_runs)
            .where(w3_schema.ebook_collection_runs.c.id == str(collection_run_id))
            .values(status=EbookCollectionRunStatus.COMPLETED_WITH_FAILURES.value)
        )
    engine.dispose()
    fresh_report_root = tmp_path / "fresh-reports"
    write_engine = create_sqlite_engine(database)
    root = next(
        value
        for value in repository(write_engine, ScanRoot).list_all()
        if value.name == "postscan-verify"
    )
    outcome = EbookInventoryReportService(
        SQLiteEbookInventoryReportStore(write_engine)
    ).generate(root.id, fresh_report_root)
    write_engine.dispose()
    assert outcome.report_sha256 == report_sha256

    assert main(
        _verify_args(
            database,
            fresh_report_root,
            report_sha256,
            collection_run_id,
            output="json",
        )
    ) == 1
    degraded = json.loads(capsys.readouterr().out)
    assert degraded["overall"] == "DEGRADED"
    assert degraded["checks"]["collection_analysis"]["code"] == (
        "COLLECTION_ANALYSIS_FAILURES"
    )


def test_postscan_verify_rejects_an_old_schema_without_modifying_it(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database = tmp_path / "old-schema.db"
    migrate(database, "0010_candidate_hash_lookup_index")
    before = database.read_bytes()
    before_entries = _report_listing(tmp_path)

    result = main(
        _verify_args(
            database,
            tmp_path / "reports",
            "0" * 64,
            EntityId.new(),
            output="json",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["overall"] == "INVALID"
    assert payload["checks"]["migration"]["code"] == "SCHEMA_MISMATCH"
    assert database.read_bytes() == before
    assert _report_listing(tmp_path) == before_entries


def _completed_postscan(
    tmp_path: Path,
) -> tuple[Path, Path, str, EntityId, tuple[str, ...]]:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    root = ScanRoot(
        id=EntityId.new(),
        name="postscan-verify",
        media_type=MediaType.EBOOK,
    )
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        status=ScanRunStatus.COMPLETED,
        completed_at=NOW + timedelta(seconds=1),
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    private_names: list[str] = []
    for ordinal, format_name in enumerate(FORMATS):
        relative_path = f"private-{ordinal}.{format_name.lower()}"
        private_names.append(relative_path)
        record = FileRecord(
            id=EntityId.new(),
            scan_root_id=root.id,
            relative_path=relative_path,
            size_bytes=ordinal + 1,
            modified_at=NOW,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        observation = FileObservation(
            id=EntityId.new(),
            file_id=record.id,
            scan_run_id=scan.id,
            relative_path=relative_path,
            size_bytes=ordinal + 1,
            modified_at=NOW,
            observed_at=NOW,
        )
        repository(engine, FileRecord).save(record)
        repository(engine, FileObservation).save(observation)

    candidate_store = SQLiteEbookCandidateHashRunStore(engine)
    candidate = candidate_store.acquire(
        root.id,
        scan.id,
        "ebook-duplicate-hash/v1",
        lease_token="candidate-lease-token",
        started_at=NOW + timedelta(seconds=2),
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    candidate_store.record_selection(
        candidate.id,
        "candidate-lease-token",
        heartbeat_at=NOW + timedelta(seconds=3),
        lease_expires_at=NOW + timedelta(minutes=30),
        candidate_groups=0,
        candidate_observations=0,
        already_hashed=0,
        remaining_count=0,
    )
    candidate_store.finish(
        candidate.id,
        "candidate-lease-token",
        EbookCandidateHashRunStatus.COMPLETED,
        finished_at=NOW + timedelta(seconds=4),
    )

    report_root = tmp_path / "reports"
    report = EbookInventoryReportService(
        SQLiteEbookInventoryReportStore(engine)
    ).generate(root.id, report_root, limits=EbookInventoryReportLimits())
    collection_store = SQLiteEbookCollectionStore(engine)
    created = collection_store.create_run(
        root.id,
        profile=EBOOK_COLLECTION_PROFILE,
        analysis_profile=EBOOK_ANALYSIS_PROFILE,
        fresh=False,
        worker_count=1,
        started_at=NOW + timedelta(seconds=5),
        lease_token="collection-lease-token",
        lease_expires_at=NOW + timedelta(minutes=30),
        plan_per_format=1,
    )
    completed_at = (NOW + timedelta(seconds=6)).isoformat()
    with engine.begin() as connection:
        connection.execute(
            update(w3_schema.ebook_collection_items)
            .where(w3_schema.ebook_collection_items.c.run_id == str(created.run.id))
            .values(
                status=EbookCollectionItemStatus.SUCCEEDED.value,
                attempt_count=1,
                started_at=completed_at,
                completed_at=completed_at,
            )
        )
        connection.execute(
            update(w3_schema.ebook_collection_runs)
            .where(w3_schema.ebook_collection_runs.c.id == str(created.run.id))
            .values(
                status=EbookCollectionRunStatus.COMPLETED.value,
                completed_at=completed_at,
                lease_token=None,
                lease_expires_at=None,
            )
        )
    engine.dispose()
    return (
        database,
        report_root,
        report.report_sha256,
        created.run.id,
        tuple(private_names),
    )


def _verify_args(
    database: Path,
    report_root: Path,
    report_sha256: str,
    collection_run_id: EntityId,
    *,
    output: str,
) -> list[str]:
    return [
        "ebook-postscan-verify",
        "--scan-root",
        "postscan-verify",
        "--database",
        str(database),
        "--inventory-report-root",
        str(report_root),
        "--inventory-report-sha256",
        report_sha256,
        "--collection-run",
        str(collection_run_id),
        "--plan-per-format",
        "1",
        "--output",
        output,
    ]


def _report_listing(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(
            str(path.relative_to(root))
            for path in root.rglob("*")
        )
    )
