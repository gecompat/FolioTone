from datetime import UTC, datetime, timedelta
from pathlib import Path

from pytest import CaptureFixture

from foliotone.cli.main import main
from foliotone.core import EntityId, FileObservation, FileRecord, ToolExecutionStatus
from foliotone.persistence import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
    create_sqlite_engine,
    repository,
)
from foliotone.tooling import ToolExecution


def test_ebook_analyze_cli_reports_all_missing_tools_without_exposing_paths(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "media"
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    work = tmp_path / "work"
    media.mkdir()
    data.mkdir()
    source = media / "synthetic.epub"
    source_bytes = b"synthetic orchestrator fixture"
    source.write_bytes(source_bytes)
    database = data / "foliotone.db"

    assert main(
        [
            "scan",
            "--name",
            "ebook-analyze-cli",
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
    ) == 0
    capsys.readouterr()

    engine = create_sqlite_engine(database)
    (observation,) = repository(engine, FileObservation).list_all()
    missing = "foliotone-definitely-missing-executable"
    analyze_args = [
        "ebook-analyze",
        "--root",
        str(media),
        "--observation-id",
        str(observation.id),
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
        "--java-executable",
        missing,
        "--epubcheck-jar",
        str(tmp_path / "missing-epubcheck.jar"),
    ]
    result = main(analyze_args)

    assert result == 1
    output = capsys.readouterr().out
    assert f"FileObservation: {observation.id}" in output
    assert "Format: EPUB" in output
    assert "Analysis profile: ebook-analysis-workflow/v3" in output
    assert "Evidence policy: REUSE_EXACT" in output
    assert "metadata status: FAILED" in output
    assert "text status: FAILED" in output
    assert "cover status: FAILED" in output
    assert "structural-validation status: FAILED" in output
    assert output.count("evidence action: EXECUTED") == 4
    assert "Quality profile: ebook-quality/v1" in output
    assert "Quality status: INCOMPLETE" in output
    assert "Quality dimension METADATA: INCOMPLETE" in output
    assert "Quality dimension TEXT: INCOMPLETE" in output
    assert "Quality dimension COVER: INCOMPLETE" in output
    assert "Quality dimension STRUCTURE: INCOMPLETE" in output
    assert "Quality dimension FORMAT_RISK: OK" in output
    assert "Quality findings: 4" in output
    assert "Overall status: FAILED" in output
    assert str(media) not in output
    assert str(source) not in output

    executions = repository(engine, ToolExecution).list_all()
    assert len(executions) == 4
    assert all(
        execution.status is ToolExecutionStatus.FAILED for execution in executions
    )
    assert all(
        execution.input_identity == f"file-observation:{observation.id}"
        for execution in executions
    )

    assert main(analyze_args) == 1
    retry_output = capsys.readouterr().out
    assert "Evidence policy: REUSE_EXACT" in retry_output
    assert retry_output.count("evidence action: EXECUTED") == 4
    assert len(repository(engine, ToolExecution).list_all()) == 8

    assert main([*analyze_args, "--fresh"]) == 1
    fresh_output = capsys.readouterr().out
    assert "Evidence policy: FRESH" in fresh_output
    assert fresh_output.count("evidence action: EXECUTED") == 4
    assert len(repository(engine, ToolExecution).list_all()) == 12
    assert source.read_bytes() == source_bytes
    assert list(work.iterdir()) == []

    record = repository(engine, FileRecord).get(observation.file_id)
    assert record is not None
    now = datetime.now(UTC)
    SQLiteScanRootWriteLeaseStore(engine).acquire(
        record.scan_root_id,
        ScanRootWriteOwnerKind.EBOOK_COLLECTION_RUN,
        EntityId.new(),
        lease_token="competing-writer",
        acquired_at=now,
        lease_expires_at=now + timedelta(minutes=30),
    )

    assert main(analyze_args) == 2
    collision_output = capsys.readouterr().out
    assert "another write workflow owns this ScanRoot" in collision_output
    assert str(media) not in collision_output
    assert str(source) not in collision_output
    assert "competing-writer" not in collision_output
    assert len(repository(engine, ToolExecution).list_all()) == 12
