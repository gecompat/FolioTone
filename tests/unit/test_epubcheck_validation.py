import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.adapters.epubcheck import (
    EPUBCHECK_CONFIG_IDENTITY,
    EPUBCHECK_PROVIDER,
    EPUBCHECK_REPORT_ARTIFACT,
    EpubCheckAnalyzer,
    EpubCheckError,
    epubcheck_version_policy,
    parse_epubcheck_report,
)
from foliotone.core import (
    EntityId,
    FileObservation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import (
    JsonValue,
    ToolArtifact,
    ToolExecution,
    ToolProviderDescriptor,
    ToolResult,
)
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("version", "accepted"),
    (
        ("EPUBCheck v5.3.0", True),
        ("EPUBCheck v5.4.1", True),
        ("EPUBCheck v5.2.1", False),
        ("epubcheck 5.3.0", False),
        ("OpenJDK 21.0.12", False),
    ),
)
def test_version_policy_requires_current_epubcheck_json_contract(
    version: str,
    accepted: bool,
) -> None:
    assert (epubcheck_version_policy(version) is None) is accepted


def test_parser_projects_nonconformance_counts_and_codes_without_private_values() -> None:
    execution_id = EntityId.new()
    observation_id = EntityId.new()
    report = _report(
        messages=[
            {"ID": "PKG-006", "severity": "ERROR", "message": "private C:/media/book"},
            {"ID": "PKG-006", "severity": "ERROR", "message": "duplicate private text"},
            {"ID": "RSC-005", "severity": "WARNING", "message": "private title"},
            {"ID": "OPF-001", "severity": "INFO", "message": "private info"},
        ],
        fatal=0,
        error=2,
        warning=1,
        usage=0,
    )

    results = parse_epubcheck_report(
        report,
        execution_id=execution_id,
        observation_id=observation_id,
        expected_filename="book.epub",
        expected_tool_version="EPUBCheck v5.3.0",
    )

    values = {result.key: result.value for result in results}
    assert values == {
        "conformance_status": "NONCONFORMANT",
        "fatal_count": "0",
        "error_count": "2",
        "warning_count": "1",
        "usage_count": "0",
        "info_count": "1",
        "diagnostic.ERROR.PKG-006": "2",
        "diagnostic.WARNING.RSC-005": "1",
        "diagnostic.INFO.OPF-001": "1",
    }
    assert {result.execution_id for result in results} == {execution_id}
    assert {result.target_id for result in results} == {observation_id}
    serialized = " ".join(
        value
        for result in results
        for value in (result.key, result.value, result.explanation or "")
    )
    assert "C:/media" not in serialized
    assert "private title" not in serialized


