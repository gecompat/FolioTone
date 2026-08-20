import io

import pytest

import foliotone.cli.main as cli_module
from foliotone.index import (
    DiscoveryProgress,
    HashMode,
    HashProgress,
    ReconciliationProgress,
    ScanProgress,
    ScanProgressPhase,
)


def test_scan_worker_auto_policy_is_bounded_and_explicit_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module.os, "cpu_count", lambda: 12)

    assert cli_module._resolved_scan_hash_workers(None, HashMode.QUICK) == 6
    assert cli_module._resolved_scan_hash_workers(3, HashMode.FULL) == 3
    assert cli_module._resolved_scan_hash_workers(None, HashMode.NONE) == 1
    assert cli_module._scan_hash_worker_value("auto") is None
    assert cli_module._scan_hash_worker_value("8") == 8


@pytest.mark.parametrize("value", ["0", "9", "invalid"])
def test_scan_worker_parser_rejects_unbounded_values(value: str) -> None:
    with pytest.raises(cli_module.argparse.ArgumentTypeError):
        cli_module._scan_hash_worker_value(value)


def test_scan_progress_renderer_is_path_free_and_reports_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    ticks = iter((10.0, 10.0, 12.0))
    monkeypatch.setattr(cli_module.sys, "stderr", stream)
    progress = cli_module._ScanConsoleProgress(True, clock=lambda: next(ticks))
    progress.start_scan()

    progress.report(
        ScanProgress(
            phase=ScanProgressPhase.DISCOVERING,
            processed_files=4,
            processed_bytes=2 * 1024 * 1024,
            hash_failures=0,
        )
    )

    assert stream.getvalue() == (
        "Scan progress: scanning; files=4; data=2.0 MiB; throughput=1.0 MiB/s\n"
    )
    assert "private" not in stream.getvalue()
    assert "archive.epub" not in stream.getvalue()


def test_scan_progress_renderer_reports_live_hash_read_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(cli_module.sys, "stderr", stream)
    progress = cli_module._ScanConsoleProgress(True)

    progress.report(
        HashProgress(
            batch_files=8,
            completed_files=3,
            bytes_read=2 * 1024 * 1024,
            current_bytes_per_second=1.5 * 1024 * 1024,
            average_bytes_per_second=1.0 * 1024 * 1024,
        )
    )

    assert stream.getvalue() == (
        "Scan progress: hashing; batch=3/8; read=2.0 MiB; "
        "current-throughput=1.5 MiB/s; average-throughput=1.0 MiB/s\n"
    )


def test_scan_progress_renderer_reports_discovery_and_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(cli_module.sys, "stderr", stream)
    progress = cli_module._ScanConsoleProgress(True)

    progress.report(
        DiscoveryProgress(
            discovered_files=10,
            discovered_bytes=4 * 1024 * 1024,
            current_bytes_per_second=2 * 1024 * 1024,
            average_bytes_per_second=1 * 1024 * 1024,
        )
    )
    progress.report(
        ReconciliationProgress(
            processed_files=8,
            processed_bytes=3 * 1024 * 1024,
            batch_files=2,
            batch_bytes=1 * 1024 * 1024,
        )
    )

    assert stream.getvalue() == (
        "Scan progress: discovering; files=10; data=4.0 MiB; "
        "current-throughput=2.0 MiB/s; average-throughput=1.0 MiB/s\n"
        "Scan progress: reconciling; completed-files=8; completed-data=3.0 MiB; "
        "batch-files=2; batch-data=1.0 MiB\n"
    )


def test_scan_cli_interrupts_cleanly_before_migration_starts_a_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupted_migration(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "migrate", interrupted_migration)

    exit_code = cli_module.main(
        [
            "scan",
            "--name",
            "interrupted",
            "--path",
            str(tmp_path),
            "--media-type",
            "ebook",
            "--database",
            str(tmp_path / "foliotone.db"),
            "--no-progress",
        ]
    )

    assert exit_code == 130
    assert capsys.readouterr().out == "Scan interrupted before a ScanRun was started.\n"
