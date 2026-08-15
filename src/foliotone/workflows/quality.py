"""Versioned, deterministic e-book quality assessment from bounded evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from foliotone.core import EntityId

if TYPE_CHECKING:
    from foliotone.workflows.ebook import EbookAnalysisStepOutcome

EBOOK_QUALITY_PROFILE = "ebook-quality/v1"
EBOOK_QUALITY_MIN_TEXT_CHARACTERS = 2000
_EBOOK_FORMATS = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")
_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


class EbookQualityStatus(StrEnum):
    """Aggregate quality state with incomplete evidence taking precedence."""

    OK = "OK"
    REVIEW = "REVIEW"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    INCOMPLETE = "INCOMPLETE"


class EbookQualityDimensionName(StrEnum):
    """Stable dimensions evaluated independently for collection reporting."""

    METADATA = "METADATA"
    TEXT = "TEXT"
    COVER = "COVER"
    STRUCTURE = "STRUCTURE"
    FORMAT_RISK = "FORMAT_RISK"


class EbookQualityDimensionStatus(StrEnum):
    """State of one quality dimension."""

    OK = "OK"
    REVIEW = "REVIEW"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EbookQualityFindingSeverity(StrEnum):
    """Stable severity independent from the aggregate quality state."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class EbookQualityFinding:
    """One stable finding backed by the exact available ToolExecutions."""

    code: str
    dimension: EbookQualityDimensionName
    severity: EbookQualityFindingSeverity
    source_execution_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if _FINDING_CODE.fullmatch(self.code) is None:
            raise ValueError("quality finding code must be bounded uppercase snake case")
        if len(self.source_execution_ids) != len(set(self.source_execution_ids)):
            raise ValueError("quality finding execution IDs must be unique")


@dataclass(frozen=True, slots=True)
class EbookQualityDimension:
    """Deterministic result for one quality dimension."""

    name: EbookQualityDimensionName
    status: EbookQualityDimensionStatus


@dataclass(frozen=True, slots=True)
class EbookQualityAssessment:
    """Versioned quality projection for one exact observed e-book file."""

    observation_id: EntityId
    format_name: str
    dimensions: tuple[EbookQualityDimension, ...]
    findings: tuple[EbookQualityFinding, ...]
    source_execution_ids: tuple[EntityId, ...]
    profile: str = EBOOK_QUALITY_PROFILE

    def __post_init__(self) -> None:
        if self.format_name not in _EBOOK_FORMATS:
            raise ValueError("quality assessment format is not supported")
        expected = tuple(EbookQualityDimensionName)
        names = tuple(dimension.name for dimension in self.dimensions)
        if names != expected:
            raise ValueError("quality dimensions must use the stable complete order")
        if not self.profile.strip():
            raise ValueError("quality profile must not be empty")
        if len(self.source_execution_ids) != len(set(self.source_execution_ids)):
            raise ValueError("quality assessment execution IDs must be unique")
        codes = tuple(finding.code for finding in self.findings)
        if len(codes) != len(set(codes)):
            raise ValueError("quality finding codes must be unique within an assessment")
        source_ids = set(self.source_execution_ids)
        if any(
            execution_id not in source_ids
            for finding in self.findings
            for execution_id in finding.source_execution_ids
        ):
            raise ValueError("quality finding execution IDs must belong to the assessment")

    @property
    def status(self) -> EbookQualityStatus:
        """Aggregate dimensions without converting missing evidence into bad media."""
        states = {dimension.status for dimension in self.dimensions}
        if EbookQualityDimensionStatus.INCOMPLETE in states:
            return EbookQualityStatus.INCOMPLETE
        if EbookQualityDimensionStatus.ACTION_REQUIRED in states:
            return EbookQualityStatus.ACTION_REQUIRED
        if EbookQualityDimensionStatus.REVIEW in states:
            return EbookQualityStatus.REVIEW
        return EbookQualityStatus.OK


