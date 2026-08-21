"""Pure, path-free contracts for a future fenced quarantine authorization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from foliotone.consolidation.contracts import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationIdentitySnapshot,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
)
from foliotone.consolidation.serialization import consolidation_plan_content_hash
from foliotone.core import EntityId, EntityKind, MatchStatus, RelationType, ReviewType

QUARANTINE_AUTHORIZATION_PROFILE: Final = "quarantine-authorization/v1"
QUARANTINE_EXECUTION_PROFILE: Final = "quarantine-execution/v1"
QUARANTINE_AUTHORIZATION_DOMAIN: Final = b"foliotone:quarantine-authorization/v1\x00"
QUARANTINE_REVIEW_DOMAIN: Final = b"foliotone:quarantine-review-set/v1\x00"
QUARANTINE_AUTHORIZATION_NAMESPACE: Final = UUID(
    "e9f0f9b0-fa5e-5b6d-9c10-22cfe3912e47"
)
MAX_QUARANTINE_AUTHORIZATION_LIFETIME: Final = timedelta(minutes=15)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class QuarantineEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"


class QuarantineAuthorizationBlockerCode(StrEnum):
    PLAN_MATERIAL_INVALID = "PLAN_MATERIAL_INVALID"
    PLAN_NOT_APPROVED = "PLAN_NOT_APPROVED"
    IDENTITY_NOT_EXACT_DUPLICATE = "IDENTITY_NOT_EXACT_DUPLICATE"
    ENDPOINTS_INCOMPLETE = "ENDPOINTS_INCOMPLETE"
    REVIEWS_NOT_ACCEPTED = "REVIEWS_NOT_ACCEPTED"
    DEPENDENCY_NOT_KNOWN_NONE = "DEPENDENCY_NOT_KNOWN_NONE"
    PRECONDITIONS_INCOMPLETE = "PRECONDITIONS_INCOMPLETE"
    CURRENT_EVIDENCE_MISMATCH = "CURRENT_EVIDENCE_MISMATCH"
    AUTHORIZATION_WINDOW_INVALID = "AUTHORIZATION_WINDOW_INVALID"
    CAPABILITY_INVALID = "CAPABILITY_INVALID"


class QuarantineRunStatus(StrEnum):
    PREPARED = "PREPARED"
    MOVED = "MOVED"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    STALE = "STALE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class QuarantineAuthorizationSnapshot:
    id: EntityId
    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    scan_root_id: EntityId = field(repr=False)
    keeper_file_id: EntityId = field(repr=False)
    candidate_file_id: EntityId = field(repr=False)
    keeper_observation_id: EntityId = field(repr=False)
    candidate_observation_id: EntityId = field(repr=False)
    keeper_full_sha256: str = field(repr=False)
    candidate_full_sha256: str = field(repr=False)
    quarantine_capability_id: EntityId = field(repr=False)
    review_fingerprint: str = field(repr=False)
    authorized_at: datetime
    expires_at: datetime
    content_hash: str = field(repr=False)
    profile: str = QUARANTINE_AUTHORIZATION_PROFILE

    def __post_init__(self) -> None:
        if self.profile != QUARANTINE_AUTHORIZATION_PROFILE:
            raise ValueError("quarantine authorization profile is invalid")
        for name in (
            "id",
            "plan_id",
            "scan_root_id",
            "keeper_file_id",
            "candidate_file_id",
            "keeper_observation_id",
            "candidate_observation_id",
            "quarantine_capability_id",
        ):
            if not isinstance(getattr(self, name), EntityId):
                raise ValueError("quarantine authorization IDs are invalid")
        for name in (
            "plan_content_hash",
            "keeper_full_sha256",
            "candidate_full_sha256",
            "review_fingerprint",
            "content_hash",
        ):
            _require_sha256(getattr(self, name))
        _validate_window(self.authorized_at, self.expires_at)
        if self.keeper_file_id == self.candidate_file_id or (
            self.keeper_observation_id == self.candidate_observation_id
        ):
            raise ValueError("quarantine endpoints must be different")
        expected_hash = _authorization_content_hash(
            self.plan_id,
            self.plan_content_hash,
            self.scan_root_id,
            self.keeper_file_id,
            self.candidate_file_id,
            self.keeper_observation_id,
            self.candidate_observation_id,
            self.keeper_full_sha256,
            self.candidate_full_sha256,
            self.quarantine_capability_id,
            self.review_fingerprint,
            self.authorized_at,
            self.expires_at,
        )
        if self.content_hash != expected_hash or self.id != _authorization_id(expected_hash):
            raise ValueError("quarantine authorization material is inconsistent")


@dataclass(frozen=True, slots=True)
class QuarantineAuthorizationAssessment:
    status: QuarantineEligibilityStatus
    blockers: tuple[QuarantineAuthorizationBlockerCode, ...]
    authorization: QuarantineAuthorizationSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, QuarantineEligibilityStatus):
            raise ValueError("quarantine eligibility status is invalid")
        if (
            not isinstance(self.blockers, tuple)
            or any(
                not isinstance(item, QuarantineAuthorizationBlockerCode)
                for item in self.blockers
            )
            or self.blockers != tuple(sorted(set(self.blockers), key=lambda item: item.value))
        ):
            raise ValueError("quarantine blockers are not canonical")
        if self.status is QuarantineEligibilityStatus.ELIGIBLE:
            if self.blockers or not isinstance(
                self.authorization, QuarantineAuthorizationSnapshot
            ):
                raise ValueError("eligible quarantine assessment requires authorization")
        elif self.authorization is not None or not self.blockers:
            raise ValueError("blocked quarantine assessment requires blockers only")


def build_quarantine_authorization(
    *,
    plan: ConsolidationPlan,
    current_keeper: ConsolidationFileEndpoint,
    current_candidate: ConsolidationFileEndpoint,
    current_dependencies: tuple[ConsolidationDependency, ...],
    current_reviews: tuple[ConsolidationReviewSnapshot, ...],
    quarantine_capability_id: EntityId,
    authorized_at: datetime,
    expires_at: datetime,
) -> QuarantineAuthorizationAssessment:
    """Reduce current opaque evidence to a non-executing authorization snapshot."""

    if not isinstance(plan, ConsolidationPlan):
        raise ValueError("plan must be a ConsolidationPlan")
    blockers: set[QuarantineAuthorizationBlockerCode] = set()
    try:
        material_valid = consolidation_plan_content_hash(plan) == plan.content_hash
    except (TypeError, ValueError):
        material_valid = False
    if not material_valid:
        blockers.add(QuarantineAuthorizationBlockerCode.PLAN_MATERIAL_INVALID)
    if (
        plan.status is not ConsolidationPlanStatus.APPROVED_NON_EXECUTABLE
        or plan.execution_state is not ConsolidationExecutionState.NOT_EXECUTABLE
        or plan.blockers
    ):
        blockers.add(QuarantineAuthorizationBlockerCode.PLAN_NOT_APPROVED)
    identity = plan.identity
    if (
        not isinstance(identity, ConsolidationIdentitySnapshot)
        or identity.relation_type is not RelationType.EXACT_DUPLICATE
        or identity.left_kind is not EntityKind.FILE
        or identity.right_kind is not EntityKind.FILE
        or identity.status is not MatchStatus.CONFIRMED
    ):
        blockers.add(
            QuarantineAuthorizationBlockerCode.IDENTITY_NOT_EXACT_DUPLICATE
        )
    if not isinstance(plan.keeper, ConsolidationFileEndpoint) or not isinstance(
        plan.candidate, ConsolidationFileEndpoint
    ):
        blockers.add(QuarantineAuthorizationBlockerCode.ENDPOINTS_INCOMPLETE)
    if not _reviews_are_accepted(plan):
        blockers.add(QuarantineAuthorizationBlockerCode.REVIEWS_NOT_ACCEPTED)
    if not _candidate_dependencies_are_known_none(plan.dependencies):
        blockers.add(
            QuarantineAuthorizationBlockerCode.DEPENDENCY_NOT_KNOWN_NONE
        )
    if not _preconditions_are_complete(plan):
        blockers.add(QuarantineAuthorizationBlockerCode.PRECONDITIONS_INCOMPLETE)
    if (
        not isinstance(current_keeper, ConsolidationFileEndpoint)
        or not isinstance(current_candidate, ConsolidationFileEndpoint)
        or not isinstance(current_dependencies, tuple)
        or not isinstance(current_reviews, tuple)
        or current_keeper != plan.keeper
        or current_candidate != plan.candidate
        or current_dependencies != plan.dependencies
        or current_reviews != plan.required_reviews
    ):
        blockers.add(QuarantineAuthorizationBlockerCode.CURRENT_EVIDENCE_MISMATCH)
    try:
        _validate_window(authorized_at, expires_at)
    except ValueError:
        blockers.add(
            QuarantineAuthorizationBlockerCode.AUTHORIZATION_WINDOW_INVALID
        )
    if not isinstance(quarantine_capability_id, EntityId):
        blockers.add(QuarantineAuthorizationBlockerCode.CAPABILITY_INVALID)

    if blockers:
        return QuarantineAuthorizationAssessment(
            QuarantineEligibilityStatus.BLOCKED,
            tuple(sorted(blockers, key=lambda item: item.value)),
        )

    assert plan.keeper is not None and plan.candidate is not None
    review_fingerprint = _review_fingerprint(plan.required_reviews)
    content_hash = _authorization_content_hash(
        plan.id,
        plan.content_hash,
        plan.scan_root_id,
        plan.keeper.file_id,
        plan.candidate.file_id,
        plan.keeper.observation_id,
        plan.candidate.observation_id,
        plan.keeper.expected_full_sha256,
        plan.candidate.expected_full_sha256,
        quarantine_capability_id,
        review_fingerprint,
        authorized_at,
        expires_at,
    )
    authorization = QuarantineAuthorizationSnapshot(
        _authorization_id(content_hash),
        plan.id,
        plan.content_hash,
        plan.scan_root_id,
        plan.keeper.file_id,
        plan.candidate.file_id,
        plan.keeper.observation_id,
        plan.candidate.observation_id,
        plan.keeper.expected_full_sha256,
        plan.candidate.expected_full_sha256,
        quarantine_capability_id,
        review_fingerprint,
        authorized_at,
        expires_at,
        content_hash,
    )
    return QuarantineAuthorizationAssessment(
        QuarantineEligibilityStatus.ELIGIBLE, (), authorization
    )


def _reviews_are_accepted(plan: ConsolidationPlan) -> bool:
    reviews = plan.required_reviews
    if not (
        isinstance(reviews, tuple)
        and len(reviews) == 2
        and all(isinstance(item, ConsolidationReviewSnapshot) for item in reviews)
        and len({item.review_type for item in reviews}) == 2
        and all(item.state is ConsolidationReviewState.ACCEPTED for item in reviews)
        and plan.keep_preference is not None
        and plan.consolidation_candidate is not None
    ):
        return False
    expected = {
        ReviewType.KEEP_PREFERENCE: (
            "ebook-keep-preference",
            CONSOLIDATION_KEEP_PREFERENCE_DECISION,
            plan.keep_preference.evidence_fingerprint,
            plan.keep_preference.candidate_set_fingerprint,
        ),
        ReviewType.CONSOLIDATION_CANDIDATE: (
            "ebook-consolidation-candidate",
            CONSOLIDATION_CANDIDATE_DECISION,
            plan.consolidation_candidate.evidence_fingerprint,
            plan.consolidation_candidate.candidate_set_fingerprint,
        ),
    }
    return all(
        (
            item.producer_name,
            item.decision_compatibility_version,
            item.evidence_fingerprint,
            item.candidate_set_fingerprint,
        )
        == expected[item.review_type]
        for item in reviews
    )


def _candidate_dependencies_are_known_none(
    dependencies: tuple[ConsolidationDependency, ...],
) -> bool:
    if not isinstance(dependencies, tuple) or any(
        not isinstance(item, ConsolidationDependency) for item in dependencies
    ):
        return False
    expected_pairs = {
        (role, kind)
        for role in ConsolidationFileRole
        for kind in ConsolidationDependencyKind
    }
    if {(item.file_role, item.kind) for item in dependencies} != expected_pairs:
        return False
    candidate = tuple(
        item
        for item in dependencies
        if item.file_role is ConsolidationFileRole.CANDIDATE
    )
    return (
        len(candidate) == len(ConsolidationDependencyKind)
        and {item.kind for item in candidate} == set(ConsolidationDependencyKind)
        and all(item.state is ConsolidationDependencyState.KNOWN_NONE for item in candidate)
    )


def _preconditions_are_complete(plan: ConsolidationPlan) -> bool:
    if not isinstance(plan.preconditions, tuple) or any(
        not isinstance(item, ConsolidationFilePreconditionSnapshot)
        for item in plan.preconditions
    ):
        return False
    base = set(ConsolidationPreconditionCode) - {
        ConsolidationPreconditionCode.KEEPER_READABLE
    }
    expected = {
        ConsolidationFileRole.KEEPER: set(ConsolidationPreconditionCode),
        ConsolidationFileRole.CANDIDATE: base,
    }
    actual = {
        role: {item.code for item in plan.preconditions if item.file_role is role}
        for role in ConsolidationFileRole
    }
    if len(plan.preconditions) != 21 or actual != expected:
        return False
    endpoints = {
        ConsolidationFileRole.KEEPER: plan.keeper,
        ConsolidationFileRole.CANDIDATE: plan.candidate,
    }
    dependencies = {
        (item.file_role, item.kind): item for item in plan.dependencies
    }
    reviews = {item.review_type: item for item in plan.required_reviews}
    relationship_kinds = {
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED:
            ConsolidationDependencyKind.CALIBRE,
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED:
            ConsolidationDependencyKind.SIDECAR,
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED:
            ConsolidationDependencyKind.ARCHIVE,
    }
    review_types = {
        ConsolidationFileRole.KEEPER: ReviewType.KEEP_PREFERENCE,
        ConsolidationFileRole.CANDIDATE: ReviewType.CONSOLIDATION_CANDIDATE,
    }
    for item in plan.preconditions:
        endpoint = endpoints[item.file_role]
        if endpoint is None or (
            item.expected_file_id,
            item.expected_observation_id,
            item.expected_scan_root_id,
            item.expected_scan_run_id,
            item.expected_presence_state,
            item.expected_full_sha256,
            item.expected_size_bytes,
            item.expected_modified_at,
            item.expected_observed_at,
        ) != (
            endpoint.file_id,
            endpoint.observation_id,
            endpoint.scan_root_id,
            endpoint.source_scan_run_id,
            endpoint.expected_presence_state,
            endpoint.expected_full_sha256,
            endpoint.expected_size_bytes,
            endpoint.expected_modified_at,
            endpoint.expected_observed_at,
        ):
            return False
        if item.code in relationship_kinds:
            dependency = dependencies.get(
                (item.file_role, relationship_kinds[item.code])
            )
            if dependency is None or (
                item.dependency_kind,
                item.dependency_state,
                item.dependency_fingerprint,
                item.dependency_snapshot_kind,
                item.dependency_snapshot_id,
            ) != (
                dependency.kind,
                dependency.state,
                dependency.material_fingerprint,
                dependency.snapshot_kind,
                dependency.snapshot_id,
            ):
                return False
        elif item.code is ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED:
            review = reviews.get(review_types[item.file_role])
            if review is None or (
                item.review_item_id,
                item.review_decision_id,
                item.review_decision_sequence_no,
                item.review_decision_compatibility_version,
                item.review_evidence_fingerprint,
                item.review_candidate_set_fingerprint,
            ) != (
                review.review_item_id,
                review.decision_id,
                review.decision_sequence_no,
                review.decision_compatibility_version,
                review.evidence_fingerprint,
                review.candidate_set_fingerprint,
            ):
                return False
    return True


def _review_fingerprint(reviews: tuple[ConsolidationReviewSnapshot, ...]) -> str:
    material = [
        {
            "review_type": item.review_type.value,
            "state": item.state.value,
            "review_item_id": str(item.review_item_id),
            "decision_id": str(item.decision_id),
            "decision_sequence_no": item.decision_sequence_no,
            "producer_name": item.producer_name,
            "decision_compatibility_version": item.decision_compatibility_version,
            "evidence_fingerprint": item.evidence_fingerprint,
            "candidate_set_fingerprint": item.candidate_set_fingerprint,
        }
        for item in sorted(reviews, key=lambda value: value.review_type.value)
    ]
    return hashlib.sha256(QUARANTINE_REVIEW_DOMAIN + _canonical_json(material)).hexdigest()


def _authorization_content_hash(
    plan_id: EntityId,
    plan_content_hash: str,
    scan_root_id: EntityId,
    keeper_file_id: EntityId,
    candidate_file_id: EntityId,
    keeper_observation_id: EntityId,
    candidate_observation_id: EntityId,
    keeper_full_sha256: str,
    candidate_full_sha256: str,
    quarantine_capability_id: EntityId,
    review_fingerprint: str,
    authorized_at: datetime,
    expires_at: datetime,
) -> str:
    material = {
        "profile": QUARANTINE_AUTHORIZATION_PROFILE,
        "plan_id": str(plan_id),
        "plan_content_hash": plan_content_hash,
        "scan_root_id": str(scan_root_id),
        "keeper_file_id": str(keeper_file_id),
        "candidate_file_id": str(candidate_file_id),
        "keeper_observation_id": str(keeper_observation_id),
        "candidate_observation_id": str(candidate_observation_id),
        "keeper_full_sha256": keeper_full_sha256,
        "candidate_full_sha256": candidate_full_sha256,
        "quarantine_capability_id": str(quarantine_capability_id),
        "review_fingerprint": review_fingerprint,
        "authorized_at": _timestamp(authorized_at),
        "expires_at": _timestamp(expires_at),
    }
    return hashlib.sha256(
        QUARANTINE_AUTHORIZATION_DOMAIN + _canonical_json(material)
    ).hexdigest()


def _authorization_id(content_hash: str) -> EntityId:
    _require_sha256(content_hash)
    return EntityId(uuid5(QUARANTINE_AUTHORIZATION_NAMESPACE, content_hash))


def _validate_window(authorized_at: datetime, expires_at: datetime) -> None:
    for value in (authorized_at, expires_at):
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("quarantine authorization timestamps must be aware")
    lifetime = expires_at - authorized_at
    if lifetime <= timedelta(0) or lifetime > MAX_QUARANTINE_AUTHORIZATION_LIFETIME:
        raise ValueError("quarantine authorization window is invalid")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: object) -> bytes:
    return unicodedata.normalize(
        "NFC",
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    ).encode("utf-8")


def _require_sha256(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("quarantine material hash is invalid")
    return value


__all__ = [
    "MAX_QUARANTINE_AUTHORIZATION_LIFETIME",
    "QUARANTINE_AUTHORIZATION_NAMESPACE",
    "QUARANTINE_AUTHORIZATION_PROFILE",
    "QUARANTINE_EXECUTION_PROFILE",
    "QuarantineAuthorizationAssessment",
    "QuarantineAuthorizationBlockerCode",
    "QuarantineAuthorizationSnapshot",
    "QuarantineEligibilityStatus",
    "QuarantineRunStatus",
    "build_quarantine_authorization",
]
