from pathlib import Path

from foliotone.cli.main import main


def test_scan_cli_reports_incremental_states(tmp_path: Path, capsys) -> None:
    media = tmp_path / "media"
    data = tmp_path / "data"
    media.mkdir()
    data.mkdir()
    database = data / "foliotone.db"
    first = media / "A.epub"
    second = media / "B.epub"
    first.write_bytes(b"alpha")
    second.write_bytes(b"bravo")

    base_args = [
        "scan",
        "--name",
        "cli-test",
        "--path",
        str(media),
        "--media-type",
        "ebook",
        "--database",
        str(database),
        "--hash",
        "quick",
        "--suffix",
        "epub",
    ]

    assert main(base_args) == 0
    first_output = capsys.readouterr().out
    assert "Status: COMPLETED" in first_output
    assert "Observed files: 2" in first_output
    assert "NEW: 2" in first_output

    assert main(base_args) == 0
    second_output = capsys.readouterr().out
    assert "UNCHANGED: 2" in second_output

    first.write_bytes(b"alpha-modified")
    second.unlink()
    assert main(base_args) == 0
    third_output = capsys.readouterr().out
    assert "MODIFIED: 1" in third_output
    assert "MISSING: 1" in third_output

    second.write_bytes(b"bravo")
    assert main(base_args) == 0
    fourth_output = capsys.readouterr().out
    assert "REAPPEARED: 1" in fourth_output
    assert "UNCHANGED: 1" in fourth_output
