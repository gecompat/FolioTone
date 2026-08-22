"""Pure builders and reducer for non-executable metadata correction planning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from foliotone.core import EntityId, PresenceState, ScanRunStatus
from foliotone.core._validation import require_aware_datetime
from foliotone.metadata_correction.contracts import (
    MAX_METADATA_BLOCKER_EVIDENCE_REFS,
    METADATA_CORRECTION_CANDIDATE_PROFILE,
    METADATA_CORRECTION_SERIALIZER_VERSION,
    MetadataCorrectionBlocker,
    MetadataCorrectionBlockerCode,
    MetadataCorrectionCandidate,
    MetadataCorrectionExecutionState,
    MetadataCorrectionOperation,
    MetadataCorrectionPlan,
    MetadataCorrectionPlanStatus,
    MetadataCorrectionPrecondition,
    MetadataCorrectionPreconditionCode,
    MetadataCorrectionReviewSnapshot,
    MetadataCorrectionReviewState,
    MetadataCorrectionVerification,
    MetadataDependencyKind,
    MetadataDependencySnapshot,
    MetadataDependencyState,
    MetadataEvidenceReference,
    MetadataFieldCorrection,
    MetadataTargetCarrier,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    MetadataWriterRequirement,
)
from foliotone.metadata_correction.serialization import (
    metadata_correction_candidate_content_hash,
    metadata_correction_candidate_evidence_fingerprint,
    metadata_correction_candidate_id,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
    metadata_correction_precondition_fingerprint,
    metadata_correction_selected_fields_fingerprint,
    metadata_field_selection_fingerprint,
    metadata_writer_requirement_fingerprint,
)

_ZERO_ID = EntityId(UUID(int=0))
_ZERO_SHA256 = "0" * 64


def _evidence_key(value: MetadataEvidenceReference) -> tuple[str, str, str]:
    return (value.kind, str(value.ref_id), value.material_fingerprint)


def _canonical_evidence(
    values: tuple[MetadataEvidenceReference, ...],
) -> tuple[MetadataEvidenceReference, ...]:
    return tuple(sorted(values, key=_evidence_key))


def build_metadata_field_correction(
    *,
    field_path: str,
    operation: MetadataCorrectionOperation,
    observed_values: tuple[MetadataValueSnapshot, ...],
    selected_values: tuple[MetadataValueSnapshot, ...],
    evidence_refs: tuple[MetadataEvidenceReference, ...] = (),
) -> MetadataFieldCorrection:
    """Build one bounded field decision and its material selection fingerprint."""
    fingerprint = metadata_field_selection_fingerprint(
        field_path=field_path,
        operation=operation,
        observed_values=observed_values,
        selected_values=selected_values,
    )
    return MetadataFieldCorrection(
        field_path=field_path,
        operation=operation,
        observed_values=observed_values,
        selected_values=selected_values,
        evidence_refs=_canonical_evidence(evidence_refs),
        selection_fingerprint=fingerprint,
    )


def build_metadata_writer_requirement(
    *,
    format_label: str,
    target_carrier: MetadataTargetCarrier,
) -> MetadataWriterRequirement:
    """Build a semantic capability requirement without binding an implementation."""
    return MetadataWriterRequirement(
        format_label=format_label,
        target_carrier=target_carrier,
        material_fingerprint=metadata_writer_requirement_fingerprint(
            format_label=format_label,
            target_carrier=target_carrier,
        ),
    )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionCandidateInputs:
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    source_scan_run_status: ScanRunStatus
    file_id: EntityId
    observation_id: EntityId
    format_label: str
    expected_presence_state: PresenceState
    expected_full_sha256: str
    expected_size_bytes: int
    expected_modified_at: datetime
    expected_observed_at: datetime
    metadata_evidence_fingerprint: str
    target: MetadataTargetSnapshot
    field_corrections: tuple[MetadataFieldCorrection, ...]
    dependencies: tuple[MetadataDependencySnapshot, ...]
    writer_requirement: MetadataWriterRequirement
    evidence_refs: tuple[MetadataEvidenceReference, ...]


def _validate_field_fingerprints(
    fields: tuple[MetadataFieldCorrection, ...],
) -> bool:
    return all(
        field.selection_fingerprint
        == metadata_field_selection_fingerprint(
            field_path=field.field_path,
            operation=field.operation,
            observed_values=field.observed_values,
            selected_values=field.selected_values,
        )
        for field in fields
    )


def _validate_writer_requirement(candidate: MetadataCorrectionCandidate) -> bool:
    requirement = candidate.writer_requirement
    return requirement.material_fingerprint == metadata_writer_requirement_fingerprint(
        format_label=requirement.format_label,
        target_carrier=requirement.target_carrier,
    )


def _validate_candidate_identity(candidate: MetadataCorrectionCandidate) -> None:
    expected_evidence = metadata_correction_candidate_evidence_fingerprint(candidate)
    if candidate.evidence_fingerprint != expected_evidence:
        raise ValueError("candidate evidence fingerprint does not match canonical evidence")
    expected_hash = metadata_correction_candidate_content_hash(candidate)
    if candidate.content_hash != expected_hash:
        raise ValueError("candidate content hash does not match canonical candidate data")
    if candidate.id != metadata_correction_candidate_id(expected_hash):
        raise ValueError("candidate ID does not match its content hash")


def build_metadata_correction_candidate(
    inputs: MetadataCorrectionCandidateInputs,
    *,
    clock: Callable[[], datetime],
) -> MetadataCorrectionCandidate:
    """Build one immutable, deterministic and non-executable review candidate."""
    if not isinstance(inputs, MetadataCorrectionCandidateInputs):
        raise TypeError("inputs must be MetadataCorrectionCandidateInputs")
    if not callable(clock):
        raise TypeError("clock must be callable")
    created_at = clock()
    require_aware_datetime(created_at, "clock result")

    fields = tuple(sorted(inputs.field_corrections, key=lambda item: item.field_path))
    if not _validate_field_fingerprints(fields):
        raise ValueError("field selection fingerprint does not match its values")
    dependency_order = {kind: ordinal for ordinal, kind in enumerate(MetadataDependencyKind)}
    dependencies = tuple(
        sorted(inputs.dependencies, key=lambda item: dependency_order[item.kind])
    )
    evidence_refs = _canonical_evidence(inputs.evidence_refs)

    draft = MetadataCorrectionCandidate(
        id=_ZERO_ID,
        profile=METADATA_CORRECTION_CANDIDATE_PROFILE,
        serializer_version=METADATA_CORRECTION_SERIALIZER_VERSION,
        scan_root_id=inputs.scan_root_id,
        source_scan_run_id=inputs.source_scan_run_id,
        source_scan_run_status=inputs.source_scan_run_status,
        file_id=inputs.file_id,
        observation_id=inputs.observation_id,
        format_label=inputs.format_label,
        expected_presence_state=inputs.expected_presence_state,
        expected_full_sha256=inputs.expected_full_sha256,
        expected_size_bytes=inputs.expected_size_bytes,
        expected_modified_at=inputs.expected_modified_at,
        expected_observed_at=inputs.expected_observed_at,
        metadata_evidence_fingerprint=inputs.metadata_evidence_fingerprint,
        target=inputs.target,
        field_corrections=fields,
        dependencies=dependencies,
        writer_requirement=inputs.writer_requirement,
        evidence_refs=evidence_refs,
        evidence_fingerprint=_ZERO_SHA256,
        content_hash=_ZERO_SHA256,
        created_at=created_at,
    )
    if not _validate_writer_requirement(draft):
        raise ValueError("writer requirement fingerprint does not match its semantics")
    evidence_fingerprint = metadata_correction_candidate_evidence_fingerprint(draft)
    with_evidence = replace(draft, evidence_fingerprint=evidence_fingerprint)
    content_hash = metadata_correction_candidate_content_hash(with_evidence)
    return replace(
        with_evidence,
        id=metadata_correction_candidate_id(content_hash),
        content_hash=content_hash,
    )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionPlanInputs:
    candidate: MetadataCorrectionCandidate
    review: MetadataCorrectionReviewSnapshot | None
    preserved_fields_fingerprint: str
    analysis_profile: str
    lineage_matches: bool
    source_evidence_complete: bool
    field_selection_valid: bool
    target_carrier_valid: bool
    writer_requirement_valid: bool
    preconditions_complete: bool
    verification_contract_complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, MetadataCorrectionCandidate):
            raise ValueError("candidate must be a MetadataCorrectionCandidate")
        if self.review is not None and not isinstance(
            self.review, MetadataCorrectionReviewSnapshot
        ):
            raise ValueError("review must be a MetadataCorrectionReviewSnapshot")
        for field_name in (
            "lineage_matches",
            "source_evidence_complete",
            "field_selection_valid",
            "target_carrier_valid",
            "writer_requirement_valid",
            "preconditions_complete",
            "verification_contract_complete",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")


def _review_is_compatible(
    candidate: MetadataCorrectionCandidate,
    review: MetadataCorrectionReviewSnapshot | None,
) -> bool:
    return (
        review is not None
        and review.candidate_id == candidate.id
        and review.evidence_fingerprint == candidate.evidence_fingerprint
        and review.candidate_set_fingerprint == candidate.content_hash
    )


def _precondition(
    code: MetadataCorrectionPreconditionCode,
    expected_material: object,
) -> MetadataCorrectionPrecondition:
    return MetadataCorrectionPrecondition(
        code=code,
        expected_fingerprint=metadata_correction_precondition_fingerprint(
            code,
            expected_material,
        ),
    )


def _build_preconditions(
    candidate: MetadataCorrectionCandidate,
    review: MetadataCorrectionReviewSnapshot | None,
    *,
    compatible_review: bool,
) -> tuple[MetadataCorrectionPrecondition, ...]:
    source_base = {
        "scan_root_id": str(candidate.scan_root_id),
        "source_scan_run_id": str(candidate.source_scan_run_id),
        "source_scan_run_status": candidate.source_scan_run_status.value,
        "file_id": str(candidate.file_id),
        "observation_id": str(candidate.observation_id),
        "observed_at": candidate.expected_observed_at,
    }
    dependencies = [
        {
            "kind": item.kind.value,
            "state": item.state.value,
            "snapshot_kind": item.snapshot_kind,
            "snapshot_id": str(item.snapshot_id),
            "material_fingerprint": item.material_fingerprint,
        }
        for item in candidate.dependencies
    ]
    expected: dict[MetadataCorrectionPreconditionCode, object] = {
        MetadataCorrectionPreconditionCode.FILE_RECORD_UNCHANGED: {
            "scan_root_id": str(candidate.scan_root_id),
            "file_id": str(candidate.file_id),
        },
        MetadataCorrectionPreconditionCode.FILE_OBSERVATION_CURRENT: source_base,
        MetadataCorrectionPreconditionCode.PRESENCE_IS_PRESENT: {
            **source_base,
            "presence_state": candidate.expected_presence_state.value,
        },
        MetadataCorrectionPreconditionCode.FULL_SHA256_MATCHES: {
            **source_base,
            "full_sha256": candidate.expected_full_sha256,
        },
        MetadataCorrectionPreconditionCode.SIZE_MATCHES: {
            **source_base,
            "size_bytes": candidate.expected_size_bytes,
        },
        MetadataCorrectionPreconditionCode.MODIFIED_AT_MATCHES: {
            **source_base,
            "modified_at": candidate.expected_modified_at,
        },
        MetadataCorrectionPreconditionCode.METADATA_EVIDENCE_UNCHANGED: {
            **source_base,
            "metadata_evidence_fingerprint": candidate.metadata_evidence_fingerprint,
            "candidate_evidence_fingerprint": candidate.evidence_fingerprint,
        },
        MetadataCorrectionPreconditionCode.TARGET_CARRIER_UNCHANGED: {
            "carrier": candidate.target.carrier.value,
            "reference_kind": candidate.target.reference_kind.value,
            "reference_id": str(candidate.target.reference_id),
            "carrier_state_fingerprint": candidate.target.carrier_state_fingerprint,
        },
        MetadataCorrectionPreconditionCode.DEPENDENCIES_UNCHANGED: dependencies,
        MetadataCorrectionPreconditionCode.WRITER_REQUIREMENT_UNCHANGED: {
            "profile": candidate.writer_requirement.profile,
            "format_label": candidate.writer_requirement.format_label,
            "target_carrier": candidate.writer_requirement.target_carrier.value,
            "material_fingerprint": candidate.writer_requirement.material_fingerprint,
        },
    }
    if (
        compatible_review
        and review is not None
        and review.state is MetadataCorrectionReviewState.ACCEPTED
    ):
        expected[MetadataCorrectionPreconditionCode.REVIEW_APPROVAL_UNCHANGED] = {
            "review_item_id": str(review.review_item_id),
            "decision_id": str(review.decision_id),
            "decision_sequence_no": review.decision_sequence_no,
            "decision_compatibility_version": review.decision_compatibility_version,
            "evidence_fingerprint": review.evidence_fingerprint,
            "candidate_set_fingerprint": review.candidate_set_fingerprint,
        }
    return tuple(
        _precondition(code, expected[code])
        for code in MetadataCorrectionPreconditionCode
        if code in expected
    )


def _dependency_reconciliation(
    candidate: MetadataCorrectionCandidate,
) -> tuple[MetadataDependencyKind, ...]:
    required = {
        item.kind
        for item in candidate.dependencies
        if item.state is MetadataDependencyState.KNOWN_PRESENT
    }
    if candidate.target.carrier is MetadataTargetCarrier.CALIBRE_LIBRARY:
        required.add(MetadataDependencyKind.CALIBRE)
    if candidate.target.carrier is MetadataTargetCarrier.SIDECAR:
        required.add(MetadataDependencyKind.SIDECAR)
    return tuple(kind for kind in MetadataDependencyKind if kind in required)


def _verification(inputs: MetadataCorrectionPlanInputs) -> MetadataCorrectionVerification:
    candidate = inputs.candidate
    return MetadataCorrectionVerification(
        analysis_profile=inputs.analysis_profile,
        format_label=candidate.format_label,
        target_carrier=candidate.target.carrier,
        expected_selected_fields_fingerprint=(
            metadata_correction_selected_fields_fingerprint(candidate)
        ),
        preserved_fields_fingerprint=inputs.preserved_fields_fingerprint,
        changed_field_paths=tuple(item.field_path for item in candidate.field_corrections),
        format_validation_required=True,
        readability_validation_required=True,
        dependency_reconciliation=_dependency_reconciliation(candidate),
    )


def _blocker(
    code: MetadataCorrectionBlockerCode,
    candidate: MetadataCorrectionCandidate,
) -> MetadataCorrectionBlocker:
    return MetadataCorrectionBlocker(
        code=code,
        evidence_refs=candidate.evidence_refs[:MAX_METADATA_BLOCKER_EVIDENCE_REFS],
    )


def _blockers(
    inputs: MetadataCorrectionPlanInputs,
    *,
    compatible_review: bool,
) -> tuple[MetadataCorrectionBlocker, ...]:
    candidate = inputs.candidate
    codes: set[MetadataCorrectionBlockerCode] = set()
    if not inputs.lineage_matches:
        codes.add(MetadataCorrectionBlockerCode.LINEAGE_MISMATCH)
    if not inputs.source_evidence_complete:
        codes.add(MetadataCorrectionBlockerCode.SOURCE_EVIDENCE_INCOMPLETE)
    if not inputs.field_selection_valid or not _validate_field_fingerprints(
        candidate.field_corrections
    ):
        codes.add(MetadataCorrectionBlockerCode.FIELD_SELECTION_INVALID)
    if not inputs.target_carrier_valid:
        codes.add(MetadataCorrectionBlockerCode.TARGET_CARRIER_INVALID)
    if not inputs.writer_requirement_valid or not _validate_writer_requirement(candidate):
        codes.add(MetadataCorrectionBlockerCode.WRITER_REQUIREMENT_INVALID)
    if any(
        dependency.state is MetadataDependencyState.UNKNOWN
        for dependency in candidate.dependencies
    ):
        codes.add(MetadataCorrectionBlockerCode.DEPENDENCY_EVIDENCE_INCOMPLETE)
    if not inputs.preconditions_complete:
        codes.add(MetadataCorrectionBlockerCode.PRECONDITION_INCOMPLETE)
    if not inputs.verification_contract_complete:
        codes.add(MetadataCorrectionBlockerCode.VERIFICATION_CONTRACT_INCOMPLETE)

    review = inputs.review
    if review is None or review.state is MetadataCorrectionReviewState.MISSING:
        codes.add(MetadataCorrectionBlockerCode.REVIEW_MISSING)
    elif not compatible_review or review.state is MetadataCorrectionReviewState.STALE:
        codes.add(MetadataCorrectionBlockerCode.REVIEW_STALE)
    elif review.state is MetadataCorrectionReviewState.REJECTED:
        codes.add(MetadataCorrectionBlockerCode.REVIEW_REJECTED)

    return tuple(_blocker(code, candidate) for code in sorted(codes, key=lambda item: item.value))


def _status(
    blockers: tuple[MetadataCorrectionBlocker, ...],
    review: MetadataCorrectionReviewSnapshot | None,
) -> MetadataCorrectionPlanStatus:
    if blockers:
        return MetadataCorrectionPlanStatus.BLOCKED
    if review is not None and review.state in {
        MetadataCorrectionReviewState.PENDING,
        MetadataCorrectionReviewState.DEFERRED,
    }:
        return MetadataCorrectionPlanStatus.REVIEW_REQUIRED
    if review is not None and review.state is MetadataCorrectionReviewState.ACCEPTED:
        return MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
    return MetadataCorrectionPlanStatus.BLOCKED


def build_metadata_correction_plan(
    inputs: MetadataCorrectionPlanInputs,
    *,
    clock: Callable[[], datetime],
) -> MetadataCorrectionPlan:
    """Reduce one candidate and review snapshot into an always non-executable plan."""
    if not isinstance(inputs, MetadataCorrectionPlanInputs):
        raise TypeError("inputs must be MetadataCorrectionPlanInputs")
    if not callable(clock):
        raise TypeError("clock must be callable")
    created_at = clock()
    require_aware_datetime(created_at, "clock result")
    _validate_candidate_identity(inputs.candidate)

    compatible_review = _review_is_compatible(inputs.candidate, inputs.review)
    preconditions = _build_preconditions(
        inputs.candidate,
        inputs.review,
        compatible_review=compatible_review,
    )
    blockers = _blockers(inputs, compatible_review=compatible_review)
    status = _status(blockers, inputs.review)

    draft = MetadataCorrectionPlan(
        id=_ZERO_ID,
        candidate=inputs.candidate,
        review=inputs.review,
        preconditions=preconditions,
        verification=_verification(inputs),
        blockers=blockers,
        status=status,
        execution_state=MetadataCorrectionExecutionState.NOT_EXECUTABLE,
        content_hash=_ZERO_SHA256,
        created_at=created_at,
    )
    content_hash = metadata_correction_plan_content_hash(draft)
    return replace(
        draft,
        id=metadata_correction_plan_id(content_hash),
        content_hash=content_hash,
    )


build_non_executable_metadata_correction_plan = build_metadata_correction_plan


__all__ = [
    "MetadataCorrectionCandidateInputs",
    "MetadataCorrectionPlanInputs",
    "build_metadata_correction_candidate",
    "build_metadata_correction_plan",
    "build_metadata_field_correction",
    "build_metadata_writer_requirement",
    "build_non_executable_metadata_correction_plan",
]
