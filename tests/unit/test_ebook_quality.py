from datetime import UTC, datetime

import pytest

from foliotone.core import EntityId, ToolCapability, ToolExecutionStatus
from foliotone.tooling import ToolExecution
from foliotone.workflows import (
    EBOOK_QUALITY_PROFILE,
    EbookAnalysisStepOutcome,
    EbookQualityAssessment,
    EbookQualityDimension,
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityStatus,
    evaluate_ebook_quality,
)

NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


def test_complete_epub_quality_is_ok_and_preserves_exact_execution_ids() -> None:
    observation_id = EntityId.new()
    steps = _epub_steps()

    assessment = evaluate_ebook_quality(observation_id, "EPUB", steps)

    assert assessment.profile == EBOOK_QUALITY_PROFILE
    assert assessment.observation_id == observation_id
    assert assessment.status is EbookQualityStatus.OK
    assert [dimension.status for dimension in assessment.dimensions] == [
        EbookQualityDimensionStatus.OK,
        EbookQualityDimensionStatus.OK,
        EbookQualityDimensionStatus.OK,
        EbookQualityDimensionStatus.OK,
        EbookQualityDimensionStatus.OK,
    ]
    assert assessment.findings == ()
    assert assessment.source_execution_ids == tuple(
        execution.id for step in steps for execution in step.executions
    )


def test_sparse_nonconformant_epub_produces_stable_actionable_findings() -> None:
    metadata = _step(
        "metadata",
        _metadata_facts(
            title=False,
            author=False,
            contributor=False,
            language=False,
            identifier=False,
            publisher=False,
            publication_date=False,
            series=True,
            series_position=False,
        ),
        ToolCapability.READ_METADATA,
    )
    text = _step(
        "text",
        (("text_status", "NO_TEXT"), ("normalized_character_count", "0")),
        ToolCapability.EXTRACT_TEXT,
    )
    cover = _step(
        "cover",
        (("cover_status", "NO_EMBEDDED_COVER"),),
        ToolCapability.FINGERPRINT,
    )
    structure = _step(
        "structural-validation",
        (
            ("conformance_status", "NONCONFORMANT"),
            ("fatal_count", "1"),
            ("error_count", "2"),
            ("warning_count", "3"),
        ),
        ToolCapability.STRUCTURAL_VALIDATION,
    )

    assessment = evaluate_ebook_quality(
        EntityId.new(),
        "EPUB",
        (metadata, text, cover, structure),
    )

    assert assessment.status is EbookQualityStatus.ACTION_REQUIRED
    assert [dimension.status for dimension in assessment.dimensions] == [
        EbookQualityDimensionStatus.REVIEW,
        EbookQualityDimensionStatus.ACTION_REQUIRED,
        EbookQualityDimensionStatus.REVIEW,
        EbookQualityDimensionStatus.ACTION_REQUIRED,
        EbookQualityDimensionStatus.OK,
    ]
    assert [finding.code for finding in assessment.findings] == [
        "METADATA_TITLE_MISSING",
        "METADATA_AUTHOR_MISSING",
        "METADATA_LANGUAGE_MISSING",
        "METADATA_IDENTIFIER_MISSING",
        "METADATA_PUBLICATION_CONTEXT_MISSING",
        "METADATA_SERIES_POSITION_MISSING",
        "TEXT_NOT_AVAILABLE",
        "COVER_MISSING",
        "EPUB_FATAL_ERRORS",
        "EPUB_VALIDATION_ERRORS",
        "EPUB_VALIDATION_WARNINGS",
    ]
    assert all(finding.source_execution_ids for finding in assessment.findings)


def test_encrypted_textless_pdf_is_an_ocr_candidate_without_cover_claims() -> None:
    step = _pdf_step(
        (
            ("title_present", "false"),
            ("author_present", "false"),
            ("page_count", "7"),
            ("encrypted", "yes (print:no copy:no)"),
            ("text_status", "NO_TEXT"),
            ("normalized_character_count", "0"),
        )
    )

    assessment = evaluate_ebook_quality(EntityId.new(), "PDF", (step,))

    assert assessment.status is EbookQualityStatus.ACTION_REQUIRED
    assert [dimension.status for dimension in assessment.dimensions] == [
        EbookQualityDimensionStatus.REVIEW,
        EbookQualityDimensionStatus.ACTION_REQUIRED,
        EbookQualityDimensionStatus.NOT_APPLICABLE,
        EbookQualityDimensionStatus.NOT_APPLICABLE,
        EbookQualityDimensionStatus.ACTION_REQUIRED,
    ]
    assert [finding.code for finding in assessment.findings] == [
        "METADATA_TITLE_MISSING",
        "METADATA_AUTHOR_MISSING",
        "TEXT_NOT_AVAILABLE",
        "PDF_OCR_CANDIDATE",
        "PDF_ENCRYPTED",
        "STRUCTURAL_VALIDATION_UNAVAILABLE",
    ]
    text_execution_id = step.executions[1].id
    ocr = next(
        finding
        for finding in assessment.findings
        if finding.code == "PDF_OCR_CANDIDATE"
    )
    assert ocr.source_execution_ids == (text_execution_id,)


