from __future__ import annotations

from dataclasses import replace

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_QUALITY_EVIDENCE_PROFILE,
    ConsolidationFileRole,
    ConsolidationQualityDimension,
    ConsolidationQualityEvidence,
    KeepPreferenceAssessment,
    KeepPreferenceInputs,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
    SizeTieBreakerPolicy,
    build_keep_preference,
    consolidation_quality_evidence_fingerprint,
)
from foliotone.core import EbookCollectionItemStatus, EntityId
from foliotone.workflows.quality import (
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityStatus,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _id(number: int) -> EntityId:
    return EntityId.parse(f"00000000-0000-4000-8000-{number:012d}")


def _assessment(observation_id: EntityId, fingerprint: str, *bad: int) -> KeepPreferenceAssessment:
    states = [EbookQualityDimensionStatus.OK] * 5
    for index, status in zip(
        bad,
        (
            EbookQualityDimensionStatus.INCOMPLETE,
            EbookQualityDimensionStatus.ACTION_REQUIRED,
            EbookQualityDimensionStatus.REVIEW,
        ),
        strict=False,
    ):
        states[index] = status
    return KeepPreferenceAssessment(observation_id, "EPUB", tuple(states), fingerprint)


def _inputs(
    left: KeepPreferenceAssessment,
    right: KeepPreferenceAssessment,
    *,
    format_preferences: tuple[str, ...] = (),
    size_tie_breaker_policy: SizeTieBreakerPolicy = SizeTieBreakerPolicy.DISABLED,
    left_size_bytes: int | None = None,
    right_size_bytes: int | None = None,
    **kwargs: object,
) -> KeepPreferenceInputs:
    evidence = (_evidence(30, left), _evidence(35, right))
    return KeepPreferenceInputs(
        preference_id=_id(40),
        left_file_id=_id(1),
        left_observation_id=left.observation_id,
        right_file_id=_id(2),
        right_observation_id=right.observation_id,
        quality_evidence=evidence,
        format_preferences=format_preferences,
        size_tie_breaker_policy=size_tie_breaker_policy,
        left_size_bytes=left_size_bytes,
        right_size_bytes=right_size_bytes,
        **kwargs,
    )


def _evidence(number: int, assessment: KeepPreferenceAssessment) -> ConsolidationQualityEvidence:
    dimensions = tuple(
        ConsolidationQualityDimension(name, status)
        for name, status in zip(
            EbookQualityDimensionName,
            assessment.dimensions,
            strict=True,
        )
    )
    material = {
        "profile": CONSOLIDATION_QUALITY_EVIDENCE_PROFILE,
        "collection_run_id": _id(number + 1),
        "collection_item_id": _id(number + 2),
        "observation_id": assessment.observation_id,
        "scan_root_id": _id(33),
        "source_scan_run_id": _id(34),
        "collection_profile": CONSOLIDATION_COLLECTION_PROFILE,
        "analysis_profile": CONSOLIDATION_ANALYSIS_PROFILE,
        "quality_profile": "ebook-quality/v1",
        "format_label": assessment.format_label,
        "item_status": EbookCollectionItemStatus.SUCCEEDED,
        "aggregate_quality_status": _aggregate(assessment.dimensions),
        "reused_step_count": 0,
        "executed_step_count": 0,
        "finding_count": 0,
        "dimensions": dimensions,
        "item_executions": (),
        "findings": (),
    }
    return ConsolidationQualityEvidence(
        id=_id(number),
        **material,
        assessment_fingerprint=consolidation_quality_evidence_fingerprint(**material),
    )


def _aggregate(states: tuple[EbookQualityDimensionStatus, ...]) -> EbookQualityStatus:
    if EbookQualityDimensionStatus.INCOMPLETE in states:
        return EbookQualityStatus.INCOMPLETE
    if EbookQualityDimensionStatus.ACTION_REQUIRED in states:
        return EbookQualityStatus.ACTION_REQUIRED
    if EbookQualityDimensionStatus.REVIEW in states:
        return EbookQualityStatus.REVIEW
    return EbookQualityStatus.OK


def test_quality_dimensions_are_compared_in_contract_order() -> None:
    outcome = build_keep_preference(
        _inputs(
            _assessment(_id(10), _HASH_A, 0, 1),
            _assessment(_id(11), _HASH_B, 0),
        )
    )
    assert outcome.status is KeepPreferenceStatus.PREFERRED
    assert outcome.keeper_file_id == _id(2)
    assert outcome.reason_codes == (KeepPreferenceReasonCode.FEWER_ACTION_REQUIRED_DIMENSIONS,)


def test_format_preference_only_breaks_a_quality_tie() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = replace(_assessment(_id(11), _HASH_B), format_label="PDF")
    outcome = build_keep_preference(_inputs(left, right, format_preferences=("PDF", "EPUB")))
    assert outcome.status is KeepPreferenceStatus.PREFERRED
    assert outcome.keeper_file_id == _id(2)
    assert outcome.reason_codes == (KeepPreferenceReasonCode.PREFERRED_FORMAT,)
    assert outcome.quality_evidence[0].observation_id == right.observation_id
    assert outcome.quality_evidence[1].observation_id == left.observation_id


def test_unlisted_formats_have_no_implicit_order_and_default_size_is_disabled() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = replace(_assessment(_id(11), _HASH_B), format_label="PDF")
    outcome = build_keep_preference(_inputs(left, right, left_size_bytes=10, right_size_bytes=20))
    assert outcome.status is KeepPreferenceStatus.TIED
    assert outcome.reason_codes == (KeepPreferenceReasonCode.TIED,)
    assert outcome.keeper_file_id is None
    assert outcome.quality_evidence[0].observation_id == left.observation_id
    assert outcome.quality_evidence[1].observation_id == right.observation_id


def test_size_is_only_the_last_explicit_tie_breaker() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = replace(_assessment(_id(11), _HASH_B), format_label="PDF")
    outcome = build_keep_preference(
        _inputs(
            left,
            right,
            size_tie_breaker_policy=SizeTieBreakerPolicy.PREFER_SMALLER,
            left_size_bytes=10,
            right_size_bytes=20,
        )
    )
    assert outcome.status is KeepPreferenceStatus.PREFERRED
    assert outcome.keeper_file_id == _id(1)
    assert outcome.reason_codes == (KeepPreferenceReasonCode.SIZE_TIE_BREAKER,)


def test_hard_constraint_wins_before_quality_and_has_no_direction() -> None:
    outcome = build_keep_preference(
        _inputs(
            _assessment(_id(10), _HASH_A),
            _assessment(_id(11), _HASH_B, 0, 1, 2),
            protected_source_root=True,
        )
    )
    assert outcome.status is KeepPreferenceStatus.BLOCKED
    assert outcome.keeper_file_id is None
    assert outcome.candidate_file_id is None
    assert outcome.reason_codes == (KeepPreferenceReasonCode.HARD_CONSTRAINT,)
    assert outcome.quality_evidence[0].observation_id == outcome.left_observation_id
    assert outcome.quality_evidence[1].observation_id == outcome.right_observation_id


def test_fingerprints_are_deterministic_and_do_not_use_paths_or_ids_as_tie_breakers() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = replace(_assessment(_id(11), _HASH_B), format_label="PDF")
    first = build_keep_preference(_inputs(left, right))
    second = build_keep_preference(_inputs(left, right))
    assert first == second
    assert first.status is KeepPreferenceStatus.TIED
    assert first.candidate_set_fingerprint
    assert first.evidence_fingerprint


def test_format_preferences_are_normalized_before_duplicate_validation() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = replace(_assessment(_id(11), _HASH_B), format_label="PDF")
    with pytest.raises(ValueError, match="duplicates"):
        _inputs(left, right, format_preferences=("epub", "EPUB"))


def test_quality_evidence_ids_are_distinct_and_output_roles_are_canonical() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = _assessment(_id(11), _HASH_B, 0)
    inputs = _inputs(left, right)
    duplicate = replace(inputs.quality_evidence[1], id=inputs.quality_evidence[0].id)
    with pytest.raises(ValueError, match="distinct ids"):
        replace(inputs, quality_evidence=(inputs.quality_evidence[0], duplicate))

    outcome = build_keep_preference(
        replace(inputs, quality_evidence=tuple(reversed(inputs.quality_evidence)))
    )
    assert tuple(item.role for item in outcome.quality_evidence) == (
        ConsolidationFileRole.KEEPER,
        ConsolidationFileRole.CANDIDATE,
    )
    assert outcome.quality_evidence[0].observation_id == outcome.left_observation_id

    foreign_observation = replace(outcome.quality_evidence[0], observation_id=_id(99))
    with pytest.raises(ValueError, match="match both endpoints"):
        replace(
            outcome,
            quality_evidence=(foreign_observation, outcome.quality_evidence[1]),
        )


def test_non_decisive_dimension_changes_are_material_to_fingerprints() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = _assessment(_id(11), _HASH_B)
    first = build_keep_preference(_inputs(left, right))
    changed_left = replace(
        left,
        dimensions=(
            EbookQualityDimensionStatus.NOT_APPLICABLE,
            *left.dimensions[1:],
        ),
    )
    second = build_keep_preference(_inputs(changed_left, right))
    assert first.status is second.status is KeepPreferenceStatus.TIED
    assert first.reason_codes == second.reason_codes
    assert first.candidate_set_fingerprint != second.candidate_set_fingerprint
    assert first.evidence_fingerprint != second.evidence_fingerprint


def test_size_evidence_changes_invalidate_preference_evidence() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = _assessment(_id(11), _HASH_B)
    first = build_keep_preference(
        _inputs(
            left,
            right,
            size_tie_breaker_policy=SizeTieBreakerPolicy.PREFER_SMALLER,
            left_size_bytes=10,
            right_size_bytes=20,
        )
    )
    second = build_keep_preference(
        _inputs(
            left,
            right,
            size_tie_breaker_policy=SizeTieBreakerPolicy.PREFER_SMALLER,
            left_size_bytes=11,
            right_size_bytes=20,
        )
    )
    assert first.keeper_file_id == second.keeper_file_id
    assert first.reason_codes == second.reason_codes
    assert first.candidate_set_fingerprint == second.candidate_set_fingerprint
    assert first.evidence_fingerprint != second.evidence_fingerprint


def test_different_hard_constraint_causes_have_distinct_evidence() -> None:
    left = _assessment(_id(10), _HASH_A)
    right = _assessment(_id(11), _HASH_B)
    protected = build_keep_preference(_inputs(left, right, protected_source_root=True))
    lineage = build_keep_preference(_inputs(left, right, lineage_complete=False))
    assert protected.status is lineage.status is KeepPreferenceStatus.BLOCKED
    assert protected.reason_codes == lineage.reason_codes
    assert protected.evidence_fingerprint != lineage.evidence_fingerprint
