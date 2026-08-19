from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pytest import CaptureFixture

from foliotone.cli.main import main
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    FileRecord,
    Fingerprint,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    EbookInventoryReportStoreError,
    SQLiteEbookInventoryReportStore,
    create_sqlite_engine,
    repository,
)
from foliotone.workflows import EbookInventoryReportLimits, EbookInventoryReportService

NOW = datetime(2026, 8, 15, 22, 0, tzinfo=UTC)


def test_inventory_report_rejects_a_latest_non_completed_scan(
    tmp_path: Path,
    head_database: Path,
) -> None:
    database = head_database
    engine = create_sqlite_engine(database)
    root = ScanRoot(
        id=EntityId.new(),
        name="changing-inventory",
        media_type=MediaType.EBOOK,
    )
    completed = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.COMPLETED,
    )
    running = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW + timedelta(seconds=1),
        status=ScanRunStatus.RUNNING,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(completed)
    repository(engine, ScanRun).save(running)

    with pytest.raises(
        EbookInventoryReportStoreError,
        match="latest ScanRun must be COMPLETED",
    ):
        SQLiteEbookInventoryReportStore(engine).snapshot(
            root.id,
            candidate_group_limit=1,
            candidate_member_limit=1,
        )


def test_inventory_report_is_scan_wide_actionable_private_and_deterministic(
    tmp_path: Path,
    head_database: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "private-media"
    media.mkdir()
    contents = {
        "+a.epub": b"x" * 100,
        "b.epub": b"x" * 100,
        "c.pdf": b"c" * 80,
        "d.pdf": b"d" * 80,
        "e.mobi": b"z" * 20,
    }
    database = head_database
    engine = create_sqlite_engine(database)
    root = ScanRoot(
        id=EntityId.new(),
        name="inventory-report",
        media_type=MediaType.EBOOK,
    )
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    observations: dict[str, FileObservation] = {}
    for relative_path, content in contents.items():
        (media / relative_path).write_bytes(content)
        record = FileRecord(
            id=EntityId.new(),
            scan_root_id=root.id,
            relative_path=relative_path,
            size_bytes=len(content),
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
            size_bytes=len(content),
            modified_at=NOW,
            observed_at=NOW,
        )
        repository(engine, FileRecord).save(record)
        repository(engine, FileObservation).save(observation)
        observations[relative_path] = observation

    quick_values = {
        "+a.epub": "1" * 64,
        "b.epub": "1" * 64,
        "c.pdf": "2" * 64,
        "d.pdf": "2" * 64,
        "e.mobi": "3" * 64,
    }
    full_values = {
        "+a.epub": "a" * 64,
        "b.epub": "a" * 64,
        "c.pdf": "c" * 64,
        "e.mobi": "e" * 64,
    }
    for relative_path, observation in observations.items():
        repository(engine, Fingerprint).save(
            Fingerprint(
                id=EntityId.new(),
                target_kind=EntityKind.FILE_OBSERVATION,
                target_id=observation.id,
                kind="QUICK_FILE",
                algorithm="sha256-head-tail",
                algorithm_version="1",
                value=quick_values[relative_path],
                created_at=NOW,
            )
        )
        if relative_path in full_values:
            repository(engine, Fingerprint).save(
                Fingerprint(
                    id=EntityId.new(),
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    kind="FILE_SHA256",
                    algorithm="sha256",
                    algorithm_version="1",
                    value=full_values[relative_path],
                    created_at=NOW,
                )
            )

    source_bytes = {path: path.read_bytes() for path in media.iterdir()}
    limits = EbookInventoryReportLimits(candidate_groups=1, members_per_group=1)
    service = EbookInventoryReportService(SQLiteEbookInventoryReportStore(engine))
    first = service.generate(root.id, tmp_path / "reports", limits=limits)
    second = service.generate(root.id, tmp_path / "reports", limits=limits)

    assert first.report_directory == second.report_directory
    assert first.report_sha256 == second.report_sha256
    assert first.files == (
        "checksums.sha256",
        "exact-duplicates.csv",
        "inventory-report.json",
    )
    payload = json.loads(
        (first.report_directory / "inventory-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["profile"] == "ebook-inventory-report/v1"
    assert payload["aggregate"]["observations"] == 5
    assert payload["aggregate"]["total_bytes"] == 380
    assert payload["aggregate"]["formats"]["EPUB"] == {
        "observations": 2,
        "total_bytes": 200,
    }
    assert payload["aggregate"]["formats"]["PDF"] == {
        "observations": 2,
        "total_bytes": 160,
    }
    assert payload["hash_coverage"] == {
        "full_hash_observations": 4,
        "quick_candidate_groups": 2,
        "quick_candidate_observations": 4,
        "quick_candidates_missing_full_hash": 1,
    }
    duplicates = payload["exact_duplicates"]
    assert duplicates["total_groups"] == 1
    assert duplicates["total_members"] == 2
    assert duplicates["total_redundant_bytes"] == 100
    assert duplicates["groups"][0]["members_truncated"] is True
    report_text = json.dumps(payload)
    assert all(value not in report_text for value in quick_values.values())
    assert all(value not in report_text for value in full_values.values())
    assert "'+a.epub" in (
        first.report_directory / "exact-duplicates.csv"
    ).read_text(encoding="utf-8")
    _verify_checksums(first.report_directory)

    cli_root = tmp_path / "cli-reports"
    assert main(
        [
            "ebook-inventory-report",
            "--scan-root",
            root.name,
            "--source-root",
            str(media),
            "--database",
            str(database),
            "--report-root",
            str(cli_root),
            "--group-limit",
            "1",
            "--group-member-limit",
            "1",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "Report profile: ebook-inventory-report/v1" in output
    assert "Observations: 5" in output
    assert "Format EPUB: 2 observations, 200 bytes" in output
    assert "Format PDF: 2 observations, 160 bytes" in output
    assert "Format MOBI: 1 observation, 20 bytes" in output
    assert "Full-hash observations: 4" in output
    assert "Quick candidate groups: 2" in output
    assert "Quick candidate observations: 4" in output
    assert "Quick candidates missing full hash: 1" in output
    assert "Exact duplicate groups: 1" in output
    assert "Exact duplicate observations: 2" in output
    assert "Potential redundant bytes: 100" in output
    assert str(media) not in output
    assert all(relative_path not in output for relative_path in observations)
    assert all(path.read_bytes() == content for path, content in source_bytes.items())


def _verify_checksums(report_directory: Path) -> None:
    lines = (report_directory / "checksums.sha256").read_text(
        encoding="ascii"
    ).splitlines()
    assert len(lines) == 2
    for line in lines:
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((report_directory / name).read_bytes()).hexdigest() == expected