def evaluate_ebook_quality(
    observation_id: EntityId,
    format_name: str,
    steps: tuple[EbookAnalysisStepOutcome, ...],
) -> EbookQualityAssessment:
    """Project bounded workflow facts into the versioned quality profile."""
    if format_name not in _EBOOK_FORMATS:
        raise ValueError("quality assessment format is not supported")

    by_name = {step.name: step for step in steps}
    if len(by_name) != len(steps):
        raise ValueError("quality assessment requires unique workflow step names")
    expected_steps = (
        {"pdf-analysis"}
        if format_name == "PDF"
        else {"metadata", "text", "cover"}
        | ({"structural-validation"} if format_name == "EPUB" else set())
    )
    if set(by_name) != expected_steps:
        raise ValueError("quality assessment received an inconsistent workflow plan")

    dimensions: list[EbookQualityDimension] = []
    findings: list[EbookQualityFinding] = []
    if format_name == "PDF":
        pdf_step = by_name["pdf-analysis"]
        metadata_dimension, metadata_findings = _pdf_metadata_quality(pdf_step)
        text_dimension, text_findings = _pdf_text_quality(pdf_step)
        cover_dimension = EbookQualityDimension(
            EbookQualityDimensionName.COVER,
            EbookQualityDimensionStatus.NOT_APPLICABLE,
        )
        structure_dimension = EbookQualityDimension(
            EbookQualityDimensionName.STRUCTURE,
            EbookQualityDimensionStatus.NOT_APPLICABLE,
        )
        format_dimension, format_findings = _pdf_format_quality(pdf_step)
        dimensions.extend(
            (
                metadata_dimension,
                text_dimension,
                cover_dimension,
                structure_dimension,
                format_dimension,
            )
        )
        findings.extend(metadata_findings + text_findings + format_findings)
    else:
        metadata_dimension, metadata_findings = _calibre_metadata_quality(
            by_name["metadata"]
        )
        text_dimension, text_findings = _calibre_text_quality(by_name["text"])
        cover_dimension, cover_findings = _cover_quality(by_name["cover"])
        if format_name == "EPUB":
            structure_dimension, structure_findings = _epub_structure_quality(
                by_name["structural-validation"]
            )
            format_findings = ()
        else:
            structure_dimension = EbookQualityDimension(
                EbookQualityDimensionName.STRUCTURE,
                EbookQualityDimensionStatus.NOT_APPLICABLE,
            )
            structure_findings = ()
            format_findings = (
                _finding(
                    "STRUCTURAL_VALIDATION_UNAVAILABLE",
                    EbookQualityDimensionName.FORMAT_RISK,
                    EbookQualityFindingSeverity.INFO,
                ),
            )
        format_dimension = EbookQualityDimension(
            EbookQualityDimensionName.FORMAT_RISK,
            EbookQualityDimensionStatus.OK,
        )
        dimensions.extend(
            (
                metadata_dimension,
                text_dimension,
                cover_dimension,
                structure_dimension,
                format_dimension,
            )
        )
        findings.extend(
            metadata_findings
            + text_findings
            + cover_findings
            + structure_findings
            + format_findings
        )

    execution_ids = tuple(
        execution.id for step in steps for execution in step.executions
    )
    return EbookQualityAssessment(
        observation_id=observation_id,
        format_name=format_name,
        dimensions=tuple(dimensions),
        findings=tuple(findings),
        source_execution_ids=execution_ids,
    )


