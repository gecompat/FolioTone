"""Pure, fail-closed archive member and budget validation for ADR-0038."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import islice
from typing import Final

ARCHIVE_SAFETY_POLICY_PROFILE: Final = "archive-safety-policy/v1"
MAX_MEMBER_COUNT: Final = 10_000
MAX_VOLUME_COUNT: Final = 256
MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 8_589_934_592
MAX_SINGLE_MEMBER_BYTES: Final = 2_147_483_648
MAX_COMPRESSION_RATIO: Final = 1_000
MAX_MEMBER_PATH_CODEPOINTS: Final = 1_024
MAX_MEMBER_PATH_UTF8_BYTES: Final = 4_096
MAX_MEMBER_PATH_SEGMENTS: Final = 128
MAX_NESTED_DEPTH: Final = 0
MAX_LISTING_SECONDS: Final = 60
MAX_INTEGRITY_SECONDS: Final = 300
MAX_EXTRACTION_SECONDS: Final = 600
MAX_STDOUT_BYTES: Final = 8_388_608
MAX_STDERR_BYTES: Final = 1_048_576
MAX_WORKSPACE_BYTES: Final = 8_589_934_592
MIN_WORKSPACE_FREE_RESERVE_BYTES: Final = 1_073_741_824
MAX_TOOL_MEMORY_BYTES: Final = 1_073_741_824
MAX_TOOL_PROCESSES: Final = 1
MAX_CONCURRENT_ARCHIVE_JOBS: Final = 2
MAX_CONCURRENT_JOBS_PER_ARCHIVE: Final = 1


class ArchiveMemberKind(StrEnum):
    REGULAR_FILE = "REGULAR_FILE"
    DIRECTORY = "DIRECTORY"
    SYMLINK = "SYMLINK"
    HARDLINK = "HARDLINK"
    REPARSE_POINT = "REPARSE_POINT"
    FIFO = "FIFO"
    SOCKET = "SOCKET"
    BLOCK_DEVICE = "BLOCK_DEVICE"
    CHARACTER_DEVICE = "CHARACTER_DEVICE"
    UNKNOWN = "UNKNOWN"


class ArchiveSafetyStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    POLICY_REJECTED = "POLICY_REJECTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class ArchiveSafetyViolation(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    MEMBER_COUNT_LIMIT = "MEMBER_COUNT_LIMIT"
    VOLUME_COUNT_LIMIT = "VOLUME_COUNT_LIMIT"
    UNKNOWN_SIZE = "UNKNOWN_SIZE"
    NEGATIVE_SIZE = "NEGATIVE_SIZE"
    MEMBER_SIZE_LIMIT = "MEMBER_SIZE_LIMIT"
    TOTAL_UNCOMPRESSED_LIMIT = "TOTAL_UNCOMPRESSED_LIMIT"
    COMPRESSION_RATIO_LIMIT = "COMPRESSION_RATIO_LIMIT"
    PATH_INVALID = "PATH_INVALID"
    PATH_COLLISION = "PATH_COLLISION"
    PARENT_CHILD_CONFLICT = "PARENT_CHILD_CONFLICT"
    MEMBER_KIND_REJECTED = "MEMBER_KIND_REJECTED"
    METADATA_REJECTED = "METADATA_REJECTED"
    NESTED_ARCHIVE_REJECTED = "NESTED_ARCHIVE_REJECTED"
    WORKSPACE_LIMIT = "WORKSPACE_LIMIT"
    WORKSPACE_RESERVE = "WORKSPACE_RESERVE"
    WORKSPACE_OVERLAP = "WORKSPACE_OVERLAP"


@dataclass(frozen=True, slots=True)
class ArchiveMemberDescriptor:
    """Untrusted listing metadata; the private locator is never rendered publicly."""

    locator: str = field(repr=False)
    kind: ArchiveMemberKind = ArchiveMemberKind.REGULAR_FILE
    declared_compressed_bytes: int | None = None
    declared_uncompressed_bytes: int | None = None
    nested_archive: bool = False
    sparse: bool = False
    alternate_stream: bool = False
    has_acl: bool = False
    has_xattrs: bool = False
    has_owner: bool = False
    has_group: bool = False
    has_setuid: bool = False
    has_setgid: bool = False
    has_special_flags: bool = False


@dataclass(frozen=True, slots=True)
class ArchiveSafetyResult:
    profile: str
    status: ArchiveSafetyStatus
    violations: tuple[ArchiveSafetyViolation, ...] = ()
    member_count: int = 0

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_SAFETY_POLICY_PROFILE:
            raise ValueError("unsupported archive safety profile")
        if not isinstance(self.status, ArchiveSafetyStatus):
            raise ValueError("status must be ArchiveSafetyStatus")
        if not isinstance(self.violations, tuple) or any(
            not isinstance(item, ArchiveSafetyViolation) for item in self.violations
        ):
            raise ValueError("violations must be fixed archive safety codes")
        if (
            isinstance(self.member_count, bool)
            or not isinstance(self.member_count, int)
            or not 0 <= self.member_count <= MAX_MEMBER_COUNT
        ):
            raise ValueError("member_count exceeds archive safety bound")
        if self.status is ArchiveSafetyStatus.ACCEPTED and self.violations:
            raise ValueError("accepted result cannot contain violations")
        if self.status is not ArchiveSafetyStatus.ACCEPTED and len(self.violations) != 1:
            raise ValueError("rejected result requires exactly one violation")


_RESERVED_WINDOWS_NAMES: Final = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_REJECTED_KINDS: Final = frozenset(
    set(ArchiveMemberKind) - {ArchiveMemberKind.REGULAR_FILE, ArchiveMemberKind.DIRECTORY}
)


def validate_archive_safety(
    members: Iterable[ArchiveMemberDescriptor],
    *,
    volume_count: int = 1,
    workspace_capacity_bytes: int = MAX_WORKSPACE_BYTES,
    workspace_free_bytes: int = MAX_WORKSPACE_BYTES + MIN_WORKSPACE_FREE_RESERVE_BYTES,
    source_overlaps_workspace: bool = False,
) -> ArchiveSafetyResult:
    """Validate supplied listing metadata without opening archives or paths."""

    listed = tuple(islice(members, MAX_MEMBER_COUNT + 1))
    if len(listed) > MAX_MEMBER_COUNT:
        return _failed(ArchiveSafetyViolation.MEMBER_COUNT_LIMIT)
    if not _bounded_nonnegative(volume_count) or not 1 <= volume_count <= MAX_VOLUME_COUNT:
        return _failed(ArchiveSafetyViolation.VOLUME_COUNT_LIMIT)
    if (
        not _bounded_nonnegative(workspace_capacity_bytes)
        or workspace_capacity_bytes > MAX_WORKSPACE_BYTES
    ):
        return _failed(ArchiveSafetyViolation.WORKSPACE_LIMIT)
    if not _bounded_nonnegative(workspace_free_bytes):
        return _failed(ArchiveSafetyViolation.WORKSPACE_RESERVE)
    if source_overlaps_workspace is not False:
        return _failed(ArchiveSafetyViolation.WORKSPACE_OVERLAP)

    total_compressed = 0
    total_uncompressed = 0
    canonical: dict[str, ArchiveMemberKind] = {}
    for member in listed:
        if not isinstance(member, ArchiveMemberDescriptor):
            return _failed(ArchiveSafetyViolation.INVALID_INPUT)
        violation = _validate_member(member)
        if violation is not None:
            return _failed(violation, len(listed))
        assert member.declared_compressed_bytes is not None
        assert member.declared_uncompressed_bytes is not None
        total_compressed += member.declared_compressed_bytes
        total_uncompressed += member.declared_uncompressed_bytes
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
            return _failed(ArchiveSafetyViolation.TOTAL_UNCOMPRESSED_LIMIT, len(listed))
        if total_uncompressed > 0 and total_compressed == 0:
            return _failed(ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT, len(listed))
        if total_compressed > 0 and total_uncompressed > total_compressed * MAX_COMPRESSION_RATIO:
            return _failed(ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT, len(listed))
        key = _canonical_locator(member.locator)
        if key in canonical:
            return _failed(ArchiveSafetyViolation.PATH_COLLISION, len(listed))
        if _has_parent_child_conflict(key, member.kind, canonical):
            return _failed(ArchiveSafetyViolation.PARENT_CHILD_CONFLICT, len(listed))
        canonical[key] = member.kind

    if total_uncompressed > workspace_capacity_bytes:
        return _failed(ArchiveSafetyViolation.WORKSPACE_LIMIT, len(listed))
    if workspace_free_bytes < total_uncompressed + MIN_WORKSPACE_FREE_RESERVE_BYTES:
        return _failed(ArchiveSafetyViolation.WORKSPACE_RESERVE, len(listed))
    return ArchiveSafetyResult(
        ARCHIVE_SAFETY_POLICY_PROFILE, ArchiveSafetyStatus.ACCEPTED, member_count=len(listed)
    )


def _validate_member(member: ArchiveMemberDescriptor) -> ArchiveSafetyViolation | None:
    if not isinstance(member.kind, ArchiveMemberKind) or member.kind in _REJECTED_KINDS:
        return ArchiveSafetyViolation.MEMBER_KIND_REJECTED
    if not _safe_locator(member.locator):
        return ArchiveSafetyViolation.PATH_INVALID
    if any(
        not isinstance(value, bool)
        for value in (
            member.nested_archive,
            member.sparse,
            member.alternate_stream,
            member.has_acl,
            member.has_xattrs,
            member.has_owner,
            member.has_group,
            member.has_setuid,
            member.has_setgid,
            member.has_special_flags,
        )
    ):
        return ArchiveSafetyViolation.INVALID_INPUT
    if member.declared_compressed_bytes is None or member.declared_uncompressed_bytes is None:
        return ArchiveSafetyViolation.UNKNOWN_SIZE
    if not _bounded_nonnegative(member.declared_compressed_bytes) or not _bounded_nonnegative(
        member.declared_uncompressed_bytes
    ):
        return ArchiveSafetyViolation.NEGATIVE_SIZE
    if member.declared_uncompressed_bytes > MAX_SINGLE_MEMBER_BYTES:
        return ArchiveSafetyViolation.MEMBER_SIZE_LIMIT
    if member.declared_uncompressed_bytes > 0 and member.declared_compressed_bytes == 0:
        return ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT
    if member.declared_compressed_bytes > 0 and (
        member.declared_uncompressed_bytes
        > member.declared_compressed_bytes * MAX_COMPRESSION_RATIO
    ):
        return ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT
    if member.nested_archive:
        return ArchiveSafetyViolation.NESTED_ARCHIVE_REJECTED
    if any(
        value
        for value in (
            member.sparse,
            member.alternate_stream,
            member.has_acl,
            member.has_xattrs,
            member.has_owner,
            member.has_group,
            member.has_setuid,
            member.has_setgid,
            member.has_special_flags,
        )
    ):
        return ArchiveSafetyViolation.METADATA_REJECTED
    return None


def _safe_locator(locator: str) -> bool:
    if not isinstance(locator, str) or not locator or len(locator) > MAX_MEMBER_PATH_CODEPOINTS:
        return False
    if any(ord(character) < 32 or character == "\x7f" for character in locator):
        return False
    try:
        if len(locator.encode("utf-8")) > MAX_MEMBER_PATH_UTF8_BYTES:
            return False
    except UnicodeEncodeError:
        return False
    if locator.startswith(("/", "\\", "//", "\\\\", "\\?\\", "\\.\\")):
        return False
    if ":" in locator or "\\" in locator:
        return False
    segments = locator.split("/")
    if len(segments) > MAX_MEMBER_PATH_SEGMENTS or any(
        not segment or segment in {".", ".."} for segment in segments
    ):
        return False
    for segment in segments:
        if (
            segment.endswith((".", " "))
            or segment.split(".", 1)[0].upper() in _RESERVED_WINDOWS_NAMES
        ):
            return False
    return True


def _canonical_locator(locator: str) -> str:
    return "/".join(
        unicodedata.normalize("NFC", unicodedata.normalize("NFC", part).casefold())
        for part in locator.split("/")
    )


def _has_parent_child_conflict(
    key: str, kind: ArchiveMemberKind, existing: dict[str, ArchiveMemberKind]
) -> bool:
    parts = key.split("/")
    for index in range(1, len(parts)):
        if existing.get("/".join(parts[:index])) is ArchiveMemberKind.REGULAR_FILE:
            return True
    if kind is ArchiveMemberKind.REGULAR_FILE:
        prefix = key + "/"
        return any(other.startswith(prefix) for other in existing)
    return False


def _bounded_nonnegative(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _failed(violation: ArchiveSafetyViolation, count: int = 0) -> ArchiveSafetyResult:
    status = (
        ArchiveSafetyStatus.LIMIT_EXCEEDED
        if violation.name.endswith("LIMIT")
        or violation
        in {
            ArchiveSafetyViolation.COMPRESSION_RATIO_LIMIT,
            ArchiveSafetyViolation.WORKSPACE_RESERVE,
        }
        else ArchiveSafetyStatus.POLICY_REJECTED
    )
    return ArchiveSafetyResult(ARCHIVE_SAFETY_POLICY_PROFILE, status, (violation,), count)
