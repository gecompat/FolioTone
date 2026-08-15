"""Read-only EPUB conformance validation with EPUBCheck JSON evidence."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine

from foliotone.analyzers.ebook import ObservedFileError, resolve_observed_file
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import repository
from foliotone.tooling import (
    JsonValue,
    StructuredOutputError,
    ToolArtifactRequirement,
    ToolProviderDescriptor,
    ToolResult,
    ToolReuseRequest,
)
from foliotone.tooling.runtime import (
    LocalCommand,
    ToolRunOutcome,
    ToolRuntime,
    WorkspaceOutput,
)

MINIMUM_EPUBCHECK_VERSION = (5, 3, 0)
MAX_EPUBCHECK_REPORT_BYTES = 8 * 1024 * 1024
MAX_EPUBCHECK_MESSAGES = 10_000

EPUBCHECK_PROVIDER = ToolProviderDescriptor(
    provider_id="epubcheck",
    display_name="EPUBCheck conformance validation",
    adapter_version="epubcheck-json/1",
    capabilities=frozenset({ToolCapability.STRUCTURAL_VALIDATION}),
)
EPUBCHECK_REPORT_ARTIFACT = "EPUBCHECK_JSON"
EPUBCHECK_CONFIG_IDENTITY = "epubcheck:epub2-epub3:json:locale-en:parser-v1"

_VERSION_PATTERN = re.compile(
    r"\bEPUBCheck\s+v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\b",
    re.IGNORECASE,
)
_CHECKER_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")
_DIAGNOSTIC_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_SEVERITIES = ("FATAL", "ERROR", "WARNING", "USAGE", "INFO")
_COUNT_FIELDS = {
    "FATAL": "nFatal",
    "ERROR": "nError",
    "WARNING": "nWarning",
    "USAGE": "nUsage",
}


class EpubCheckError(RuntimeError):
    """A safe, user-facing EPUBCheck validation failure."""


@dataclass(frozen=True, slots=True)
class EpubCheckOutcome:
    """One auditable EPUBCheck run and its normalized structural evidence."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]

    @property
    def conformance_status(self) -> str | None:
        """Return the normalized verdict when the validation run produced evidence."""
        return next(
            (result.value for result in self.results if result.key == "conformance_status"),
            None,
        )


def epubcheck_version_policy(version_text: str) -> str | None:
    """Require the current JSON-report contract before opening source media."""
    version = _version_tuple(version_text)
    if version is None:
        return "EPUBCheck version is unrecognized; source analysis was not started"
    if version < MINIMUM_EPUBCHECK_VERSION:
        return "EPUBCheck 5.3.0 or newer is required; source analysis was not started"
    return None


class EpubCheckAnalyzer:
    """Run a fixed EPUBCheck JSON validation against one unchanged EPUB observation."""

    def __init__(
        self,
        engine: Engine,
        runtime: ToolRuntime,
        *,
        java_executable: str = "java",
        epubcheck_jar: Path = Path("epubcheck.jar"),
    ) -> None:
        if not java_executable.strip():
            raise ValueError("java_executable must not be empty")
        self._result_repo = repository(engine, ToolResult)
        self._runtime = runtime
        self._java_executable = java_executable
        self._epubcheck_jar = epubcheck_jar.resolve()

    def reuse_request(self, observation: FileObservation) -> ToolReuseRequest | None:
        """Describe exact reusable EPUBCheck evidence after a safe version probe."""
        probe = self._runtime.probe_local(
            EPUBCHECK_PROVIDER,
            LocalCommand(
                executable=self._java_executable,
                args=(),
                capability=ToolCapability.STRUCTURAL_VALIDATION,
                version_args=("-jar", str(self._epubcheck_jar), "--version"),
                version_policy=epubcheck_version_policy,
            ),
        )
        if not probe.usable:
            return None
        return ToolReuseRequest(
            descriptor=EPUBCHECK_PROVIDER,
            capability=ToolCapability.STRUCTURAL_VALIDATION,
            tool_version=probe.tool_version,
            input_identity=f"file-observation:{observation.id}",
            config_identity=EPUBCHECK_CONFIG_IDENTITY,
            required_artifacts=(
                ToolArtifactRequirement(
                    EPUBCHECK_REPORT_ARTIFACT,
                    MAX_EPUBCHECK_REPORT_BYTES,
                ),
            ),
        )

    def analyze(self, source_root: Path, observation: FileObservation) -> EpubCheckOutcome:
        """Validate one unchanged EPUB without exposing caller-controlled tool options."""
        if PurePosixPath(observation.relative_path).suffix.lower() != ".epub":
            raise EpubCheckError("EPUBCheck validation accepts only EPUB files")

        source_file = self._source_file(source_root, observation)
        run = self._runtime.execute_local(
            EPUBCHECK_PROVIDER,
            LocalCommand(
                executable=self._java_executable,
                args=(
                    "-Djava.awt.headless=true",
                    "-Djava.io.tmpdir=.",
                    "-jar",
                    str(self._epubcheck_jar),
                    str(source_file),
                    "--json",
                    "report.json",
                    "--locale",
                    "en",
                ),
                capability=ToolCapability.STRUCTURAL_VALIDATION,
                version_args=("-jar", str(self._epubcheck_jar), "--version"),
                timeout_seconds=120.0,
                outputs=(
                    WorkspaceOutput(
                        artifact_type=EPUBCHECK_REPORT_ARTIFACT,
                        relative_path="report.json",
                        max_bytes=MAX_EPUBCHECK_REPORT_BYTES,
                    ),
                ),
                version_policy=epubcheck_version_policy,
                accepted_exit_codes=frozenset({0, 1}),
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=EPUBCHECK_CONFIG_IDENTITY,
        )

        results: tuple[ToolResult, ...] = ()
        if run.execution.status is ToolExecutionStatus.SUCCEEDED:
            self._source_file(source_root, observation)
            report = self._read_report(run)
            results = parse_epubcheck_report(
                report,
                execution_id=run.execution.id,
                observation_id=observation.id,
                expected_filename=source_file.name,
                expected_tool_version=run.execution.tool_version,
            )
            for result in results:
                self._result_repo.save(result)

        return EpubCheckOutcome(run=run, results=results)

    @staticmethod
    def _source_file(source_root: Path, observation: FileObservation) -> Path:
        try:
            return resolve_observed_file(source_root, observation)
        except ObservedFileError as error:
            raise EpubCheckError(str(error)) from error

    def _read_report(self, run: ToolRunOutcome) -> JsonValue:
        artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == EPUBCHECK_REPORT_ARTIFACT
        )
        if len(artifacts) != 1:
            raise EpubCheckError("EPUBCheck did not produce exactly one JSON report artifact")
        try:
            return self._runtime.read_json_artifact(
                artifacts[0],
                max_bytes=MAX_EPUBCHECK_REPORT_BYTES,
            )
        except StructuredOutputError as error:
            raise EpubCheckError("EPUBCheck JSON report validation failed") from error


