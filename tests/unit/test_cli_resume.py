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
