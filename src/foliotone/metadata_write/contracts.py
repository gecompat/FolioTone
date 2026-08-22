"""Immutable contracts for the bounded EPUB source-metadata writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import NoReturn

from foliotone.core import EntityId

EPUB_TITLE_WRITE_PROFILE = "ebook-source-metadata-write/epub3-title-replace/v1"
EPUB_TITLE_PREFLIGHT_PROFILE = "epub3-title-write-preflight/v1"
EPUB_TITLE_PATCH_PROFILE = "epub3-title-package-patch/v1"
EPUB_TITLE_DIFF_PROFILE = "epub3-title-archive-diff/v1"
EPUB_INPUT_CONFORMANCE_PROFILE = "epubcheck-5.3.0-input-conformance/v1"
EPUB_TITLE_PATCHER_VERSION = "epub3-title-lexical-patch/1"

MAX_EPUB_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EPUB_ENTRIES = 10_000
MAX_EPUB_MEMBER_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_EPUB_CONTAINER_XML_BYTES = 1024 * 1024
MAX_EPUB_PACKAGE_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_EPUB_XML_ELEMENTS = 100_000
MAX_EPUB_XML_DEPTH = 128


class EpubPublicationKind(StrEnum):
    """The caller's format-classification evidence for one bounded input."""

    EPUB3 = "EPUB3"
    KEPUB = "KEPUB"
    UNKNOWN = "UNKNOWN"


class EpubConformanceStatus(StrEnum):
    """The normalized structural verdict bound to the input bytes."""

    CONFORMANT = "CONFORMANT"
    NONCONFORMANT = "NONCONFORMANT"
    UNKNOWN = "UNKNOWN"


class EpubTitleWriteErrorCode(StrEnum):
    """Path- and metadata-free failure codes for the pure writer contract."""

    PLAN_INCOMPATIBLE = "PLAN_INCOMPATIBLE"
    CONFORMANCE_EVIDENCE_INVALID = "CONFORMANCE_EVIDENCE_INVALID"
    SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
    ARCHIVE_SIZE_UNSUPPORTED = "ARCHIVE_SIZE_UNSUPPORTED"
    ARCHIVE_INVALID = "ARCHIVE_INVALID"
    ARCHIVE_FEATURE_UNSUPPORTED = "ARCHIVE_FEATURE_UNSUPPORTED"
    ENTRY_LIMIT_EXCEEDED = "ENTRY_LIMIT_EXCEEDED"
    ENTRY_NAME_INVALID = "ENTRY_NAME_INVALID"
    ENTRY_DUPLICATE = "ENTRY_DUPLICATE"
    ENTRY_ENCRYPTED = "ENTRY_ENCRYPTED"
    ENTRY_COMPRESSION_UNSUPPORTED = "ENTRY_COMPRESSION_UNSUPPORTED"
    ENTRY_SIZE_UNSUPPORTED = "ENTRY_SIZE_UNSUPPORTED"
    ENTRY_UNREADABLE = "ENTRY_UNREADABLE"
    MIMETYPE_INVALID = "MIMETYPE_INVALID"
    CONTAINER_INVALID = "CONTAINER_INVALID"
    PACKAGE_DOCUMENT_INVALID = "PACKAGE_DOCUMENT_INVALID"
    EPUB_VERSION_UNSUPPORTED = "EPUB_VERSION_UNSUPPORTED"
    TITLE_STRUCTURE_UNSUPPORTED = "TITLE_STRUCTURE_UNSUPPORTED"
    MODIFIED_STRUCTURE_UNSUPPORTED = "MODIFIED_STRUCTURE_UNSUPPORTED"
    MODIFIED_TIME_INVALID = "MODIFIED_TIME_INVALID"
    AUTHORIZATION_TIME_INVALID = "AUTHORIZATION_TIME_INVALID"
    MODIFIED_TIME_FUTURE = "MODIFIED_TIME_FUTURE"
    PATCH_DIFF_INVALID = "PATCH_DIFF_INVALID"
    ARCHIVE_DIFF_INVALID = "ARCHIVE_DIFF_INVALID"


