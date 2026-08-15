"""Read-only calibre cover extraction with FolioTone-owned visual Evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine

from foliotone.analyzers.ebook import (
    COVER_FINGERPRINT_PROFILE,
    DEFAULT_MAX_EBOOK_COVER_BYTES,
    EbookCoverError,
    build_cover_fingerprint,
    fingerprint_ebook_cover,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.index import stream_sha256
from foliotone.persistence import repository
from foliotone.tooling import (
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
from foliotone.tooling.structured import JsonValue, StructuredOutputError

from .common import CalibreAdapterError, calibre_version_policy, validated_observed_file

CALIBRE_COVER_FORMATS = ("EPUB", "MOBI", "AZW", "AZW3")
CALIBRE_COVER_SUFFIXES = frozenset(
    f".{format_name.lower()}" for format_name in CALIBRE_COVER_FORMATS
)
CALIBRE_COVER_PROVIDER = ToolProviderDescriptor(
    provider_id="calibre",
    display_name="calibre embedded-cover extraction",
    adapter_version="calibre-debug-cover/1",
    capabilities=frozenset({ToolCapability.FINGERPRINT}),
)
CALIBRE_COVER_ARTIFACT = "CALIBRE_EMBEDDED_COVER"
CALIBRE_COVER_RESULT_ARTIFACT = "CALIBRE_COVER_RESULT"
CALIBRE_COVER_RESULT_TYPE = "calibre_cover_analysis"
CALIBRE_COVER_CONFIG_IDENTITY = (
    "calibre-debug:exec-file:staged-source:embedded-cover-only:v1:"
    f"{COVER_FINGERPRINT_PROFILE}"
)
MAX_COVER_BYTES = DEFAULT_MAX_EBOOK_COVER_BYTES
MAX_COVER_RESULT_BYTES = 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class CalibreCoverError(RuntimeError):
    """A safe, user-facing calibre cover-analysis failure."""


@dataclass(frozen=True, slots=True)
class CalibreCoverOutcome:
    """Auditable extraction, cover facts, and optional perceptual fingerprint."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]
    fingerprint: Fingerprint | None


@dataclass(frozen=True, slots=True)
class CalibreCoverExtractionResult:
    """Strict bounded result emitted by the private calibre cover helper."""

    status: str
    source_sha256: str
    cover_bytes: int