def parse_epubcheck_report(
    report: JsonValue,
    *,
    execution_id: EntityId,
    observation_id: EntityId,
    expected_filename: str,
    expected_tool_version: str,
) -> tuple[ToolResult, ...]:
    """Project bounded EPUBCheck counts and diagnostic codes without private paths."""
    root = _require_object(report, "EPUBCheck report")
    checker = _require_object(root.get("checker"), "EPUBCheck checker")
    messages = _require_array(root.get("messages"), "EPUBCheck messages")
    if len(messages) > MAX_EPUBCHECK_MESSAGES:
        raise EpubCheckError("EPUBCheck report contains too many messages")

    filename = _require_string(checker.get("filename"), "checker filename")
    if filename != expected_filename:
        raise EpubCheckError("EPUBCheck report filename does not match the source observation")

    reported_version = _require_string(checker.get("checkerVersion"), "checker version")
    if _CHECKER_VERSION_PATTERN.fullmatch(reported_version) is None:
        raise EpubCheckError("EPUBCheck report contains an invalid checker version")
    expected_version = _version_tuple(expected_tool_version)
    if expected_version is None or reported_version != ".".join(map(str, expected_version)):
        raise EpubCheckError("EPUBCheck report version does not match the executed tool")

    declared_counts = {
        severity: _require_count(checker.get(field), f"checker {field}")
        for severity, field in _COUNT_FIELDS.items()
    }
    severity_counts: Counter[str] = Counter()
    diagnostics: Counter[tuple[str, str]] = Counter()
    for index, raw_message in enumerate(messages):
        message = _require_object(raw_message, f"EPUBCheck message {index}")
        severity = _require_string(message.get("severity"), "message severity")
        if severity not in _SEVERITIES:
            raise EpubCheckError("EPUBCheck report contains an unknown message severity")
        diagnostic_id = _require_string(message.get("ID"), "message ID")
        if _DIAGNOSTIC_ID_PATTERN.fullmatch(diagnostic_id) is None:
            raise EpubCheckError("EPUBCheck report contains an invalid message ID")
        severity_counts[severity] += 1
        diagnostics[(severity, diagnostic_id)] += 1

    for severity, declared in declared_counts.items():
        if severity_counts[severity] != declared:
            raise EpubCheckError("EPUBCheck report message counts are inconsistent")

    result_values: list[tuple[str, str, str | None]] = [
        (
            "conformance_status",
            (
                "CONFORMANT"
                if declared_counts["FATAL"] == 0 and declared_counts["ERROR"] == 0
                else "NONCONFORMANT"
            ),
            (
                "EPUBCheck verdict projected from fatal and error counts; external "
                "evidence, not canonical truth."
            ),
        ),
        ("fatal_count", str(declared_counts["FATAL"]), None),
        ("error_count", str(declared_counts["ERROR"]), None),
        ("warning_count", str(declared_counts["WARNING"]), None),
        ("usage_count", str(declared_counts["USAGE"]), None),
        ("info_count", str(severity_counts["INFO"]), None),
    ]
    severity_order = {severity: index for index, severity in enumerate(_SEVERITIES)}
    for (severity, diagnostic_id), count in sorted(
        diagnostics.items(),
        key=lambda item: (severity_order[item[0][0]], item[0][1]),
    ):
        result_values.append(
            (
                f"diagnostic.{severity}.{diagnostic_id}",
                str(count),
                (
                    "Count projected from the bounded EPUBCheck JSON report without "
                    "message text or local paths."
                ),
            )
        )

    return tuple(
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type="epub_structural_validation",
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key=key,
            value=value,
            explanation=explanation,
        )
        for key, value, explanation in result_values
    )


def _version_tuple(version_text: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.search(version_text)
    if match is None:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def _require_object(value: JsonValue | None, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise EpubCheckError(f"{label} must be a JSON object")
    return value


def _require_array(value: JsonValue | None, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise EpubCheckError(f"{label} must be a JSON array")
    return value


def _require_string(value: JsonValue | None, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise EpubCheckError(f"{label} must be a bounded non-empty string")
    return value


def _require_count(value: JsonValue | None, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EpubCheckError(f"{label} must be a bounded non-negative integer")
    if not 0 <= value <= MAX_EPUBCHECK_MESSAGES:
        raise EpubCheckError(f"{label} must be a bounded non-negative integer")
    return value
