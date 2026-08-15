from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.adapters.calibre import (
    CalibreCoverOutcome,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    CalibreTextOutcome,
)
from foliotone.adapters.epubcheck import EpubCheckOutcome
from foliotone.adapters.poppler import PopplerPdfOutcome
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.tooling import ToolExecution, ToolResult
from foliotone.tooling.runtime import ToolRunOutcome
from foliotone.workflows import (
    EBOOK_ANALYSIS_PROFILE,
    EbookAnalysisError,
    EbookAnalysisOrchestrator,
    EbookAnalysisStatus,
    EbookAnalysisStepOutcome,
    EbookAnalysisStepState,
    EbookAnalysisTools,
    ebook_analysis_format,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("relative_path", "format_name"),
    (
        ("books/example.EPUB", "EPUB"),
        ("books/example.mobi", "MOBI"),
        ("books/example.azw", "AZW"),
        ("books/example.azw3", "AZW3"),
        ("books/example.pdf", "PDF"),
    ),
)
def test_analysis_format_uses_explicit_case_insensitive_allowlist(
    relative_path: str,
    format_name: str,
) -> None:
    assert ebook_analysis_format(relative_path) == format_name


def test_epub_workflow_runs_every_applicable_step_and_bounds_summary() -> None:
    order: list[str] = []
    observation = _observation("books/example.epub")

    outcome = EbookAnalysisOrchestrator(_tools(order)).analyze(
        Path("unused"),
        observation,
    )

    assert order == ["metadata", "text", "cover", "validation"]
    assert outcome.observation_id == observation.id
    assert outcome.format_name == "EPUB"
    assert outcome.profile == EBOOK_ANALYSIS_PROFILE
    assert outcome.status is EbookAnalysisStatus.SUCCEEDED
    assert [step.name for step in outcome.steps] == [
        "metadata",
        "text",
        "cover",
        "structural-validation",
    ]
    assert all(step.state is EbookAnalysisStepState.SUCCEEDED for step in outcome.steps)

    metadata_facts = dict(outcome.steps[0].facts)
    assert metadata_facts == {
        "metadata_observation_count": "1",
        "metadata_candidate_count": "1",
    }
    assert "Synthetic Title" not in metadata_facts.values()
    assert dict(outcome.steps[1].facts) == {
        "text_status": "TEXT_EXTRACTED",
        "normalized_character_count": "123",
        "normalized_text_fingerprint": "1" * 64,
    }
    assert dict(outcome.steps[2].facts) == {
        "cover_status": "COVER_EXTRACTED",
        "image_format": "PNG",
        "display_width": "600",
        "display_height": "900",
        "cover_perceptual_fingerprint": "0123456789abcdef",
    }
    assert dict(outcome.steps[3].facts) == {
        "conformance_status": "CONFORMANT",
        "fatal_count": "0",
        "error_count": "0",
        "warning_count": "1",
        "usage_count": "0",
        "info_count": "0",
        "diagnostic_code_count": "1",
    }


@pytest.mark.parametrize("suffix", ("mobi", "azw", "azw3"))
def test_calibre_formats_skip_epubcheck_and_poppler(suffix: str) -> None:
    order: list[str] = []

    outcome = EbookAnalysisOrchestrator(_tools(order)).analyze(
        Path("unused"),
        _observation(f"books/example.{suffix}"),
    )

    assert order == ["metadata", "text", "cover"]
    assert [step.name for step in outcome.steps] == ["metadata", "text", "cover"]
    assert outcome.format_name == suffix.upper()
    assert outcome.status is EbookAnalysisStatus.SUCCEEDED


def test_pdf_workflow_uses_only_poppler_and_preserves_both_executions() -> None:
    order: list[str] = []

    outcome = EbookAnalysisOrchestrator(_tools(order)).analyze(
        Path("unused"),
        _observation("books/example.pdf"),
    )

    assert order == ["pdf"]
    assert outcome.format_name == "PDF"
    assert outcome.status is EbookAnalysisStatus.SUCCEEDED
    assert len(outcome.steps) == 1
    step = outcome.steps[0]
    assert step.name == "pdf-analysis"
    assert len(step.executions) == 2
    assert dict(step.facts) == {
        "metadata_observation_count": "4",
        "page_count": "42",
        "encrypted": "no",
        "pdf_version": "1.7",
        "text_status": "TEXT_EXTRACTED",
        "normalized_character_count": "456",
        "normalized_text_fingerprint": "2" * 64,
    }


