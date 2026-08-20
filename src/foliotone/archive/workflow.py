"""Synthetic-only archive listing contracts; no tool, IO, or secret channel."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from foliotone.archive.safety_policy import (
    ARCHIVE_SAFETY_POLICY_PROFILE,
    MAX_MEMBER_COUNT,
    MAX_SINGLE_MEMBER_BYTES,
    ArchiveMemberKind,
    ArchiveSafetyStatus,
    is_safe_archive_member_locator,
)
from foliotone.archive.secret_handle import ArchivePasswordAttemptStatus
from foliotone.archive.signatures import ArchiveListingStatus

ARCHIVE_LISTING_PROFILE: Final = "archive-listing/v1"
ARCHIVE_INTEGRITY_PROFILE: Final = "archive-integrity/v1"
ARCHIVE_EXTRACTION_PROFILE: Final = "archive-extraction/v1"
ARCHIVE_MEMBER_PROFILE: Final = "archive-member-observation/v1"
ARCHIVE_MEMBER_IDENTITY_PROFILE: Final = "archive-member-identity/v1"
ARCHIVE_LISTING_REUSE_PROFILE: Final = "archive-listing-reuse/v1"
ARCHIVE_MEMBER_REUSE_PROFILE: Final = "archive-member-reuse/v1"
NONE_SECRET_VERSION: Final = "NONE"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArchiveEncryptionStatus(StrEnum):
    NONE = "NONE"
    DATA_ENCRYPTED = "DATA_ENCRYPTED"
    HEADERS_ENCRYPTED = "HEADERS_ENCRYPTED"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ArchiveIntegrityStatus(StrEnum):
    NOT_TESTED = "NOT_TESTED"
    PASSED = "PASSED"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    UNSUPPORTED_METHOD = "UNSUPPORTED_METHOD"
    CORRUPT = "CORRUPT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TIMED_OUT = "TIMED_OUT"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_FAILED = "TOOL_FAILED"
    POLICY_REJECTED = "POLICY_REJECTED"


class ArchiveMemberCrcStatus(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_TESTED = "NOT_TESTED"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


@dataclass(frozen=True, slots=True)
class ArchiveReuseKey:
    archive_full_sha256: str
    volume_group_fingerprint: str
    tool_provider_id: str
    tool_version: str
    adapter_version: str
    parser_version: str
    listing_profile: str
    extraction_profile: str
    safety_profile: str
    secret_version: str = NONE_SECRET_VERSION

    def __post_init__(self) -> None:
        _require_sha256("archive_full_sha256", self.archive_full_sha256)
        _require_sha256("volume_group_fingerprint", self.volume_group_fingerprint)
        for name, value in (
            ("tool_provider_id", self.tool_provider_id),
            ("tool_version", self.tool_version),
            ("adapter_version", self.adapter_version),
            ("parser_version", self.parser_version),
            ("secret_version", self.secret_version),
        ):
            _require_opaque(name, value)
        if self.listing_profile != ARCHIVE_LISTING_PROFILE:
            raise ValueError("unsupported archive listing profile")
        if self.extraction_profile != ARCHIVE_EXTRACTION_PROFILE:
            raise ValueError("unsupported archive extraction profile")
        if self.safety_profile != ARCHIVE_SAFETY_POLICY_PROFILE:
            raise ValueError("unsupported archive safety profile")

    def _fields(self) -> tuple[str, ...]:
        return (
            self.archive_full_sha256,
            self.volume_group_fingerprint,
            self.tool_provider_id,
            self.tool_version,
            self.adapter_version,
            self.parser_version,
            self.listing_profile,
            self.extraction_profile,
            self.safety_profile,
            self.secret_version,
        )

    def member_key(self) -> tuple[str, ...]:
        return (ARCHIVE_MEMBER_REUSE_PROFILE, *self._fields())

    def listing_key(self) -> tuple[str, ...]:
        return (ARCHIVE_LISTING_REUSE_PROFILE, *self._fields())


@dataclass(frozen=True, slots=True)
class ArchiveMemberObservation:
    profile: str
    archive_observation_id: str
    volume_group_fingerprint: str
    member_ordinal: int
    member_identity: str
    member_path_safe: str = field(repr=False)
    member_kind: ArchiveMemberKind = ArchiveMemberKind.REGULAR_FILE
    declared_compressed_bytes: int | None = None
    declared_uncompressed_bytes: int | None = None
    observed_uncompressed_bytes: int | None = None
    member_sha256: str | None = None
    crc_status: ArchiveMemberCrcStatus = ArchiveMemberCrcStatus.NOT_TESTED
    encryption_status: ArchiveEncryptionStatus = ArchiveEncryptionStatus.NONE
    listing_execution_id: str = ""
    extraction_execution_id: str | None = None
    listing_profile: str = ARCHIVE_LISTING_PROFILE
    extraction_profile: str = ARCHIVE_EXTRACTION_PROFILE
    safety_profile: str = ARCHIVE_SAFETY_POLICY_PROFILE
    secret_version: str = NONE_SECRET_VERSION

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_MEMBER_PROFILE:
            raise ValueError("unsupported archive member profile")
        for name, value in (
            ("archive_observation_id", self.archive_observation_id),
            ("listing_execution_id", self.listing_execution_id),
            ("secret_version", self.secret_version),
        ):
            _require_opaque(name, value)
        _require_sha256("volume_group_fingerprint", self.volume_group_fingerprint)
        _require_sha256("member_identity", self.member_identity)
        if (
            isinstance(self.member_ordinal, bool)
            or not isinstance(self.member_ordinal, int)
            or self.member_ordinal < 0
        ):
            raise ValueError("member_ordinal must be a nonnegative integer")
        if not is_safe_archive_member_locator(self.member_path_safe):
            raise ValueError("member_path_safe violates archive safety policy")
        if not isinstance(self.member_kind, ArchiveMemberKind):
            raise ValueError("member_kind must be ArchiveMemberKind")
        for size_name, size_value in (
            ("declared_compressed_bytes", self.declared_compressed_bytes),
            ("declared_uncompressed_bytes", self.declared_uncompressed_bytes),
        ):
            _require_optional_size(size_name, size_value)
        if not isinstance(self.crc_status, ArchiveMemberCrcStatus):
            raise ValueError("crc_status must be ArchiveMemberCrcStatus")
        if not isinstance(self.encryption_status, ArchiveEncryptionStatus):
            raise ValueError("encryption_status must be ArchiveEncryptionStatus")
        if self.listing_profile != ARCHIVE_LISTING_PROFILE:
            raise ValueError("unsupported archive listing profile")
        if self.extraction_profile != ARCHIVE_EXTRACTION_PROFILE:
            raise ValueError("unsupported archive extraction profile")
        if self.safety_profile != ARCHIVE_SAFETY_POLICY_PROFILE:
            raise ValueError("unsupported archive safety profile")

        trio = (
            self.extraction_execution_id,
            self.observed_uncompressed_bytes,
            self.member_sha256,
        )
        if any(value is None for value in trio) and any(value is not None for value in trio):
            raise ValueError("extraction fields are jointly nullable")
        if self.extraction_execution_id is not None:
            _require_opaque("extraction_execution_id", self.extraction_execution_id)
            _require_optional_size("observed_uncompressed_bytes", self.observed_uncompressed_bytes)
            assert self.member_sha256 is not None
            _require_sha256("member_sha256", self.member_sha256)


@dataclass(frozen=True, slots=True)
class ArchiveListingResult:
    listing_status: ArchiveListingStatus
    execution_id: str
    encryption_status: ArchiveEncryptionStatus
    reuse_key: ArchiveReuseKey
    integrity_status: ArchiveIntegrityStatus = ArchiveIntegrityStatus.NOT_TESTED
    password_attempt_status: ArchivePasswordAttemptStatus = (
        ArchivePasswordAttemptStatus.NOT_ATTEMPTED
    )
    extraction_policy_status: ArchiveSafetyStatus = ArchiveSafetyStatus.ACCEPTED
    members: tuple[ArchiveMemberObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.listing_status, ArchiveListingStatus):
            raise ValueError("listing_status must be ArchiveListingStatus")
        _require_opaque("execution_id", self.execution_id)
        if not isinstance(self.encryption_status, ArchiveEncryptionStatus):
            raise ValueError("encryption_status must be ArchiveEncryptionStatus")
        if not isinstance(self.reuse_key, ArchiveReuseKey):
            raise ValueError("reuse_key must be ArchiveReuseKey")
        if not isinstance(self.integrity_status, ArchiveIntegrityStatus):
            raise ValueError("integrity_status must be ArchiveIntegrityStatus")
        if not isinstance(self.password_attempt_status, ArchivePasswordAttemptStatus):
            raise ValueError("password_attempt_status must be ArchivePasswordAttemptStatus")
        if not isinstance(self.extraction_policy_status, ArchiveSafetyStatus):
            raise ValueError("extraction_policy_status must be ArchiveSafetyStatus")
        if not isinstance(self.members, tuple) or len(self.members) > MAX_MEMBER_COUNT:
            raise ValueError("members exceed the archive listing bound")
        if any(not isinstance(member, ArchiveMemberObservation) for member in self.members):
            raise ValueError("members must contain ArchiveMemberObservation values")
        if self.listing_status is not ArchiveListingStatus.LISTED and self.members:
            raise ValueError("non-listed archive result cannot expose members")
        if (
            self.listing_status is not ArchiveListingStatus.LISTED
            and self.extraction_policy_status is ArchiveSafetyStatus.ACCEPTED
        ):
            raise ValueError("failed listing cannot permit extraction")
        if self.encryption_status is ArchiveEncryptionStatus.HEADERS_ENCRYPTED:
            if self.members or self.listing_status is not ArchiveListingStatus.PASSWORD_REQUIRED:
                raise ValueError("encrypted headers require a password-required empty listing")
        expected_attempt = (
            ArchivePasswordAttemptStatus.NOT_ATTEMPTED
            if self.encryption_status
            in {ArchiveEncryptionStatus.NONE, ArchiveEncryptionStatus.UNKNOWN}
            else ArchivePasswordAttemptStatus.SECURE_CHANNEL_UNAVAILABLE
        )
        if self.password_attempt_status is not expected_attempt:
            raise ValueError("no secure archive secret channel is available")
        extraction_must_be_blocked = (
            self.encryption_status is not ArchiveEncryptionStatus.NONE
            or any(
                member.declared_compressed_bytes is None
                or member.declared_uncompressed_bytes is None
                for member in self.members
            )
        )
        if (
            extraction_must_be_blocked
            and self.extraction_policy_status is ArchiveSafetyStatus.ACCEPTED
        ):
            raise ValueError("unextractable listing requires a blocked policy status")
        ordinals = tuple(member.member_ordinal for member in self.members)
        if ordinals != tuple(range(len(self.members))):
            raise ValueError("archive members must use contiguous canonical ordinals")
        if any(member.listing_execution_id != self.execution_id for member in self.members):
            raise ValueError("archive members must bind the listing execution")
        if len({member.member_identity for member in self.members}) != len(self.members):
            raise ValueError("archive member identities must be unique")
        if any(
            member.volume_group_fingerprint != self.reuse_key.volume_group_fingerprint
            or member.secret_version != self.reuse_key.secret_version
            for member in self.members
        ):
            raise ValueError("archive members must match the result reuse lineage")
        if any(
            member.member_identity
            != build_archive_member_identity(
                archive_full_sha256=self.reuse_key.archive_full_sha256,
                volume_group_fingerprint=self.reuse_key.volume_group_fingerprint,
                member_path_safe=member.member_path_safe,
                member_ordinal=member.member_ordinal,
                listing_profile=member.listing_profile,
            )
            for member in self.members
        ):
            raise ValueError("archive member identity does not match material lineage")
        if self.encryption_status is ArchiveEncryptionStatus.NONE and any(
            member.encryption_status is not ArchiveEncryptionStatus.NONE for member in self.members
        ):
            raise ValueError("member encryption must match the listing")
        if self.encryption_status is ArchiveEncryptionStatus.DATA_ENCRYPTED and any(
            member.encryption_status is not ArchiveEncryptionStatus.DATA_ENCRYPTED
            for member in self.members
        ):
            raise ValueError("member encryption must match the listing")
        regular_members = tuple(
            member
            for member in self.members
            if member.member_kind is ArchiveMemberKind.REGULAR_FILE
        )
        extracted = tuple(member.extraction_execution_id is not None for member in regular_members)
        if any(extracted) and not all(extracted):
            raise ValueError("partial extraction cannot form member evidence")
        if any(extracted):
            if (
                self.encryption_status is not ArchiveEncryptionStatus.NONE
                or self.extraction_policy_status is not ArchiveSafetyStatus.ACCEPTED
                or self.integrity_status is not ArchiveIntegrityStatus.PASSED
            ):
                raise ValueError("extracted members require a safe successful result")
            if any(
                member.declared_uncompressed_bytes is None
                or member.observed_uncompressed_bytes != member.declared_uncompressed_bytes
                or member.crc_status
                not in {ArchiveMemberCrcStatus.MATCHED, ArchiveMemberCrcStatus.NOT_AVAILABLE}
                for member in regular_members
            ):
                raise ValueError("extracted member size or CRC evidence is inconsistent")


class FakeArchiveListingProvider:
    """Return one validated synthetic result without accepting secret or command input."""

    def __init__(self, result: ArchiveListingResult) -> None:
        if not isinstance(result, ArchiveListingResult):
            raise ValueError("result must be ArchiveListingResult")
        self._result = result

    def list(self) -> ArchiveListingResult:
        return self._result


class FakeArchiveListingReuseStore:
    """Keep only successful synthetic snapshots; failures never replace them."""

    def __init__(self) -> None:
        self._successful: dict[tuple[str, ...], ArchiveListingResult] = {}

    def remember(
        self, key: ArchiveReuseKey, result: ArchiveListingResult
    ) -> ArchiveListingResult | None:
        if not isinstance(key, ArchiveReuseKey) or not isinstance(result, ArchiveListingResult):
            raise ValueError("reuse inputs must use archive contracts")
        if result.reuse_key != key:
            raise ValueError("archive result does not match the reuse key")
        cache_key = key.listing_key()
        if any(
            member.volume_group_fingerprint != key.volume_group_fingerprint
            or member.secret_version != key.secret_version
            for member in result.members
        ):
            raise ValueError("archive listing does not match the reuse lineage")
        existing = self._successful.get(cache_key)
        if result.listing_status is not ArchiveListingStatus.LISTED:
            return existing
        if existing is not None and existing != result:
            raise ValueError("divergent successful archive listing reuse")
        self._successful[cache_key] = result
        return result

    def get(self, key: ArchiveReuseKey) -> ArchiveListingResult | None:
        if not isinstance(key, ArchiveReuseKey):
            raise ValueError("key must be ArchiveReuseKey")
        return self._successful.get(key.listing_key())


def build_archive_member_identity(
    *,
    archive_full_sha256: str,
    volume_group_fingerprint: str,
    member_path_safe: str,
    member_ordinal: int,
    listing_profile: str = ARCHIVE_LISTING_PROFILE,
) -> str:
    """Build the domain-separated identity without exposing the private locator."""

    _require_sha256("archive_full_sha256", archive_full_sha256)
    _require_sha256("volume_group_fingerprint", volume_group_fingerprint)
    if not is_safe_archive_member_locator(member_path_safe):
        raise ValueError("member_path_safe violates archive safety policy")
    if (
        isinstance(member_ordinal, bool)
        or not isinstance(member_ordinal, int)
        or member_ordinal < 0
    ):
        raise ValueError("member_ordinal must be a nonnegative integer")
    if listing_profile != ARCHIVE_LISTING_PROFILE:
        raise ValueError("unsupported archive listing profile")
    material = json.dumps(
        {
            "archive_full_sha256": archive_full_sha256,
            "listing_profile": listing_profile,
            "member_ordinal": member_ordinal,
            "member_path_safe": unicodedata.normalize("NFC", member_path_safe),
            "volume_group_fingerprint": volume_group_fingerprint,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(
        ARCHIVE_MEMBER_IDENTITY_PROFILE.encode("ascii") + b"\x00" + material
    ).hexdigest()


def _require_sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


def _require_opaque(name: str, value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"{name} must be a bounded path-free value")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be a bounded path-free value") from error
    if (
        len(encoded) > 1_024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in value for character in ("/", "\\", ":"))
    ):
        raise ValueError(f"{name} must be a bounded path-free value")


def _require_optional_size(name: str, value: int | None) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= MAX_SINGLE_MEMBER_BYTES
    ):
        raise ValueError(f"{name} exceeds the member bound")
