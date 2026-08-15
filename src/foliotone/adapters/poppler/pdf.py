"""Read-only Poppler PDF metadata, page, and text analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine

from foliotone.analyzers.ebook import (
    DEFAULT_MAX_EBOOK_TEXT_BYTES,
    TEXT_NORMALIZATION_PROFILE,
    EbookTextError,
    ObservedFileError,
    build_normalized_text_fingerprint,
    normalize_ebook_text,
    resolve_observed_file,
)
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

MINIMUM_POPPLER_VERSION = (26, 7, 0)
MAX_PDFINFO_BYTES = 1024 * 1024
MAX_PDFINFO_RESULTS = 32
MAX_PDFINFO_VALUE_CHARS = 4096
MAX_PDF_TEXT_BYTES = DEFAULT_MAX_EBOOK_TEXT_BYTES

POPPLER_INFO_PROVIDER = ToolProviderDescriptor(
    provider_id="poppler",
    display_name="Poppler pdfinfo PDF inspection",
    adapter_version="pdfinfo-metadata/1",
    capabilities=frozenset({ToolCapability.TECHNICAL_METADATA}),
)
POPPLER_TEXT_PROVIDER = ToolProviderDescriptor(
    provider_id="poppler",
    display_name="Poppler pdftotext extraction",
    adapter_version="pdftotext-text/1",
    capabilities=frozenset({ToolCapability.EXTRACT_TEXT}),
)
POPPLER_TEXT_ARTIFACT = "POPPLER_TEXT"
POPPLER_INFO_CONFIG_IDENTITY = "pdfinfo:utf-8:isodates:parser-v1"
POPPLER_TEXT_CONFIG_IDENTITY = (
    "pdftotext:utf-8:unix:no-page-breaks:remove-hyphens-all:"
    f"{TEXT_NORMALIZATION_PROFILE}"
)

_VERSION_PATTERN = re.compile(
    r"\b(?:pdfinfo|pdftotext)\s+version\s+"
    r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?",
    re.IGNORECASE,
)
_INTEGER_PATTERN = re.compile(r"\d+")
_FILE_SIZE_PATTERN = re.compile(r"(?P<size>\d+)\s+bytes", re.IGNORECASE)
_INFO_FIELDS = {
    "Title": "title",
    "Subject": "subject",
    "Keywords": "keywords",
    "Author": "author",
    "Creator": "creator",
    "Producer": "producer",
    "CreationDate": "creation_date",
    "ModDate": "modification_date",
    "Custom Metadata": "custom_metadata",
    "Metadata Stream": "metadata_stream",
    "Tagged": "tagged",
    "UserProperties": "user_properties",
    "Suspects": "suspects",
    "Form": "form",
    "JavaScript": "javascript",
    "Pages": "page_count",
    "Encrypted": "encrypted",
    "Page size": "page_size",
    "Page rot": "page_rotation_degrees",
    "File size": "file_size_bytes",
    "Optimized": "optimized",
    "PDF version": "pdf_version",
    "PDF subtype": "pdf_subtype",
}


class PopplerPdfError(RuntimeError):
    """A safe, user-facing Poppler PDF-analysis failure."""


@dataclass(frozen=True, slots=True)
class PopplerPdfOutcome:
    """Two auditable Poppler runs plus their persisted PDF Evidence."""

    info_run: ToolRunOutcome
    text_run: ToolRunOutcome
    metadata_results: tuple[ToolResult, ...]
    text_results: tuple[ToolResult, ...]
    fingerprint: Fingerprint | None

    @property
    def results(self) -> tuple[ToolResult, ...]:
        """Return metadata and text results in execution order."""
        return self.metadata_results + self.text_results


def poppler_version_policy(version_text: str) -> str | None:
    """Require output sanitization and explicit hyphen handling before PDF access."""
    match = _VERSION_PATTERN.search(version_text)
    if match is None:
        return "Poppler version is unrecognized; source analysis was not started"
    version = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )
    if version < MINIMUM_POPPLER_VERSION:
        return "Poppler 26.07.0 or newer is required; source analysis was not started"
    return None


class PopplerPdfAnalyzer:
    """Run fixed ``pdfinfo`` and ``pdftotext`` commands against one PDF observation."""

    def __init__(
        self,
        engine: Engine,
        runtime: ToolRuntime,
        *,
        pdfinfo_executable: str = "pdfinfo",
        pdftotext_executable: str = "pdftotext",
    ) -> None:
        if not pdfinfo_executable.strip():
            raise ValueError("pdfinfo_executable must not be empty")
        if not pdftotext_executable.strip():
            raise ValueError("pdftotext_executable must not be empty")
        self._result_repo = repository(engine, ToolResult)
        self._fingerprint_repo = repository(engine, Fingerprint)
        self._runtime = runtime
        self._pdfinfo_executable = pdfinfo_executable
        self._pdftotext_executable = pdftotext_executable

    def reuse_requests(
        self,
        observation: FileObservation,
    ) -> tuple[ToolReuseRequest, ToolReuseRequest] | None:
        """Describe the atomic pair of exact reusable Poppler executions."""
        info_probe = self._runtime.probe_local(
            POPPLER_INFO_PROVIDER,
            LocalCommand(
                executable=self._pdfinfo_executable,
                args=(),
                capability=ToolCapability.TECHNICAL_METADATA,
                version_args=("-v",),
                environment={"LC_ALL": "C", "LANG": "C"},
                version_policy=poppler_version_policy,
            ),
        )
        text_probe = self._runtime.probe_local(
            POPPLER_TEXT_PROVIDER,
            LocalCommand(
                executable=self._pdftotext_executable,
                args=(),
                capability=ToolCapability.EXTRACT_TEXT,
                version_args=("-v",),
                environment={"LC_ALL": "C", "LANG": "C"},
                version_policy=poppler_version_policy,
            ),
        )
        if not info_probe.usable or not text_probe.usable:
            return None
        input_identity = f"file-observation:{observation.id}"
        return (
            ToolReuseRequest(
                descriptor=POPPLER_INFO_PROVIDER,
                capability=ToolCapability.TECHNICAL_METADATA,
                tool_version=info_probe.tool_version,
                input_identity=input_identity,
                config_identity=POPPLER_INFO_CONFIG_IDENTITY,
                required_artifacts=(
                    ToolArtifactRequirement("STDOUT", MAX_PDFINFO_BYTES),
                ),
            ),
            ToolReuseRequest(
                descriptor=POPPLER_TEXT_PROVIDER,
                capability=ToolCapability.EXTRACT_TEXT,
                tool_version=text_probe.tool_version,
                input_identity=input_identity,
                config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
                required_artifacts=(
                    ToolArtifactRequirement(POPPLER_TEXT_ARTIFACT, MAX_PDF_TEXT_BYTES),
                ),
            ),
        )

    def analyze(self, source_root: Path, observation: FileObservation) -> PopplerPdfOutcome:
        """Analyze one unchanged PDF without exposing passwords, OCR, or write options."""
        if PurePosixPath(observation.relative_path).suffix.lower() != ".pdf":
            raise PopplerPdfError("Poppler PDF analysis accepts only PDF files")

        source_file = self._source_file(source_root, observation)
        info_run = self._runtime.execute_local(
            POPPLER_INFO_PROVIDER,
            LocalCommand(
                executable=self._pdfinfo_executable,
                args=("-enc", "UTF-8", "-isodates", str(source_file)),
                capability=ToolCapability.TECHNICAL_METADATA,
                version_args=("-v",),
                environment={"LC_ALL": "C", "LANG": "C"},
                version_policy=poppler_version_policy,
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=POPPLER_INFO_CONFIG_IDENTITY,
        )

        metadata_results: tuple[ToolResult, ...] = ()
        if info_run.execution.status is ToolExecutionStatus.SUCCEEDED:
            self._source_file(source_root, observation)
            data = self._read_stdout(info_run)
            metadata_results = parse_pdfinfo_output(
                data,
                execution_id=info_run.execution.id,
                observation_id=observation.id,
            )
            self._verify_reported_file_size(metadata_results, observation)
            for result in metadata_results:
                self._result_repo.save(result)

        source_file = self._source_file(source_root, observation)
        text_run = self._runtime.execute_local(
            POPPLER_TEXT_PROVIDER,
            LocalCommand(
                executable=self._pdftotext_executable,
                args=(
                    "-enc",
                    "UTF-8",
                    "-eol",
                    "unix",
                    "-nopgbrk",
                    "-remove-hyphens",
                    "all",
                    str(source_file),
                    "content.txt",
                ),
                capability=ToolCapability.EXTRACT_TEXT,
                version_args=("-v",),
                timeout_seconds=120.0,
                environment={"LC_ALL": "C", "LANG": "C"},
                outputs=(
                    WorkspaceOutput(
                        artifact_type=POPPLER_TEXT_ARTIFACT,
                        relative_path="content.txt",
                        max_bytes=MAX_PDF_TEXT_BYTES,
                    ),
                ),
                version_policy=poppler_version_policy,
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=POPPLER_TEXT_CONFIG_IDENTITY,
        )

        text_results: tuple[ToolResult, ...] = ()
        fingerprint: Fingerprint | None = None
        if text_run.execution.status is ToolExecutionStatus.SUCCEEDED:
            self._source_file(source_root, observation)
            data = self._read_text_artifact(text_run)
            try:
                normalized = normalize_ebook_text(data, max_bytes=MAX_PDF_TEXT_BYTES)
                fingerprint = build_normalized_text_fingerprint(
                    normalized,
                    observation,
                    text_run.execution,
                )
            except EbookTextError as error:
                raise PopplerPdfError(str(error)) from error
            text_results = (
                ToolResult(
                    id=EntityId.new(),
                    execution_id=text_run.execution.id,
                    result_type="poppler_pdf_text_analysis",
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    key="text_status",
                    value="TEXT_EXTRACTED" if normalized.text else "NO_TEXT",
                ),
                ToolResult(
                    id=EntityId.new(),
                    execution_id=text_run.execution.id,
                    result_type="poppler_pdf_text_analysis",
                    target_kind=EntityKind.FILE_OBSERVATION,
                    target_id=observation.id,
                    key="normalized_character_count",
                    value=str(normalized.character_count),
                ),
            )
            for result in text_results:
                self._result_repo.save(result)
            if fingerprint is not None:
                self._fingerprint_repo.save(fingerprint)

        return PopplerPdfOutcome(
            info_run=info_run,
            text_run=text_run,
            metadata_results=metadata_results,
            text_results=text_results,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _source_file(source_root: Path, observation: FileObservation) -> Path:
        try:
            return resolve_observed_file(source_root, observation)
        except ObservedFileError as error:
            raise PopplerPdfError(str(error)) from error

    def _read_stdout(self, run: ToolRunOutcome) -> bytes:
        artifacts = tuple(
            artifact for artifact in run.artifacts if artifact.artifact_type == "STDOUT"
        )
        if len(artifacts) != 1:
            raise PopplerPdfError("pdfinfo did not produce exactly one stdout artifact")
        try:
            return self._runtime.read_artifact_bytes(
                artifacts[0],
                max_bytes=MAX_PDFINFO_BYTES,
            )
        except StructuredOutputError as error:
            raise PopplerPdfError("pdfinfo stdout artifact validation failed") from error

    def _read_text_artifact(self, run: ToolRunOutcome) -> bytes:
        artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == POPPLER_TEXT_ARTIFACT
        )
        if len(artifacts) != 1:
            raise PopplerPdfError("pdftotext did not produce exactly one text artifact")
        try:
            return self._runtime.read_artifact_bytes(
                artifacts[0],
                max_bytes=MAX_PDF_TEXT_BYTES,
            )
        except StructuredOutputError as error:
            raise PopplerPdfError("Poppler text artifact validation failed") from error

    @staticmethod
    def _verify_reported_file_size(
        results: tuple[ToolResult, ...],
        observation: FileObservation,
    ) -> None:
        reported = next(
            (result.value for result in results if result.key == "file_size_bytes"),
            None,
        )
        if reported is None:
            raise PopplerPdfError("pdfinfo output does not contain a file size")
        if int(reported) != observation.size_bytes:
            raise PopplerPdfError("pdfinfo file size does not match the recorded observation")


def parse_pdfinfo_output(
    data: bytes,
    *,
    execution_id: EntityId,
    observation_id: EntityId,
) -> tuple[ToolResult, ...]:
    """Parse a strict allowlist from bounded, sanitized Poppler ``pdfinfo`` output."""
    if len(data) > MAX_PDFINFO_BYTES:
        raise PopplerPdfError("pdfinfo output exceeds the configured size limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise PopplerPdfError("pdfinfo output is not valid UTF-8") from error

    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        label, separator, raw_value = line.partition(":")
        if not separator:
            continue
        key = _INFO_FIELDS.get(label.strip())
        if key is None:
            continue
        if key in seen:
            raise PopplerPdfError(f"pdfinfo output contains duplicate field: {key}")
        seen.add(key)
        value = raw_value.strip()
        if key == "page_count":
            if _INTEGER_PATTERN.fullmatch(value) is None:
                raise PopplerPdfError("pdfinfo output contains an invalid page count")
        elif key == "file_size_bytes":
            match = _FILE_SIZE_PATTERN.fullmatch(value)
            if match is None:
                raise PopplerPdfError("pdfinfo output contains an invalid file size")
            value = match.group("size")
        if not value:
            continue
        if len(value) > MAX_PDFINFO_VALUE_CHARS:
            raise PopplerPdfError("pdfinfo output contains an oversized field value")
        if len(values) >= MAX_PDFINFO_RESULTS:
            raise PopplerPdfError("pdfinfo output contains too many selected fields")
        values.append((key, value))

    if "page_count" not in seen:
        raise PopplerPdfError("pdfinfo output does not contain a page count")
    return tuple(
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type="poppler_pdf_metadata",
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key=key,
            value=value,
        )
        for key, value in values
    )
