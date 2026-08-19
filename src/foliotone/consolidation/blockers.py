"""Pure hard-blocker construction for non-executable consolidation plans."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.consolidation.contracts import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceReference,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationIdentitySnapshot,
    ConsolidationPreconditionCode,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
)
from foliotone.core import EntityKind, MatchStatus, RelationType, ReviewType

_DEPENDENCY_BLOCKERS = {
    ConsolidationDependencyKind.CALIBRE: (
        ConsolidationBlockerCode.CALIBRE_RELATIONSHIP_UNKNOWN,
        ConsolidationBlockerCode.CALIBRE_OWNERSHIP_PRESENT,
    ),
    ConsolidationDependencyKind.SIDECAR: (
        ConsolidationBlockerCode.SIDECAR_RELATIONSHIP_UNKNOWN,
        ConsolidationBlockerCode.SIDECAR_DEPENDENCY_PRESENT,
    ),
    ConsolidationDependencyKind.ARCHIVE: (
        ConsolidationBlockerCode.ARCHIVE_RELATIONSHIP_UNKNOWN,
        ConsolidationBlockerCode.ARCHIVE_MEMBERSHIP_PRESENT,
    ),
}

_REVIEW_BLOCKERS = {
    ReviewType.KEEP_PREFERENCE: (
        ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
        ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_REJECTED,
        "ebook-keep-preference",
        CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ),
    ReviewType.CONSOLIDATION_CANDIDATE: (
        ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
        ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED,
        "ebook-consolidation-candidate",
        CONSOLIDATION_CANDIDATE_DECISION,
    ),
}

_FILE_PRECONDITION_CODES = frozenset(
    {
        ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
        ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
        ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
        ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
        ConsolidationPreconditionCode.SIZE_MATCHES,
        ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
    }
)
_RELATIONSHIP_PRECONDITION_CODES = frozenset(
    {
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
    }
)
_DEPENDENCY_PRECONDITION_CODES = {
    ConsolidationDependencyKind.CALIBRE: (
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED
    ),
    ConsolidationDependencyKind.SIDECAR: (
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED
    ),
    ConsolidationDependencyKind.ARCHIVE: (
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED
    ),
}
_ROLE_REVIEW_TYPES = {
    ConsolidationFileRole.KEEPER: ReviewType.KEEP_PREFERENCE,
    ConsolidationFileRole.CANDIDATE: ReviewType.CONSOLIDATION_CANDIDATE,
}


@dataclass(frozen=True, slots=True)
class ConsolidationHardBlockerInputs:
    """Read-only observations consumed by :func:`build_consolidation_blockers`.

    The optional boolean completeness overrides are useful when an upstream
    adapter has already validated a source projection but cannot expose all
    of its internal records.  If omitted, the supplied immutable snapshots
    are checked structurally.  No path, command, or mutable runtime object is
    accepted by this contract.
    """

    identity: ConsolidationIdentitySnapshot | None = None
    protected_source_root: bool = False
    lineage_matches: bool = True
    source_scan_run_completed: bool = True
    file_sha256_equal: bool = True
    quality_evidence: tuple[ConsolidationQualityEvidenceSnapshot, ...] = ()
    dependencies: tuple[ConsolidationDependency, ...] = ()
    required_reviews: tuple[ConsolidationReviewSnapshot, ...] = ()
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...] = ()
    evidence_refs: tuple[ConsolidationEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        if self.identity is not None and not isinstance(
            self.identity, ConsolidationIdentitySnapshot
        ):
            raise ValueError("identity contains an invalid snapshot")
        if not isinstance(self.protected_source_root, bool):
            raise ValueError("protected_source_root must be a bool")
        for name in (
            "lineage_matches",
            "source_scan_run_completed",
            "file_sha256_equal",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")
        if any(
            not isinstance(item, ConsolidationQualityEvidenceSnapshot)
            for item in self.quality_evidence
        ):
            raise ValueError("quality_evidence contains an invalid snapshot")
        if any(not isinstance(item, ConsolidationDependency) for item in self.dependencies):
            raise ValueError("dependencies contains an invalid snapshot")
        if any(not isinstance(item, ConsolidationReviewSnapshot) for item in self.required_reviews):
            raise ValueError("required_reviews contains an invalid snapshot")
        if len({item.review_type for item in self.required_reviews}) != len(
            self.required_reviews
        ):
            raise ValueError("required_reviews must contain unique review types")
        if any(
            not isinstance(item, ConsolidationFilePreconditionSnapshot)
            for item in self.preconditions
        ):
            raise ValueError("preconditions contains an invalid snapshot")
        if any(not isinstance(item, ConsolidationEvidenceReference) for item in self.evidence_refs):
            raise ValueError("evidence_refs contains an invalid reference")
        if len(self.evidence_refs) > 64:
            raise ValueError("evidence_refs exceeds the blocker limit of 64")


# Shorter public spelling for callers that do not need the word ``Hard``.
ConsolidationBlockerInputs = ConsolidationHardBlockerInputs


def _sorted_evidence(
    refs: tuple[ConsolidationEvidenceReference, ...],
) -> tuple[ConsolidationEvidenceReference, ...]:
    return tuple(
        sorted(
            set(refs),
            key=lambda ref: (ref.role.value, ref.kind.value, ref.ref_id, ref.material_fingerprint),
        )
    )


def _blocker(
    code: ConsolidationBlockerCode,
    refs: tuple[ConsolidationEvidenceReference, ...],
) -> ConsolidationBlocker:
    return ConsolidationBlocker(code=code, evidence_refs=_sorted_evidence(refs))


def _identity_codes(inputs: ConsolidationHardBlockerInputs) -> tuple[ConsolidationBlockerCode, ...]:
    identity = inputs.identity
    signatures = _precondition_signatures(inputs.preconditions)
    if identity is None:
        return (ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,)

    if (
        identity.relation_type is not RelationType.EXACT_DUPLICATE
        or identity.left_kind is not EntityKind.FILE
        or identity.right_kind is not EntityKind.FILE
        or not inputs.file_sha256_equal
        or signatures is None
        or len({signature[5] for signature in signatures.values()}) != 1
    ):
        return (ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,)
    if (
        identity.status is not MatchStatus.CONFIRMED
        or not inputs.source_scan_run_completed
    ):
        return (ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED,)
    return ()


def _precondition_signatures(
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...],
) -> dict[ConsolidationFileRole, tuple[object, ...]] | None:
    signatures: dict[ConsolidationFileRole, tuple[object, ...]] = {}
    for role in ConsolidationFileRole:
        role_signatures = {
            (
                item.expected_file_id,
                item.expected_observation_id,
                item.expected_scan_root_id,
                item.expected_scan_run_id,
                item.expected_presence_state,
                item.expected_full_sha256,
                item.expected_size_bytes,
                item.expected_modified_at,
                item.expected_observed_at,
            )
            for item in preconditions
            if item.file_role is role
        }
        if len(role_signatures) != 1:
            return None
        signatures[role] = next(iter(role_signatures))
    return signatures


def _quality_is_complete(inputs: ConsolidationHardBlockerInputs) -> bool:
    identity = inputs.identity
    signatures = _precondition_signatures(inputs.preconditions)
    quality_by_role = {item.role: item for item in inputs.quality_evidence}
    return (
        identity is not None
        and signatures is not None
        and len(inputs.quality_evidence) == 2
        and set(quality_by_role) == set(ConsolidationFileRole)
        and all(
            item.scan_root_id == identity.scan_root_id
            and item.source_scan_run_id == identity.source_scan_run_id
            for item in inputs.quality_evidence
        )
        and all(
            quality_by_role[role].observation_id == signatures[role][1]
            for role in ConsolidationFileRole
        )
    )


def _preconditions_are_complete(inputs: ConsolidationHardBlockerInputs) -> bool:
    identity = inputs.identity
    if identity is None or not inputs.preconditions:
        return False
    signatures = _precondition_signatures(inputs.preconditions)
    if signatures is None:
        return False
    if len({(item.file_role, item.code) for item in inputs.preconditions}) != len(
        inputs.preconditions
    ):
        return False
    by_role = {
        role: {item.code for item in inputs.preconditions if item.file_role is role}
        for role in ConsolidationFileRole
    }
    required = _FILE_PRECONDITION_CODES | _RELATIONSHIP_PRECONDITION_CODES
    required |= {ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED}
    if by_role[ConsolidationFileRole.KEEPER] != required | {
        ConsolidationPreconditionCode.KEEPER_READABLE
    }:
        return False
    if by_role[ConsolidationFileRole.CANDIDATE] != required:
        return False
    if any(
        signature[2] != identity.scan_root_id
        or signature[3] != identity.source_scan_run_id
        for signature in signatures.values()
    ):
        return False
    if {signature[0] for signature in signatures.values()} != {
        identity.left_file_id,
        identity.right_file_id,
    }:
        return False

    for role in ConsolidationFileRole:
        role_preconditions = {
            item.code: item for item in inputs.preconditions if item.file_role is role
        }
        for kind, code in _DEPENDENCY_PRECONDITION_CODES.items():
            dependencies = tuple(
                item
                for item in inputs.dependencies
                if item.file_role is role and item.kind is kind
            )
            if len(dependencies) != 1:
                return False
            dependency = dependencies[0]
            precondition = role_preconditions[code]
            if (
                precondition.dependency_kind is not dependency.kind
                or precondition.dependency_state is not dependency.state
                or precondition.dependency_fingerprint
                != dependency.material_fingerprint
                or precondition.dependency_snapshot_kind != dependency.snapshot_kind
                or precondition.dependency_snapshot_id != dependency.snapshot_id
            ):
                return False

        review_type = _ROLE_REVIEW_TYPES[role]
        reviews = tuple(
            item for item in inputs.required_reviews if item.review_type is review_type
        )
        if len(reviews) != 1:
            return False
        review = reviews[0]
        review_precondition = role_preconditions[
            ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED
        ]
        if (
            review.state is not ConsolidationReviewState.ACCEPTED
            or review_precondition.review_item_id != review.review_item_id
            or review_precondition.review_decision_id != review.decision_id
            or review_precondition.review_decision_sequence_no
            != review.decision_sequence_no
            or review_precondition.review_decision_compatibility_version
            != review.decision_compatibility_version
            or review_precondition.review_evidence_fingerprint
            != review.evidence_fingerprint
            or review_precondition.review_candidate_set_fingerprint
            != review.candidate_set_fingerprint
        ):
            return False
    return True


def _review_codes(
    reviews: tuple[ConsolidationReviewSnapshot, ...],
) -> tuple[ConsolidationBlockerCode, ...]:
    result: list[ConsolidationBlockerCode] = []
    for review_type, (
        missing_code,
        rejected_code,
        producer_name,
        decision_compatibility_version,
    ) in _REVIEW_BLOCKERS.items():
        matches = tuple(review for review in reviews if review.review_type is review_type)
        if not matches:
            result.append(missing_code)
            continue
        review = matches[0]
        if (
            review.producer_name != producer_name
            or review.decision_compatibility_version != decision_compatibility_version
            or review.state
            in {
                ConsolidationReviewState.MISSING,
                ConsolidationReviewState.STALE,
            }
        ):
            result.append(missing_code)
            continue
        state = review.state
        if state is ConsolidationReviewState.REJECTED:
            result.append(rejected_code)
    return tuple(result)


def _dependency_codes(
    dependencies: tuple[ConsolidationDependency, ...],
) -> tuple[ConsolidationBlockerCode, ...]:
    result: list[ConsolidationBlockerCode] = []
    for role in ConsolidationFileRole:
        for kind, (unknown_code, present_code) in _DEPENDENCY_BLOCKERS.items():
            matches = tuple(
                item
                for item in dependencies
                if item.file_role is role and item.kind is kind
            )
            state = (
                matches[0].state
                if len(matches) == 1
                else ConsolidationDependencyState.UNKNOWN
            )
            if state is ConsolidationDependencyState.UNKNOWN:
                result.append(unknown_code)
            elif state is ConsolidationDependencyState.NOT_APPLICABLE and (
                matches[0].snapshot_kind is None or matches[0].snapshot_id is None
            ):
                # NOT_APPLICABLE is safe only with an adapter-bound proof snapshot.
                result.append(unknown_code)
            elif (
                role is ConsolidationFileRole.CANDIDATE
                and state is ConsolidationDependencyState.KNOWN_PRESENT
            ):
                result.append(present_code)
    return tuple(result)


def build_consolidation_blockers(
    inputs: ConsolidationHardBlockerInputs,
) -> tuple[ConsolidationBlocker, ...]:
    """Build sorted, deduplicated hard blockers from immutable snapshots.

    ``PENDING`` and ``DEFERRED`` reviews intentionally produce no blocker;
    their later status projection belongs to S-EB08-07.  Missing and rejected
    reviews, incomplete evidence, and unsafe dependencies remain blockers.
    """

    if not isinstance(inputs, ConsolidationHardBlockerInputs):
        raise TypeError("inputs must be ConsolidationHardBlockerInputs")

    codes: set[ConsolidationBlockerCode] = set(_identity_codes(inputs))
    if inputs.protected_source_root:
        codes.add(ConsolidationBlockerCode.PROTECTED_SOURCE_ROOT)
    if not inputs.lineage_matches:
        codes.add(ConsolidationBlockerCode.LINEAGE_MISMATCH)
    if not _quality_is_complete(inputs):
        codes.add(ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE)
    if not _preconditions_are_complete(inputs):
        codes.add(ConsolidationBlockerCode.PRECONDITION_INCOMPLETE)
    codes.update(_review_codes(inputs.required_reviews))
    codes.update(_dependency_codes(inputs.dependencies))
    refs = _sorted_evidence(inputs.evidence_refs)
    return tuple(_blocker(code, refs) for code in sorted(codes, key=lambda item: item.value))


# Explicit synonym matching the package name used in planning prose.
build_consolidation_hard_blockers = build_consolidation_blockers


__all__ = [
    "ConsolidationBlockerInputs",
    "ConsolidationHardBlockerInputs",
    "build_consolidation_blockers",
    "build_consolidation_hard_blockers",
]
