"""Pure consolidation precondition builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.consolidation.contracts import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationPreconditionCode,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
)
from foliotone.core import (
    EntityId,
    FileObservation,
    FileRecord,
    PresenceState,
    ReviewCandidateKind,
    ReviewType,
)


@dataclass(frozen=True, slots=True)
class ConsolidationFilePreconditionInputs:
    """Validated source material for one file-role precondition build."""

    file_endpoint: ConsolidationFileEndpoint
    file_record: FileRecord
    file_observation: FileObservation
    quality_evidence: ConsolidationQualityEvidenceSnapshot
    dependencies: tuple[ConsolidationDependency, ...]
    review_approval: ConsolidationReviewSnapshot


_FILE_PRECONDITION_CODES = (
    ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
    ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
    ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
    ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
    ConsolidationPreconditionCode.SIZE_MATCHES,
    ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
)

_DEPENDENCY_TO_CODE = (
    (
        ConsolidationDependencyKind.CALIBRE,
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
    ),
    (
        ConsolidationDependencyKind.SIDECAR,
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
    ),
    (
        ConsolidationDependencyKind.ARCHIVE,
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
    ),
)

_REVIEW_CONTRACT = {
    ConsolidationFileRole.KEEPER: (
        ReviewType.KEEP_PREFERENCE,
        ReviewCandidateKind.KEEP_PREFERENCE,
        "ebook-keep-preference",
        CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ),
    ConsolidationFileRole.CANDIDATE: (
        ReviewType.CONSOLIDATION_CANDIDATE,
        ReviewCandidateKind.CONSOLIDATION_CANDIDATE,
        "ebook-consolidation-candidate",
        CONSOLIDATION_CANDIDATE_DECISION,
    ),
}


def _lookup_dependency(
    role: ConsolidationFileRole,
    kind: ConsolidationDependencyKind,
    dependencies: tuple[ConsolidationDependency, ...],
) -> ConsolidationDependency:
    matches = tuple(
        dependency
        for dependency in dependencies
        if dependency.file_role == role and dependency.kind == kind
    )
    if len(matches) != 1:
        raise ValueError(
            "dependency snapshot for preconditions must be unique and complete"
        )
    return matches[0]


def _build_signature(
    endpoint: ConsolidationFileEndpoint,
    file_observation_id: EntityId,
) -> tuple[
    EntityId,
    EntityId,
    EntityId,
    EntityId,
    PresenceState,
    str,
    int,
    datetime,
    datetime,
]:
    return (
        endpoint.file_id,
        file_observation_id,
        endpoint.scan_root_id,
        endpoint.source_scan_run_id,
        endpoint.expected_presence_state,
        endpoint.expected_full_sha256,
        endpoint.expected_size_bytes,
        endpoint.expected_modified_at,
        endpoint.expected_observed_at,
    )


def build_consolidation_file_preconditions(
    inputs: ConsolidationFilePreconditionInputs,
) -> tuple[ConsolidationFilePreconditionSnapshot, ...]:
    """Build deterministic preconditions for one file endpoint."""

    if inputs.file_endpoint.expected_presence_state is not PresenceState.PRESENT:
        raise ValueError("presence must be PRESENT")
    if inputs.file_endpoint.file_id != inputs.file_record.id:
        raise ValueError("endpoint and file record must refer to the same file")
    if inputs.file_endpoint.file_id != inputs.file_observation.file_id:
        raise ValueError("endpoint and file observation must refer to the same file")
    if (
        inputs.file_record.scan_root_id != inputs.file_endpoint.scan_root_id
        or inputs.file_record.presence_state is not PresenceState.PRESENT
    ):
        raise ValueError(
            "endpoint and file record must refer to same present file in scan root"
        )
    if (
        inputs.file_observation.scan_run_id != inputs.file_endpoint.source_scan_run_id
        or inputs.file_observation.id != inputs.file_endpoint.observation_id
    ):
        raise ValueError("endpoint and file observation must refer to same lineage")
    if (
        inputs.file_record.size_bytes != inputs.file_endpoint.expected_size_bytes
        or inputs.file_observation.size_bytes != inputs.file_endpoint.expected_size_bytes
    ):
        raise ValueError("endpoint and both source rows must agree on file size")
    if (
        inputs.file_record.modified_at != inputs.file_endpoint.expected_modified_at
        or inputs.file_observation.modified_at != inputs.file_endpoint.expected_modified_at
    ):
        raise ValueError("endpoint and both source rows must agree on modified timestamp")
    if inputs.file_observation.observed_at != inputs.file_endpoint.expected_observed_at:
        raise ValueError("endpoint and file observation must share observed timestamp")
    quality = inputs.quality_evidence
    if (
        quality.role is not inputs.file_endpoint.role
        or quality.observation_id != inputs.file_endpoint.observation_id
        or quality.scan_root_id != inputs.file_endpoint.scan_root_id
        or quality.source_scan_run_id != inputs.file_endpoint.source_scan_run_id
        or quality.format_label != inputs.file_endpoint.format_label
    ):
        raise ValueError("quality evidence must match endpoint role, lineage and format")

    review = inputs.review_approval
    expected_review = _REVIEW_CONTRACT[inputs.file_endpoint.role]
    if (
        review.state is not ConsolidationReviewState.ACCEPTED
        or review.review_type is not expected_review[0]
        or review.candidate_kind is not expected_review[1]
        or review.producer_name != expected_review[2]
        or review.decision_compatibility_version != expected_review[3]
    ):
        raise ValueError("review approval is not compatible with the file role")

    signature = _build_signature(
        endpoint=inputs.file_endpoint,
        file_observation_id=inputs.file_observation.id,
    )
    preconditions: list[ConsolidationFilePreconditionSnapshot] = []
    (
        file_id,
        observation_id,
        scan_root_id,
        scan_run_id,
        expected_presence_state,
        expected_full_sha256,
        expected_size_bytes,
        expected_modified_at,
        expected_observed_at,
    ) = signature

    for code in _FILE_PRECONDITION_CODES:
        preconditions.append(
            ConsolidationFilePreconditionSnapshot(
                file_role=inputs.file_endpoint.role,
                code=code,
                expected_file_id=file_id,
                expected_observation_id=observation_id,
                expected_scan_root_id=scan_root_id,
                expected_scan_run_id=scan_run_id,
                expected_presence_state=expected_presence_state,
                expected_full_sha256=expected_full_sha256,
                expected_size_bytes=expected_size_bytes,
                expected_modified_at=expected_modified_at,
                expected_observed_at=expected_observed_at,
            )
        )

    if inputs.file_endpoint.role is ConsolidationFileRole.KEEPER:
        preconditions.append(
            ConsolidationFilePreconditionSnapshot(
                file_role=inputs.file_endpoint.role,
                code=ConsolidationPreconditionCode.KEEPER_READABLE,
                expected_file_id=file_id,
                expected_observation_id=observation_id,
                expected_scan_root_id=scan_root_id,
                expected_scan_run_id=scan_run_id,
                expected_presence_state=expected_presence_state,
                expected_full_sha256=expected_full_sha256,
                expected_size_bytes=expected_size_bytes,
                expected_modified_at=expected_modified_at,
                expected_observed_at=expected_observed_at,
            )
        )

    for kind, code in _DEPENDENCY_TO_CODE:
        dependency = _lookup_dependency(
            inputs.file_endpoint.role,
            kind,
            inputs.dependencies,
        )
        preconditions.append(
            ConsolidationFilePreconditionSnapshot(
                file_role=inputs.file_endpoint.role,
                code=code,
                expected_file_id=file_id,
                expected_observation_id=observation_id,
                expected_scan_root_id=scan_root_id,
                expected_scan_run_id=scan_run_id,
                expected_presence_state=expected_presence_state,
                expected_full_sha256=expected_full_sha256,
                expected_size_bytes=expected_size_bytes,
                expected_modified_at=expected_modified_at,
                expected_observed_at=expected_observed_at,
                dependency_kind=dependency.kind,
                dependency_state=dependency.state,
                dependency_fingerprint=dependency.material_fingerprint,
                dependency_snapshot_kind=dependency.snapshot_kind,
                dependency_snapshot_id=dependency.snapshot_id,
            )
        )

    preconditions.append(
        ConsolidationFilePreconditionSnapshot(
            file_role=inputs.file_endpoint.role,
            code=ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
            expected_file_id=file_id,
            expected_observation_id=observation_id,
            expected_scan_root_id=scan_root_id,
            expected_scan_run_id=scan_run_id,
            expected_presence_state=expected_presence_state,
            expected_full_sha256=expected_full_sha256,
            expected_size_bytes=expected_size_bytes,
            expected_modified_at=expected_modified_at,
            expected_observed_at=expected_observed_at,
            review_item_id=review.review_item_id,
            review_decision_id=review.decision_id,
            review_decision_sequence_no=review.decision_sequence_no,
            review_decision_compatibility_version=review.decision_compatibility_version,
            review_evidence_fingerprint=review.evidence_fingerprint,
            review_candidate_set_fingerprint=review.candidate_set_fingerprint,
        )
    )

    return tuple(sorted(preconditions, key=lambda item: (item.file_role, item.code)))
