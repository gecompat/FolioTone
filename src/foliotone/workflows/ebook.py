"""Format-aware orchestration of the implemented read-only e-book analyzers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from foliotone.adapters.calibre import (
    CalibreCoverError,
    CalibreCoverOutcome,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    CalibreTextError,
    CalibreTextOutcome,
)
from foliotone.adapters.epubcheck import EpubCheckError, EpubCheckOutcome
from foliotone.adapters.poppler import PopplerPdfError, PopplerPdfOutcome
from foliotone.analyzers.ebook import ObservedFileError, resolve_observed_file
from foliotone.core import EntityId, FileObservation, ToolExecutionStatus
from foliotone.tooling import ToolExecution, ToolResult

EBOOK_ANALYSIS_PROFILE = "ebook-analysis-workflow/v2"
EBOOK_ANALYSIS_FORMATS = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")
_FORMAT_BY_SUFFIX = {
    f".{format_name.lower()}": format_name for format_name in EBOOK_ANALYSIS_FORMATS
}
_TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ToolExecutionStatus.SUCCEEDED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    }
)
_MAX_FACT_KEY_CHARS = 64
_MAX_FACT_VALUE_CHARS = 4096
_MAX_STEP_ERROR_CHARS = 4096

type MetadataAnalysis = Callable[[Path, FileObservation], CalibreMetadataOutcome]
type TextAnalysis = Callable[[Path, FileObservation], CalibreTextOutcome]
type CoverAnalysis = Callable[[Path, FileObservation], CalibreCoverOutcome]
type ValidationAnalysis = Callable[[Path, FileObservation], EpubCheckOutcome]
type PdfAnalysis = Callable[[Path, FileObservation], PopplerPdfOutcome]
type MetadataReuse = Callable[[Path, FileObservation], CalibreMetadataOutcome | None]
type TextReuse = Callable[[Path, FileObservation], CalibreTextOutcome | None]
type CoverReuse = Callable[[Path, FileObservation], CalibreCoverOutcome | None]
type ValidationReuse = Callable[[Path, FileObservation], EpubCheckOutcome | None]
type PdfReuse = Callable[[Path, FileObservation], PopplerPdfOutcome | None]


class EbookAnalysisError(RuntimeError):
    """A unified e-book analysis request cannot be planned or configured safely."""


class EbookAnalysisStepState(StrEnum):
    """Terminal state of one adapter step in the unified workflow."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class EbookAnalysisStatus(StrEnum):
    """Aggregate terminal state without hiding partial analyzer failures."""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"


class EbookAnalysisStepDisposition(StrEnum):
    """Whether a step executed tools or reused exact persisted evidence."""

    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class EbookAnalysisStepOutcome:
    """Bounded summary of one adapter step and its exact ToolExecutions."""

    name: str
    executions: tuple[ToolExecution, ...] = ()
    facts: tuple[tuple[str, str], ...] = ()
    error: str | None = None
    disposition: EbookAnalysisStepDisposition = EbookAnalysisStepDisposition.EXECUTED

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("step name must not be empty")
        object.__setattr__(self, "name", name)

        if self.error is None and not self.executions:
            raise ValueError("a completed step requires an execution or an error")
        if self.error is not None:
            error = self.error.strip()
            if not error:
                raise ValueError("step error must not be empty")
            if len(error) > _MAX_STEP_ERROR_CHARS:
                raise ValueError("step error exceeds the configured size limit")
            if self.executions:
                raise ValueError("adapter errors cannot claim inaccessible executions")
            object.__setattr__(self, "error", error)

        for execution in self.executions:
            if execution.status not in _TERMINAL_EXECUTION_STATUSES:
                raise ValueError("workflow steps require terminal ToolExecutions")

        seen: set[str] = set()
        for key, value in self.facts:
            if not key or len(key) > _MAX_FACT_KEY_CHARS:
                raise ValueError("workflow fact key must be bounded and non-empty")
            if not value or len(value) > _MAX_FACT_VALUE_CHARS:
                raise ValueError("workflow fact value must be bounded and non-empty")
            if key in seen:
                raise ValueError("workflow fact keys must be unique within one step")
            seen.add(key)

    @property
    def state(self) -> EbookAnalysisStepState:
        """Summarize terminal execution states without treating adapter errors as runs."""
        if self.error is not None:
            return EbookAnalysisStepState.ERROR
        if all(
            execution.status is ToolExecutionStatus.SUCCEEDED
            for execution in self.executions
        ):
            return EbookAnalysisStepState.SUCCEEDED
        if any(
            execution.status is ToolExecutionStatus.CANCELLED
            for execution in self.executions
        ):
            return EbookAnalysisStepState.CANCELLED
        return EbookAnalysisStepState.FAILED


