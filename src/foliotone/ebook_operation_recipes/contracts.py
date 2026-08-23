"""Immutable contracts for bounded, non-executable e-book operation recipes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from foliotone.core import EntityId, PresenceState, ScanRunStatus
from foliotone.core._validation import require_aware_datetime, require_relative_path

EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE: Final = (
    "ebook-operation-recipe-candidate/v1"
)
EBOOK_OPERATION_RECIPE_PLAN_PROFILE: Final = "ebook-operation-recipe-plan/v1"
EBOOK_OPERATION_RECIPE_SERIALIZER: Final = "canonical-json/v1"
EBOOK_OPERATION_RECIPE_REVIEW_TYPE: Final = "EBOOK_OPERATION_RECIPE"
EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND: Final = (
    "EBOOK_OPERATION_RECIPE_CANDIDATE"
)
EBOOK_OPERATION_RECIPE_PRODUCER_NAME: Final = "ebook-operation-recipe"
EBOOK_OPERATION_RECIPE_PRODUCER_VERSION: Final = "1"
EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY: Final = (
    "ebook-operation-recipe-decision/v1"
)
EBOOK_OPERATION_RECIPE_CANDIDATE_NAMESPACE: Final = UUID(
    "b816872e-89df-5a80-8b60-acde1ac8b5ae"
)
EBOOK_OPERATION_RECIPE_PLAN_NAMESPACE: Final = UUID(
    "79f04148-70bb-5c12-82d4-a7fbc2d8cd31"
)

MAX_EBOOK_OPERATION_SOURCES: Final = 32
MAX_EBOOK_OPERATION_EVIDENCE_REFS: Final = 256
MAX_EBOOK_OPERATION_LOCATOR_BYTES: Final = 1024
MAX_EBOOK_OPERATION_LOCATOR_COMPONENT_BYTES: Final = 255

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE_KIND = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_FORMAT_LABEL = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")
_TECHNICAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,127}\Z")


class EbookOperationKind(StrEnum):
    FILE_RENAME = "FILE_RENAME"
    FILE_REORGANIZE = "FILE_REORGANIZE"
    FILE_IMPORT = "FILE_IMPORT"
    FILE_EXPORT = "FILE_EXPORT"
    FORMAT_TRANSFORM = "FORMAT_TRANSFORM"
    ARCHIVE_REWRITE = "ARCHIVE_REWRITE"


class EbookOperationSourceRole(StrEnum):
    PRIMARY = "PRIMARY"
    COMPANION = "COMPANION"


class EbookOperationTargetKind(StrEnum):
    MANAGED_SCAN_ROOT_FILE = "MANAGED_SCAN_ROOT_FILE"
    EXTERNAL_ENDPOINT_FILE = "EXTERNAL_ENDPOINT_FILE"
    GENERATED_FILE = "GENERATED_FILE"
    SOURCE_REPLACEMENT = "SOURCE_REPLACEMENT"


class EbookOperationOutputIdentityKind(StrEnum):
    BYTE_IDENTICAL_TO_PRIMARY = "BYTE_IDENTICAL_TO_PRIMARY"
    EXPECTED_FULL_SHA256 = "EXPECTED_FULL_SHA256"


class EbookOperationCollisionPolicy(StrEnum):
    REQUIRE_TARGET_ABSENT = "REQUIRE_TARGET_ABSENT"
    REQUIRE_EXACT_SOURCE = "REQUIRE_EXACT_SOURCE"


class EbookOperationWorkspaceMode(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PRIVATE_STAGING_REQUIRED = "PRIVATE_STAGING_REQUIRED"


class EbookOperationRecoveryMode(StrEnum):
    REVERSE_RELOCATION = "REVERSE_RELOCATION"
    SOURCE_UNCHANGED = "SOURCE_UNCHANGED"
    ORIGINAL_PRESERVED = "ORIGINAL_PRESERVED"


class EbookOperationProcessorKind(StrEnum):
    FOLIOTONE_NATIVE = "FOLIOTONE_NATIVE"
    TOOL_PROVIDER = "TOOL_PROVIDER"


class EbookOperationDependencyKind(StrEnum):
    CALIBRE = "CALIBRE"
    SIDECAR = "SIDECAR"
    ARCHIVE = "ARCHIVE"
    VOLUME_GROUP = "VOLUME_GROUP"
    EXTERNAL_LIBRARY = "EXTERNAL_LIBRARY"


class EbookOperationDependencyState(StrEnum):
    KNOWN_NONE = "KNOWN_NONE"
    KNOWN_PRESENT = "KNOWN_PRESENT"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EbookOperationVerificationCode(StrEnum):
    INPUT_IDENTITY_RECHECKED = "INPUT_IDENTITY_RECHECKED"
    TARGET_STATE_RECHECKED = "TARGET_STATE_RECHECKED"
    OUTPUT_FULL_SHA256_MATCHES = "OUTPUT_FULL_SHA256_MATCHES"
    OUTPUT_SIZE_MATCHES = "OUTPUT_SIZE_MATCHES"
    SOURCE_PRESENCE_VERIFIED = "SOURCE_PRESENCE_VERIFIED"
    FORMAT_READABLE = "FORMAT_READABLE"
    DEPENDENCIES_RECONCILED = "DEPENDENCIES_RECONCILED"
    RESCAN_COMPLETED = "RESCAN_COMPLETED"
    COLLECTION_STATE_RECONCILED = "COLLECTION_STATE_RECONCILED"


class EbookOperationPreconditionCode(StrEnum):
    SOURCE_LINEAGE_UNCHANGED = "SOURCE_LINEAGE_UNCHANGED"
    SOURCE_BYTES_UNCHANGED = "SOURCE_BYTES_UNCHANGED"
    TARGET_STATE_UNCHANGED = "TARGET_STATE_UNCHANGED"
    DEPENDENCIES_UNCHANGED = "DEPENDENCIES_UNCHANGED"
    PROCESSOR_REQUIREMENT_UNCHANGED = "PROCESSOR_REQUIREMENT_UNCHANGED"
    OUTPUT_EXPECTATION_UNCHANGED = "OUTPUT_EXPECTATION_UNCHANGED"
    RECOVERY_REQUIREMENT_UNCHANGED = "RECOVERY_REQUIREMENT_UNCHANGED"
    VERIFICATION_REQUIREMENT_UNCHANGED = "VERIFICATION_REQUIREMENT_UNCHANGED"
    REVIEW_APPROVAL_UNCHANGED = "REVIEW_APPROVAL_UNCHANGED"


class EbookOperationReviewState(StrEnum):
    MISSING = "MISSING"
    PENDING = "PENDING"
    DEFERRED = "DEFERRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class EbookOperationPlanStatus(StrEnum):
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_NON_EXECUTABLE = "APPROVED_NON_EXECUTABLE"


class EbookOperationExecutionState(StrEnum):
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


class EbookOperationBlockerCode(StrEnum):
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    SOURCE_EVIDENCE_INCOMPLETE = "SOURCE_EVIDENCE_INCOMPLETE"
    TARGET_INVALID = "TARGET_INVALID"
    OUTPUT_IDENTITY_INVALID = "OUTPUT_IDENTITY_INVALID"
    PROCESSOR_REQUIREMENT_INVALID = "PROCESSOR_REQUIREMENT_INVALID"
    DEPENDENCY_EVIDENCE_INCOMPLETE = "DEPENDENCY_EVIDENCE_INCOMPLETE"
    PRECONDITION_INCOMPLETE = "PRECONDITION_INCOMPLETE"
    RECOVERY_CONTRACT_INCOMPLETE = "RECOVERY_CONTRACT_INCOMPLETE"
    VERIFICATION_CONTRACT_INCOMPLETE = "VERIFICATION_CONTRACT_INCOMPLETE"
    REVIEW_MISSING = "REVIEW_MISSING"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    REVIEW_STALE = "REVIEW_STALE"


_TARGET_KIND: Final = {
    EbookOperationKind.FILE_RENAME: EbookOperationTargetKind.MANAGED_SCAN_ROOT_FILE,
    EbookOperationKind.FILE_REORGANIZE: (
        EbookOperationTargetKind.MANAGED_SCAN_ROOT_FILE
    ),
    EbookOperationKind.FILE_IMPORT: EbookOperationTargetKind.MANAGED_SCAN_ROOT_FILE,
    EbookOperationKind.FILE_EXPORT: EbookOperationTargetKind.EXTERNAL_ENDPOINT_FILE,
    EbookOperationKind.FORMAT_TRANSFORM: EbookOperationTargetKind.GENERATED_FILE,
    EbookOperationKind.ARCHIVE_REWRITE: EbookOperationTargetKind.SOURCE_REPLACEMENT,
}
_OUTPUT_IDENTITY: Final = {
    EbookOperationKind.FILE_RENAME: (
        EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
    ),
    EbookOperationKind.FILE_REORGANIZE: (
        EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
    ),
    EbookOperationKind.FILE_IMPORT: (
        EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
    ),
    EbookOperationKind.FILE_EXPORT: (
        EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
    ),
    EbookOperationKind.FORMAT_TRANSFORM: (
        EbookOperationOutputIdentityKind.EXPECTED_FULL_SHA256
    ),
    EbookOperationKind.ARCHIVE_REWRITE: (
        EbookOperationOutputIdentityKind.EXPECTED_FULL_SHA256
    ),
}
_COLLISION_POLICY: Final = {
    kind: (
        EbookOperationCollisionPolicy.REQUIRE_EXACT_SOURCE
        if kind is EbookOperationKind.ARCHIVE_REWRITE
        else EbookOperationCollisionPolicy.REQUIRE_TARGET_ABSENT
    )
    for kind in EbookOperationKind
}
_WORKSPACE_MODE: Final = {
    EbookOperationKind.FILE_RENAME: EbookOperationWorkspaceMode.NOT_REQUIRED,
    EbookOperationKind.FILE_REORGANIZE: EbookOperationWorkspaceMode.NOT_REQUIRED,
    EbookOperationKind.FILE_IMPORT: (
        EbookOperationWorkspaceMode.PRIVATE_STAGING_REQUIRED
    ),
    EbookOperationKind.FILE_EXPORT: (
        EbookOperationWorkspaceMode.PRIVATE_STAGING_REQUIRED
    ),
    EbookOperationKind.FORMAT_TRANSFORM: (
        EbookOperationWorkspaceMode.PRIVATE_STAGING_REQUIRED
    ),
    EbookOperationKind.ARCHIVE_REWRITE: (
        EbookOperationWorkspaceMode.PRIVATE_STAGING_REQUIRED
    ),
}
_RECOVERY_MODE: Final = {
    EbookOperationKind.FILE_RENAME: EbookOperationRecoveryMode.REVERSE_RELOCATION,
    EbookOperationKind.FILE_REORGANIZE: (
        EbookOperationRecoveryMode.REVERSE_RELOCATION
    ),
    EbookOperationKind.FILE_IMPORT: EbookOperationRecoveryMode.SOURCE_UNCHANGED,
    EbookOperationKind.FILE_EXPORT: EbookOperationRecoveryMode.SOURCE_UNCHANGED,
    EbookOperationKind.FORMAT_TRANSFORM: EbookOperationRecoveryMode.SOURCE_UNCHANGED,
    EbookOperationKind.ARCHIVE_REWRITE: EbookOperationRecoveryMode.ORIGINAL_PRESERVED,
}


def operation_target_kind(operation_kind: EbookOperationKind) -> EbookOperationTargetKind:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    return _TARGET_KIND[operation_kind]


def operation_output_identity_kind(
    operation_kind: EbookOperationKind,
) -> EbookOperationOutputIdentityKind:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    return _OUTPUT_IDENTITY[operation_kind]


def operation_collision_policy(
    operation_kind: EbookOperationKind,
) -> EbookOperationCollisionPolicy:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    return _COLLISION_POLICY[operation_kind]


def operation_workspace_mode(
    operation_kind: EbookOperationKind,
) -> EbookOperationWorkspaceMode:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    return _WORKSPACE_MODE[operation_kind]


def operation_recovery_mode(
    operation_kind: EbookOperationKind,
) -> EbookOperationRecoveryMode:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    return _RECOVERY_MODE[operation_kind]


def _entity_id(value: EntityId, field_name: str) -> EntityId:
    if not isinstance(value, EntityId):
        raise ValueError(f"{field_name} must be an EntityId")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")
    return value


def _technical_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a bounded technical identifier")
    normalized = value.strip()
    if _TECHNICAL_ID.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a bounded technical identifier")
    return normalized


def _format_label(value: str) -> str:
    if not isinstance(value, str) or _FORMAT_LABEL.fullmatch(value) is None:
        raise ValueError("format_label must be a bounded uppercase format")
    return value


def _relative_locator(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("relative_locator must be a string")
    raw = value.replace("\\", "/").strip()
    components = raw.split("/")
    if (
        "\x00" in raw
        or raw.startswith("/")
        or re.match(r"[A-Za-z]:", raw) is not None
        or raw.endswith("/")
        or any(component in {"", ".", ".."} for component in components)
        or len(raw.encode("utf-8")) > MAX_EBOOK_OPERATION_LOCATOR_BYTES
        or any(
            len(component.encode("utf-8"))
            > MAX_EBOOK_OPERATION_LOCATOR_COMPONENT_BYTES
            for component in components
        )
    ):
        raise ValueError("relative_locator is outside the bounded private grammar")
    return require_relative_path(raw)


def _parent(value: str) -> str:
    parent, separator, _name = value.rpartition("/")
    return parent if separator else ""


@dataclass(frozen=True, slots=True)
class EbookOperationEvidenceReference:
    kind: str
    ref_id: EntityId
    material_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or _REFERENCE_KIND.fullmatch(self.kind) is None:
            raise ValueError("kind must be a bounded uppercase reference kind")
        _entity_id(self.ref_id, "ref_id")
        object.__setattr__(
            self,
            "material_fingerprint",
            _sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationSourceSnapshot:
    ordinal: int
    role: EbookOperationSourceRole
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    source_scan_run_status: ScanRunStatus
    file_id: EntityId
    observation_id: EntityId
    relative_locator: str = field(repr=False)
    format_label: str
    expected_presence_state: PresenceState
    expected_full_sha256: str = field(repr=False)
    expected_size_bytes: int
    expected_modified_at: datetime
    expected_observed_at: datetime
    source_evidence_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        _nonnegative_int(self.ordinal, "ordinal")
        if not isinstance(self.role, EbookOperationSourceRole):
            raise ValueError("role must be an EbookOperationSourceRole")
        for field_name in (
            "scan_root_id",
            "source_scan_run_id",
            "file_id",
            "observation_id",
        ):
            _entity_id(getattr(self, field_name), field_name)
        if self.source_scan_run_status is not ScanRunStatus.COMPLETED:
            raise ValueError("operation sources require a completed ScanRun")
        object.__setattr__(
            self,
            "relative_locator",
            _relative_locator(self.relative_locator),
        )
        object.__setattr__(self, "format_label", _format_label(self.format_label))
        if self.expected_presence_state is not PresenceState.PRESENT:
            raise ValueError("operation sources require PRESENT evidence")
        object.__setattr__(
            self,
            "expected_full_sha256",
            _sha256(self.expected_full_sha256, "expected_full_sha256"),
        )
        _nonnegative_int(self.expected_size_bytes, "expected_size_bytes")
        require_aware_datetime(self.expected_modified_at, "expected_modified_at")
        require_aware_datetime(self.expected_observed_at, "expected_observed_at")
        object.__setattr__(
            self,
            "source_evidence_fingerprint",
            _sha256(
                self.source_evidence_fingerprint,
                "source_evidence_fingerprint",
            ),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationTargetSnapshot:
    kind: EbookOperationTargetKind
    scope_id: EntityId
    relative_locator: str = field(repr=False)
    target_state_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EbookOperationTargetKind):
            raise ValueError("kind must be an EbookOperationTargetKind")
        _entity_id(self.scope_id, "scope_id")
        object.__setattr__(
            self,
            "relative_locator",
            _relative_locator(self.relative_locator),
        )
        object.__setattr__(
            self,
            "target_state_fingerprint",
            _sha256(self.target_state_fingerprint, "target_state_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationExpectedOutput:
    identity_kind: EbookOperationOutputIdentityKind
    format_label: str
    expected_full_sha256: str = field(repr=False)
    expected_size_bytes: int
    output_specification_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity_kind, EbookOperationOutputIdentityKind):
            raise ValueError("identity_kind must be an EbookOperationOutputIdentityKind")
        object.__setattr__(self, "format_label", _format_label(self.format_label))
        object.__setattr__(
            self,
            "expected_full_sha256",
            _sha256(self.expected_full_sha256, "expected_full_sha256"),
        )
        _nonnegative_int(self.expected_size_bytes, "expected_size_bytes")
        object.__setattr__(
            self,
            "output_specification_fingerprint",
            _sha256(
                self.output_specification_fingerprint,
                "output_specification_fingerprint",
            ),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationProcessorRequirement:
    kind: EbookOperationProcessorKind
    processor_profile: str
    configuration_fingerprint: str = field(repr=False)
    material_fingerprint: str = field(repr=False)
    provider_id: str | None = None
    tool_version: str | None = None
    adapter_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EbookOperationProcessorKind):
            raise ValueError("kind must be an EbookOperationProcessorKind")
        object.__setattr__(
            self,
            "processor_profile",
            _technical_id(self.processor_profile, "processor_profile"),
        )
        object.__setattr__(
            self,
            "configuration_fingerprint",
            _sha256(self.configuration_fingerprint, "configuration_fingerprint"),
        )
        object.__setattr__(
            self,
            "material_fingerprint",
            _sha256(self.material_fingerprint, "material_fingerprint"),
        )
        tool_fields = ("provider_id", "tool_version", "adapter_version")
        if self.kind is EbookOperationProcessorKind.FOLIOTONE_NATIVE:
            if any(getattr(self, field_name) is not None for field_name in tool_fields):
                raise ValueError("native processor cannot bind ToolProvider fields")
        else:
            if any(getattr(self, field_name) is None for field_name in tool_fields):
                raise ValueError("ToolProvider processor requires provider/tool/adapter identity")
            for field_name in tool_fields:
                object.__setattr__(
                    self,
                    field_name,
                    _technical_id(getattr(self, field_name), field_name),
                )


@dataclass(frozen=True, slots=True)
class EbookOperationDependencySnapshot:
    kind: EbookOperationDependencyKind
    state: EbookOperationDependencyState
    snapshot_kind: str
    snapshot_id: EntityId
    material_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EbookOperationDependencyKind):
            raise ValueError("kind must be an EbookOperationDependencyKind")
        if not isinstance(self.state, EbookOperationDependencyState):
            raise ValueError("state must be an EbookOperationDependencyState")
        object.__setattr__(
            self,
            "snapshot_kind",
            _technical_id(self.snapshot_kind, "snapshot_kind"),
        )
        _entity_id(self.snapshot_id, "snapshot_id")
        object.__setattr__(
            self,
            "material_fingerprint",
            _sha256(self.material_fingerprint, "material_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationRecipeCandidate:
    id: EntityId
    operation_kind: EbookOperationKind
    sources: tuple[EbookOperationSourceSnapshot, ...]
    target: EbookOperationTargetSnapshot
    expected_output: EbookOperationExpectedOutput
    collision_policy: EbookOperationCollisionPolicy
    workspace_mode: EbookOperationWorkspaceMode
    recovery_mode: EbookOperationRecoveryMode
    processor_requirement: EbookOperationProcessorRequirement
    dependencies: tuple[EbookOperationDependencySnapshot, ...]
    verification_codes: tuple[EbookOperationVerificationCode, ...]
    workspace_requirement_fingerprint: str = field(repr=False)
    recovery_requirement_fingerprint: str = field(repr=False)
    verification_fingerprint: str = field(repr=False)
    evidence_refs: tuple[EbookOperationEvidenceReference, ...]
    evidence_fingerprint: str = field(repr=False)
    content_hash: str = field(repr=False)
    created_at: datetime
    profile: str = EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE
    serializer_version: str = EBOOK_OPERATION_RECIPE_SERIALIZER

    def __post_init__(self) -> None:
        if self.profile != EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE:
            raise ValueError("operation recipe candidate profile is invalid")
        if self.serializer_version != EBOOK_OPERATION_RECIPE_SERIALIZER:
            raise ValueError("operation recipe candidate serializer is invalid")
        _entity_id(self.id, "id")
        if not isinstance(self.operation_kind, EbookOperationKind):
            raise ValueError("operation_kind must be an EbookOperationKind")
        if not 1 <= len(self.sources) <= MAX_EBOOK_OPERATION_SOURCES:
            raise ValueError("sources must contain between one and 32 entries")
        if tuple(source.ordinal for source in self.sources) != tuple(
            range(len(self.sources))
        ):
            raise ValueError("source ordinals must be contiguous and ordered")
        if self.sources[0].role is not EbookOperationSourceRole.PRIMARY or any(
            source.role is not EbookOperationSourceRole.COMPANION
            for source in self.sources[1:]
        ):
            raise ValueError("sources require one primary followed by companions")
        primary = self.sources[0]
        if self.operation_kind is not EbookOperationKind.ARCHIVE_REWRITE and len(
            self.sources
        ) != 1:
            raise ValueError("only archive rewrite can bind companion sources")
        if any(
            source.scan_root_id != primary.scan_root_id
            or source.source_scan_run_id != primary.source_scan_run_id
            for source in self.sources[1:]
        ):
            raise ValueError("companion sources must share primary ScanRoot and ScanRun")
        source_keys = tuple((source.file_id, source.observation_id) for source in self.sources)
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("sources must be unique")
        if not isinstance(self.target, EbookOperationTargetSnapshot):
            raise ValueError("target must be an EbookOperationTargetSnapshot")
        if not isinstance(self.expected_output, EbookOperationExpectedOutput):
            raise ValueError("expected_output must be an EbookOperationExpectedOutput")
        if self.target.kind is not _TARGET_KIND[self.operation_kind]:
            raise ValueError("target kind is incompatible with operation kind")
        if self.expected_output.identity_kind is not _OUTPUT_IDENTITY[
            self.operation_kind
        ]:
            raise ValueError("output identity is incompatible with operation kind")
        if self.collision_policy is not _COLLISION_POLICY[self.operation_kind]:
            raise ValueError("collision policy is incompatible with operation kind")
        if self.workspace_mode is not _WORKSPACE_MODE[self.operation_kind]:
            raise ValueError("workspace mode is incompatible with operation kind")
        if self.recovery_mode is not _RECOVERY_MODE[self.operation_kind]:
            raise ValueError("recovery mode is incompatible with operation kind")
        _validate_target_relation(self.operation_kind, primary, self.target)
        if (
            self.expected_output.identity_kind
            is EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
            and (
                self.expected_output.format_label != primary.format_label
                or self.expected_output.expected_full_sha256
                != primary.expected_full_sha256
                or self.expected_output.expected_size_bytes
                != primary.expected_size_bytes
            )
        ):
            raise ValueError("byte-identical output must match the primary source")
        if not isinstance(
            self.processor_requirement,
            EbookOperationProcessorRequirement,
        ):
            raise ValueError("processor_requirement is invalid")
        if self.operation_kind in {
            EbookOperationKind.FILE_RENAME,
            EbookOperationKind.FILE_REORGANIZE,
            EbookOperationKind.FILE_IMPORT,
            EbookOperationKind.FILE_EXPORT,
        } and self.processor_requirement.kind is not (
            EbookOperationProcessorKind.FOLIOTONE_NATIVE
        ):
            raise ValueError("byte-preserving file operations require native processing")
        dependency_kinds = tuple(value.kind for value in self.dependencies)
        if dependency_kinds != tuple(EbookOperationDependencyKind):
            raise ValueError("dependencies must contain all axes in canonical order")
        required_verification = required_verification_codes(self.operation_kind)
        if self.verification_codes != required_verification:
            raise ValueError("verification codes are incomplete or not canonical")
        for field_name in (
            "workspace_requirement_fingerprint",
            "recovery_requirement_fingerprint",
            "verification_fingerprint",
            "evidence_fingerprint",
            "content_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        _require_sorted_unique_evidence(self.evidence_refs)
        if not self.evidence_refs:
            raise ValueError("candidate requires at least one evidence reference")
        require_aware_datetime(self.created_at, "created_at")


def _validate_target_relation(
    operation_kind: EbookOperationKind,
    primary: EbookOperationSourceSnapshot,
    target: EbookOperationTargetSnapshot,
) -> None:
    same_scope = target.scope_id == primary.scan_root_id
    same_locator = target.relative_locator == primary.relative_locator
    same_parent = _parent(target.relative_locator) == _parent(primary.relative_locator)
    if operation_kind is EbookOperationKind.FILE_RENAME and not (
        same_scope and same_parent and not same_locator
    ):
        raise ValueError("rename requires a different basename in the same parent")
    if operation_kind is EbookOperationKind.FILE_REORGANIZE and not (
        same_scope and not same_parent and not same_locator
    ):
        raise ValueError("reorganization requires a different parent in the same root")
    if operation_kind is EbookOperationKind.FILE_IMPORT and same_scope:
        raise ValueError("import target must use a different managed ScanRoot")
    if operation_kind is EbookOperationKind.FORMAT_TRANSFORM and same_scope and same_locator:
        raise ValueError("transformation target cannot overwrite its source locator")
    if operation_kind is EbookOperationKind.ARCHIVE_REWRITE and not (
        same_scope and same_locator
    ):
        raise ValueError("archive rewrite must bind the exact source replacement slot")


def required_verification_codes(
    operation_kind: EbookOperationKind,
) -> tuple[EbookOperationVerificationCode, ...]:
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    required = {
        EbookOperationVerificationCode.INPUT_IDENTITY_RECHECKED,
        EbookOperationVerificationCode.TARGET_STATE_RECHECKED,
        EbookOperationVerificationCode.OUTPUT_FULL_SHA256_MATCHES,
        EbookOperationVerificationCode.OUTPUT_SIZE_MATCHES,
        EbookOperationVerificationCode.SOURCE_PRESENCE_VERIFIED,
    }
    if operation_kind in {
        EbookOperationKind.FILE_RENAME,
        EbookOperationKind.FILE_REORGANIZE,
        EbookOperationKind.FILE_IMPORT,
        EbookOperationKind.FORMAT_TRANSFORM,
        EbookOperationKind.ARCHIVE_REWRITE,
    }:
        required.update(
            {
                EbookOperationVerificationCode.RESCAN_COMPLETED,
                EbookOperationVerificationCode.COLLECTION_STATE_RECONCILED,
            }
        )
    if operation_kind in {
        EbookOperationKind.FORMAT_TRANSFORM,
        EbookOperationKind.ARCHIVE_REWRITE,
    }:
        required.add(EbookOperationVerificationCode.FORMAT_READABLE)
    if operation_kind is EbookOperationKind.ARCHIVE_REWRITE:
        required.add(EbookOperationVerificationCode.DEPENDENCIES_RECONCILED)
    return tuple(code for code in EbookOperationVerificationCode if code in required)


def _evidence_key(
    value: EbookOperationEvidenceReference,
) -> tuple[str, str, str]:
    return value.kind, str(value.ref_id), value.material_fingerprint


def _require_sorted_unique_evidence(
    values: tuple[EbookOperationEvidenceReference, ...],
) -> None:
    if len(values) > MAX_EBOOK_OPERATION_EVIDENCE_REFS:
        raise ValueError("evidence_refs exceeds the configured limit")
    keys = tuple(_evidence_key(value) for value in values)
    identities = tuple((value.kind, value.ref_id) for value in values)
    if keys != tuple(sorted(keys)) or len(identities) != len(set(identities)):
        raise ValueError("evidence_refs must be sorted and semantically unique")


@dataclass(frozen=True, slots=True)
class EbookOperationReviewSnapshot:
    candidate_id: EntityId
    state: EbookOperationReviewState
    evidence_fingerprint: str = field(repr=False)
    candidate_set_fingerprint: str = field(repr=False)
    producer_name: str = EBOOK_OPERATION_RECIPE_PRODUCER_NAME
    producer_version: str = EBOOK_OPERATION_RECIPE_PRODUCER_VERSION
    decision_compatibility_version: str = (
        EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY
    )
    review_type: str = EBOOK_OPERATION_RECIPE_REVIEW_TYPE
    candidate_kind: str = EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND
    review_item_id: EntityId | None = None
    decision_id: EntityId | None = None
    decision_sequence_no: int | None = None

    def __post_init__(self) -> None:
        _entity_id(self.candidate_id, "candidate_id")
        if not isinstance(self.state, EbookOperationReviewState):
            raise ValueError("state must be an EbookOperationReviewState")
        expected = (
            ("producer_name", EBOOK_OPERATION_RECIPE_PRODUCER_NAME),
            ("producer_version", EBOOK_OPERATION_RECIPE_PRODUCER_VERSION),
            (
                "decision_compatibility_version",
                EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY,
            ),
            ("review_type", EBOOK_OPERATION_RECIPE_REVIEW_TYPE),
            (
                "candidate_kind",
                EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND,
            ),
        )
        if any(getattr(self, field_name) != value for field_name, value in expected):
            raise ValueError("review contract is incompatible with recipe v1")
        for field_name in ("evidence_fingerprint", "candidate_set_fingerprint"):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        if self.state is EbookOperationReviewState.MISSING:
            if any(
                value is not None
                for value in (
                    self.review_item_id,
                    self.decision_id,
                    self.decision_sequence_no,
                )
            ):
                raise ValueError("MISSING review cannot bind persisted records")
            return
        if self.review_item_id is None:
            raise ValueError("non-missing review requires review_item_id")
        _entity_id(self.review_item_id, "review_item_id")
        decided = self.state in {
            EbookOperationReviewState.ACCEPTED,
            EbookOperationReviewState.REJECTED,
        }
        if decided:
            if self.decision_id is None:
                raise ValueError("decided review requires decision_id")
            _entity_id(self.decision_id, "decision_id")
            if (
                isinstance(self.decision_sequence_no, bool)
                or not isinstance(self.decision_sequence_no, int)
                or self.decision_sequence_no < 1
            ):
                raise ValueError("decided review requires a positive sequence")
        elif self.decision_id is not None or self.decision_sequence_no is not None:
            raise ValueError("unresolved review cannot carry an effective decision")


@dataclass(frozen=True, slots=True)
class EbookOperationPrecondition:
    code: EbookOperationPreconditionCode
    expected_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, EbookOperationPreconditionCode):
            raise ValueError("code must be an EbookOperationPreconditionCode")
        object.__setattr__(
            self,
            "expected_fingerprint",
            _sha256(self.expected_fingerprint, "expected_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class EbookOperationBlocker:
    code: EbookOperationBlockerCode
    evidence_refs: tuple[EbookOperationEvidenceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, EbookOperationBlockerCode):
            raise ValueError("code must be an EbookOperationBlockerCode")
        _require_sorted_unique_evidence(self.evidence_refs)


@dataclass(frozen=True, slots=True)
class EbookOperationRecipePlan:
    id: EntityId
    candidate: EbookOperationRecipeCandidate
    review: EbookOperationReviewSnapshot
    preconditions: tuple[EbookOperationPrecondition, ...]
    blockers: tuple[EbookOperationBlocker, ...]
    status: EbookOperationPlanStatus
    execution_state: EbookOperationExecutionState
    content_hash: str = field(repr=False)
    created_at: datetime
    profile: str = EBOOK_OPERATION_RECIPE_PLAN_PROFILE
    serializer_version: str = EBOOK_OPERATION_RECIPE_SERIALIZER

    def __post_init__(self) -> None:
        if self.profile != EBOOK_OPERATION_RECIPE_PLAN_PROFILE:
            raise ValueError("operation recipe plan profile is invalid")
        if self.serializer_version != EBOOK_OPERATION_RECIPE_SERIALIZER:
            raise ValueError("operation recipe plan serializer is invalid")
        _entity_id(self.id, "id")
        if not isinstance(self.candidate, EbookOperationRecipeCandidate):
            raise ValueError("candidate must be an EbookOperationRecipeCandidate")
        if not isinstance(self.review, EbookOperationReviewSnapshot):
            raise ValueError("review must be an EbookOperationReviewSnapshot")
        if self.review.candidate_id != self.candidate.id:
            raise ValueError("review candidate binding differs")
        precondition_codes = tuple(value.code for value in self.preconditions)
        if precondition_codes != tuple(
            sorted(set(precondition_codes), key=lambda code: code.value)
        ):
            raise ValueError("preconditions must be sorted and unique")
        base_preconditions = set(EbookOperationPreconditionCode) - {
            EbookOperationPreconditionCode.REVIEW_APPROVAL_UNCHANGED
        }
        if not base_preconditions <= set(precondition_codes):
            raise ValueError("plan requires every non-review precondition")
        blocker_codes = tuple(value.code for value in self.blockers)
        if blocker_codes != tuple(sorted(set(blocker_codes), key=lambda code: code.value)):
            raise ValueError("blockers must be sorted and unique")
        if not isinstance(self.status, EbookOperationPlanStatus):
            raise ValueError("status must be an EbookOperationPlanStatus")
        if self.execution_state is not EbookOperationExecutionState.NOT_EXECUTABLE:
            raise ValueError("operation recipe plans are permanently NOT_EXECUTABLE")
        review_compatible = (
            self.review.evidence_fingerprint == self.candidate.evidence_fingerprint
            and self.review.candidate_set_fingerprint == self.candidate.content_hash
        )
        if self.status is EbookOperationPlanStatus.BLOCKED:
            if not self.blockers:
                raise ValueError("BLOCKED plan requires at least one blocker")
        elif self.blockers:
            raise ValueError("non-blocked plan cannot carry blockers")
        if self.status is not EbookOperationPlanStatus.BLOCKED and not review_compatible:
            raise ValueError("non-blocked review does not bind the plan candidate")
        if self.status is EbookOperationPlanStatus.REVIEW_REQUIRED and self.review.state not in {
            EbookOperationReviewState.PENDING,
            EbookOperationReviewState.DEFERRED,
        }:
            raise ValueError("REVIEW_REQUIRED plan requires an open review")
        if self.status is EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE and (
            self.review.state is not EbookOperationReviewState.ACCEPTED
        ):
            raise ValueError("approved plan requires an accepted review")
        approval_precondition = (
            EbookOperationPreconditionCode.REVIEW_APPROVAL_UNCHANGED
            in set(precondition_codes)
        )
        accepted_review = (
            review_compatible
            and self.review.state is EbookOperationReviewState.ACCEPTED
        )
        if approval_precondition != accepted_review:
            raise ValueError("review approval precondition does not match review state")
        object.__setattr__(self, "content_hash", _sha256(self.content_hash, "content_hash"))
        require_aware_datetime(self.created_at, "created_at")


__all__ = [
    "EBOOK_OPERATION_RECIPE_CANDIDATE_NAMESPACE",
    "EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE",
    "EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY",
    "EBOOK_OPERATION_RECIPE_PLAN_NAMESPACE",
    "EBOOK_OPERATION_RECIPE_PLAN_PROFILE",
    "EBOOK_OPERATION_RECIPE_PRODUCER_NAME",
    "EBOOK_OPERATION_RECIPE_PRODUCER_VERSION",
    "EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND",
    "EBOOK_OPERATION_RECIPE_REVIEW_TYPE",
    "EBOOK_OPERATION_RECIPE_SERIALIZER",
    "MAX_EBOOK_OPERATION_EVIDENCE_REFS",
    "MAX_EBOOK_OPERATION_SOURCES",
    "EbookOperationBlocker",
    "EbookOperationBlockerCode",
    "EbookOperationCollisionPolicy",
    "EbookOperationDependencyKind",
    "EbookOperationDependencySnapshot",
    "EbookOperationDependencyState",
    "EbookOperationEvidenceReference",
    "EbookOperationExecutionState",
    "EbookOperationExpectedOutput",
    "EbookOperationKind",
    "EbookOperationOutputIdentityKind",
    "EbookOperationPlanStatus",
    "EbookOperationPrecondition",
    "EbookOperationPreconditionCode",
    "EbookOperationProcessorKind",
    "EbookOperationProcessorRequirement",
    "EbookOperationRecipeCandidate",
    "EbookOperationRecipePlan",
    "EbookOperationRecoveryMode",
    "EbookOperationReviewSnapshot",
    "EbookOperationReviewState",
    "EbookOperationSourceRole",
    "EbookOperationSourceSnapshot",
    "EbookOperationTargetKind",
    "EbookOperationTargetSnapshot",
    "EbookOperationVerificationCode",
    "EbookOperationWorkspaceMode",
    "operation_collision_policy",
    "operation_output_identity_kind",
    "operation_recovery_mode",
    "operation_target_kind",
    "operation_workspace_mode",
    "required_verification_codes",
]
