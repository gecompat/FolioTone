"""Bounded real archive listing and integrity through the fixed Linux runner."""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol

from foliotone.archive.container_sandbox import (
    ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
    ArchiveContainerRequest,
    ArchiveContainerRunResult,
    ArchiveContainerRunStatus,
    ArchiveLinuxContainerRunner,
    ArchiveWrapperContainerRequest,
    ArchiveWrapperContainerRunResult,
    ArchiveWrapperOperation,
)
from foliotone.archive.process_runner import CancellationProbe
from foliotone.archive.safety_policy import (
    ARCHIVE_SAFETY_POLICY_PROFILE,
    MAX_MEMBER_COUNT,
    ArchiveMemberDescriptor,
    ArchiveMemberKind,
    ArchiveSafetyStatus,
    is_safe_archive_member_locator,
    validate_archive_safety,
)
from foliotone.archive.secret_handle import ArchivePasswordAttemptStatus
from foliotone.archive.sevenzip import (
    ARCHIVE_7ZIP_ADAPTER_VERSION,
    ARCHIVE_7ZIP_PROVIDER_ID,
    ARCHIVE_7ZIP_TOOL_VERSION,
    ARCHIVE_IMAGE_REFERENCE,
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    build_7zzs_integrity_command,
    build_7zzs_listing_command,
    build_7zzs_tar_stdin_integrity_command,
    build_7zzs_tar_stdin_listing_command,
    build_7zzs_wrapper_decode_command,
)
from foliotone.archive.sevenzip_slt import (
    ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
    ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
    ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
    ArchiveSevenZipFormatCase,
    ArchiveSevenZipSltMember,
    ArchiveSevenZipSltParseStatus,
    _ArchiveSevenZipLockedPrivateParseResult,
    _parse_archive_7zip_slt_members_locked_private,
)
from foliotone.archive.signatures import (
    ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
    ARCHIVE_SIGNATURE_PROFILE_V2,
    ArchiveContainerClass,
    ArchiveListingStatus,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservationV2,
    ArchiveStorageFamily,
    ArchiveSuffixKind,
)
from foliotone.archive.workflow import (
    ARCHIVE_EXTRACTION_PROFILE,
    ARCHIVE_LISTING_PROFILE,
    NONE_SECRET_VERSION,
    ArchiveEncryptionStatus,
    ArchiveIntegrityExecution,
    ArchiveIntegrityStatus,
    ArchiveListingExecution,
    ArchiveListingResult,
    ArchiveMemberCrcStatus,
    ArchiveMemberObservation,
    ArchiveReuseKey,
    build_archive_member_identity,
)
from foliotone.archive.wrapper_stream import ARCHIVE_TAR_STREAM_FRAME_PROFILE
from foliotone.core import EntityId, ToolCapability, ToolExecutionStatus
from foliotone.tooling import ToolExecution

ARCHIVE_PROVIDER_PROFILE: Final = "archive-7zip-provider/v1"
ARCHIVE_WRAPPER_PROVIDER_PROFILE: Final = "archive-7zip-wrapper-provider/v1"
_INPUT_DOMAIN: Final = b"archive-7zip-provider-input/v1\x00"
_VOLUME_GROUP_DOMAIN: Final = b"archive-volume-group/v1\x00"
_SHA256: Final = re.compile(r"[0-9a-f]{64}\Z")
_CRC32: Final = re.compile(r"[0-9A-F]{8}\Z")
_INPUT_IDENTITY: Final = re.compile(r"archive-7zip-provider-input/v1:[0-9a-f]{64}\Z")
_OPAQUE: Final = re.compile(r"[A-Za-z0-9._@-]{1,256}\Z")
_SENTINEL: Final = object()
_WRAPPER_IMAGE_REFERENCE: Final = (
    f"{ARCHIVE_IMAGE_REFERENCE}@"
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)
_WRAPPER_KINDS: Final = frozenset(
    {
        ArchiveOuterCompressionKind.GZIP,
        ArchiveOuterCompressionKind.BZIP2,
        ArchiveOuterCompressionKind.XZ,
        ArchiveOuterCompressionKind.ZSTD,
    }
)
_PROVIDER_LISTING_STATUSES: Final = frozenset(
    {
        ArchiveListingStatus.NOT_ATTEMPTED,
        ArchiveListingStatus.LISTED,
        ArchiveListingStatus.LIMIT_EXCEEDED,
        ArchiveListingStatus.TIMED_OUT,
        ArchiveListingStatus.TOOL_UNAVAILABLE,
        ArchiveListingStatus.TOOL_FAILED,
        ArchiveListingStatus.POLICY_REJECTED,
    }
)
_PROVIDER_INTEGRITY_STATUSES: Final = frozenset(
    {
        ArchiveIntegrityStatus.NOT_TESTED,
        ArchiveIntegrityStatus.PASSED,
        ArchiveIntegrityStatus.LIMIT_EXCEEDED,
        ArchiveIntegrityStatus.TIMED_OUT,
        ArchiveIntegrityStatus.TOOL_UNAVAILABLE,
        ArchiveIntegrityStatus.TOOL_FAILED,
        ArchiveIntegrityStatus.POLICY_REJECTED,
    }
)
_EXTRACTABLE_LOCKED_CASES: Final = frozenset(
    {
        (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR),
        (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.DIRECTORY),
        (ArchiveStorageFamily.RAR4, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR),
        (ArchiveStorageFamily.RAR5, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR),
        (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR),
        (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.DIRECTORY),
        (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR),
        (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.DIRECTORY),
    }
)


class _Runner(Protocol):
    def run(
        self,
        request: ArchiveContainerRequest,
        *,
        stdout_consumer: Callable[[bytes], bool],
        stderr_classifier: Callable[[bytes], bool],
        cancellation: CancellationProbe | None = None,
    ) -> ArchiveContainerRunResult: ...

    def run_wrapper_pipeline(
        self,
        request: ArchiveWrapperContainerRequest,
        *,
        stdout_consumer: Callable[[bytes], bool],
        cancellation: CancellationProbe | None = None,
    ) -> ArchiveWrapperContainerRunResult: ...


@dataclass(frozen=True, slots=True)
class ArchiveProviderResult:
    """Locator-free public projection of one validated private listing result."""

    profile: str
    listing_execution: ArchiveListingExecution
    encryption_status: ArchiveEncryptionStatus
    reuse_key: ArchiveReuseKey
    integrity_execution: ArchiveIntegrityExecution
    password_attempt_status: ArchivePasswordAttemptStatus
    extraction_policy_status: ArchiveSafetyStatus
    member_count: int

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_PROVIDER_PROFILE:
            raise ValueError("unsupported archive provider result profile")
        if not isinstance(self.listing_execution, ArchiveListingExecution):
            raise ValueError("listing_execution must be ArchiveListingExecution")
        if not isinstance(self.encryption_status, ArchiveEncryptionStatus):
            raise ValueError("encryption_status must be ArchiveEncryptionStatus")
        if not isinstance(self.reuse_key, ArchiveReuseKey):
            raise ValueError("reuse_key must be ArchiveReuseKey")
        if not isinstance(self.integrity_execution, ArchiveIntegrityExecution):
            raise ValueError("integrity_execution must be ArchiveIntegrityExecution")
        if not isinstance(self.password_attempt_status, ArchivePasswordAttemptStatus):
            raise ValueError("password_attempt_status must be ArchivePasswordAttemptStatus")
        if not isinstance(self.extraction_policy_status, ArchiveSafetyStatus):
            raise ValueError("extraction_policy_status must be ArchiveSafetyStatus")
        if self.listing_status not in _PROVIDER_LISTING_STATUSES:
            raise ValueError("listing status is not authorized by archive provider v1")
        if self.integrity_status not in _PROVIDER_INTEGRITY_STATUSES:
            raise ValueError("integrity status is not authorized by archive provider v1")
        if (
            isinstance(self.member_count, bool)
            or not isinstance(self.member_count, int)
            or not 0 <= self.member_count <= MAX_MEMBER_COUNT
        ):
            raise ValueError("member_count exceeds the archive provider bound")
        if self.listing_status is not ArchiveListingStatus.LISTED:
            if (
                self.member_count != 0
                or self.encryption_status is not ArchiveEncryptionStatus.UNKNOWN
                or self.integrity_status is not ArchiveIntegrityStatus.NOT_TESTED
                or self.password_attempt_status is not ArchivePasswordAttemptStatus.NOT_ATTEMPTED
                or self.extraction_policy_status is ArchiveSafetyStatus.ACCEPTED
            ):
                raise ValueError("failed or unattempted listing projection is inconsistent")
        elif self.encryption_status is ArchiveEncryptionStatus.NONE:
            if (
                self.password_attempt_status is not ArchivePasswordAttemptStatus.NOT_ATTEMPTED
                or self.integrity_status is ArchiveIntegrityStatus.NOT_TESTED
            ):
                raise ValueError("plaintext listing projection requires tested integrity")
        elif self.encryption_status in {
            ArchiveEncryptionStatus.DATA_ENCRYPTED,
            ArchiveEncryptionStatus.MIXED,
        }:
            if (
                self.integrity_status is not ArchiveIntegrityStatus.NOT_TESTED
                or self.password_attempt_status
                is not ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE
                or self.extraction_policy_status is ArchiveSafetyStatus.ACCEPTED
                or (
                    self.encryption_status is ArchiveEncryptionStatus.DATA_ENCRYPTED
                    and self.member_count < 1
                )
                or (
                    self.encryption_status is ArchiveEncryptionStatus.MIXED
                    and self.member_count < 2
                )
            ):
                raise ValueError("encrypted listing projection must remain blocked")
        else:
            raise ValueError("listed archive encryption must be determined")

    @property
    def listing_status(self) -> ArchiveListingStatus:
        return self.listing_execution.status

    @property
    def integrity_status(self) -> ArchiveIntegrityStatus:
        return self.integrity_execution.status


