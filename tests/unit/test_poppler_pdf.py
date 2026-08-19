import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

import foliotone.adapters.poppler.pdf as poppler_pdf
from foliotone.adapters.poppler.pdf import (
    MAX_PDF_TEXT_BYTES,
    MAX_PDFINFO_BYTES,
    POPPLER_INFO_CONFIG_IDENTITY,
    POPPLER_INFO_PROVIDER,
    POPPLER_TEXT_ARTIFACT,
    POPPLER_TEXT_CONFIG_IDENTITY,
    POPPLER_TEXT_PROVIDER,
    PopplerPdfAnalyzer,
    PopplerPdfError,
    parse_pdfinfo_output,
    poppler_version_policy,
)
from foliotone.analyzers.ebook import TEXT_FINGERPRINT_KIND, TEXT_NORMALIZATION_PROFILE
from foliotone.core import (
    EntityId,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import ToolArtifact, ToolExecution, ToolProviderDescriptor, ToolResult
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("version", "accepted"),
    (
        ("pdfinfo version 26.07.0", True),
        ("pdftotext version 26.7", True),
        ("pdfinfo version 27.1.2", True),
        ("pdftotext version 26.06.0", False),
        ("pdfinfo version 25.11.0", False),
        ("Poppler 26.07.0", False),
    ),
)
def test_poppler_version_policy_requires_sanitized_current_cli(
    version: str,
    accepted: bool,
) -> None:
    error = poppler_version_policy(version)
    assert (error is None) is accepted


def test_pdfinfo_parser_selects_bounded_raw_evidence_with_provenance() -> None:
    execution_id = EntityId.new()
    observation_id = EntityId.new()

    results = parse_pdfinfo_output(
        _pdfinfo_output(file_size=123),
        execution_id=execution_id,
        observation_id=observation_id,
    )

    assert [(result.key, result.value) for result in results] == [
        ("title", "The Example"),
        ("author", "Ada Author"),
        ("creation_date", "2026-08-14T10:00:00+02:00"),
        ("custom_metadata", "no"),
        ("metadata_stream", "no"),
        ("tagged", "no"),
        ("form", "none"),
        ("javascript", "no"),
        ("page_count", "2"),
        ("encrypted", "no"),
        ("page_size", "595 x 842 pts (A4)"),
        ("page_rotation_degrees", "0"),
        ("file_size_bytes", "123"),
        ("optimized", "no"),
        ("pdf_version", "1.7"),
    ]
    assert {result.execution_id for result in results} == {execution_id}
    assert {result.target_id for result in results} == {observation_id}


@pytest.mark.parametrize(
    ("data", "message"),
    (
        (b"File size: 12 bytes\n", "page count"),
        (b"Pages: many\nFile size: 12 bytes\n", "invalid page count"),
        (b"Pages: 1\nPages: 2\nFile size: 12 bytes\n", "duplicate"),
        (b"Pages: 1\nFile size: many\n", "invalid file size"),
        (b"\xff", "valid UTF-8"),
    ),
)
def test_pdfinfo_parser_rejects_ambiguous_or_invalid_output(
    data: bytes,
    message: str,
) -> None:
    with pytest.raises(PopplerPdfError, match=message):
        parse_pdfinfo_output(
            data,
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


def test_pdfinfo_parser_rejects_oversized_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poppler_pdf, "MAX_PDFINFO_BYTES", 7)

    with pytest.raises(PopplerPdfError, match="size limit"):
        parse_pdfinfo_output(
            b"Pages: 1",
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
        )


