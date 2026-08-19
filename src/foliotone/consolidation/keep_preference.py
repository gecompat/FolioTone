"""Pure, versioned keep-preference evaluation for consolidation planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Final

from foliotone.consolidation.contracts import (
    CONSOLIDATION_KEEP_PREFERENCE_PROFILE,
    CONSOLIDATION_KEEP_PREFERENCE_VERSION,
    ConsolidationBlockerCode,
    ConsolidationFileRole,
    ConsolidationQualityEvidenceSnapshot,
    KeepPreferenceOutcome,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
    SizeTieBreakerPolicy,
)
from foliotone.core import EntityId
from foliotone.workflows.quality import (
    EbookQualityAssessment,
    EbookQualityDimensionStatus,
)

_SUPPORTED_FORMATS: Final = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PDF"})
_QUALITY_ORDER: Final = (
    EbookQualityDimensionStatus.INCOMPLETE,
    EbookQualityDimensionStatus.ACTION_REQUIRED,
    EbookQualityDimensionStatus.REVIEW,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _id(value: EntityId, name: str) -> EntityId:
    if not isinstance(value, EntityId):
        raise ValueError(f"{name} must be an EntityId")
    return value


@dataclass(frozen=True, slots=True)
class KeepPreferenceAssessment:
    """The bounded quality projection consumed by the preference evaluator.

    The assessment deliberately carries only dimension states and the
    persisted material fingerprint.  It never contains a path or source
    media handle.
    """

    observation_id: EntityId
    format_label: str
    dimensions: tuple[EbookQualityDimensionStatus, ...]
    assessment_fingerprint: str

    def __post_init__(self) -> None:
        _id(self.observation_id, "observation_id")
        format_label = self.format_label.strip().upper()
        if format_label not in _SUPPORTED_FORMATS:
            raise ValueError("format_label is not supported")
        object.__setattr__(self, "format_label", format_label)
        if len(self.dimensions) != 5 or any(
            not isinstance(value, EbookQualityDimensionStatus) for value in self.dimensions
        ):
            raise ValueError("dimensions must contain the five quality dimension states")
        if (
            not isinstance(self.assessment_fingerprint, str)
            or len(self.assessment_fingerprint) != 64
            or self.assessment_fingerprint != self.assessment_fingerprint.lower()
            or any(char not in "0123456789abcdef" for char in self.assessment_fingerprint)
        ):
            raise ValueError("assessment_fingerprint must be a lowercase SHA-256")

    @classmethod
    def from_quality_assessment(
        cls, assessment: EbookQualityAssessment
    ) -> KeepPreferenceAssessment:
        """Adapt the existing quality projection without recalculating it."""

        if not isinstance(assessment, EbookQualityAssessment):
            raise TypeError("assessment must be an EbookQualityAssessment")
        return cls(
            observation_id=assessment.observation_id,
            format_label=assessment.format_name,
            dimensions=tuple(item.status for item in assessment.dimensions),
            assessment_fingerprint=_digest(
                {
                    "profile": assessment.profile,
                    "observation_id": str(assessment.observation_id),
                    "format_label": assessment.format_name,
                    "dimensions": [item.status.value for item in assessment.dimensions],
                    "findings": [
                        {
                            "code": item.code,
                            "dimension": item.dimension.value,
                            "severity": item.severity.value,
                            "source_execution_ids": [
                                str(value) for value in item.source_execution_ids
                            ],
                        }
                        for item in assessment.findings
                    ],
                    "source_execution_ids": [
                        str(value) for value in assessment.source_execution_ids
                    ],
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class KeepPreferenceInputs:
    """Immutable, path-free input for :func:`build_keep_preference`."""

    preference_id: EntityId
    left_file_id: EntityId
    left_observation_id: EntityId
    right_file_id: EntityId
    right_observation_id: EntityId
    quality_evidence: tuple[ConsolidationQualityEvidenceSnapshot, ...]
    assessments: tuple[KeepPreferenceAssessment, ...]
    format_preferences: tuple[str, ...] = ()
    size_tie_breaker_policy: SizeTieBreakerPolicy = SizeTieBreakerPolicy.DISABLED
    left_size_bytes: int | None = None
    right_size_bytes: int | None = None
    hard_blockers: tuple[ConsolidationBlockerCode, ...] = ()
    protected_source_root: bool = False
    lineage_complete: bool = True
    full_hash_evidence: bool = True
    blocking_dependency: bool = False

    def __post_init__(self) -> None:
        _id(self.preference_id, "preference_id")
        for name in (
            "left_file_id",
            "left_observation_id",
            "right_file_id",
            "right_observation_id",
        ):
            _id(getattr(self, name), name)
        if (
            self.left_file_id == self.right_file_id
            or str(self.left_file_id).casefold() >= str(self.right_file_id).casefold()
        ):
            raise ValueError("preference endpoints must be distinct and canonically ordered")
        if len(self.quality_evidence) != 2 or len(self.assessments) != 2:
            raise ValueError("exactly two quality evidence snapshots and assessments are required")
        if len({item.id for item in self.quality_evidence}) != 2:
            raise ValueError("quality evidence snapshots must have distinct ids")
        if {item.observation_id for item in self.assessments} != {
            self.left_observation_id,
            self.right_observation_id,
        }:
            raise ValueError("assessments must match both preference observations")
        evidence_observations = {item.observation_id for item in self.quality_evidence}
        if evidence_observations != {
            self.left_observation_id,
            self.right_observation_id,
        }:
            raise ValueError("quality evidence must match both preference observations")
        if any(
            item.assessment_fingerprint
            != next(
                assessment.assessment_fingerprint
                for assessment in self.assessments
                if assessment.observation_id == item.observation_id
            )
            for item in self.quality_evidence
        ):
            raise ValueError("quality evidence fingerprint does not match assessment")
        normalized_formats = tuple(value.strip().upper() for value in self.format_preferences)
        if any(value not in _SUPPORTED_FORMATS for value in normalized_formats):
            raise ValueError("format_preferences contains an unsupported format")
        if len(normalized_formats) != len(set(normalized_formats)):
            raise ValueError("format_preferences must not contain duplicates")
        object.__setattr__(self, "format_preferences", normalized_formats)
        if not isinstance(self.size_tie_breaker_policy, SizeTieBreakerPolicy):
            raise ValueError("size_tie_breaker_policy must be a SizeTieBreakerPolicy")
        for name in ("left_size_bytes", "right_size_bytes"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.size_tie_breaker_policy is not SizeTieBreakerPolicy.DISABLED and (
            self.left_size_bytes is None or self.right_size_bytes is None
        ):
            raise ValueError("an enabled size tie-breaker requires both sizes")
        if any(not isinstance(item, ConsolidationBlockerCode) for item in self.hard_blockers):
            raise ValueError("hard_blockers must contain ConsolidationBlockerCode values")
        for name in (
            "protected_source_root",
            "lineage_complete",
            "full_hash_evidence",
            "blocking_dependency",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")


def _assessment_by_observation(
    inputs: KeepPreferenceInputs,
) -> dict[EntityId, KeepPreferenceAssessment]:
    return {item.observation_id: item for item in inputs.assessments}


def _quality_counts(assessment: KeepPreferenceAssessment) -> tuple[int, int, int]:
    return tuple(assessment.dimensions.count(status) for status in _QUALITY_ORDER)  # type: ignore[return-value]


def _configuration_fingerprint(inputs: KeepPreferenceInputs) -> str:
    return _digest(
        {
            "domain": CONSOLIDATION_KEEP_PREFERENCE_PROFILE,
            "version": CONSOLIDATION_KEEP_PREFERENCE_VERSION,
            "format_preferences": list(inputs.format_preferences),
            "size_tie_breaker_policy": inputs.size_tie_breaker_policy.value,
        }
    )


def _assessment_material(assessment: KeepPreferenceAssessment) -> dict[str, object]:
    return {
        "observation_id": str(assessment.observation_id),
        "format_label": assessment.format_label,
        "dimensions": [value.value for value in assessment.dimensions],
        "assessment_fingerprint": assessment.assessment_fingerprint,
    }


def _candidate_set_fingerprint(
    inputs: KeepPreferenceInputs,
    configuration_fingerprint: str,
) -> str:
    assessments = _assessment_by_observation(inputs)
    ordered = sorted(
        (
            (str(inputs.left_file_id), inputs.left_observation_id),
            (str(inputs.right_file_id), inputs.right_observation_id),
        )
    )
    by_file = {
        str(inputs.left_file_id): inputs.left_observation_id,
        str(inputs.right_file_id): inputs.right_observation_id,
    }
    return _digest(
        {
            "domain": CONSOLIDATION_KEEP_PREFERENCE_PROFILE,
            "version": CONSOLIDATION_KEEP_PREFERENCE_VERSION,
            "possible_directions": [
                {"keeper_file_id": left[0], "candidate_file_id": right[0]}
                for left, right in (ordered, tuple(reversed(ordered)))
            ],
            "configuration_fingerprint": configuration_fingerprint,
            "assessment_fingerprints": [
                assessments[by_file[item[0]]].assessment_fingerprint for item in ordered
            ],
            "assessment_projections": [
                _assessment_material(assessments[by_file[item[0]]]) for item in ordered
            ],
        }
    )


def _evidence_fingerprint(
    inputs: KeepPreferenceInputs,
    configuration_fingerprint: str,
    candidate_set_fingerprint: str,
    status: KeepPreferenceStatus,
    reason_codes: tuple[KeepPreferenceReasonCode, ...],
    keeper_file_id: EntityId | None,
    candidate_file_id: EntityId | None,
    hard_constraint_material: dict[str, object],
) -> str:
    return _digest(
        {
            "domain": CONSOLIDATION_KEEP_PREFERENCE_PROFILE,
            "version": CONSOLIDATION_KEEP_PREFERENCE_VERSION,
            "left_file_id": str(inputs.left_file_id),
            "left_observation_id": str(inputs.left_observation_id),
            "right_file_id": str(inputs.right_file_id),
            "right_observation_id": str(inputs.right_observation_id),
            "status": status.value,
            "keeper_file_id": None if keeper_file_id is None else str(keeper_file_id),
            "candidate_file_id": None if candidate_file_id is None else str(candidate_file_id),
            "reason_codes": [item.value for item in reason_codes],
            "configuration_fingerprint": configuration_fingerprint,
            "candidate_set_fingerprint": candidate_set_fingerprint,
            "quality_evidence": sorted(
                (str(item.observation_id), item.assessment_fingerprint)
                for item in inputs.quality_evidence
            ),
            "assessment_projections": sorted(
                (_assessment_material(item) for item in inputs.assessments),
                key=lambda item: str(item["observation_id"]),
            ),
            "size_evidence": {
                "left_size_bytes": inputs.left_size_bytes,
                "right_size_bytes": inputs.right_size_bytes,
            },
            "hard_constraints": hard_constraint_material,
        }
    )


def _quality_evidence_for_output(
    inputs: KeepPreferenceInputs,
    keeper_file_id: EntityId | None,
) -> tuple[ConsolidationQualityEvidenceSnapshot, ...]:
    by_observation = {item.observation_id: item for item in inputs.quality_evidence}
    if keeper_file_id is None:
        keeper_observation_id = inputs.left_observation_id
    elif keeper_file_id == inputs.left_file_id:
        keeper_observation_id = inputs.left_observation_id
    else:
        keeper_observation_id = inputs.right_observation_id
    keeper = replace(by_observation[keeper_observation_id], role=ConsolidationFileRole.KEEPER)
    candidate = replace(
        by_observation[
            inputs.right_observation_id
            if keeper_observation_id == inputs.left_observation_id
            else inputs.left_observation_id
        ],
        role=ConsolidationFileRole.CANDIDATE,
    )
    return (keeper, candidate)


def build_keep_preference(inputs: KeepPreferenceInputs) -> KeepPreferenceOutcome:
    """Evaluate two already-reviewed quality projections deterministically."""

    if not isinstance(inputs, KeepPreferenceInputs):
        raise TypeError("inputs must be KeepPreferenceInputs")
    config_fingerprint = _configuration_fingerprint(inputs)
    candidate_set_fingerprint = _candidate_set_fingerprint(inputs, config_fingerprint)
    hard_constraints = list(inputs.hard_blockers)
    if inputs.protected_source_root:
        hard_constraints.append(ConsolidationBlockerCode.PROTECTED_SOURCE_ROOT)
    if not inputs.lineage_complete:
        hard_constraints.append(ConsolidationBlockerCode.LINEAGE_MISMATCH)
    evidence_by_observation = {
        item.observation_id: item for item in inputs.quality_evidence
    }
    quality_lineage_mismatch = (
        len({item.scan_root_id for item in inputs.quality_evidence}) != 1
        or len({item.source_scan_run_id for item in inputs.quality_evidence}) != 1
        or any(
            evidence_by_observation[assessment.observation_id].format_label
            != assessment.format_label
            for assessment in inputs.assessments
        )
    )
    if quality_lineage_mismatch:
        hard_constraints.append(ConsolidationBlockerCode.LINEAGE_MISMATCH)
    if not inputs.full_hash_evidence:
        hard_constraints.append(ConsolidationBlockerCode.PRECONDITION_INCOMPLETE)
    if inputs.blocking_dependency:
        hard_constraints.append(ConsolidationBlockerCode.PRECONDITION_INCOMPLETE)
    hard_constraint_material: dict[str, object] = {
        "codes": sorted({item.value for item in hard_constraints}),
        "protected_source_root": inputs.protected_source_root,
        "lineage_complete": inputs.lineage_complete,
        "quality_lineage_mismatch": quality_lineage_mismatch,
        "full_hash_evidence": inputs.full_hash_evidence,
        "blocking_dependency": inputs.blocking_dependency,
    }
    hard = bool(hard_constraints)
    assessments = _assessment_by_observation(inputs)
    left_assessment = assessments[inputs.left_observation_id]
    right_assessment = assessments[inputs.right_observation_id]
    keeper_file_id: EntityId | None = None
    candidate_file_id: EntityId | None = None
    reason_codes: tuple[KeepPreferenceReasonCode, ...]
    if hard:
        status = KeepPreferenceStatus.BLOCKED
        reason_codes = (KeepPreferenceReasonCode.HARD_CONSTRAINT,)
    else:
        left_counts = _quality_counts(left_assessment)
        right_counts = _quality_counts(right_assessment)
        reason_codes_list: list[KeepPreferenceReasonCode] = []
        winner: str | None = None
        for index, reason in enumerate(
            (
                KeepPreferenceReasonCode.FEWER_INCOMPLETE_DIMENSIONS,
                KeepPreferenceReasonCode.FEWER_ACTION_REQUIRED_DIMENSIONS,
                KeepPreferenceReasonCode.FEWER_REVIEW_DIMENSIONS,
            )
        ):
            if left_counts[index] < right_counts[index]:
                winner = "left"
                reason_codes_list.append(reason)
                break
            if right_counts[index] < left_counts[index]:
                winner = "right"
                reason_codes_list.append(reason)
                break
        if winner is None:
            preference_ranks = {
                value: index for index, value in enumerate(inputs.format_preferences)
            }
            left_rank = preference_ranks.get(left_assessment.format_label)
            right_rank = preference_ranks.get(right_assessment.format_label)
            if left_rank is not None and (right_rank is None or left_rank < right_rank):
                winner = "left"
                reason_codes_list.append(KeepPreferenceReasonCode.PREFERRED_FORMAT)
            elif right_rank is not None and (left_rank is None or right_rank < left_rank):
                winner = "right"
                reason_codes_list.append(KeepPreferenceReasonCode.PREFERRED_FORMAT)
        if winner is None and inputs.size_tie_breaker_policy is not SizeTieBreakerPolicy.DISABLED:
            assert inputs.left_size_bytes is not None and inputs.right_size_bytes is not None
            if inputs.left_size_bytes != inputs.right_size_bytes:
                prefer_smaller = (
                    inputs.size_tie_breaker_policy is SizeTieBreakerPolicy.PREFER_SMALLER
                )
                left_wins = inputs.left_size_bytes < inputs.right_size_bytes
                if not prefer_smaller:
                    left_wins = not left_wins
                winner = "left" if left_wins else "right"
                reason_codes_list.append(KeepPreferenceReasonCode.SIZE_TIE_BREAKER)
        if winner is None:
            status = KeepPreferenceStatus.TIED
            reason_codes = (KeepPreferenceReasonCode.TIED,)
        else:
            status = KeepPreferenceStatus.PREFERRED
            keeper_file_id = inputs.left_file_id if winner == "left" else inputs.right_file_id
            candidate_file_id = inputs.right_file_id if winner == "left" else inputs.left_file_id
            reason_codes = tuple(reason_codes_list)
    quality_evidence = _quality_evidence_for_output(inputs, keeper_file_id)
    evidence_fingerprint = _evidence_fingerprint(
        inputs,
        config_fingerprint,
        candidate_set_fingerprint,
        status,
        reason_codes,
        keeper_file_id,
        candidate_file_id,
        hard_constraint_material,
    )
    return KeepPreferenceOutcome(
        preference_id=inputs.preference_id,
        profile=CONSOLIDATION_KEEP_PREFERENCE_PROFILE,
        profile_version=CONSOLIDATION_KEEP_PREFERENCE_VERSION,
        left_file_id=inputs.left_file_id,
        left_observation_id=inputs.left_observation_id,
        right_file_id=inputs.right_file_id,
        right_observation_id=inputs.right_observation_id,
        status=status,
        keeper_file_id=keeper_file_id,
        candidate_file_id=candidate_file_id,
        reason_codes=reason_codes,
        configuration_fingerprint=config_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
        quality_evidence=quality_evidence,
        candidate_set_fingerprint=candidate_set_fingerprint,
    )


build_keep_preference_outcome = build_keep_preference
evaluate_keep_preference = build_keep_preference


__all__ = [
    "KeepPreferenceAssessment",
    "KeepPreferenceInputs",
    "build_keep_preference",
    "build_keep_preference_outcome",
    "evaluate_keep_preference",
]
