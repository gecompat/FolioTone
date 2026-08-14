from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.adapters.calibre.metadata import (
    CALIBRE_CONFIG_IDENTITY,
    CALIBRE_OPF_ARTIFACT,
    MAX_OPF_BYTES,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    calibre_version_policy,
    parse_calibre_opf,
)
from foliotone.core import (
    EntityId,
    FileObservation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.tooling import ToolArtifact, ToolExecution, ToolResult
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
SAMPLE_OPF = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="2.0">
  <metadata>
    <dc:title>  The   Example  </dc:title>
    <dc:creator xmlns:opf="http://www.idpf.org/2007/opf" opf:role="aut">
      Ada Author
    </dc:creator>
    <dc:identifier xmlns:opf="http://www.idpf.org/2007/opf" opf:scheme="ISBN">
      9780000000001
    </dc:identifier>
    <dc:language>en</dc:language>
    <dc:publisher>Example Press</dc:publisher>
    <dc:date>2026-08-14</dc:date>
    <dc:subject>Testing</dc:subject>
    <meta name="calibre:series" content="Example Series" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
"""


@pytest.mark.parametrize(
    ("version", "accepted"),
    (
        ("ebook-meta (calibre 9.13.0)", True),
        ("calibre 9.10", True),
        ("ebook-meta (calibre 9.9.105)", False),
        ("calibre 8.16.2", False),
        ("unexpected output", False),
    ),
)
def test_calibre_version_policy_enforces_security_floor(version: str, accepted: bool) -> None:
    error = calibre_version_policy(version)
    assert (error is None) is accepted


def test_calibre_opf_parser_preserves_raw_values_and_provenance() -> None:
    execution_id = EntityId.new()
    observation_id = EntityId.new()

    results = parse_calibre_opf(
        SAMPLE_OPF,
        execution_id=execution_id,
        observation_id=observation_id,
    )

    assert [(result.key, result.value) for result in results] == [
        ("title", "The Example"),
        ("creator:aut", "Ada Author"),
        ("identifier:isbn", "9780000000001"),
        ("language", "en"),
        ("publisher", "Example Press"),
        ("date", "2026-08-14"),
        ("subject", "Testing"),
        ("series", "Example Series"),
        ("series_index", "2"),
    ]
    assert {result.execution_id for result in results} == {execution_id}
    assert {result.target_id for result in results} == {observation_id}


@pytest.mark.parametrize(
    ("data", "message"),
    (
        (b"<not-package />", "unexpected root"),
        (b"<package>", "well-formed"),
        (b"\xff", "valid UTF-8"),
        (
            b"<!DOCTYPE package [<!ENTITY x 'unsafe'>]><package><metadata /></package>",
            "forbidden",
        ),
    ),
)
def test_calibre_opf_parser_rejects_unsafe_or_invalid_xml(data: bytes, message: str) -> None:
    with pytest.raises(CalibreMetadataError, match=message):
        parse_calibre_opf(
            data,
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


def test_calibre_opf_parser_rejects_oversized_documents() -> None:
    with pytest.raises(CalibreMetadataError, match="size limit"):
        parse_calibre_opf(
            b"x" * (MAX_OPF_BYTES + 1),
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


class RecordingRuntime:
    def __init__(self, execution: ToolExecution, opf: bytes) -> None:
        self.command: LocalCommand | None = None
        self.input_identity: str | None = None
        self.config_identity: str | None = None
        self.opf = opf
        artifact = ToolArtifact(
            id=EntityId.new(),
            execution_id=execution.id,
            artifact_type=CALIBRE_OPF_ARTIFACT,
            relative_path="synthetic/metadata.opf",
            size_bytes=len(opf),
            sha256="0" * 64,
        )
        self.outcome = ToolRunOutcome(execution, (artifact,), "", "")

    def execute_local(
        self,
        _descriptor: object,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.command = command
        self.input_identity = input_identity
        self.config_identity = config_identity
        return self.outcome

    def read_artifact_bytes(self, _artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        assert max_bytes == MAX_OPF_BYTES
        return self.opf


def test_analyzer_exposes_only_read_only_command_shape_and_persists_results(
    tmp_path: Path,
) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="ebook-meta (calibre 9.13.0)",
        adapter_version="ebook-meta-opf/1",
        capability=ToolCapability.READ_METADATA,
        input_identity="file-observation:synthetic",
        config_identity=CALIBRE_CONFIG_IDENTITY,
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    repository(engine, ToolExecution).save(execution)
    fake_runtime = RecordingRuntime(execution, SAMPLE_OPF)

    source_root = tmp_path / "media"
    source_file = source_root / "books" / "example.epub"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic ebook")
    stat = source_file.stat()
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path="books/example.epub",
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        observed_at=NOW,
    )

    analyzer = CalibreMetadataAnalyzer(engine, fake_runtime, executable="ebook-meta-test")  # type: ignore[arg-type]
    outcome = analyzer.analyze(source_root, observation)

    assert fake_runtime.command is not None
    assert fake_runtime.command.args == (
        str(source_file.resolve()),
        "--to-opf",
        "metadata.opf",
    )
    assert fake_runtime.command.workspace_environment == {
        "CALIBRE_CONFIG_DIRECTORY": "calibre-config"
    }
    assert fake_runtime.command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"}
    assert fake_runtime.command.outputs[0].artifact_type == CALIBRE_OPF_ARTIFACT
    assert fake_runtime.command.version_policy is calibre_version_policy
    assert fake_runtime.input_identity == f"file-observation:{observation.id}"
    assert fake_runtime.config_identity == CALIBRE_CONFIG_IDENTITY
    assert set(outcome.results) == set(repository(engine, ToolResult).list_all())


def test_analyzer_rejects_changed_source_before_invoking_calibre(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="ebook-meta (calibre 9.13.0)",
        adapter_version="ebook-meta-opf/1",
        capability=ToolCapability.READ_METADATA,
        input_identity="file-observation:synthetic",
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
    )
    fake_runtime = RecordingRuntime(execution, SAMPLE_OPF)
    source_root = tmp_path / "media"
    source_root.mkdir()
    source_file = source_root / "book.epub"
    source_file.write_bytes(b"changed")
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path="book.epub",
        size_bytes=1,
        modified_at=NOW,
        observed_at=NOW,
    )

    analyzer = CalibreMetadataAnalyzer(engine, fake_runtime)  # type: ignore[arg-type]
    with pytest.raises(CalibreMetadataError, match="changed"):
        analyzer.analyze(source_root, observation)
    assert fake_runtime.command is None