def test_parser_treats_warnings_and_usage_as_conformant_external_evidence() -> None:
    results = parse_epubcheck_report(
        _report(
            messages=[
                {"ID": "CSS-001", "severity": "WARNING"},
                {"ID": "HTM-001", "severity": "USAGE"},
            ],
            fatal=0,
            error=0,
            warning=1,
            usage=1,
        ),
        execution_id=EntityId.new(),
        observation_id=EntityId.new(),
        expected_filename="book.epub",
        expected_tool_version="EPUBCheck v5.3.0",
    )

    assert next(result.value for result in results if result.key == "conformance_status") == (
        "CONFORMANT"
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda report: report["checker"].update({"filename": "other.epub"}), "filename"),
        (lambda report: report["checker"].update({"checkerVersion": "5.2.1"}), "version"),
        (lambda report: report["checker"].update({"nError": 2}), "inconsistent"),
        (lambda report: report["messages"][0].update({"severity": "UNKNOWN"}), "severity"),
        (lambda report: report["messages"][0].update({"ID": "bad value"}), "message ID"),
    ),
)
def test_parser_rejects_mismatched_or_ambiguous_reports(
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    report: dict[str, object] = _report(
        messages=[{"ID": "PKG-006", "severity": "ERROR"}],
        fatal=0,
        error=1,
        warning=0,
        usage=0,
    )
    mutate(report)

    with pytest.raises(EpubCheckError, match=message):
        parse_epubcheck_report(
            report,  # type: ignore[arg-type]
            execution_id=EntityId.new(),
            observation_id=EntityId.new(),
            expected_filename="book.epub",
            expected_tool_version="EPUBCheck v5.3.0",
        )


class RecordingRuntime:
    def __init__(
        self,
        execution: ToolExecution,
        report: JsonValue,
        *,
        after_call: Callable[[], None] | None = None,
    ) -> None:
        self.calls: list[
            tuple[ToolProviderDescriptor, LocalCommand, str, str | None]
        ] = []
        self._report = report
        self._after_call = after_call
        data = b"synthetic report"
        artifact = ToolArtifact(
            id=EntityId.new(),
            execution_id=execution.id,
            artifact_type=EPUBCHECK_REPORT_ARTIFACT,
            relative_path="synthetic/report.json",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        self._outcome = ToolRunOutcome(execution, (artifact,), "", "")

    def execute_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.calls.append((descriptor, command, input_identity, config_identity))
        if self._after_call is not None:
            self._after_call()
        return self._outcome

    def read_json_artifact(self, artifact: ToolArtifact, *, max_bytes: int) -> JsonValue:
        assert artifact.artifact_type == EPUBCHECK_REPORT_ARTIFACT
        assert max_bytes == 8 * 1024 * 1024
        return self._report


def test_analyzer_uses_fixed_read_only_command_and_persists_evidence(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _execution(observation, exit_code=1)
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(
        execution,
        _report(
            messages=[{"ID": "PKG-006", "severity": "ERROR"}],
            fatal=0,
            error=1,
            warning=0,
            usage=0,
        ),
    )
    jar = tmp_path / "tools" / "epubcheck.jar"

    outcome = EpubCheckAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        java_executable="java-test",
        epubcheck_jar=jar,
    ).analyze(source_root, observation)

    assert len(runtime.calls) == 1
    descriptor, command, input_identity, config_identity = runtime.calls[0]
    assert descriptor == EPUBCHECK_PROVIDER
    assert command.args == (
        "-Djava.awt.headless=true",
        "-Djava.io.tmpdir=.",
        "-jar",
        str(jar.resolve()),
        str(source_file.resolve()),
        "--json",
        "report.json",
        "--locale",
        "en",
    )
    assert command.capability is ToolCapability.STRUCTURAL_VALIDATION
    assert command.version_args == ("-jar", str(jar.resolve()), "--version")
    assert command.timeout_seconds == 120.0
    assert command.accepted_exit_codes == frozenset({0, 1})
    assert command.outputs[0].artifact_type == EPUBCHECK_REPORT_ARTIFACT
    assert command.version_policy is epubcheck_version_policy
    assert input_identity == f"file-observation:{observation.id}"
    assert config_identity == EPUBCHECK_CONFIG_IDENTITY
    assert outcome.conformance_status == "NONCONFORMANT"
    assert set(repository(engine, ToolResult).list_all()) == set(outcome.results)


def test_analyzer_rejects_changed_source_before_importing_report(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _execution(observation, exit_code=0)
    repository(engine, ToolExecution).save(execution)

    def change_source() -> None:
        source_file.write_bytes(b"changed after validation")

    runtime = RecordingRuntime(
        execution,
        _report(messages=[], fatal=0, error=0, warning=0, usage=0),
        after_call=change_source,
    )

    with pytest.raises(EpubCheckError, match="changed"):
        EpubCheckAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert repository(engine, ToolResult).list_all() == []


def test_analyzer_rejects_non_epub_before_invoking_tool(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path="books/book.pdf",
    )
    execution = _execution(observation, exit_code=0)
    runtime = RecordingRuntime(
        execution,
        _report(messages=[], fatal=0, error=0, warning=0, usage=0),
    )

    with pytest.raises(EpubCheckError, match="only EPUB"):
        EpubCheckAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert runtime.calls == []


def _report(
    *,
    messages: list[dict[str, object]],
    fatal: int,
    error: int,
    warning: int,
    usage: int,
) -> dict[str, object]:
    return {
        "messages": messages,
        "checker": {
            "path": "C:/private/media/book.epub",
            "filename": "book.epub",
            "checkerVersion": "5.3.0",
            "nFatal": fatal,
            "nError": error,
            "nWarning": warning,
            "nUsage": usage,
        },
        "publication": {"title": "Private title"},
        "items": [],
    }


def _synthetic_observation(
    tmp_path: Path,
    *,
    relative_path: str = "books/book.epub",
) -> tuple[Path, Path, FileObservation]:
    source_root = tmp_path / "media"
    source_file = source_root.joinpath(*relative_path.split("/"))
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic EPUB")
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


def _execution(observation: FileObservation, *, exit_code: int) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id="epubcheck",
        tool_version="EPUBCheck v5.3.0",
        adapter_version="epubcheck-json/1",
        capability=ToolCapability.STRUCTURAL_VALIDATION,
        input_identity=f"file-observation:{observation.id}",
        config_identity=EPUBCHECK_CONFIG_IDENTITY,
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=exit_code,
    )
