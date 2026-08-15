"""Read-only calibre e-book text extraction with a FolioTone-owned fingerprint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine

from foliotone.analyzers.ebook import (
    DEFAULT_MAX_EBOOK_TEXT_BYTES,
    TEXT_NORMALIZATION_PROFILE,
    EbookTextError,
    build_normalized_text_fingerprint,
)
from foliotone.analyzers.ebook import TEXT_FINGERPRINT_KIND as TEXT_FINGERPRINT_KIND
from foliotone.analyzers.ebook import NormalizedEbookText as NormalizedEbookText
from foliotone.analyzers.ebook import normalize_ebook_text as normalize_shared_ebook_text
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
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
from foliotone.tooling.structured import StructuredOutputError

from .common import CalibreAdapterError, calibre_version_policy, validated_observed_file

CALIBRE_TEXT_FORMATS = ("EPUB", "MOBI", "AZW", "AZW3")
CALIBRE_TEXT_SUFFIXES = frozenset(
    f".{format_name.lower()}" for format_name in CALIBRE_TEXT_FORMATS
)
CALIBRE_TEXT_PROVIDER = ToolProviderDescriptor(
    provider_id="calibre",
    display_name="calibre ebook-convert text extraction",
    adapter_version="ebook-convert-text/2",
    capabilities=frozenset({ToolCapability.EXTRACT_TEXT}),
)
CALIBRE_TEXT_ARTIFACT = "CALIBRE_TEXT"
CALIBRE_TEXT_CONFIG_IDENTITY = (
    "ebook-convert:epub-mobi-azw-azw3:txt:plain:utf-8:unix:max-line-length-0:"
    f"{TEXT_NORMALIZATION_PROFILE}"
)
MAX_TEXT_BYTES = DEFAULT_MAX_EBOOK_TEXT_BYTES


class CalibreTextError(RuntimeError):
    """A safe, user-facing calibre text-analysis failure."""


@dataclass(frozen=True, slots=True)
class CalibreTextOutcome:
    """Auditable extraction, status results, and optional text fingerprint."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]
    fingerprint: Fingerprint | None


class CalibreTextAnalyzer:
    """Extract supported e-book text and persist a normalized fingerprint."""

    def __init__(
        self,
        engine: Engine,
        runtime: ToolRuntime,
        *,
        executable: str = "ebook-convert",
    ) -> None:
        if not executable.strip():
            raise ValueError("executable must not be empty")
        self._result_repo = repository(engine, ToolResult)
        self._fingerprint_repo = repository(engine, Fingerprint)
        self._runtime = runtime
        self._executable = executable

    def reuse_request(self, observation: FileObservation) -> ToolReuseRequest | None:
        """Describe exact reusable text evidence after a safe version probe."""
        probe = self._runtime.probe_local(
            CALIBRE_TEXT_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(),
                capability=ToolCapability.EXTRACT_TEXT,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                version_policy=calibre_version_policy,
            ),
        )
        if not probe.usable:
            return None
        return ToolReuseRequest(
            descriptor=CALIBRE_TEXT_PROVIDER,
            capability=ToolCapability.EXTRACT_TEXT,
            tool_version=probe.tool_version,
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_TEXT_CONFIG_IDENTITY,
            required_artifacts=(
                ToolArtifactRequirement(CALIBRE_TEXT_ARTIFACT, MAX_TEXT_BYTES),
            ),
        )

    def analyze(
        self,
        source_root: Path,
        observation: FileObservation,
    ) -> CalibreTextOutcome:
        """Analyze one unchanged e-book without exposing options to callers."""
        suffix = PurePosixPath(observation.relative_path).suffix.lower()
        if suffix not in CALIBRE_TEXT_SUFFIXES:
            raise CalibreTextError(
                "calibre text analysis accepts only EPUB, MOBI, AZW, or AZW3 files"
            )
        try:
            source_file = validated_observed_file(source_root, observation)
        except CalibreAdapterError as error:
            raise CalibreTextError(str(error)) from error

        run = self._runtime.execute_local(
            CALIBRE_TEXT_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(
                    str(source_file),
                    "content.txt",
                    "--txt-output-formatting=plain",
                    "--txt-output-encoding=utf-8",
                    "--newline=unix",
                    "--max-line-length=0",
                ),
                capability=ToolCapability.EXTRACT_TEXT,
                timeout_seconds=120.0,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                outputs=(
                    WorkspaceOutput(
                        artifact_type=CALIBRE_TEXT_ARTIFACT,
                        relative_path="content.txt",
                        max_bytes=MAX_TEXT_BYTES,
                    ),
                ),
                version_policy=calibre_version_policy,
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_TEXT_CONFIG_IDENTITY,
        )
        if run.execution.status is not ToolExecutionStatus.SUCCEEDED:
            return CalibreTextOutcome(run=run, results=(), fingerprint=None)

        text_artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == CALIBRE_TEXT_ARTIFACT
        )
        if len(text_artifacts) != 1:
            raise CalibreTextError("calibre did not produce exactly one text artifact")
        try:
            data = self._runtime.read_artifact_bytes(
                text_artifacts[0],
                max_bytes=MAX_TEXT_BYTES,
            )
        except StructuredOutputError as error:
            raise CalibreTextError("calibre text artifact validation failed") from error

        normalized = normalize_ebook_text(data)
        text_status = "TEXT_EXTRACTED" if normalized.text else "NO_TEXT"
        results = (
            ToolResult(
                id=EntityId.new(),
                execution_id=run.execution.id,
                result_type="calibre_text_analysis",
                target_kind=EntityKind.FILE_OBSERVATION,
                target_id=observation.id,
                key="text_status",
                value=text_status,
            ),
            ToolResult(
                id=EntityId.new(),
                execution_id=run.execution.id,
                result_type="calibre_text_analysis",
                target_kind=EntityKind.FILE_OBSERVATION,
                target_id=observation.id,
                key="normalized_character_count",
                value=str(normalized.character_count),
            ),
        )

        fingerprint = self._fingerprint(run, observation, normalized)
        for result in results:
            self._result_repo.save(result)
        if fingerprint is not None:
            self._fingerprint_repo.save(fingerprint)
        return CalibreTextOutcome(run=run, results=results, fingerprint=fingerprint)

    @staticmethod
    def _fingerprint(
        run: ToolRunOutcome,
        observation: FileObservation,
        normalized: NormalizedEbookText,
    ) -> Fingerprint | None:
        try:
            return build_normalized_text_fingerprint(
                normalized,
                observation,
                run.execution,
            )
        except EbookTextError as error:
            raise CalibreTextError(str(error)) from error


def normalize_ebook_text(data: bytes) -> NormalizedEbookText:
    """Apply the shared text contract behind calibre's public error boundary."""
    try:
        return normalize_shared_ebook_text(data, max_bytes=MAX_TEXT_BYTES)
    except EbookTextError as error:
        raise CalibreTextError(str(error)) from error
