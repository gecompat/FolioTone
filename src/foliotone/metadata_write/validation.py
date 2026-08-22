"""Fixed independent validation of one private staged EPUB title output."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Protocol

from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.cover import (
    MAX_COVER_BYTES,
    MAX_COVER_RESULT_BYTES,
    parse_calibre_cover_result,
)
from foliotone.adapters.calibre.metadata import MAX_OPF_BYTES, project_calibre_opf
from foliotone.adapters.calibre.text import MAX_TEXT_BYTES, normalize_ebook_text
from foliotone.adapters.epubcheck.validation import (
    MAX_EPUBCHECK_REPORT_BYTES,
    epubcheck_version_policy,
    parse_epubcheck_report,
)
from foliotone.analyzers.ebook import EbookCoverError, fingerprint_ebook_cover
from foliotone.core import EntityId
from foliotone.metadata_write.contracts import (
    EPUB_TITLE_PATCHER_VERSION,
    EPUB_TITLE_WRITE_PROFILE,
    EpubTitlePackagePatch,
    EpubTitleWritePreflight,
)
from foliotone.metadata_write.staging import (
    EpubTitleStagedFiles,
    EpubTitleStagingError,
    EpubTitleStagingErrorCode,
    build_private_epub3_title_stage,
)
from foliotone.tooling.structured import StructuredOutputError, parse_json_output

EPUB_TITLE_VALIDATION_PROFILE = "epub3-title-staged-validation/v1"
EPUB_TITLE_VERIFIED_STAGE_PROFILE = "epub3-title-verified-private-stage/v1"
EPUB_TITLE_VALIDATOR_SET = (
    "ebook-meta-opf/2+epubcheck-json/1+ebook-convert-text/2+"
    "calibre-debug-cover/1"
)

_PROCESS_OUTPUT_LIMIT = 1024 * 1024
_VERSION_OUTPUT_LIMIT = 64 * 1024
_PROCESS_CHUNK_BYTES = 64 * 1024
_FILE_CHUNK_BYTES = 1024 * 1024
_WINDOWS_REPARSE_POINT = 0x0400
_FIXED_STEPS = frozenset(
    {
        "metadata-input",
        "metadata-output",
        "epubcheck-output",
        "text-input",
        "text-output",
        "cover-input",
        "cover-output",
    }
)


@dataclass(frozen=True, slots=True)
class EpubTitleValidationOutput:
    """One bounded private file expected from a fixed validator command."""

    artifact_type: str
    relative_path: str
    max_bytes: int
    required: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_type, str)
            or not isinstance(self.relative_path, str)
            or isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not isinstance(self.required, bool)
        ):
            raise ValueError("invalid staged validator output")
        normalized = self.relative_path.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not self.artifact_type.strip()
            or not normalized
            or path.is_absolute()
            or PureWindowsPath(normalized).is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or self.max_bytes <= 0
        ):
            raise ValueError("invalid staged validator output")
        object.__setattr__(self, "relative_path", normalized)


@dataclass(frozen=True, slots=True)
class EpubTitleValidationCommand:
    """Internal fixed-command request; paths and arguments are never persisted."""

    step: str
    executable: str
    args: tuple[str, ...] = field(repr=False)
    version_args: tuple[str, ...]
    version_policy: Callable[[str], str | None] = field(repr=False)
    outputs: tuple[EpubTitleValidationOutput, ...]
    accepted_exit_codes: frozenset[int] = frozenset({0})
    timeout_seconds: float = 120.0
    environment: Mapping[str, str] | None = field(default=None, repr=False)
    workspace_environment: Mapping[str, str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.step, str)
            or not isinstance(self.executable, str)
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
        ):
            raise ValueError("invalid staged validator command")
        artifact_types = tuple(output.artifact_type for output in self.outputs)
        if (
            self.step not in _FIXED_STEPS
            or not self.executable.strip()
            or not self.version_args
            or self.timeout_seconds <= 0
            or not self.accepted_exit_codes
            or any(
                isinstance(code, bool) or not isinstance(code, int) or code < 0
                for code in self.accepted_exit_codes
            )
            or len(artifact_types) != len(set(artifact_types))
        ):
            raise ValueError("invalid staged validator command")


@dataclass(frozen=True, slots=True)
class EpubTitleValidationArtifact:
    """Bounded non-persisted bytes returned by the private tool runner."""

    artifact_type: str
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_type, str)
            or not self.artifact_type.strip()
            or not isinstance(self.data, bytes)
        ):
            raise ValueError("invalid staged validation artifact")


@dataclass(frozen=True, slots=True)
class EpubTitleValidationToolOutcome:
    """Successful fixed tool execution with only bounded private artifacts."""

    step: str
    tool_version: str
    artifacts: tuple[EpubTitleValidationArtifact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.step, str) or not isinstance(self.tool_version, str):
            raise ValueError("invalid staged validation outcome")
        artifact_types = tuple(item.artifact_type for item in self.artifacts)
        if (
            self.step not in _FIXED_STEPS
            or not self.tool_version.strip()
            or len(self.tool_version) > 256
            or len(artifact_types) != len(set(artifact_types))
        ):
            raise ValueError("invalid staged validation outcome")

    def artifact(self, artifact_type: str) -> bytes | None:
        matches = tuple(
            item.data for item in self.artifacts if item.artifact_type == artifact_type
        )
        if len(matches) > 1:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        return matches[0] if matches else None


class EpubTitleValidationToolRunner(Protocol):
    """Injected non-persisting runner seam owned by the fixed validator."""

    def run(
        self,
        command: EpubTitleValidationCommand,
        workspace: Path,
    ) -> EpubTitleValidationToolOutcome: ...


@dataclass(frozen=True, slots=True)
class EpubTitleStagedValidation:
    """Path-free evidence that every fixed independent validator agreed."""

    plan_id: EntityId
    input_sha256: str = field(repr=False)
    output_sha256: str = field(repr=False)
    preserved_fields_sha256: str = field(repr=False)
    normalized_text_sha256: str = field(repr=False)
    cover_identity_sha256: str = field(repr=False)
    cover_status: str
    metadata_tool_version: str
    epubcheck_tool_version: str
    text_tool_version: str
    cover_tool_version: str
    validator_set_fingerprint: str = field(repr=False)
    conformance_status: str = "CONFORMANT"
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    validator_set: str = EPUB_TITLE_VALIDATOR_SET
    profile: str = EPUB_TITLE_VALIDATION_PROFILE

    def __post_init__(self) -> None:
        hashes = (
            self.input_sha256,
            self.output_sha256,
            self.preserved_fields_sha256,
            self.normalized_text_sha256,
            self.cover_identity_sha256,
            self.validator_set_fingerprint,
        )
        versions = (
            self.metadata_tool_version,
            self.epubcheck_tool_version,
            self.text_tool_version,
            self.cover_tool_version,
        )
        if (
            not isinstance(self.plan_id, EntityId)
            or self.profile != EPUB_TITLE_VALIDATION_PROFILE
            or self.writer_profile != EPUB_TITLE_WRITE_PROFILE
            or self.patcher_version != EPUB_TITLE_PATCHER_VERSION
            or self.validator_set != EPUB_TITLE_VALIDATOR_SET
            or self.conformance_status != "CONFORMANT"
            or self.cover_status not in {"COVER_EXTRACTED", "NO_EMBEDDED_COVER"}
            or any(not _is_sha256(value) for value in hashes)
            or any(
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 256
                for value in versions
            )
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )


@dataclass(frozen=True, slots=True)
class EpubTitleVerifiedStage:
    """Complete MW02 result; still no Authorization, persistence, or commit."""

    staged_files: EpubTitleStagedFiles
    validation: EpubTitleStagedValidation
    profile: str = EPUB_TITLE_VERIFIED_STAGE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.staged_files, EpubTitleStagedFiles)
            or not isinstance(self.validation, EpubTitleStagedValidation)
            or self.profile != EPUB_TITLE_VERIFIED_STAGE_PROFILE
            or self.staged_files.plan_id != self.validation.plan_id
            or self.staged_files.input_sha256 != self.validation.input_sha256
            or self.staged_files.output_sha256 != self.validation.output_sha256
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )


@dataclass(frozen=True, slots=True)
class _MetadataProjection:
    title: str
    preserved_sha256: str
    tool_version: str


@dataclass(frozen=True, slots=True)
class _TextProjection:
    sha256: str
    character_count: int
    tool_version: str


@dataclass(frozen=True, slots=True)
class _CoverProjection:
    status: str
    identity_sha256: str
    tool_version: str


class FixedEpubTitleStagingValidator:
    """Run the exact calibre and EPUBCheck read-only validation sequence."""

    def __init__(
        self,
        *,
        runner: EpubTitleValidationToolRunner | None = None,
        metadata_executable: str = "ebook-meta",
        text_executable: str = "ebook-convert",
        cover_executable: str = "calibre-debug",
        java_executable: str = "java",
        epubcheck_jar: Path = Path("epubcheck.jar"),
        cover_script: Path | None = None,
    ) -> None:
        executables = (
            metadata_executable,
            text_executable,
            cover_executable,
            java_executable,
        )
        if any(not value.strip() for value in executables):
            raise ValueError("validator executable must not be empty")
        script = cover_script or (
            Path(__file__).parents[1]
            / "adapters"
            / "calibre"
            / "scripts"
            / "extract_cover.py"
        )
        try:
            self._cover_script = script.resolve(strict=True)
        except OSError as error:
            raise ValueError("calibre cover helper script is unavailable") from error
        self._runner = runner or _BoundedLocalValidationRunner()
        self._metadata_executable = metadata_executable
        self._text_executable = text_executable
        self._cover_executable = cover_executable
        self._java_executable = java_executable
        self._epubcheck_jar = epubcheck_jar.resolve()

    def validate(
        self,
        stage: EpubTitleStagedFiles,
        preflight: EpubTitleWritePreflight,
        patch: EpubTitlePackagePatch,
    ) -> EpubTitleStagedValidation:
        """Require read-back agreement while keeping all artifacts private."""
        if (
            not isinstance(stage, EpubTitleStagedFiles)
            or not isinstance(preflight, EpubTitleWritePreflight)
            or not isinstance(patch, EpubTitlePackagePatch)
            or stage.plan_id != patch.plan_id
            or stage.plan_id != preflight.plan_id
            or stage.plan_content_hash != patch.plan_content_hash
            or stage.plan_content_hash != preflight.plan_content_hash
            or stage.input_sha256 != patch.source_sha256
            or stage.input_sha256 != preflight.source_sha256
            or stage.archive_diff.patched_package_sha256
            != patch.patched_package_sha256
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        if _file_identity(stage.input_path) != (
            stage.input_sha256,
            stage.input_size_bytes,
        ) or _file_identity(stage.output_path) != (
            stage.output_sha256,
            stage.output_size_bytes,
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        validation_root = _create_validation_root(stage)
        metadata_before = self._metadata(
            stage.input_path,
            validation_root,
            "metadata-input",
        )
        metadata_after = self._metadata(
            stage.output_path,
            validation_root,
            "metadata-output",
        )
        if metadata_before.title != _normalized_value(preflight.original_title):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.METADATA_READBACK_MISMATCH
            )
        if metadata_after.title != _normalized_value(patch.selected_title):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.METADATA_READBACK_MISMATCH
            )
        if (
            metadata_before.tool_version != metadata_after.tool_version
            or metadata_before.preserved_sha256 != metadata_after.preserved_sha256
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.PRESERVED_FIELDS_MISMATCH
            )

        epubcheck_version = self._epubcheck(stage.output_path, validation_root)
        text_before = self._text(stage.input_path, validation_root, "text-input")
        text_after = self._text(stage.output_path, validation_root, "text-output")
        if (
            text_before.tool_version != text_after.tool_version
            or text_before.sha256 != text_after.sha256
            or text_before.character_count != text_after.character_count
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.TEXT_READBACK_MISMATCH
            )

        cover_before = self._cover(
            stage.input_path,
            stage.input_sha256,
            stage.input_size_bytes,
            validation_root,
            "cover-input",
        )
        cover_after = self._cover(
            stage.output_path,
            stage.output_sha256,
            stage.output_size_bytes,
            validation_root,
            "cover-output",
        )
        if (
            cover_before.tool_version != cover_after.tool_version
            or cover_before.status != cover_after.status
            or cover_before.identity_sha256 != cover_after.identity_sha256
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.COVER_READBACK_MISMATCH
            )

        if _file_identity(stage.input_path) != (
            stage.input_sha256,
            stage.input_size_bytes,
        ) or _file_identity(stage.output_path) != (
            stage.output_sha256,
            stage.output_size_bytes,
        ):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )

        versions = (
            metadata_before.tool_version,
            epubcheck_version,
            text_before.tool_version,
            cover_before.tool_version,
        )
        validator_fingerprint = _canonical_sha256(
            {
                "cover_identity_sha256": cover_before.identity_sha256,
                "cover_status": cover_before.status,
                "input_sha256": stage.input_sha256,
                "metadata_preserved_sha256": metadata_before.preserved_sha256,
                "output_sha256": stage.output_sha256,
                "profile": EPUB_TITLE_VALIDATION_PROFILE,
                "text_sha256": text_before.sha256,
                "tool_versions": list(versions),
                "validator_set": EPUB_TITLE_VALIDATOR_SET,
            }
        )
        return EpubTitleStagedValidation(
            plan_id=stage.plan_id,
            input_sha256=stage.input_sha256,
            output_sha256=stage.output_sha256,
            preserved_fields_sha256=metadata_before.preserved_sha256,
            normalized_text_sha256=text_before.sha256,
            cover_identity_sha256=cover_before.identity_sha256,
            cover_status=cover_before.status,
            metadata_tool_version=versions[0],
            epubcheck_tool_version=versions[1],
            text_tool_version=versions[2],
            cover_tool_version=versions[3],
            validator_set_fingerprint=validator_fingerprint,
        )

    def _metadata(
        self,
        source: Path,
        validation_root: Path,
        step: str,
    ) -> _MetadataProjection:
        outcome = self._runner.run(
            EpubTitleValidationCommand(
                step=step,
                executable=self._metadata_executable,
                args=(str(source), "--to-opf", "metadata.opf"),
                version_args=("--version",),
                version_policy=calibre_version_policy,
                outputs=(
                    EpubTitleValidationOutput("CALIBRE_OPF", "metadata.opf", MAX_OPF_BYTES),
                ),
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment=_calibre_workspace_environment(),
            ),
            validation_root / step,
        )
        _require_outcome_step(outcome, step)
        data = outcome.artifact("CALIBRE_OPF")
        if data is None:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        try:
            projection = project_calibre_opf(
                data,
                execution_id=EntityId.new(),
                observation_id=EntityId.new(),
            )
        except (TypeError, ValueError, RuntimeError) as error:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            ) from error
        observations = tuple((item.key, item.value) for item in projection.observations)
        candidates = tuple((item.key, item.value) for item in projection.candidates)
        titles = tuple(value for key, value in observations if key == "title")
        if len(titles) != 1:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.METADATA_READBACK_MISMATCH
            )
        preserved = _preserved_calibre_projection(observations, candidates)
        return _MetadataProjection(
            title=titles[0],
            preserved_sha256=_canonical_sha256(preserved),
            tool_version=outcome.tool_version,
        )

    def _epubcheck(self, source: Path, validation_root: Path) -> str:
        outcome = self._runner.run(
            EpubTitleValidationCommand(
                step="epubcheck-output",
                executable=self._java_executable,
                args=(
                    "-Djava.awt.headless=true",
                    "-Djava.io.tmpdir=.",
                    "-jar",
                    str(self._epubcheck_jar),
                    str(source),
                    "--json",
                    "report.json",
                    "--locale",
                    "en",
                ),
                version_args=("-jar", str(self._epubcheck_jar), "--version"),
                version_policy=epubcheck_version_policy,
                outputs=(
                    EpubTitleValidationOutput(
                        "EPUBCHECK_JSON",
                        "report.json",
                        MAX_EPUBCHECK_REPORT_BYTES,
                    ),
                ),
                accepted_exit_codes=frozenset({0, 1}),
            ),
            validation_root / "epubcheck-output",
        )
        _require_outcome_step(outcome, "epubcheck-output")
        data = outcome.artifact("EPUBCHECK_JSON")
        if data is None:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        try:
            report = parse_json_output(data, max_bytes=MAX_EPUBCHECK_REPORT_BYTES)
            results = parse_epubcheck_report(
                report,
                execution_id=EntityId.new(),
                observation_id=EntityId.new(),
                expected_filename=source.name,
                expected_tool_version=outcome.tool_version,
            )
        except (StructuredOutputError, TypeError, ValueError, RuntimeError) as error:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            ) from error
        status = next(
            (item.value for item in results if item.key == "conformance_status"),
            None,
        )
        if status != "CONFORMANT":
            raise EpubTitleStagingError(EpubTitleStagingErrorCode.EPUBCHECK_MISMATCH)
        return outcome.tool_version

    def _text(
        self,
        source: Path,
        validation_root: Path,
        step: str,
    ) -> _TextProjection:
        outcome = self._runner.run(
            EpubTitleValidationCommand(
                step=step,
                executable=self._text_executable,
                args=(
                    str(source),
                    "content.txt",
                    "--txt-output-formatting=plain",
                    "--txt-output-encoding=utf-8",
                    "--newline=unix",
                    "--max-line-length=0",
                ),
                version_args=("--version",),
                version_policy=calibre_version_policy,
                outputs=(
                    EpubTitleValidationOutput("CALIBRE_TEXT", "content.txt", MAX_TEXT_BYTES),
                ),
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment=_calibre_workspace_environment(),
            ),
            validation_root / step,
        )
        _require_outcome_step(outcome, step)
        data = outcome.artifact("CALIBRE_TEXT")
        if data is None:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        try:
            normalized = normalize_ebook_text(data)
        except (TypeError, ValueError) as error:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            ) from error
        return _TextProjection(
            sha256=normalized.sha256,
            character_count=normalized.character_count,
            tool_version=outcome.tool_version,
        )

    def _cover(
        self,
        source: Path,
        expected_sha256: str,
        expected_size: int,
        validation_root: Path,
        step: str,
    ) -> _CoverProjection:
        outcome = self._runner.run(
            EpubTitleValidationCommand(
                step=step,
                executable=self._cover_executable,
                args=(
                    "-e",
                    str(self._cover_script),
                    "--",
                    str(source),
                    "cover.bin",
                    "cover-result.json",
                    str(expected_size),
                    str(MAX_COVER_BYTES),
                ),
                version_args=("--version",),
                version_policy=calibre_version_policy,
                outputs=(
                    EpubTitleValidationOutput(
                        "CALIBRE_COVER_RESULT",
                        "cover-result.json",
                        MAX_COVER_RESULT_BYTES,
                    ),
                    EpubTitleValidationOutput(
                        "CALIBRE_EMBEDDED_COVER",
                        "cover.bin",
                        MAX_COVER_BYTES,
                        required=False,
                    ),
                ),
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment=_calibre_workspace_environment(),
            ),
            validation_root / step,
        )
        _require_outcome_step(outcome, step)
        result_data = outcome.artifact("CALIBRE_COVER_RESULT")
        cover_data = outcome.artifact("CALIBRE_EMBEDDED_COVER")
        if result_data is None:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        try:
            result = parse_calibre_cover_result(
                parse_json_output(result_data, max_bytes=MAX_COVER_RESULT_BYTES)
            )
        except (StructuredOutputError, TypeError, ValueError, RuntimeError) as error:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            ) from error
        if result.source_sha256 != expected_sha256:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        if result.status == "NO_EMBEDDED_COVER":
            if result.cover_bytes != 0 or cover_data is not None:
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                )
            identity = _canonical_sha256({"status": result.status})
        elif result.status == "COVER_EXTRACTED":
            if cover_data is None or result.cover_bytes != len(cover_data):
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                )
            try:
                cover = fingerprint_ebook_cover(cover_data, max_bytes=MAX_COVER_BYTES)
            except EbookCoverError as error:
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                ) from error
            identity = _canonical_sha256(
                {
                    "height": cover.height,
                    "image_format": cover.image_format,
                    "status": result.status,
                    "value": cover.value,
                    "width": cover.width,
                }
            )
        else:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        return _CoverProjection(
            status=result.status,
            identity_sha256=identity,
            tool_version=outcome.tool_version,
        )


class _BoundedLocalValidationRunner:
    """Execute only validator-owned requests without persistence or shell access."""

    def __init__(self) -> None:
        self._version_cache: dict[tuple[str, tuple[str, ...]], str] = {}

    def run(
        self,
        command: EpubTitleValidationCommand,
        workspace: Path,
    ) -> EpubTitleValidationToolOutcome:
        try:
            if workspace.exists() or not workspace.parent.is_dir():
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                )
            workspace.mkdir(mode=0o700)
            executable = shutil.which(command.executable)
            if executable is None:
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_TOOL_UNAVAILABLE
                )
            environment = os.environ.copy()
            if command.environment:
                environment.update(command.environment)
            environment = _apply_workspace_environment(
                environment,
                command.workspace_environment,
                workspace,
            )
            cache_key = (executable, command.version_args)
            version = self._version_cache.get(cache_key)
            if version is None:
                version = _detect_version(
                    executable,
                    command.version_args,
                    environment,
                    workspace,
                )
                if command.version_policy(version) is not None:
                    raise EpubTitleStagingError(
                        EpubTitleStagingErrorCode.VALIDATION_TOOL_UNAVAILABLE
                    )
                self._version_cache[cache_key] = version
            return_code, _stdout, _stderr = _run_bounded_process(
                (executable, *command.args),
                environment,
                workspace,
                command.timeout_seconds,
                _PROCESS_OUTPUT_LIMIT,
            )
            if return_code not in command.accepted_exit_codes:
                raise EpubTitleStagingError(
                    EpubTitleStagingErrorCode.VALIDATION_TOOL_FAILED
                )
            artifacts: list[EpubTitleValidationArtifact] = []
            for output in command.outputs:
                path = (workspace / output.relative_path).resolve()
                if not path.is_relative_to(workspace):
                    raise EpubTitleStagingError(
                        EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                    )
                if not path.exists():
                    if output.required:
                        raise EpubTitleStagingError(
                            EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                        )
                    continue
                if _is_link_or_reparse(path) or not path.is_file():
                    raise EpubTitleStagingError(
                        EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                    )
                with path.open("rb") as stream:
                    data = stream.read(output.max_bytes + 1)
                if len(data) > output.max_bytes:
                    raise EpubTitleStagingError(
                        EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
                    )
                artifacts.append(
                    EpubTitleValidationArtifact(output.artifact_type, data)
                )
            return EpubTitleValidationToolOutcome(
                step=command.step,
                tool_version=version,
                artifacts=tuple(artifacts),
            )
        except EpubTitleStagingError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_TOOL_FAILED
            ) from error


def build_and_verify_private_epub3_title_stage(
    private_stage_directory: Path,
    source_stream: BinaryIO,
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
    *,
    validator: FixedEpubTitleStagingValidator | None = None,
) -> EpubTitleVerifiedStage:
    """Build and independently validate one private stage without source commit."""
    stage = build_private_epub3_title_stage(
        private_stage_directory,
        source_stream,
        preflight,
        patch,
    )
    validation = (validator or FixedEpubTitleStagingValidator()).validate(
        stage,
        preflight,
        patch,
    )
    return EpubTitleVerifiedStage(stage, validation)


def _create_validation_root(stage: EpubTitleStagedFiles) -> Path:
    root = stage.private_directory / "validators"
    try:
        if root.exists() or _is_link_or_reparse(stage.private_directory):
            raise EpubTitleStagingError(
                EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
            )
        root.mkdir(mode=0o700)
        resolved = root.resolve(strict=True)
    except EpubTitleStagingError:
        raise
    except OSError as error:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
        ) from error
    if resolved.parent != stage.private_directory or _is_link_or_reparse(resolved):
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
        )
    return resolved


def _normalized_value(value: str) -> str:
    return " ".join(value.split())


def _preserved_calibre_projection(
    observations: tuple[tuple[str, str], ...],
    candidates: tuple[tuple[str, str], ...],
) -> dict[str, list[list[str]]]:
    volatile_identifier_prefixes = {
        ".".join(key.split(".")[:2])
        for key, value in candidates
        if key.startswith("identifier.")
        and ".namespace" in key
        and value.strip().lower() == "calibre"
    }

    def preserved_candidate(item: tuple[str, str]) -> bool:
        key, _value = item
        return key != "title" and not any(
            key == prefix or key.startswith(f"{prefix}.")
            for prefix in volatile_identifier_prefixes
        )

    return {
        "candidates": [list(item) for item in candidates if preserved_candidate(item)],
        "observations": [
            list(item)
            for item in observations
            if item[0] != "title" and item[0].lower() != "identifier:calibre"
        ],
    }


def _calibre_workspace_environment() -> dict[str, str]:
    return {
        "CALIBRE_CONFIG_DIRECTORY": "calibre-config",
        "CALIBRE_TEMP_DIR": "calibre-temp",
        "TEMP": "temp",
        "TMP": "temp",
        "TMPDIR": "temp",
    }


def _require_outcome_step(
    outcome: EpubTitleValidationToolOutcome,
    expected_step: str,
) -> None:
    if not isinstance(outcome, EpubTitleValidationToolOutcome) or outcome.step != expected_step:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
        )


def _apply_workspace_environment(
    environment: Mapping[str, str],
    variables: Mapping[str, str] | None,
    workspace: Path,
) -> dict[str, str]:
    result = dict(environment)
    if variables is None:
        return result
    for variable, relative_path in variables.items():
        path = PurePosixPath(relative_path)
        if (
            not variable.strip()
            or path.is_absolute()
            or PureWindowsPath(relative_path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("invalid private tool environment")
        directory = (workspace / relative_path).resolve()
        if not directory.is_relative_to(workspace):
            raise ValueError("private tool environment escapes its workspace")
        directory.mkdir(parents=True, exist_ok=True)
        result[variable] = str(directory)
    return result


def _detect_version(
    executable: str,
    args: tuple[str, ...],
    environment: Mapping[str, str],
    workspace: Path,
) -> str:
    return_code, stdout, stderr = _run_bounded_process(
        (executable, *args),
        environment,
        workspace,
        10.0,
        _VERSION_OUTPUT_LIMIT,
    )
    if return_code != 0:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_TOOL_UNAVAILABLE
        )
    text = bytes(stdout or stderr).decode(errors="replace").strip()
    if not text:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_TOOL_UNAVAILABLE
        )
    return text.splitlines()[0][:256]


def _run_bounded_process(
    argv: tuple[str, ...],
    environment: Mapping[str, str],
    workspace: Path,
    timeout_seconds: float,
    output_limit: int,
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            argv,
            cwd=workspace,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as error:
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_TOOL_UNAVAILABLE
        ) from error
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    rejected = threading.Event()

    def capture(stream: BinaryIO, target: bytearray) -> None:
        try:
            while chunk := os.read(stream.fileno(), _PROCESS_CHUNK_BYTES):
                if len(target) + len(chunk) > output_limit:
                    rejected.set()
                    process.kill()
                    return
                target.extend(chunk)
        except (OSError, ValueError):
            rejected.set()
            try:
                process.kill()
            except OSError:
                pass

    readers = (
        threading.Thread(target=capture, args=(process.stdout, stdout)),
        threading.Thread(target=capture, args=(process.stderr, stderr)),
    )
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_TOOL_FAILED
        ) from error
    finally:
        for reader in readers:
            reader.join()
    if rejected.is_set():
        raise EpubTitleStagingError(EpubTitleStagingErrorCode.VALIDATION_TOOL_FAILED)
    return return_code, bytes(stdout), bytes(stderr)


def _file_identity(path: Path) -> tuple[str, int]:
    if _is_link_or_reparse(path) or not path.is_file():
        raise EpubTitleStagingError(
            EpubTitleStagingErrorCode.VALIDATION_EVIDENCE_INVALID
        )
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_FILE_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & _WINDOWS_REPARSE_POINT)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "EPUB_TITLE_VALIDATION_PROFILE",
    "EPUB_TITLE_VALIDATOR_SET",
    "EPUB_TITLE_VERIFIED_STAGE_PROFILE",
    "EpubTitleStagedValidation",
    "EpubTitleValidationArtifact",
    "EpubTitleValidationCommand",
    "EpubTitleValidationOutput",
    "EpubTitleValidationToolOutcome",
    "EpubTitleValidationToolRunner",
    "EpubTitleVerifiedStage",
    "FixedEpubTitleStagingValidator",
    "build_and_verify_private_epub3_title_stage",
]
