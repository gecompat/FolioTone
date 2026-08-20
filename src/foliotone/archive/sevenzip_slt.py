"""Bounded, secret-free parser for synthetic ``7zz l -slt`` stdout streams."""

from __future__ import annotations

import codecs
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

ARCHIVE_7ZIP_SLT_PARSER_PROFILE: Final = "archive-7zip-slt-parser/v1"
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
