"""Pure RN02 authority, probe, run, and journal contracts for e-book rename."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid5

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import (
    EbookOperationCollisionPolicy,
    EbookOperationDependencyKind,
    EbookOperationDependencyState,
    EbookOperationExecutionState,
    EbookOperationKind,
    EbookOperationOutputIdentityKind,
    EbookOperationPlanStatus,
    EbookOperationProcessorKind,
    EbookOperationRecipePlan,
    EbookOperationRecoveryMode,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationTargetKind,
    EbookOperationWorkspaceMode,
    ebook_operation_recipe_candidate_content_hash,
    ebook_operation_recipe_candidate_id,
    ebook_operation_recipe_plan_content_hash,
    ebook_operation_recipe_plan_id,
)
from foliotone.ebook_rename.capabilities import (
    EBOOK_RENAME_CAPABILITY_PROFILE,
    ResolvedEbookRenameCapability,
)
from foliotone.ebook_rename.dependency_scopes import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EbookRenameDependencyScopeMode,
    ResolvedEbookRenameDependencyScope,
    ebook_rename_dependency_axis_material_fingerprint,
    ebook_rename_dependency_scope_material_fingerprint,
)
from foliotone.ebook_rename.target import EBOOK_RENAME_PROCESSOR_PROFILE

EBOOK_RENAME_PREPARATION_PROFILE: Final = "ebook-file-rename-preparation/v1"
EBOOK_RENAME_AUTHORIZATION_PROFILE: Final = "ebook-file-rename-authorization/v1"
EBOOK_RENAME_RUN_PROFILE: Final = "ebook-file-rename-run/v1"
EBOOK_RENAME_PROBE_PROFILE: Final = "ebook-file-rename-capability-probe/v1"
EBOOK_RENAME_PLATFORM_PROFILE: Final = "linux-x86_64-glibc/v1"
MAX_EBOOK_RENAME_AUTHORIZATION_LIFETIME: Final = timedelta(minutes=15)
MAX_EBOOK_RENAME_EVENTS: Final = 16
EBOOK_RENAME_ALLOWED_FILESYSTEMS: Final = frozenset({"ext4", "btrfs", "xfs", "tmpfs"})

_PREPARATION_DOMAIN: Final = b"foliotone:ebook-rename-preparation/v1\x00"
_AUTHORIZATION_DOMAIN: Final = b"foliotone:ebook-rename-authorization/v1\x00"
_PROBE_DOMAIN: Final = b"foliotone:ebook-rename-capability-probe/v1\x00"
_BACKEND_BINDING_DOMAIN: Final = b"foliotone:ebook-rename-backend-binding/v1\x00"
_LOCATOR_SOURCE_DOMAIN: Final = b"foliotone:ebook-rename-source-locator/v1\x00"
_LOCATOR_TARGET_DOMAIN: Final = b"foliotone:ebook-rename-target-locator/v1\x00"
_TARGET_ABSENCE_DOMAIN: Final = b"foliotone:ebook-rename-target-absence/v1\x00"
_DEPENDENCIES_DOMAIN: Final = b"foliotone:ebook-rename-dependencies/v1\x00"

_PREPARATION_NAMESPACE: Final = UUID("9f4206b7-0fe2-578c-a51f-a827666f7719")
_AUTHORIZATION_NAMESPACE: Final = UUID("df9c3e7c-58d3-59db-b61c-af37073c622f")
_PROBE_NAMESPACE: Final = UUID("7d17affd-c90e-5d8c-a531-e55e1aa02578")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_TECHNICAL_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,256}\Z")


@runtime_checkable
class EbookRenameLeaseSnapshot(Protocol):
    """Persistence-neutral root-fence evidence required by the contract."""

    @property
    def scan_root_id(self) -> EntityId: ...

    @property
    def owner_kind(self) -> object: ...

    @property
    def owner_run_id(self) -> EntityId: ...

    @property
    def fence_epoch(self) -> int: ...

    @property
    def acquired_at(self) -> datetime: ...

    @property
    def lease_expires_at(self) -> datetime: ...


class EbookRenameAuthorityErrorCode(StrEnum):
    PLAN_INVALID = "PLAN_INVALID"
    PHYSICAL_EVIDENCE_INVALID = "PHYSICAL_EVIDENCE_INVALID"
    DEPENDENCY_SCOPE_INVALID = "DEPENDENCY_SCOPE_INVALID"
    CAPABILITY_INVALID = "CAPABILITY_INVALID"
    PROBE_INVALID = "PROBE_INVALID"
    PREPARATION_INVALID = "PREPARATION_INVALID"
    AUTHORIZATION_WINDOW_INVALID = "AUTHORIZATION_WINDOW_INVALID"
    AUTHORIZATION_INVALID = "AUTHORIZATION_INVALID"
    LEASE_INVALID = "LEASE_INVALID"
    RUN_INVALID = "RUN_INVALID"
    BACKEND_BINDING_INVALID = "BACKEND_BINDING_INVALID"
    EVENT_INVALID = "EVENT_INVALID"


class EbookRenameAuthorityError(ValueError):
    """One fixed-code failure without paths, locators, hashes, or attributes."""

    def __init__(self, code: EbookRenameAuthorityErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class EbookRenameRunStatus(StrEnum):
    PREPARED = "PREPARED"
    RELOCATED = "RELOCATED"
    IMMEDIATE_VERIFIED = "IMMEDIATE_VERIFIED"
    RECOVERY_RELOCATED = "RECOVERY_RELOCATED"
    RECOVERY_VERIFIED = "RECOVERY_VERIFIED"
    SCAN_HANDOFF = "SCAN_HANDOFF"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"
    RECOVERED = "RECOVERED"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"


_TERMINAL_STATUSES: Final = frozenset(
    {
        EbookRenameRunStatus.VERIFIED,
        EbookRenameRunStatus.CANCELLED,
        EbookRenameRunStatus.RECOVERED,
        EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
    }
)
_TRANSITIONS: Final = {
    EbookRenameRunStatus.PREPARED: frozenset(
        {
            EbookRenameRunStatus.RELOCATED,
            EbookRenameRunStatus.RECOVERY_RELOCATED,
            EbookRenameRunStatus.CANCELLED,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    EbookRenameRunStatus.RELOCATED: frozenset(
        {
            EbookRenameRunStatus.IMMEDIATE_VERIFIED,
            EbookRenameRunStatus.RECOVERY_RELOCATED,
            EbookRenameRunStatus.RECOVERY_VERIFIED,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    EbookRenameRunStatus.IMMEDIATE_VERIFIED: frozenset(
        {
            EbookRenameRunStatus.SCAN_HANDOFF,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    EbookRenameRunStatus.RECOVERY_RELOCATED: frozenset(
        {
            EbookRenameRunStatus.RECOVERY_VERIFIED,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    EbookRenameRunStatus.RECOVERY_VERIFIED: frozenset(
        {
            EbookRenameRunStatus.SCAN_HANDOFF,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    EbookRenameRunStatus.SCAN_HANDOFF: frozenset(
        {
            EbookRenameRunStatus.VERIFIED,
            EbookRenameRunStatus.RECOVERED,
            EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
}


def _fail(code: EbookRenameAuthorityErrorCode) -> NoReturn:
    raise EbookRenameAuthorityError(code)


@dataclass(frozen=True, slots=True)
class EbookRenameCapabilityProbeSnapshot:
    """Successful immutable conformance evidence; failed probes are not authority."""

    id: EntityId
    ebook_rename_capability_id: EntityId
    scan_root_id: EntityId
    capability_configuration_fingerprint: str = field(repr=False)
    filesystem_type: str
    filesystem_identity_fingerprint: str = field(repr=False)
    kernel_release: str
    probed_at: datetime
    content_hash: str = field(repr=False)
    openat2_supported: bool = True
    renameat2_noreplace_supported: bool = True
    directory_fsync_supported: bool = True
    root_probe_same_filesystem: bool = True
    platform_profile: str = EBOOK_RENAME_PLATFORM_PROFILE
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    capability_profile: str = EBOOK_RENAME_CAPABILITY_PROFILE
    profile: str = EBOOK_RENAME_PROBE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, EntityId)
            or not isinstance(self.ebook_rename_capability_id, EntityId)
            or not isinstance(self.scan_root_id, EntityId)
            or self.filesystem_type not in EBOOK_RENAME_ALLOWED_FILESYSTEMS
            or self.profile != EBOOK_RENAME_PROBE_PROFILE
            or self.platform_profile != EBOOK_RENAME_PLATFORM_PROFILE
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or self.capability_profile != EBOOK_RENAME_CAPABILITY_PROFILE
            or not all(
                type(value) is bool and value
                for value in (
                    self.openat2_supported,
                    self.renameat2_noreplace_supported,
                    self.directory_fsync_supported,
                    self.root_probe_same_filesystem,
                )
            )
        ):
            _fail(EbookRenameAuthorityErrorCode.PROBE_INVALID)
        _sha256(
            self.capability_configuration_fingerprint,
            EbookRenameAuthorityErrorCode.PROBE_INVALID,
        )
        _sha256(
            self.filesystem_identity_fingerprint,
            EbookRenameAuthorityErrorCode.PROBE_INVALID,
        )
        _sha256(self.content_hash, EbookRenameAuthorityErrorCode.PROBE_INVALID)
        _technical(self.kernel_release, EbookRenameAuthorityErrorCode.PROBE_INVALID)
        object.__setattr__(
            self,
            "probed_at",
            _utc(self.probed_at, EbookRenameAuthorityErrorCode.PROBE_INVALID),
        )
        expected = _probe_content_hash(self)
        if self.content_hash != expected or self.id != _probe_id(expected):
            _fail(EbookRenameAuthorityErrorCode.PROBE_INVALID)


@dataclass(frozen=True, slots=True)
class EbookRenamePhysicalPreparationEvidence:
    """Private read-only physical evidence used to build one preparation."""

    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    source_locator_digest: str = field(repr=False)
    target_locator_digest: str = field(repr=False)
    source_device: int = field(repr=False)
    source_inode: int = field(repr=False)
    source_mode: int = field(repr=False)
    source_uid: int = field(repr=False)
    source_gid: int = field(repr=False)
    source_link_count: int = field(repr=False)
    source_size_bytes: int
    source_mtime_ns: int = field(repr=False)
    source_modified_at: datetime
    source_full_sha256: str = field(repr=False)
    source_xattr_fingerprint: str = field(repr=False)
    source_format_label: str
    target_state_fingerprint: str = field(repr=False)
    target_absence_fingerprint: str = field(repr=False)
    captured_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId)
            for value in (self.scan_root_id, self.file_id, self.observation_id)
        ):
            _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
        for digest in (
            self.source_locator_digest,
            self.target_locator_digest,
            self.source_full_sha256,
            self.source_xattr_fingerprint,
            self.target_state_fingerprint,
            self.target_absence_fingerprint,
        ):
            _sha256(digest, EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
        for number in (
            self.source_uid,
            self.source_gid,
            self.source_size_bytes,
        ):
            if not _nonnegative_int(number):
                _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
        if (
            not _positive_int(self.source_device)
            or not _positive_int(self.source_inode)
            or not _positive_int(self.source_mode)
            or not stat.S_ISREG(self.source_mode)
            or not _signed_64_int(self.source_mtime_ns)
            or self.source_link_count != 1
        ):
            _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
        _format_label(
            self.source_format_label,
            EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID,
        )
        modified = _utc(
            self.source_modified_at,
            EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID,
        )
        captured = _utc(
            self.captured_at,
            EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID,
        )
        object.__setattr__(self, "source_modified_at", modified)
        object.__setattr__(self, "captured_at", captured)


@dataclass(frozen=True, slots=True)
class EbookRenamePreparationSnapshot:
    """Content-addressed plan and physical binding under a preparation fence."""

    id: EntityId
    preparation_owner_id: EntityId
    preparation_fence_epoch: int
    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    candidate_id: EntityId
    candidate_content_hash: str = field(repr=False)
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    source_file_id: EntityId
    source_observation_id: EntityId
    source_locator_digest: str = field(repr=False)
    target_locator_digest: str = field(repr=False)
    source_format_label: str
    source_full_sha256: str = field(repr=False)
    source_size_bytes: int
    source_modified_at: datetime
    source_device: int = field(repr=False)
    source_inode: int = field(repr=False)
    source_mode: int = field(repr=False)
    source_uid: int = field(repr=False)
    source_gid: int = field(repr=False)
    source_link_count: int = field(repr=False)
    source_mtime_ns: int = field(repr=False)
    source_xattr_fingerprint: str = field(repr=False)
    target_state_fingerprint: str = field(repr=False)
    target_absence_fingerprint: str = field(repr=False)
    dependency_scope_id: EntityId
    dependency_scope_material_fingerprint: str = field(repr=False)
    dependencies_fingerprint: str = field(repr=False)
    review_item_id: EntityId
    review_decision_id: EntityId
    review_decision_sequence_no: int
    review_evidence_fingerprint: str = field(repr=False)
    review_candidate_set_fingerprint: str = field(repr=False)
    ebook_rename_capability_id: EntityId
    capability_configuration_fingerprint: str = field(repr=False)
    probe_id: EntityId
    probe_content_hash: str = field(repr=False)
    authorized_at: datetime
    prepared_at: datetime
    content_hash: str = field(repr=False)
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    probe_profile: str = EBOOK_RENAME_PROBE_PROFILE
    profile: str = EBOOK_RENAME_PREPARATION_PROFILE

    def __post_init__(self) -> None:
        entity_values = (
            self.id,
            self.preparation_owner_id,
            self.plan_id,
            self.candidate_id,
            self.scan_root_id,
            self.source_scan_run_id,
            self.source_file_id,
            self.source_observation_id,
            self.dependency_scope_id,
            self.review_item_id,
            self.review_decision_id,
            self.ebook_rename_capability_id,
            self.probe_id,
        )
        if (
            self.profile != EBOOK_RENAME_PREPARATION_PROFILE
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or self.probe_profile != EBOOK_RENAME_PROBE_PROFILE
            or not all(isinstance(value, EntityId) for value in entity_values)
            or not _positive_int(self.preparation_fence_epoch)
            or not _positive_int(self.review_decision_sequence_no)
            or not _nonnegative_int(self.source_size_bytes)
            or not _positive_int(self.source_device)
            or not _positive_int(self.source_inode)
            or not _positive_int(self.source_mode)
            or not stat.S_ISREG(self.source_mode)
            or not _nonnegative_int(self.source_uid)
            or not _nonnegative_int(self.source_gid)
            or self.source_link_count != 1
            or not _signed_64_int(self.source_mtime_ns)
        ):
            _fail(EbookRenameAuthorityErrorCode.PREPARATION_INVALID)
        for value in (
            self.plan_content_hash,
            self.candidate_content_hash,
            self.source_locator_digest,
            self.target_locator_digest,
            self.source_full_sha256,
            self.source_xattr_fingerprint,
            self.target_state_fingerprint,
            self.target_absence_fingerprint,
            self.dependency_scope_material_fingerprint,
            self.dependencies_fingerprint,
            self.review_evidence_fingerprint,
            self.review_candidate_set_fingerprint,
            self.capability_configuration_fingerprint,
            self.probe_content_hash,
            self.content_hash,
        ):
            _sha256(value, EbookRenameAuthorityErrorCode.PREPARATION_INVALID)
        _format_label(
            self.source_format_label,
            EbookRenameAuthorityErrorCode.PREPARATION_INVALID,
        )
        authorized = _second_utc(
            self.authorized_at,
            EbookRenameAuthorityErrorCode.PREPARATION_INVALID,
        )
        prepared = _utc(
            self.prepared_at,
            EbookRenameAuthorityErrorCode.PREPARATION_INVALID,
        )
        object.__setattr__(self, "authorized_at", authorized)
        object.__setattr__(self, "prepared_at", prepared)
        object.__setattr__(
            self,
            "source_modified_at",
            _utc(
                self.source_modified_at,
                EbookRenameAuthorityErrorCode.PREPARATION_INVALID,
            ),
        )
        if prepared < authorized:
            _fail(EbookRenameAuthorityErrorCode.PREPARATION_INVALID)
        expected = _preparation_content_hash(self)
        if self.content_hash != expected or self.id != _preparation_id(expected):
            _fail(EbookRenameAuthorityErrorCode.PREPARATION_INVALID)


@dataclass(frozen=True, slots=True)
class EbookRenameAuthorizationSnapshot:
    """At-most-15-minute, one-use authority for one exact preparation."""

    id: EntityId
    preparation_id: EntityId
    preparation_content_hash: str = field(repr=False)
    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    candidate_id: EntityId
    scan_root_id: EntityId
    source_file_id: EntityId
    ebook_rename_capability_id: EntityId
    capability_configuration_fingerprint: str = field(repr=False)
    probe_id: EntityId
    probe_content_hash: str = field(repr=False)
    authorized_at: datetime
    prepared_at: datetime
    expires_at: datetime
    content_hash: str = field(repr=False)
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    probe_profile: str = EBOOK_RENAME_PROBE_PROFILE
    profile: str = EBOOK_RENAME_AUTHORIZATION_PROFILE

    def __post_init__(self) -> None:
        if (
            self.profile != EBOOK_RENAME_AUTHORIZATION_PROFILE
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or self.probe_profile != EBOOK_RENAME_PROBE_PROFILE
            or not all(
                isinstance(value, EntityId)
                for value in (
                    self.id,
                    self.preparation_id,
                    self.plan_id,
                    self.candidate_id,
                    self.scan_root_id,
                    self.source_file_id,
                    self.ebook_rename_capability_id,
                    self.probe_id,
                )
            )
        ):
            _fail(EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID)
        for value in (
            self.preparation_content_hash,
            self.plan_content_hash,
            self.capability_configuration_fingerprint,
            self.probe_content_hash,
            self.content_hash,
        ):
            _sha256(value, EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID)
        authorized = _second_utc(
            self.authorized_at,
            EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID,
        )
        prepared = _utc(
            self.prepared_at,
            EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID,
        )
        expires = _utc(
            self.expires_at,
            EbookRenameAuthorityErrorCode.AUTHORIZATION_WINDOW_INVALID,
        )
        object.__setattr__(self, "authorized_at", authorized)
        object.__setattr__(self, "prepared_at", prepared)
        object.__setattr__(self, "expires_at", expires)
        _validate_window(authorized, prepared, expires)
        expected = _authorization_content_hash(self)
        if self.content_hash != expected or self.id != _authorization_id(expected):
            _fail(EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID)


@dataclass(frozen=True, slots=True)
class EbookRenameExecutionRun:
    """Immutable one-use run identity; this object performs no filesystem work."""

    id: EntityId
    authorization_id: EntityId
    authorization_content_hash: str = field(repr=False)
    plan_id: EntityId
    scan_root_id: EntityId
    source_file_id: EntityId
    ebook_rename_capability_id: EntityId
    probe_id: EntityId
    initial_fence_epoch: int
    created_at: datetime
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    profile: str = EBOOK_RENAME_RUN_PROFILE

    def __post_init__(self) -> None:
        if (
            self.profile != EBOOK_RENAME_RUN_PROFILE
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or not all(
                isinstance(value, EntityId)
                for value in (
                    self.id,
                    self.authorization_id,
                    self.plan_id,
                    self.scan_root_id,
                    self.source_file_id,
                    self.ebook_rename_capability_id,
                    self.probe_id,
                )
            )
            or not _positive_int(self.initial_fence_epoch)
        ):
            _fail(EbookRenameAuthorityErrorCode.RUN_INVALID)
        _sha256(
            self.authorization_content_hash,
            EbookRenameAuthorityErrorCode.RUN_INVALID,
        )
        object.__setattr__(
            self,
            "created_at",
            _utc(self.created_at, EbookRenameAuthorityErrorCode.RUN_INVALID),
        )


@dataclass(frozen=True, slots=True)
class EbookRenameBackendBinding:
    """Immutable run binding to the fixed backend and successful probe."""

    run_id: EntityId
    ebook_rename_capability_id: EntityId
    capability_configuration_fingerprint: str = field(repr=False)
    probe_id: EntityId
    probe_content_hash: str = field(repr=False)
    bound_at: datetime
    content_hash: str = field(repr=False)
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    probe_profile: str = EBOOK_RENAME_PROBE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_id, EntityId)
            or not isinstance(self.ebook_rename_capability_id, EntityId)
            or not isinstance(self.probe_id, EntityId)
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or self.probe_profile != EBOOK_RENAME_PROBE_PROFILE
        ):
            _fail(EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)
        for value in (
            self.capability_configuration_fingerprint,
            self.probe_content_hash,
            self.content_hash,
        ):
            _sha256(value, EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)
        object.__setattr__(
            self,
            "bound_at",
            _utc(self.bound_at, EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID),
        )
        if self.content_hash != _backend_binding_content_hash(self):
            _fail(EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)


@dataclass(frozen=True, slots=True)
class EbookRenameExecutionEvent:
    """One gapless append-only event bound to an actually held run fence."""

    run_id: EntityId
    sequence_no: int
    status: EbookRenameRunStatus
    occurred_at: datetime
    fence_epoch: int
    finding_code: str | None = None
    confirmation_digest: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_id, EntityId)
            or not _positive_int(self.sequence_no)
            or self.sequence_no > MAX_EBOOK_RENAME_EVENTS
            or not isinstance(self.status, EbookRenameRunStatus)
            or not _positive_int(self.fence_epoch)
            or (self.sequence_no == 1) != (self.status is EbookRenameRunStatus.PREPARED)
        ):
            _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)
        object.__setattr__(
            self,
            "occurred_at",
            _utc(self.occurred_at, EbookRenameAuthorityErrorCode.EVENT_INVALID),
        )
        if self.finding_code is not None and _FINDING_CODE.fullmatch(
            self.finding_code
        ) is None:
            _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)
        if self.status is EbookRenameRunStatus.PREPARED:
            if self.confirmation_digest is None:
                _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)
            _sha256(
                self.confirmation_digest,
                EbookRenameAuthorityErrorCode.EVENT_INVALID,
            )
        elif self.confirmation_digest is not None:
            _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)


def build_ebook_rename_capability_probe(
    capability: ResolvedEbookRenameCapability,
    *,
    filesystem_type: str,
    filesystem_identity_fingerprint: str,
    kernel_release: str,
    probed_at: datetime,
    openat2_supported: bool,
    renameat2_noreplace_supported: bool,
    directory_fsync_supported: bool,
    root_probe_same_filesystem: bool,
) -> EbookRenameCapabilityProbeSnapshot:
    if not isinstance(capability, ResolvedEbookRenameCapability):
        _fail(EbookRenameAuthorityErrorCode.CAPABILITY_INVALID)
    probe_time = _utc(probed_at, EbookRenameAuthorityErrorCode.PROBE_INVALID)
    material = {
        "ebook_rename_capability_id": capability.ebook_rename_capability_id,
        "scan_root_id": capability.scan_root_id,
        "capability_configuration_fingerprint": capability.configuration_fingerprint,
        "filesystem_type": filesystem_type,
        "filesystem_identity_fingerprint": filesystem_identity_fingerprint,
        "kernel_release": kernel_release,
        "probed_at": probe_time,
        "openat2_supported": openat2_supported,
        "renameat2_noreplace_supported": renameat2_noreplace_supported,
        "directory_fsync_supported": directory_fsync_supported,
        "root_probe_same_filesystem": root_probe_same_filesystem,
    }
    content_hash = _hash(_PROBE_DOMAIN, material)
    return EbookRenameCapabilityProbeSnapshot(
        id=_probe_id(content_hash),
        ebook_rename_capability_id=capability.ebook_rename_capability_id,
        scan_root_id=capability.scan_root_id,
        capability_configuration_fingerprint=capability.configuration_fingerprint,
        filesystem_type=filesystem_type,
        filesystem_identity_fingerprint=filesystem_identity_fingerprint,
        kernel_release=kernel_release,
        probed_at=probe_time,
        openat2_supported=openat2_supported,
        renameat2_noreplace_supported=renameat2_noreplace_supported,
        directory_fsync_supported=directory_fsync_supported,
        root_probe_same_filesystem=root_probe_same_filesystem,
        content_hash=content_hash,
    )


def build_ebook_rename_physical_evidence(
    plan: EbookOperationRecipePlan,
    *,
    source_device: int,
    source_inode: int,
    source_mode: int,
    source_uid: int,
    source_gid: int,
    source_link_count: int,
    source_size_bytes: int,
    source_mtime_ns: int,
    source_modified_at: datetime,
    source_full_sha256: str,
    source_xattr_fingerprint: str,
    target_physically_absent: bool,
    target_historically_absent: bool,
    captured_at: datetime,
) -> EbookRenamePhysicalPreparationEvidence:
    _validate_plan(plan)
    source = plan.candidate.sources[0]
    target = plan.candidate.target
    captured = _utc(
        captured_at,
        EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID,
    )
    if type(target_physically_absent) is not bool or type(target_historically_absent) is not bool:
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    if not target_physically_absent or not target_historically_absent:
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    target_absence = _hash(
        _TARGET_ABSENCE_DOMAIN,
        {
            "scan_root_id": source.scan_root_id,
            "target_locator_digest": ebook_rename_locator_digest(
                source.scan_root_id,
                target.relative_locator,
                target=True,
            ),
            "target_state_fingerprint": target.target_state_fingerprint,
            "physically_absent": True,
            "historically_absent": True,
            "captured_at": captured,
        },
    )
    return EbookRenamePhysicalPreparationEvidence(
        scan_root_id=source.scan_root_id,
        file_id=source.file_id,
        observation_id=source.observation_id,
        source_locator_digest=ebook_rename_locator_digest(
            source.scan_root_id,
            source.relative_locator,
            target=False,
        ),
        target_locator_digest=ebook_rename_locator_digest(
            source.scan_root_id,
            target.relative_locator,
            target=True,
        ),
        source_device=source_device,
        source_inode=source_inode,
        source_mode=source_mode,
        source_uid=source_uid,
        source_gid=source_gid,
        source_link_count=source_link_count,
        source_size_bytes=source_size_bytes,
        source_mtime_ns=source_mtime_ns,
        source_modified_at=source_modified_at,
        source_full_sha256=source_full_sha256,
        source_xattr_fingerprint=source_xattr_fingerprint,
        source_format_label=source.format_label,
        target_state_fingerprint=target.target_state_fingerprint,
        target_absence_fingerprint=target_absence,
        captured_at=captured,
    )


def build_ebook_rename_preparation(
    plan: EbookOperationRecipePlan,
    physical: EbookRenamePhysicalPreparationEvidence,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    dependency_scope: ResolvedEbookRenameDependencyScope,
    preparation_lease: EbookRenameLeaseSnapshot,
    *,
    authorized_at: datetime,
    prepared_at: datetime,
) -> EbookRenamePreparationSnapshot:
    _validate_plan(plan)
    if not isinstance(physical, EbookRenamePhysicalPreparationEvidence):
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    if not isinstance(capability, ResolvedEbookRenameCapability):
        _fail(EbookRenameAuthorityErrorCode.CAPABILITY_INVALID)
    if not isinstance(probe, EbookRenameCapabilityProbeSnapshot):
        _fail(EbookRenameAuthorityErrorCode.PROBE_INVALID)
    if (
        not isinstance(dependency_scope, ResolvedEbookRenameDependencyScope)
        or dependency_scope.scan_root_id != plan.candidate.sources[0].scan_root_id
    ):
        _fail(EbookRenameAuthorityErrorCode.DEPENDENCY_SCOPE_INVALID)
    try:
        dependency_scope_material_fingerprint = (
            ebook_rename_dependency_scope_material_fingerprint(dependency_scope)
        )
    except (TypeError, ValueError, RuntimeError):
        _fail(EbookRenameAuthorityErrorCode.DEPENDENCY_SCOPE_INVALID)
    source = plan.candidate.sources[0]
    review = plan.review
    for axis, dependency in zip(
        dependency_scope.axes,
        plan.candidate.dependencies,
        strict=True,
    ):
        if axis.mode is EbookRenameDependencyScopeMode.NOT_APPLICABLE:
            expected = ebook_rename_dependency_axis_material_fingerprint(
                scope_material_fingerprint=(
                    dependency_scope_material_fingerprint
                ),
                scan_root_id=source.scan_root_id,
                source_scan_run_id=source.source_scan_run_id,
                observation_id=source.observation_id,
                kind=axis.kind,
                state=EbookOperationDependencyState.NOT_APPLICABLE,
                snapshot_kind=EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
                snapshot_id=source.observation_id,
                snapshot_material=dependency_scope_material_fingerprint,
            )
            if (
                dependency.kind is not axis.kind
                or dependency.state
                is not EbookOperationDependencyState.NOT_APPLICABLE
                or dependency.snapshot_kind
                != EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE
                or dependency.snapshot_id != source.observation_id
                or dependency.material_fingerprint != expected
            ):
                _fail(EbookRenameAuthorityErrorCode.DEPENDENCY_SCOPE_INVALID)
        elif (
            dependency.kind is not axis.kind
            or dependency.state is not EbookOperationDependencyState.KNOWN_NONE
            or dependency.snapshot_kind == EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE
        ):
            _fail(EbookRenameAuthorityErrorCode.DEPENDENCY_SCOPE_INVALID)
    if (
        review.review_item_id is None
        or review.decision_id is None
        or review.decision_sequence_no is None
    ):
        _fail(EbookRenameAuthorityErrorCode.PLAN_INVALID)
    if (
        physical.scan_root_id != source.scan_root_id
        or physical.file_id != source.file_id
        or physical.observation_id != source.observation_id
        or physical.source_locator_digest
        != ebook_rename_locator_digest(source.scan_root_id, source.relative_locator, target=False)
        or physical.target_locator_digest
        != ebook_rename_locator_digest(
            source.scan_root_id,
            plan.candidate.target.relative_locator,
            target=True,
        )
        or physical.source_format_label != source.format_label
        or physical.source_full_sha256 != source.expected_full_sha256
        or physical.source_size_bytes != source.expected_size_bytes
        or physical.source_modified_at != source.expected_modified_at
        or physical.target_state_fingerprint
        != plan.candidate.target.target_state_fingerprint
        or physical.target_absence_fingerprint
        != _hash(
            _TARGET_ABSENCE_DOMAIN,
            {
                "scan_root_id": source.scan_root_id,
                "target_locator_digest": physical.target_locator_digest,
                "target_state_fingerprint": physical.target_state_fingerprint,
                "physically_absent": True,
                "historically_absent": True,
                "captured_at": physical.captured_at,
            },
        )
    ):
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    if (
        capability.scan_root_id != source.scan_root_id
        or capability.writer_profile != EBOOK_RENAME_PROCESSOR_PROFILE
        or probe.ebook_rename_capability_id != capability.ebook_rename_capability_id
        or probe.scan_root_id != capability.scan_root_id
        or probe.capability_configuration_fingerprint
        != capability.configuration_fingerprint
    ):
        _fail(EbookRenameAuthorityErrorCode.CAPABILITY_INVALID)
    authorized = _second_utc(
        authorized_at,
        EbookRenameAuthorityErrorCode.PREPARATION_INVALID,
    )
    prepared = _utc(prepared_at, EbookRenameAuthorityErrorCode.PREPARATION_INVALID)
    if (
        not isinstance(preparation_lease, EbookRenameLeaseSnapshot)
        or _lease_owner_kind(preparation_lease) != "EBOOK_RENAME_PREPARATION"
        or not isinstance(preparation_lease.owner_run_id, EntityId)
        or preparation_lease.scan_root_id != source.scan_root_id
        or not _positive_int(preparation_lease.fence_epoch)
        or not _aware_datetime(preparation_lease.acquired_at)
        or not _aware_datetime(preparation_lease.lease_expires_at)
        or preparation_lease.acquired_at > authorized
        or prepared < authorized
        or preparation_lease.lease_expires_at <= prepared
        or probe.probed_at > prepared
        or physical.captured_at > prepared
    ):
        _fail(EbookRenameAuthorityErrorCode.LEASE_INVALID)
    dependencies_fingerprint = ebook_rename_dependencies_fingerprint(plan)
    material = {
        "preparation_owner_id": preparation_lease.owner_run_id,
        "preparation_fence_epoch": preparation_lease.fence_epoch,
        "plan_id": plan.id,
        "plan_content_hash": plan.content_hash,
        "candidate_id": plan.candidate.id,
        "candidate_content_hash": plan.candidate.content_hash,
        "scan_root_id": source.scan_root_id,
        "source_scan_run_id": source.source_scan_run_id,
        "source_file_id": source.file_id,
        "source_observation_id": source.observation_id,
        "source_locator_digest": physical.source_locator_digest,
        "target_locator_digest": physical.target_locator_digest,
        "source_format_label": physical.source_format_label,
        "source_full_sha256": physical.source_full_sha256,
        "source_size_bytes": physical.source_size_bytes,
        "source_modified_at": physical.source_modified_at,
        "source_device": physical.source_device,
        "source_inode": physical.source_inode,
        "source_mode": physical.source_mode,
        "source_uid": physical.source_uid,
        "source_gid": physical.source_gid,
        "source_link_count": physical.source_link_count,
        "source_mtime_ns": physical.source_mtime_ns,
        "source_xattr_fingerprint": physical.source_xattr_fingerprint,
        "target_state_fingerprint": physical.target_state_fingerprint,
        "target_absence_fingerprint": physical.target_absence_fingerprint,
        "dependency_scope_id": dependency_scope.dependency_scope_id,
        "dependency_scope_material_fingerprint": dependency_scope_material_fingerprint,
        "dependencies_fingerprint": dependencies_fingerprint,
        "review_item_id": review.review_item_id,
        "review_decision_id": review.decision_id,
        "review_decision_sequence_no": review.decision_sequence_no,
        "review_evidence_fingerprint": review.evidence_fingerprint,
        "review_candidate_set_fingerprint": review.candidate_set_fingerprint,
        "ebook_rename_capability_id": capability.ebook_rename_capability_id,
        "capability_configuration_fingerprint": capability.configuration_fingerprint,
        "probe_id": probe.id,
        "probe_content_hash": probe.content_hash,
        "authorized_at": authorized,
        "prepared_at": prepared,
    }
    content_hash = _hash(_PREPARATION_DOMAIN, material)
    return EbookRenamePreparationSnapshot(
        id=_preparation_id(content_hash),
        preparation_owner_id=preparation_lease.owner_run_id,
        preparation_fence_epoch=preparation_lease.fence_epoch,
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        candidate_id=plan.candidate.id,
        candidate_content_hash=plan.candidate.content_hash,
        scan_root_id=source.scan_root_id,
        source_scan_run_id=source.source_scan_run_id,
        source_file_id=source.file_id,
        source_observation_id=source.observation_id,
        source_locator_digest=physical.source_locator_digest,
        target_locator_digest=physical.target_locator_digest,
        source_format_label=physical.source_format_label,
        source_full_sha256=physical.source_full_sha256,
        source_size_bytes=physical.source_size_bytes,
        source_modified_at=physical.source_modified_at,
        source_device=physical.source_device,
        source_inode=physical.source_inode,
        source_mode=physical.source_mode,
        source_uid=physical.source_uid,
        source_gid=physical.source_gid,
        source_link_count=physical.source_link_count,
        source_mtime_ns=physical.source_mtime_ns,
        source_xattr_fingerprint=physical.source_xattr_fingerprint,
        target_state_fingerprint=physical.target_state_fingerprint,
        target_absence_fingerprint=physical.target_absence_fingerprint,
        dependency_scope_id=dependency_scope.dependency_scope_id,
        dependency_scope_material_fingerprint=dependency_scope_material_fingerprint,
        dependencies_fingerprint=dependencies_fingerprint,
        review_item_id=review.review_item_id,
        review_decision_id=review.decision_id,
        review_decision_sequence_no=review.decision_sequence_no,
        review_evidence_fingerprint=review.evidence_fingerprint,
        review_candidate_set_fingerprint=review.candidate_set_fingerprint,
        ebook_rename_capability_id=capability.ebook_rename_capability_id,
        capability_configuration_fingerprint=capability.configuration_fingerprint,
        probe_id=probe.id,
        probe_content_hash=probe.content_hash,
        authorized_at=authorized,
        prepared_at=prepared,
        content_hash=content_hash,
    )


def build_ebook_rename_authorization(
    preparation: EbookRenamePreparationSnapshot,
    *,
    expires_at: datetime,
) -> EbookRenameAuthorizationSnapshot:
    if not isinstance(preparation, EbookRenamePreparationSnapshot):
        _fail(EbookRenameAuthorityErrorCode.PREPARATION_INVALID)
    expires = _utc(
        expires_at,
        EbookRenameAuthorityErrorCode.AUTHORIZATION_WINDOW_INVALID,
    )
    _validate_window(preparation.authorized_at, preparation.prepared_at, expires)
    material = {
        "preparation_id": preparation.id,
        "preparation_content_hash": preparation.content_hash,
        "plan_id": preparation.plan_id,
        "plan_content_hash": preparation.plan_content_hash,
        "candidate_id": preparation.candidate_id,
        "scan_root_id": preparation.scan_root_id,
        "source_file_id": preparation.source_file_id,
        "ebook_rename_capability_id": preparation.ebook_rename_capability_id,
        "capability_configuration_fingerprint": (
            preparation.capability_configuration_fingerprint
        ),
        "probe_id": preparation.probe_id,
        "probe_content_hash": preparation.probe_content_hash,
        "authorized_at": preparation.authorized_at,
        "prepared_at": preparation.prepared_at,
        "expires_at": expires,
    }
    content_hash = _hash(_AUTHORIZATION_DOMAIN, material)
    return EbookRenameAuthorizationSnapshot(
        id=_authorization_id(content_hash),
        preparation_id=preparation.id,
        preparation_content_hash=preparation.content_hash,
        plan_id=preparation.plan_id,
        plan_content_hash=preparation.plan_content_hash,
        candidate_id=preparation.candidate_id,
        scan_root_id=preparation.scan_root_id,
        source_file_id=preparation.source_file_id,
        ebook_rename_capability_id=preparation.ebook_rename_capability_id,
        capability_configuration_fingerprint=(
            preparation.capability_configuration_fingerprint
        ),
        probe_id=preparation.probe_id,
        probe_content_hash=preparation.probe_content_hash,
        authorized_at=preparation.authorized_at,
        prepared_at=preparation.prepared_at,
        expires_at=expires,
        content_hash=content_hash,
    )


def build_ebook_rename_run(
    authorization: EbookRenameAuthorizationSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    lease: EbookRenameLeaseSnapshot,
    *,
    run_id: EntityId,
    created_at: datetime,
) -> EbookRenameExecutionRun:
    if not isinstance(authorization, EbookRenameAuthorizationSnapshot):
        _fail(EbookRenameAuthorityErrorCode.AUTHORIZATION_INVALID)
    created = _utc(created_at, EbookRenameAuthorityErrorCode.RUN_INVALID)
    if not authorization.authorized_at <= created < authorization.expires_at:
        _fail(EbookRenameAuthorityErrorCode.AUTHORIZATION_WINDOW_INVALID)
    if (
        not isinstance(capability, ResolvedEbookRenameCapability)
        or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
        or capability.ebook_rename_capability_id
        != authorization.ebook_rename_capability_id
        or capability.scan_root_id != authorization.scan_root_id
        or capability.configuration_fingerprint
        != authorization.capability_configuration_fingerprint
        or probe.id != authorization.probe_id
        or probe.content_hash != authorization.probe_content_hash
        or probe.capability_configuration_fingerprint
        != capability.configuration_fingerprint
    ):
        _fail(EbookRenameAuthorityErrorCode.CAPABILITY_INVALID)
    if (
        not isinstance(run_id, EntityId)
        or not isinstance(lease, EbookRenameLeaseSnapshot)
        or _lease_owner_kind(lease) != "EBOOK_RENAME_RUN"
        or lease.owner_run_id != run_id
        or lease.scan_root_id != authorization.scan_root_id
        or not _positive_int(lease.fence_epoch)
        or not _aware_datetime(lease.acquired_at)
        or not _aware_datetime(lease.lease_expires_at)
        or lease.acquired_at > created
        or lease.lease_expires_at <= created
    ):
        _fail(EbookRenameAuthorityErrorCode.LEASE_INVALID)
    return EbookRenameExecutionRun(
        id=run_id,
        authorization_id=authorization.id,
        authorization_content_hash=authorization.content_hash,
        plan_id=authorization.plan_id,
        scan_root_id=authorization.scan_root_id,
        source_file_id=authorization.source_file_id,
        ebook_rename_capability_id=authorization.ebook_rename_capability_id,
        probe_id=authorization.probe_id,
        initial_fence_epoch=lease.fence_epoch,
        created_at=created,
    )


def build_ebook_rename_backend_binding(
    run: EbookRenameExecutionRun,
    authorization: EbookRenameAuthorizationSnapshot,
    probe: EbookRenameCapabilityProbeSnapshot,
    *,
    bound_at: datetime,
) -> EbookRenameBackendBinding:
    if (
        not isinstance(run, EbookRenameExecutionRun)
        or not isinstance(authorization, EbookRenameAuthorizationSnapshot)
        or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
        or run.authorization_id != authorization.id
        or run.ebook_rename_capability_id != authorization.ebook_rename_capability_id
        or run.probe_id != probe.id
        or probe.content_hash != authorization.probe_content_hash
    ):
        _fail(EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)
    bound = _utc(bound_at, EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)
    if bound < run.created_at:
        _fail(EbookRenameAuthorityErrorCode.BACKEND_BINDING_INVALID)
    material = {
        "run_id": run.id,
        "ebook_rename_capability_id": authorization.ebook_rename_capability_id,
        "capability_configuration_fingerprint": (
            authorization.capability_configuration_fingerprint
        ),
        "probe_id": probe.id,
        "probe_content_hash": probe.content_hash,
        "bound_at": bound,
        "backend_profile": EBOOK_RENAME_PROCESSOR_PROFILE,
        "probe_profile": EBOOK_RENAME_PROBE_PROFILE,
    }
    return EbookRenameBackendBinding(
        run_id=run.id,
        ebook_rename_capability_id=authorization.ebook_rename_capability_id,
        capability_configuration_fingerprint=(
            authorization.capability_configuration_fingerprint
        ),
        probe_id=probe.id,
        probe_content_hash=probe.content_hash,
        bound_at=bound,
        content_hash=_hash(_BACKEND_BINDING_DOMAIN, material),
    )


def validate_ebook_rename_event_history(
    events: tuple[EbookRenameExecutionEvent, ...],
) -> None:
    if (
        not events
        or len(events) > MAX_EBOOK_RENAME_EVENTS
        or tuple(event.sequence_no for event in events)
        != tuple(range(1, len(events) + 1))
        or any(event.run_id != events[0].run_id for event in events)
        or events[0].status is not EbookRenameRunStatus.PREPARED
    ):
        _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)
    for previous, current in zip(events, events[1:], strict=False):
        if current.status not in _TRANSITIONS.get(previous.status, frozenset()):
            _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)
        if current.occurred_at < previous.occurred_at:
            _fail(EbookRenameAuthorityErrorCode.EVENT_INVALID)


def ebook_rename_locator_digest(
    scan_root_id: EntityId,
    relative_locator: str,
    *,
    target: bool,
) -> str:
    if not isinstance(scan_root_id, EntityId) or not isinstance(relative_locator, str):
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    path = PurePosixPath(relative_locator)
    if (
        not relative_locator
        or path.is_absolute()
        or path.as_posix() != relative_locator
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(relative_locator.encode("utf-8")) > 1024
    ):
        _fail(EbookRenameAuthorityErrorCode.PHYSICAL_EVIDENCE_INVALID)
    domain = _LOCATOR_TARGET_DOMAIN if target else _LOCATOR_SOURCE_DOMAIN
    return hashlib.sha256(
        domain + str(scan_root_id).encode("ascii") + b"\x00" + relative_locator.encode("utf-8")
    ).hexdigest()


def ebook_rename_dependencies_fingerprint(plan: EbookOperationRecipePlan) -> str:
    _validate_plan(plan)
    material = [
        {
            "kind": value.kind.value,
            "state": value.state.value,
            "snapshot_kind": value.snapshot_kind,
            "snapshot_id": value.snapshot_id,
            "material_fingerprint": value.material_fingerprint,
        }
        for value in plan.candidate.dependencies
    ]
    return _hash(_DEPENDENCIES_DOMAIN, material)


def _validate_plan(plan: EbookOperationRecipePlan) -> None:
    if not isinstance(plan, EbookOperationRecipePlan):
        _fail(EbookRenameAuthorityErrorCode.PLAN_INVALID)
    candidate = plan.candidate
    source = candidate.sources[0] if candidate.sources else None
    expected_dependencies = set(EbookOperationDependencyKind)
    if (
        plan.id != ebook_operation_recipe_plan_id(
            ebook_operation_recipe_plan_content_hash(plan)
        )
        or plan.content_hash != ebook_operation_recipe_plan_content_hash(plan)
        or candidate.id
        != ebook_operation_recipe_candidate_id(
            ebook_operation_recipe_candidate_content_hash(candidate)
        )
        or candidate.content_hash
        != ebook_operation_recipe_candidate_content_hash(candidate)
        or candidate.operation_kind is not EbookOperationKind.FILE_RENAME
        or plan.status is not EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
        or plan.execution_state is not EbookOperationExecutionState.NOT_EXECUTABLE
        or plan.blockers
        or len(candidate.sources) != 1
        or source is None
        or source.role is not EbookOperationSourceRole.PRIMARY
        or candidate.target.kind is not EbookOperationTargetKind.MANAGED_SCAN_ROOT_FILE
        or candidate.target.scope_id != source.scan_root_id
        or candidate.expected_output.identity_kind
        is not EbookOperationOutputIdentityKind.BYTE_IDENTICAL_TO_PRIMARY
        or candidate.expected_output.format_label != source.format_label
        or candidate.expected_output.expected_full_sha256 != source.expected_full_sha256
        or candidate.expected_output.expected_size_bytes != source.expected_size_bytes
        or candidate.collision_policy
        is not EbookOperationCollisionPolicy.REQUIRE_TARGET_ABSENT
        or candidate.workspace_mode is not EbookOperationWorkspaceMode.NOT_REQUIRED
        or candidate.recovery_mode is not EbookOperationRecoveryMode.REVERSE_RELOCATION
        or candidate.processor_requirement.kind
        is not EbookOperationProcessorKind.FOLIOTONE_NATIVE
        or candidate.processor_requirement.processor_profile
        != EBOOK_RENAME_PROCESSOR_PROFILE
        or {value.kind for value in candidate.dependencies} != expected_dependencies
        or any(
            value.state
            not in {
                EbookOperationDependencyState.KNOWN_NONE,
                EbookOperationDependencyState.NOT_APPLICABLE,
            }
            for value in candidate.dependencies
        )
        or plan.review.state is not EbookOperationReviewState.ACCEPTED
        or plan.review.review_item_id is None
        or plan.review.decision_id is None
        or plan.review.decision_sequence_no is None
        or plan.review.evidence_fingerprint != candidate.evidence_fingerprint
        or plan.review.candidate_set_fingerprint != candidate.content_hash
    ):
        _fail(EbookRenameAuthorityErrorCode.PLAN_INVALID)
    source_parent = PurePosixPath(source.relative_locator).parent
    target_parent = PurePosixPath(candidate.target.relative_locator).parent
    if source_parent != target_parent:
        _fail(EbookRenameAuthorityErrorCode.PLAN_INVALID)


def _probe_content_hash(value: EbookRenameCapabilityProbeSnapshot) -> str:
    return _hash(
        _PROBE_DOMAIN,
        {
            "ebook_rename_capability_id": value.ebook_rename_capability_id,
            "scan_root_id": value.scan_root_id,
            "capability_configuration_fingerprint": (
                value.capability_configuration_fingerprint
            ),
            "filesystem_type": value.filesystem_type,
            "filesystem_identity_fingerprint": value.filesystem_identity_fingerprint,
            "kernel_release": value.kernel_release,
            "probed_at": value.probed_at,
            "openat2_supported": value.openat2_supported,
            "renameat2_noreplace_supported": value.renameat2_noreplace_supported,
            "directory_fsync_supported": value.directory_fsync_supported,
            "root_probe_same_filesystem": value.root_probe_same_filesystem,
        },
    )


def _preparation_content_hash(value: EbookRenamePreparationSnapshot) -> str:
    return _hash(
        _PREPARATION_DOMAIN,
        {
            name: getattr(value, name)
            for name in (
                "preparation_owner_id",
                "preparation_fence_epoch",
                "plan_id",
                "plan_content_hash",
                "candidate_id",
                "candidate_content_hash",
                "scan_root_id",
                "source_scan_run_id",
                "source_file_id",
                "source_observation_id",
                "source_locator_digest",
                "target_locator_digest",
                "source_format_label",
                "source_full_sha256",
                "source_size_bytes",
                "source_modified_at",
                "source_device",
                "source_inode",
                "source_mode",
                "source_uid",
                "source_gid",
                "source_link_count",
                "source_mtime_ns",
                "source_xattr_fingerprint",
                "target_state_fingerprint",
                "target_absence_fingerprint",
                "dependency_scope_id",
                "dependency_scope_material_fingerprint",
                "dependencies_fingerprint",
                "review_item_id",
                "review_decision_id",
                "review_decision_sequence_no",
                "review_evidence_fingerprint",
                "review_candidate_set_fingerprint",
                "ebook_rename_capability_id",
                "capability_configuration_fingerprint",
                "probe_id",
                "probe_content_hash",
                "authorized_at",
                "prepared_at",
            )
        },
    )


def _authorization_content_hash(value: EbookRenameAuthorizationSnapshot) -> str:
    return _hash(
        _AUTHORIZATION_DOMAIN,
        {
            name: getattr(value, name)
            for name in (
                "preparation_id",
                "preparation_content_hash",
                "plan_id",
                "plan_content_hash",
                "candidate_id",
                "scan_root_id",
                "source_file_id",
                "ebook_rename_capability_id",
                "capability_configuration_fingerprint",
                "probe_id",
                "probe_content_hash",
                "authorized_at",
                "prepared_at",
                "expires_at",
            )
        },
    )


def _backend_binding_content_hash(value: EbookRenameBackendBinding) -> str:
    return _hash(
        _BACKEND_BINDING_DOMAIN,
        {
            "run_id": value.run_id,
            "ebook_rename_capability_id": value.ebook_rename_capability_id,
            "capability_configuration_fingerprint": (
                value.capability_configuration_fingerprint
            ),
            "probe_id": value.probe_id,
            "probe_content_hash": value.probe_content_hash,
            "bound_at": value.bound_at,
            "backend_profile": value.backend_profile,
            "probe_profile": value.probe_profile,
        },
    )


def _hash(domain: bytes, material: object) -> str:
    return hashlib.sha256(domain + _canonical_json(material)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: object) -> object:
    if isinstance(value, EntityId):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError("unsupported canonical value")


def _preparation_id(content_hash: str) -> EntityId:
    return EntityId(uuid5(_PREPARATION_NAMESPACE, content_hash))


def _authorization_id(content_hash: str) -> EntityId:
    return EntityId(uuid5(_AUTHORIZATION_NAMESPACE, content_hash))


def _probe_id(content_hash: str) -> EntityId:
    return EntityId(uuid5(_PROBE_NAMESPACE, content_hash))


def _validate_window(
    authorized_at: datetime,
    prepared_at: datetime,
    expires_at: datetime,
) -> None:
    if (
        prepared_at < authorized_at
        or expires_at <= prepared_at
        or expires_at - authorized_at > MAX_EBOOK_RENAME_AUTHORIZATION_LIFETIME
    ):
        _fail(EbookRenameAuthorityErrorCode.AUTHORIZATION_WINDOW_INVALID)


def _lease_owner_kind(value: EbookRenameLeaseSnapshot) -> str | None:
    raw = value.owner_kind
    return raw if isinstance(raw, str) else getattr(raw, "value", None)


def _aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _sha256(value: str, code: EbookRenameAuthorityErrorCode) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _technical(value: str, code: EbookRenameAuthorityErrorCode) -> str:
    if not isinstance(value, str) or _TECHNICAL_TEXT.fullmatch(value) is None:
        _fail(code)
    return value


def _format_label(value: str, code: EbookRenameAuthorityErrorCode) -> str:
    if value not in {"EPUB", "MOBI", "AZW", "AZW3", "PDF"}:
        _fail(code)
    return value


def _positive_int(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 < value <= 2**63 - 1
    )


def _nonnegative_int(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 <= value <= 2**63 - 1
    )


def _signed_64_int(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and -(2**63) <= value <= 2**63 - 1
    )


def _utc(value: datetime, code: EbookRenameAuthorityErrorCode) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _fail(code)
    return value.astimezone(UTC)


def _second_utc(value: datetime, code: EbookRenameAuthorityErrorCode) -> datetime:
    normalized = _utc(value, code)
    if normalized.microsecond != 0:
        _fail(code)
    return normalized


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "EBOOK_RENAME_ALLOWED_FILESYSTEMS",
    "EBOOK_RENAME_AUTHORIZATION_PROFILE",
    "EBOOK_RENAME_PLATFORM_PROFILE",
    "EBOOK_RENAME_PREPARATION_PROFILE",
    "EBOOK_RENAME_PROBE_PROFILE",
    "EBOOK_RENAME_RUN_PROFILE",
    "MAX_EBOOK_RENAME_AUTHORIZATION_LIFETIME",
    "MAX_EBOOK_RENAME_EVENTS",
    "EbookRenameAuthorityError",
    "EbookRenameAuthorityErrorCode",
    "EbookRenameAuthorizationSnapshot",
    "EbookRenameBackendBinding",
    "EbookRenameCapabilityProbeSnapshot",
    "EbookRenameExecutionEvent",
    "EbookRenameExecutionRun",
    "EbookRenameLeaseSnapshot",
    "EbookRenamePhysicalPreparationEvidence",
    "EbookRenamePreparationSnapshot",
    "EbookRenameRunStatus",
    "build_ebook_rename_authorization",
    "build_ebook_rename_backend_binding",
    "build_ebook_rename_capability_probe",
    "build_ebook_rename_physical_evidence",
    "build_ebook_rename_preparation",
    "build_ebook_rename_run",
    "ebook_rename_dependencies_fingerprint",
    "ebook_rename_locator_digest",
    "validate_ebook_rename_event_history",
]
