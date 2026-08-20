"""Bounded, secret-free parser for synthetic ``7zz l -slt`` stdout streams."""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from foliotone.archive.safety_policy import (
    MAX_MEMBER_COUNT,
    MAX_MEMBER_PATH_CODEPOINTS,
    MAX_MEMBER_PATH_UTF8_BYTES,
    is_safe_archive_member_locator,
)
from foliotone.archive.signatures import (
    ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
    ARCHIVE_SIGNATURE_PROFILE_V2,
    ArchiveOuterCompressionKind,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservationV2,
    ArchiveStorageFamily,
)

ARCHIVE_7ZIP_SLT_PARSER_PROFILE: Final = "archive-7zip-slt-parser/v1"
ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE: Final = "archive-7zip-slt-parser/v2"
ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE: Final = "archive-7zip-slt-parser/v3"
ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE: Final = "archive-7zip-format-lock/v1"
ARCHIVE_7ZIP_FORMAT_LOCK_SHA256: Final = (
    "4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061"
)
MAX_CHUNK_BYTES: Final = 262_144
MAX_CHUNKS: Final = 65_536
MAX_LINE_UTF8_BYTES: Final = 8_192
MAX_LINE_CODEPOINTS: Final = 4_096
MAX_FIELDS_PER_RECORD: Final = 32
MAX_COMMENT_UTF8_BYTES: Final = 4_096
MAX_COMMENT_CODEPOINTS: Final = 4_086
MAX_STDOUT_BYTES: Final = 8_388_608


class ArchiveSevenZipSltParseStatus(StrEnum):
    PARSED = "PARSED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    ENCODING_REJECTED = "ENCODING_REJECTED"
    GRAMMAR_REJECTED = "GRAMMAR_REJECTED"


class ArchiveSevenZipFormatCase(StrEnum):
    PLAINTEXT_REGULAR = "PLAINTEXT_REGULAR"
    DIRECTORY = "DIRECTORY"
    ALL_ENCRYPTED = "ALL_ENCRYPTED"
    MIXED = "MIXED"
    SYMBOLIC_LINK = "SYMBOLIC_LINK"
    HARD_LINK = "HARD_LINK"


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipSltMemberParseResult:
    profile: str
    status: ArchiveSevenZipSltParseStatus
    members: tuple[ArchiveSevenZipSltMember, ...] = ()

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE:
            raise ValueError("unsupported archive member parser profile")
        if not isinstance(self.status, ArchiveSevenZipSltParseStatus):
            raise ValueError("status must be ArchiveSevenZipSltParseStatus")
        if not isinstance(self.members, tuple) or len(self.members) > MAX_MEMBER_COUNT:
            raise ValueError("members violate archive member parser bounds")
        if any(not isinstance(member, ArchiveSevenZipSltMember) for member in self.members):
            raise ValueError("members must contain archive parser members")
        if self.status is not ArchiveSevenZipSltParseStatus.PARSED:
            if self.members != ():
                raise ValueError("failed member parse cannot retain members")
            return
        canonical: dict[str, bool] = {}
        for member in self.members:
            key = _canonical_locator(member.locator)
            if key in canonical or _parent_child_conflict(key, member.is_directory, canonical):
                raise ValueError("member locators must be distinct and safe")
            canonical[key] = member.is_directory


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipLockedMember:
    """Locator-free projection of one member from an accepted locked profile."""

    is_directory: bool
    declared_uncompressed_bytes: int
    declared_compressed_bytes: int
    encrypted: bool
    crc32: str | None
    symbolic_link: bool
    hard_link: bool
    user_present: bool
    group_present: bool
    characteristics_present: bool
    alternate_stream: bool
    anti_item: bool

    def __post_init__(self) -> None:
        _require_int64("declared_uncompressed_bytes", self.declared_uncompressed_bytes)
        _require_int64("declared_compressed_bytes", self.declared_compressed_bytes)
        for name, value in (
            ("is_directory", self.is_directory),
            ("encrypted", self.encrypted),
            ("symbolic_link", self.symbolic_link),
            ("hard_link", self.hard_link),
            ("user_present", self.user_present),
            ("group_present", self.group_present),
            ("characteristics_present", self.characteristics_present),
            ("alternate_stream", self.alternate_stream),
            ("anti_item", self.anti_item),
        ):
            _require_bool(name, value)
        if self.crc32 is not None and not _is_crc(self.crc32):
            raise ValueError("crc32 violates archive parser grammar")


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipLockedParseResult:
    profile: str
    lock_profile: str
    lock_sha256: str
    compatibility: str
    signature_profile: str
    storage_family: ArchiveStorageFamily
    status: ArchiveSevenZipSltParseStatus
    case_kind: ArchiveSevenZipFormatCase | None = None
    members: tuple[ArchiveSevenZipLockedMember, ...] = ()

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE:
            raise ValueError("unsupported archive locked parser profile")
        if self.lock_profile != ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE:
            raise ValueError("unsupported archive format lock profile")
        if self.lock_sha256 != ARCHIVE_7ZIP_FORMAT_LOCK_SHA256:
            raise ValueError("unsupported archive format lock digest")
        if self.compatibility != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY:
            raise ValueError("unsupported publication storage compatibility")
        if self.signature_profile != ARCHIVE_SIGNATURE_PROFILE_V2:
            raise ValueError("unsupported archive signature profile")
        if not isinstance(self.storage_family, ArchiveStorageFamily):
            raise ValueError("storage_family must be ArchiveStorageFamily")
        if not isinstance(self.status, ArchiveSevenZipSltParseStatus):
            raise ValueError("status must be ArchiveSevenZipSltParseStatus")
        if self.status is ArchiveSevenZipSltParseStatus.PARSED:
            if not isinstance(self.case_kind, ArchiveSevenZipFormatCase):
                raise ValueError("parsed locked result requires a format case")
            if self.storage_family is ArchiveStorageFamily.UNKNOWN:
                raise ValueError("parsed locked result requires direct storage")
            expected_hashes = _LOCKED_RECORD_HASHES.get(self.storage_family, {}).get(
                self.case_kind
            )
            if expected_hashes is None or len(self.members) != len(expected_hashes):
                raise ValueError("parsed locked result requires an accepted cell shape")
            if not isinstance(self.members, tuple) or not self.members:
                raise ValueError("parsed locked result requires bounded members")
            if len(self.members) > MAX_MEMBER_COUNT or any(
                not isinstance(member, ArchiveSevenZipLockedMember)
                for member in self.members
            ):
                raise ValueError("members violate archive parser bounds")
            _validate_locked_case_shape(
                self.storage_family, self.case_kind, self.members
            )
        elif self.case_kind is not None or self.members != ():
            raise ValueError("failed locked result cannot retain parsed values")