def _calibre_metadata_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step)
    if not _step_succeeded(step):
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "METADATA_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    facts = dict(step.facts)
    keys = (
        "title_present",
        "author_present",
        "contributor_present",
        "language_present",
        "identifier_present",
        "publisher_present",
        "publication_date_present",
        "series_present",
        "series_position_present",
    )
    parsed = {key: _boolean(facts.get(key)) for key in keys}
    if any(value is None for value in parsed.values()):
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "METADATA_EVIDENCE_INCOMPLETE",
            execution_ids,
        )
    values = {key: bool(value) for key, value in parsed.items()}
    if values["author_present"] and not values["contributor_present"]:
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "METADATA_EVIDENCE_INCONSISTENT",
            execution_ids,
        )
    if values["series_position_present"] and not values["series_present"]:
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "METADATA_EVIDENCE_INCONSISTENT",
            execution_ids,
        )

    findings: list[EbookQualityFinding] = []
    for key, code in (
        ("title_present", "METADATA_TITLE_MISSING"),
        ("author_present", "METADATA_AUTHOR_MISSING"),
        ("language_present", "METADATA_LANGUAGE_MISSING"),
    ):
        if not values[key]:
            findings.append(
                _finding(
                    code,
                    EbookQualityDimensionName.METADATA,
                    EbookQualityFindingSeverity.WARNING,
                    execution_ids,
                )
            )
    if not values["identifier_present"]:
        findings.append(
            _finding(
                "METADATA_IDENTIFIER_MISSING",
                EbookQualityDimensionName.METADATA,
                EbookQualityFindingSeverity.INFO,
                execution_ids,
            )
        )
    if not values["publisher_present"] and not values["publication_date_present"]:
        findings.append(
            _finding(
                "METADATA_PUBLICATION_CONTEXT_MISSING",
                EbookQualityDimensionName.METADATA,
                EbookQualityFindingSeverity.INFO,
                execution_ids,
            )
        )
    if values["series_present"] and not values["series_position_present"]:
        findings.append(
            _finding(
                "METADATA_SERIES_POSITION_MISSING",
                EbookQualityDimensionName.METADATA,
                EbookQualityFindingSeverity.INFO,
                execution_ids,
            )
        )
    status = (
        EbookQualityDimensionStatus.REVIEW
        if any(
            finding.severity is EbookQualityFindingSeverity.WARNING
            for finding in findings
        )
        else EbookQualityDimensionStatus.OK
    )
    return EbookQualityDimension(EbookQualityDimensionName.METADATA, status), tuple(
        findings
    )


def _pdf_metadata_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step, index=0)
    if not _execution_succeeded(step, 0):
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "PDF_METADATA_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    facts = dict(step.facts)
    title_present = _boolean(facts.get("title_present"))
    author_present = _boolean(facts.get("author_present"))
    if title_present is None or author_present is None:
        return _incomplete(
            EbookQualityDimensionName.METADATA,
            "PDF_METADATA_EVIDENCE_INCOMPLETE",
            execution_ids,
        )
    findings = tuple(
        _finding(
            code,
            EbookQualityDimensionName.METADATA,
            EbookQualityFindingSeverity.WARNING,
            execution_ids,
        )
        for present, code in (
            (title_present, "METADATA_TITLE_MISSING"),
            (author_present, "METADATA_AUTHOR_MISSING"),
        )
        if not present
    )
    status = (
        EbookQualityDimensionStatus.REVIEW
        if findings
        else EbookQualityDimensionStatus.OK
    )
    return EbookQualityDimension(EbookQualityDimensionName.METADATA, status), findings


def _calibre_text_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    if not _step_succeeded(step):
        return _incomplete(
            EbookQualityDimensionName.TEXT,
            "TEXT_ANALYSIS_INCOMPLETE",
            _execution_ids(step),
        )
    return _text_facts_quality(dict(step.facts), _execution_ids(step), pdf=False)


