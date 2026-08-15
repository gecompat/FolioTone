from pathlib import Path

from pytest import CaptureFixture

from foliotone.cli.main import main
from foliotone.core import (
    EbookCollectionItem,
    EbookCollectionItemStatus,
    EbookCollectionRun,
    EbookCollectionRunStatus,
    FileObservation,
)
from foliotone.persistence import create_sqlite_engine, repository


def test_collection_cli_stops_and_resumes_without_exposing_source_paths(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "private-media"
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    work = tmp_path / "work"
    media.mkdir()
    data.mkdir()
    sources = {
        media / "a.epub": b"synthetic epub",
        media / "b.pdf": b"synthetic pdf",
    }
    for path, content in sources.items():
        path.write_bytes(content)
    database = data / "foliotone.db"

    assert main(
        [
            "scan",
            "--name",
            "collection-cli",
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
            "--suffix",
            "pdf",
        ]
    ) == 0
    capsys.readouterr()

    missing = "foliotone-definitely-missing-executable"
    base_args = [
        "ebook-collection-analyze",
        "--root",
        str(media),
        "--scan-root",
        "collection-cli",
        "--database",
        str(database),
        "--artifact-root",
        str(artifacts),
        "--work-root",
        str(work),
        "--ebook-meta-executable",
        missing,
        "--ebook-convert-executable",
        missing,
        "--calibre-debug-executable",
        missing,
        "--pdfinfo-executable",
        missing,
        "--pdftotext-executable",
        missing,
        "--java-executable",
        missing,
        "--epubcheck-jar",
        str(tmp_path / "missing-epubcheck.jar"),
    ]
    first_result = main(
        [
            *base_args,
            "--workers",
            "2",
            "--plan-per-format",
            "1",
            "--max-items",
            "1",
        ]
    )
    first_output = capsys.readouterr().out

    assert first_result == 3
    assert "Collection profile: ebook-collection-analysis/v1" in first_output
    assert "Analysis profile: ebook-analysis-workflow/v3" in first_output
    assert "Evidence policy: REUSE_EXACT" in first_output
    assert "Processed this invocation: 1" in first_output
    assert "Planned: 2" in first_output
    assert "Pending: 1" in first_output
    assert "Status: INTERRUPTED" in first_output
    assert str(media) not in first_output
    assert all(str(path) not in first_output for path in sources)

    engine = create_sqlite_engine(database)
    (run,) = repository(engine, EbookCollectionRun).list_all()
    assert run.status is EbookCollectionRunStatus.INTERRUPTED
    observations = repository(engine, FileObservation).list_all()
    assert all(str(observation.id) not in first_output for observation in observations)

    resumed_result = main([*base_args, "--resume-run", str(run.id)])
    resumed_output = capsys.readouterr().out

    assert resumed_result == 1
    assert f"E-book collection run: {run.id}" in resumed_output
    assert "Processed this invocation: 1" in resumed_output
    assert "Pending: 0" in resumed_output
    assert "Failed: 2" in resumed_output
    assert "Status: COMPLETED_WITH_FAILURES" in resumed_output
    assert str(media) not in resumed_output
    assert all(str(path) not in resumed_output for path in sources)
    assert all(str(observation.id) not in resumed_output for observation in observations)

    resumed_last_result = main([*base_args, "--resume-last-interrupted"])
    resumed_last_output = capsys.readouterr().out

    assert resumed_last_result == 1
    assert f"E-book collection run: {run.id}" in resumed_last_output
    assert "Processed this invocation: 0" in resumed_last_output
    assert "Pending: 0" in resumed_last_output
    assert "Status: COMPLETED_WITH_FAILURES" in resumed_last_output

    items = repository(engine, EbookCollectionItem).list_all()
    assert len(items) == 2
    assert all(item.status is EbookCollectionItemStatus.FAILED for item in items)
    assert all(path.read_bytes() == content for path, content in sources.items())
    assert list(work.iterdir()) == []


def test_collection_cli_rejects_mutable_storage_inside_source_root(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "media"
    media.mkdir()

    result = main(
        [
            "ebook-collection-analyze",
            "--root",
            str(media),
            "--scan-root",
            "not-created",
            "--database",
            str(media / "foliotone.db"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--work-root",
            str(tmp_path / "work"),
        ]
    )

    assert result == 2
    assert "must be outside source root" in capsys.readouterr().out
    assert not (media / "foliotone.db").exists()
