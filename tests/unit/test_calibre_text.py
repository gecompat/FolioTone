import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

import foliotone.adapters.calibre.text as calibre_text
from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.text import (
    CALIBRE_TEXT_ARTIFACT,
    CALIBRE_TEXT_CONFIG_IDENTITY,
    CALIBRE_TEXT_FORMATS,
    CALIBRE_TEXT_PROVIDER,
    CALIBRE_TEXT_SUFFIXES,
    MAX_TEXT_BYTES,
    TEXT_FINGERPRINT_KIND,
    TEXT_NORMALIZATION_PROFILE,
    CalibreTextAnalyzer,
    CalibreTextError,
    normalize_ebook_text,
)
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

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def test_normalization_is_versioned_deterministic_and_preserves_case() -> None:
    source = "\ufeff  \ufb01rst\tLINE\r\nSecond\u00a0word  ".encode()

    normalized = normalize_ebook_text(source)

    expected = "first LINE Second word"
    assert normalized.text == expected
    assert normalized.character_count == len(expected)
    assert normalized.sha256 == hashlib.sha256(expected.encode()).hexdigest()
    assert TEXT_NORMALIZATION_PROFILE.startswith("unicode-nfkc-whitespace-v1+ucd-")


def test_normalization_explicitly_represents_empty_text() -> None:
    normalized = normalize_ebook_text(b" \t\r\n")

    assert normalized.text == ""
    assert normalized.character_count == 0
    assert normalized.sha256 == hashlib.sha256(b"").hexdigest()


def test_normalization_rejects_invalid_utf8() -> None:
    with pytest.raises(CalibreTextError, match="valid UTF-8"):
        normalize_ebook_text(b"\xff")


def test_normalization_rejects_oversized_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibre_text, "MAX_TEXT_BYTES", 4)

    with pytest.raises(CalibreTextError, match="size limit"):
        normalize_ebook_text(b"12345")


class RecordingRuntime:
    def __init__(self, execution: ToolExecution, text: bytes) -> None:
        self.descriptor: ToolProviderDescriptor | None = None
        self.command: LocalCommand | None = None
        self.input_identity: str | None = None
        self.config_identity: str | None = None
        self.read_artifact_calls = 0
        self.text = text
        artifact = ToolArtifact(
            id=EntityId.new(),
            execution_id=execution.id,
            artifact_type=CALIBRE_TEXT_ARTIFACT,
            relative_path="synthetic/content.txt",
            size_bytes=len(text),
            sha256="0" * 64,
        )
        self.outcome = ToolRunOutcome(execution, (artifact,), "", "")

    def execute_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.descriptor = descriptor
        self.command = command
        self.input_identity = input_identity
        self.config_identity = config_identity
        return self.outcome

    def read_artifact_bytes(self, _artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        self.read_artifact_calls += 1
        assert max_bytes == MAX_TEXT_BYTES
        return self.text


@pytest.mark.parametrize(
    "relative_path",
    (
        "books/example.epub",
        "books/example.mobi",
        "books/example.azw",
        "books/example.azw3",
    ),
)
def test_analyzer_uses_fixed_command_and_persists_status_and_fingerprint(
    tmp_path: Path,
    relative_path: str,
) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path=relative_path,
    )
    execution = _successful_execution(observation)
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(execution, b"  Example\r\ntext  ")

    analyzer = CalibreTextAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="ebook-convert-test",
    )
    outcome = analyzer.analyze(source_root, observation)

    assert runtime.descriptor == CALIBRE_TEXT_PROVIDER
    assert CALIBRE_TEXT_PROVIDER.adapter_version == "ebook-convert-text/2"
    assert CALIBRE_TEXT_FORMATS == ("EPUB", "MOBI", "AZW", "AZW3")
    assert CALIBRE_TEXT_SUFFIXES == frozenset(
        {".epub", ".mobi", ".azw", ".azw3"}
    )
    assert runtime.command is not None
    assert runtime.command.args == (
        str(source_file.resolve()),
        "content.txt",
        "--txt-output-formatting=plain",
        "--txt-output-encoding=utf-8",
        "--newline=unix",
        "--max-line-length=0",
    )
    assert runtime.command.capability is ToolCapability.EXTRACT_TEXT
    assert runtime.command.timeout_seconds == 120.0
    assert runtime.command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"}
    assert runtime.command.workspace_environment == {
        "CALIBRE_CONFIG_DIRECTORY": "calibre-config"
    }
    assert runtime.command.outputs[0].artifact_type == CALIBRE_TEXT_ARTIFACT
    assert runtime.command.outputs[0].max_bytes == MAX_TEXT_BYTES
    assert runtime.command.version_policy is calibre_version_policy
    assert runtime.input_identity == f"file-observation:{observation.id}"
    assert runtime.config_identity == CALIBRE_TEXT_CONFIG_IDENTITY
    assert runtime.read_artifact_calls == 1

    assert {(result.key, result.value) for result in outcome.results} == {
        ("text_status", "TEXT_EXTRACTED"),
        ("normalized_character_count", "12"),
    }
    assert set(outcome.results) == set(repository(engine, ToolResult).list_all())
    assert outcome.fingerprint is not None
    assert repository(engine, Fingerprint).list_all() == [outcome.fingerprint]
    assert outcome.fingerprint.target_id == observation.id
    assert outcome.fingerprint.kind == TEXT_FINGERPRINT_KIND
    assert outcome.fingerprint.algorithm == "sha256"
    assert outcome.fingerprint.algorithm_version == TEXT_NORMALIZATION_PROFILE
    assert outcome.fingerprint.tool_execution_id == execution.id
    assert outcome.fingerprint.created_at == NOW
    assert outcome.fingerprint.value == hashlib.sha256(b"Example text").hexdigest()


