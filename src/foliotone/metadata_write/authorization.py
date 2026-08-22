"""Path-free preparation, authorization, run, and event contracts for MW03."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid5

from foliotone.core import EntityId
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.metadata_write.capabilities import ResolvedMetadataWriteCapability
from foliotone.metadata_write.contracts import (
    EPUB_TITLE_PATCHER_VERSION,
    EPUB_TITLE_WRITE_PROFILE,
    MAX_EPUB_ARCHIVE_BYTES,
    EpubTitlePackagePatch,
    EpubTitleWritePreflight,
)
from foliotone.metadata_write.epub_title import (
    build_epub3_title_package_patch,
    validate_epub3_title_package_patch,
    validate_epub3_title_write_plan,
)
from foliotone.metadata_write.staging import EPUB_TITLE_STAGING_PROFILE
from foliotone.metadata_write.validation import (
    EPUB_TITLE_VALIDATION_PROFILE,
    EPUB_TITLE_VALIDATOR_SET,
    EpubTitleVerifiedStage,
)

METADATA_WRITE_PREPARATION_PROFILE: Final = "metadata-write-preparation/v1"
METADATA_WRITE_AUTHORIZATION_PROFILE: Final = "metadata-write-authorization/v1"
METADATA_WRITE_RUN_PROFILE: Final = "metadata-write-run/v1"
MAX_METADATA_WRITE_AUTHORIZATION_LIFETIME: Final = timedelta(minutes=15)
MAX_METADATA_WRITE_EVENTS: Final = 16

_PREPARATION_DOMAIN: Final = b"foliotone:metadata-write-preparation/v1\x00"
_AUTHORIZATION_DOMAIN: Final = b"foliotone:metadata-write-authorization/v1\x00"
_PREPARATION_NAMESPACE: Final = UUID("6b2e3d0b-5b43-5fa4-a997-68582b10d21c")
_AUTHORIZATION_NAMESPACE: Final = UUID("04f2f973-7db8-50dc-81af-691e669249d9")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MODIFIED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


@runtime_checkable
class MetadataWriteLeaseSnapshot(Protocol):
    """Persistence-neutral root-lease evidence required by the W10 contract."""

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


class MetadataWriteAuthorizationErrorCode(StrEnum):
    """Fixed path- and metadata-free contract failure codes."""

    PLAN_INVALID = "PLAN_INVALID"
    PREPARATION_INVALID = "PREPARATION_INVALID"
    CAPABILITY_INVALID = "CAPABILITY_INVALID"
    LEASE_INVALID = "LEASE_INVALID"
    AUTHORIZATION_WINDOW_INVALID = "AUTHORIZATION_WINDOW_INVALID"
    AUTHORIZATION_INVALID = "AUTHORIZATION_INVALID"
    RUN_INVALID = "RUN_INVALID"
    EVENT_INVALID = "EVENT_INVALID"


class MetadataWriteAuthorizationError(ValueError):
    """One fixed-code failure without paths, hashes, or metadata values."""

    def __init__(self, code: MetadataWriteAuthorizationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class MetadataWriteRunStatus(StrEnum):
    """Append-only phases and terminal outcomes for the future executor."""

    CREATED = "CREATED"
    PREPARED = "PREPARED"
    EXCHANGED = "EXCHANGED"
    ORIGINAL_PRESERVED = "ORIGINAL_PRESERVED"
    VERIFIED = "VERIFIED"
    RECOVERED = "RECOVERED"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"
    STALE = "STALE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FENCED_OUT = "FENCED_OUT"
    CANCELLED = "CANCELLED"


def _fail(code: MetadataWriteAuthorizationErrorCode) -> NoReturn:
    raise MetadataWriteAuthorizationError(code)


@dataclass(frozen=True, slots=True)
class EpubTitleWritePreparationSnapshot:
    """Verified private output plus the short-lived preparation fence evidence."""

    id: EntityId
    preparation_owner_id: EntityId
    preparation_fence_epoch: int
    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    source_sha256: str = field(repr=False)
    source_size_bytes: int
    expected_output_sha256: str = field(repr=False)
    expected_output_size_bytes: int
    metadata_write_capability_id: EntityId
    dcterms_modified: str = field(repr=False)
    authorized_at: datetime
    prepared_at: datetime
    metadata_tool_version: str
    epubcheck_tool_version: str
    text_tool_version: str
    cover_tool_version: str
    validator_set_fingerprint: str = field(repr=False)
    content_hash: str = field(repr=False)
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    staging_profile: str = EPUB_TITLE_STAGING_PROFILE
    validation_profile: str = EPUB_TITLE_VALIDATION_PROFILE
    validator_set: str = EPUB_TITLE_VALIDATOR_SET
    profile: str = METADATA_WRITE_PREPARATION_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_WRITE_PREPARATION_PROFILE:
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.id,
                self.preparation_owner_id,
                self.plan_id,
                self.scan_root_id,
                self.file_id,
                self.observation_id,
                self.metadata_write_capability_id,
            )
        ):
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        if (
            isinstance(self.preparation_fence_epoch, bool)
            or not isinstance(self.preparation_fence_epoch, int)
            or self.preparation_fence_epoch <= 0
            or isinstance(self.source_size_bytes, bool)
            or not isinstance(self.source_size_bytes, int)
            or self.source_size_bytes <= 0
            or self.source_size_bytes > MAX_EPUB_ARCHIVE_BYTES
            or isinstance(self.expected_output_size_bytes, bool)
            or not isinstance(self.expected_output_size_bytes, int)
            or self.expected_output_size_bytes <= 0
            or self.expected_output_size_bytes > MAX_EPUB_ARCHIVE_BYTES
        ):
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        for value in (
            self.plan_content_hash,
            self.source_sha256,
            self.expected_output_sha256,
            self.validator_set_fingerprint,
            self.content_hash,
        ):
            _require_sha256(value, MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        if self.source_sha256 == self.expected_output_sha256:
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        if _MODIFIED.fullmatch(self.dcterms_modified) is None:
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        for value in (
            self.metadata_tool_version,
            self.epubcheck_tool_version,
            self.text_tool_version,
            self.cover_tool_version,
        ):
            _technical_text(value, MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        if (
            self.writer_profile != EPUB_TITLE_WRITE_PROFILE
            or self.patcher_version != EPUB_TITLE_PATCHER_VERSION
            or self.staging_profile != EPUB_TITLE_STAGING_PROFILE
            or self.validation_profile != EPUB_TITLE_VALIDATION_PROFILE
            or self.validator_set != EPUB_TITLE_VALIDATOR_SET
        ):
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        authorized = _second_utc(
            self.authorized_at,
            MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID,
        )
        prepared = _utc(
            self.prepared_at,
            MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID,
        )
        object.__setattr__(self, "authorized_at", authorized)
        object.__setattr__(self, "prepared_at", prepared)
        if prepared < authorized:
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
        expected_hash = _preparation_content_hash(self)
        if self.content_hash != expected_hash or self.id != _preparation_id(expected_hash):
            _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)


@dataclass(frozen=True, slots=True)
class MetadataWriteAuthorizationSnapshot:
    """One-use, content-addressed authority for exactly one verified output."""

    id: EntityId
    preparation_id: EntityId
    preparation_content_hash: str = field(repr=False)
    preparation_owner_id: EntityId
    preparation_fence_epoch: int
    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    source_sha256: str = field(repr=False)
    source_size_bytes: int
    expected_output_sha256: str = field(repr=False)
    expected_output_size_bytes: int
    metadata_write_capability_id: EntityId
    dcterms_modified: str = field(repr=False)
    authorized_at: datetime
    prepared_at: datetime
    expires_at: datetime
    metadata_tool_version: str
    epubcheck_tool_version: str
    text_tool_version: str
    cover_tool_version: str
    validator_set_fingerprint: str = field(repr=False)
    content_hash: str = field(repr=False)
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    staging_profile: str = EPUB_TITLE_STAGING_PROFILE
    validation_profile: str = EPUB_TITLE_VALIDATION_PROFILE
    validator_set: str = EPUB_TITLE_VALIDATOR_SET
    profile: str = METADATA_WRITE_AUTHORIZATION_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_WRITE_AUTHORIZATION_PROFILE:
            _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.id,
                self.preparation_id,
                self.preparation_owner_id,
                self.plan_id,
                self.scan_root_id,
                self.file_id,
                self.observation_id,
                self.metadata_write_capability_id,
            )
        ):
            _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        for value in (
            self.preparation_content_hash,
            self.plan_content_hash,
            self.source_sha256,
            self.expected_output_sha256,
            self.validator_set_fingerprint,
            self.content_hash,
        ):
            _require_sha256(value, MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        if (
            isinstance(self.preparation_fence_epoch, bool)
            or not isinstance(self.preparation_fence_epoch, int)
            or self.preparation_fence_epoch <= 0
            or isinstance(self.source_size_bytes, bool)
            or not isinstance(self.source_size_bytes, int)
            or self.source_size_bytes <= 0
            or self.source_size_bytes > MAX_EPUB_ARCHIVE_BYTES
            or isinstance(self.expected_output_size_bytes, bool)
            or not isinstance(self.expected_output_size_bytes, int)
            or self.expected_output_size_bytes <= 0
            or self.expected_output_size_bytes > MAX_EPUB_ARCHIVE_BYTES
            or self.source_sha256 == self.expected_output_sha256
            or _MODIFIED.fullmatch(self.dcterms_modified) is None
        ):
            _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        for value in (
            self.metadata_tool_version,
            self.epubcheck_tool_version,
            self.text_tool_version,
            self.cover_tool_version,
        ):
            _technical_text(value, MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        if (
            self.writer_profile != EPUB_TITLE_WRITE_PROFILE
            or self.patcher_version != EPUB_TITLE_PATCHER_VERSION
            or self.staging_profile != EPUB_TITLE_STAGING_PROFILE
            or self.validation_profile != EPUB_TITLE_VALIDATION_PROFILE
            or self.validator_set != EPUB_TITLE_VALIDATOR_SET
        ):
            _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
        authorized = _second_utc(
            self.authorized_at,
            MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID,
        )
        prepared = _utc(
            self.prepared_at,
            MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID,
        )
        expires = _utc(
            self.expires_at,
            MetadataWriteAuthorizationErrorCode.AUTHORIZATION_WINDOW_INVALID,
        )
        object.__setattr__(self, "authorized_at", authorized)
        object.__setattr__(self, "prepared_at", prepared)
        object.__setattr__(self, "expires_at", expires)
        _validate_window(authorized, prepared, expires)
        expected_hash = _authorization_content_hash(self)
        if self.content_hash != expected_hash or self.id != _authorization_id(expected_hash):
            _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)


@dataclass(frozen=True, slots=True)
class MetadataWriteExecutionRun:
    """Immutable one-use execution identity; it does not execute filesystem work."""

    id: EntityId
    authorization_id: EntityId
    authorization_content_hash: str = field(repr=False)
    plan_id: EntityId
    scan_root_id: EntityId
    file_id: EntityId
    metadata_write_capability_id: EntityId
    initial_fence_epoch: int
    created_at: datetime
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    profile: str = METADATA_WRITE_RUN_PROFILE

    def __post_init__(self) -> None:
        if (
            self.profile != METADATA_WRITE_RUN_PROFILE
            or self.writer_profile != EPUB_TITLE_WRITE_PROFILE
        ):
            _fail(MetadataWriteAuthorizationErrorCode.RUN_INVALID)
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.id,
                self.authorization_id,
                self.plan_id,
                self.scan_root_id,
                self.file_id,
                self.metadata_write_capability_id,
            )
        ):
            _fail(MetadataWriteAuthorizationErrorCode.RUN_INVALID)
        _require_sha256(
            self.authorization_content_hash,
            MetadataWriteAuthorizationErrorCode.RUN_INVALID,
        )
        if (
            isinstance(self.initial_fence_epoch, bool)
            or not isinstance(self.initial_fence_epoch, int)
            or self.initial_fence_epoch <= 0
        ):
            _fail(MetadataWriteAuthorizationErrorCode.RUN_INVALID)
        object.__setattr__(
            self,
            "created_at",
            _utc(self.created_at, MetadataWriteAuthorizationErrorCode.RUN_INVALID),
        )


@dataclass(frozen=True, slots=True)
class MetadataWriteExecutionEvent:
    """One gapless append-only event bound to an actually held lease fence."""

    run_id: EntityId
    sequence_no: int
    status: MetadataWriteRunStatus
    occurred_at: datetime
    fence_epoch: int
    finding_code: str | None = None
    confirmation_digest: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, EntityId):
            _fail(MetadataWriteAuthorizationErrorCode.EVENT_INVALID)
        if (
            isinstance(self.sequence_no, bool)
            or not isinstance(self.sequence_no, int)
            or self.sequence_no < 1
            or self.sequence_no > MAX_METADATA_WRITE_EVENTS
            or not isinstance(self.status, MetadataWriteRunStatus)
            or isinstance(self.fence_epoch, bool)
            or not isinstance(self.fence_epoch, int)
            or self.fence_epoch <= 0
        ):
            _fail(MetadataWriteAuthorizationErrorCode.EVENT_INVALID)
        object.__setattr__(
            self,
            "occurred_at",
            _utc(self.occurred_at, MetadataWriteAuthorizationErrorCode.EVENT_INVALID),
        )
        if self.finding_code is not None and _FINDING_CODE.fullmatch(self.finding_code) is None:
            _fail(MetadataWriteAuthorizationErrorCode.EVENT_INVALID)
        if self.confirmation_digest is not None:
            _require_sha256(
                self.confirmation_digest,
                MetadataWriteAuthorizationErrorCode.EVENT_INVALID,
            )


def build_epub3_title_write_preparation(
    *,
    plan: MetadataCorrectionPlan,
    preflight: EpubTitleWritePreflight,
    patch: EpubTitlePackagePatch,
    verified_stage: EpubTitleVerifiedStage,
    capability: ResolvedMetadataWriteCapability,
    preparation_lease: MetadataWriteLeaseSnapshot,
    authorized_at: datetime,
    prepared_at: datetime,
) -> EpubTitleWritePreparationSnapshot:
    """Bind one verified private stage to the exact short-lived preparation fence."""

    try:
        validate_epub3_title_write_plan(plan)
    except (TypeError, ValueError):
        _fail(MetadataWriteAuthorizationErrorCode.PLAN_INVALID)
    try:
        validate_epub3_title_package_patch(preflight, patch)
        expected_patch = build_epub3_title_package_patch(
            preflight,
            authorized_at=authorized_at,
        )
    except (TypeError, ValueError):
        _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    if expected_patch != patch:
        _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    if not isinstance(verified_stage, EpubTitleVerifiedStage):
        _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    stage = verified_stage.staged_files
    validation = verified_stage.validation
    candidate = plan.candidate
    if (
        preflight.plan_id != plan.id
        or preflight.plan_content_hash != plan.content_hash
        or preflight.source_sha256 != candidate.expected_full_sha256
        or preflight.source_size_bytes != candidate.expected_size_bytes
        or stage.plan_id != plan.id
        or stage.plan_content_hash != plan.content_hash
        or stage.input_sha256 != preflight.source_sha256
        or stage.input_size_bytes != preflight.source_size_bytes
        or stage.output_sha256 != validation.output_sha256
        or stage.input_sha256 != validation.input_sha256
        or validation.plan_id != plan.id
    ):
        _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    if (
        not isinstance(capability, ResolvedMetadataWriteCapability)
        or capability.scan_root_id != candidate.scan_root_id
        or capability.writer_profile != EPUB_TITLE_WRITE_PROFILE
    ):
        _fail(MetadataWriteAuthorizationErrorCode.CAPABILITY_INVALID)
    authorized = _second_utc(
        authorized_at,
        MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID,
    )
    prepared = _utc(
        prepared_at,
        MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID,
    )
    if (
        not isinstance(preparation_lease, MetadataWriteLeaseSnapshot)
        or _lease_owner_kind(preparation_lease) != "METADATA_WRITE_PREPARATION"
        or not isinstance(preparation_lease.owner_run_id, EntityId)
        or isinstance(preparation_lease.fence_epoch, bool)
        or not isinstance(preparation_lease.fence_epoch, int)
        or preparation_lease.fence_epoch <= 0
        or not _aware_datetime(preparation_lease.acquired_at)
        or not _aware_datetime(preparation_lease.lease_expires_at)
        or preparation_lease.scan_root_id != candidate.scan_root_id
        or preparation_lease.acquired_at > authorized
        or prepared < authorized
        or preparation_lease.lease_expires_at <= prepared
    ):
        _fail(MetadataWriteAuthorizationErrorCode.LEASE_INVALID)
    material = {
        "preparation_owner_id": preparation_lease.owner_run_id,
        "preparation_fence_epoch": preparation_lease.fence_epoch,
        "plan_id": plan.id,
        "plan_content_hash": plan.content_hash,
        "scan_root_id": candidate.scan_root_id,
        "file_id": candidate.file_id,
        "observation_id": candidate.observation_id,
        "source_sha256": stage.input_sha256,
        "source_size_bytes": stage.input_size_bytes,
        "expected_output_sha256": stage.output_sha256,
        "expected_output_size_bytes": stage.output_size_bytes,
        "metadata_write_capability_id": capability.metadata_write_capability_id,
        "dcterms_modified": patch.dcterms_modified,
        "authorized_at": authorized,
        "prepared_at": prepared,
        "metadata_tool_version": validation.metadata_tool_version,
        "epubcheck_tool_version": validation.epubcheck_tool_version,
        "text_tool_version": validation.text_tool_version,
        "cover_tool_version": validation.cover_tool_version,
        "validator_set_fingerprint": validation.validator_set_fingerprint,
    }
    content_hash = _preparation_hash_from_material(material)
    return EpubTitleWritePreparationSnapshot(
        id=_preparation_id(content_hash),
        preparation_owner_id=preparation_lease.owner_run_id,
        preparation_fence_epoch=preparation_lease.fence_epoch,
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        scan_root_id=candidate.scan_root_id,
        file_id=candidate.file_id,
        observation_id=candidate.observation_id,
        source_sha256=stage.input_sha256,
        source_size_bytes=stage.input_size_bytes,
        expected_output_sha256=stage.output_sha256,
        expected_output_size_bytes=stage.output_size_bytes,
        metadata_write_capability_id=capability.metadata_write_capability_id,
        dcterms_modified=patch.dcterms_modified,
        authorized_at=authorized,
        prepared_at=prepared,
        metadata_tool_version=validation.metadata_tool_version,
        epubcheck_tool_version=validation.epubcheck_tool_version,
        text_tool_version=validation.text_tool_version,
        cover_tool_version=validation.cover_tool_version,
        validator_set_fingerprint=validation.validator_set_fingerprint,
        content_hash=content_hash,
    )


def build_metadata_write_authorization(
    preparation: EpubTitleWritePreparationSnapshot,
    *,
    expires_at: datetime,
) -> MetadataWriteAuthorizationSnapshot:
    """Confirm exactly one prepared output without reserving its root lease."""

    if not isinstance(preparation, EpubTitleWritePreparationSnapshot):
        _fail(MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    expires = _utc(
        expires_at,
        MetadataWriteAuthorizationErrorCode.AUTHORIZATION_WINDOW_INVALID,
    )
    _validate_window(preparation.authorized_at, preparation.prepared_at, expires)
    material = {
        "preparation_id": preparation.id,
        "preparation_content_hash": preparation.content_hash,
        "preparation_owner_id": preparation.preparation_owner_id,
        "preparation_fence_epoch": preparation.preparation_fence_epoch,
        "plan_id": preparation.plan_id,
        "plan_content_hash": preparation.plan_content_hash,
        "scan_root_id": preparation.scan_root_id,
        "file_id": preparation.file_id,
        "observation_id": preparation.observation_id,
        "source_sha256": preparation.source_sha256,
        "source_size_bytes": preparation.source_size_bytes,
        "expected_output_sha256": preparation.expected_output_sha256,
        "expected_output_size_bytes": preparation.expected_output_size_bytes,
        "metadata_write_capability_id": preparation.metadata_write_capability_id,
        "dcterms_modified": preparation.dcterms_modified,
        "authorized_at": preparation.authorized_at,
        "prepared_at": preparation.prepared_at,
        "expires_at": expires,
        "metadata_tool_version": preparation.metadata_tool_version,
        "epubcheck_tool_version": preparation.epubcheck_tool_version,
        "text_tool_version": preparation.text_tool_version,
        "cover_tool_version": preparation.cover_tool_version,
        "validator_set_fingerprint": preparation.validator_set_fingerprint,
    }
    content_hash = _authorization_hash_from_material(material)
    return MetadataWriteAuthorizationSnapshot(
        id=_authorization_id(content_hash),
        preparation_id=preparation.id,
        preparation_content_hash=preparation.content_hash,
        preparation_owner_id=preparation.preparation_owner_id,
        preparation_fence_epoch=preparation.preparation_fence_epoch,
        plan_id=preparation.plan_id,
        plan_content_hash=preparation.plan_content_hash,
        scan_root_id=preparation.scan_root_id,
        file_id=preparation.file_id,
        observation_id=preparation.observation_id,
        source_sha256=preparation.source_sha256,
        source_size_bytes=preparation.source_size_bytes,
        expected_output_sha256=preparation.expected_output_sha256,
        expected_output_size_bytes=preparation.expected_output_size_bytes,
        metadata_write_capability_id=preparation.metadata_write_capability_id,
        dcterms_modified=preparation.dcterms_modified,
        authorized_at=preparation.authorized_at,
        prepared_at=preparation.prepared_at,
        expires_at=expires,
        metadata_tool_version=preparation.metadata_tool_version,
        epubcheck_tool_version=preparation.epubcheck_tool_version,
        text_tool_version=preparation.text_tool_version,
        cover_tool_version=preparation.cover_tool_version,
        validator_set_fingerprint=preparation.validator_set_fingerprint,
        content_hash=content_hash,
    )


def build_metadata_write_run(
    authorization: MetadataWriteAuthorizationSnapshot,
    capability: ResolvedMetadataWriteCapability,
    lease: MetadataWriteLeaseSnapshot,
    *,
    run_id: EntityId,
    created_at: datetime,
) -> MetadataWriteExecutionRun:
    """Bind one unused authorization to the fresh fence held by its future executor."""

    if not isinstance(authorization, MetadataWriteAuthorizationSnapshot):
        _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
    created = _utc(created_at, MetadataWriteAuthorizationErrorCode.RUN_INVALID)
    if not authorization.authorized_at <= created < authorization.expires_at:
        _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_WINDOW_INVALID)
    if (
        not isinstance(capability, ResolvedMetadataWriteCapability)
        or capability.metadata_write_capability_id
        != authorization.metadata_write_capability_id
        or capability.scan_root_id != authorization.scan_root_id
        or capability.writer_profile != authorization.writer_profile
    ):
        _fail(MetadataWriteAuthorizationErrorCode.CAPABILITY_INVALID)
    if (
        not isinstance(run_id, EntityId)
        or not isinstance(lease, MetadataWriteLeaseSnapshot)
        or _lease_owner_kind(lease) != "METADATA_WRITE_RUN"
        or isinstance(lease.fence_epoch, bool)
        or not isinstance(lease.fence_epoch, int)
        or lease.fence_epoch <= 0
        or not _aware_datetime(lease.acquired_at)
        or not _aware_datetime(lease.lease_expires_at)
        or lease.owner_run_id != run_id
        or lease.scan_root_id != authorization.scan_root_id
        or lease.acquired_at > created
        or lease.lease_expires_at <= created
    ):
        _fail(MetadataWriteAuthorizationErrorCode.LEASE_INVALID)
    return MetadataWriteExecutionRun(
        id=run_id,
        authorization_id=authorization.id,
        authorization_content_hash=authorization.content_hash,
        plan_id=authorization.plan_id,
        scan_root_id=authorization.scan_root_id,
        file_id=authorization.file_id,
        metadata_write_capability_id=authorization.metadata_write_capability_id,
        initial_fence_epoch=lease.fence_epoch,
        created_at=created,
    )


def _preparation_content_hash(value: EpubTitleWritePreparationSnapshot) -> str:
    return _preparation_hash_from_material(
        {
            "preparation_owner_id": value.preparation_owner_id,
            "preparation_fence_epoch": value.preparation_fence_epoch,
            "plan_id": value.plan_id,
            "plan_content_hash": value.plan_content_hash,
            "scan_root_id": value.scan_root_id,
            "file_id": value.file_id,
            "observation_id": value.observation_id,
            "source_sha256": value.source_sha256,
            "source_size_bytes": value.source_size_bytes,
            "expected_output_sha256": value.expected_output_sha256,
            "expected_output_size_bytes": value.expected_output_size_bytes,
            "metadata_write_capability_id": value.metadata_write_capability_id,
            "dcterms_modified": value.dcterms_modified,
            "authorized_at": value.authorized_at,
            "prepared_at": value.prepared_at,
            "metadata_tool_version": value.metadata_tool_version,
            "epubcheck_tool_version": value.epubcheck_tool_version,
            "text_tool_version": value.text_tool_version,
            "cover_tool_version": value.cover_tool_version,
            "validator_set_fingerprint": value.validator_set_fingerprint,
        }
    )


def _authorization_content_hash(value: MetadataWriteAuthorizationSnapshot) -> str:
    return _authorization_hash_from_material(
        {
            "preparation_id": value.preparation_id,
            "preparation_content_hash": value.preparation_content_hash,
            "preparation_owner_id": value.preparation_owner_id,
            "preparation_fence_epoch": value.preparation_fence_epoch,
            "plan_id": value.plan_id,
            "plan_content_hash": value.plan_content_hash,
            "scan_root_id": value.scan_root_id,
            "file_id": value.file_id,
            "observation_id": value.observation_id,
            "source_sha256": value.source_sha256,
            "source_size_bytes": value.source_size_bytes,
            "expected_output_sha256": value.expected_output_sha256,
            "expected_output_size_bytes": value.expected_output_size_bytes,
            "metadata_write_capability_id": value.metadata_write_capability_id,
            "dcterms_modified": value.dcterms_modified,
            "authorized_at": value.authorized_at,
            "prepared_at": value.prepared_at,
            "expires_at": value.expires_at,
            "metadata_tool_version": value.metadata_tool_version,
            "epubcheck_tool_version": value.epubcheck_tool_version,
            "text_tool_version": value.text_tool_version,
            "cover_tool_version": value.cover_tool_version,
            "validator_set_fingerprint": value.validator_set_fingerprint,
        }
    )


def _preparation_hash_from_material(material: dict[str, object]) -> str:
    return hashlib.sha256(
        _PREPARATION_DOMAIN
        + _canonical_json(_hash_payload(material, METADATA_WRITE_PREPARATION_PROFILE))
    ).hexdigest()


def _authorization_hash_from_material(material: dict[str, object]) -> str:
    return hashlib.sha256(
        _AUTHORIZATION_DOMAIN
        + _canonical_json(_hash_payload(material, METADATA_WRITE_AUTHORIZATION_PROFILE))
    ).hexdigest()


def _hash_payload(material: dict[str, object], profile: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile": profile,
        "writer_profile": EPUB_TITLE_WRITE_PROFILE,
        "patcher_version": EPUB_TITLE_PATCHER_VERSION,
        "staging_profile": EPUB_TITLE_STAGING_PROFILE,
        "validation_profile": EPUB_TITLE_VALIDATION_PROFILE,
        "validator_set": EPUB_TITLE_VALIDATOR_SET,
    }
    for key, value in material.items():
        if isinstance(value, EntityId):
            payload[key] = str(value)
        elif isinstance(value, datetime):
            payload[key] = _timestamp(value)
        else:
            payload[key] = value
    return payload


def _preparation_id(content_hash: str) -> EntityId:
    _require_sha256(content_hash, MetadataWriteAuthorizationErrorCode.PREPARATION_INVALID)
    return EntityId(uuid5(_PREPARATION_NAMESPACE, content_hash))


def _authorization_id(content_hash: str) -> EntityId:
    _require_sha256(content_hash, MetadataWriteAuthorizationErrorCode.AUTHORIZATION_INVALID)
    return EntityId(uuid5(_AUTHORIZATION_NAMESPACE, content_hash))


def _validate_window(authorized_at: datetime, prepared_at: datetime, expires_at: datetime) -> None:
    if (
        prepared_at < authorized_at
        or expires_at <= prepared_at
        or expires_at - authorized_at > MAX_METADATA_WRITE_AUTHORIZATION_LIFETIME
    ):
        _fail(MetadataWriteAuthorizationErrorCode.AUTHORIZATION_WINDOW_INVALID)


def _technical_text(value: str, code: MetadataWriteAuthorizationErrorCode) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(character) < 0x20 for character in value)
        or "/" in value
        or "\\" in value
    ):
        _fail(code)
    return value


def _lease_owner_kind(value: MetadataWriteLeaseSnapshot) -> str | None:
    raw = value.owner_kind
    candidate = getattr(raw, "value", raw)
    return candidate if isinstance(candidate, str) else None


def _aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _require_sha256(value: str, code: MetadataWriteAuthorizationErrorCode) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _utc(value: datetime, code: MetadataWriteAuthorizationErrorCode) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(code)
    return value.astimezone(UTC)


def _second_utc(value: datetime, code: MetadataWriteAuthorizationErrorCode) -> datetime:
    normalized = _utc(value, code)
    if normalized.microsecond != 0:
        _fail(code)
    return normalized


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


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


__all__ = [
    "MAX_METADATA_WRITE_AUTHORIZATION_LIFETIME",
    "MAX_METADATA_WRITE_EVENTS",
    "METADATA_WRITE_AUTHORIZATION_PROFILE",
    "METADATA_WRITE_PREPARATION_PROFILE",
    "METADATA_WRITE_RUN_PROFILE",
    "EpubTitleWritePreparationSnapshot",
    "MetadataWriteAuthorizationError",
    "MetadataWriteAuthorizationErrorCode",
    "MetadataWriteAuthorizationSnapshot",
    "MetadataWriteExecutionEvent",
    "MetadataWriteExecutionRun",
    "MetadataWriteLeaseSnapshot",
    "MetadataWriteRunStatus",
    "build_epub3_title_write_preparation",
    "build_metadata_write_authorization",
    "build_metadata_write_run",
]
