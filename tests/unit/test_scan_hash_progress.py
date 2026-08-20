from foliotone.index.scanner import _HashProgressKeeper, _HashReadMeter


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