class EpubTitleWriteContractError(ValueError):
    """One fixed-code failure without private path, hash, or metadata values."""

    def __init__(self, code: EpubTitleWriteErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def _raise(code: EpubTitleWriteErrorCode) -> NoReturn:
    raise EpubTitleWriteContractError(code)


def _require_sha256(value: str, code: EpubTitleWriteErrorCode) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        _raise(code)
    return value


@dataclass(frozen=True, slots=True)
class EpubInputConformance:
    """Pinned EPUBCheck and publication-kind evidence for exact input bytes."""

    input_sha256: str = field(repr=False)
    publication_kind: EpubPublicationKind
    status: EpubConformanceStatus
    profile: str = EPUB_INPUT_CONFORMANCE_PROFILE

    def __post_init__(self) -> None:
        if self.profile != EPUB_INPUT_CONFORMANCE_PROFILE:
            _raise(EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID)
        _require_sha256(
            self.input_sha256,
            EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID,
        )
        if not isinstance(self.publication_kind, EpubPublicationKind):
            _raise(EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID)
        if not isinstance(self.status, EpubConformanceStatus):
            _raise(EpubTitleWriteErrorCode.CONFORMANCE_EVIDENCE_INVALID)


@dataclass(frozen=True, slots=True)
class EpubTextSpan:
    """One half-open byte span inside the original UTF-8 package document."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)


@dataclass(frozen=True, slots=True)
class EpubMemberSnapshot:
    """Bounded content and metadata identity for one ordered OCF member."""

    ordinal: int
    name: str = field(repr=False)
    raw_name: bytes = field(repr=False)
    content_sha256: str = field(repr=False)
    uncompressed_size: int
    metadata_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.name or not self.raw_name:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        if self.uncompressed_size < 0:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        _require_sha256(self.content_sha256, EpubTitleWriteErrorCode.ARCHIVE_INVALID)
        _require_sha256(self.metadata_fingerprint, EpubTitleWriteErrorCode.ARCHIVE_INVALID)


@dataclass(frozen=True, slots=True)
class EpubTitleWritePreflight:
    """Pure, immutable result of plan, archive, XML, and identity preflight."""

    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    source_sha256: str = field(repr=False)
    source_size_bytes: int
    package_member_ordinal: int
    package_member_name: str = field(repr=False)
    package_document: bytes = field(repr=False)
    package_document_sha256: str = field(repr=False)
    title_span: EpubTextSpan
    modified_span: EpubTextSpan
    original_title: str = field(repr=False)
    selected_title: str = field(repr=False)
    original_modified: str
    members: tuple[EpubMemberSnapshot, ...] = field(repr=False)
    archive_comment_sha256: str = field(repr=False)
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    profile: str = EPUB_TITLE_PREFLIGHT_PROFILE

    def __post_init__(self) -> None:
        if self.profile != EPUB_TITLE_PREFLIGHT_PROFILE:
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        if self.writer_profile != EPUB_TITLE_WRITE_PROFILE:
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        if self.patcher_version != EPUB_TITLE_PATCHER_VERSION:
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        if self.source_size_bytes < 0:
            _raise(EpubTitleWriteErrorCode.SOURCE_IDENTITY_MISMATCH)
        if not 0 <= self.package_member_ordinal < len(self.members):
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        if self.members[self.package_member_ordinal].name != self.package_member_name:
            _raise(EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)
        for value in (
            self.plan_content_hash,
            self.source_sha256,
            self.package_document_sha256,
            self.archive_comment_sha256,
        ):
            _require_sha256(value, EpubTitleWriteErrorCode.PACKAGE_DOCUMENT_INVALID)


@dataclass(frozen=True, slots=True)
class EpubTitlePackagePatch:
    """Exact package-document output; it is not an EPUB archive or executable plan."""

    plan_id: EntityId
    plan_content_hash: str = field(repr=False)
    source_sha256: str = field(repr=False)
    original_package_sha256: str = field(repr=False)
    patched_package_document: bytes = field(repr=False)
    patched_package_sha256: str = field(repr=False)
    selected_title: str = field(repr=False)
    dcterms_modified: str
    title_span: EpubTextSpan
    modified_span: EpubTextSpan
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    profile: str = EPUB_TITLE_PATCH_PROFILE

    def __post_init__(self) -> None:
        if self.profile != EPUB_TITLE_PATCH_PROFILE:
            _raise(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
        if self.writer_profile != EPUB_TITLE_WRITE_PROFILE:
            _raise(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
        if self.patcher_version != EPUB_TITLE_PATCHER_VERSION:
            _raise(EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)
        for value in (
            self.plan_content_hash,
            self.source_sha256,
            self.original_package_sha256,
            self.patched_package_sha256,
        ):
            _require_sha256(value, EpubTitleWriteErrorCode.PATCH_DIFF_INVALID)


@dataclass(frozen=True, slots=True)
class EpubTitleArchiveDiff:
    """Successful member-wise and package-semantic diff for a staged archive."""

    plan_id: EntityId
    input_sha256: str = field(repr=False)
    output_sha256: str = field(repr=False)
    original_package_sha256: str = field(repr=False)
    patched_package_sha256: str = field(repr=False)
    member_count: int
    preserved_member_count: int
    changed_member_count: int = 1
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    patcher_version: str = EPUB_TITLE_PATCHER_VERSION
    profile: str = EPUB_TITLE_DIFF_PROFILE

    def __post_init__(self) -> None:
        if self.profile != EPUB_TITLE_DIFF_PROFILE:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        if self.writer_profile != EPUB_TITLE_WRITE_PROFILE:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        if self.patcher_version != EPUB_TITLE_PATCHER_VERSION:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        for value in (
            self.input_sha256,
            self.output_sha256,
            self.original_package_sha256,
            self.patched_package_sha256,
        ):
            _require_sha256(value, EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        if self.member_count < 1 or self.preserved_member_count != self.member_count - 1:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)
        if self.changed_member_count != 1:
            _raise(EpubTitleWriteErrorCode.ARCHIVE_DIFF_INVALID)


__all__ = [
    "EPUB_INPUT_CONFORMANCE_PROFILE",
    "EPUB_TITLE_DIFF_PROFILE",
    "EPUB_TITLE_PATCHER_VERSION",
    "EPUB_TITLE_PATCH_PROFILE",
    "EPUB_TITLE_PREFLIGHT_PROFILE",
    "EPUB_TITLE_WRITE_PROFILE",
    "MAX_EPUB_ARCHIVE_BYTES",
    "MAX_EPUB_CONTAINER_XML_BYTES",
    "MAX_EPUB_ENTRIES",
    "MAX_EPUB_MEMBER_UNCOMPRESSED_BYTES",
    "MAX_EPUB_PACKAGE_DOCUMENT_BYTES",
    "MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES",
    "MAX_EPUB_XML_DEPTH",
    "MAX_EPUB_XML_ELEMENTS",
    "EpubConformanceStatus",
    "EpubInputConformance",
    "EpubMemberSnapshot",
    "EpubPublicationKind",
    "EpubTextSpan",
    "EpubTitleArchiveDiff",
    "EpubTitlePackagePatch",
    "EpubTitleWriteContractError",
    "EpubTitleWriteErrorCode",
    "EpubTitleWritePreflight",
]
