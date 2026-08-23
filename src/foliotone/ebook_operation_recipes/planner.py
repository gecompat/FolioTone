"""Pure builders and reducer for non-executable e-book operation recipes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from foliotone.core import EntityId, PresenceState, ScanRunStatus
from foliotone.core._validation import require_aware_datetime
from foliotone.ebook_operation_recipes.contracts import (
    EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE,
    EBOOK_OPERATION_RECIPE_SERIALIZER,
    EbookOperationBlocker,
    EbookOperationBlockerCode,
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationEvidenceReference,
    EbookOperationExecutionState,
    EbookOperationExpectedOutput,
    EbookOperationKind,
    EbookOperationPlanStatus,
    EbookOperationPrecondition,
    EbookOperationPreconditionCode,
    EbookOperationProcessorKind,
    EbookOperationProcessorRequirement,
    EbookOperationRecipeCandidate,
    EbookOperationRecipePlan,
    EbookOperationReviewSnapshot,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationSourceSnapshot,
    EbookOperationTargetSnapshot,
    operation_collision_policy,
    operation_output_identity_kind,
    operation_recovery_mode,
    operation_workspace_mode,
    required_verification_codes,
)
from foliotone.ebook_operation_recipes.serialization import (
    ebook_operation_expected_output_fingerprint,
    ebook_operation_precondition_fingerprint,
    ebook_operation_processor_requirement_fingerprint,
    ebook_operation_recipe_candidate_content_hash,
    ebook_operation_recipe_candidate_evidence_fingerprint,
    ebook_operation_recipe_candidate_id,
    ebook_operation_recipe_plan_content_hash,
    ebook_operation_recipe_plan_id,
    ebook_operation_recovery_requirement_fingerprint,
    ebook_operation_source_evidence_fingerprint,
    ebook_operation_verification_fingerprint,
    ebook_operation_workspace_requirement_fingerprint,
)

_ZERO_ID = EntityId(UUID(int=0))
_ZERO_SHA256 = "0" * 64


def _evidence_key(value: EbookOperationEvidenceReference) -> tuple[str, str, str]:
    return value.kind, str(value.ref_id), value.material_fingerprint


def _canonical_evidence(
    values: tuple[EbookOperationEvidenceReference, ...],
) -> tuple[EbookOperationEvidenceReference, ...]:
    return tuple(sorted(values, key=_evidence_key))


def build_ebook_operation_source_snapshot(
    *,
    ordinal: int,
    role: EbookOperationSourceRole,
    scan_root_id: EntityId,
    source_scan_run_id: EntityId,
    source_scan_run_status: ScanRunStatus,
    file_id: EntityId,
    observation_id: EntityId,
    relative_locator: str,
    format_label: str,
    expected_presence_state: PresenceState,
    expected_full_sha256: str,
    expected_size_bytes: int,
    expected_modified_at: datetime,
    expected_observed_at: datetime,
) -> EbookOperationSourceSnapshot:
    """Build a source snapshot whose fingerprint covers every material field."""
    draft = EbookOperationSourceSnapshot(
        ordinal=ordinal,
        role=role,
        scan_root_id=scan_root_id,
        source_scan_run_id=source_scan_run_id,
        source_scan_run_status=source_scan_run_status,
        file_id=file_id,
        observation_id=observation_id,
        relative_locator=relative_locator,
        format_label=format_label,
        expected_presence_state=expected_presence_state,
        expected_full_sha256=expected_full_sha256,
        expected_size_bytes=expected_size_bytes,
        expected_modified_at=expected_modified_at,
        expected_observed_at=expected_observed_at,
        source_evidence_fingerprint=_ZERO_SHA256,
    )
    return replace(
        draft,
        source_evidence_fingerprint=ebook_operation_source_evidence_fingerprint(draft),
    )


def build_ebook_operation_expected_output(
    *,
    operation_kind: EbookOperationKind,
    format_label: str,
    expected_full_sha256: str,
    expected_size_bytes: int,
) -> EbookOperationExpectedOutput:
    """Build the complete deterministic output identity for one operation."""
    draft = EbookOperationExpectedOutput(
        identity_kind=operation_output_identity_kind(operation_kind),
        format_label=format_label,
        expected_full_sha256=expected_full_sha256,
        expected_size_bytes=expected_size_bytes,
        output_specification_fingerprint=_ZERO_SHA256,
    )
    return replace(
        draft,
        output_specification_fingerprint=(
            ebook_operation_expected_output_fingerprint(draft)
        ),
    )


def build_ebook_operation_processor_requirement(
    *,
    kind: EbookOperationProcessorKind,
    processor_profile: str,
    configuration_fingerprint: str,
    provider_id: str | None = None,
    tool_version: str | None = None,
    adapter_version: str | None = None,
) -> EbookOperationProcessorRequirement:
    """Build an adapter-neutral requirement without a command or executable path."""
    draft = EbookOperationProcessorRequirement(
        kind=kind,
        processor_profile=processor_profile,
        configuration_fingerprint=configuration_fingerprint,
        material_fingerprint=_ZERO_SHA256,
        provider_id=provider_id,
        tool_version=tool_version,
        adapter_version=adapter_version,
    )
    return replace(
        draft,
        material_fingerprint=ebook_operation_processor_requirement_fingerprint(draft),
    )


@dataclass(frozen=True, slots=True)
class EbookOperationRecipeCandidateInputs:
    operation_kind: EbookOperationKind
    sources: tuple[EbookOperationSourceSnapshot, ...]
    target: EbookOperationTargetSnapshot
    expected_output: EbookOperationExpectedOutput
    processor_requirement: EbookOperationProcessorRequirement
    dependencies: tuple[EbookOperationDependencySnapshot, ...]
    evidence_refs: tuple[EbookOperationEvidenceReference, ...]


def _validate_candidate_component_fingerprints(
    candidate: EbookOperationRecipeCandidate,
) -> None:
    if any(
        source.source_evidence_fingerprint
        != ebook_operation_source_evidence_fingerprint(source)
        for source in candidate.sources
    ):
        raise ValueError("source evidence fingerprint does not match source semantics")
    if (
        candidate.expected_output.output_specification_fingerprint
        != ebook_operation_expected_output_fingerprint(candidate.expected_output)
    ):
        raise ValueError("output specification fingerprint does not match output semantics")
    if (
        candidate.processor_requirement.material_fingerprint
        != ebook_operation_processor_requirement_fingerprint(
            candidate.processor_requirement
        )
    ):
        raise ValueError("processor requirement fingerprint does not match semantics")
    if (
        candidate.workspace_requirement_fingerprint
        != ebook_operation_workspace_requirement_fingerprint(
            candidate.operation_kind,
            candidate.workspace_mode,
        )
    ):
        raise ValueError("workspace fingerprint does not match operation semantics")
    if (
        candidate.recovery_requirement_fingerprint
        != ebook_operation_recovery_requirement_fingerprint(
            candidate.operation_kind,
            candidate.recovery_mode,
            candidate.collision_policy,
        )
    ):
        raise ValueError("recovery fingerprint does not match operation semantics")
    if (
        candidate.verification_fingerprint
        != ebook_operation_verification_fingerprint(
            candidate.operation_kind,
            candidate.verification_codes,
        )
    ):
        raise ValueError("verification fingerprint does not match operation semantics")


def _validate_candidate_identity(candidate: EbookOperationRecipeCandidate) -> None:
    _validate_candidate_component_fingerprints(candidate)
    expected_evidence = ebook_operation_recipe_candidate_evidence_fingerprint(candidate)
    if candidate.evidence_fingerprint != expected_evidence:
        raise ValueError("candidate evidence fingerprint does not match canonical evidence")
    expected_hash = ebook_operation_recipe_candidate_content_hash(candidate)
    if candidate.content_hash != expected_hash:
        raise ValueError("candidate content hash does not match canonical candidate data")
    if candidate.id != ebook_operation_recipe_candidate_id(expected_hash):
        raise ValueError("candidate ID does not match its content hash")


def build_ebook_operation_recipe_candidate(
    inputs: EbookOperationRecipeCandidateInputs,
    *,
    clock: Callable[[], datetime],
) -> EbookOperationRecipeCandidate:
    """Build one content-addressed review candidate; no operation is performed."""
    if not isinstance(inputs, EbookOperationRecipeCandidateInputs):
        raise TypeError("inputs must be EbookOperationRecipeCandidateInputs")
    if not callable(clock):
        raise TypeError("clock must be callable")
    created_at = clock()
    require_aware_datetime(created_at, "clock result")

    sources = tuple(sorted(inputs.sources, key=lambda value: value.ordinal))
    dependency_order = {
        kind: ordinal for ordinal, kind in enumerate(EbookOperationDependencyKind)
    }
    dependencies = tuple(
        sorted(inputs.dependencies, key=lambda value: dependency_order[value.kind])
    )
    evidence_refs = _canonical_evidence(inputs.evidence_refs)
    collision_policy = operation_collision_policy(inputs.operation_kind)
    workspace_mode = operation_workspace_mode(inputs.operation_kind)
    recovery_mode = operation_recovery_mode(inputs.operation_kind)
    verification_codes = required_verification_codes(inputs.operation_kind)

    draft = EbookOperationRecipeCandidate(
        id=_ZERO_ID,
        profile=EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE,
        serializer_version=EBOOK_OPERATION_RECIPE_SERIALIZER,
        operation_kind=inputs.operation_kind,
        sources=sources,
        target=inputs.target,
        expected_output=inputs.expected_output,
        collision_policy=collision_policy,
        workspace_mode=workspace_mode,
        recovery_mode=recovery_mode,
        processor_requirement=inputs.processor_requirement,
        dependencies=dependencies,
        verification_codes=verification_codes,
        workspace_requirement_fingerprint=(
            ebook_operation_workspace_requirement_fingerprint(
                inputs.operation_kind,
                workspace_mode,
            )
        ),
        recovery_requirement_fingerprint=(
            ebook_operation_recovery_requirement_fingerprint(
                inputs.operation_kind,
                recovery_mode,
                collision_policy,
            )
        ),
        verification_fingerprint=ebook_operation_verification_fingerprint(
            inputs.operation_kind,
            verification_codes,
        ),
        evidence_refs=evidence_refs,
        evidence_fingerprint=_ZERO_SHA256,
        content_hash=_ZERO_SHA256,
        created_at=created_at,
    )
    _validate_candidate_component_fingerprints(draft)
    evidence_fingerprint = ebook_operation_recipe_candidate_evidence_fingerprint(draft)
    with_evidence = replace(draft, evidence_fingerprint=evidence_fingerprint)
    content_hash = ebook_operation_recipe_candidate_content_hash(with_evidence)
    return replace(
        with_evidence,
        id=ebook_operation_recipe_candidate_id(content_hash),
        content_hash=content_hash,
    )


@dataclass(frozen=True, slots=True)
class EbookOperationRecipePlanInputs:
    candidate: EbookOperationRecipeCandidate
    review: EbookOperationReviewSnapshot | None
    lineage_matches: bool
    source_evidence_complete: bool
    target_valid: bool
    output_identity_valid: bool
    processor_requirement_valid: bool
    preconditions_complete: bool
    recovery_contract_complete: bool
    verification_contract_complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, EbookOperationRecipeCandidate):
            raise ValueError("candidate must be an EbookOperationRecipeCandidate")
        if self.review is not None and not isinstance(
            self.review, EbookOperationReviewSnapshot
        ):
            raise ValueError("review must be an EbookOperationReviewSnapshot")
        for field_name in (
            "lineage_matches",
            "source_evidence_complete",
            "target_valid",
            "output_identity_valid",
            "processor_requirement_valid",
            "preconditions_complete",
            "recovery_contract_complete",
            "verification_contract_complete",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")


def _review_is_compatible(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot | None,
) -> bool:
    return (
        review is not None
        and review.candidate_id == candidate.id
        and review.evidence_fingerprint == candidate.evidence_fingerprint
        and review.candidate_set_fingerprint == candidate.content_hash
    )


def _plan_review(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot | None,
    *,
    compatible: bool,
) -> EbookOperationReviewSnapshot:
    if review is None or review.state is EbookOperationReviewState.MISSING:
        return EbookOperationReviewSnapshot(
            candidate_id=candidate.id,
            state=EbookOperationReviewState.MISSING,
            evidence_fingerprint=candidate.evidence_fingerprint,
            candidate_set_fingerprint=candidate.content_hash,
        )
    if compatible:
        return review
    return EbookOperationReviewSnapshot(
        candidate_id=candidate.id,
        state=EbookOperationReviewState.STALE,
        evidence_fingerprint=review.evidence_fingerprint,
        candidate_set_fingerprint=review.candidate_set_fingerprint,
        review_item_id=review.review_item_id,
    )


def _precondition(
    code: EbookOperationPreconditionCode,
    expected_material: object,
) -> EbookOperationPrecondition:
    return EbookOperationPrecondition(
        code=code,
        expected_fingerprint=ebook_operation_precondition_fingerprint(
            code,
            expected_material,
        ),
    )


def _build_preconditions(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot | None,
    *,
    compatible_review: bool,
) -> tuple[EbookOperationPrecondition, ...]:
    source_lineage = [
        {
            "ordinal": source.ordinal,
            "scan_root_id": str(source.scan_root_id),
            "source_scan_run_id": str(source.source_scan_run_id),
            "source_scan_run_status": source.source_scan_run_status.value,
            "file_id": str(source.file_id),
            "observation_id": str(source.observation_id),
            "relative_locator": source.relative_locator,
            "expected_observed_at": source.expected_observed_at,
        }
        for source in candidate.sources
    ]
    source_bytes = [
        {
            "ordinal": source.ordinal,
            "file_id": str(source.file_id),
            "observation_id": str(source.observation_id),
            "presence_state": source.expected_presence_state.value,
            "full_sha256": source.expected_full_sha256,
            "size_bytes": source.expected_size_bytes,
            "modified_at": source.expected_modified_at,
            "source_evidence_fingerprint": source.source_evidence_fingerprint,
        }
        for source in candidate.sources
    ]
    dependencies = [
        {
            "kind": value.kind.value,
            "state": value.state.value,
            "snapshot_kind": value.snapshot_kind,
            "snapshot_id": str(value.snapshot_id),
            "material_fingerprint": value.material_fingerprint,
        }
        for value in candidate.dependencies
    ]
    processor = candidate.processor_requirement
    output = candidate.expected_output
    expected: dict[EbookOperationPreconditionCode, object] = {
        EbookOperationPreconditionCode.SOURCE_LINEAGE_UNCHANGED: source_lineage,
        EbookOperationPreconditionCode.SOURCE_BYTES_UNCHANGED: source_bytes,
        EbookOperationPreconditionCode.TARGET_STATE_UNCHANGED: {
            "kind": candidate.target.kind.value,
            "scope_id": str(candidate.target.scope_id),
            "relative_locator": candidate.target.relative_locator,
            "target_state_fingerprint": candidate.target.target_state_fingerprint,
            "collision_policy": candidate.collision_policy.value,
        },
        EbookOperationPreconditionCode.DEPENDENCIES_UNCHANGED: dependencies,
        EbookOperationPreconditionCode.PROCESSOR_REQUIREMENT_UNCHANGED: {
            "kind": processor.kind.value,
            "processor_profile": processor.processor_profile,
            "configuration_fingerprint": processor.configuration_fingerprint,
            "provider_id": processor.provider_id,
            "tool_version": processor.tool_version,
            "adapter_version": processor.adapter_version,
            "material_fingerprint": processor.material_fingerprint,
        },
        EbookOperationPreconditionCode.OUTPUT_EXPECTATION_UNCHANGED: {
            "identity_kind": output.identity_kind.value,
            "format_label": output.format_label,
            "expected_full_sha256": output.expected_full_sha256,
            "expected_size_bytes": output.expected_size_bytes,
            "output_specification_fingerprint": (
                output.output_specification_fingerprint
            ),
        },
        EbookOperationPreconditionCode.RECOVERY_REQUIREMENT_UNCHANGED: {
            "workspace_mode": candidate.workspace_mode.value,
            "workspace_requirement_fingerprint": (
                candidate.workspace_requirement_fingerprint
            ),
            "recovery_mode": candidate.recovery_mode.value,
            "recovery_requirement_fingerprint": (
                candidate.recovery_requirement_fingerprint
            ),
        },
        EbookOperationPreconditionCode.VERIFICATION_REQUIREMENT_UNCHANGED: {
            "verification_codes": [
                value.value for value in candidate.verification_codes
            ],
            "verification_fingerprint": candidate.verification_fingerprint,
        },
    }
    if (
        compatible_review
        and review is not None
        and review.state is EbookOperationReviewState.ACCEPTED
    ):
        expected[EbookOperationPreconditionCode.REVIEW_APPROVAL_UNCHANGED] = {
            "review_item_id": str(review.review_item_id),
            "decision_id": str(review.decision_id),
            "decision_sequence_no": review.decision_sequence_no,
            "decision_compatibility_version": review.decision_compatibility_version,
            "evidence_fingerprint": review.evidence_fingerprint,
            "candidate_set_fingerprint": review.candidate_set_fingerprint,
        }
    return tuple(
        _precondition(code, expected[code])
        for code in sorted(expected, key=lambda value: value.value)
    )


def _blocker(
    code: EbookOperationBlockerCode,
    candidate: EbookOperationRecipeCandidate,
) -> EbookOperationBlocker:
    return EbookOperationBlocker(code=code, evidence_refs=candidate.evidence_refs)


def _blockers(
    inputs: EbookOperationRecipePlanInputs,
    *,
    compatible_review: bool,
) -> tuple[EbookOperationBlocker, ...]:
    candidate = inputs.candidate
    codes: set[EbookOperationBlockerCode] = set()
    if not inputs.lineage_matches:
        codes.add(EbookOperationBlockerCode.LINEAGE_MISMATCH)
    if not inputs.source_evidence_complete:
        codes.add(EbookOperationBlockerCode.SOURCE_EVIDENCE_INCOMPLETE)
    if not inputs.target_valid:
        codes.add(EbookOperationBlockerCode.TARGET_INVALID)
    if not inputs.output_identity_valid:
        codes.add(EbookOperationBlockerCode.OUTPUT_IDENTITY_INVALID)
    if not inputs.processor_requirement_valid:
        codes.add(EbookOperationBlockerCode.PROCESSOR_REQUIREMENT_INVALID)
    if any(
        dependency.state is EbookOperationDependencyState.UNKNOWN
        for dependency in candidate.dependencies
    ):
        codes.add(EbookOperationBlockerCode.DEPENDENCY_EVIDENCE_INCOMPLETE)
    if not inputs.preconditions_complete:
        codes.add(EbookOperationBlockerCode.PRECONDITION_INCOMPLETE)
    if not inputs.recovery_contract_complete:
        codes.add(EbookOperationBlockerCode.RECOVERY_CONTRACT_INCOMPLETE)
    if not inputs.verification_contract_complete:
        codes.add(EbookOperationBlockerCode.VERIFICATION_CONTRACT_INCOMPLETE)

    review = inputs.review
    if review is None or review.state is EbookOperationReviewState.MISSING:
        codes.add(EbookOperationBlockerCode.REVIEW_MISSING)
    elif not compatible_review or review.state is EbookOperationReviewState.STALE:
        codes.add(EbookOperationBlockerCode.REVIEW_STALE)
    elif review.state is EbookOperationReviewState.REJECTED:
        codes.add(EbookOperationBlockerCode.REVIEW_REJECTED)

    return tuple(
        _blocker(code, candidate) for code in sorted(codes, key=lambda value: value.value)
    )


def _status(
    blockers: tuple[EbookOperationBlocker, ...],
    review: EbookOperationReviewSnapshot,
) -> EbookOperationPlanStatus:
    if blockers:
        return EbookOperationPlanStatus.BLOCKED
    if review.state is EbookOperationReviewState.ACCEPTED:
        return EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
    return EbookOperationPlanStatus.REVIEW_REQUIRED


def build_ebook_operation_recipe_plan(
    inputs: EbookOperationRecipePlanInputs,
    *,
    clock: Callable[[], datetime],
) -> EbookOperationRecipePlan:
    """Reduce evidence and review into an always non-executable recipe plan."""
    if not isinstance(inputs, EbookOperationRecipePlanInputs):
        raise TypeError("inputs must be EbookOperationRecipePlanInputs")
    if not callable(clock):
        raise TypeError("clock must be callable")
    created_at = clock()
    require_aware_datetime(created_at, "clock result")
    _validate_candidate_identity(inputs.candidate)

    compatible_review = _review_is_compatible(inputs.candidate, inputs.review)
    review = _plan_review(
        inputs.candidate,
        inputs.review,
        compatible=compatible_review,
    )
    preconditions = _build_preconditions(
        inputs.candidate,
        inputs.review,
        compatible_review=compatible_review,
    )
    blockers = _blockers(inputs, compatible_review=compatible_review)
    draft = EbookOperationRecipePlan(
        id=_ZERO_ID,
        candidate=inputs.candidate,
        review=review,
        preconditions=preconditions,
        blockers=blockers,
        status=_status(blockers, review),
        execution_state=EbookOperationExecutionState.NOT_EXECUTABLE,
        content_hash=_ZERO_SHA256,
        created_at=created_at,
    )
    content_hash = ebook_operation_recipe_plan_content_hash(draft)
    return replace(
        draft,
        id=ebook_operation_recipe_plan_id(content_hash),
        content_hash=content_hash,
    )


build_non_executable_ebook_operation_recipe_plan = build_ebook_operation_recipe_plan


__all__ = [
    "EbookOperationRecipeCandidateInputs",
    "EbookOperationRecipePlanInputs",
    "build_ebook_operation_expected_output",
    "build_ebook_operation_processor_requirement",
    "build_ebook_operation_recipe_candidate",
    "build_ebook_operation_recipe_plan",
    "build_ebook_operation_source_snapshot",
    "build_non_executable_ebook_operation_recipe_plan",
]