def test_failed_tool_step_does_not_hide_or_block_later_steps() -> None:
    order: list[str] = []

    outcome = EbookAnalysisOrchestrator(
        _tools(order, text_status=ToolExecutionStatus.FAILED)
    ).analyze(Path("unused"), _observation("books/example.epub"))

    assert order == ["metadata", "text", "cover", "validation"]
    assert outcome.steps[1].state is EbookAnalysisStepState.FAILED
    assert outcome.steps[1].facts == ()
    assert outcome.steps[2].state is EbookAnalysisStepState.SUCCEEDED
    assert outcome.steps[3].state is EbookAnalysisStepState.SUCCEEDED
    assert outcome.status is EbookAnalysisStatus.PARTIAL_FAILURE


def test_adapter_error_is_bounded_and_does_not_block_independent_steps() -> None:
    order: list[str] = []

    outcome = EbookAnalysisOrchestrator(
        _tools(order, metadata_error="metadata projection failed")
    ).analyze(Path("unused"), _observation("books/example.epub"))

    assert order == ["metadata", "text", "cover", "validation"]
    assert outcome.steps[0].state is EbookAnalysisStepState.ERROR
    assert outcome.steps[0].executions == ()
    assert outcome.steps[0].error == "metadata projection failed"
    assert outcome.status is EbookAnalysisStatus.PARTIAL_FAILURE


def test_missing_required_tool_is_rejected_before_any_step_runs() -> None:
    order: list[str] = []
    tools = _tools(order)
    incomplete = EbookAnalysisTools(
        metadata=tools.metadata,
        text=tools.text,
        cover=None,
        validation=tools.validation,
        pdf=tools.pdf,
    )

    with pytest.raises(EbookAnalysisError, match="cover analyzer"):
        EbookAnalysisOrchestrator(incomplete).analyze(
            Path("unused"),
            _observation("books/example.epub"),
        )

    assert order == []


def test_unsupported_format_is_rejected_before_any_step_runs() -> None:
    order: list[str] = []

    with pytest.raises(EbookAnalysisError, match="only EPUB, MOBI, AZW, AZW3, or PDF"):
        EbookAnalysisOrchestrator(_tools(order)).analyze(
            Path("unused"),
            _observation("books/example.kfx"),
        )

    assert order == []


def test_workflow_summary_rejects_nonterminal_execution_and_duplicate_facts() -> None:
    running = _execution(
        ToolCapability.READ_METADATA,
        ToolExecutionStatus.RUNNING,
    )
    with pytest.raises(ValueError, match="terminal"):
        EbookAnalysisStepOutcome(name="metadata", executions=(running,))

    succeeded = _execution(
        ToolCapability.READ_METADATA,
        ToolExecutionStatus.SUCCEEDED,
    )
    with pytest.raises(ValueError, match="unique"):
        EbookAnalysisStepOutcome(
            name="metadata",
            executions=(succeeded,),
            facts=(("count", "1"), ("count", "2")),
        )