class RecordingRuntime:
    def __init__(
        self,
        info_execution: ToolExecution,
        text_execution: ToolExecution,
        *,
        info: bytes,
        text: bytes,
        after_call: Callable[[int], None] | None = None,
    ) -> None:
        self.calls: list[
            tuple[ToolProviderDescriptor, LocalCommand, str, str | None]
        ] = []
        self._after_call = after_call
        self._payloads: dict[str, bytes] = {"STDOUT": info, POPPLER_TEXT_ARTIFACT: text}
        info_artifacts = (
            (_artifact(info_execution, "STDOUT", "synthetic/pdfinfo.txt", info),)
            if info_execution.status is ToolExecutionStatus.SUCCEEDED
            else ()
        )
        text_artifacts = (
            (
                _artifact(
                    text_execution,
                    POPPLER_TEXT_ARTIFACT,
                    "synthetic/content.txt",
                    text,
                ),
            )
            if text_execution.status is ToolExecutionStatus.SUCCEEDED
            else ()
        )
        self._outcomes = [
            ToolRunOutcome(info_execution, info_artifacts, "", ""),
            ToolRunOutcome(text_execution, text_artifacts, "", ""),
        ]

    def execute_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        index = len(self.calls)
        self.calls.append((descriptor, command, input_identity, config_identity))
        outcome = self._outcomes[index]
        if self._after_call is not None:
            self._after_call(index)
        return outcome

    def read_artifact_bytes(self, artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        if artifact.artifact_type == "STDOUT":
            assert max_bytes == MAX_PDFINFO_BYTES
        else:
            assert artifact.artifact_type == POPPLER_TEXT_ARTIFACT
            assert max_bytes == MAX_PDF_TEXT_BYTES
        return self._payloads[artifact.artifact_type]


def test_analyzer_uses_fixed_commands_and_persists_pdf_evidence(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    info_execution = _execution(
        observation,
        capability=ToolCapability.TECHNICAL_METADATA,
        adapter_version="pdfinfo-metadata/1",
        config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        tool_version="pdfinfo version 26.07.0",
    )
    text_execution = _execution(
        observation,
        capability=ToolCapability.EXTRACT_TEXT,
        adapter_version="pdftotext-text/1",
        config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        tool_version="pdftotext version 26.07.0",
    )
    repository(engine, ToolExecution).save(info_execution)
    repository(engine, ToolExecution).save(text_execution)
    runtime = RecordingRuntime(
        info_execution,
        text_execution,
        info=_pdfinfo_output(file_size=observation.size_bytes),
        text=b"  Example\r\nPDF\ttext  ",
    )

    outcome = PopplerPdfAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        pdfinfo_executable="pdfinfo-test",
        pdftotext_executable="pdftotext-test",
    ).analyze(source_root, observation)

    assert len(runtime.calls) == 2
    info_descriptor, info_command, input_identity, info_config = runtime.calls[0]
    assert info_descriptor == POPPLER_INFO_PROVIDER
    assert info_command.args == (
        "-enc",
        "UTF-8",
        "-isodates",
        str(source_file.resolve()),
    )
    assert info_command.capability is ToolCapability.TECHNICAL_METADATA
    assert info_command.version_args == ("-v",)
    assert info_command.environment == {"LC_ALL": "C", "LANG": "C"}
    assert info_command.version_policy is poppler_version_policy
    assert input_identity == f"file-observation:{observation.id}"
    assert info_config == POPPLER_INFO_CONFIG_IDENTITY

    text_descriptor, text_command, input_identity, text_config = runtime.calls[1]
    assert text_descriptor == POPPLER_TEXT_PROVIDER
    assert text_command.args == (
        "-enc",
        "UTF-8",
        "-eol",
        "unix",
        "-nopgbrk",
        "-remove-hyphens",
        "all",
        str(source_file.resolve()),
        "content.txt",
    )
    assert text_command.capability is ToolCapability.EXTRACT_TEXT
    assert text_command.version_args == ("-v",)
    assert text_command.timeout_seconds == 120.0
    assert text_command.outputs[0].artifact_type == POPPLER_TEXT_ARTIFACT
    assert text_command.outputs[0].max_bytes == MAX_PDF_TEXT_BYTES
    assert text_command.version_policy is poppler_version_policy
    assert input_identity == f"file-observation:{observation.id}"
    assert text_config == POPPLER_TEXT_CONFIG_IDENTITY

    assert {result.key for result in outcome.metadata_results} >= {
        "title",
        "page_count",
        "file_size_bytes",
        "pdf_version",
    }
    assert {(result.key, result.value) for result in outcome.text_results} == {
        ("text_status", "TEXT_EXTRACTED"),
        ("normalized_character_count", "16"),
    }
    assert set(outcome.results) == set(repository(engine, ToolResult).list_all())
    assert outcome.fingerprint is not None
    assert repository(engine, Fingerprint).list_all() == [outcome.fingerprint]
    assert outcome.fingerprint.kind == TEXT_FINGERPRINT_KIND
    assert outcome.fingerprint.algorithm_version == TEXT_NORMALIZATION_PROFILE
    assert outcome.fingerprint.target_id == observation.id
    assert outcome.fingerprint.tool_execution_id == text_execution.id
    assert outcome.fingerprint.value == hashlib.sha256(b"Example PDF text").hexdigest()
    assert "Example PDF text" not in {result.value for result in outcome.results}


def test_analyzer_records_no_text_without_fingerprint(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(tmp_path)
    info_execution = _execution(
        observation,
        capability=ToolCapability.TECHNICAL_METADATA,
        adapter_version="pdfinfo-metadata/1",
        config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        tool_version="pdfinfo version 26.07.0",
    )
    text_execution = _execution(
        observation,
        capability=ToolCapability.EXTRACT_TEXT,
        adapter_version="pdftotext-text/1",
        config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        tool_version="pdftotext version 26.07.0",
    )
    repository(engine, ToolExecution).save(info_execution)
    repository(engine, ToolExecution).save(text_execution)
    runtime = RecordingRuntime(
        info_execution,
        text_execution,
        info=_pdfinfo_output(file_size=observation.size_bytes),
        text=b" \n\t",
    )

    outcome = PopplerPdfAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert {(result.key, result.value) for result in outcome.text_results} == {
        ("text_status", "NO_TEXT"),
        ("normalized_character_count", "0"),
    }
    assert outcome.fingerprint is None
    assert repository(engine, Fingerprint).list_all() == []


def test_analyzer_keeps_text_evidence_when_pdfinfo_fails(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(tmp_path)
    info_execution = _execution(
        observation,
        capability=ToolCapability.TECHNICAL_METADATA,
        adapter_version="pdfinfo-metadata/1",
        config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        tool_version="unavailable",
        succeeded=False,
    )
    text_execution = _execution(
        observation,
        capability=ToolCapability.EXTRACT_TEXT,
        adapter_version="pdftotext-text/1",
        config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        tool_version="pdftotext version 26.07.0",
    )
    repository(engine, ToolExecution).save(info_execution)
    repository(engine, ToolExecution).save(text_execution)
    runtime = RecordingRuntime(
        info_execution,
        text_execution,
        info=b"",
        text=b"available text",
    )

    outcome = PopplerPdfAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert len(runtime.calls) == 2
    assert outcome.metadata_results == ()
    assert {(result.key, result.value) for result in outcome.text_results} == {
        ("text_status", "TEXT_EXTRACTED"),
        ("normalized_character_count", "14"),
    }
    assert outcome.fingerprint is not None


def test_analyzer_rejects_changed_source_between_tool_and_import(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    info_execution = _execution(
        observation,
        capability=ToolCapability.TECHNICAL_METADATA,
        adapter_version="pdfinfo-metadata/1",
        config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        tool_version="pdfinfo version 26.07.0",
    )
    text_execution = _execution(
        observation,
        capability=ToolCapability.EXTRACT_TEXT,
        adapter_version="pdftotext-text/1",
        config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        tool_version="pdftotext version 26.07.0",
    )
    repository(engine, ToolExecution).save(info_execution)
    repository(engine, ToolExecution).save(text_execution)

    def change_source(index: int) -> None:
        if index == 0:
            source_file.write_bytes(b"changed after pdfinfo")

    runtime = RecordingRuntime(
        info_execution,
        text_execution,
        info=_pdfinfo_output(file_size=observation.size_bytes),
        text=b"text",
        after_call=change_source,
    )

    with pytest.raises(PopplerPdfError, match="changed"):
        PopplerPdfAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert len(runtime.calls) == 1
    assert repository(engine, ToolResult).list_all() == []


def test_analyzer_rejects_non_pdf_before_invoking_poppler(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path="books/example.epub",
    )
    info_execution = _execution(
        observation,
        capability=ToolCapability.TECHNICAL_METADATA,
        adapter_version="pdfinfo-metadata/1",
        config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        tool_version="pdfinfo version 26.07.0",
    )
    text_execution = _execution(
        observation,
        capability=ToolCapability.EXTRACT_TEXT,
        adapter_version="pdftotext-text/1",
        config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        tool_version="pdftotext version 26.07.0",
    )
    runtime = RecordingRuntime(
        info_execution,
        text_execution,
        info=b"",
        text=b"",
    )

    with pytest.raises(PopplerPdfError, match="only PDF"):
        PopplerPdfAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert runtime.calls == []


def _pdfinfo_output(*, file_size: int) -> bytes:
    return f"""Title:           The Example
Author:          Ada Author
CreationDate:    2026-08-14T10:00:00+02:00
Custom Metadata: no
Metadata Stream: no
Tagged:          no
Form:            none
JavaScript:      no
Pages:           2
Encrypted:       no
Page size:       595 x 842 pts (A4)
Page rot:        0
File size:       {file_size} bytes
Optimized:       no
PDF version:     1.7
Ignored field:   ignored
""".encode()


def _synthetic_observation(
    tmp_path: Path,
    *,
    relative_path: str = "books/example.pdf",
) -> tuple[Path, Path, FileObservation]:
    source_root = tmp_path / "media"
    source_file = source_root.joinpath(*relative_path.split("/"))
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic PDF")
    stat = source_file.stat()
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        observed_at=NOW,
    )
    return source_root, source_file, observation


def _execution(
    observation: FileObservation,
    *,
    capability: ToolCapability,
    adapter_version: str,
    config_identity: str,
    tool_version: str,
    succeeded: bool = True,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id="poppler",
        tool_version=tool_version,
        adapter_version=adapter_version,
        capability=capability,
        input_identity=f"file-observation:{observation.id}",
        config_identity=config_identity,
        started_at=NOW,
        finished_at=NOW,
        status=(
            ToolExecutionStatus.SUCCEEDED if succeeded else ToolExecutionStatus.FAILED
        ),
        exit_code=0 if succeeded else 1,
        error_summary=None if succeeded else "synthetic failure",
    )


def _artifact(
    execution: ToolExecution,
    artifact_type: str,
    relative_path: str,
    data: bytes,
) -> ToolArtifact:
    return ToolArtifact(
        id=EntityId.new(),
        execution_id=execution.id,
        artifact_type=artifact_type,
        relative_path=relative_path,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