@dataclass(frozen=True, slots=True)
class EbookAnalysisOutcome:
    """Format route and bounded summaries for one exact FileObservation."""

    observation_id: EntityId
    format_name: str
    steps: tuple[EbookAnalysisStepOutcome, ...]
    profile: str = EBOOK_ANALYSIS_PROFILE

    def __post_init__(self) -> None:
        if self.format_name not in EBOOK_ANALYSIS_FORMATS:
            raise ValueError("format_name is not supported by the e-book workflow")
        if not self.steps:
            raise ValueError("an e-book analysis outcome requires at least one step")
        if not self.profile.strip():
            raise ValueError("analysis profile must not be empty")
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError("e-book analysis step names must be unique")

    @property
    def status(self) -> EbookAnalysisStatus:
        """Return success, partial failure, or total failure for CLI exit semantics."""
        if all(step.state is EbookAnalysisStepState.SUCCEEDED for step in self.steps):
            return EbookAnalysisStatus.SUCCEEDED
        if any(
            execution.status is ToolExecutionStatus.SUCCEEDED
            for step in self.steps
            for execution in step.executions
        ):
            return EbookAnalysisStatus.PARTIAL_FAILURE
        return EbookAnalysisStatus.FAILED


@dataclass(frozen=True, slots=True)
class EbookAnalysisTools:
    """Injectable adapter entry points used by the format-aware workflow."""

    metadata: MetadataAnalysis | None = None
    text: TextAnalysis | None = None
    cover: CoverAnalysis | None = None
    validation: ValidationAnalysis | None = None
    pdf: PdfAnalysis | None = None
    metadata_reuse: MetadataReuse | None = None
    text_reuse: TextReuse | None = None
    cover_reuse: CoverReuse | None = None
    validation_reuse: ValidationReuse | None = None
    pdf_reuse: PdfReuse | None = None


class EbookAnalysisOrchestrator:
    """Run every applicable adapter sequentially while preserving partial failures."""

    def __init__(self, tools: EbookAnalysisTools) -> None:
        self._tools = tools

    def analyze(
        self,
        source_root: Path,
        observation: FileObservation,
        *,
        fresh: bool = False,
    ) -> EbookAnalysisOutcome:
        """Reuse exact evidence or run only the required format-aware steps."""
        format_name = ebook_analysis_format(observation.relative_path)
        steps: tuple[EbookAnalysisStepOutcome, ...]
        if format_name == "PDF":
            pdf = _required_tool(self._tools.pdf, "pdf")
            if not fresh and self._tools.pdf_reuse is not None:
                _validate_source(source_root, observation)
            steps = (
                _capture_step(
                    "pdf-analysis",
                    lambda: _pdf_step(
                        *_select_analysis(
                            pdf,
                            self._tools.pdf_reuse,
                            source_root,
                            observation,
                            fresh=fresh,
                        )
                    ),
                    (PopplerPdfError,),
                ),
            )
        else:
            metadata = _required_tool(self._tools.metadata, "metadata")
            text = _required_tool(self._tools.text, "text")
            cover = _required_tool(self._tools.cover, "cover")
            validation = (
                _required_tool(self._tools.validation, "structural validation")
                if format_name == "EPUB"
                else None
            )
            if not fresh and any(
                reuse is not None
                for reuse in (
                    self._tools.metadata_reuse,
                    self._tools.text_reuse,
                    self._tools.cover_reuse,
                    self._tools.validation_reuse if format_name == "EPUB" else None,
                )
            ):
                _validate_source(source_root, observation)
            planned: list[EbookAnalysisStepOutcome] = [
                _capture_step(
                    "metadata",
                    lambda: _metadata_step(
                        *_select_analysis(
                            metadata,
                            self._tools.metadata_reuse,
                            source_root,
                            observation,
                            fresh=fresh,
                        )
                    ),
                    (CalibreMetadataError,),
                ),
                _capture_step(
                    "text",
                    lambda: _text_step(
                        *_select_analysis(
                            text,
                            self._tools.text_reuse,
                            source_root,
                            observation,
                            fresh=fresh,
                        )
                    ),
                    (CalibreTextError,),
                ),
                _capture_step(
                    "cover",
                    lambda: _cover_step(
                        *_select_analysis(
                            cover,
                            self._tools.cover_reuse,
                            source_root,
                            observation,
                            fresh=fresh,
                        )
                    ),
                    (CalibreCoverError,),
                ),
            ]
            if validation is not None:
                planned.append(
                    _capture_step(
                        "structural-validation",
                        lambda: _validation_step(
                            *_select_analysis(
                                validation,
                                self._tools.validation_reuse,
                                source_root,
                                observation,
                                fresh=fresh,
                            )
                        ),
                        (EpubCheckError,),
                    )
                )
            steps = tuple(planned)

        return EbookAnalysisOutcome(
            observation_id=observation.id,
            format_name=format_name,
            steps=steps,
        )


def ebook_analysis_format(relative_path: str) -> str:
    """Resolve the explicit workflow allowlist from a persisted relative path."""
    suffix = PurePosixPath(relative_path).suffix.lower()
    format_name = _FORMAT_BY_SUFFIX.get(suffix)
    if format_name is None:
        raise EbookAnalysisError(
            "unified e-book analysis accepts only EPUB, MOBI, AZW, AZW3, or PDF files"
        )
    return format_name


