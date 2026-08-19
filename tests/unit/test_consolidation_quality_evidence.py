"""Focused synthetic contracts for persistable consolidation quality evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_QUALITY_EVIDENCE_PROFILE,
    MAX_CONSOLIDATION_QUALITY_EXECUTIONS,
    ConsolidationFileRole,
    ConsolidationQualityDimension,
    ConsolidationQualityEvidence,
    ConsolidationQualityExecutionDisposition,
    ConsolidationQualityFinding,
    ConsolidationQualityItemExecution,
    consolidation_quality_evidence_fingerprint,
)
from foliotone.core import EbookCollectionItemStatus, EntityId
from foliotone.workflows.quality import (
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityFindingSeverity,
    EbookQualityStatus,
)


def _id(number: int) -> EntityId:
    return EntityId.parse(f"00000000-0000-4000-8000-{number:012d}")


def _material() -> dict[str, object]:
    executions = (
        ConsolidationQualityItemExecution(
            0,
            "metadata",
            ConsolidationQualityExecutionDisposition.REUSED,
            _id(20),
        ),
        ConsolidationQualityItemExecution(
            1,
            "text",
            ConsolidationQualityExecutionDisposition.EXECUTED,
            _id(21),
        ),
        ConsolidationQualityItemExecution(
            2,
            "text",
            ConsolidationQualityExecutionDisposition.EXECUTED,
            _id(22),
        ),
    )
    dimensions = tuple(
        ConsolidationQualityDimension(name, EbookQualityDimensionStatus.OK)
        for name in EbookQualityDimensionName
    )
    findings = (
        ConsolidationQualityFinding(
            0,
            "STRUCTURAL_VALIDATION_UNAVAILABLE",
            EbookQualityDimensionName.FORMAT_RISK,
            EbookQualityFindingSeverity.INFO,
            (_id(21), _id(22), _id(20)),
        ),
    )
    return {
        "profile": CONSOLIDATION_QUALITY_EVIDENCE_PROFILE,
        "collection_run_id": _id(2),
        "collection_item_id": _id(3),
        "observation_id": _id(4),
        "scan_root_id": _id(5),
        "source_scan_run_id": _id(6),
        "collection_profile": CONSOLIDATION_COLLECTION_PROFILE,
        "analysis_profile": CONSOLIDATION_ANALYSIS_PROFILE,
        "quality_profile": "ebook-quality/v1",
        "format_label": "EPUB",
        "item_status": EbookCollectionItemStatus.SUCCEEDED,
        "aggregate_quality_status": EbookQualityStatus.OK,
        "reused_step_count": 1,
        "executed_step_count": 1,
        "finding_count": 1,
        "dimensions": dimensions,
        "item_executions": executions,
        "findings": findings,
    }


def _evidence() -> ConsolidationQualityEvidence:
    material = _material()
    return ConsolidationQualityEvidence(
        id=_id(1),
        **material,
        assessment_fingerprint=consolidation_quality_evidence_fingerprint(**material),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_projection_is_complete_role_free_bounded_and_path_free() -> None:
    evidence = _evidence()
    assert tuple(item.name for item in evidence.dimensions) == tuple(EbookQualityDimensionName)
    assert tuple(item.ordinal for item in evidence.item_executions) == (0, 1, 2)
    assert evidence.findings[0].source_execution_ids == (_id(21), _id(22), _id(20))
    assert not hasattr(evidence, "role")
    assert "path" not in repr(evidence).casefold()
    assert evidence.snapshot(ConsolidationFileRole.KEEPER).role is ConsolidationFileRole.KEEPER


def test_fingerprint_binds_all_material_but_not_identity_or_audit_time() -> None:
    evidence = _evidence()
    assert (
        evidence.assessment_fingerprint
        == "7b0a65d2222845e4f6182b86f9c8bcc57cbdc89c3cb51bf536cd4ea0e7862328"
    )
    assert replace(evidence, id=_id(99)).assessment_fingerprint == evidence.assessment_fingerprint
    assert (
        replace(
            evidence, created_at=evidence.created_at + timedelta(seconds=1)
        ).assessment_fingerprint
        == evidence.assessment_fingerprint
    )
    with pytest.raises(ValueError, match="assessment_fingerprint"):
        replace(evidence, format_label="PDF")
    with pytest.raises(ValueError, match="assessment_fingerprint"):
        replace(
            evidence,
            findings=(replace(evidence.findings[0], severity=EbookQualityFindingSeverity.WARNING),),
        )
    with pytest.raises(ValueError, match="assessment_fingerprint"):
        replace(
            evidence,
            item_executions=(
                evidence.item_executions[0],
                replace(evidence.item_executions[1], step_name="text-nfc"),
                replace(evidence.item_executions[2], step_name="text-nfc"),
            ),
        )


def test_every_declared_material_group_changes_the_fingerprint() -> None:
    material = _material()
    baseline = consolidation_quality_evidence_fingerprint(**material)
    changes: dict[str, object] = {
        "profile": "consolidation-quality-evidence/v2",
        "collection_run_id": _id(102),
        "collection_item_id": _id(103),
        "observation_id": _id(104),
        "scan_root_id": _id(105),
        "source_scan_run_id": _id(106),
        "collection_profile": "ebook-collection-analysis/v2",
        "analysis_profile": "ebook-analysis-workflow/v4",
        "quality_profile": "ebook-quality/v2",
        "format_label": "PDF",
        "item_status": EbookCollectionItemStatus.PARTIAL_FAILURE,
        "aggregate_quality_status": EbookQualityStatus.REVIEW,
        "reused_step_count": 2,
        "executed_step_count": 2,
        "finding_count": 2,
        "dimensions": (
            replace(material["dimensions"][0], status=EbookQualityDimensionStatus.REVIEW),
            *material["dimensions"][1:],
        ),
        "item_executions": (
            replace(material["item_executions"][0], step_name="metadata-v2"),
            *material["item_executions"][1:],
        ),
        "findings": (
            replace(material["findings"][0], severity=EbookQualityFindingSeverity.WARNING),
        ),
    }
    for field_name, changed_value in changes.items():
        changed = {**material, field_name: changed_value}
        assert consolidation_quality_evidence_fingerprint(**changed) != baseline


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    (
        ("reused_step_count", 0, "execution counts"),
        ("finding_count", 0, "finding_count"),
        ("aggregate_quality_status", EbookQualityStatus.REVIEW, "aggregate quality"),
    ),
)
def test_counts_and_aggregate_status_cannot_disagree(
    field_name: str, value: object, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        replace(_evidence(), **{field_name: value})


def test_child_order_duplicate_ids_and_foreign_finding_refs_are_rejected() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="contiguous and ordered"):
        replace(
            evidence,
            item_executions=(
                replace(evidence.item_executions[0], ordinal=1),
                replace(evidence.item_executions[1], ordinal=0),
                evidence.item_executions[2],
            ),
        )
    with pytest.raises(ValueError, match="execution IDs"):
        replace(
            evidence,
            item_executions=(
                evidence.item_executions[0],
                replace(evidence.item_executions[1], execution_id=_id(20)),
                evidence.item_executions[2],
            ),
        )
    with pytest.raises(ValueError, match="belong to the collection item"):
        replace(
            evidence,
            findings=(replace(evidence.findings[0], source_execution_ids=(_id(88),)),),
        )
    with pytest.raises(ValueError, match="configured limit"):
        replace(
            evidence,
            item_executions=tuple(
                ConsolidationQualityItemExecution(
                    ordinal,
                    f"step-{ordinal}",
                    ConsolidationQualityExecutionDisposition.EXECUTED,
                    _id(100 + ordinal),
                )
                for ordinal in range(MAX_CONSOLIDATION_QUALITY_EXECUTIONS + 1)
            ),
            reused_step_count=0,
            executed_step_count=MAX_CONSOLIDATION_QUALITY_EXECUTIONS + 1,
        )


def test_multi_execution_steps_are_counted_once_and_must_stay_contiguous() -> None:
    evidence = _evidence()
    assert evidence.executed_step_count == 1
    assert len(evidence.item_executions) == 3
    with pytest.raises(ValueError, match="cannot mix dispositions"):
        replace(
            evidence,
            item_executions=(
                evidence.item_executions[0],
                evidence.item_executions[1],
                replace(
                    evidence.item_executions[2],
                    disposition=ConsolidationQualityExecutionDisposition.REUSED,
                ),
            ),
        )
    with pytest.raises(ValueError, match="step groups must be contiguous"):
        replace(
            evidence,
            item_executions=(
                replace(evidence.item_executions[0], step_name="text"),
                replace(evidence.item_executions[1], step_name="metadata"),
                evidence.item_executions[2],
            ),
        )


def test_terminal_item_status_and_failed_quality_consistency_are_enforced() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="terminal item status"):
        replace(evidence, item_status=EbookCollectionItemStatus.ERROR)
    with pytest.raises(ValueError, match="require INCOMPLETE"):
        replace(evidence, item_status=EbookCollectionItemStatus.FAILED)


def test_profiles_and_five_dimension_order_are_exact() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="profiles"):
        replace(evidence, analysis_profile="ebook-analysis-workflow/v2")
    with pytest.raises(ValueError, match="five canonical dimensions"):
        replace(
            evidence,
            dimensions=tuple(reversed(evidence.dimensions)),
        )


def test_keep_preference_projection_consumes_persisted_material() -> None:
    evidence = _evidence()
    from foliotone.consolidation import KeepPreferenceAssessment

    assessment = KeepPreferenceAssessment.from_quality_evidence(evidence)
    assert assessment.observation_id == evidence.observation_id
    assert assessment.dimensions == tuple(item.status for item in evidence.dimensions)
    assert assessment.assessment_fingerprint == evidence.assessment_fingerprint
