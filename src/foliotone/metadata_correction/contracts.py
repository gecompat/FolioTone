"""Immutable, path-free contracts for non-executable metadata correction plans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from foliotone.core import EntityId, PresenceState, ScanRunStatus, ValueState
from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.resolution_models import _require_sha256

METADATA_CORRECTION_CANDIDATE_PROFILE: Final = "metadata-correction-candidate/v1"
METADATA_CORRECTION_PLAN_PROFILE: Final = "metadata-correction-plan/v1"
METADATA_CORRECTION_WRITE_INTENT_PROFILE: Final = "ebook-metadata-write-intent/v1"
METADATA_CORRECTION_VERIFICATION_PROFILE: Final = "metadata-correction-verification/v1"
METADATA_CORRECTION_SERIALIZER_VERSION: Final = "canonical-json/v1"
METADATA_CORRECTION_REVIEW_TYPE: Final = "METADATA_CORRECTION"
METADATA_CORRECTION_REVIEW_CANDIDATE_KIND: Final = "METADATA_CORRECTION_CANDIDATE"
METADATA_CORRECTION_PRODUCER_NAME: Final = "ebook-metadata-correction"
METADATA_CORRECTION_PRODUCER_VERSION: Final = "1"
METADATA_CORRECTION_DECISION_COMPATIBILITY: Final = (
    "ebook-metadata-correction-decision/v1"
)
METADATA_CORRECTION_CANDIDATE_NAMESPACE: Final = UUID(
    "d0133c2d-ac8b-51d6-9eb3-5e6fe0d24c2c"
)
METADATA_CORRECTION_PLAN_NAMESPACE: Final = UUID(
    "eff58167-8718-531c-8f11-dc3a5229e860"
)
METADATA_CORRECTION_FORMATS: Final = ("AZW", "AZW3", "EPUB", "MOBI", "PDF")

MAX_METADATA_CORRECTION_FIELDS: Final = 64
MAX_METADATA_VALUES_PER_FIELD: Final = 256
MAX_METADATA_VALUES_PER_CANDIDATE: Final = 4096
MAX_METADATA_VALUE_CHARS: Final = 65_536
MAX_METADATA_EVIDENCE_REFS: Final = 512
MAX_METADATA_FIELD_EVIDENCE_REFS: Final = 64
MAX_METADATA_BLOCKER_EVIDENCE_REFS: Final = 64

_REFERENCE_KIND = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_TECHNICAL_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SIMPLE_FIELD_PATHS: Final = frozenset(
    {
        "description",
        "language",
        "publication_date",
        "publisher",
        "rating",
        "rights",
        "subject",
        "subtitle",
        "title",
        "title_sort",
        "type",
    }
)
_INDEX = r"[1-9][0-9]{0,3}"
_CONTRIBUTOR_FIELD_PATH = re.compile(
    rf"contributor\.{_INDEX}\."
    rf"(?:name|source_element|source_role|source_role_scheme|role|sort_name)"
    rf"(?:\.{_INDEX})?\Z"
)
_IDENTIFIER_FIELD_PATH = re.compile(
    rf"identifier\.{_INDEX}\."
    rf"(?:value|source_namespace|source_namespace_scheme|namespace)"
    rf"(?:\.{_INDEX})?\Z"
)
_SERIES_FIELD_PATH = re.compile(
    rf"series\.{_INDEX}\.(?:name|position)(?:\.{_INDEX})?\Z"
)


class MetadataTargetCarrier(StrEnum):
    FOLIOTONE_PROJECTION = "FOLIOTONE_PROJECTION"
    SIDECAR = "SIDECAR"
    SOURCE_METADATA = "SOURCE_METADATA"
    CALIBRE_LIBRARY = "CALIBRE_LIBRARY"
    EXTERNAL_TOOL = "EXTERNAL_TOOL"


class MetadataTargetReferenceKind(StrEnum):
    DOMAIN_ENTITY = "DOMAIN_ENTITY"
    SIDECAR_SLOT = "SIDECAR_SLOT"
    SOURCE_FILE = "SOURCE_FILE"
    CALIBRE_RECORD = "CALIBRE_RECORD"
    EXTERNAL_RECORD = "EXTERNAL_RECORD"


METADATA_TARGET_REFERENCE_KIND: Final = {
    MetadataTargetCarrier.FOLIOTONE_PROJECTION: MetadataTargetReferenceKind.DOMAIN_ENTITY,
    MetadataTargetCarrier.SIDECAR: MetadataTargetReferenceKind.SIDECAR_SLOT,
    MetadataTargetCarrier.SOURCE_METADATA: MetadataTargetReferenceKind.SOURCE_FILE,
    MetadataTargetCarrier.CALIBRE_LIBRARY: MetadataTargetReferenceKind.CALIBRE_RECORD,
    MetadataTargetCarrier.EXTERNAL_TOOL: MetadataTargetReferenceKind.EXTERNAL_RECORD,
}


class MetadataCorrectionOperation(StrEnum):
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"


class MetadataDependencyKind(StrEnum):
    CALIBRE = "CALIBRE"
    SIDECAR = "SIDECAR"
    ARCHIVE = "ARCHIVE"


class MetadataDependencyState(StrEnum):
    KNOWN_NONE = "KNOWN_NONE"
    KNOWN_PRESENT = "KNOWN_PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MetadataCorrectionReviewState(StrEnum):
    MISSING = "MISSING"
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class MetadataCorrectionPlanStatus(StrEnum):
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_NON_EXECUTABLE = "APPROVED_NON_EXECUTABLE"


class MetadataCorrectionExecutionState(StrEnum):
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


class MetadataCorrectionPreconditionCode(StrEnum):
    FILE_RECORD_UNCHANGED = "FILE_RECORD_UNCHANGED"
    FILE_OBSERVATION_CURRENT = "FILE_OBSERVATION_CURRENT"
    PRESENCE_IS_PRESENT = "PRESENCE_IS_PRESENT"
    FULL_SHA256_MATCHES = "FULL_SHA256_MATCHES"
    SIZE_MATCHES = "SIZE_MATCHES"
    MODIFIED_AT_MATCHES = "MODIFIED_AT_MATCHES"
    METADATA_EVIDENCE_UNCHANGED = "METADATA_EVIDENCE_UNCHANGED"
    TARGET_CARRIER_UNCHANGED = "TARGET_CARRIER_UNCHANGED"
    DEPENDENCIES_UNCHANGED = "DEPENDENCIES_UNCHANGED"
    REVIEW_APPROVAL_UNCHANGED = "REVIEW_APPROVAL_UNCHANGED"
    WRITER_REQUIREMENT_UNCHANGED = "WRITER_REQUIREMENT_UNCHANGED"


class MetadataCorrectionBlockerCode(StrEnum):
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    SOURCE_EVIDENCE_INCOMPLETE = "SOURCE_EVIDENCE_INCOMPLETE"
    FIELD_SELECTION_INVALID = "FIELD_SELECTION_INVALID"
    TARGET_CARRIER_INVALID = "TARGET_CARRIER_INVALID"
    WRITER_REQUIREMENT_INVALID = "WRITER_REQUIREMENT_INVALID"
    DEPENDENCY_EVIDENCE_INCOMPLETE = "DEPENDENCY_EVIDENCE_INCOMPLETE"
    PRECONDITION_INCOMPLETE = "PRECONDITION_INCOMPLETE"
    VERIFICATION_CONTRACT_INCOMPLETE = "VERIFICATION_CONTRACT_INCOMPLETE"
    REVIEW_MISSING = "REVIEW_MISSING"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    REVIEW_STALE = "REVIEW_STALE"


def _entity_id(value: EntityId, field_name: str) -> EntityId:
    if not isinstance(value, EntityId):
        raise ValueError(f"{field_name} must be an EntityId")
    return value


def _nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")
    return value


def _bounded_reference_kind(value: str, field_name: str) -> str:
    normalized = require_non_empty(value, field_name)
    if _REFERENCE_KIND.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded uppercase reference kind")
    return normalized


def _bounded_technical_text(value: str, field_name: str) -> str:
    normalized = require_non_empty(value, field_name)
    if _TECHNICAL_TEXT.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded technical identifier")
    return normalized


def validate_metadata_field_path(value: str) -> str:
    """Validate one field from the bounded provider-neutral e-book field grammar."""
    normalized = require_non_empty(value, "field_path")
    if (
        normalized not in _SIMPLE_FIELD_PATHS
        and _CONTRIBUTOR_FIELD_PATH.fullmatch(normalized) is None
        and _IDENTIFIER_FIELD_PATH.fullmatch(normalized) is None
        and _SERIES_FIELD_PATH.fullmatch(normalized) is None
    ):
        raise ValueError("field_path is outside the bounded e-book metadata grammar")
    return normalized


def _private_value(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must be a non-empty string")
    if len(value) > MAX_METADATA_VALUE_CHARS:
        raise ValueError("value exceeds the bounded metadata value size")
    return value


def _evidence_key(value: MetadataEvidenceReference) -> tuple[str, str, str]:
    return (value.kind, str(value.ref_id), value.material_fingerprint)


def _require_sorted_unique_evidence(
    values: tuple[MetadataEvidenceReference, ...],
    *,
    field_name: str,
    limit: int,
) -> None:
    if len(values) > limit:
        raise ValueError(f"{field_name} exceeds the configured limit of {limit}")
    keys = tuple(_evidence_key(value) for value in values)
    identities = tuple((value.kind, str(value.ref_id)) for value in values)
    if keys != tuple(sorted(keys)) or len(identities) != len(set(identities)):
        raise ValueError(f"{field_name} must be sorted and semantically unique")


@dataclass(frozen=True, slots=True)
class MetadataEvidenceReference:
    kind: str
    ref_id: EntityId
    material_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _bounded_reference_kind(self.kind, "kind"))
        _entity_id(self.ref_id, "ref_id")
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataValueSnapshot:
    ordinal: int
    state: ValueState
    source_ref: MetadataEvidenceReference
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _nonnegative_int(self.ordinal, "ordinal")
        if not isinstance(self.state, ValueState):
            raise ValueError("state must be a ValueState")
        if not isinstance(self.source_ref, MetadataEvidenceReference):
            raise ValueError("source_ref must be a MetadataEvidenceReference")
        object.__setattr__(self, "value", _private_value(self.value))


@dataclass(frozen=True, slots=True)
class MetadataFieldCorrection:
    field_path: str
    operation: MetadataCorrectionOperation
    observed_values: tuple[MetadataValueSnapshot, ...]
    selected_values: tuple[MetadataValueSnapshot, ...]
    evidence_refs: tuple[MetadataEvidenceReference, ...]
    selection_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_path", validate_metadata_field_path(self.field_path))
        if not isinstance(self.operation, MetadataCorrectionOperation):
            raise ValueError("operation must be a MetadataCorrectionOperation")
        for field_name in ("observed_values", "selected_values"):
            values = getattr(self, field_name)
            if len(values) > MAX_METADATA_VALUES_PER_FIELD:
                raise ValueError(
                    f"{field_name} exceeds the configured limit of "
                    f"{MAX_METADATA_VALUES_PER_FIELD}"
                )
            if tuple(value.ordinal for value in values) != tuple(range(len(values))):
                raise ValueError(f"{field_name} ordinals must be contiguous and ordered")
        if self.operation is MetadataCorrectionOperation.REPLACE and not self.selected_values:
            raise ValueError("REPLACE requires at least one selected value")
        if self.operation is MetadataCorrectionOperation.REMOVE and self.selected_values:
            raise ValueError("REMOVE requires an empty selected value set")
        allowed_selected_states = {ValueState.CANONICAL, ValueState.USER_CONFIRMED}
        if any(value.state not in allowed_selected_states for value in self.selected_values):
            raise ValueError("selected values must be CANONICAL or USER_CONFIRMED")
        _require_sorted_unique_evidence(
            self.evidence_refs,
            field_name="evidence_refs",
            limit=MAX_METADATA_FIELD_EVIDENCE_REFS,
        )
        object.__setattr__(
            self,
            "selection_fingerprint",
            _require_sha256(self.selection_fingerprint, "selection_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataTargetSnapshot:
    carrier: MetadataTargetCarrier
    reference_kind: MetadataTargetReferenceKind
    reference_id: EntityId
    carrier_state_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.carrier, MetadataTargetCarrier):
            raise ValueError("carrier must be a MetadataTargetCarrier")
        if self.reference_kind is not METADATA_TARGET_REFERENCE_KIND[self.carrier]:
            raise ValueError("target reference kind does not match its carrier")
        _entity_id(self.reference_id, "reference_id")
        object.__setattr__(
            self,
            "carrier_state_fingerprint",
            _require_sha256(self.carrier_state_fingerprint, "carrier_state_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataDependencySnapshot:
    kind: MetadataDependencyKind
    state: MetadataDependencyState
    snapshot_kind: str
    snapshot_id: EntityId
    material_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MetadataDependencyKind):
            raise ValueError("kind must be a MetadataDependencyKind")
        if not isinstance(self.state, MetadataDependencyState):
            raise ValueError("state must be a MetadataDependencyState")
        object.__setattr__(
            self,
            "snapshot_kind",
            _bounded_technical_text(self.snapshot_kind, "snapshot_kind"),
        )
        _entity_id(self.snapshot_id, "snapshot_id")
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataWriterRequirement:
    format_label: str
    target_carrier: MetadataTargetCarrier
    material_fingerprint: str = field(repr=False)
    profile: str = METADATA_CORRECTION_WRITE_INTENT_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_CORRECTION_WRITE_INTENT_PROFILE:
            raise ValueError("writer requirement profile is invalid")
        if self.format_label not in METADATA_CORRECTION_FORMATS:
            raise ValueError("writer requirement format is outside the e-book allowlist")
        if not isinstance(self.target_carrier, MetadataTargetCarrier):
            raise ValueError("target_carrier must be a MetadataTargetCarrier")
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionCandidate:
    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    source_scan_run_status: ScanRunStatus
    file_id: EntityId
    observation_id: EntityId
    format_label: str
    expected_presence_state: PresenceState
    expected_full_sha256: str = field(repr=False)
    expected_size_bytes: int
    expected_modified_at: datetime
    expected_observed_at: datetime
    metadata_evidence_fingerprint: str = field(repr=False)
    target: MetadataTargetSnapshot
    field_corrections: tuple[MetadataFieldCorrection, ...]
    dependencies: tuple[MetadataDependencySnapshot, ...]
    writer_requirement: MetadataWriterRequirement
    evidence_refs: tuple[MetadataEvidenceReference, ...]
    evidence_fingerprint: str = field(repr=False)
    content_hash: str = field(repr=False)
    created_at: datetime
    profile: str = METADATA_CORRECTION_CANDIDATE_PROFILE
    serializer_version: str = METADATA_CORRECTION_SERIALIZER_VERSION

    def __post_init__(self) -> None:
        if self.profile != METADATA_CORRECTION_CANDIDATE_PROFILE:
            raise ValueError("metadata correction candidate profile is invalid")
        if self.serializer_version != METADATA_CORRECTION_SERIALIZER_VERSION:
            raise ValueError("metadata correction candidate serializer is invalid")
        for field_name in (
            "id",
            "scan_root_id",
            "source_scan_run_id",
            "file_id",
            "observation_id",
        ):
            _entity_id(getattr(self, field_name), field_name)
        if self.source_scan_run_status is not ScanRunStatus.COMPLETED:
            raise ValueError("metadata correction candidates require a completed ScanRun")
        if self.format_label not in METADATA_CORRECTION_FORMATS:
            raise ValueError("format_label is outside the e-book allowlist")
        if self.expected_presence_state is not PresenceState.PRESENT:
            raise ValueError("metadata correction candidates require PRESENT source evidence")
        object.__setattr__(
            self,
            "expected_full_sha256",
            _require_sha256(self.expected_full_sha256, "expected_full_sha256"),
        )
        _nonnegative_int(self.expected_size_bytes, "expected_size_bytes")
        require_aware_datetime(self.expected_modified_at, "expected_modified_at")
        require_aware_datetime(self.expected_observed_at, "expected_observed_at")
        require_aware_datetime(self.created_at, "created_at")
        object.__setattr__(
            self,
            "metadata_evidence_fingerprint",
            _require_sha256(
                self.metadata_evidence_fingerprint,
                "metadata_evidence_fingerprint",
            ),
        )
        if not isinstance(self.target, MetadataTargetSnapshot):
            raise ValueError("target must be a MetadataTargetSnapshot")
        if (
            self.target.carrier is MetadataTargetCarrier.SOURCE_METADATA
            and self.target.reference_id != self.file_id
        ):
            raise ValueError("SOURCE_METADATA target must bind the source file")
        if not 1 <= len(self.field_corrections) <= MAX_METADATA_CORRECTION_FIELDS:
            raise ValueError("field_corrections must contain between one and 64 entries")
        field_paths = tuple(value.field_path for value in self.field_corrections)
        if field_paths != tuple(sorted(set(field_paths))):
            raise ValueError("field_corrections must be sorted with unique field paths")
        value_count = sum(
            len(value.observed_values) + len(value.selected_values)
            for value in self.field_corrections
        )
        if value_count > MAX_METADATA_VALUES_PER_CANDIDATE:
            raise ValueError("candidate metadata values exceed the bounded total")
        dependency_kinds = tuple(value.kind for value in self.dependencies)
        if dependency_kinds != tuple(MetadataDependencyKind):
            raise ValueError("dependencies must contain all axes in canonical order")
        if not isinstance(self.writer_requirement, MetadataWriterRequirement):
            raise ValueError("writer_requirement must be a MetadataWriterRequirement")
        if (
            self.writer_requirement.format_label != self.format_label
            or self.writer_requirement.target_carrier is not self.target.carrier
        ):
            raise ValueError("writer requirement does not match source format and target")
        _require_sorted_unique_evidence(
            self.evidence_refs,
            field_name="evidence_refs",
            limit=MAX_METADATA_EVIDENCE_REFS,
        )
        if not self.evidence_refs:
            raise ValueError("candidate requires at least one evidence reference")
        for field_name in ("evidence_fingerprint", "content_hash"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionReviewSnapshot:
    candidate_id: EntityId
    state: MetadataCorrectionReviewState
    evidence_fingerprint: str = field(repr=False)
    candidate_set_fingerprint: str = field(repr=False)
    producer_name: str = METADATA_CORRECTION_PRODUCER_NAME
    producer_version: str = METADATA_CORRECTION_PRODUCER_VERSION
    decision_compatibility_version: str = METADATA_CORRECTION_DECISION_COMPATIBILITY
    review_type: str = METADATA_CORRECTION_REVIEW_TYPE
    candidate_kind: str = METADATA_CORRECTION_REVIEW_CANDIDATE_KIND
    review_item_id: EntityId | None = None
    decision_id: EntityId | None = None
    decision_sequence_no: int | None = None

    def __post_init__(self) -> None:
        _entity_id(self.candidate_id, "candidate_id")
        if not isinstance(self.state, MetadataCorrectionReviewState):
            raise ValueError("state must be a MetadataCorrectionReviewState")
        if (
            self.review_type != METADATA_CORRECTION_REVIEW_TYPE
            or self.candidate_kind != METADATA_CORRECTION_REVIEW_CANDIDATE_KIND
        ):
            raise ValueError("review type and candidate kind are incompatible")
        for field_name, expected in (
            ("producer_name", METADATA_CORRECTION_PRODUCER_NAME),
            ("producer_version", METADATA_CORRECTION_PRODUCER_VERSION),
            (
                "decision_compatibility_version",
                METADATA_CORRECTION_DECISION_COMPATIBILITY,
            ),
        ):
            value = require_non_empty(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)
            if value != expected:
                raise ValueError(f"{field_name} is incompatible with metadata correction v1")
        for field_name in ("evidence_fingerprint", "candidate_set_fingerprint"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        if self.state is MetadataCorrectionReviewState.MISSING:
            if any(
                value is not None
                for value in (
                    self.review_item_id,
                    self.decision_id,
                    self.decision_sequence_no,
                )
            ):
                raise ValueError("MISSING review cannot bind persisted review records")
        elif self.review_item_id is None:
            raise ValueError("non-missing review requires a review item")
        decided = {
            MetadataCorrectionReviewState.ACCEPTED,
            MetadataCorrectionReviewState.REJECTED,
        }
        if self.state in decided:
            if self.decision_id is None or self.decision_sequence_no is None:
                raise ValueError("decided review requires decision ID and sequence")
            if (
                isinstance(self.decision_sequence_no, bool)
                or not isinstance(self.decision_sequence_no, int)
                or self.decision_sequence_no < 1
            ):
                raise ValueError("decision_sequence_no must be a positive integer")
        elif self.decision_id is not None or self.decision_sequence_no is not None:
            raise ValueError("unresolved review cannot carry an effective decision")
        for field_name in ("review_item_id", "decision_id"):
            value = getattr(self, field_name)
            if value is not None:
                _entity_id(value, field_name)


@dataclass(frozen=True, slots=True)
class MetadataCorrectionPrecondition:
    code: MetadataCorrectionPreconditionCode
    expected_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, MetadataCorrectionPreconditionCode):
            raise ValueError("code must be a MetadataCorrectionPreconditionCode")
        object.__setattr__(
            self,
            "expected_fingerprint",
            _require_sha256(self.expected_fingerprint, "expected_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionVerification:
    analysis_profile: str
    format_label: str
    target_carrier: MetadataTargetCarrier
    expected_selected_fields_fingerprint: str = field(repr=False)
    preserved_fields_fingerprint: str = field(repr=False)
    changed_field_paths: tuple[str, ...]
    format_validation_required: bool
    readability_validation_required: bool
    dependency_reconciliation: tuple[MetadataDependencyKind, ...]
    profile: str = METADATA_CORRECTION_VERIFICATION_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_CORRECTION_VERIFICATION_PROFILE:
            raise ValueError("verification profile is invalid")
        object.__setattr__(
            self,
            "analysis_profile",
            _bounded_technical_text(self.analysis_profile, "analysis_profile"),
        )
        if self.format_label not in METADATA_CORRECTION_FORMATS:
            raise ValueError("verification format is outside the e-book allowlist")
        if not isinstance(self.target_carrier, MetadataTargetCarrier):
            raise ValueError("target_carrier must be a MetadataTargetCarrier")
        for field_name in (
            "expected_selected_fields_fingerprint",
            "preserved_fields_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        paths = tuple(validate_metadata_field_path(value) for value in self.changed_field_paths)
        if not paths or paths != tuple(sorted(set(paths))):
            raise ValueError("changed_field_paths must be non-empty, sorted and unique")
        object.__setattr__(self, "changed_field_paths", paths)
        if self.format_validation_required is not True:
            raise ValueError("format validation is mandatory")
        if self.readability_validation_required is not True:
            raise ValueError("readability validation is mandatory")
        dependencies = self.dependency_reconciliation
        if dependencies != tuple(
            kind for kind in MetadataDependencyKind if kind in set(dependencies)
        ):
            raise ValueError("dependency_reconciliation must be unique and canonically ordered")


@dataclass(frozen=True, slots=True)
class MetadataCorrectionBlocker:
    code: MetadataCorrectionBlockerCode
    evidence_refs: tuple[MetadataEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, MetadataCorrectionBlockerCode):
            raise ValueError("code must be a MetadataCorrectionBlockerCode")
        _require_sorted_unique_evidence(
            self.evidence_refs,
            field_name="evidence_refs",
            limit=MAX_METADATA_BLOCKER_EVIDENCE_REFS,
        )


@dataclass(frozen=True, slots=True)
class MetadataCorrectionPlan:
    id: EntityId
    candidate: MetadataCorrectionCandidate
    review: MetadataCorrectionReviewSnapshot | None
    preconditions: tuple[MetadataCorrectionPrecondition, ...]
    verification: MetadataCorrectionVerification
    blockers: tuple[MetadataCorrectionBlocker, ...]
    status: MetadataCorrectionPlanStatus
    execution_state: MetadataCorrectionExecutionState
    content_hash: str = field(repr=False)
    created_at: datetime
    profile: str = METADATA_CORRECTION_PLAN_PROFILE
    serializer_version: str = METADATA_CORRECTION_SERIALIZER_VERSION

    def __post_init__(self) -> None:
        _entity_id(self.id, "id")
        if self.profile != METADATA_CORRECTION_PLAN_PROFILE:
            raise ValueError("metadata correction plan profile is invalid")
        if self.serializer_version != METADATA_CORRECTION_SERIALIZER_VERSION:
            raise ValueError("metadata correction plan serializer is invalid")
        if not isinstance(self.candidate, MetadataCorrectionCandidate):
            raise ValueError("candidate must be a MetadataCorrectionCandidate")
        if self.review is not None and self.status is not MetadataCorrectionPlanStatus.BLOCKED:
            if (
                self.review.candidate_id != self.candidate.id
                or self.review.evidence_fingerprint != self.candidate.evidence_fingerprint
                or self.review.candidate_set_fingerprint != self.candidate.content_hash
            ):
                raise ValueError("non-blocked review does not bind the plan candidate")
        codes = tuple(value.code for value in self.preconditions)
        canonical_codes = tuple(
            code for code in MetadataCorrectionPreconditionCode if code in set(codes)
        )
        if codes != canonical_codes:
            raise ValueError("preconditions must be unique and canonically ordered")
        if not isinstance(self.verification, MetadataCorrectionVerification):
            raise ValueError("verification must be a MetadataCorrectionVerification")
        candidate_paths = tuple(value.field_path for value in self.candidate.field_corrections)
        if (
            self.verification.changed_field_paths != candidate_paths
            or self.verification.format_label != self.candidate.format_label
            or self.verification.target_carrier is not self.candidate.target.carrier
        ):
            raise ValueError("verification does not match the candidate")
        blocker_codes = tuple(value.code for value in self.blockers)
        if blocker_codes != tuple(sorted(set(blocker_codes), key=lambda value: value.value)):
            raise ValueError("blockers must be unique and sorted")
        if not isinstance(self.status, MetadataCorrectionPlanStatus):
            raise ValueError("status must be a MetadataCorrectionPlanStatus")
        if self.execution_state is not MetadataCorrectionExecutionState.NOT_EXECUTABLE:
            raise ValueError("metadata correction plans are always NOT_EXECUTABLE")
        if self.status is MetadataCorrectionPlanStatus.BLOCKED:
            if not self.blockers:
                raise ValueError("BLOCKED plan requires at least one blocker")
        elif self.blockers:
            raise ValueError("non-blocked plan cannot carry blockers")
        if self.status is MetadataCorrectionPlanStatus.REVIEW_REQUIRED and (
            self.review is None
            or self.review.state
            not in {
                MetadataCorrectionReviewState.PENDING,
                MetadataCorrectionReviewState.DEFERRED,
            }
        ):
            raise ValueError("REVIEW_REQUIRED plan requires a pending or deferred review")
        if (
            self.status is MetadataCorrectionPlanStatus.REVIEW_REQUIRED
            and MetadataCorrectionPreconditionCode.REVIEW_APPROVAL_UNCHANGED in set(codes)
        ):
            raise ValueError("open review cannot have an approval precondition")
        if self.status is MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE and (
            self.review is None
            or self.review.state is not MetadataCorrectionReviewState.ACCEPTED
        ):
            raise ValueError("approved plan requires an accepted review")
        if (
            self.status is MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
            and MetadataCorrectionPreconditionCode.REVIEW_APPROVAL_UNCHANGED not in set(codes)
        ):
            raise ValueError("approved plan requires a review approval precondition")
        object.__setattr__(
            self,
            "content_hash",
            _require_sha256(self.content_hash, "content_hash"),
        )
        require_aware_datetime(self.created_at, "created_at")


__all__ = [
    "MAX_METADATA_BLOCKER_EVIDENCE_REFS",
    "MAX_METADATA_CORRECTION_FIELDS",
    "MAX_METADATA_EVIDENCE_REFS",
    "MAX_METADATA_FIELD_EVIDENCE_REFS",
    "MAX_METADATA_VALUE_CHARS",
    "MAX_METADATA_VALUES_PER_CANDIDATE",
    "MAX_METADATA_VALUES_PER_FIELD",
    "METADATA_CORRECTION_CANDIDATE_NAMESPACE",
    "METADATA_CORRECTION_CANDIDATE_PROFILE",
    "METADATA_CORRECTION_DECISION_COMPATIBILITY",
    "METADATA_CORRECTION_FORMATS",
    "METADATA_CORRECTION_PLAN_NAMESPACE",
    "METADATA_CORRECTION_PLAN_PROFILE",
    "METADATA_CORRECTION_PRODUCER_NAME",
    "METADATA_CORRECTION_PRODUCER_VERSION",
    "METADATA_CORRECTION_REVIEW_CANDIDATE_KIND",
    "METADATA_CORRECTION_REVIEW_TYPE",
    "METADATA_CORRECTION_SERIALIZER_VERSION",
    "METADATA_CORRECTION_VERIFICATION_PROFILE",
    "METADATA_CORRECTION_WRITE_INTENT_PROFILE",
    "METADATA_TARGET_REFERENCE_KIND",
    "MetadataCorrectionBlocker",
    "MetadataCorrectionBlockerCode",
    "MetadataCorrectionCandidate",
    "MetadataCorrectionExecutionState",
    "MetadataCorrectionOperation",
    "MetadataCorrectionPlan",
    "MetadataCorrectionPlanStatus",
    "MetadataCorrectionPrecondition",
    "MetadataCorrectionPreconditionCode",
    "MetadataCorrectionReviewSnapshot",
    "MetadataCorrectionReviewState",
    "MetadataCorrectionVerification",
    "MetadataDependencyKind",
    "MetadataDependencySnapshot",
    "MetadataDependencyState",
    "MetadataEvidenceReference",
    "MetadataFieldCorrection",
    "MetadataTargetCarrier",
    "MetadataTargetReferenceKind",
    "MetadataTargetSnapshot",
    "MetadataValueSnapshot",
    "MetadataWriterRequirement",
    "validate_metadata_field_path",
]
