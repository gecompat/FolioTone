"""Immutable, path-free contracts for non-executable consolidation plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    PresenceState,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
)
from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.resolution_models import _require_sha256
from foliotone.workflows.quality import (
    EBOOK_QUALITY_PROFILE,
)

CONSOLIDATION_PLAN_PROFILE = "consolidation-plan/v1"
CONSOLIDATION_PLAN_VERSION = 1
CONSOLIDATION_PLAN_SERIALIZER_VERSION = "canonical-json/v1"
CONSOLIDATION_QUALITY_EVIDENCE_PROFILE = "consolidation-quality-evidence/v1"
CONSOLIDATION_COLLECTION_PROFILE = "ebook-collection-analysis/v1"
CONSOLIDATION_ANALYSIS_PROFILE = "ebook-analysis-workflow/v3"
CONSOLIDATION_KEEP_PREFERENCE_PROFILE = "ebook-keep-preference/v1"
CONSOLIDATION_KEEP_PREFERENCE_VERSION = "1"
CONSOLIDATION_KEEP_PREFERENCE_DECISION = "ebook-keep-preference-decision/v1"
CONSOLIDATION_CANDIDATE_PROFILE = "ebook-consolidation-candidate/v1"
CONSOLIDATION_CANDIDATE_DECISION = "ebook-consolidation-candidate-decision/v1"
CONSOLIDATION_FORMATS = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")

MAX_CONSOLIDATION_EVIDENCE_REFS = 1024
MAX_CONSOLIDATION_DEPENDENCIES = 6
MAX_CONSOLIDATION_REVIEWS = 16
MAX_CONSOLIDATION_PRECONDITIONS = 32
MAX_CONSOLIDATION_INTENTS = 16
MAX_CONSOLIDATION_BLOCKERS = 32
MAX_CONSOLIDATION_BLOCKER_EVIDENCE_REFS = 64
MAX_CONSOLIDATION_REASONS = 64


class ConsolidationPlanStatus(StrEnum):
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_NON_EXECUTABLE = "APPROVED_NON_EXECUTABLE"


class ConsolidationExecutionState(StrEnum):
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


class ConsolidationBlockerCode(StrEnum):
    IDENTITY_NOT_ACTIONABLE = "IDENTITY_NOT_ACTIONABLE"
    IDENTITY_NOT_CONFIRMED = "IDENTITY_NOT_CONFIRMED"
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    PRECONDITION_INCOMPLETE = "PRECONDITION_INCOMPLETE"
    PROTECTED_SOURCE_ROOT = "PROTECTED_SOURCE_ROOT"
    QUALITY_EVIDENCE_INCOMPLETE = "QUALITY_EVIDENCE_INCOMPLETE"
    KEEP_PREFERENCE_UNRESOLVED = "KEEP_PREFERENCE_UNRESOLVED"
    KEEP_PREFERENCE_REVIEW_MISSING = "KEEP_PREFERENCE_REVIEW_MISSING"
    KEEP_PREFERENCE_REVIEW_REJECTED = "KEEP_PREFERENCE_REVIEW_REJECTED"
    CONSOLIDATION_REVIEW_MISSING = "CONSOLIDATION_REVIEW_MISSING"
    CONSOLIDATION_REVIEW_REJECTED = "CONSOLIDATION_REVIEW_REJECTED"
    CALIBRE_RELATIONSHIP_UNKNOWN = "CALIBRE_RELATIONSHIP_UNKNOWN"
    CALIBRE_OWNERSHIP_PRESENT = "CALIBRE_OWNERSHIP_PRESENT"
    SIDECAR_RELATIONSHIP_UNKNOWN = "SIDECAR_RELATIONSHIP_UNKNOWN"
    SIDECAR_DEPENDENCY_PRESENT = "SIDECAR_DEPENDENCY_PRESENT"
    ARCHIVE_RELATIONSHIP_UNKNOWN = "ARCHIVE_RELATIONSHIP_UNKNOWN"
    ARCHIVE_MEMBERSHIP_PRESENT = "ARCHIVE_MEMBERSHIP_PRESENT"


class ConsolidationFileRole(StrEnum):
    KEEPER = "KEEPER"
    CANDIDATE = "CANDIDATE"


class ConsolidationEvidenceRole(StrEnum):
    IDENTITY = "IDENTITY"
    KEEPER_QUALITY = "KEEPER_QUALITY"
    CANDIDATE_QUALITY = "CANDIDATE_QUALITY"
    KEEP_PREFERENCE = "KEEP_PREFERENCE"
    DEPENDENCY = "DEPENDENCY"
    REVIEW = "REVIEW"


class ConsolidationEvidenceKind(StrEnum):
    RELATION_CANDIDATE = "RELATION_CANDIDATE"
    RELATION_CANDIDATE_EVIDENCE = "RELATION_CANDIDATE_EVIDENCE"
    REVIEW_DECISION = "REVIEW_DECISION"
    FINGERPRINT = "FINGERPRINT"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    TOOL_RESULT = "TOOL_RESULT"
    EBOOK_COLLECTION_ITEM = "EBOOK_COLLECTION_ITEM"
    EBOOK_COLLECTION_FINDING = "EBOOK_COLLECTION_FINDING"
    QUALITY_EVIDENCE = "QUALITY_EVIDENCE"
    CALIBRE_SNAPSHOT = "CALIBRE_SNAPSHOT"
    CALIBRE_FINDING = "CALIBRE_FINDING"
    CALIBRE_FORMAT = "CALIBRE_FORMAT"
    CALIBRE_SIDECAR = "CALIBRE_SIDECAR"


class ConsolidationDependencyKind(StrEnum):
    CALIBRE = "CALIBRE"
    SIDECAR = "SIDECAR"
    ARCHIVE = "ARCHIVE"


class ConsolidationDependencyState(StrEnum):
    KNOWN_NONE = "KNOWN_NONE"
    KNOWN_PRESENT = "KNOWN_PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConsolidationIntentCode(StrEnum):
    KEEP = "KEEP"
    QUARANTINE = "QUARANTINE"
    VERIFY = "VERIFY"
    ROLLBACK = "ROLLBACK"
    PURGE = "PURGE"
    CALIBRE_RECONCILE = "CALIBRE_RECONCILE"
    SIDECAR_RECONCILE = "SIDECAR_RECONCILE"
    ARCHIVE_RECONCILE = "ARCHIVE_RECONCILE"
    EMPTY_DIRECTORY_REVIEW = "EMPTY_DIRECTORY_REVIEW"


class KeepPreferenceStatus(StrEnum):
    PREFERRED = "PREFERRED"
    TIED = "TIED"
    BLOCKED = "BLOCKED"


class KeepPreferenceReasonCode(StrEnum):
    FEWER_INCOMPLETE_DIMENSIONS = "FEWER_INCOMPLETE_DIMENSIONS"
    FEWER_ACTION_REQUIRED_DIMENSIONS = "FEWER_ACTION_REQUIRED_DIMENSIONS"
    FEWER_REVIEW_DIMENSIONS = "FEWER_REVIEW_DIMENSIONS"
    PREFERRED_FORMAT = "PREFERRED_FORMAT"
    SIZE_TIE_BREAKER = "SIZE_TIE_BREAKER"
    TIED = "TIED"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"


class SizeTieBreakerPolicy(StrEnum):
    DISABLED = "DISABLED"
    PREFER_SMALLER = "PREFER_SMALLER"
    PREFER_LARGER = "PREFER_LARGER"


class ConsolidationReviewState(StrEnum):
    MISSING = "MISSING"
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class ConsolidationPreconditionCode(StrEnum):
    FILE_RECORD_UNCHANGED = "FILE_RECORD_UNCHANGED"
    FILE_OBSERVATION_CURRENT = "FILE_OBSERVATION_CURRENT"
    PRESENCE_IS_PRESENT = "PRESENCE_IS_PRESENT"
    FULL_SHA256_MATCHES = "FULL_SHA256_MATCHES"
    SIZE_MATCHES = "SIZE_MATCHES"
    MODIFIED_AT_MATCHES = "MODIFIED_AT_MATCHES"
    KEEPER_READABLE = "KEEPER_READABLE"
    CALIBRE_RELATIONSHIP_UNCHANGED = "CALIBRE_RELATIONSHIP_UNCHANGED"
    SIDECAR_RELATIONSHIP_UNCHANGED = "SIDECAR_RELATIONSHIP_UNCHANGED"
    ARCHIVE_RELATIONSHIP_UNCHANGED = "ARCHIVE_RELATIONSHIP_UNCHANGED"
    REVIEW_APPROVALS_UNCHANGED = "REVIEW_APPROVALS_UNCHANGED"


def _id(value: EntityId, field_name: str) -> EntityId:
    if not isinstance(value, EntityId):
        raise ValueError(f"{field_name} must be an EntityId")
    return value


def _ordered_ids(left: EntityId, right: EntityId) -> bool:
    return str(left).casefold() < str(right).casefold()


def _tuple_limit(values: tuple[object, ...], limit: int, field_name: str) -> None:
    if len(values) > limit:
        raise ValueError(f"{field_name} exceeds the configured limit of {limit}")


def _unique(values: tuple[object, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} entries must be unique")


def _text(value: str, field_name: str) -> str:
    return require_non_empty(value, field_name)


@dataclass(frozen=True, slots=True)
class ConsolidationEvidenceReference:
    kind: ConsolidationEvidenceKind
    ref_id: str = field(repr=False)
    role: ConsolidationEvidenceRole
    material_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConsolidationEvidenceKind):
            raise ValueError("kind must be a ConsolidationEvidenceKind")
        if not isinstance(self.role, ConsolidationEvidenceRole):
            raise ValueError("role must be a ConsolidationEvidenceRole")
        object.__setattr__(self, "ref_id", _text(self.ref_id, "ref_id"))
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ConsolidationBlocker:
    code: ConsolidationBlockerCode
    evidence_refs: tuple[ConsolidationEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, ConsolidationBlockerCode):
            raise ValueError("code must be a ConsolidationBlockerCode")
        _tuple_limit(self.evidence_refs, MAX_CONSOLIDATION_BLOCKER_EVIDENCE_REFS, "evidence_refs")
        if any(not isinstance(ref, ConsolidationEvidenceReference) for ref in self.evidence_refs):
            raise ValueError("evidence_refs must contain ConsolidationEvidenceReference values")
        _unique(self.evidence_refs, "evidence_refs")


@dataclass(frozen=True, slots=True)
class ConsolidationDependency:
    file_role: ConsolidationFileRole
    kind: ConsolidationDependencyKind
    state: ConsolidationDependencyState
    material_fingerprint: str = field(repr=False)
    snapshot_kind: str | None = None
    snapshot_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.file_role, ConsolidationFileRole):
            raise ValueError("file_role must be a ConsolidationFileRole")
        if not isinstance(self.kind, ConsolidationDependencyKind):
            raise ValueError("kind must be a ConsolidationDependencyKind")
        if not isinstance(self.state, ConsolidationDependencyState):
            raise ValueError("state must be a ConsolidationDependencyState")
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )
        if self.snapshot_kind is not None:
            object.__setattr__(self, "snapshot_kind", _text(self.snapshot_kind, "snapshot_kind"))
        if self.snapshot_id is not None:
            _id(self.snapshot_id, "snapshot_id")
        if self.state is ConsolidationDependencyState.KNOWN_NONE and self.snapshot_id is not None:
            raise ValueError("KNOWN_NONE dependencies cannot carry a snapshot_id")


@dataclass(frozen=True, slots=True)
class ConsolidationIdentitySnapshot:
    relation_candidate_id: EntityId
    relation_type: RelationType
    left_kind: EntityKind
    right_kind: EntityKind
    left_file_id: EntityId
    right_file_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    status: MatchStatus
    matcher_version: str
    decision_compatibility_version: str
    evidence_fingerprint: str = field(repr=False)
    candidate_set_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in (
            "relation_candidate_id",
            "left_file_id",
            "right_file_id",
            "scan_root_id",
            "source_scan_run_id",
        ):
            _id(getattr(self, name), name)
        if not isinstance(self.relation_type, RelationType):
            raise ValueError("relation_type must be a RelationType")
        if not isinstance(self.left_kind, EntityKind) or not isinstance(
            self.right_kind, EntityKind
        ):
            raise ValueError("identity endpoint kinds must be EntityKind values")
        if not isinstance(self.status, MatchStatus):
            raise ValueError("status must be a MatchStatus")
        object.__setattr__(self, "matcher_version", _text(self.matcher_version, "matcher_version"))
        object.__setattr__(
            self,
            "decision_compatibility_version",
            _text(self.decision_compatibility_version, "decision_compatibility_version"),
        )
        if self.left_file_id == self.right_file_id:
            raise ValueError("identity endpoints must be different")
        if not _ordered_ids(self.left_file_id, self.right_file_id):
            raise ValueError("identity endpoints must be canonically ordered")
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _require_sha256(self.evidence_fingerprint, "evidence_fingerprint"),
        )
        object.__setattr__(
            self,
            "candidate_set_fingerprint",
            _require_sha256(self.candidate_set_fingerprint, "candidate_set_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ConsolidationFileEndpoint:
    role: ConsolidationFileRole
    file_id: EntityId
    observation_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    expected_presence_state: PresenceState
    expected_full_sha256: str
    expected_size_bytes: int
    expected_modified_at: datetime
    expected_observed_at: datetime
    format_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, ConsolidationFileRole):
            raise ValueError("role must be a ConsolidationFileRole")
        for name in ("file_id", "observation_id", "scan_root_id", "source_scan_run_id"):
            _id(getattr(self, name), name)
        if self.expected_presence_state is not PresenceState.PRESENT:
            raise ValueError("expected_presence_state must be PRESENT")
        object.__setattr__(
            self,
            "expected_full_sha256",
            _require_sha256(self.expected_full_sha256, "expected_full_sha256"),
        )
        if isinstance(self.expected_size_bytes, bool) or self.expected_size_bytes < 0:
            raise ValueError("expected_size_bytes must be nonnegative")
        require_aware_datetime(self.expected_modified_at, "expected_modified_at")
        require_aware_datetime(self.expected_observed_at, "expected_observed_at")
        object.__setattr__(self, "format_label", _text(self.format_label, "format_label").upper())
        if self.format_label not in CONSOLIDATION_FORMATS:
            raise ValueError("format_label is not supported")


@dataclass(frozen=True, slots=True)
class ConsolidationQualityEvidenceSnapshot:
    id: EntityId
    role: ConsolidationFileRole
    collection_run_id: EntityId
    collection_item_id: EntityId
    observation_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    collection_profile: str
    analysis_profile: str
    quality_profile: str
    format_label: str
    assessment_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.role, ConsolidationFileRole):
            raise ValueError("role must be a ConsolidationFileRole")
        for name in (
            "id",
            "collection_run_id",
            "collection_item_id",
            "observation_id",
            "scan_root_id",
            "source_scan_run_id",
        ):
            _id(getattr(self, name), name)
        if (
            self.collection_profile != CONSOLIDATION_COLLECTION_PROFILE
            or self.analysis_profile != CONSOLIDATION_ANALYSIS_PROFILE
            or self.quality_profile != EBOOK_QUALITY_PROFILE
        ):
            raise ValueError("quality evidence profiles are not compatible")
        object.__setattr__(self, "format_label", _text(self.format_label, "format_label").upper())
        if self.format_label not in CONSOLIDATION_FORMATS:
            raise ValueError("format_label is not supported")
        object.__setattr__(
            self,
            "assessment_fingerprint",
            _require_sha256(self.assessment_fingerprint, "assessment_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class KeepPreferenceOutcome:
    preference_id: EntityId
    profile: str
    profile_version: str
    left_file_id: EntityId
    left_observation_id: EntityId
    right_file_id: EntityId
    right_observation_id: EntityId
    status: KeepPreferenceStatus
    keeper_file_id: EntityId | None
    candidate_file_id: EntityId | None
    reason_codes: tuple[KeepPreferenceReasonCode, ...]
    configuration_fingerprint: str = field(repr=False)
    evidence_fingerprint: str = field(repr=False)
    quality_evidence: tuple[ConsolidationQualityEvidenceSnapshot, ...]
    candidate_set_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        _id(self.preference_id, "preference_id")
        if (
            self.profile != CONSOLIDATION_KEEP_PREFERENCE_PROFILE
            or self.profile_version != CONSOLIDATION_KEEP_PREFERENCE_VERSION
        ):
            raise ValueError("invalid keep-preference profile")
        for name in (
            "left_file_id",
            "left_observation_id",
            "right_file_id",
            "right_observation_id",
        ):
            _id(getattr(self, name), name)
        if self.left_file_id == self.right_file_id or not _ordered_ids(
            self.left_file_id, self.right_file_id
        ):
            raise ValueError("keep-preference endpoints must be distinct and canonically ordered")
        if not isinstance(self.status, KeepPreferenceStatus):
            raise ValueError("status must be a KeepPreferenceStatus")
        _unique(self.reason_codes, "reason_codes")
        if len(self.reason_codes) > MAX_CONSOLIDATION_REASONS or any(
            not isinstance(code, KeepPreferenceReasonCode) for code in self.reason_codes
        ):
            raise ValueError("reason_codes are invalid or exceed the configured limit")
        if len(self.quality_evidence) != 2 or {ref.role for ref in self.quality_evidence} != set(
            ConsolidationFileRole
        ):
            raise ValueError("keep preference requires one quality snapshot per file role")
        if self.status is KeepPreferenceStatus.PREFERRED:
            if (
                self.keeper_file_id is None
                or self.candidate_file_id is None
                or self.keeper_file_id == self.candidate_file_id
            ):
                raise ValueError("PREFERRED requires exactly one keeper and candidate direction")
            if {self.keeper_file_id, self.candidate_file_id} != {
                self.left_file_id,
                self.right_file_id,
            }:
                raise ValueError("keeper and candidate must be the preference endpoints")
        elif self.keeper_file_id is not None or self.candidate_file_id is not None:
            raise ValueError("TIED and BLOCKED cannot contain a direction")
        for name in (
            "configuration_fingerprint",
            "evidence_fingerprint",
            "candidate_set_fingerprint",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ConsolidationFutureOperationIntent:
    ordinal: int
    code: ConsolidationIntentCode
    file_role: ConsolidationFileRole

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a nonnegative integer")
        if not isinstance(self.code, ConsolidationIntentCode) or not isinstance(
            self.file_role, ConsolidationFileRole
        ):
            raise ValueError("intent contains invalid literals")
        if (
            self.code is ConsolidationIntentCode.KEEP
            and self.file_role is not ConsolidationFileRole.KEEPER
        ):
            raise ValueError("KEEP intent must address the KEEPER")
        if (
            self.code is not ConsolidationIntentCode.KEEP
            and self.file_role is not ConsolidationFileRole.CANDIDATE
        ):
            raise ValueError("non-KEEP intents must address the CANDIDATE")


@dataclass(frozen=True, slots=True)
class ConsolidationCandidateSnapshot:
    candidate_id: EntityId
    profile: str
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    relation_candidate_id: EntityId
    relation_fingerprint: str = field(repr=False)
    keep_preference_id: EntityId
    keep_preference_fingerprint: str = field(repr=False)
    keeper_file_id: EntityId
    candidate_file_id: EntityId
    dependency_fingerprint: str = field(repr=False)
    precondition_fingerprint: str = field(repr=False)
    evidence_fingerprint: str = field(repr=False)
    candidate_set_fingerprint: str = field(repr=False)
    intents: tuple[ConsolidationFutureOperationIntent, ...] = ()
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "scan_root_id",
            "source_scan_run_id",
            "relation_candidate_id",
            "keep_preference_id",
            "keeper_file_id",
            "candidate_file_id",
        ):
            _id(getattr(self, name), name)
        if self.profile != CONSOLIDATION_CANDIDATE_PROFILE:
            raise ValueError("invalid consolidation candidate profile")
        if self.keeper_file_id == self.candidate_file_id:
            raise ValueError("candidate snapshot keeper and candidate must differ")
        for name in (
            "relation_fingerprint",
            "keep_preference_fingerprint",
            "dependency_fingerprint",
            "precondition_fingerprint",
            "evidence_fingerprint",
            "candidate_set_fingerprint",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        _tuple_limit(self.intents, MAX_CONSOLIDATION_INTENTS, "intents")
        _unique(self.intents, "intents")
        if self.created_at is not None:
            require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ConsolidationReviewSnapshot:
    review_type: ReviewType
    state: ConsolidationReviewState
    evidence_fingerprint: str = field(repr=False)
    candidate_set_fingerprint: str = field(repr=False)
    candidate_kind: ReviewCandidateKind
    producer_name: str
    decision_compatibility_version: str
    review_item_id: EntityId | None = None
    decision_id: EntityId | None = None
    decision_sequence_no: int | None = None

    def __post_init__(self) -> None:
        expected = {
            ReviewType.KEEP_PREFERENCE: ReviewCandidateKind.KEEP_PREFERENCE,
            ReviewType.CONSOLIDATION_CANDIDATE: ReviewCandidateKind.CONSOLIDATION_CANDIDATE,
        }
        if (
            self.review_type not in expected
            or self.candidate_kind is not expected[self.review_type]
        ):
            raise ValueError("review type and candidate kind are incompatible")
        if not isinstance(self.state, ConsolidationReviewState):
            raise ValueError("state must be a ConsolidationReviewState")
        for name in ("evidence_fingerprint", "candidate_set_fingerprint"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        object.__setattr__(self, "producer_name", _text(self.producer_name, "producer_name"))
        object.__setattr__(
            self,
            "decision_compatibility_version",
            _text(self.decision_compatibility_version, "decision_compatibility_version"),
        )
        if self.state in {ConsolidationReviewState.ACCEPTED, ConsolidationReviewState.REJECTED}:
            if (
                self.review_item_id is None
                or self.decision_id is None
                or self.decision_sequence_no is None
                or self.decision_sequence_no < 1
            ):
                raise ValueError("decided reviews require item, decision and positive sequence")
        elif self.decision_id is not None or self.decision_sequence_no is not None:
            raise ValueError("unresolved reviews cannot carry an effective decision")
        if self.review_item_id is not None:
            _id(self.review_item_id, "review_item_id")
        if self.decision_id is not None:
            _id(self.decision_id, "decision_id")


@dataclass(frozen=True, slots=True)
class ConsolidationFilePreconditionSnapshot:
    file_role: ConsolidationFileRole
    code: ConsolidationPreconditionCode
    expected_file_id: EntityId
    expected_observation_id: EntityId
    expected_scan_root_id: EntityId
    expected_scan_run_id: EntityId
    expected_presence_state: PresenceState
    expected_full_sha256: str
    expected_size_bytes: int
    expected_modified_at: datetime
    expected_observed_at: datetime
    dependency_kind: ConsolidationDependencyKind | None = None
    dependency_state: ConsolidationDependencyState | None = None
    dependency_fingerprint: str | None = field(default=None, repr=False)
    review_item_id: EntityId | None = None
    review_decision_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.file_role, ConsolidationFileRole) or not isinstance(
            self.code, ConsolidationPreconditionCode
        ):
            raise ValueError("precondition contains invalid literals")
        for name in (
            "expected_file_id",
            "expected_observation_id",
            "expected_scan_root_id",
            "expected_scan_run_id",
        ):
            _id(getattr(self, name), name)
        if self.expected_presence_state is not PresenceState.PRESENT:
            raise ValueError("preconditions require PRESENT")
        object.__setattr__(
            self,
            "expected_full_sha256",
            _require_sha256(self.expected_full_sha256, "expected_full_sha256"),
        )
        if isinstance(self.expected_size_bytes, bool) or self.expected_size_bytes < 0:
            raise ValueError("expected_size_bytes must be nonnegative")
        require_aware_datetime(self.expected_modified_at, "expected_modified_at")
        require_aware_datetime(self.expected_observed_at, "expected_observed_at")
        relationship_codes = {
            ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
            ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
            ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
        }
        if self.code in relationship_codes:
            if (
                self.dependency_kind is None
                or self.dependency_state is None
                or self.dependency_fingerprint is None
            ):
                raise ValueError("relationship preconditions require dependency binding")
            object.__setattr__(
                self,
                "dependency_fingerprint",
                _require_sha256(self.dependency_fingerprint, "dependency_fingerprint"),
            )
        elif (
            self.dependency_kind is not None
            or self.dependency_state is not None
            or self.dependency_fingerprint is not None
        ):
            raise ValueError("dependency binding is only valid for relationship preconditions")
        if (
            self.code is ConsolidationPreconditionCode.KEEPER_READABLE
            and self.file_role is not ConsolidationFileRole.KEEPER
        ):
            raise ValueError("KEEPER_READABLE is only valid for the keeper")
        if self.code is ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED and (
            self.review_item_id is None or self.review_decision_id is None
        ):
            raise ValueError("review preconditions require review bindings")
        for name in ("review_item_id", "review_decision_id"):
            value = getattr(self, name)
            if value is not None:
                _id(value, name)


@dataclass(frozen=True, slots=True)
class ConsolidationPlan:
    id: EntityId
    profile: str
    plan_version: int
    serializer_version: str
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    identity: ConsolidationIdentitySnapshot | None
    keeper: ConsolidationFileEndpoint | None
    candidate: ConsolidationFileEndpoint | None
    keep_preference: KeepPreferenceOutcome | None
    consolidation_candidate: ConsolidationCandidateSnapshot | None
    dependencies: tuple[ConsolidationDependency, ...]
    quality_evidence: tuple[ConsolidationQualityEvidenceSnapshot, ...]
    required_reviews: tuple[ConsolidationReviewSnapshot, ...]
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...]
    future_operation_intents: tuple[ConsolidationFutureOperationIntent, ...]
    blockers: tuple[ConsolidationBlocker, ...]
    status: ConsolidationPlanStatus
    execution_state: ConsolidationExecutionState
    content_hash: str = field(repr=False)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _id(self.id, "id")
        if (
            self.profile != CONSOLIDATION_PLAN_PROFILE
            or self.plan_version != CONSOLIDATION_PLAN_VERSION
            or self.serializer_version != CONSOLIDATION_PLAN_SERIALIZER_VERSION
        ):
            raise ValueError("invalid consolidation plan profile/version")
        if self.execution_state is not ConsolidationExecutionState.NOT_EXECUTABLE:
            raise ValueError("consolidation plans are always NOT_EXECUTABLE")
        if not isinstance(self.status, ConsolidationPlanStatus):
            raise ValueError("status must be a ConsolidationPlanStatus")
        for name in ("scan_root_id", "source_scan_run_id"):
            _id(getattr(self, name), name)
        if self.identity is not None and (
            self.identity.scan_root_id != self.scan_root_id
            or self.identity.source_scan_run_id != self.source_scan_run_id
        ):
            raise ValueError("identity lineage does not match plan lineage")
        if (self.keeper is None) is not (self.candidate is None):
            raise ValueError("keeper and candidate endpoints must be present together")
        endpoints = tuple(
            endpoint for endpoint in (self.keeper, self.candidate) if endpoint is not None
        )
        if endpoints and (
            self.keeper is None
            or self.candidate is None
            or self.keeper.role is not ConsolidationFileRole.KEEPER
            or self.candidate.role is not ConsolidationFileRole.CANDIDATE
        ):
            raise ValueError("endpoints must carry their fixed roles")
        for endpoint in endpoints:
            if (
                endpoint.scan_root_id != self.scan_root_id
                or endpoint.source_scan_run_id != self.source_scan_run_id
            ):
                raise ValueError("endpoint lineage does not match plan lineage")
        if self.keeper is not None and self.candidate is not None:
            if self.keeper.file_id == self.candidate.file_id:
                raise ValueError("keeper and candidate files must differ")
            if self.keeper.expected_full_sha256 != self.candidate.expected_full_sha256:
                raise ValueError("exact-duplicate endpoints require equal full SHA-256")
            if self.identity is not None and {
                self.keeper.file_id,
                self.candidate.file_id,
            } != {self.identity.left_file_id, self.identity.right_file_id}:
                raise ValueError("keeper and candidate must be the identity endpoints")
        if (
            self.keep_preference is not None
            and self.keeper is not None
            and self.candidate is not None
        ):
            if (
                self.keep_preference.keeper_file_id != self.keeper.file_id
                or self.keep_preference.candidate_file_id != self.candidate.file_id
            ):
                raise ValueError("keep preference direction does not match plan endpoints")
            if (
                self.keep_preference.left_observation_id
                not in {self.keeper.observation_id, self.candidate.observation_id}
                or self.keep_preference.right_observation_id
                not in {self.keeper.observation_id, self.candidate.observation_id}
            ):
                raise ValueError("keep preference observations do not match plan endpoints")
        plan_candidate = self.consolidation_candidate
        if plan_candidate is not None:
            if (
                plan_candidate.scan_root_id != self.scan_root_id
                or plan_candidate.source_scan_run_id != self.source_scan_run_id
            ):
                raise ValueError("consolidation candidate lineage does not match plan")
            if self.identity is not None and (
                plan_candidate.relation_candidate_id != self.identity.relation_candidate_id
                or plan_candidate.relation_fingerprint != self.identity.evidence_fingerprint
            ):
                raise ValueError("consolidation candidate identity does not match plan")
            if self.keep_preference is not None and (
                plan_candidate.keep_preference_id != self.keep_preference.preference_id
                or plan_candidate.keep_preference_fingerprint
                != self.keep_preference.evidence_fingerprint
            ):
                raise ValueError("consolidation candidate preference does not match plan")
            if self.keeper is not None and self.candidate is not None and (
                plan_candidate.keeper_file_id != self.keeper.file_id
                or plan_candidate.candidate_file_id != self.candidate.file_id
            ):
                raise ValueError("consolidation candidate endpoints do not match plan")
            if plan_candidate.intents != self.future_operation_intents:
                raise ValueError("consolidation candidate intents do not match plan")
        _tuple_limit(self.dependencies, MAX_CONSOLIDATION_DEPENDENCIES, "dependencies")
        if len({(dep.file_role, dep.kind) for dep in self.dependencies}) != len(
            self.dependencies
        ):
            raise ValueError("dependency role/kind pairs must be unique")
        if len({item.role for item in self.quality_evidence}) != len(self.quality_evidence):
            raise ValueError("quality evidence roles must be unique")
        for item in self.quality_evidence:
            quality_endpoint = (
                self.keeper if item.role is ConsolidationFileRole.KEEPER else self.candidate
            )
            if quality_endpoint is not None and (
                item.observation_id != quality_endpoint.observation_id
                or item.scan_root_id != self.scan_root_id
                or item.source_scan_run_id != self.source_scan_run_id
                or item.format_label != quality_endpoint.format_label
            ):
                raise ValueError("quality evidence does not match its plan endpoint")
        if self.keep_preference is not None:
            preference_quality = {
                item.role: (item.id, item.assessment_fingerprint)
                for item in self.keep_preference.quality_evidence
            }
            plan_quality = {
                item.role: (item.id, item.assessment_fingerprint)
                for item in self.quality_evidence
            }
            if plan_quality != preference_quality:
                raise ValueError("plan quality evidence does not match keep preference")
        if len({review.review_type for review in self.required_reviews}) != len(
            self.required_reviews
        ):
            raise ValueError("review types must be unique")
        _tuple_limit(self.preconditions, MAX_CONSOLIDATION_PRECONDITIONS, "preconditions")
        _tuple_limit(
            self.future_operation_intents, MAX_CONSOLIDATION_INTENTS, "future_operation_intents"
        )
        _tuple_limit(self.blockers, MAX_CONSOLIDATION_BLOCKERS, "blockers")
        _unique(self.dependencies, "dependencies")
        _unique(self.quality_evidence, "quality_evidence")
        _unique(self.required_reviews, "required_reviews")
        _unique(self.preconditions, "preconditions")
        _unique(self.future_operation_intents, "future_operation_intents")
        _unique(self.blockers, "blockers")
        object.__setattr__(self, "content_hash", _require_sha256(self.content_hash, "content_hash"))
        if self.created_at is not None:
            require_aware_datetime(self.created_at, "created_at")


ConsolidationKeepPreference = KeepPreferenceOutcome
ConsolidationCandidate = ConsolidationCandidateSnapshot


__all__ = [
    name
    for name in globals()
    if name.startswith("Consolidation")
    or name.startswith("KeepPreference")
    or name.startswith("SizeTie")
    or name.startswith("MAX_CONSOLIDATION")
    or name.startswith("CONSOLIDATION_")
    or name == "validate_consolidation_status"
]
