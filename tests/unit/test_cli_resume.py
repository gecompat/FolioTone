import pytest

from foliotone.cli.main import build_parser
from foliotone.core import EntityId


def test_scan_cli_parses_resume_run_as_entity_id() -> None:
    run_id = EntityId.new()
    args = build_parser().parse_args(
        [
            "scan",
            "--name",
            "resume-test",
            "--path",
            "/media/ebooks",
            "--media-type",
            "ebook",
            "--resume-run",
            str(run_id),
        ]
    )

    assert args.resume_run == run_id


def test_scan_cli_parses_stale_running_recovery_as_resume_choice() -> None:
    args = build_parser().parse_args(
        [
            "scan",
            "--name",
            "resume-test",
            "--path",
            "/media/ebooks",
            "--media-type",
            "ebook",
            "--recover-stale-running",
        ]
    )

    assert args.recover_stale_running is True
    assert args.resume_run is None
    assert args.resume_last_interrupted is False


def test_scan_cli_rejects_two_resume_sources() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "scan",
                "--name",
                "resume-test",
                "--path",
                "/media/ebooks",
                "--media-type",
                "ebook",
                "--resume-last-interrupted",
                "--recover-stale-running",
            ]
        )


def test_collection_cli_parses_resume_last_interrupted_flag() -> None:
    args = build_parser().parse_args(
        [
            "ebook-collection-analyze",
            "--root",
            "/media/ebooks",
            "--scan-root",
            "resume-test",
            "--database",
            "/tmp/foliotone.db",
            "--resume-last-interrupted",
            "--workers",
            "2",
        ]
    )

    assert args.resume_last_interrupted is True
    assert args.resume_run is None