def _pdf_text_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step, index=1)
    if not _execution_succeeded(step, 1):
        return _incomplete(
            EbookQualityDimensionName.TEXT,
            "TEXT_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    return _text_facts_quality(dict(step.facts), execution_ids, pdf=True)


def _text_facts_quality(
    facts: dict[str, str],
    execution_ids: tuple[EntityId, ...],
    *,
    pdf: bool,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    text_status = facts.get("text_status")
    character_count = _nonnegative_integer(facts.get("normalized_character_count"))
    if text_status not in {"TEXT_EXTRACTED", "NO_TEXT"} or character_count is None:
        return _incomplete(
            EbookQualityDimensionName.TEXT,
            "TEXT_EVIDENCE_INCOMPLETE",
            execution_ids,
        )
    if (text_status == "NO_TEXT") != (character_count == 0):
        return _incomplete(
            EbookQualityDimensionName.TEXT,
            "TEXT_EVIDENCE_INCONSISTENT",
            execution_ids,
        )
    if text_status == "NO_TEXT":
        findings = [
            _finding(
                "TEXT_NOT_AVAILABLE",
                EbookQualityDimensionName.TEXT,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            )
        ]
        if pdf:
            findings.append(
                _finding(
                    "PDF_OCR_CANDIDATE",
                    EbookQualityDimensionName.TEXT,
                    EbookQualityFindingSeverity.INFO,
                    execution_ids,
                )
            )
        return (
            EbookQualityDimension(
                EbookQualityDimensionName.TEXT,
                EbookQualityDimensionStatus.ACTION_REQUIRED,
            ),
            tuple(findings),
        )
    if character_count < EBOOK_QUALITY_MIN_TEXT_CHARACTERS:
        return (
            EbookQualityDimension(
                EbookQualityDimensionName.TEXT,
                EbookQualityDimensionStatus.REVIEW,
            ),
            (
                _finding(
                    "TEXT_VERY_SHORT",
                    EbookQualityDimensionName.TEXT,
                    EbookQualityFindingSeverity.WARNING,
                    execution_ids,
                ),
            ),
        )
    return (
        EbookQualityDimension(
            EbookQualityDimensionName.TEXT,
            EbookQualityDimensionStatus.OK,
        ),
        (),
    )


def _cover_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step)
    if not _step_succeeded(step):
        return _incomplete(
            EbookQualityDimensionName.COVER,
            "COVER_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    cover_status = dict(step.facts).get("cover_status")
    if cover_status == "COVER_EXTRACTED":
        return (
            EbookQualityDimension(
                EbookQualityDimensionName.COVER,
                EbookQualityDimensionStatus.OK,
            ),
            (),
        )
    if cover_status == "NO_EMBEDDED_COVER":
        return (
            EbookQualityDimension(
                EbookQualityDimensionName.COVER,
                EbookQualityDimensionStatus.REVIEW,
            ),
            (
                _finding(
                    "COVER_MISSING",
                    EbookQualityDimensionName.COVER,
                    EbookQualityFindingSeverity.WARNING,
                    execution_ids,
                ),
            ),
        )
    return _incomplete(
        EbookQualityDimensionName.COVER,
        "COVER_EVIDENCE_INCOMPLETE",
        execution_ids,
    )


def _epub_structure_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step)
    if not _step_succeeded(step):
        return _incomplete(
            EbookQualityDimensionName.STRUCTURE,
            "STRUCTURE_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    facts = dict(step.facts)
    conformance = facts.get("conformance_status")
    fatal_count = _nonnegative_integer(facts.get("fatal_count"))
    error_count = _nonnegative_integer(facts.get("error_count"))
    warning_count = _nonnegative_integer(facts.get("warning_count"))
    if (
        conformance not in {"CONFORMANT", "NONCONFORMANT"}
        or fatal_count is None
        or error_count is None
        or warning_count is None
    ):
        return _incomplete(
            EbookQualityDimensionName.STRUCTURE,
            "STRUCTURE_EVIDENCE_INCOMPLETE",
            execution_ids,
        )
    if conformance == "CONFORMANT" and (fatal_count or error_count):
        return _incomplete(
            EbookQualityDimensionName.STRUCTURE,
            "STRUCTURE_EVIDENCE_INCONSISTENT",
            execution_ids,
        )

    findings: list[EbookQualityFinding] = []
    if fatal_count:
        findings.append(
            _finding(
                "EPUB_FATAL_ERRORS",
                EbookQualityDimensionName.STRUCTURE,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            )
        )
    if error_count:
        findings.append(
            _finding(
                "EPUB_VALIDATION_ERRORS",
                EbookQualityDimensionName.STRUCTURE,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            )
        )
    if conformance == "NONCONFORMANT" and not fatal_count and not error_count:
        findings.append(
            _finding(
                "EPUB_NONCONFORMANT",
                EbookQualityDimensionName.STRUCTURE,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            )
        )
    if warning_count:
        findings.append(
            _finding(
                "EPUB_VALIDATION_WARNINGS",
                EbookQualityDimensionName.STRUCTURE,
                EbookQualityFindingSeverity.WARNING,
                execution_ids,
            )
        )
    status = EbookQualityDimensionStatus.OK
    if any(
        finding.severity is EbookQualityFindingSeverity.ERROR for finding in findings
    ):
        status = EbookQualityDimensionStatus.ACTION_REQUIRED
    elif findings:
        status = EbookQualityDimensionStatus.REVIEW
    return EbookQualityDimension(EbookQualityDimensionName.STRUCTURE, status), tuple(
        findings
    )


def _pdf_format_quality(
    step: EbookAnalysisStepOutcome,
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    execution_ids = _execution_ids(step, index=0)
    if not _execution_succeeded(step, 0):
        return _incomplete(
            EbookQualityDimensionName.FORMAT_RISK,
            "PDF_FORMAT_ANALYSIS_INCOMPLETE",
            execution_ids,
        )
    facts = dict(step.facts)
    page_count = _nonnegative_integer(facts.get("page_count"))
    encrypted = facts.get("encrypted", "").strip().lower()
    if page_count is None or page_count == 0 or not (
        encrypted == "no" or encrypted.startswith("yes")
    ):
        return _incomplete(
            EbookQualityDimensionName.FORMAT_RISK,
            "PDF_FORMAT_EVIDENCE_INCOMPLETE",
            execution_ids,
        )
    findings = [
        _finding(
            "STRUCTURAL_VALIDATION_UNAVAILABLE",
            EbookQualityDimensionName.FORMAT_RISK,
            EbookQualityFindingSeverity.INFO,
            execution_ids,
        )
    ]
    status = EbookQualityDimensionStatus.OK
    if encrypted.startswith("yes"):
        findings.insert(
            0,
            _finding(
                "PDF_ENCRYPTED",
                EbookQualityDimensionName.FORMAT_RISK,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            ),
        )
        status = EbookQualityDimensionStatus.ACTION_REQUIRED
    return EbookQualityDimension(EbookQualityDimensionName.FORMAT_RISK, status), tuple(
        findings
    )


def _incomplete(
    dimension: EbookQualityDimensionName,
    code: str,
    execution_ids: tuple[EntityId, ...],
) -> tuple[EbookQualityDimension, tuple[EbookQualityFinding, ...]]:
    return (
        EbookQualityDimension(dimension, EbookQualityDimensionStatus.INCOMPLETE),
        (
            _finding(
                code,
                dimension,
                EbookQualityFindingSeverity.ERROR,
                execution_ids,
            ),
        ),
    )


def _finding(
    code: str,
    dimension: EbookQualityDimensionName,
    severity: EbookQualityFindingSeverity,
    execution_ids: tuple[EntityId, ...] = (),
) -> EbookQualityFinding:
    return EbookQualityFinding(code, dimension, severity, execution_ids)


def _step_succeeded(step: EbookAnalysisStepOutcome) -> bool:
    return step.state.value == "SUCCEEDED"


def _execution_succeeded(step: EbookAnalysisStepOutcome, index: int) -> bool:
    return (
        len(step.executions) > index
        and step.executions[index].status.value == "SUCCEEDED"
    )


def _execution_ids(
    step: EbookAnalysisStepOutcome,
    *,
    index: int | None = None,
) -> tuple[EntityId, ...]:
    if index is None:
        return tuple(execution.id for execution in step.executions)
    if len(step.executions) <= index:
        return ()
    return (step.executions[index].id,)


def _boolean(value: str | None) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _nonnegative_integer(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)