def _required_tool[T](value: T | None, name: str) -> T:
    if value is None:
        raise EbookAnalysisError(f"required {name} analyzer is not configured")
    return value


def _capture_step(
    name: str,
    action: Callable[[], EbookAnalysisStepOutcome],
    handled_errors: tuple[type[Exception], ...],
) -> EbookAnalysisStepOutcome:
    try:
        return action()
    except handled_errors as error:
        message = str(error).strip() or type(error).__name__
        return EbookAnalysisStepOutcome(
            name=name,
            error=message[:_MAX_STEP_ERROR_CHARS],
        )


def _select_analysis[T](
    analyze: Callable[[Path, FileObservation], T],
    reuse: Callable[[Path, FileObservation], T | None] | None,
    source_root: Path,
    observation: FileObservation,
    *,
    fresh: bool,
) -> tuple[T, EbookAnalysisStepDisposition]:
    if not fresh and reuse is not None:
        previous = reuse(source_root, observation)
        if previous is not None:
            return previous, EbookAnalysisStepDisposition.REUSED
    return analyze(source_root, observation), EbookAnalysisStepDisposition.EXECUTED


def _validate_source(source_root: Path, observation: FileObservation) -> None:
    try:
        resolve_observed_file(source_root, observation)
    except ObservedFileError as error:
        raise EbookAnalysisError(str(error)) from error


def _metadata_step(
    outcome: CalibreMetadataOutcome,
    disposition: EbookAnalysisStepDisposition,
) -> EbookAnalysisStepOutcome:
    facts: tuple[tuple[str, str], ...] = ()
    if outcome.run.execution.status is ToolExecutionStatus.SUCCEEDED:
        facts = (
            ("metadata_observation_count", str(len(outcome.results))),
            ("metadata_candidate_count", str(len(outcome.candidates))),
        )
    return EbookAnalysisStepOutcome(
        name="metadata",
        executions=(outcome.run.execution,),
        facts=facts,
        disposition=disposition,
    )


def _text_step(
    outcome: CalibreTextOutcome,
    disposition: EbookAnalysisStepDisposition,
) -> EbookAnalysisStepOutcome:
    facts = _selected_result_facts(
        outcome.results,
        ("text_status", "normalized_character_count"),
    )
    if outcome.fingerprint is not None:
        facts += (("normalized_text_fingerprint", outcome.fingerprint.value),)
    return EbookAnalysisStepOutcome(
        name="text",
        executions=(outcome.run.execution,),
        facts=facts,
        disposition=disposition,
    )


def _cover_step(
    outcome: CalibreCoverOutcome,
    disposition: EbookAnalysisStepDisposition,
) -> EbookAnalysisStepOutcome:
    facts = _selected_result_facts(
        outcome.results,
        ("cover_status", "image_format", "display_width", "display_height"),
    )
    if outcome.fingerprint is not None:
        facts += (("cover_perceptual_fingerprint", outcome.fingerprint.value),)
    return EbookAnalysisStepOutcome(
        name="cover",
        executions=(outcome.run.execution,),
        facts=facts,
        disposition=disposition,
    )


def _validation_step(
    outcome: EpubCheckOutcome,
    disposition: EbookAnalysisStepDisposition,
) -> EbookAnalysisStepOutcome:
    facts = _selected_result_facts(
        outcome.results,
        (
            "conformance_status",
            "fatal_count",
            "error_count",
            "warning_count",
            "usage_count",
            "info_count",
        ),
    )
    diagnostic_count = sum(
        result.key.startswith("diagnostic.") for result in outcome.results
    )
    if outcome.run.execution.status is ToolExecutionStatus.SUCCEEDED:
        facts += (("diagnostic_code_count", str(diagnostic_count)),)
    return EbookAnalysisStepOutcome(
        name="structural-validation",
        executions=(outcome.run.execution,),
        facts=facts,
        disposition=disposition,
    )


def _pdf_step(
    outcome: PopplerPdfOutcome,
    disposition: EbookAnalysisStepDisposition,
) -> EbookAnalysisStepOutcome:
    facts: tuple[tuple[str, str], ...] = ()
    if outcome.info_run.execution.status is ToolExecutionStatus.SUCCEEDED:
        facts = (("metadata_observation_count", str(len(outcome.metadata_results))),)
        facts += _selected_result_facts(
            outcome.metadata_results,
            ("page_count", "encrypted", "pdf_version", "pdf_subtype"),
        )
    facts += _selected_result_facts(
        outcome.text_results,
        ("text_status", "normalized_character_count"),
    )
    if outcome.fingerprint is not None:
        facts += (("normalized_text_fingerprint", outcome.fingerprint.value),)
    return EbookAnalysisStepOutcome(
        name="pdf-analysis",
        executions=(outcome.info_run.execution, outcome.text_run.execution),
        facts=facts,
        disposition=disposition,
    )


def _selected_result_facts(
    results: tuple[ToolResult, ...],
    keys: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    values = {result.key: result.value for result in results}
    return tuple((key, values[key]) for key in keys if key in values)