@dataclass(frozen=True, slots=True)
class _ArchiveWrapperReuseEvidence:
    """Private locator-free binding for one accepted wrapper composite pair."""

    outcome: ArchiveProviderOutcome = field(repr=False, compare=False)
    signature: ArchiveSignatureObservationV2 = field(repr=False, compare=False)
    listing_run: ArchiveWrapperContainerRunResult = field(repr=False, compare=False)
    integrity_run: ArchiveWrapperContainerRunResult = field(repr=False, compare=False)
    profile: str
    archive_full_sha256: str
    volume_group_fingerprint: str
    outer_compression_kind: ArchiveOuterCompressionKind
    signature_profile: str
    compatibility_profile: str
    runner_profile: str
    frame_profile: str
    parser_profile: str
    format_lock_profile: str
    format_lock_sha256: str
    image_reference: str
    wrapper_command_identity: str
    listing_command_identity: str
    integrity_command_identity: str
    inner_stream_size_bytes: int
    inner_stream_sha256: str
    listing_execution_id: str
    integrity_execution_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.outcome, ArchiveProviderOutcome)
            or not isinstance(self.signature, ArchiveSignatureObservationV2)
            or not _is_supported_wrapper_signature(self.signature)
            or self.signature.outer_compression_kind is not self.outer_compression_kind
            or self.signature.profile != self.signature_profile
            or self.signature.compatibility != self.compatibility_profile
            or not isinstance(self.listing_run, ArchiveWrapperContainerRunResult)
            or not isinstance(self.integrity_run, ArchiveWrapperContainerRunResult)
            or self.listing_run.status is not ArchiveContainerRunStatus.COMPLETED
            or self.integrity_run.status is not ArchiveContainerRunStatus.COMPLETED
            or self.listing_run.inner_stream_size_bytes
            != self.integrity_run.inner_stream_size_bytes
            or self.listing_run.inner_stream_sha256
            != self.integrity_run.inner_stream_sha256
            or self.inner_stream_size_bytes != self.listing_run.inner_stream_size_bytes
            or self.inner_stream_sha256 != self.listing_run.inner_stream_sha256
            or self.outcome.result is None
            or len(self.outcome.executions) != 2
            or self.outcome._extraction_handoff is not None
            or self.outcome.result.listing_status is not ArchiveListingStatus.LISTED
            or self.outcome.result.integrity_status is not ArchiveIntegrityStatus.PASSED
            or self.outcome.result.extraction_policy_status
            is not ArchiveSafetyStatus.POLICY_REJECTED
            or self.outcome.result.reuse_key.archive_full_sha256
            != self.archive_full_sha256
            or self.outcome.result.reuse_key.volume_group_fingerprint
            != self.volume_group_fingerprint
            or tuple(str(item.id) for item in self.outcome.executions)
            != (self.listing_execution_id, self.integrity_execution_id)
        ):
            raise ValueError("wrapper reuse outcome lineage is inconsistent")
        if (
            self.profile != ARCHIVE_WRAPPER_PROVIDER_PROFILE
            or self.outer_compression_kind not in _WRAPPER_KINDS
            or self.signature_profile != ARCHIVE_SIGNATURE_PROFILE_V2
            or self.compatibility_profile != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
            or self.runner_profile != ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE
            or self.frame_profile != ARCHIVE_TAR_STREAM_FRAME_PROFILE
            or self.parser_profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE
            or self.format_lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE
            or self.format_lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256
            or self.image_reference != _WRAPPER_IMAGE_REFERENCE
        ):
            raise ValueError("wrapper reuse profiles are inconsistent")
        for value in (
            self.archive_full_sha256,
            self.volume_group_fingerprint,
            self.inner_stream_sha256,
            self.wrapper_command_identity,
            self.listing_command_identity,
            self.integrity_command_identity,
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("wrapper reuse material must use lowercase SHA-256")
        if (
            isinstance(self.inner_stream_size_bytes, bool)
            or not isinstance(self.inner_stream_size_bytes, int)
            or self.inner_stream_size_bytes < 1_024
        ):
            raise ValueError("wrapper inner stream size is invalid")
        if any(
            not isinstance(value, str) or _OPAQUE.fullmatch(value) is None
            for value in (self.listing_execution_id, self.integrity_execution_id)
        ) or self.listing_execution_id == self.integrity_execution_id:
            raise ValueError("wrapper composite executions must be distinct and opaque")
        expected_commands = (
            _command_identity(build_7zzs_wrapper_decode_command()),
            _command_identity(build_7zzs_tar_stdin_listing_command()),
            _command_identity(build_7zzs_tar_stdin_integrity_command()),
        )
        if (
            self.wrapper_command_identity,
            self.listing_command_identity,
            self.integrity_command_identity,
        ) != expected_commands:
            raise ValueError("wrapper command identities are inconsistent")


@dataclass(frozen=True, slots=True)
class _ArchivePersistenceHandoff:
    """Private same-run listing material for immutable persistence only."""

    outcome: ArchiveProviderOutcome = field(repr=False, compare=False)
    signature: ArchiveSignatureObservationV2 = field(repr=False, compare=False)
    listing_result: ArchiveListingResult = field(repr=False, compare=False)
    parser_result: _ArchiveSevenZipLockedPrivateParseResult = field(
        repr=False, compare=False
    )
    executions: tuple[ToolExecution, ...] = field(repr=False, compare=False)
    wrapper_listing_run: ArchiveWrapperContainerRunResult | None = field(
        default=None, repr=False, compare=False
    )
    wrapper_integrity_run: ArchiveWrapperContainerRunResult | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        public = self.outcome.result
        if (
            public is None
            or self.outcome._persistence_handoff is not None
            or self.executions is not self.outcome.executions
            or tuple(str(item.id) for item in self.executions)
            != tuple(
                value
                for value in (
                    public.listing_execution.execution_id,
                    public.integrity_execution.execution_id,
                )
                if value is not None
            )
            or self.listing_result.listing_execution is not public.listing_execution
            or self.listing_result.integrity_execution is not public.integrity_execution
            or self.listing_result.reuse_key is not public.reuse_key
            or self.parser_result.public.signature_profile != self.signature.profile
        ):
            raise ValueError("archive persistence handoff lineage is inconsistent")
        wrapper = _is_supported_wrapper_signature(self.signature)
        if wrapper is not (self.wrapper_listing_run is not None):
            raise ValueError("archive persistence wrapper lineage is inconsistent")
        if self.wrapper_integrity_run is not None and self.wrapper_listing_run is None:
            raise ValueError("archive persistence integrity lineage is inconsistent")
        if self.wrapper_listing_run is not None:
            has_size = self.wrapper_listing_run.inner_stream_size_bytes > 0
            has_hash = self.wrapper_listing_run.inner_stream_sha256 is not None
            if has_size is not has_hash:
                raise ValueError("archive persistence wrapper listing is incomplete")
            if self.listing_result.listing_status is ArchiveListingStatus.LISTED and not has_size:
                raise ValueError("listed wrapper persistence material is incomplete")
        parser_public = self.parser_result.public
        expected_storage = (
            ArchiveStorageFamily.TAR if wrapper else self.signature.storage_family
        )
        if (
            parser_public.profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE
            or parser_public.lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE
            or parser_public.lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256
            or parser_public.compatibility
            != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
            or parser_public.storage_family is not expected_storage
            or len(self.listing_result.members) != len(self.parser_result.members)
            or len(self.listing_result.members) != public.member_count
        ):
            raise ValueError("archive persistence parser lineage is inconsistent")
        for ordinal, (listed, parsed) in enumerate(
            zip(
                self.listing_result.members,
                self.parser_result.members,
                strict=True,
            )
        ):
            expected_identity = build_archive_member_identity(
                archive_full_sha256=self.listing_result.reuse_key.archive_full_sha256,
                volume_group_fingerprint=(
                    self.listing_result.reuse_key.volume_group_fingerprint
                ),
                member_path_safe=parsed.locator,
                member_ordinal=listed.member_ordinal,
            )
            if (
                listed.member_path_safe != parsed.locator
                or listed.member_ordinal != ordinal
                or listed.member_kind is not _member_kind(parsed)
                or listed.declared_compressed_bytes
                != parsed.declared_compressed_bytes
                or listed.declared_uncompressed_bytes
                != parsed.declared_uncompressed_bytes
                or listed.encryption_status
                is not (
                    ArchiveEncryptionStatus.DATA_ENCRYPTED
                    if parsed.encrypted
                    else ArchiveEncryptionStatus.NONE
                )
                or listed.member_identity != expected_identity
            ):
                raise ValueError("archive persistence member lineage is inconsistent")


@dataclass(frozen=True, slots=True)
class ArchiveProviderOutcome:
    profile: str
    result: ArchiveProviderResult | None = field(default=None, repr=False)
    executions: tuple[ToolExecution, ...] = ()
    _extraction_handoff: _ArchiveExtractionHandoff | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _private_listing_result: ArchiveListingResult | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _private_parser_result: _ArchiveSevenZipLockedPrivateParseResult | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _wrapper_reuse_evidence: _ArchiveWrapperReuseEvidence | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _persistence_handoff: _ArchivePersistenceHandoff | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_PROVIDER_PROFILE:
            raise ValueError("unsupported archive provider profile")
        if not isinstance(self.executions, tuple) or any(
            not isinstance(item, ToolExecution) for item in self.executions
        ):
            raise ValueError("executions must contain ToolExecution values")
        if len(self.executions) > 2 or len({item.id for item in self.executions}) != len(
            self.executions
        ):
            raise ValueError("archive provider executions must be distinct and bounded")
        if self.executions and (
            any(
                item.provider_id != ARCHIVE_7ZIP_PROVIDER_ID
                or item.tool_version != ARCHIVE_7ZIP_TOOL_VERSION
                or item.adapter_version != ARCHIVE_7ZIP_ADAPTER_VERSION
                or item.config_identity != ARCHIVE_PROVIDER_PROFILE
                for item in self.executions
            )
            or len({item.input_identity for item in self.executions}) != 1
            or any(
                _INPUT_IDENTITY.fullmatch(item.input_identity) is None for item in self.executions
            )
        ):
            raise ValueError("tool executions must use the fixed archive provider identity")
        if self.result is None:
            if (
                not self.executions
                or self.executions[-1].status is not ToolExecutionStatus.CANCELLED
            ):
                raise ValueError("snapshotless outcome requires a cancelled execution")
            expected: tuple[tuple[ToolCapability, ToolExecutionStatus], ...]
            if len(self.executions) == 1:
                expected = ((ToolCapability.ARCHIVE_LISTING, ToolExecutionStatus.CANCELLED),)
            else:
                expected = (
                    (ToolCapability.ARCHIVE_LISTING, ToolExecutionStatus.SUCCEEDED),
                    (ToolCapability.ARCHIVE_INTEGRITY, ToolExecutionStatus.CANCELLED),
                )
            if tuple((item.capability, item.status) for item in self.executions) != expected:
                raise ValueError("cancelled archive provenance has an invalid execution shape")
            return
        if not isinstance(self.result, ArchiveProviderResult):
            raise ValueError("result must be ArchiveProviderResult or None")
        expected_ids = tuple(
            value
            for value in (
                self.result.listing_execution.execution_id,
                self.result.integrity_execution.execution_id,
            )
            if value is not None
        )
        if tuple(str(item.id) for item in self.executions) != expected_ids:
            raise ValueError("tool executions do not match archive result provenance")
        expected_identity = build_archive_provider_input_identity(
            archive_full_sha256=self.result.reuse_key.archive_full_sha256,
            volume_group_fingerprint=self.result.reuse_key.volume_group_fingerprint,
        )
        if any(item.input_identity != expected_identity for item in self.executions):
            raise ValueError("tool executions do not match archive material identity")
        expected_executions = tuple(
            (
                capability,
                ToolExecutionStatus.SUCCEEDED if succeeded else ToolExecutionStatus.FAILED,
            )
            for capability, succeeded in (
                (
                    ToolCapability.ARCHIVE_LISTING,
                    self.result.listing_status is ArchiveListingStatus.LISTED,
                ),
                (
                    ToolCapability.ARCHIVE_INTEGRITY,
                    self.result.integrity_status is ArchiveIntegrityStatus.PASSED,
                ),
            )[: len(self.executions)]
        )
        if tuple((item.capability, item.status) for item in self.executions) != expected_executions:
            raise ValueError("tool execution statuses do not match archive result states")


@dataclass(frozen=True, slots=True)
class _ArchiveExtractionMemberHandoff:
    """Private, non-rendering member binding for the future extraction boundary."""

    member_ordinal: int = field(repr=False)
    member_locator: str = field(repr=False)
    member_kind: ArchiveMemberKind = field(repr=False)
    declared_compressed_bytes: int = field(repr=False)
    declared_uncompressed_bytes: int = field(repr=False)
    listed_crc32: str | None = field(repr=False)
    member_identity: str = field(repr=False)
    is_directory: bool = field(repr=False)
    encrypted: bool = field(repr=False)
    symbolic_link: bool = field(repr=False)
    hard_link: bool = field(repr=False)
    user_present: bool = field(repr=False)
    group_present: bool = field(repr=False)
    characteristics_present: bool = field(repr=False)
    alternate_stream: bool = field(repr=False)
    anti_item: bool = field(repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.member_ordinal, bool)
            or not isinstance(self.member_ordinal, int)
            or self.member_ordinal < 0
        ):
            raise ValueError("private archive member ordinal is invalid")
        if not is_safe_archive_member_locator(self.member_locator):
            raise ValueError("private archive member locator is invalid")
        if not isinstance(self.member_kind, ArchiveMemberKind) or self.member_kind not in {
            ArchiveMemberKind.REGULAR_FILE,
            ArchiveMemberKind.DIRECTORY,
        }:
            raise ValueError("private archive member kind is not extractable")
        for value in (
            self.declared_compressed_bytes,
            self.declared_uncompressed_bytes,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("private archive member size is invalid")
        if self.listed_crc32 is not None and (
            not isinstance(self.listed_crc32, str)
            or _CRC32.fullmatch(self.listed_crc32) is None
        ):
            raise ValueError("private archive member CRC is invalid")
        if not isinstance(self.member_identity, str) or _SHA256.fullmatch(
            self.member_identity
        ) is None:
            raise ValueError("private archive member identity is invalid")
        if any(
            not isinstance(value, bool)
            for value in (
                self.is_directory,
                self.encrypted,
                self.symbolic_link,
                self.hard_link,
                self.user_present,
                self.group_present,
                self.characteristics_present,
                self.alternate_stream,
                self.anti_item,
            )
        ):
            raise ValueError("private archive member flags are invalid")
        if (
            self.is_directory
            is not (self.member_kind is ArchiveMemberKind.DIRECTORY)
            or self.encrypted
            or self.symbolic_link
            or self.hard_link
            or self.user_present
            or self.group_present
            or self.characteristics_present
            or self.alternate_stream
            or self.anti_item
        ):
            raise ValueError("private archive member flags are not extractable")


@dataclass(frozen=True, slots=True)
class _ArchiveExtractionHandoff:
    """Private one-run lineage envelope; never a public or persistent DTO."""

    outcome: ArchiveProviderOutcome = field(repr=False)
    listing_result: ArchiveListingResult = field(repr=False)
    listing_execution: ToolExecution = field(repr=False)
    integrity_execution: ToolExecution = field(repr=False)
    parser_result: _ArchiveSevenZipLockedPrivateParseResult = field(repr=False)
    archive_full_sha256: str = field(repr=False)
    volume_group_fingerprint: str = field(repr=False)
    signature_profile: str = field(repr=False)
    storage_family: ArchiveStorageFamily = field(repr=False)
    case_kind: ArchiveSevenZipFormatCase = field(repr=False)
    parser_profile: str = field(repr=False)
    format_lock_profile: str = field(repr=False)
    format_lock_sha256: str = field(repr=False)
    compatibility_profile: str = field(repr=False)
    members: tuple[_ArchiveExtractionMemberHandoff, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ArchiveProviderOutcome):
            raise ValueError("private archive handoff outcome is invalid")
        if not isinstance(self.listing_result, ArchiveListingResult):
            raise ValueError("private archive handoff listing result is invalid")
        if not isinstance(
            self.parser_result, _ArchiveSevenZipLockedPrivateParseResult
        ):
            raise ValueError("private archive handoff parser result is invalid")
        if not isinstance(self.listing_execution, ToolExecution) or not isinstance(
            self.integrity_execution, ToolExecution
        ):
            raise ValueError("private archive handoff executions are invalid")
        if self.outcome._extraction_handoff is not None:
            raise ValueError("private archive handoff is already sealed")
        public = self.outcome.result
        if (
            public is None
            or self.outcome._private_listing_result is not self.listing_result
            or self.outcome._private_parser_result is not self.parser_result
            or self.listing_result.listing_execution is not public.listing_execution
            or self.listing_result.integrity_execution is not public.integrity_execution
            or self.listing_result.reuse_key is not public.reuse_key
            or len(self.outcome.executions) != 2
            or self.listing_execution is not self.outcome.executions[0]
            or self.integrity_execution is not self.outcome.executions[1]
            or str(self.listing_execution.id)
            != self.listing_result.listing_execution.execution_id
            or str(self.integrity_execution.id)
            != self.listing_result.integrity_execution.execution_id
        ):
            raise ValueError("private archive handoff object lineage is inconsistent")
        if (
            public.listing_status is not ArchiveListingStatus.LISTED
            or public.integrity_status is not ArchiveIntegrityStatus.PASSED
            or public.encryption_status is not ArchiveEncryptionStatus.NONE
            or public.extraction_policy_status is not ArchiveSafetyStatus.ACCEPTED
        ):
            raise ValueError("private archive handoff state is not extractable")
        for value in (self.archive_full_sha256, self.volume_group_fingerprint):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("private archive handoff material identity is invalid")
        if (
            self.archive_full_sha256
            != self.listing_result.reuse_key.archive_full_sha256
            or self.volume_group_fingerprint
            != self.listing_result.reuse_key.volume_group_fingerprint
            or self.signature_profile != ARCHIVE_SIGNATURE_PROFILE_V2
            or not isinstance(self.storage_family, ArchiveStorageFamily)
            or self.storage_family is ArchiveStorageFamily.UNKNOWN
            or not isinstance(self.case_kind, ArchiveSevenZipFormatCase)
            or (self.storage_family, self.case_kind) not in _EXTRACTABLE_LOCKED_CASES
            or self.parser_profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE
            or self.format_lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE
            or self.format_lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256
            or self.compatibility_profile != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
        ):
            raise ValueError("private archive handoff profiles are inconsistent")
        parser_public = self.parser_result.public
        if (
            parser_public.status is not ArchiveSevenZipSltParseStatus.PARSED
            or parser_public.signature_profile != self.signature_profile
            or parser_public.storage_family is not self.storage_family
            or parser_public.case_kind is not self.case_kind
            or parser_public.profile != self.parser_profile
            or parser_public.lock_profile != self.format_lock_profile
            or parser_public.lock_sha256 != self.format_lock_sha256
            or parser_public.compatibility != self.compatibility_profile
        ):
            raise ValueError("private archive handoff parser lineage is inconsistent")
        if (
            not isinstance(self.members, tuple)
            or not self.members
            or len(self.members) != len(self.listing_result.members)
            or len(self.members) != public.member_count
            or any(
                not isinstance(member, _ArchiveExtractionMemberHandoff)
                for member in self.members
            )
            or tuple(member.member_ordinal for member in self.members)
            != tuple(range(len(self.members)))
        ):
            raise ValueError("private archive handoff members are inconsistent")
        if len(self.parser_result.members) != len(self.members):
            raise ValueError("private archive handoff parser members are inconsistent")
        for private, listed, parsed in zip(
            self.members,
            self.listing_result.members,
            self.parser_result.members,
            strict=True,
        ):
            expected_identity = build_archive_member_identity(
                archive_full_sha256=self.archive_full_sha256,
                volume_group_fingerprint=self.volume_group_fingerprint,
                member_path_safe=private.member_locator,
                member_ordinal=private.member_ordinal,
            )
            if (
                private.member_locator != listed.member_path_safe
                or private.member_locator != parsed.locator
                or private.member_ordinal != listed.member_ordinal
                or private.member_kind is not listed.member_kind
                or private.member_kind is not _member_kind(parsed)
                or private.declared_compressed_bytes
                != listed.declared_compressed_bytes
                or private.declared_compressed_bytes
                != parsed.declared_compressed_bytes
                or private.declared_uncompressed_bytes
                != listed.declared_uncompressed_bytes
                or private.declared_uncompressed_bytes
                != parsed.declared_uncompressed_bytes
                or private.listed_crc32 != parsed.crc32
                or private.member_identity != listed.member_identity
                or private.member_identity != expected_identity
                or private.is_directory is not parsed.is_directory
                or private.encrypted is not parsed.encrypted
                or private.symbolic_link is not parsed.symbolic_link
                or private.hard_link is not parsed.hard_link
                or private.user_present is not parsed.user_present
                or private.group_present is not parsed.group_present
                or private.characteristics_present is not parsed.characteristics_present
                or private.alternate_stream is not parsed.alternate_stream
                or private.anti_item is not parsed.anti_item
            ):
                raise ValueError("private archive handoff member lineage is inconsistent")


def build_archive_provider_input_identity(
    *, archive_full_sha256: str, volume_group_fingerprint: str
) -> str:
    """Return the sole closed, path-free identity accepted by this adapter."""

    for value in (archive_full_sha256, volume_group_fingerprint):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError("archive provider inputs must be lowercase SHA-256")
    material = json.dumps(
        {
            "archive_full_sha256": archive_full_sha256,
            "volume_group_fingerprint": volume_group_fingerprint,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return "archive-7zip-provider-input/v1:" + hashlib.sha256(_INPUT_DOMAIN + material).hexdigest()


def _command_identity(command: tuple[str, ...]) -> str:
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise ValueError("wrapper command identity requires fixed arguments")
    material = json.dumps(command, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return hashlib.sha256(b"archive-wrapper-command/v1\x00" + material).hexdigest()


def build_archive_volume_group_fingerprint(request: ArchiveContainerRequest) -> str:
    """Bind the canonical ordered volume material without exposing locators."""

    if not isinstance(request, ArchiveContainerRequest):
        raise ValueError("request must be ArchiveContainerRequest")
    material = json.dumps(
        [
            {
                "full_sha256": volume.full_sha256,
                "size_bytes": volume.size_bytes,
                "staging_name": volume.staging_name,
            }
            for volume in request.volumes
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(_VOLUME_GROUP_DOMAIN + material).hexdigest()


class ArchiveSevenZipProvider:
    """Production adapter for exactly ``ArchiveLinuxContainerRunner`` only."""

    def __init__(self, runner: ArchiveLinuxContainerRunner) -> None:
        if type(runner) is not ArchiveLinuxContainerRunner:
            raise ValueError("archive provider requires the exact ArchiveLinuxContainerRunner")
        self._runner = runner

    def inspect(
        self,
        request: ArchiveContainerRequest,
        *,
        signature: ArchiveSignatureObservationV2,
        archive_observation_id: str,
        archive_full_sha256: str,
        volume_group_fingerprint: str,
        cancellation: CancellationProbe | None = None,
    ) -> ArchiveProviderOutcome:
        return _inspect(
            self._runner,
            request,
            signature=signature,
            archive_observation_id=archive_observation_id,
            archive_full_sha256=archive_full_sha256,
            volume_group_fingerprint=volume_group_fingerprint,
            cancellation=cancellation,
            now=lambda: datetime.now(UTC),
        )


def _inspect(
    runner: _Runner,
    request: ArchiveContainerRequest,
    *,
    signature: ArchiveSignatureObservationV2,
    archive_observation_id: str,
    archive_full_sha256: str,
    volume_group_fingerprint: str,
    cancellation: CancellationProbe | None,
    now: Callable[[], datetime],
) -> ArchiveProviderOutcome:
    if not isinstance(request, ArchiveContainerRequest):
        raise ValueError("request must be ArchiveContainerRequest")
    if request.command != build_7zzs_listing_command():
        raise ValueError("archive provider accepts only the fixed listing request")
    if not isinstance(signature, ArchiveSignatureObservationV2):
        raise ValueError("signature must be ArchiveSignatureObservationV2")
    if (
        not isinstance(archive_observation_id, str)
        or _OPAQUE.fullmatch(archive_observation_id) is None
    ):
        raise ValueError("archive_observation_id must be path-free and opaque")
    primary = next(volume for volume in request.volumes if volume.staging_name == "archive")
    if archive_full_sha256 != primary.full_sha256:
        raise ValueError("archive hash does not match the primary volume")
    if volume_group_fingerprint != build_archive_volume_group_fingerprint(request):
        raise ValueError("volume group fingerprint does not match the request")
    identity = build_archive_provider_input_identity(
        archive_full_sha256=archive_full_sha256,
        volume_group_fingerprint=volume_group_fingerprint,
    )
    reuse_key = _reuse_key(archive_full_sha256, volume_group_fingerprint)
    if _is_supported_wrapper_signature(signature):
        return _inspect_wrapper(
            runner,
            request,
            signature=signature,
            archive_observation_id=archive_observation_id,
            archive_full_sha256=archive_full_sha256,
            volume_group_fingerprint=volume_group_fingerprint,
            identity=identity,
            reuse_key=reuse_key,
            cancellation=cancellation,
            now=now,
        )
    if signature.recognition_status is not ArchiveRecognitionStatus.MATCHED:
        return _provider_outcome(
            ArchiveListingResult(
                ArchiveListingExecution(ArchiveListingStatus.NOT_ATTEMPTED),
                ArchiveEncryptionStatus.UNKNOWN,
                reuse_key,
                extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
            ),
        )

    listing_started = now()
    listing_run, parsed, parser_terminal = _stream_listing(runner, request, signature, cancellation)
    listing_status = _listing_status(listing_run, parsed.public.status, parser_terminal)
    listing_execution = _tool_execution(
        identity,
        ToolCapability.ARCHIVE_LISTING,
        listing_started,
        now(),
        listing_run,
        succeeded=listing_status is ArchiveListingStatus.LISTED,
    )
    executions: tuple[ToolExecution, ...] = (listing_execution,)
    if listing_run.status is ArchiveContainerRunStatus.CANCELLED:
        return ArchiveProviderOutcome(ARCHIVE_PROVIDER_PROFILE, executions=executions)
    listing_snapshot = ArchiveListingExecution(listing_status, str(listing_execution.id))
    if listing_status is not ArchiveListingStatus.LISTED:
        result = ArchiveListingResult(
            listing_snapshot,
            ArchiveEncryptionStatus.UNKNOWN,
            reuse_key,
            extraction_policy_status=_blocked_policy(listing_status),
        )
        outcome = _provider_outcome(result, executions)
        _attach_persistence_handoff(outcome, signature, parsed, result)
        return outcome

    raw_members = parsed.members
    descriptors = tuple(_descriptor(member) for member in raw_members)
    safety = validate_archive_safety(descriptors, volume_count=len(request.volumes))
    encryption = _encryption(raw_members)
    members = _members(
        raw_members,
        archive_observation_id,
        str(listing_execution.id),
        archive_full_sha256,
        volume_group_fingerprint,
    )
    if encryption is not ArchiveEncryptionStatus.NONE:
        result = ArchiveListingResult(
            listing_snapshot,
            encryption,
            reuse_key,
            members=members,
            password_attempt_status=(ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE),
            extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        )
        outcome = _provider_outcome(result, executions)
        _attach_persistence_handoff(outcome, signature, parsed, result)
        return outcome

    integrity_started = now()
    integrity_request = ArchiveContainerRequest(
        request.volumes, build_7zzs_integrity_command(), request.scan_roots
    )
    integrity_run = runner.run(
        integrity_request,
        stdout_consumer=_discard,
        stderr_classifier=_discard,
        cancellation=cancellation,
    )
    integrity_status = _integrity_status(integrity_run)
    integrity_execution = _tool_execution(
        identity,
        ToolCapability.ARCHIVE_INTEGRITY,
        integrity_started,
        now(),
        integrity_run,
        succeeded=integrity_status is ArchiveIntegrityStatus.PASSED,
    )
    executions += (integrity_execution,)
    if integrity_run.status is ArchiveContainerRunStatus.CANCELLED:
        return ArchiveProviderOutcome(ARCHIVE_PROVIDER_PROFILE, executions=executions)
    policy_status = (
        safety.status
        if integrity_status is ArchiveIntegrityStatus.PASSED
        else ArchiveSafetyStatus.POLICY_REJECTED
    )
    result = ArchiveListingResult(
        listing_snapshot,
        encryption,
        reuse_key,
        ArchiveIntegrityExecution(integrity_status, str(integrity_execution.id)),
        extraction_policy_status=policy_status,
        members=members,
    )
    outcome = _provider_outcome(result, executions)
    _attach_persistence_handoff(outcome, signature, parsed, result)
    if (
        integrity_status is ArchiveIntegrityStatus.PASSED
        and safety.status is ArchiveSafetyStatus.ACCEPTED
    ):
        object.__setattr__(outcome, "_private_listing_result", result)
        object.__setattr__(outcome, "_private_parser_result", parsed)
        _attach_extraction_handoff(
            outcome,
            result,
            executions,
            signature,
            parsed,
        )
    return outcome


def _inspect_wrapper(
    runner: _Runner,
    request: ArchiveContainerRequest,
    *,
    signature: ArchiveSignatureObservationV2,
    archive_observation_id: str,
    archive_full_sha256: str,
    volume_group_fingerprint: str,
    identity: str,
    reuse_key: ArchiveReuseKey,
    cancellation: CancellationProbe | None,
    now: Callable[[], datetime],
) -> ArchiveProviderOutcome:
    inner_signature = _inner_tar_signature()
    listing_started = now()
    listing_run, parsed, parser_terminal = _stream_wrapper_listing(
        runner,
        request,
        inner_signature,
        ArchiveWrapperOperation.LISTING,
        cancellation,
    )
    listing_status = _listing_status(
        listing_run, parsed.public.status, parser_terminal
    )
    listing_execution = _tool_execution(
        identity,
        ToolCapability.ARCHIVE_LISTING,
        listing_started,
        now(),
        listing_run,
        succeeded=listing_status is ArchiveListingStatus.LISTED,
    )
    executions: tuple[ToolExecution, ...] = (listing_execution,)
    if listing_run.status is ArchiveContainerRunStatus.CANCELLED:
        return ArchiveProviderOutcome(ARCHIVE_PROVIDER_PROFILE, executions=executions)
    listing_snapshot = ArchiveListingExecution(
        listing_status, str(listing_execution.id)
    )
    if listing_status is not ArchiveListingStatus.LISTED:
        result = ArchiveListingResult(
            listing_snapshot,
            ArchiveEncryptionStatus.UNKNOWN,
            reuse_key,
            extraction_policy_status=_blocked_policy(listing_status),
        )
        outcome = _provider_outcome(result, executions)
        _attach_persistence_handoff(
            outcome,
            signature,
            parsed,
            result,
            wrapper_listing_run=listing_run,
        )
        return outcome

    raw_members = parsed.members
    members = _members(
        raw_members,
        archive_observation_id,
        str(listing_execution.id),
        archive_full_sha256,
        volume_group_fingerprint,
    )
    encryption = _encryption(raw_members)
    if encryption is not ArchiveEncryptionStatus.NONE:
        result = ArchiveListingResult(
            listing_snapshot,
            encryption,
            reuse_key,
            members=members,
            password_attempt_status=(
                ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE
            ),
            extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        )
        outcome = _provider_outcome(result, executions)
        _attach_persistence_handoff(
            outcome,
            signature,
            parsed,
            result,
            wrapper_listing_run=listing_run,
        )
        return outcome

    integrity_started = now()
    integrity_run = _run_wrapper_integrity(runner, request, cancellation)
    integrity_status = _integrity_status(integrity_run)
    if (
        integrity_status is ArchiveIntegrityStatus.PASSED
        and (
            integrity_run.inner_stream_size_bytes
            != listing_run.inner_stream_size_bytes
            or integrity_run.inner_stream_sha256 != listing_run.inner_stream_sha256
        )
    ):
        integrity_status = ArchiveIntegrityStatus.TOOL_FAILED
    integrity_execution = _tool_execution(
        identity,
        ToolCapability.ARCHIVE_INTEGRITY,
        integrity_started,
        now(),
        integrity_run,
        succeeded=integrity_status is ArchiveIntegrityStatus.PASSED,
    )
    executions += (integrity_execution,)
    if integrity_run.status is ArchiveContainerRunStatus.CANCELLED:
        return ArchiveProviderOutcome(ARCHIVE_PROVIDER_PROFILE, executions=executions)
    result = ArchiveListingResult(
        listing_snapshot,
        encryption,
        reuse_key,
        ArchiveIntegrityExecution(integrity_status, str(integrity_execution.id)),
        extraction_policy_status=ArchiveSafetyStatus.POLICY_REJECTED,
        members=members,
    )
    outcome = _provider_outcome(result, executions)
    _attach_persistence_handoff(
        outcome,
        signature,
        parsed,
        result,
        wrapper_listing_run=listing_run,
        wrapper_integrity_run=integrity_run,
    )
    if integrity_status is ArchiveIntegrityStatus.PASSED:
        object.__setattr__(
            outcome,
            "_wrapper_reuse_evidence",
            _ArchiveWrapperReuseEvidence(
                outcome,
                signature,
                listing_run,
                integrity_run,
                ARCHIVE_WRAPPER_PROVIDER_PROFILE,
                archive_full_sha256,
                volume_group_fingerprint,
                signature.outer_compression_kind,
                signature.profile,
                signature.compatibility,
                ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
                ARCHIVE_TAR_STREAM_FRAME_PROFILE,
                ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
                ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
                ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
                _WRAPPER_IMAGE_REFERENCE,
                _command_identity(build_7zzs_wrapper_decode_command()),
                _command_identity(build_7zzs_tar_stdin_listing_command()),
                _command_identity(build_7zzs_tar_stdin_integrity_command()),
                listing_run.inner_stream_size_bytes,
                listing_run.inner_stream_sha256 or "",
                str(listing_execution.id),
                str(integrity_execution.id),
            ),
        )
    return outcome


def _provider_outcome(
    result: ArchiveListingResult,
    executions: tuple[ToolExecution, ...] = (),
) -> ArchiveProviderOutcome:
    public = ArchiveProviderResult(
        ARCHIVE_PROVIDER_PROFILE,
        result.listing_execution,
        result.encryption_status,
        result.reuse_key,
        result.integrity_execution,
        result.password_attempt_status,
        result.extraction_policy_status,
        len(result.members),
    )
    return ArchiveProviderOutcome(ARCHIVE_PROVIDER_PROFILE, public, executions)


def _attach_persistence_handoff(
    outcome: ArchiveProviderOutcome,
    signature: ArchiveSignatureObservationV2,
    parsed: _ArchiveSevenZipLockedPrivateParseResult,
    listing: ArchiveListingResult,
    *,
    wrapper_listing_run: ArchiveWrapperContainerRunResult | None = None,
    wrapper_integrity_run: ArchiveWrapperContainerRunResult | None = None,
) -> None:
    result = outcome.result
    if result is None:
        raise ValueError("archive persistence handoff requires a terminal result")
    handoff = _ArchivePersistenceHandoff(
        outcome,
        signature,
        listing,
        parsed,
        outcome.executions,
        wrapper_listing_run,
        wrapper_integrity_run,
    )
    object.__setattr__(outcome, "_persistence_handoff", handoff)


def _attach_extraction_handoff(
    outcome: ArchiveProviderOutcome,
    result: ArchiveListingResult,
    executions: tuple[ToolExecution, ...],
    signature: ArchiveSignatureObservationV2,
    parsed: _ArchiveSevenZipLockedPrivateParseResult,
) -> None:
    """Attach the sealed private continuation only after all EBAR-05 gates pass."""

    if (
        outcome.result is None
        or outcome._extraction_handoff is not None
        or outcome._private_listing_result is not result
        or outcome._private_parser_result is not parsed
        or result.listing_execution is not outcome.result.listing_execution
        or result.integrity_execution is not outcome.result.integrity_execution
        or result.reuse_key is not outcome.result.reuse_key
        or outcome.result.listing_status is not ArchiveListingStatus.LISTED
        or outcome.result.integrity_status is not ArchiveIntegrityStatus.PASSED
        or outcome.result.encryption_status is not ArchiveEncryptionStatus.NONE
        or outcome.result.extraction_policy_status is not ArchiveSafetyStatus.ACCEPTED
        or signature.recognition_status is not ArchiveRecognitionStatus.MATCHED
        or signature.outer_compression_kind is not ArchiveOuterCompressionKind.NONE
        or signature.storage_family is ArchiveStorageFamily.UNKNOWN
        or not isinstance(parsed, _ArchiveSevenZipLockedPrivateParseResult)
        or parsed.public.status is not ArchiveSevenZipSltParseStatus.PARSED
        or parsed.public.signature_profile != signature.profile
        or parsed.public.storage_family is not signature.storage_family
        or parsed.public.compatibility != signature.compatibility
        or parsed.public.profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE
        or parsed.public.lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE
        or parsed.public.lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256
        or not isinstance(parsed.public.case_kind, ArchiveSevenZipFormatCase)
        or len(executions) != 2
        or tuple(str(item.id) for item in executions)
        != tuple(
            item
            for item in (
                outcome.result.listing_execution.execution_id,
                outcome.result.integrity_execution.execution_id,
            )
            if item is not None
        )
        or len(parsed.members) != len(result.members)
    ):
        raise ValueError("archive extraction handoff lineage is inconsistent")
    case_kind = parsed.public.case_kind
    assert isinstance(case_kind, ArchiveSevenZipFormatCase)
    private_members = tuple(
        _ArchiveExtractionMemberHandoff(
            member_ordinal=observation.member_ordinal,
            member_locator=parsed.locator,
            member_kind=observation.member_kind,
            declared_compressed_bytes=parsed.declared_compressed_bytes,
            declared_uncompressed_bytes=parsed.declared_uncompressed_bytes,
            listed_crc32=parsed.crc32,
            member_identity=observation.member_identity,
            is_directory=parsed.is_directory,
            encrypted=parsed.encrypted,
            symbolic_link=parsed.symbolic_link,
            hard_link=parsed.hard_link,
            user_present=parsed.user_present,
            group_present=parsed.group_present,
            characteristics_present=parsed.characteristics_present,
            alternate_stream=parsed.alternate_stream,
            anti_item=parsed.anti_item,
        )
        for observation, parsed in zip(result.members, parsed.members, strict=True)
    )
    if any(
        observation.member_ordinal != ordinal
        or observation.member_path_safe != parsed.locator
        or observation.member_kind is not _member_kind(parsed)
        or observation.declared_compressed_bytes != parsed.declared_compressed_bytes
        or observation.declared_uncompressed_bytes != parsed.declared_uncompressed_bytes
        or observation.member_identity
        != build_archive_member_identity(
            archive_full_sha256=result.reuse_key.archive_full_sha256,
            volume_group_fingerprint=result.reuse_key.volume_group_fingerprint,
            member_path_safe=parsed.locator,
            member_ordinal=ordinal,
        )
        for ordinal, (observation, parsed) in enumerate(
            zip(result.members, parsed.members, strict=True)
        )
    ):
        raise ValueError("archive extraction handoff members are inconsistent")
    object.__setattr__(
        outcome,
        "_extraction_handoff",
        _ArchiveExtractionHandoff(
            outcome=outcome,
            listing_result=result,
            listing_execution=executions[0],
            integrity_execution=executions[1],
            parser_result=parsed,
            archive_full_sha256=result.reuse_key.archive_full_sha256,
            volume_group_fingerprint=result.reuse_key.volume_group_fingerprint,
            signature_profile=signature.profile,
            storage_family=signature.storage_family,
            case_kind=case_kind,
            parser_profile=ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
            format_lock_profile=ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
            format_lock_sha256=ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
            compatibility_profile=signature.compatibility,
            members=private_members,
        ),
)


def _stream_listing(
    runner: _Runner,
    request: ArchiveContainerRequest,
    signature: ArchiveSignatureObservationV2,
    cancellation: CancellationProbe | None,
) -> tuple[ArchiveContainerRunResult, _ArchiveSevenZipLockedPrivateParseResult, bool]:
    chunks: queue.Queue[bytes | object] = queue.Queue(maxsize=1)
    parsed: list[_ArchiveSevenZipLockedPrivateParseResult] = []
    done = threading.Event()
    runner_active = threading.Event()
    parser_terminal = threading.Event()

    def iterable() -> Iterable[bytes]:
        while True:
            value = chunks.get()
            if value is _SENTINEL:
                return
            assert isinstance(value, bytes)
            yield value

    def parse() -> None:
        try:
            parsed.append(_parse_archive_7zip_slt_members_locked_private(signature, iterable()))
        finally:
            if runner_active.is_set():
                parser_terminal.set()
            done.set()

    def consume(chunk: bytes) -> bool:
        if not isinstance(chunk, bytes):
            return False
        while not done.is_set():
            try:
                chunks.put(chunk, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    worker = threading.Thread(target=parse, name="archive-locked-parser", daemon=False)
    worker.start()
    runner_active.set()
    try:
        try:
            run = runner.run(
                request,
                stdout_consumer=consume,
                stderr_classifier=_discard,
                cancellation=cancellation,
            )
        except Exception:
            run = ArchiveContainerRunResult(
                ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
                ArchiveContainerRunStatus.TOOL_FAILED,
            )
    finally:
        runner_active.clear()
        if not done.is_set():
            while not done.is_set():
                try:
                    chunks.put(_SENTINEL, timeout=0.05)
                    break
                except queue.Full:
                    continue
        worker.join(timeout=2.0)
    if worker.is_alive() or len(parsed) != 1:
        raise RuntimeError("archive parser worker did not quiesce")
    return run, parsed[0], parser_terminal.is_set()


def _is_supported_wrapper_signature(signature: ArchiveSignatureObservationV2) -> bool:
    return (
        signature.profile == ARCHIVE_SIGNATURE_PROFILE_V2
        and signature.compatibility == ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
        and signature.recognition_status is ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY
        and signature.storage_family is ArchiveStorageFamily.UNKNOWN
        and signature.outer_compression_kind in _WRAPPER_KINDS
    )


def _inner_tar_signature() -> ArchiveSignatureObservationV2:
    return ArchiveSignatureObservationV2(
        ARCHIVE_SIGNATURE_PROFILE_V2,
        ArchiveContainerClass.GENERIC_ARCHIVE,
        ArchiveSuffixKind.TAR,
        ArchivePublicationKind.NONE,
        ArchiveStorageFamily.TAR,
        ArchiveOuterCompressionKind.NONE,
        ArchiveRecognitionStatus.MATCHED,
        512,
        False,
    )


def _stream_wrapper_listing(
    runner: _Runner,
    request: ArchiveContainerRequest,
    signature: ArchiveSignatureObservationV2,
    operation: ArchiveWrapperOperation,
    cancellation: CancellationProbe | None,
) -> tuple[
    ArchiveWrapperContainerRunResult,
    _ArchiveSevenZipLockedPrivateParseResult,
    bool,
]:
    if operation is not ArchiveWrapperOperation.LISTING:
        raise ValueError("wrapper parser accepts only listing output")
    chunks: queue.Queue[bytes | object] = queue.Queue(maxsize=1)
    parsed: list[_ArchiveSevenZipLockedPrivateParseResult] = []
    done = threading.Event()
    runner_active = threading.Event()
    parser_terminal = threading.Event()

    def iterable() -> Iterable[bytes]:
        while True:
            value = chunks.get()
            if value is _SENTINEL:
                return
            assert isinstance(value, bytes)
            yield value

    def parse() -> None:
        try:
            parsed.append(
                _parse_archive_7zip_slt_members_locked_private(signature, iterable())
            )
        finally:
            if runner_active.is_set():
                parser_terminal.set()
            done.set()

    def consume(chunk: bytes) -> bool:
        if not isinstance(chunk, bytes):
            return False
        while not done.is_set():
            try:
                chunks.put(chunk, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    worker = threading.Thread(
        target=parse, name="archive-wrapper-locked-parser", daemon=False
    )
    worker.start()
    runner_active.set()
    try:
        try:
            run = runner.run_wrapper_pipeline(
                ArchiveWrapperContainerRequest(
                    request.volumes, operation, request.scan_roots
                ),
                stdout_consumer=consume,
                cancellation=cancellation,
            )
        except Exception:
            run = _failed_wrapper_run()
    finally:
        runner_active.clear()
        if not done.is_set():
            while not done.is_set():
                try:
                    chunks.put(_SENTINEL, timeout=0.05)
                    break
                except queue.Full:
                    continue
        worker.join(timeout=2.0)
    if worker.is_alive() or len(parsed) != 1:
        raise RuntimeError("archive wrapper parser worker did not quiesce")
    return run, parsed[0], parser_terminal.is_set()


def _run_wrapper_integrity(
    runner: _Runner,
    request: ArchiveContainerRequest,
    cancellation: CancellationProbe | None,
) -> ArchiveWrapperContainerRunResult:
    try:
        return runner.run_wrapper_pipeline(
            ArchiveWrapperContainerRequest(
                request.volumes, ArchiveWrapperOperation.INTEGRITY, request.scan_roots
            ),
            stdout_consumer=_discard,
            cancellation=cancellation,
        )
    except Exception:
        return _failed_wrapper_run()


def _failed_wrapper_run() -> ArchiveWrapperContainerRunResult:
    return ArchiveWrapperContainerRunResult(
        ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
        ArchiveContainerRunStatus.TOOL_FAILED,
    )


def _discard(chunk: bytes) -> bool:
    return isinstance(chunk, bytes)


def _reuse_key(archive_sha256: str, volume_fingerprint: str) -> ArchiveReuseKey:
    return ArchiveReuseKey(
        archive_sha256,
        volume_fingerprint,
        ARCHIVE_7ZIP_PROVIDER_ID,
        ARCHIVE_7ZIP_TOOL_VERSION,
        ARCHIVE_7ZIP_ADAPTER_VERSION,
        ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
        ARCHIVE_LISTING_PROFILE,
        ARCHIVE_EXTRACTION_PROFILE,
        ARCHIVE_SAFETY_POLICY_PROFILE,
        NONE_SECRET_VERSION,
    )


def _descriptor(member: ArchiveSevenZipSltMember) -> ArchiveMemberDescriptor:
    kind = _member_kind(member)
    return ArchiveMemberDescriptor(
        member.locator,
        kind,
        member.declared_compressed_bytes,
        member.declared_uncompressed_bytes,
        alternate_stream=member.alternate_stream,
        has_owner=member.user_present,
        has_group=member.group_present,
        has_special_flags=member.characteristics_present or member.anti_item,
    )


def _member_kind(member: ArchiveSevenZipSltMember) -> ArchiveMemberKind:
    if member.symbolic_link and member.hard_link:
        return ArchiveMemberKind.UNKNOWN
    if member.symbolic_link:
        return ArchiveMemberKind.SYMLINK
    if member.hard_link:
        return ArchiveMemberKind.HARDLINK
    if member.is_directory:
        return ArchiveMemberKind.DIRECTORY
    return ArchiveMemberKind.REGULAR_FILE


def _members(
    source: tuple[ArchiveSevenZipSltMember, ...],
    archive_observation_id: str,
    listing_execution_id: str,
    archive_sha256: str,
    volume_fingerprint: str,
) -> tuple[ArchiveMemberObservation, ...]:
    values = []
    for ordinal, item in enumerate(source):
        kind = _member_kind(item)
        encrypted = (
            ArchiveEncryptionStatus.DATA_ENCRYPTED
            if kind is ArchiveMemberKind.REGULAR_FILE and item.encrypted
            else ArchiveEncryptionStatus.NONE
        )
        values.append(
            ArchiveMemberObservation(
                "archive-member-observation/v1",
                archive_observation_id,
                volume_fingerprint,
                ordinal,
                build_archive_member_identity(
                    archive_full_sha256=archive_sha256,
                    volume_group_fingerprint=volume_fingerprint,
                    member_path_safe=item.locator,
                    member_ordinal=ordinal,
                ),
                item.locator,
                kind,
                item.declared_compressed_bytes,
                item.declared_uncompressed_bytes,
                crc_status=ArchiveMemberCrcStatus.NOT_TESTED,
                encryption_status=encrypted,
                listing_execution_id=listing_execution_id,
            )
        )
    return tuple(values)


def _encryption(members: tuple[ArchiveSevenZipSltMember, ...]) -> ArchiveEncryptionStatus:
    values = {
        member.encrypted
        for member in members
        if _member_kind(member) is ArchiveMemberKind.REGULAR_FILE
    }
    if not values or values == {False}:
        return ArchiveEncryptionStatus.NONE
    if values == {True}:
        return ArchiveEncryptionStatus.DATA_ENCRYPTED
    return ArchiveEncryptionStatus.MIXED


def _tool_execution(
    identity: str,
    capability: ToolCapability,
    started: datetime,
    finished: datetime,
    run: ArchiveContainerRunResult | ArchiveWrapperContainerRunResult,
    *,
    succeeded: bool,
) -> ToolExecution:
    status = (
        ToolExecutionStatus.CANCELLED
        if run.status is ArchiveContainerRunStatus.CANCELLED
        else ToolExecutionStatus.SUCCEEDED
        if succeeded
        else ToolExecutionStatus.FAILED
    )
    return ToolExecution(
        EntityId.new(),
        ARCHIVE_7ZIP_PROVIDER_ID,
        ARCHIVE_7ZIP_TOOL_VERSION,
        ARCHIVE_7ZIP_ADAPTER_VERSION,
        capability,
        identity,
        started,
        status,
        finished,
        _execution_exit_code(run),
        config_identity=ARCHIVE_PROVIDER_PROFILE,
        error_summary=(
            None if status is ToolExecutionStatus.SUCCEEDED else "ARCHIVE_PROVIDER_FAILED"
        ),
    )


def _execution_exit_code(
    run: ArchiveContainerRunResult | ArchiveWrapperContainerRunResult,
) -> int | None:
    if isinstance(run, ArchiveContainerRunResult):
        return run.exit_code
    if run.status is ArchiveContainerRunStatus.COMPLETED:
        return 0
    for value in (run.producer_exit_code, run.consumer_exit_code):
        if value not in (None, 0):
            return value
    return None


def _listing_status(
    run: ArchiveContainerRunResult | ArchiveWrapperContainerRunResult,
    parsed: ArchiveSevenZipSltParseStatus,
    parser_terminal: bool,
) -> ArchiveListingStatus:
    if run.status is ArchiveContainerRunStatus.CANCELLED:
        return ArchiveListingStatus.TOOL_FAILED
    runner_status = {
        ArchiveContainerRunStatus.TOOL_FAILED: ArchiveListingStatus.TOOL_FAILED,
        ArchiveContainerRunStatus.LIMIT_EXCEEDED: ArchiveListingStatus.LIMIT_EXCEEDED,
        ArchiveContainerRunStatus.TIMED_OUT: ArchiveListingStatus.TIMED_OUT,
        ArchiveContainerRunStatus.TOOL_UNAVAILABLE: ArchiveListingStatus.TOOL_UNAVAILABLE,
    }.get(run.status)
    if runner_status is not None:
        return runner_status
    if run.status is ArchiveContainerRunStatus.COMPLETED or (
        run.status is ArchiveContainerRunStatus.POLICY_REJECTED and parser_terminal
    ):
        if parsed is ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED:
            return ArchiveListingStatus.LIMIT_EXCEEDED
        if parsed is not ArchiveSevenZipSltParseStatus.PARSED:
            return ArchiveListingStatus.TOOL_FAILED
    if run.status is ArchiveContainerRunStatus.COMPLETED:
        return ArchiveListingStatus.LISTED
    if run.status is ArchiveContainerRunStatus.POLICY_REJECTED:
        return ArchiveListingStatus.POLICY_REJECTED
    return ArchiveListingStatus.TOOL_FAILED


def _integrity_status(
    run: ArchiveContainerRunResult | ArchiveWrapperContainerRunResult,
) -> ArchiveIntegrityStatus:
    if run.status is ArchiveContainerRunStatus.COMPLETED:
        return ArchiveIntegrityStatus.PASSED
    return {
        ArchiveContainerRunStatus.LIMIT_EXCEEDED: ArchiveIntegrityStatus.LIMIT_EXCEEDED,
        ArchiveContainerRunStatus.TIMED_OUT: ArchiveIntegrityStatus.TIMED_OUT,
        ArchiveContainerRunStatus.TOOL_UNAVAILABLE: ArchiveIntegrityStatus.TOOL_UNAVAILABLE,
        ArchiveContainerRunStatus.POLICY_REJECTED: ArchiveIntegrityStatus.POLICY_REJECTED,
    }.get(run.status, ArchiveIntegrityStatus.TOOL_FAILED)


def _blocked_policy(status: ArchiveListingStatus) -> ArchiveSafetyStatus:
    return (
        ArchiveSafetyStatus.LIMIT_EXCEEDED
        if status is ArchiveListingStatus.LIMIT_EXCEEDED
        else ArchiveSafetyStatus.POLICY_REJECTED
    )
