from datetime import UTC, datetime
from pathlib import Path

from foliotone.index.discovery import DiscoveredFile
from foliotone.index.scanner import (
    _DiscoveryMeter,
    _DiscoveryProgressReporter,
    _HashProgressKeeper,
    _HashReadMeter,
    _ReconciliationMeter,
    _ReconciliationProgressKeeper,
)


def test_hash_progress_keeper_reports_current_and_average_read_rates() -> None:
    meter = _HashReadMeter()
    reports = []
    ticks = iter((10.0, 12.0))
    keeper = _HashProgressKeeper(
        meter,
        8,
        reports.append,
        clock=lambda: next(ticks),
        interval_seconds=1.0,
    )
    meter.add_bytes(2 * 1024 * 1024)
    meter.complete_file()

    keeper._report_once()

    assert len(reports) == 1
    progress = reports[0]
    assert progress.batch_files == 8
    assert progress.completed_files == 1
    assert progress.bytes_read == 2 * 1024 * 1024
    assert progress.current_bytes_per_second == 1024 * 1024
    assert progress.average_bytes_per_second == 1024 * 1024


def test_reconciliation_progress_keeper_reports_partial_atomic_batch() -> None:
    meter = _ReconciliationMeter()
    reports = []
    keeper = _ReconciliationProgressKeeper(
        meter,
        processed_files=256,
        processed_bytes=3 * 1024 * 1024,
        batch_files=256,
        batch_bytes=2 * 1024 * 1024,
        report=reports.append,
        interval_seconds=1.0,
    )
    meter.set_progress(17, 128 * 1024)

    keeper._report_once()

    assert len(reports) == 1
    progress = reports[0]
    assert progress.processed_files == 256
    assert progress.batch_files == 256
    assert progress.reconciled_files == 17
    assert progress.reconciled_bytes == 128 * 1024


def test_reconciliation_progress_keeper_reports_fast_file_steps() -> None:
    meter = _ReconciliationMeter()
    reports = []
    keeper = _ReconciliationProgressKeeper(
        meter,
        processed_files=0,
        processed_bytes=0,
        batch_files=32,
        batch_bytes=32,
        report=reports.append,
        interval_seconds=1.0,
    )

    keeper.record_progress(15, 15)
    keeper.record_progress(16, 16)
    keeper.record_progress(32, 32)

    assert [progress.reconciled_files for progress in reports] == [16, 32]


def test_discovery_progress_reports_live_enumeration_rate() -> None:
    meter = _DiscoveryMeter()
    reports = []
    ticks = iter((10.0, 12.0))
    reporter = _DiscoveryProgressReporter(
        meter,
        reports.append,
        clock=lambda: next(ticks),
        interval_seconds=1.0,
    )
    meter.add_file(
        DiscoveredFile(
            relative_path="example.epub",
            size_bytes=2 * 1024 * 1024,
            modified_at=datetime(2026, 1, 1, tzinfo=UTC),
            physical_path=Path("C:/synthetic/example.epub"),
        )
    )

    reporter.report_now()

    assert len(reports) == 1
    progress = reports[0]
    assert progress.discovered_files == 1
    assert progress.discovered_bytes == 2 * 1024 * 1024
    assert progress.current_bytes_per_second == 1024 * 1024
    assert progress.average_bytes_per_second == 1024 * 1024
