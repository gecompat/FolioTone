"""Private, path-free extraction validation for the future archive runner.

This module deliberately has no public export and cannot start an extraction.
It consumes an already sealed provider handoff and an opaque, short-lived
workspace capability supplied by a later runner boundary.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final, Protocol

from foliotone.archive.provider import (
    _EXTRACTABLE_LOCKED_CASES,
    ARCHIVE_PROVIDER_PROFILE,
    ArchiveProviderOutcome,
    _ArchiveExtractionHandoff,
    _ArchiveExtractionMemberHandoff,
    _member_kind,
)
from foliotone.archive.safety_policy import (
    MAX_EXTRACTION_SECONDS,
    MAX_MEMBER_COUNT,
    MAX_SINGLE_MEMBER_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_WORKSPACE_BYTES,
    ArchiveMemberKind,
    ArchiveSafetyStatus,
    is_safe_archive_member_locator,
)
from foliotone.archive.sevenzip_slt import (
    ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
    ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
    ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
    ArchiveSevenZipSltParseStatus,
    _ArchiveSevenZipLockedPrivateParseResult,
)
from foliotone.archive.signatures import (
    ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
    ARCHIVE_SIGNATURE_PROFILE_V2,
    ArchiveListingStatus,
    ArchiveStorageFamily,
)
from foliotone.archive.workflow import (
    ArchiveEncryptionStatus,
    ArchiveIntegrityStatus,
    ArchiveListingResult,
    ArchiveMemberCrcStatus,
    build_archive_member_identity,
)
from foliotone.core import ToolCapability, ToolExecutionStatus

_EXTRACTION_VALIDATOR_PROFILE: Final = "archive-extraction-validator/v1"
_MAX_STREAM_CHUNK_BYTES: Final = 1_048_576
_MAX_STREAM_CHUNK_COUNT: Final = (
    MAX_SINGLE_MEMBER_BYTES + _MAX_STREAM_CHUNK_BYTES - 1
) // _MAX_STREAM_CHUNK_BYTES
_EVIDENCE_FACTORY_TOKEN: Final = object()


class _ArchiveExtractionValidationError(ValueError):
    """A deliberately detail-free failure at the private extraction boundary."""

    def __init__(self) -> None:
        super().__init__("archive extraction validation failed")


@dataclass(frozen=True, slots=True)
class _ExtractionValidationLimits:
    """Closed, in-memory limits supplied by the future private runner."""

    start_monotonic: float
    deadline_monotonic: float
    max_member_count: int = MAX_MEMBER_COUNT
    max_single_member_bytes: int = MAX_SINGLE_MEMBER_BYTES
    max_total_uncompressed_bytes: int = MAX_TOTAL_UNCOMPRESSED_BYTES
    max_workspace_bytes: int = MAX_WORKSPACE_BYTES

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in (self.start_monotonic, self.deadline_monotonic)
        ) or not (
            self.start_monotonic
            <= self.deadline_monotonic
            <= self.start_monotonic + MAX_EXTRACTION_SECONDS
        ):
            raise ValueError("extraction validation limits are invalid")
        for value, maximum in (
            (self.max_member_count, MAX_MEMBER_COUNT),
            (self.max_single_member_bytes, MAX_SINGLE_MEMBER_BYTES),
            (self.max_total_uncompressed_bytes, MAX_TOTAL_UNCOMPRESSED_BYTES),
            (self.max_workspace_bytes, MAX_WORKSPACE_BYTES),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > maximum
            ):
                raise ValueError("extraction validation limits are invalid")


@dataclass(frozen=True, slots=True)
class _ObservedWorkspaceMember:
    """One frozen, path-free-capability observation; locators never render."""

    locator: str = field(repr=False)
    kind: ArchiveMemberKind = field(repr=False)
    observed_size: int = field(repr=False)
    observation_token: str = field(repr=False)
    link_count: int = field(repr=False, default=1)
    has_special_metadata: bool = field(repr=False, default=False)

    def __post_init__(self) -> None:
        if not is_safe_archive_member_locator(self.locator):
            raise ValueError("workspace observation is invalid")
        if self.kind not in {ArchiveMemberKind.REGULAR_FILE, ArchiveMemberKind.DIRECTORY}:
            raise ValueError("workspace observation is invalid")
        if (
            isinstance(self.observed_size, bool)
            or not isinstance(self.observed_size, int)
            or self.observed_size < 0
            or isinstance(self.link_count, bool)
            or not isinstance(self.link_count, int)
            or self.link_count != 1
            or not isinstance(self.has_special_metadata, bool)
            or self.has_special_metadata
            or not isinstance(self.observation_token, str)
            or not self.observation_token
        ):
            raise ValueError("workspace observation is invalid")
        if self.kind is ArchiveMemberKind.DIRECTORY and self.observed_size != 0:
            raise ValueError("workspace observation is invalid")


class _BorrowedWorkspaceCapability(Protocol):
    """Narrow synchronous capability; no paths, FDs, cleanup, or process control."""

    def snapshot(self) -> tuple[_ObservedWorkspaceMember, ...]: ...

    def stream(self, member: _ObservedWorkspaceMember) -> Iterable[bytes]: ...

    def unchanged(self, member: _ObservedWorkspaceMember) -> bool: ...

    def now_monotonic(self) -> float: ...


@dataclass(frozen=True, slots=True)
class _ProvisionalMemberEvidence:
    """Non-persistent evidence without a locator or listed CRC value."""

    member_ordinal: int
    member_identity: str
    declared_uncompressed_bytes: int
    observed_uncompressed_bytes: int
    member_sha256: str
    crc_status: ArchiveMemberCrcStatus

    def __post_init__(self) -> None:
        if (
            isinstance(self.member_ordinal, bool)
            or not isinstance(self.member_ordinal, int)
            or self.member_ordinal < 0
            or not isinstance(self.member_identity, str)
            or len(self.member_identity) != 64
            or any(character not in "0123456789abcdef" for character in self.member_identity)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (self.declared_uncompressed_bytes, self.observed_uncompressed_bytes)
            )
            or self.observed_uncompressed_bytes != self.declared_uncompressed_bytes
            or not isinstance(self.member_sha256, str)
            or len(self.member_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.member_sha256)
            or self.crc_status
            not in {ArchiveMemberCrcStatus.MATCHED, ArchiveMemberCrcStatus.NOT_AVAILABLE}
        ):
            raise ValueError("provisional extraction evidence is invalid")


@dataclass(frozen=True, slots=True)
class _ProvisionalExtractionEvidence:
    """All-or-nothing, in-memory-only result for a later runner to release."""

    profile: str
    members: tuple[_ProvisionalMemberEvidence, ...]
    _source_ordinals: tuple[int, ...] = field(repr=False)
    _factory_token: object = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.profile != _EXTRACTION_VALIDATOR_PROFILE
            or self._factory_token is not _EVIDENCE_FACTORY_TOKEN
            or not isinstance(self.members, tuple)
            or any(not isinstance(member, _ProvisionalMemberEvidence) for member in self.members)
            or not isinstance(self._source_ordinals, tuple)
            or tuple(member.member_ordinal for member in self.members) != self._source_ordinals
            or len(set(self._source_ordinals)) != len(self._source_ordinals)
        ):
            raise ValueError("provisional extraction evidence is invalid")


def _validate_private_extraction_workspace(
    handoff: _ArchiveExtractionHandoff,
    capability: _BorrowedWorkspaceCapability,
    limits: _ExtractionValidationLimits,
) -> _ProvisionalExtractionEvidence:
    """Validate one frozen workspace without authorizing or publishing extraction.

    Every error is reduced to a fixed exception and no result is constructed
    before the complete observation, stream, hash and post-stream identity
    checks have succeeded.
    """

    try:
        if not isinstance(handoff, _ArchiveExtractionHandoff) or not isinstance(
            limits, _ExtractionValidationLimits
        ):
            raise _ArchiveExtractionValidationError()
        _validate_sealed_handoff(handoff)
        deadline = _DeadlineGuard(capability, limits)
        deadline.check()
        observed = capability.snapshot()
        if not isinstance(observed, tuple):
            raise _ArchiveExtractionValidationError()
        _validate_workspace_shape(handoff, observed, limits)

        expected_files = tuple(
            member
            for member in handoff.members
            if member.member_kind is ArchiveMemberKind.REGULAR_FILE
        )
        by_locator = {member.member_locator: member for member in expected_files}
        evidence: list[_ProvisionalMemberEvidence] = []
        total = 0
        for observed_member in observed:
            if observed_member.kind is ArchiveMemberKind.DIRECTORY:
                continue
            deadline.check()
            listed = by_locator.get(observed_member.locator)
            if (
                listed is None
                or observed_member.observed_size != listed.declared_uncompressed_bytes
            ):
                raise _ArchiveExtractionValidationError()
            if (
                observed_member.observed_size > limits.max_single_member_bytes
                or total + observed_member.observed_size > limits.max_total_uncompressed_bytes
                or total + observed_member.observed_size > limits.max_workspace_bytes
            ):
                raise _ArchiveExtractionValidationError()
            observed_size, sha256, crc32 = _stream_member(
                capability, observed_member, total, limits, deadline
            )
            if (
                observed_size != observed_member.observed_size
                or observed_size != listed.declared_uncompressed_bytes
                or not capability.unchanged(observed_member)
            ):
                raise _ArchiveExtractionValidationError()
            if listed.listed_crc32 is not None and crc32 != listed.listed_crc32:
                raise _ArchiveExtractionValidationError()
            total += observed_size
            evidence.append(
                _ProvisionalMemberEvidence(
                    listed.member_ordinal,
                    listed.member_identity,
                    listed.declared_uncompressed_bytes,
                    observed_size,
                    sha256,
                    (
                        ArchiveMemberCrcStatus.MATCHED
                        if listed.listed_crc32 is not None
                        else ArchiveMemberCrcStatus.NOT_AVAILABLE
                    ),
                )
            )
        deadline.check()
        if len(evidence) != len(expected_files):
            raise _ArchiveExtractionValidationError()
        evidence.sort(key=lambda item: item.member_ordinal)
        source_ordinals = tuple(member.member_ordinal for member in expected_files)
        return _ProvisionalExtractionEvidence(
            _EXTRACTION_VALIDATOR_PROFILE,
            tuple(evidence),
            source_ordinals,
            _EVIDENCE_FACTORY_TOKEN,
        )
    except _ArchiveExtractionValidationError:
        raise
    except Exception:
        raise _ArchiveExtractionValidationError() from None


def _validate_sealed_handoff(handoff: _ArchiveExtractionHandoff) -> None:
    outcome = handoff.outcome
    listing = handoff.listing_result
    parsed = handoff.parser_result
    if (
        not isinstance(outcome, ArchiveProviderOutcome)
        or not isinstance(listing, ArchiveListingResult)
        or not isinstance(parsed, _ArchiveSevenZipLockedPrivateParseResult)
        or outcome.profile != ARCHIVE_PROVIDER_PROFILE
        or outcome._extraction_handoff is not handoff
        or outcome._private_listing_result is not listing
        or outcome._private_parser_result is not parsed
        or outcome.result is None
        or len(outcome.executions) != 2
        or outcome.executions[0] is not handoff.listing_execution
        or outcome.executions[1] is not handoff.integrity_execution
        or listing.listing_execution is not outcome.result.listing_execution
        or listing.integrity_execution is not outcome.result.integrity_execution
        or listing.reuse_key is not outcome.result.reuse_key
        or str(handoff.listing_execution.id) != listing.listing_execution.execution_id
        or str(handoff.integrity_execution.id) != listing.integrity_execution.execution_id
        or handoff.listing_execution.capability is not ToolCapability.ARCHIVE_LISTING
        or handoff.integrity_execution.capability is not ToolCapability.ARCHIVE_INTEGRITY
        or handoff.listing_execution.status is not ToolExecutionStatus.SUCCEEDED
        or handoff.integrity_execution.status is not ToolExecutionStatus.SUCCEEDED
        or outcome.result.listing_status is not ArchiveListingStatus.LISTED
        or outcome.result.integrity_status is not ArchiveIntegrityStatus.PASSED
        or outcome.result.encryption_status is not ArchiveEncryptionStatus.NONE
        or outcome.result.extraction_policy_status is not ArchiveSafetyStatus.ACCEPTED
        or handoff.archive_full_sha256 != listing.reuse_key.archive_full_sha256
        or handoff.volume_group_fingerprint != listing.reuse_key.volume_group_fingerprint
        or handoff.signature_profile != ARCHIVE_SIGNATURE_PROFILE_V2
        or not isinstance(handoff.storage_family, ArchiveStorageFamily)
        or (handoff.storage_family, handoff.case_kind) not in _EXTRACTABLE_LOCKED_CASES
        or handoff.parser_profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE
        or handoff.format_lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE
        or handoff.format_lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256
        or handoff.compatibility_profile != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
    ):
        raise _ArchiveExtractionValidationError()
    public_parse = parsed.public
    if (
        public_parse.status is not ArchiveSevenZipSltParseStatus.PARSED
        or public_parse.signature_profile != handoff.signature_profile
        or public_parse.storage_family is not handoff.storage_family
        or public_parse.case_kind is not handoff.case_kind
        or public_parse.profile != handoff.parser_profile
        or public_parse.lock_profile != handoff.format_lock_profile
        or public_parse.lock_sha256 != handoff.format_lock_sha256
        or public_parse.compatibility != handoff.compatibility_profile
        or not isinstance(handoff.members, tuple)
        or len(handoff.members) != len(listing.members)
        or len(handoff.members) != len(parsed.members)
        or len(handoff.members) != outcome.result.member_count
        or tuple(member.member_ordinal for member in handoff.members)
        != tuple(range(len(handoff.members)))
    ):
        raise _ArchiveExtractionValidationError()
    for private, listed, parser_member in zip(
        handoff.members, listing.members, parsed.members, strict=True
    ):
        if not isinstance(private, _ArchiveExtractionMemberHandoff):
            raise _ArchiveExtractionValidationError()
        expected_identity = build_archive_member_identity(
            archive_full_sha256=handoff.archive_full_sha256,
            volume_group_fingerprint=handoff.volume_group_fingerprint,
            member_path_safe=private.member_locator,
            member_ordinal=private.member_ordinal,
        )
        if (
            private.member_locator != listed.member_path_safe
            or private.member_locator != parser_member.locator
            or private.member_ordinal != listed.member_ordinal
            or private.member_kind is not listed.member_kind
            or private.member_kind is not _member_kind(parser_member)
            or private.declared_compressed_bytes != listed.declared_compressed_bytes
            or private.declared_compressed_bytes != parser_member.declared_compressed_bytes
            or private.declared_uncompressed_bytes != listed.declared_uncompressed_bytes
            or private.declared_uncompressed_bytes != parser_member.declared_uncompressed_bytes
            or private.listed_crc32 != parser_member.crc32
            or private.member_identity != listed.member_identity
            or private.member_identity != expected_identity
            or private.is_directory is not parser_member.is_directory
            or private.encrypted is not parser_member.encrypted
            or private.symbolic_link is not parser_member.symbolic_link
            or private.hard_link is not parser_member.hard_link
            or private.user_present is not parser_member.user_present
            or private.group_present is not parser_member.group_present
            or private.characteristics_present is not parser_member.characteristics_present
            or private.alternate_stream is not parser_member.alternate_stream
            or private.anti_item is not parser_member.anti_item
        ):
            raise _ArchiveExtractionValidationError()


def _validate_workspace_shape(
    handoff: _ArchiveExtractionHandoff,
    observed: tuple[_ObservedWorkspaceMember, ...],
    limits: _ExtractionValidationLimits,
) -> None:
    if len(observed) > limits.max_member_count:
        raise _ArchiveExtractionValidationError()
    expected: dict[str, tuple[str, ArchiveMemberKind]] = {}
    required_directories: dict[str, str] = {}
    for member in handoff.members:
        key = _canonical_locator(member.member_locator)
        if key in expected:
            raise _ArchiveExtractionValidationError()
        expected[key] = (member.member_locator, member.member_kind)
        for parent in _parent_locators(member.member_locator):
            parent_key = _canonical_locator(parent)
            prior = required_directories.setdefault(parent_key, parent)
            if prior != parent:
                raise _ArchiveExtractionValidationError()
    allowed_directories = dict(required_directories)
    for key, (locator, kind) in expected.items():
        if kind is ArchiveMemberKind.DIRECTORY:
            prior = allowed_directories.setdefault(key, locator)
            if prior != locator:
                raise _ArchiveExtractionValidationError()
    observed_keys: set[str] = set()
    for observed_member in observed:
        if not isinstance(observed_member, _ObservedWorkspaceMember):
            raise _ArchiveExtractionValidationError()
        key = _canonical_locator(observed_member.locator)
        if key in observed_keys:
            raise _ArchiveExtractionValidationError()
        observed_keys.add(key)
        expected_item = expected.get(key)
        if observed_member.kind is ArchiveMemberKind.REGULAR_FILE:
            if expected_item != (observed_member.locator, ArchiveMemberKind.REGULAR_FILE):
                raise _ArchiveExtractionValidationError()
        elif observed_member.kind is ArchiveMemberKind.DIRECTORY:
            if allowed_directories.get(key) != observed_member.locator:
                raise _ArchiveExtractionValidationError()
        else:
            raise _ArchiveExtractionValidationError()
    expected_files = {
        key
        for key, (_, kind) in expected.items()
        if kind is ArchiveMemberKind.REGULAR_FILE
    }
    expected_directories = {
        key for key, (_, kind) in expected.items() if kind is ArchiveMemberKind.DIRECTORY
    }
    observed_files = {
        _canonical_locator(member.locator)
        for member in observed
        if member.kind is ArchiveMemberKind.REGULAR_FILE
    }
    observed_directories = {
        _canonical_locator(member.locator)
        for member in observed
        if member.kind is ArchiveMemberKind.DIRECTORY
    }
    if (
        observed_files != expected_files
        or observed_directories != set(allowed_directories)
        or not expected_directories <= observed_directories
    ):
        raise _ArchiveExtractionValidationError()
    expected_file_order = tuple(
        member.member_locator
        for member in handoff.members
        if member.member_kind is ArchiveMemberKind.REGULAR_FILE
    )
    observed_file_order = tuple(
        member.locator
        for member in observed
        if member.kind is ArchiveMemberKind.REGULAR_FILE
    )
    if observed_file_order != expected_file_order:
        raise _ArchiveExtractionValidationError()


def _stream_member(
    capability: _BorrowedWorkspaceCapability,
    member: _ObservedWorkspaceMember,
    total_before_member: int,
    limits: _ExtractionValidationLimits,
    deadline: _DeadlineGuard,
) -> tuple[int, str, str]:
    digest = hashlib.sha256()
    crc32 = 0
    observed_size = 0
    chunk_count = 0
    for chunk in capability.stream(member):
        deadline.check()
        chunk_count += 1
        if (
            not isinstance(chunk, bytes)
            or not chunk
            or len(chunk) > _MAX_STREAM_CHUNK_BYTES
            or chunk_count > _MAX_STREAM_CHUNK_COUNT
        ):
            raise _ArchiveExtractionValidationError()
        observed_size += len(chunk)
        if (
            observed_size > limits.max_single_member_bytes
            or total_before_member + observed_size > limits.max_total_uncompressed_bytes
            or total_before_member + observed_size > limits.max_workspace_bytes
        ):
            raise _ArchiveExtractionValidationError()
        digest.update(chunk)
        crc32 = zlib.crc32(chunk, crc32)
    deadline.check()
    return observed_size, digest.hexdigest(), f"{crc32 & 0xFFFFFFFF:08X}"


@dataclass(slots=True)
class _DeadlineGuard:
    capability: _BorrowedWorkspaceCapability
    limits: _ExtractionValidationLimits
    _last: float = field(init=False)

    def __post_init__(self) -> None:
        self._last = self.limits.start_monotonic

    def check(self) -> None:
        now = self.capability.now_monotonic()
        if (
            not isinstance(now, (int, float))
            or isinstance(now, bool)
            or not math.isfinite(now)
            or now < self._last
            or now > self.limits.deadline_monotonic
        ):
            raise _ArchiveExtractionValidationError()
        self._last = float(now)


def _canonical_locator(locator: str) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in locator.split("/"))


def _parent_locators(locator: str) -> tuple[str, ...]:
    parts = locator.split("/")
    return tuple("/".join(parts[:index]) for index in range(1, len(parts)))
