"""Read-only calibre EPUB text extraction with a FolioTone-owned fingerprint."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine

from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import repository
from foliotone.tooling import ToolProviderDescriptor, ToolResult
from foliotone.tooling.runtime import (
    LocalCommand,
    ToolRunOutcome,
    ToolRuntime,
    WorkspaceOutput,
)
from foliotone.tooling.structured import StructuredOutputError

from .common import CalibreAdapterError, calibre_version_policy, validated_observed_file

CALIBRE_TEXT_PROVIDER = ToolProviderDescriptor(
    provider_id="calibre",
    display_name="calibre ebook-convert text extraction",
    adapter_version="ebook-convert-text/1",
    capabilities=frozenset({ToolCapability.EXTRACT_TEXT}),
)
CALIBRE_TEXT_ARTIFACT = "CALIBRE_TEXT"
TEXT_FINGERPRINT_KIND = "EBOOK_NORMALIZED_TEXT"
TEXT_NORMALIZATION_PROFILE = (
    f"unicode-nfkc-whitespace-v1+ucd-{unicodedata.unidata_version}"
)
CALIBRE_TEXT_CONFIG_IDENTITY = (
    "ebook-convert:txt:plain:utf-8:unix:max-line-length-0:"
    f"{TEXT_NORMALIZATION_PROFILE}"
)
MAX_TEXT_BYTES = 64 * 1024 * 1024


class CalibreTextError(RuntimeError):
    """A safe, user-facing calibre text-analysis failure."""


@dataclass(frozen=True, slots=True)
class NormalizedEbookText:
    """Bounded normalized text plus its deterministic SHA-256."""

    text: str
    sha256: str

    @property
    def character_count(self) -> int:
        """Return the number of Unicode code points after normalization."""
        return len(self.text)


@dataclass(frozen=True, slots=True)
class CalibreTextOutcome:
    """Auditable extraction, status results, and optional text fingerprint."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]
    fingerprint: Fingerprint | None


class CalibreTextAnalyzer:
    """Extract plain EPUB text and persist a versioned normalized fingerprint."""

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

    def analyze(
        self,
        source_root: Path,
        observation: FileObservation,
    ) -> CalibreTextOutcome:
        """Analyze one unchanged EPUB without exposing conversion options to callers."""
        if PurePosixPath(observation.relative_path).suffix.lower() != ".epub":
            raise CalibreTextError("calibre text analysis currently accepts only EPUB files")
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
        if not normalized.text:
            return None
        finished_at = run.execution.finished_at
        if finished_at is None:
            raise CalibreTextError("successful calibre execution has no completion time")
        return Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            kind=TEXT_FINGERPRINT_KIND,
            algorithm="sha256",
            algorithm_version=TEXT_NORMALIZATION_PROFILE,
            value=normalized.sha256,
            created_at=finished_at,
            tool_execution_id=run.execution.id,
        )


def normalize_ebook_text(data: bytes) -> NormalizedEbookText:
    """Decode bounded UTF-8, apply NFKC, and collapse Unicode whitespace."""
    if len(data) > MAX_TEXT_BYTES:
        raise CalibreTextError("calibre text exceeds the configured size limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CalibreTextError("calibre text is not valid UTF-8") from error
    normalized = " ".join(unicodedata.normalize("NFKC", text).split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return NormalizedEbookText(text=normalized, sha256=digest)