def parse_archive_7zip_slt_members(chunks: Iterable[bytes]) -> ArchiveSevenZipSltMemberParseResult:
    """Parse the exact headerless member-only v2 grammar without raw retention."""

    parser = _MemberOnlyParser()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    total_bytes = 0
    chunk_count = 0
    started = False
    try:
        for chunk in chunks:
            chunk_count += 1
            if not isinstance(chunk, bytes):
                return _failed_members(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)
            if chunk_count > MAX_CHUNKS or len(chunk) > MAX_CHUNK_BYTES:
                return _failed_members(ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED)
            total_bytes += len(chunk)
            if total_bytes > MAX_STDOUT_BYTES:
                return _failed_members(ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED)
            decoded = decoder.decode(chunk, final=False)
            if decoded:
                if not started and decoded.startswith("\ufeff"):
                    decoded = decoded[1:]
                started = True
                if "\ufeff" in decoded:
                    return _failed_members(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
                if not parser.feed(decoded):
                    return _failed_members(parser.failure)
        decoded = decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return _failed_members(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
    except Exception:
        return _failed_members(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)
    if decoded:
        if not started and decoded.startswith("\ufeff"):
            decoded = decoded[1:]
        started = True
        if "\ufeff" in decoded:
            return _failed_members(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
        if not parser.feed(decoded):
            return _failed_members(parser.failure)
    if not parser.finish():
        return _failed_members(parser.failure)
    try:
        return parser.member_result()
    except Exception:
        return _failed_members(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)


def parse_archive_7zip_slt_members_locked(
    observation: ArchiveSignatureObservationV2,
    chunks: Iterable[bytes],
) -> ArchiveSevenZipLockedParseResult:
    """Parse only a matched direct v2 observation against the accepted format lock."""

    if not isinstance(observation, ArchiveSignatureObservationV2):
        return _failed_locked(
            ArchiveStorageFamily.UNKNOWN,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
        )
    storage_family = observation.storage_family
    if (
        observation.profile != ARCHIVE_SIGNATURE_PROFILE_V2
        or observation.compatibility != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
        or observation.recognition_status is not ArchiveRecognitionStatus.MATCHED
        or storage_family is ArchiveStorageFamily.UNKNOWN
        or observation.outer_compression_kind is not ArchiveOuterCompressionKind.NONE
        or storage_family not in _LOCKED_RECORD_HASHES
    ):
        return _failed_locked(
            storage_family,
            ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED,
        )

    parser = _LockedMemberOnlyParser(storage_family)
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    total_bytes = 0
    chunk_count = 0
    started = False
    try:
        for chunk in chunks:
            chunk_count += 1
            if not isinstance(chunk, bytes):
                return _failed_locked(
                    storage_family, ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
                )
            if chunk_count > MAX_CHUNKS or len(chunk) > MAX_CHUNK_BYTES:
                return _failed_locked(
                    storage_family, ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
                )
            total_bytes += len(chunk)
            if total_bytes > MAX_STDOUT_BYTES:
                return _failed_locked(
                    storage_family, ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
                )
            decoded = decoder.decode(chunk, final=False)
            if decoded:
                if not started and decoded.startswith("\ufeff"):
                    decoded = decoded[1:]
                started = True
                if "\ufeff" in decoded:
                    return _failed_locked(
                        storage_family, ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
                    )
                if not parser.feed(decoded):
                    return _failed_locked(storage_family, parser.failure)
        decoded = decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return _failed_locked(
            storage_family, ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
        )
    except Exception:
        return _failed_locked(
            storage_family, ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        )
    if decoded:
        if not started and decoded.startswith("\ufeff"):
            decoded = decoded[1:]
        started = True
        if "\ufeff" in decoded:
            return _failed_locked(
                storage_family, ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
            )
        if not parser.feed(decoded):
            return _failed_locked(storage_family, parser.failure)
    if not parser.finish():
        return _failed_locked(storage_family, parser.failure)
    try:
        return parser.locked_result()
    except Exception:
        return _failed_locked(
            storage_family, ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        )


def _failed_members(status: ArchiveSevenZipSltParseStatus) -> ArchiveSevenZipSltMemberParseResult:
    return ArchiveSevenZipSltMemberParseResult(ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE, status)


def _failed_locked(
    storage_family: ArchiveStorageFamily, status: ArchiveSevenZipSltParseStatus
) -> ArchiveSevenZipLockedParseResult:
    return ArchiveSevenZipLockedParseResult(
        profile=ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
        lock_profile=ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
        lock_sha256=ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
        compatibility=ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
        signature_profile=ARCHIVE_SIGNATURE_PROFILE_V2,
        storage_family=storage_family,
        status=status,
    )


@dataclass(frozen=True, slots=True)
class EphemeralArchiveComment:
    """Private, in-memory-only header comment with redacted text forms."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or self.value.strip() != self.value
            or "\ufeff" in self.value
            or len(self.value) > MAX_COMMENT_CODEPOINTS
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in self.value)
            or _utf8_too_long(self.value, MAX_COMMENT_UTF8_BYTES)
        ):
            raise ValueError("comment violates archive parser bounds")

    def __str__(self) -> str:
        return "EphemeralArchiveComment(redacted=True)"


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipSltHeader:
    locator: str = field(repr=False)
    archive_type: str = field(repr=False)
    physical_size: int
    characteristics_present: bool = False

    def __post_init__(self) -> None:
        if not _bounded_text(
            self.locator,
            max_codepoints=MAX_LINE_CODEPOINTS,
            max_utf8_bytes=MAX_LINE_UTF8_BYTES,
        ):
            raise ValueError("header locator violates archive parser bounds")
        if not _bounded_text(
            self.archive_type,
            max_codepoints=MAX_LINE_CODEPOINTS,
            max_utf8_bytes=MAX_LINE_UTF8_BYTES,
        ):
            raise ValueError("archive type violates archive parser bounds")
        _require_int64("physical_size", self.physical_size)
        _require_bool("characteristics_present", self.characteristics_present)


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipSltMember:
    locator: str = field(repr=False)
    is_directory: bool
    declared_uncompressed_bytes: int
    declared_compressed_bytes: int
    encrypted: bool
    crc32: str | None
    symbolic_link: bool
    hard_link: bool
    user_present: bool
    group_present: bool
    characteristics_present: bool
    alternate_stream: bool
    anti_item: bool

    def __post_init__(self) -> None:
        if not _bounded_text(
            self.locator,
            max_codepoints=MAX_MEMBER_PATH_CODEPOINTS,
            max_utf8_bytes=MAX_MEMBER_PATH_UTF8_BYTES,
        ) or not is_safe_archive_member_locator(self.locator):
            raise ValueError("member locator violates archive parser bounds")
        _require_int64("declared_uncompressed_bytes", self.declared_uncompressed_bytes)
        _require_int64("declared_compressed_bytes", self.declared_compressed_bytes)
        for name, value in (
            ("is_directory", self.is_directory),
            ("encrypted", self.encrypted),
            ("symbolic_link", self.symbolic_link),
            ("hard_link", self.hard_link),
            ("user_present", self.user_present),
            ("group_present", self.group_present),
            ("characteristics_present", self.characteristics_present),
            ("alternate_stream", self.alternate_stream),
            ("anti_item", self.anti_item),
        ):
            _require_bool(name, value)
        if self.crc32 is not None and not _is_crc(self.crc32):
            raise ValueError("crc32 violates archive parser grammar")


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipSltParseResult:
    profile: str
    status: ArchiveSevenZipSltParseStatus
    header: ArchiveSevenZipSltHeader | None = None
    members: tuple[ArchiveSevenZipSltMember, ...] = ()
    comment: EphemeralArchiveComment | None = None

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_7ZIP_SLT_PARSER_PROFILE:
            raise ValueError("unsupported archive parser profile")
        if not isinstance(self.status, ArchiveSevenZipSltParseStatus):
            raise ValueError("status must be ArchiveSevenZipSltParseStatus")
        if self.status is ArchiveSevenZipSltParseStatus.PARSED:
            if not isinstance(self.header, ArchiveSevenZipSltHeader):
                raise ValueError("parsed result requires header")
            if not isinstance(self.members, tuple) or len(self.members) > MAX_MEMBER_COUNT:
                raise ValueError("members violate archive parser bounds")
            if any(not isinstance(member, ArchiveSevenZipSltMember) for member in self.members):
                raise ValueError("members must contain archive parser members")
            if self.comment is not None and not isinstance(self.comment, EphemeralArchiveComment):
                raise ValueError("comment must be EphemeralArchiveComment")
            canonical: dict[str, bool] = {}
            for member in self.members:
                key = _canonical_locator(member.locator)
                if key in canonical or _parent_child_conflict(key, member.is_directory, canonical):
                    raise ValueError("member locators must be distinct and safe")
                canonical[key] = member.is_directory
        elif (
            self.header is not None
            or not isinstance(self.members, tuple)
            or self.members != ()
            or self.comment is not None
        ):
            raise ValueError("failed result cannot retain parsed values")


_HEADER_FIELDS: Final = frozenset(
    {
        "Path",
        "Type",
        "Physical Size",
        "Headers Size",
        "Method",
        "Solid",
        "Blocks",
        "Volumes",
        "Total Physical Size",
        "Tail Size",
        "Embedded Stub Size",
        "Characteristics",
        "Comment",
    }
)
_MEMBER_FIELDS: Final = frozenset(
    {
        "Path",
        "Folder",
        "Size",
        "Packed Size",
        "Modified",
        "Created",
        "Accessed",
        "Attributes",
        "Encrypted",
        "CRC",
        "Method",
        "Block",
        "Characteristics",
        "Host OS",
        "Version",
        "Volume Index",
        "Offset",
        "Symbolic Link",
        "Hard Link",
        "User",
        "Group",
        "Alternate Stream",
        "Anti",
    }
)
_HEADER_NUMBERS: Final = frozenset(
    {
        "Physical Size",
        "Headers Size",
        "Blocks",
        "Volumes",
        "Total Physical Size",
        "Tail Size",
        "Embedded Stub Size",
    }
)
_MEMBER_NUMBERS: Final = frozenset({"Size", "Packed Size", "Block", "Volume Index", "Offset"})
_BOOLEAN_FIELDS: Final = frozenset({"Folder", "Encrypted", "Solid", "Alternate Stream", "Anti"})
_MAX_INT64: Final = 2**63 - 1
_LOCKED_MEMBER_FIELDS: Final = frozenset(
    {
        "Accessed",
        "Alternate Stream",
        "Attributes",
        "Block",
        "CRC",
        "Characteristics",
        "Checksum",
        "Comment",
        "Commented",
        "Copy Link",
        "Created",
        "Device Major",
        "Device Minor",
        "Encrypted",
        "Folder",
        "Group",
        "Group ID",
        "Hard Link",
        "Host OS",
        "Method",
        "Mode",
        "Modified",
        "NT Security",
        "Offset",
        "Packed Size",
        "Path",
        "Size",
        "Solid",
        "Split After",
        "Split Before",
        "Symbolic Link",
        "User",
        "User ID",
        "Version",
        "Volume Index",
    }
)
_LOCKED_BOOLEAN_FIELDS: Final = frozenset(
    {
        "Alternate Stream",
        "Anti",
        "Commented",
        "Encrypted",
        "Folder",
        "Solid",
        "Split After",
        "Split Before",
    }
)
_LOCKED_PRIVATE_FIELDS: Final = frozenset(
    {"Comment", "Copy Link", "Group", "Hard Link", "Symbolic Link", "User"}
)
_LOCKED_TIMESTAMP: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:.-]+$")
_LOCKED_RECORD_HASHES: Final[
    dict[ArchiveStorageFamily, dict[ArchiveSevenZipFormatCase, tuple[str, ...]]]
] = {
    ArchiveStorageFamily.ZIP: {
        ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR: (
            "c22061ae7450e886c70b6aecd328859f19cf1f17f6a0dae2e6b23a2b51f846ab",
        ),
        ArchiveSevenZipFormatCase.DIRECTORY: (
            "4e0f29940953ad4a1bf8e3691fbd20a1aa05c0dba3188a6bc66e4f0e8edd8bba",
        ),
        ArchiveSevenZipFormatCase.ALL_ENCRYPTED: (
            "d14a6ebe84e41b040909192ee1cbac7ad44f1734d95f6875ceec1bd3f7ba2ca5",
        ),
        ArchiveSevenZipFormatCase.MIXED: (
            "c22061ae7450e886c70b6aecd328859f19cf1f17f6a0dae2e6b23a2b51f846ab",
            "d14a6ebe84e41b040909192ee1cbac7ad44f1734d95f6875ceec1bd3f7ba2ca5",
        ),
    },
    ArchiveStorageFamily.RAR4: {
        ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR: (
            "562b97821c17dbeb0ea64418431611d7bd66519b7b247372b7995176f61716ca",
        )
    },
    ArchiveStorageFamily.RAR5: {
        ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR: (
            "c769027e80e4cd090986ba95833d3f1ca3f88b76721d4c2947628d5a3b25259f",
        )
    },
    ArchiveStorageFamily.SEVEN_Z: {
        ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR: (
            "1a7ae20cb61fc60f1ecacba157838b8cb76a0f4054f676001a59aad66d325787",
        ),
        ArchiveSevenZipFormatCase.DIRECTORY: (
            "0fb6b5d68f1c3e1cbd9fd5255ec866fe5ceecb3a7dcae348edc0e0cb62d308f1",
        ),
        ArchiveSevenZipFormatCase.ALL_ENCRYPTED: (
            "d888c5de9a489c89e3ac5cd817f555631e2e41e5df813c62d9d3e7dc16116b92",
        ),
        ArchiveSevenZipFormatCase.MIXED: (
            "9cbfb0c08ee0e863703ca67faf640ef6915d95f056f3ff7236e39f82e86920d7",
            "d888c5de9a489c89e3ac5cd817f555631e2e41e5df813c62d9d3e7dc16116b92",
        ),
    },
    ArchiveStorageFamily.TAR: {
        ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR: (
            "9c3b413b429c3c6043b6ed8cb2b4029287a079323111cb55aef2c6b43d9041c7",
        ),
        ArchiveSevenZipFormatCase.DIRECTORY: (
            "fcb1e316dfb2e6d12afcdef9c62acc1fb881adf607d117391b4b6c487dfb4d6e",
        ),
        ArchiveSevenZipFormatCase.SYMBOLIC_LINK: (
            "0b7d70ad09d2e1549cb26229f9d24c021ed66f51a6623315bd0988706620888d",
        ),
        ArchiveSevenZipFormatCase.HARD_LINK: (
            "9c3b413b429c3c6043b6ed8cb2b4029287a079323111cb55aef2c6b43d9041c7",
            "2e894ee0ef904e9feb86098bbec2274d4717111935b7ea47913082274c699928",
        ),
    },
}


def parse_archive_7zip_slt(chunks: Iterable[bytes]) -> ArchiveSevenZipSltParseResult:
    """Parse one bounded synthetic stdout stream without retaining raw output."""

    parser = _Parser()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    total_bytes = 0
    chunk_count = 0
    started = False
    try:
        for chunk in chunks:
            chunk_count += 1
            if not isinstance(chunk, bytes):
                return _failed(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)
            if chunk_count > MAX_CHUNKS or len(chunk) > MAX_CHUNK_BYTES:
                return _failed(ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED)
            total_bytes += len(chunk)
            if total_bytes > MAX_STDOUT_BYTES:
                return _failed(ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED)
            decoded = decoder.decode(chunk, final=False)
            if decoded:
                if not started and decoded.startswith("\ufeff"):
                    decoded = decoded[1:]
                started = True
                if "\ufeff" in decoded:
                    return _failed(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
                if not parser.feed(decoded):
                    return _failed(parser.failure)
        decoded = decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return _failed(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
    except Exception:
        return _failed(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)
    if decoded:
        if not started and decoded.startswith("\ufeff"):
            decoded = decoded[1:]
        started = True
        if "\ufeff" in decoded:
            return _failed(ArchiveSevenZipSltParseStatus.ENCODING_REJECTED)
        if not parser.feed(decoded):
            return _failed(parser.failure)
    if not started or not parser.finish():
        return _failed(parser.failure)
    try:
        return parser.result()
    except Exception:
        return _failed(ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED)


def _failed(status: ArchiveSevenZipSltParseStatus) -> ArchiveSevenZipSltParseResult:
    return ArchiveSevenZipSltParseResult(ARCHIVE_7ZIP_SLT_PARSER_PROFILE, status)


class _Parser:
    def __init__(self) -> None:
        self.failure = ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        self._line: list[str] = []
        self._pending_cr = False
        self._stage = "header"
        self._header: dict[str, str] = {}
        self._member: dict[str, str] = {}
        self._members: list[ArchiveSevenZipSltMember] = []
        self._canonical_members: dict[str, bool] = {}
        self._header_closed = False
        self._member_closed = False

    def feed(self, text: str) -> bool:
        for char in text:
            if ord(char) < 32 or 127 <= ord(char) <= 159:
                if char not in {"\n", "\r"}:
                    return self._reject()
            if self._pending_cr:
                if char != "\n":
                    return self._reject()
                self._pending_cr = False
                if not self._complete_line():
                    return False
                continue
            if char == "\r":
                self._pending_cr = True
            elif char == "\n":
                if not self._complete_line():
                    return False
            else:
                self._line.append(char)
                if len(self._line) > MAX_LINE_CODEPOINTS:
                    self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
                    return False
        return True

    def finish(self) -> bool:
        if self._pending_cr or self._line or self._stage != "members" or self._member_closed:
            return self._reject()
        if self._member and not self._close_member():
            return False
        return self._header_closed

    def result(self) -> ArchiveSevenZipSltParseResult:
        header = ArchiveSevenZipSltHeader(
            self._header["Path"],
            self._header["Type"],
            int(self._header["Physical Size"]),
            characteristics_present="Characteristics" in self._header,
        )
        comment = self._header.get("Comment")
        return ArchiveSevenZipSltParseResult(
            ARCHIVE_7ZIP_SLT_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            header,
            tuple(self._members),
            EphemeralArchiveComment(comment) if comment is not None else None,
        )

    def _complete_line(self) -> bool:
        line = "".join(self._line)
        self._line.clear()
        try:
            if len(line.encode("utf-8")) > MAX_LINE_UTF8_BYTES:
                self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
                return False
        except UnicodeEncodeError:
            self.failure = ArchiveSevenZipSltParseStatus.ENCODING_REJECTED
            return False
        return self._accept_line(line)

    def _accept_line(self, line: str) -> bool:
        if self._stage == "header":
            if line == "":
                if not self._header or self._header_closed:
                    return self._reject()
                self._header_closed = True
                self._stage = "separator"
                return True
            return self._add_field(self._header, line, _HEADER_FIELDS)
        if self._stage == "separator":
            if line != "----------":
                return self._reject()
            if not {"Path", "Type", "Physical Size"}.issubset(self._header):
                return self._reject()
            if not _bounded_text(
                self._header["Path"],
                max_codepoints=MAX_LINE_CODEPOINTS,
                max_utf8_bytes=MAX_LINE_UTF8_BYTES,
            ) or not _bounded_text(
                self._header["Type"],
                max_codepoints=MAX_LINE_CODEPOINTS,
                max_utf8_bytes=MAX_LINE_UTF8_BYTES,
            ):
                return self._reject()
            self._stage = "members"
            return True
        if line == "":
            if not self._member:
                return self._reject()
            if not self._close_member():
                return False
            self._member_closed = True
            return True
        if self._member_closed:
            self._member_closed = False
        return self._add_field(self._member, line, _MEMBER_FIELDS)

    def _add_field(self, record: dict[str, str], line: str, allowed: frozenset[str]) -> bool:
        if " = " not in line:
            return self._reject()
        name, value = line.split(" = ", 1)
        if (
            not name
            or name.strip() != name
            or value.strip() != value
            or name not in allowed
            or name in record
        ):
            return self._reject()
        if len(record) >= MAX_FIELDS_PER_RECORD:
            self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
            return False
        if name in _BOOLEAN_FIELDS and value not in {"+", "-"}:
            return self._reject()
        if name in _HEADER_NUMBERS or name in _MEMBER_NUMBERS:
            if not _is_canonical_number(value):
                return self._reject()
        if name == "CRC" and not _is_crc(value):
            return self._reject()
        if name == "Comment" and (
            len(value) > MAX_COMMENT_CODEPOINTS or _utf8_too_long(value, MAX_COMMENT_UTF8_BYTES)
        ):
            self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
            return False
        record[name] = value
        return True

    def _close_member(self) -> bool:
        required = {"Path", "Folder", "Size", "Packed Size", "Encrypted"}
        if not required.issubset(self._member) or "Comment" in self._member:
            return self._reject()
        locator = self._member["Path"]
        if (
            len(locator) > MAX_MEMBER_PATH_CODEPOINTS
            or _utf8_too_long(locator, MAX_MEMBER_PATH_UTF8_BYTES)
            or not is_safe_archive_member_locator(locator)
        ):
            return self._reject()
        if len(self._members) >= MAX_MEMBER_COUNT:
            self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
            return False
        is_directory = self._member["Folder"] == "+"
        canonical = _canonical_locator(locator)
        if canonical in self._canonical_members or _parent_child_conflict(
            canonical, is_directory, self._canonical_members
        ):
            return self._reject()
        self._members.append(
            ArchiveSevenZipSltMember(
                locator=locator,
                is_directory=is_directory,
                declared_uncompressed_bytes=int(self._member["Size"]),
                declared_compressed_bytes=int(self._member["Packed Size"]),
                encrypted=self._member["Encrypted"] == "+",
                crc32=self._member.get("CRC"),
                symbolic_link="Symbolic Link" in self._member,
                hard_link="Hard Link" in self._member,
                user_present="User" in self._member,
                group_present="Group" in self._member,
                characteristics_present="Characteristics" in self._member,
                alternate_stream=self._member.get("Alternate Stream") == "+",
                anti_item=self._member.get("Anti") == "+",
            )
        )
        self._canonical_members[canonical] = is_directory
        self._member.clear()
        return True

    def _reject(self) -> bool:
        self.failure = ArchiveSevenZipSltParseStatus.GRAMMAR_REJECTED
        return False


class _MemberOnlyParser(_Parser):
    """State machine for ``EOF | (FIELD+ BLANK)+ EOF``."""

    def __init__(self) -> None:
        super().__init__()
        self._stage = "members"
        self._record_closed = False

    def finish(self) -> bool:
        if self._pending_cr or self._line or self._member:
            return self._reject()
        return not self._members or self._record_closed

    def member_result(self) -> ArchiveSevenZipSltMemberParseResult:
        return ArchiveSevenZipSltMemberParseResult(
            ARCHIVE_7ZIP_SLT_MEMBER_PARSER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            tuple(self._members),
        )

    def _accept_line(self, line: str) -> bool:
        if line == "":
            if not self._member or self._record_closed:
                return self._reject()
            if not self._close_member():
                return False
            self._record_closed = True
            return True
        if self._record_closed:
            self._record_closed = False
        return self._add_field(self._member, line, _MEMBER_FIELDS)


class _LockedMemberOnlyParser(_Parser):
    """Headerless parser that accepts only exact reviewed v1 lock profiles."""

    def __init__(self, storage_family: ArchiveStorageFamily) -> None:
        super().__init__()
        self._stage = "members"
        self._record_closed = False
        self._storage_family = storage_family
        self._candidate_cases = dict(_LOCKED_RECORD_HASHES[storage_family])
        self._record_hashes: list[str] = []

    def finish(self) -> bool:
        if self._pending_cr or self._line or self._member or not self._record_closed:
            return self._reject()
        complete = {
            case_kind: hashes
            for case_kind, hashes in self._candidate_cases.items()
            if len(hashes) == len(self._record_hashes)
        }
        if len(complete) != 1:
            return self._reject()
        self._candidate_cases = complete
        return True

    def locked_result(self) -> ArchiveSevenZipLockedParseResult:
        case_kind = next(iter(self._candidate_cases))
        return ArchiveSevenZipLockedParseResult(
            profile=ARCHIVE_7ZIP_LOCKED_MEMBER_PARSER_PROFILE,
            lock_profile=ARCHIVE_7ZIP_FORMAT_LOCK_PROFILE,
            lock_sha256=ARCHIVE_7ZIP_FORMAT_LOCK_SHA256,
            compatibility=ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
            signature_profile=ARCHIVE_SIGNATURE_PROFILE_V2,
            storage_family=self._storage_family,
            status=ArchiveSevenZipSltParseStatus.PARSED,
            case_kind=case_kind,
            members=tuple(_locked_member_projection(member) for member in self._members),
        )

    def _accept_line(self, line: str) -> bool:
        if line == "":
            if not self._member or self._record_closed:
                return self._reject()
            if not self._close_member():
                return False
            self._record_closed = True
            return True
        if self._record_closed:
            self._record_closed = False
        return self._add_locked_field(line)

    def _add_locked_field(self, line: str) -> bool:
        if " = " not in line:
            return self._reject()
        name, value = line.split(" = ", 1)
        if (
            not name
            or name.strip() != name
            or value.strip() != value
            or name not in _LOCKED_MEMBER_FIELDS
            or name in self._member
        ):
            return self._reject()
        if len(self._member) >= MAX_FIELDS_PER_RECORD:
            self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
            return False
        try:
            _locked_value_class(name, value)
        except ValueError:
            return self._reject()
        self._member[name] = value
        return True

    def _close_member(self) -> bool:
        fields = [
            {
                "handling": _locked_handling(value_class),
                "name": name,
                "value_class": value_class,
            }
            for name, value in self._member.items()
            for value_class in (_locked_value_class(name, value),)
        ]
        record_hash = hashlib.sha256(
            json.dumps(
                fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        record_index = len(self._record_hashes)
        candidates = {
            case_kind: hashes
            for case_kind, hashes in self._candidate_cases.items()
            if record_index < len(hashes) and hashes[record_index] == record_hash
        }
        if not candidates:
            return self._reject()
        self._candidate_cases = candidates
        self._record_hashes.append(record_hash)

        locator = self._member.get("Path")
        size = self._member.get("Size")
        packed_size = self._member.get("Packed Size")
        encrypted = self._member.get("Encrypted")
        if encrypted is None and self._storage_family is ArchiveStorageFamily.TAR:
            encrypted = "-"
        if (
            locator is None
            or size is None
            or packed_size is None
            or encrypted not in {"+", "-"}
            or not _is_canonical_number(size)
            or not _is_canonical_number(packed_size)
            or len(locator) > MAX_MEMBER_PATH_CODEPOINTS
            or _utf8_too_long(locator, MAX_MEMBER_PATH_UTF8_BYTES)
            or not is_safe_archive_member_locator(locator)
        ):
            return self._reject()
        if len(self._members) >= MAX_MEMBER_COUNT:
            self.failure = ArchiveSevenZipSltParseStatus.LIMIT_EXCEEDED
            return False
        directory_shapes = {
            case_kind is ArchiveSevenZipFormatCase.DIRECTORY for case_kind in candidates
        }
        if len(directory_shapes) != 1:
            return self._reject()
        is_directory = next(iter(directory_shapes))
        canonical = _canonical_locator(locator)
        if canonical in self._canonical_members or _parent_child_conflict(
            canonical, is_directory, self._canonical_members
        ):
            return self._reject()
        crc = self._member.get("CRC") or None
        self._members.append(
            ArchiveSevenZipSltMember(
                locator=locator,
                is_directory=is_directory,
                declared_uncompressed_bytes=int(size),
                declared_compressed_bytes=int(packed_size),
                encrypted=encrypted == "+",
                crc32=crc,
                symbolic_link=bool(self._member.get("Symbolic Link")),
                hard_link=bool(self._member.get("Hard Link")),
                user_present="User" in self._member,
                group_present="Group" in self._member,
                characteristics_present="Characteristics" in self._member,
                alternate_stream=self._member.get("Alternate Stream") == "+",
                anti_item=self._member.get("Anti") == "+",
            )
        )
        self._canonical_members[canonical] = is_directory
        self._member.clear()
        return True


def _locked_member_projection(
    member: ArchiveSevenZipSltMember,
) -> ArchiveSevenZipLockedMember:
    return ArchiveSevenZipLockedMember(
        is_directory=member.is_directory,
        declared_uncompressed_bytes=member.declared_uncompressed_bytes,
        declared_compressed_bytes=member.declared_compressed_bytes,
        encrypted=member.encrypted,
        crc32=member.crc32,
        symbolic_link=member.symbolic_link,
        hard_link=member.hard_link,
        user_present=member.user_present,
        group_present=member.group_present,
        characteristics_present=member.characteristics_present,
        alternate_stream=member.alternate_stream,
        anti_item=member.anti_item,
    )


def _validate_locked_case_shape(
    storage_family: ArchiveStorageFamily,
    case_kind: ArchiveSevenZipFormatCase,
    members: tuple[ArchiveSevenZipLockedMember, ...],
) -> None:
    actual = tuple(
        (
            member.is_directory,
            member.encrypted,
            member.crc32 is not None,
            member.symbolic_link,
            member.hard_link,
            member.user_present,
            member.group_present,
            member.characteristics_present,
            member.alternate_stream,
            member.anti_item,
        )
        for member in members
    )
    expected = _LOCKED_MEMBER_SHAPES.get((storage_family, case_kind))
    if actual != expected:
        raise ValueError("locked member projection does not match the accepted case")


_LOCKED_MEMBER_SHAPES: Final[
    dict[
        tuple[ArchiveStorageFamily, ArchiveSevenZipFormatCase],
        tuple[tuple[bool, bool, bool, bool, bool, bool, bool, bool, bool, bool], ...],
    ]
] = {
    (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR): (
        (False, False, True, False, False, False, False, True, False, False),
    ),
    (ArchiveStorageFamily.RAR4, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR): (
        (False, False, True, False, False, False, False, False, False, False),
    ),
    (ArchiveStorageFamily.RAR5, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR): (
        (False, False, True, False, False, False, False, True, False, False),
    ),
    (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR): (
        (False, False, True, False, False, False, False, False, False, False),
    ),
    (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.PLAINTEXT_REGULAR): (
        (False, False, False, False, False, True, True, True, False, False),
    ),
    (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.DIRECTORY): (
        (True, False, False, False, False, False, False, True, False, False),
    ),
    (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.DIRECTORY): (
        (True, False, False, False, False, False, False, False, False, False),
    ),
    (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.DIRECTORY): (
        (True, False, False, False, False, True, True, True, False, False),
    ),
    (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.ALL_ENCRYPTED): (
        (False, True, False, False, False, False, False, True, False, False),
    ),
    (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.ALL_ENCRYPTED): (
        (False, True, True, False, False, False, False, False, False, False),
    ),
    (ArchiveStorageFamily.ZIP, ArchiveSevenZipFormatCase.MIXED): (
        (False, False, True, False, False, False, False, True, False, False),
        (False, True, False, False, False, False, False, True, False, False),
    ),
    (ArchiveStorageFamily.SEVEN_Z, ArchiveSevenZipFormatCase.MIXED): (
        (False, False, True, False, False, False, False, False, False, False),
        (False, True, True, False, False, False, False, False, False, False),
    ),
    (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.SYMBOLIC_LINK): (
        (False, False, False, True, False, True, True, True, False, False),
    ),
    (ArchiveStorageFamily.TAR, ArchiveSevenZipFormatCase.HARD_LINK): (
        (False, False, False, False, False, True, True, True, False, False),
        (False, False, False, False, True, True, True, True, False, False),
    ),
}


def _locked_value_class(name: str, value: str) -> str:
    if name in _LOCKED_BOOLEAN_FIELDS:
        if value == "+":
            return "BOOL_PLUS"
        if value == "-":
            return "BOOL_MINUS"
        raise ValueError("locked bool value rejected")
    if not value:
        return "EMPTY"
    if name == "Path":
        return "PRIVATE_LOCATOR_DISCARDED"
    if name in _LOCKED_PRIVATE_FIELDS:
        return "PRIVATE_NONEMPTY_DISCARDED"
    if _is_canonical_number(value):
        return "CANONICAL_UINT"
    if _is_crc(value):
        return "CRC32"
    if _LOCKED_TIMESTAMP.fullmatch(value):
        return "TIMESTAMP"
    return "TECHNICAL_NONEMPTY_DISCARDED"


def _locked_handling(value_class: str) -> str:
    if value_class == "EMPTY":
        return "EMPTY"
    if value_class.endswith("_DISCARDED"):
        return "DISCARD"
    return "REQUIRED"


def _is_canonical_number(value: str) -> bool:
    return (
        bool(value)
        and value.isascii()
        and value.isdecimal()
        and (value == "0" or not value.startswith("0"))
        and int(value) <= _MAX_INT64
    )


def _is_crc(value: str) -> bool:
    return len(value) == 8 and all(character in "0123456789ABCDEF" for character in value)


def _utf8_too_long(value: str, limit: int) -> bool:
    try:
        return len(value.encode("utf-8")) > limit
    except UnicodeEncodeError:
        return True


def _bounded_text(value: object, *, max_codepoints: int, max_utf8_bytes: int) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\ufeff" in value
        or len(value) > max_codepoints
    ):
        return False
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        return False
    return not _utf8_too_long(value, max_utf8_bytes)


def _require_int64(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_INT64:
        raise ValueError(f"{name} violates archive parser bounds")


def _require_bool(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be bool")


def _canonical_locator(locator: str) -> str:
    return "/".join(
        unicodedata.normalize("NFC", segment).casefold() for segment in locator.split("/")
    )


def _parent_child_conflict(locator: str, is_directory: bool, existing: dict[str, bool]) -> bool:
    parts = locator.split("/")
    for index in range(1, len(parts)):
        if existing.get("/".join(parts[:index])) is False:
            return True
    return not is_directory and any(other.startswith(locator + "/") for other in existing)
