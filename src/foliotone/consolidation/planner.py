"""Pure assembly of immutable, non-executable consolidation plans.

The planner deliberately has no persistence, filesystem, or runtime dependency.
It only joins snapshots that have already been obtained by the read-only
analysis stages.  In particular, a ``TIED`` or ``BLOCKED`` keep-preference
outcome never becomes a direction through incidental input ordering.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from foliotone.consolidation.blockers import (
    ConsolidationHardBlockerInputs,
    build_consolidation_blockers,
)
from foliotone.consolidation.contracts import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_CANDIDATE_PROFILE,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    CONSOLIDATION_PLAN_VERSION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationCandidateSnapshot,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationEvidenceReference,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
    KeepPreferenceOutcome,
    KeepPreferenceStatus,
)
from foliotone.consolidation.preconditions import (
    ConsolidationFilePreconditionInputs,
    build_consolidation_file_preconditions,
)
from foliotone.consolidation.serialization import consolidation_plan_content_hash
from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
)
from foliotone.core._validation import require_aware_datetime


@dataclass(frozen=True, slots=True)
class ConsolidationPlannerInputs:
    """Path-free source snapshots for :func:`build_consolidation_plan`.

    ``precondition_inputs`` are deliberately the existing S-EB08-03 inputs.
    This keeps file-generation validation in one place.  The planner uses
    them only after a compatible accepted keep-preference review established a
    genuine direction; a pending review cannot accidentally create a keeper.
    """

    plan_id: EntityId
    consolidation_candidate_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    identity: ConsolidationIdentitySnapshot | None
    keep_preference: KeepPreferenceOutcome | None
    dependencies: tuple[ConsolidationDependency, ...] = ()
    required_reviews: tuple[ConsolidationReviewSnapshot, ...] = ()
    precondition_inputs: tuple[ConsolidationFilePreconditionInputs, ...] = ()
    future_operation_intents: tuple[ConsolidationFutureOperationIntent, ...] = ()
    protected_source_root: bool = False
    lineage_matches: bool = True
    source_scan_run_completed: bool = True
    file_sha256_equal: bool = True
    evidence_refs: tuple[ConsolidationEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "plan_id",
            "consolidation_candidate_id",
            "scan_root_id",
            "source_scan_run_id",
        ):
            if not isinstance(getattr(self, name), EntityId):
                raise ValueError(f"{name} must be an EntityId")
        if self.identity is not None and not isinstance(
            self.identity, ConsolidationIdentitySnapshot
        ):
            raise ValueError("identity must be a ConsolidationIdentitySnapshot or None")
        if self.keep_preference is not None and not isinstance(
            self.keep_preference, KeepPreferenceOutcome
        ):
            raise ValueError("keep_preference must be a KeepPreferenceOutcome or None")
        if any(not isinstance(item, ConsolidationDependency) for item in self.dependencies):
            raise ValueError("dependencies must contain ConsolidationDependency values")
        if len({(item.file_role, item.kind) for item in self.dependencies}) != len(
            self.dependencies
        ):
            raise ValueError("dependencies must contain unique file role/kind pairs")
        object.__setattr__(
            self,
            "dependencies",
            tuple(
                sorted(
                    self.dependencies,
                    key=lambda item: (item.file_role.value, item.kind.value),
                )
            ),
        )
        if any(
            not isinstance(item, ConsolidationReviewSnapshot) for item in self.required_reviews
        ):
            raise ValueError("required_reviews must contain ConsolidationReviewSnapshot values")
        if len({item.review_type for item in self.required_reviews}) != len(
            self.required_reviews
        ):
            raise ValueError("required_reviews must contain unique review types")
        if any(
            not isinstance(item, ConsolidationFilePreconditionInputs)
            for item in self.precondition_inputs
        ):
            raise ValueError("precondition_inputs contain an invalid value")
        if self.precondition_inputs and len(self.precondition_inputs) != 2:
            raise ValueError("precondition_inputs require exactly one input per file role")
        if self.precondition_inputs and {
            item.file_endpoint.role for item in self.precondition_inputs
        } != set(
            ConsolidationFileRole
        ):
            raise ValueError("precondition_inputs require exactly one input per file role")
        if any(
            not isinstance(item, ConsolidationFutureOperationIntent)
            for item in self.future_operation_intents
        ):
            raise ValueError("future_operation_intents contain an invalid value")
        intents = tuple(
            sorted(
                self.future_operation_intents,
                key=lambda item: (item.ordinal, item.code.value, item.file_role.value),
            )
        )
        if tuple(item.ordinal for item in intents) != tuple(range(len(intents))):
            raise ValueError("future_operation_intents must have contiguous ordinals")
        object.__setattr__(self, "future_operation_intents", intents)
        if any(
            not isinstance(item, ConsolidationEvidenceReference) for item in self.evidence_refs
        ):
            raise ValueError("evidence_refs contain an invalid value")
        for name in (
            "protected_source_root",
            "lineage_matches",
            "source_scan_run_completed",
            "file_sha256_equal",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")


def _canonical_timestamp(value: datetime) -> str:
    require_aware_datetime(value, "timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonicalize(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are forbidden in canonical candidate payloads")
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical candidate object keys must be strings")
        return {
            unicodedata.normalize("NFC", key): _canonicalize(item)
            for key, item in value.items()
        }
    raise TypeError(f"unsupported canonical candidate value: {type(value).__name__}")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonicalize(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _review_by_type(
    reviews: tuple[ConsolidationReviewSnapshot, ...], review_type: ReviewType
) -> ConsolidationReviewSnapshot | None:
    return next((item for item in reviews if item.review_type is review_type), None)


def _compatible_review(
    review: ConsolidationReviewSnapshot | None,
    review_type: ReviewType,
    evidence_fingerprint: str,
    candidate_set_fingerprint: str,
    *,
    keep_preference_status: KeepPreferenceStatus | None = None,
) -> bool:
    expected = {
        ReviewType.KEEP_PREFERENCE: (
            "ebook-keep-preference",
            CONSOLIDATION_KEEP_PREFERENCE_DECISION,
        ),
        ReviewType.CONSOLIDATION_CANDIDATE: (
            "ebook-consolidation-candidate",
            CONSOLIDATION_CANDIDATE_DECISION,
        ),
    }[review_type]
    return (
        review is not None
        and review.review_type is review_type
        and (
            review_type is not ReviewType.KEEP_PREFERENCE
            or keep_preference_status is KeepPreferenceStatus.PREFERRED
        )
        and review.producer_name == expected[0]
        and review.decision_compatibility_version == expected[1]
        and review.evidence_fingerprint == evidence_fingerprint
        and review.candidate_set_fingerprint == candidate_set_fingerprint
        and (
            review.state
            not in {
                ConsolidationReviewState.PENDING,
                ConsolidationReviewState.DEFERRED,
            }
            or review.review_item_id is not None
        )
    )


def _resolved_review(
    review: ConsolidationReviewSnapshot | None,
    *,
    compatible: bool,
) -> ConsolidationReviewSnapshot | None:
    """Project only a target-bound review; foreign inputs are not plan state."""

    if review is None or compatible:
        return review
    return None


def _identity_is_actionable(inputs: ConsolidationPlannerInputs) -> bool:
    identity = inputs.identity
    return (
        identity is not None
        and identity.scan_root_id == inputs.scan_root_id
        and identity.source_scan_run_id == inputs.source_scan_run_id
        and identity.relation_type is RelationType.EXACT_DUPLICATE
        and identity.left_kind is EntityKind.FILE
        and identity.right_kind is EntityKind.FILE
        and identity.status is MatchStatus.CONFIRMED
        and inputs.source_scan_run_completed
        and inputs.file_sha256_equal
    )


def _canonical_preference(
    preference: KeepPreferenceOutcome | None,
) -> KeepPreferenceOutcome | None:
    if preference is None:
        return None
    quality_evidence = tuple(
        sorted(preference.quality_evidence, key=lambda item: (item.role.value, str(item.id)))
    )
    return replace(preference, quality_evidence=quality_evidence)


def _identity_needs_confirmation(inputs: ConsolidationPlannerInputs) -> bool:
    """Return whether a structurally actionable identity lacks only confirmation."""

    identity = inputs.identity
    return (
        identity is not None
        and identity.scan_root_id == inputs.scan_root_id
        and identity.source_scan_run_id == inputs.source_scan_run_id
        and identity.relation_type is RelationType.EXACT_DUPLICATE
        and identity.left_kind is EntityKind.FILE
        and identity.right_kind is EntityKind.FILE
        and inputs.file_sha256_equal
        and inputs.lineage_matches
        and (
            identity.status is not MatchStatus.CONFIRMED
            or not inputs.source_scan_run_completed
        )
    )


def _preference_binds_identity(inputs: ConsolidationPlannerInputs) -> bool:
    """Require canonical file endpoints and available observation slots to agree."""

    identity = inputs.identity
    preference = inputs.keep_preference
    if (
        identity is None
        or preference is None
        or preference.left_file_id != identity.left_file_id
        or preference.right_file_id != identity.right_file_id
    ):
        return False
    if preference.status is not KeepPreferenceStatus.PREFERRED:
        return True
    if (
        preference.keeper_file_id is None
        or preference.candidate_file_id is None
        or {preference.keeper_file_id, preference.candidate_file_id}
        != {identity.left_file_id, identity.right_file_id}
    ):
        return False
    if not inputs.precondition_inputs:
        return True
    by_role = {item.file_endpoint.role: item.file_endpoint for item in inputs.precondition_inputs}
    if set(by_role) != set(ConsolidationFileRole):
        return False
    keeper_observation_id = (
        preference.left_observation_id
        if preference.keeper_file_id == preference.left_file_id
        else preference.right_observation_id
    )
    candidate_observation_id = (
        preference.right_observation_id
        if keeper_observation_id == preference.left_observation_id
        else preference.left_observation_id
    )
    return (
        by_role[ConsolidationFileRole.KEEPER].file_id == preference.keeper_file_id
        and by_role[ConsolidationFileRole.CANDIDATE].file_id == preference.candidate_file_id
        and by_role[ConsolidationFileRole.KEEPER].observation_id == keeper_observation_id
        and by_role[ConsolidationFileRole.CANDIDATE].observation_id == candidate_observation_id
        and keeper_observation_id != candidate_observation_id
    )


def _quality_slots_are_complete(inputs: ConsolidationPlannerInputs) -> bool:
    """Validate preference quality slots without requiring a physical endpoint.

    A quality projection is immutable evidence. Its completeness must not
    depend on identity confirmation or mutable FileRecord preconditions.
    """

    preference = inputs.keep_preference
    if (
        preference is None
        or preference.status
        not in {
            KeepPreferenceStatus.PREFERRED,
            KeepPreferenceStatus.TIED,
            KeepPreferenceStatus.BLOCKED,
        }
    ):
        return False
    by_role = {item.role: item for item in preference.quality_evidence}
    if len(by_role) != 2 or set(by_role) != set(ConsolidationFileRole):
        return False
    keeper = by_role[ConsolidationFileRole.KEEPER]
    candidate = by_role[ConsolidationFileRole.CANDIDATE]
    if preference.status is KeepPreferenceStatus.PREFERRED:
        if preference.keeper_file_id == preference.left_file_id:
            keeper_observation_id = preference.left_observation_id
            candidate_observation_id = preference.right_observation_id
        elif preference.keeper_file_id == preference.right_file_id:
            keeper_observation_id = preference.right_observation_id
            candidate_observation_id = preference.left_observation_id
        else:
            return False
    else:
        keeper_observation_id = preference.left_observation_id
        candidate_observation_id = preference.right_observation_id
    return (
        keeper.observation_id == keeper_observation_id
        and candidate.observation_id == candidate_observation_id
        and keeper.scan_root_id == inputs.scan_root_id
        and candidate.scan_root_id == inputs.scan_root_id
        and keeper.source_scan_run_id == inputs.source_scan_run_id
        and candidate.source_scan_run_id == inputs.source_scan_run_id
    )


def _source_lineage_matches(inputs: ConsolidationPlannerInputs) -> bool:
    """Derive lineage from every supplied immutable source snapshot."""

    identity = inputs.identity
    if identity is not None and (
        identity.scan_root_id != inputs.scan_root_id
        or identity.source_scan_run_id != inputs.source_scan_run_id
    ):
        return False
    preference = inputs.keep_preference
    if preference is not None and any(
        item.scan_root_id != inputs.scan_root_id
        or item.source_scan_run_id != inputs.source_scan_run_id
        for item in preference.quality_evidence
    ):
        return False
    for source in inputs.precondition_inputs:
        endpoint = source.file_endpoint
        if (
            endpoint.scan_root_id != inputs.scan_root_id
            or endpoint.source_scan_run_id != inputs.source_scan_run_id
            or source.file_record.scan_root_id != inputs.scan_root_id
            or source.file_observation.scan_run_id != inputs.source_scan_run_id
            or source.quality_evidence.scan_root_id != inputs.scan_root_id
            or source.quality_evidence.source_scan_run_id != inputs.source_scan_run_id
        ):
            return False
    return True


def _endpoint_inputs(
    inputs: ConsolidationPlannerInputs,
) -> tuple[ConsolidationFilePreconditionInputs, ...]:
    preference = inputs.keep_preference
    if (
        preference is None
        or preference.status is not KeepPreferenceStatus.PREFERRED
        or not _identity_is_actionable(inputs)
        or not _preference_binds_identity(inputs)
    ):
        return ()
    by_role = {item.file_endpoint.role: item for item in inputs.precondition_inputs}
    if len(by_role) != 2 or set(by_role) != set(ConsolidationFileRole):
        return ()
    keeper_source = by_role[ConsolidationFileRole.KEEPER]
    candidate_source = by_role[ConsolidationFileRole.CANDIDATE]
    keeper = keeper_source.file_endpoint
    candidate = candidate_source.file_endpoint
    identity = inputs.identity
    if (
        identity is None
        or preference.keeper_file_id != keeper.file_id
        or preference.candidate_file_id != candidate.file_id
        or {keeper.file_id, candidate.file_id} != {identity.left_file_id, identity.right_file_id}
        or keeper.observation_id == candidate.observation_id
        or any(
            endpoint.scan_root_id != inputs.scan_root_id
            or endpoint.source_scan_run_id != inputs.source_scan_run_id
            for endpoint in (keeper, candidate)
        )
        or not _quality_matches_endpoints(preference, (keeper, candidate), inputs)
    ):
        return ()
    return (by_role[ConsolidationFileRole.KEEPER], by_role[ConsolidationFileRole.CANDIDATE])


def _quality_matches_endpoints(
    preference: KeepPreferenceOutcome,
    endpoints: tuple[ConsolidationFileEndpoint, ConsolidationFileEndpoint],
    inputs: ConsolidationPlannerInputs,
) -> bool:
    keeper, candidate = endpoints
    by_role = {item.role: item for item in preference.quality_evidence}
    if len(by_role) != 2 or set(by_role) != set(ConsolidationFileRole):
        return False
    return all(
        quality.observation_id == endpoint.observation_id
        and quality.scan_root_id == inputs.scan_root_id
        and quality.source_scan_run_id == inputs.source_scan_run_id
        and quality.format_label == endpoint.format_label
        for quality, endpoint in (
            (by_role[ConsolidationFileRole.KEEPER], keeper),
            (by_role[ConsolidationFileRole.CANDIDATE], candidate),
        )
    )


def consolidation_dependency_fingerprint(
    dependencies: tuple[ConsolidationDependency, ...],
) -> str:
    return _digest(
        {
            "domain": CONSOLIDATION_CANDIDATE_PROFILE,
            "dependencies": [
                {
                    "role": item.file_role.value,
                    "kind": item.kind.value,
                    "state": item.state.value,
                    "material_fingerprint": item.material_fingerprint,
                    "snapshot_kind": item.snapshot_kind,
                    "snapshot_id": None if item.snapshot_id is None else str(item.snapshot_id),
                }
                for item in sorted(
                    dependencies, key=lambda item: (item.file_role.value, item.kind.value)
                )
            ],
        }
    )


def consolidation_candidate_precondition_fingerprint(
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...],
) -> str:
    """Fingerprint physical and relationship preconditions before review binding.

    Candidate review binding is intentionally excluded: the candidate exists
    before its review item can be decided, while the final plan still includes
    the full review-approval preconditions.
    """

    material: list[tuple[str, str, dict[str, object]]] = [
        (
            item.file_role.value,
            item.code.value,
            {
            "role": item.file_role.value,
            "code": item.code.value,
            "file_id": str(item.expected_file_id),
            "observation_id": str(item.expected_observation_id),
            "root_id": str(item.expected_scan_root_id),
            "run_id": str(item.expected_scan_run_id),
            "presence": item.expected_presence_state.value,
            "full_sha256": item.expected_full_sha256,
            "size_bytes": item.expected_size_bytes,
            "modified_at": _canonical_timestamp(item.expected_modified_at),
            "observed_at": _canonical_timestamp(item.expected_observed_at),
            "dependency_kind": (
                None if item.dependency_kind is None else item.dependency_kind.value
            ),
            "dependency_state": (
                None if item.dependency_state is None else item.dependency_state.value
            ),
            "dependency_fingerprint": item.dependency_fingerprint,
            "dependency_snapshot_kind": item.dependency_snapshot_kind,
            "dependency_snapshot_id": (
                None if item.dependency_snapshot_id is None else str(item.dependency_snapshot_id)
            ),
            },
        )
        for item in preconditions
        if item.code is not ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED
    ]
    return _digest(
        {
            "domain": CONSOLIDATION_CANDIDATE_PROFILE,
            "preconditions": [item[2] for item in sorted(material)],
        }
    )


def consolidation_candidate_physical_preconditions(
    endpoints: tuple[ConsolidationFileEndpoint, ConsolidationFileEndpoint],
    dependencies: tuple[ConsolidationDependency, ...],
) -> tuple[ConsolidationFilePreconditionSnapshot, ...]:
    """Project candidate material that exists before either review approval."""

    dependency_codes = (
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
    physical_codes = (
        ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
        ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
        ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
        ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
        ConsolidationPreconditionCode.SIZE_MATCHES,
        ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
    )

    def snapshot(
        endpoint: ConsolidationFileEndpoint,
        code: ConsolidationPreconditionCode,
        dependency: ConsolidationDependency | None = None,
    ) -> ConsolidationFilePreconditionSnapshot:
        return ConsolidationFilePreconditionSnapshot(
            file_role=endpoint.role,
            code=code,
            expected_file_id=endpoint.file_id,
            expected_observation_id=endpoint.observation_id,
            expected_scan_root_id=endpoint.scan_root_id,
            expected_scan_run_id=endpoint.source_scan_run_id,
            expected_presence_state=endpoint.expected_presence_state,
            expected_full_sha256=endpoint.expected_full_sha256,
            expected_size_bytes=endpoint.expected_size_bytes,
            expected_modified_at=endpoint.expected_modified_at,
            expected_observed_at=endpoint.expected_observed_at,
            dependency_kind=None if dependency is None else dependency.kind,
            dependency_state=None if dependency is None else dependency.state,
            dependency_fingerprint=(
                None if dependency is None else dependency.material_fingerprint
            ),
            dependency_snapshot_kind=(
                None if dependency is None else dependency.snapshot_kind
            ),
            dependency_snapshot_id=None if dependency is None else dependency.snapshot_id,
        )

    result: list[ConsolidationFilePreconditionSnapshot] = []
    for endpoint in endpoints:
        result.extend(snapshot(endpoint, code) for code in physical_codes)
        if endpoint.role is ConsolidationFileRole.KEEPER:
            result.append(snapshot(endpoint, ConsolidationPreconditionCode.KEEPER_READABLE))
        for kind, code in dependency_codes:
            dependency = next(
                (
                    item
                    for item in dependencies
                    if item.file_role is endpoint.role and item.kind is kind
                ),
                None,
            )
            if dependency is None:
                raise ValueError("candidate dependencies must be complete by role and kind")
            result.append(snapshot(endpoint, code, dependency))
    return tuple(sorted(result, key=lambda item: (item.file_role.value, item.code.value)))


def consolidation_candidate_material_fingerprints(
    *,
    identity: ConsolidationIdentitySnapshot,
    preference: KeepPreferenceOutcome,
    keeper: ConsolidationFileEndpoint,
    candidate: ConsolidationFileEndpoint,
    dependencies: tuple[ConsolidationDependency, ...],
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...],
    intents: tuple[ConsolidationFutureOperationIntent, ...],
) -> tuple[str, str, str, str]:
    """Return dependency, precondition, evidence and candidate-set fingerprints."""

    dependency_fingerprint = consolidation_dependency_fingerprint(dependencies)
    precondition_fingerprint = consolidation_candidate_precondition_fingerprint(preconditions)
    intent_values = [(item.ordinal, item.code.value, item.file_role.value) for item in intents]
    candidate_set_fingerprint = _digest(
        {
            "domain": CONSOLIDATION_CANDIDATE_PROFILE,
            "identity_candidate_set_fingerprint": identity.candidate_set_fingerprint,
            "keep_preference_candidate_set_fingerprint": preference.candidate_set_fingerprint,
            "keeper_file_id": str(keeper.file_id),
            "candidate_file_id": str(candidate.file_id),
            "dependency_fingerprint": dependency_fingerprint,
            "precondition_fingerprint": precondition_fingerprint,
            "intents": intent_values,
        }
    )
    evidence_fingerprint = _digest(
        {
            "domain": CONSOLIDATION_CANDIDATE_PROFILE,
            "relation_candidate_id": str(identity.relation_candidate_id),
            "relation_fingerprint": identity.evidence_fingerprint,
            "keep_preference_id": str(preference.preference_id),
            "keep_preference_fingerprint": preference.evidence_fingerprint,
            "keeper_file_id": str(keeper.file_id),
            "candidate_file_id": str(candidate.file_id),
            "dependency_fingerprint": dependency_fingerprint,
            "precondition_fingerprint": precondition_fingerprint,
            "candidate_set_fingerprint": candidate_set_fingerprint,
            "intents": intent_values,
        }
    )
    return (
        dependency_fingerprint,
        precondition_fingerprint,
        evidence_fingerprint,
        candidate_set_fingerprint,
    )


def _candidate_snapshot(
    inputs: ConsolidationPlannerInputs,
    endpoints: tuple[ConsolidationFilePreconditionInputs, ...],
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...],
    created_at: datetime,
) -> ConsolidationCandidateSnapshot:
    assert inputs.identity is not None and inputs.keep_preference is not None
    keeper = endpoints[0].file_endpoint
    candidate = endpoints[1].file_endpoint
    intents = inputs.future_operation_intents
    (
        dependency_fingerprint,
        precondition_fingerprint,
        evidence_fingerprint,
        candidate_set_fingerprint,
    ) = consolidation_candidate_material_fingerprints(
        identity=inputs.identity,
        preference=inputs.keep_preference,
        keeper=keeper,
        candidate=candidate,
        dependencies=inputs.dependencies,
        preconditions=preconditions,
        intents=intents,
    )
    return ConsolidationCandidateSnapshot(
        candidate_id=inputs.consolidation_candidate_id,
        profile=CONSOLIDATION_CANDIDATE_PROFILE,
        scan_root_id=inputs.scan_root_id,
        source_scan_run_id=inputs.source_scan_run_id,
        relation_candidate_id=inputs.identity.relation_candidate_id,
        relation_fingerprint=inputs.identity.evidence_fingerprint,
        keep_preference_id=inputs.keep_preference.preference_id,
        keep_preference_fingerprint=inputs.keep_preference.evidence_fingerprint,
        keeper_file_id=keeper.file_id,
        candidate_file_id=candidate.file_id,
        dependency_fingerprint=dependency_fingerprint,
        precondition_fingerprint=precondition_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
        candidate_set_fingerprint=candidate_set_fingerprint,
        intents=intents,
        created_at=created_at,
    )


def _ephemeral_review_approval(
    review: ConsolidationReviewSnapshot | None,
    review_type: ReviewType,
    fallback_id: EntityId,
) -> ConsolidationReviewSnapshot:
    """Return an ephemeral accepted review shape for candidate materialization.

    A candidate is intentionally assembled before its own review decision. The
    review-approval precondition is excluded from the candidate precondition
    fingerprint, so this temporary shape can only contribute the independent
    file and dependency checks.  It is never returned or persisted.
    """

    expected = {
        ReviewType.KEEP_PREFERENCE: (
            ReviewCandidateKind.KEEP_PREFERENCE,
            "ebook-keep-preference",
            CONSOLIDATION_KEEP_PREFERENCE_DECISION,
        ),
        ReviewType.CONSOLIDATION_CANDIDATE: (
            ReviewCandidateKind.CONSOLIDATION_CANDIDATE,
            "ebook-consolidation-candidate",
            CONSOLIDATION_CANDIDATE_DECISION,
        ),
    }[review_type]
    if (
        review is not None
        and review.review_item_id is not None
        and review.review_type is review_type
        and review.candidate_kind is expected[0]
        and review.producer_name == expected[1]
        and review.decision_compatibility_version == expected[2]
    ):
        return replace(
            review,
            state=ConsolidationReviewState.ACCEPTED,
            decision_id=fallback_id,
            decision_sequence_no=1,
        )
    return ConsolidationReviewSnapshot(
        review_type=review_type,
        state=ConsolidationReviewState.ACCEPTED,
        evidence_fingerprint="0" * 64,
        candidate_set_fingerprint="0" * 64,
        candidate_kind=expected[0],
        producer_name=expected[1],
        decision_compatibility_version=expected[2],
        review_item_id=fallback_id,
        decision_id=fallback_id,
        decision_sequence_no=1,
    )


def _physical_preconditions(
    endpoint_inputs: tuple[ConsolidationFilePreconditionInputs, ...],
    keep_review: ConsolidationReviewSnapshot | None,
    candidate_review: ConsolidationReviewSnapshot | None,
    fallback_id: EntityId,
) -> tuple[ConsolidationFilePreconditionSnapshot, ...] | None:
    if not endpoint_inputs:
        return ()
    approvals = {
        ConsolidationFileRole.KEEPER: _ephemeral_review_approval(
            keep_review, ReviewType.KEEP_PREFERENCE, fallback_id
        ),
        ConsolidationFileRole.CANDIDATE: _ephemeral_review_approval(
            candidate_review, ReviewType.CONSOLIDATION_CANDIDATE, fallback_id
        ),
    }
    try:
        return tuple(
            item
            for source in endpoint_inputs
            for item in build_consolidation_file_preconditions(
                replace(source, review_approval=approvals[source.file_endpoint.role])
            )
        )
    except ValueError:
        return None


def _blocker(
    code: ConsolidationBlockerCode,
    refs: tuple[ConsolidationEvidenceReference, ...],
) -> ConsolidationBlocker:
    return ConsolidationBlocker(
        code,
        tuple(
            sorted(
                set(refs),
                key=lambda item: (
                    item.role.value,
                    item.kind.value,
                    item.ref_id,
                    item.material_fingerprint,
                ),
            )
        ),
    )


def _status(
    blockers: tuple[ConsolidationBlocker, ...],
    reviews: tuple[ConsolidationReviewSnapshot, ...],
    complete_direction: bool,
) -> ConsolidationPlanStatus:
    if blockers:
        return ConsolidationPlanStatus.BLOCKED
    if any(
        item.state in {ConsolidationReviewState.PENDING, ConsolidationReviewState.DEFERRED}
        for item in reviews
    ):
        return ConsolidationPlanStatus.REVIEW_REQUIRED
    if complete_direction and all(
        item.state is ConsolidationReviewState.ACCEPTED for item in reviews
    ):
        return ConsolidationPlanStatus.APPROVED_NON_EXECUTABLE
    return ConsolidationPlanStatus.BLOCKED


def build_consolidation_plan(
    inputs: ConsolidationPlannerInputs,
    *,
    clock: Callable[[], datetime],
) -> ConsolidationPlan:
    """Build one deterministic, immutable, always non-executable plan.

    ``clock`` is explicit so audit timestamps are testable.  It never affects
    the resulting ``content_hash``.
    """

    if not isinstance(inputs, ConsolidationPlannerInputs):
        raise TypeError("inputs must be ConsolidationPlannerInputs")
    if not callable(clock):
        raise TypeError("clock must be callable")
    created_at = clock()
    require_aware_datetime(created_at, "clock result")

    canonical_preference = _canonical_preference(inputs.keep_preference)
    if canonical_preference is not inputs.keep_preference:
        inputs = replace(inputs, keep_preference=canonical_preference)

    keep_review = _review_by_type(inputs.required_reviews, ReviewType.KEEP_PREFERENCE)
    preference = inputs.keep_preference
    quality = () if preference is None else preference.quality_evidence
    candidate_review = _review_by_type(
        inputs.required_reviews, ReviewType.CONSOLIDATION_CANDIDATE
    )
    endpoint_inputs = _endpoint_inputs(inputs)
    keep_review_compatible = preference is not None and _compatible_review(
        keep_review,
        ReviewType.KEEP_PREFERENCE,
        preference.evidence_fingerprint,
        preference.candidate_set_fingerprint,
        keep_preference_status=preference.status,
    )
    keep_review_accepted = (
        keep_review_compatible
        and keep_review is not None
        and keep_review.state is ConsolidationReviewState.ACCEPTED
    )
    directed_inputs = endpoint_inputs if keep_review_accepted else ()
    physical_preconditions = _physical_preconditions(
        endpoint_inputs,
        keep_review,
        candidate_review,
        inputs.consolidation_candidate_id,
    )
    physical_preconditions = () if physical_preconditions is None else physical_preconditions
    candidate_snapshot = (
        _candidate_snapshot(inputs, directed_inputs, physical_preconditions, created_at)
        if directed_inputs and physical_preconditions
        else None
    )
    candidate_review_compatible = (
        candidate_snapshot is not None
        and _compatible_review(
            candidate_review,
            ReviewType.CONSOLIDATION_CANDIDATE,
            candidate_snapshot.evidence_fingerprint,
            candidate_snapshot.candidate_set_fingerprint,
        )
    )
    resolved_keep_review = (
        _resolved_review(keep_review, compatible=keep_review_compatible)
        if preference is not None and preference.status is KeepPreferenceStatus.PREFERRED
        else None
    )
    resolved_candidate_review = _resolved_review(
        candidate_review, compatible=candidate_review_compatible
    )
    full_preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...] = ()
    if (
        directed_inputs
        and candidate_review_compatible
        and candidate_review is not None
        and candidate_review.state is ConsolidationReviewState.ACCEPTED
    ):
        try:
            full_preconditions = (
                *build_consolidation_file_preconditions(directed_inputs[0]),
                *build_consolidation_file_preconditions(directed_inputs[1]),
            )
        except ValueError:
            full_preconditions = ()
    physical_only_preconditions = tuple(
        item
        for item in physical_preconditions
        if item.code is not ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED
    )

    output_reviews = tuple(
        item
        for item in (resolved_keep_review, resolved_candidate_review)
        if item is not None
        and (
            item.review_type is ReviewType.KEEP_PREFERENCE
            or candidate_snapshot is not None
        )
    )
    hard_blockers = build_consolidation_blockers(
        ConsolidationHardBlockerInputs(
            identity=inputs.identity,
            protected_source_root=inputs.protected_source_root,
            lineage_matches=inputs.lineage_matches and _source_lineage_matches(inputs),
            source_scan_run_completed=inputs.source_scan_run_completed,
            file_sha256_equal=inputs.file_sha256_equal,
            quality_evidence=quality,
            dependencies=inputs.dependencies,
            required_reviews=output_reviews,
            preconditions=(full_preconditions or physical_preconditions),
            evidence_refs=inputs.evidence_refs,
        )
    )

    blockers = list(hard_blockers)
    if candidate_snapshot is None:
        # A consolidation review can only exist for an actually composed
        # candidate.  Without one, candidate-review blockers would merely be
        # a downstream cascade of an earlier identity/preference/precondition
        # failure rather than an actionable missing review.
        blockers = [
            item
            for item in blockers
            if item.code
            not in {
                ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
                ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED,
            }
        ]
    if _identity_needs_confirmation(inputs):
        blockers = [
            (
                replace(item, code=ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED)
                if item.code is ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE
                else item
            )
            for item in blockers
        ]
    actionable = _identity_is_actionable(inputs)
    if actionable:
        # S-EB08-04 uses precondition signatures as one available identity
        # witness.  The planner already has a validated exact identity, so an
        # absent or malformed precondition source remains a PRECONDITION
        # problem, never a false IDENTITY_NOT_ACTIONABLE result.
        blockers = [
            item
            for item in blockers
            if item.code is not ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE
        ]
    # S-EB08-04 uses precondition signatures to prove quality binding.  The
    # planner can establish the immutable quality-to-endpoint binding before
    # validating mutable FileRecord fields, so a physical mismatch remains a
    # precondition blocker and does not invalidate quality evidence.
    if _quality_slots_are_complete(inputs):
        blockers = [
            item
            for item in blockers
            if item.code is not ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE
        ]
    if (
        preference is not None
        and preference.status in {KeepPreferenceStatus.TIED, KeepPreferenceStatus.BLOCKED}
        and _quality_slots_are_complete(inputs)
    ):
        blockers = [
            item
            for item in blockers
            if item.code
            not in {
                ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE,
                ConsolidationBlockerCode.PRECONDITION_INCOMPLETE,
                ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
                ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
            }
        ]
    keep_review_waiting = (
        keep_review_compatible
        and keep_review is not None
        and keep_review.state
        in {
            ConsolidationReviewState.PENDING,
            ConsolidationReviewState.DEFERRED,
        }
    )
    non_accepted_candidate_review = (
        candidate_review_compatible
        and candidate_review is not None
        and candidate_review.state
        in {
            ConsolidationReviewState.PENDING,
            ConsolidationReviewState.DEFERRED,
            ConsolidationReviewState.REJECTED,
        }
    )
    if (
        (keep_review_waiting or non_accepted_candidate_review)
        and physical_preconditions
    ):
        # A compatible unresolved review is a review workflow state.  The
        # physical sources above were still fully validated through the shared
        # S-EB08-03 builder; only the intentionally unavailable approval
        # precondition is suppressed here.
        blockers = [
            item
            for item in blockers
            if item.code
            not in {
                ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE,
                ConsolidationBlockerCode.PRECONDITION_INCOMPLETE,
            }
        ]
        if keep_review_waiting:
            blockers = [
                item
                for item in blockers
                if item.code is not ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING
            ]
    if (
        preference is None
        or preference.status is not KeepPreferenceStatus.PREFERRED
        or not _preference_binds_identity(inputs)
    ):
        blockers.append(
            _blocker(ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED, inputs.evidence_refs)
        )
    elif not keep_review_compatible:
        blockers = [
            item
            for item in blockers
            if item.code is not ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_REJECTED
        ]
        blockers.append(
            _blocker(
                ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
                inputs.evidence_refs,
            )
        )
    if candidate_snapshot is not None and not candidate_review_compatible:
        blockers = [
            item
            for item in blockers
            if item.code is not ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED
        ]
        blockers.append(
            _blocker(ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING, inputs.evidence_refs)
        )
    blockers = list(
        sorted(
            set(blockers),
            key=lambda item: (
                item.code.value,
                tuple(
                    (ref.role.value, ref.kind.value, ref.ref_id, ref.material_fingerprint)
                    for ref in item.evidence_refs
                ),
            ),
        )
    )

    complete_direction = (
        candidate_snapshot is not None
        and len(directed_inputs) == 2
        and candidate_review_compatible
        and bool(full_preconditions)
    )
    status = _status(tuple(blockers), output_reviews, complete_direction)
    keeper = directed_inputs[0].file_endpoint if directed_inputs else None
    candidate = directed_inputs[1].file_endpoint if directed_inputs else None
    intents = inputs.future_operation_intents if candidate_snapshot is not None else ()
    if candidate_snapshot is None:
        keeper = None
        candidate = None
        full_preconditions = ()
        physical_only_preconditions = ()
    plan_preconditions = (
        full_preconditions
        if full_preconditions
        else physical_only_preconditions
        if candidate_snapshot is not None
        else ()
    )

    draft = ConsolidationPlan(
        id=inputs.plan_id,
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=CONSOLIDATION_PLAN_VERSION,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=inputs.scan_root_id,
        source_scan_run_id=inputs.source_scan_run_id,
        identity=inputs.identity,
        keeper=keeper,
        candidate=candidate,
        keep_preference=preference,
        consolidation_candidate=candidate_snapshot,
        dependencies=inputs.dependencies,
        quality_evidence=quality,
        required_reviews=output_reviews,
        preconditions=plan_preconditions,
        future_operation_intents=intents,
        blockers=tuple(blockers),
        status=status,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash="0" * 64,
        created_at=created_at,
    )
    return replace(draft, content_hash=consolidation_plan_content_hash(draft))


build_non_executable_consolidation_plan = build_consolidation_plan


__all__ = [
    "ConsolidationPlannerInputs",
    "build_consolidation_plan",
    "build_non_executable_consolidation_plan",
    "consolidation_candidate_material_fingerprints",
    "consolidation_candidate_physical_preconditions",
    "consolidation_candidate_precondition_fingerprint",
    "consolidation_dependency_fingerprint",
]