class CalibreCoverAnalyzer:
    """Extract embedded covers through a fixed, source-isolated calibre script."""

    def __init__(
        self,
        engine: Engine,
        runtime: ToolRuntime,
        *,
        executable: str = "calibre-debug",
        script_path: Path | None = None,
    ) -> None:
        if not executable.strip():
            raise ValueError("executable must not be empty")
        script = script_path or Path(__file__).parent / "scripts" / "extract_cover.py"
        try:
            resolved_script = script.resolve(strict=True)
        except OSError as error:
            raise ValueError("calibre cover helper script is unavailable") from error
        if not resolved_script.is_file():
            raise ValueError("calibre cover helper script is unavailable")
        self._result_repo = repository(engine, ToolResult)
        self._fingerprint_repo = repository(engine, Fingerprint)
        self._runtime = runtime
        self._executable = executable
        self._script_path = resolved_script

    def reuse_request(self, observation: FileObservation) -> ToolReuseRequest | None:
        """Describe exact reusable cover evidence after a safe version probe."""
        probe = self._runtime.probe_local(
            CALIBRE_COVER_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(),
                capability=ToolCapability.FINGERPRINT,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                version_policy=calibre_version_policy,
            ),
        )
        if not probe.usable:
            return None
        return ToolReuseRequest(
            descriptor=CALIBRE_COVER_PROVIDER,
            capability=ToolCapability.FINGERPRINT,
            tool_version=probe.tool_version,
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_COVER_CONFIG_IDENTITY,
            required_artifacts=(
                ToolArtifactRequirement(
                    CALIBRE_COVER_RESULT_ARTIFACT,
                    MAX_COVER_RESULT_BYTES,
                ),
            ),
        )

    def analyze(
        self,
        source_root: Path,
        observation: FileObservation,
    ) -> CalibreCoverOutcome:
        """Extract one unchanged e-book's embedded cover without rendering pages."""
        suffix = PurePosixPath(observation.relative_path).suffix.lower()
        if suffix not in CALIBRE_COVER_SUFFIXES:
            raise CalibreCoverError(
                "calibre cover analysis accepts only EPUB, MOBI, AZW, or AZW3 files"
            )
        try:
            source_file = validated_observed_file(source_root, observation)
        except CalibreAdapterError as error:
            raise CalibreCoverError(str(error)) from error

        run = self._runtime.execute_local(
            CALIBRE_COVER_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(
                    "-e",
                    str(self._script_path),
                    "--",
                    str(source_file),
                    "cover.bin",
                    "cover-result.json",
                    str(observation.size_bytes),
                    str(MAX_COVER_BYTES),
                ),
                capability=ToolCapability.FINGERPRINT,
                timeout_seconds=120.0,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                outputs=(
                    WorkspaceOutput(
                        artifact_type=CALIBRE_COVER_RESULT_ARTIFACT,
                        relative_path="cover-result.json",
                        max_bytes=MAX_COVER_RESULT_BYTES,
                    ),
                    WorkspaceOutput(
                        artifact_type=CALIBRE_COVER_ARTIFACT,
                        relative_path="cover.bin",
                        required=False,
                        max_bytes=MAX_COVER_BYTES,
                    ),
                ),
                version_policy=calibre_version_policy,
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_COVER_CONFIG_IDENTITY,
        )
        if run.execution.status is not ToolExecutionStatus.SUCCEEDED:
            return CalibreCoverOutcome(run=run, results=(), fingerprint=None)

        extraction = self._read_extraction_result(run)
        self._verify_source_unchanged(source_root, observation, extraction.source_sha256)
        cover_artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == CALIBRE_COVER_ARTIFACT
        )
        if extraction.status == "NO_EMBEDDED_COVER":
            if extraction.cover_bytes != 0 or cover_artifacts:
                raise CalibreCoverError("calibre cover result is internally inconsistent")
            no_cover_results = (
                self._result(run, observation, "cover_status", extraction.status),
            )
            self._result_repo.save(no_cover_results[0])
            return CalibreCoverOutcome(
                run=run,
                results=no_cover_results,
                fingerprint=None,
            )

        if extraction.status != "COVER_EXTRACTED":
            raise CalibreCoverError("calibre cover result contains an unknown status")
        if len(cover_artifacts) != 1:
            raise CalibreCoverError("calibre did not produce exactly one cover artifact")
        if extraction.cover_bytes <= 0 or cover_artifacts[0].size_bytes != extraction.cover_bytes:
            raise CalibreCoverError("calibre cover result is internally inconsistent")
        try:
            data = self._runtime.read_artifact_bytes(
                cover_artifacts[0],
                max_bytes=MAX_COVER_BYTES,
            )
            normalized = fingerprint_ebook_cover(data, max_bytes=MAX_COVER_BYTES)
            fingerprint = build_cover_fingerprint(normalized, observation, run.execution)
        except (StructuredOutputError, EbookCoverError) as error:
            raise CalibreCoverError("calibre cover artifact validation failed") from error

        cover_results = (
            self._result(run, observation, "cover_status", extraction.status),
            self._result(run, observation, "image_format", normalized.image_format),
            self._result(run, observation, "display_width", str(normalized.width)),
            self._result(run, observation, "display_height", str(normalized.height)),
        )
        for result in cover_results:
            self._result_repo.save(result)
        self._fingerprint_repo.save(fingerprint)
        return CalibreCoverOutcome(
            run=run,
            results=cover_results,
            fingerprint=fingerprint,
        )

    def _read_extraction_result(self, run: ToolRunOutcome) -> CalibreCoverExtractionResult:
        artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == CALIBRE_COVER_RESULT_ARTIFACT
        )
        if len(artifacts) != 1:
            raise CalibreCoverError("calibre did not produce exactly one cover result")
        try:
            parsed = self._runtime.read_json_artifact(
                artifacts[0],
                max_bytes=MAX_COVER_RESULT_BYTES,
            )
        except StructuredOutputError as error:
            raise CalibreCoverError("calibre cover result validation failed") from error
        return parse_calibre_cover_result(parsed)

    @staticmethod
    def _verify_source_unchanged(
        source_root: Path,
        observation: FileObservation,
        staged_sha256: str,
    ) -> None:
        try:
            source_file = validated_observed_file(source_root, observation)
        except CalibreAdapterError as error:
            raise CalibreCoverError("source file changed during cover analysis") from error
        if stream_sha256(source_file) != staged_sha256:
            raise CalibreCoverError("source file changed during cover analysis")

    @staticmethod
    def _result(
        run: ToolRunOutcome,
        observation: FileObservation,
        key: str,
        value: str,
    ) -> ToolResult:
        return ToolResult(
            id=EntityId.new(),
            execution_id=run.execution.id,
            result_type=CALIBRE_COVER_RESULT_TYPE,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            key=key,
            value=value,
        )


def parse_calibre_cover_result(value: JsonValue) -> CalibreCoverExtractionResult:
    """Parse the helper's strict result without exposing private source paths."""
    if not isinstance(value, dict) or set(value) != {
        "cover_bytes",
        "source_sha256",
        "status",
    }:
        raise CalibreCoverError("calibre cover result has an unexpected shape")
    status = value["status"]
    source_sha256 = value["source_sha256"]
    cover_bytes = value["cover_bytes"]
    if not isinstance(status, str):
        raise CalibreCoverError("calibre cover result has an invalid status")
    if not isinstance(source_sha256, str) or _SHA256_PATTERN.fullmatch(source_sha256) is None:
        raise CalibreCoverError("calibre cover result has an invalid source digest")
    if isinstance(cover_bytes, bool) or not isinstance(cover_bytes, int) or cover_bytes < 0:
        raise CalibreCoverError("calibre cover result has an invalid byte count")
    return CalibreCoverExtractionResult(
        status=status,
        source_sha256=source_sha256,
        cover_bytes=cover_bytes,
    )