def _tools(
    order: list[str],
    *,
    text_status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
    metadata_error: str | None = None,
) -> EbookAnalysisTools:
    def metadata(_root: Path, observation: FileObservation) -> CalibreMetadataOutcome:
        order.append("metadata")
        if metadata_error is not None:
            raise CalibreMetadataError(metadata_error)
        execution = _execution(
            ToolCapability.READ_METADATA,
            ToolExecutionStatus.SUCCEEDED,
        )
        return CalibreMetadataOutcome(
            run=_run(execution),
            results=(_result(execution, observation, "title", "Synthetic Title"),),
            candidates=(
                _result(
                    execution,
                    observation,
                    "title.candidate",
                    "Synthetic Title",
                ),
            ),
        )

    def text(_root: Path, observation: FileObservation) -> CalibreTextOutcome:
        order.append("text")
        execution = _execution(ToolCapability.EXTRACT_TEXT, text_status)
        if text_status is not ToolExecutionStatus.SUCCEEDED:
            return CalibreTextOutcome(_run(execution), (), None)
        return CalibreTextOutcome(
            run=_run(execution),
            results=(
                _result(execution, observation, "text_status", "TEXT_EXTRACTED"),
                _result(execution, observation, "normalized_character_count", "123"),
            ),
            fingerprint=_fingerprint(execution, observation, "1" * 64),
        )

    def cover(_root: Path, observation: FileObservation) -> CalibreCoverOutcome:
        order.append("cover")
        execution = _execution(
            ToolCapability.FINGERPRINT,
            ToolExecutionStatus.SUCCEEDED,
        )
        return CalibreCoverOutcome(
            run=_run(execution),
            results=(
                _result(execution, observation, "cover_status", "COVER_EXTRACTED"),
                _result(execution, observation, "image_format", "PNG"),
                _result(execution, observation, "display_width", "600"),
                _result(execution, observation, "display_height", "900"),
            ),
            fingerprint=_fingerprint(
                execution,
                observation,
                "0123456789abcdef",
                kind="EBOOK_COVER_DHASH",
                algorithm="dhash-64",
            ),
        )

    def validation(_root: Path, observation: FileObservation) -> EpubCheckOutcome:
        order.append("validation")
        execution = _execution(
            ToolCapability.STRUCTURAL_VALIDATION,
            ToolExecutionStatus.SUCCEEDED,
        )
        values = (
            ("conformance_status", "CONFORMANT"),
            ("fatal_count", "0"),
            ("error_count", "0"),
            ("warning_count", "1"),
            ("usage_count", "0"),
            ("info_count", "0"),
            ("diagnostic.WARNING.OPF-001", "1"),
        )
        return EpubCheckOutcome(
            run=_run(execution),
            results=tuple(
                _result(execution, observation, key, value) for key, value in values
            ),
        )

    def pdf(_root: Path, observation: FileObservation) -> PopplerPdfOutcome:
        order.append("pdf")
        info_execution = _execution(
            ToolCapability.TECHNICAL_METADATA,
            ToolExecutionStatus.SUCCEEDED,
        )
        text_execution = _execution(
            ToolCapability.EXTRACT_TEXT,
            ToolExecutionStatus.SUCCEEDED,
        )
        metadata_results = (
            _result(info_execution, observation, "page_count", "42"),
            _result(info_execution, observation, "encrypted", "no"),
            _result(info_execution, observation, "pdf_version", "1.7"),
            _result(info_execution, observation, "title", "Private Fixture Title"),
        )
        text_results = (
            _result(text_execution, observation, "text_status", "TEXT_EXTRACTED"),
            _result(
                text_execution,
                observation,
                "normalized_character_count",
                "456",
            ),
        )
        return PopplerPdfOutcome(
            info_run=_run(info_execution),
            text_run=_run(text_execution),
            metadata_results=metadata_results,
            text_results=text_results,
            fingerprint=_fingerprint(text_execution, observation, "2" * 64),
        )

    return EbookAnalysisTools(
        metadata=metadata,
        text=text,
        cover=cover,
        validation=validation,
        pdf=pdf,
    )


def _observation(relative_path: str) -> FileObservation:
    return FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=1234,
        modified_at=NOW,
        observed_at=NOW,
    )


def _execution(
    capability: ToolCapability,
    status: ToolExecutionStatus,
) -> ToolExecution:
    terminal = status in {
        ToolExecutionStatus.SUCCEEDED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    }
    return ToolExecution(
        id=EntityId.new(),
        provider_id="fixture",
        tool_version="fixture 1.0",
        adapter_version="fixture/1",
        capability=capability,
        input_identity="file-observation:fixture",
        config_identity="fixture:v1",
        started_at=NOW,
        finished_at=NOW if terminal else None,
        status=status,
        exit_code=0 if status is ToolExecutionStatus.SUCCEEDED else None,
        error_summary=(
            "fixture failure" if status is ToolExecutionStatus.FAILED else None
        ),
    )


def _run(execution: ToolExecution) -> ToolRunOutcome:
    return ToolRunOutcome(execution=execution, artifacts=(), stdout_preview="", stderr_preview="")


def _result(
    execution: ToolExecution,
    observation: FileObservation,
    key: str,
    value: str,
) -> ToolResult:
    return ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type="fixture",
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        key=key,
        value=value,
    )


def _fingerprint(
    execution: ToolExecution,
    observation: FileObservation,
    value: str,
    *,
    kind: str = "EBOOK_NORMALIZED_TEXT",
    algorithm: str = "sha256",
) -> Fingerprint:
    return Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        kind=kind,
        algorithm=algorithm,
        algorithm_version="fixture-v1",
        value=value,
        created_at=NOW,
        tool_execution_id=execution.id,
    )