def test_analyzer_records_no_text_without_creating_a_fingerprint(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(tmp_path)
    execution = _successful_execution(observation)
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(execution, b" \n\t")

    outcome = CalibreTextAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert {(result.key, result.value) for result in outcome.results} == {
        ("text_status", "NO_TEXT"),
        ("normalized_character_count", "0"),
    }
    assert outcome.fingerprint is None
    assert repository(engine, Fingerprint).list_all() == []


def test_analyzer_rejects_changed_source_before_invoking_calibre(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _successful_execution(observation)
    runtime = RecordingRuntime(execution, b"text")
    source_file.write_bytes(b"changed after observation")

    analyzer = CalibreTextAnalyzer(engine, runtime)  # type: ignore[arg-type]
    with pytest.raises(CalibreTextError, match="changed"):
        analyzer.analyze(source_root, observation)
    assert runtime.command is None


@pytest.mark.parametrize("suffix", (".pdf", ".azw4", ".kfx"))
def test_analyzer_rejects_unsupported_format_before_invoking_calibre(
    tmp_path: Path,
    suffix: str,
) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path=f"books/example{suffix}",
    )
    execution = _successful_execution(observation)
    runtime = RecordingRuntime(execution, b"text")

    analyzer = CalibreTextAnalyzer(engine, runtime)  # type: ignore[arg-type]
    with pytest.raises(
        CalibreTextError,
        match="only EPUB, MOBI, AZW, or AZW3",
    ):
        analyzer.analyze(source_root, observation)
    assert runtime.command is None
    assert runtime.read_artifact_calls == 0


def test_failed_conversion_is_not_mislabeled_as_no_text(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path="books/protected.azw3",
    )
    execution = _execution(
        observation,
        status=ToolExecutionStatus.FAILED,
        exit_code=1,
        error_summary="exit code 1",
    )
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(execution, b"")

    outcome = CalibreTextAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert outcome.run.execution.status is ToolExecutionStatus.FAILED
    assert outcome.results == ()
    assert outcome.fingerprint is None
    assert runtime.read_artifact_calls == 0
    assert repository(engine, ToolResult).list_all() == []
    assert repository(engine, Fingerprint).list_all() == []


def _synthetic_observation(
    tmp_path: Path,
    *,
    relative_path: str = "books/example.epub",
) -> tuple[Path, Path, FileObservation]:
    source_root = tmp_path / "media"
    source_file = source_root.joinpath(*relative_path.split("/"))
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic ebook")
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


def _successful_execution(observation: FileObservation) -> ToolExecution:
    return _execution(
        observation,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )


def _execution(
    observation: FileObservation,
    *,
    status: ToolExecutionStatus,
    exit_code: int,
    error_summary: str | None = None,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="ebook-convert.exe (calibre 9.13.0)",
        adapter_version="ebook-convert-text/2",
        capability=ToolCapability.EXTRACT_TEXT,
        input_identity=f"file-observation:{observation.id}",
        config_identity=CALIBRE_TEXT_CONFIG_IDENTITY,
        started_at=NOW,
        finished_at=NOW,
        status=status,
        exit_code=exit_code,
        error_summary=error_summary,
    )