def test_failed_evidence_makes_quality_incomplete_without_hiding_other_findings() -> None:
    steps = list(_epub_steps())
    steps[0] = _step(
        "metadata",
        (),
        ToolCapability.READ_METADATA,
        status=ToolExecutionStatus.FAILED,
    )
    steps[2] = _step(
        "cover",
        (("cover_status", "NO_EMBEDDED_COVER"),),
        ToolCapability.FINGERPRINT,
    )

    assessment = evaluate_ebook_quality(EntityId.new(), "EPUB", tuple(steps))

    assert assessment.status is EbookQualityStatus.INCOMPLETE
    assert assessment.dimensions[0].status is EbookQualityDimensionStatus.INCOMPLETE
    assert {finding.code for finding in assessment.findings} == {
        "METADATA_ANALYSIS_INCOMPLETE",
        "COVER_MISSING",
    }


def test_inconsistent_text_evidence_is_incomplete_instead_of_a_quality_verdict() -> None:
    steps = list(_epub_steps())
    steps[1] = _step(
        "text",
        (("text_status", "NO_TEXT"), ("normalized_character_count", "12")),
        ToolCapability.EXTRACT_TEXT,
    )

    assessment = evaluate_ebook_quality(EntityId.new(), "EPUB", tuple(steps))

    assert assessment.status is EbookQualityStatus.INCOMPLETE
    assert assessment.findings[0].code == "TEXT_EVIDENCE_INCONSISTENT"


def test_quality_assessment_requires_the_complete_stable_dimension_order() -> None:
    with pytest.raises(ValueError, match="stable complete order"):
        EbookQualityAssessment(
            observation_id=EntityId.new(),
            format_name="EPUB",
            dimensions=(
                EbookQualityDimension(
                    EbookQualityDimensionName.TEXT,
                    EbookQualityDimensionStatus.OK,
                ),
            ),
            findings=(),
            source_execution_ids=(),
        )


def _epub_steps() -> tuple[EbookAnalysisStepOutcome, ...]:
    return (
        _step(
            "metadata",
            _metadata_facts(),
            ToolCapability.READ_METADATA,
        ),
        _step(
            "text",
            (
                ("text_status", "TEXT_EXTRACTED"),
                ("normalized_character_count", "5000"),
            ),
            ToolCapability.EXTRACT_TEXT,
        ),
        _step(
            "cover",
            (("cover_status", "COVER_EXTRACTED"),),
            ToolCapability.FINGERPRINT,
        ),
        _step(
            "structural-validation",
            (
                ("conformance_status", "CONFORMANT"),
                ("fatal_count", "0"),
                ("error_count", "0"),
                ("warning_count", "0"),
            ),
            ToolCapability.STRUCTURAL_VALIDATION,
        ),
    )


def _metadata_facts(
    *,
    title: bool = True,
    author: bool = True,
    contributor: bool = True,
    language: bool = True,
    identifier: bool = True,
    publisher: bool = True,
    publication_date: bool = True,
    series: bool = False,
    series_position: bool = False,
) -> tuple[tuple[str, str], ...]:
    values = (
        ("title_present", title),
        ("author_present", author),
        ("contributor_present", contributor),
        ("language_present", language),
        ("identifier_present", identifier),
        ("publisher_present", publisher),
        ("publication_date_present", publication_date),
        ("series_present", series),
        ("series_position_present", series_position),
    )
    return tuple((key, "true" if value else "false") for key, value in values)


def _pdf_step(facts: tuple[tuple[str, str], ...]) -> EbookAnalysisStepOutcome:
    return EbookAnalysisStepOutcome(
        name="pdf-analysis",
        executions=(
            _execution(ToolCapability.TECHNICAL_METADATA),
            _execution(ToolCapability.EXTRACT_TEXT),
        ),
        facts=facts,
    )


def _step(
    name: str,
    facts: tuple[tuple[str, str], ...],
    capability: ToolCapability,
    *,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
) -> EbookAnalysisStepOutcome:
    return EbookAnalysisStepOutcome(
        name=name,
        executions=(_execution(capability, status),),
        facts=facts,
    )


def _execution(
    capability: ToolCapability,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id="quality-fixture",
        tool_version="fixture 1.0",
        adapter_version="quality-fixture/1",
        capability=capability,
        input_identity="file-observation:quality-fixture",
        config_identity="quality-fixture:v1",
        started_at=NOW,
        finished_at=NOW,
        status=status,
        exit_code=0 if status is ToolExecutionStatus.SUCCEEDED else 1,
        error_summary=(
            None
            if status is ToolExecutionStatus.SUCCEEDED
            else "synthetic analyzer failure"
        ),
    )
