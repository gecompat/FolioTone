"""Immutable contracts for the private GATE-0002 EPUB transformation profile."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NoReturn

CANONICAL_EPUB_PROFILE = "ebook-transform-canonical-epub3/v1"
METADATA_SNAPSHOT_PROFILE = "ebook-transform-metadata-snapshot/v1"
METADATA_INVENTORY_KEYS = (
    "title",
    "title_sort",
    "identifiers",
    "contributors",
    "language",
    "publisher",
    "publication_date",
    "subjects",
    "description",
    "rights",
    "type",
    "rating",
    "series_name",
    "series_type",
    "series_position",
)

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 10_000
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_CONTAINER_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_XML_ELEMENTS = 100_000
MAX_XML_DEPTH = 128
MAX_COMPRESSION_RATIO = 200
MAX_MEMBER_NAME_BYTES = 1024
MAX_MEMBER_COMPONENT_BYTES = 255
MAX_METADATA_VALUES_PER_FIELD = 256
MAX_METADATA_VALUE_CHARS = 4096

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_SECOND = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


class MetadataProvenance(StrEnum):
    """Provenance classes permitted by the isolated transformation snapshot."""

    OBSERVED = "OBSERVED"
    EXTERNAL = "EXTERNAL"
    CANONICAL = "CANONICAL"
    USER_CONFIRMED = "USER_CONFIRMED"


class MetadataDisposition(StrEnum):
    """Whether a snapshot field is preserved, reviewed, or explicitly absent."""

    PRESERVE = "PRESERVE"
    REVIEWED = "REVIEWED"
    OBSERVED_ABSENT = "OBSERVED_ABSENT"


class EbookTransformErrorCode(StrEnum):
    """Path- and metadata-free failure codes for the pure profile."""

    PROFILE_INVALID = "PROFILE_INVALID"
    SNAPSHOT_INVALID = "SNAPSHOT_INVALID"
    ARCHIVE_SIZE_UNSUPPORTED = "ARCHIVE_SIZE_UNSUPPORTED"
    ARCHIVE_INVALID = "ARCHIVE_INVALID"
    ARCHIVE_FEATURE_UNSUPPORTED = "ARCHIVE_FEATURE_UNSUPPORTED"
    ENTRY_LIMIT_EXCEEDED = "ENTRY_LIMIT_EXCEEDED"
    ENTRY_NAME_INVALID = "ENTRY_NAME_INVALID"
    ENTRY_DUPLICATE = "ENTRY_DUPLICATE"
    ENTRY_LINK_UNSUPPORTED = "ENTRY_LINK_UNSUPPORTED"
    ENTRY_ENCRYPTED = "ENTRY_ENCRYPTED"
    ENTRY_COMPRESSION_UNSUPPORTED = "ENTRY_COMPRESSION_UNSUPPORTED"
    ENTRY_SIZE_UNSUPPORTED = "ENTRY_SIZE_UNSUPPORTED"
    ENTRY_RATIO_UNSUPPORTED = "ENTRY_RATIO_UNSUPPORTED"
    ENTRY_UNREADABLE = "ENTRY_UNREADABLE"
    MIMETYPE_INVALID = "MIMETYPE_INVALID"
    CONTAINER_INVALID = "CONTAINER_INVALID"
    PACKAGE_DOCUMENT_INVALID = "PACKAGE_DOCUMENT_INVALID"
    METADATA_UNREPRESENTABLE = "METADATA_UNREPRESENTABLE"
    METADATA_SNAPSHOT_MISMATCH = "METADATA_SNAPSHOT_MISMATCH"
    UNSAFE_CALIBRE_METADATA = "UNSAFE_CALIBRE_METADATA"
    PAYLOAD_PRESERVATION_FAILED = "PAYLOAD_PRESERVATION_FAILED"
    OUTPUT_NOT_CANONICAL = "OUTPUT_NOT_CANONICAL"


class EbookTransformError(ValueError):
    """One fixed-code failure without private paths, hashes, or field values."""

    def __init__(self, code: EbookTransformErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def fail(code: EbookTransformErrorCode) -> NoReturn:
    """Raise the fixed safe error for a failed contract."""
    raise EbookTransformError(code)


def require_sha256(value: str, code: EbookTransformErrorCode) -> str:
    """Return a validated lowercase SHA-256 value."""
    if _SHA256.fullmatch(value) is None:
        fail(code)
    return value


@dataclass(frozen=True, slots=True)
class TransformMetadataField:
    """One complete inventory row with an explicit lineage obligation."""

    key: str
    values: tuple[str, ...] = field(repr=False)
    provenance: MetadataProvenance
    disposition: MetadataDisposition
    review_reference: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.key not in METADATA_INVENTORY_KEYS:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if not isinstance(self.provenance, MetadataProvenance) or not isinstance(
            self.disposition, MetadataDisposition
        ):
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if len(self.values) > MAX_METADATA_VALUES_PER_FIELD:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if any(
            not value
            or len(value) > MAX_METADATA_VALUE_CHARS
            or any(ord(character) < 0x20 and character not in "\t\n\r" for character in value)
            for value in self.values
        ):
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if self.disposition is MetadataDisposition.OBSERVED_ABSENT:
            if self.values or self.provenance is not MetadataProvenance.OBSERVED:
                fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
            if self.review_reference is not None:
                fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        elif not self.values:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        elif self.disposition is MetadataDisposition.PRESERVE:
            if self.provenance not in {
                MetadataProvenance.OBSERVED,
                MetadataProvenance.EXTERNAL,
            } or self.review_reference is not None:
                fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        elif self.disposition is MetadataDisposition.REVIEWED:
            if self.provenance not in {
                MetadataProvenance.CANONICAL,
                MetadataProvenance.USER_CONFIRMED,
            } or self.review_reference is None or not self.review_reference.strip():
                fail(EbookTransformErrorCode.SNAPSHOT_INVALID)


@dataclass(frozen=True, slots=True)
class TransformMetadataSnapshot:
    """Complete immutable metadata projection for one synthetic transform."""

    fields: tuple[TransformMetadataField, ...] = field(repr=False)
    technical_modified_utc: str
    technical_delta_allowlist: tuple[str, ...] = ("dcterms:modified",)
    profile: str = METADATA_SNAPSHOT_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_SNAPSHOT_PROFILE:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if tuple(item.key for item in self.fields) != METADATA_INVENTORY_KEYS:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if self.technical_delta_allowlist != ("dcterms:modified",):
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)
        if _UTC_SECOND.fullmatch(self.technical_modified_utc) is None:
            fail(EbookTransformErrorCode.SNAPSHOT_INVALID)

    @property
    def values_by_key(self) -> dict[str, tuple[str, ...]]:
        """Return the exact value projection without lineage metadata."""
        return {item.key: item.values for item in self.fields}

    @property
    def snapshot_sha256(self) -> str:
        """Return the canonical JSON identity of values and lineage."""
        payload = {
            "fields": [
                {
                    "disposition": item.disposition.value,
                    "key": item.key,
                    "provenance": item.provenance.value,
                    "review_reference": item.review_reference,
                    "values": list(item.values),
                }
                for item in self.fields
            ],
            "profile": self.profile,
            "technical_delta_allowlist": list(self.technical_delta_allowlist),
            "technical_modified_utc": self.technical_modified_utc,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalEpubProfile:
    """Every output-relevant tool, runtime, serializer, and ZIP binder."""

    calibre_version: str
    calibre_adapter_version: str
    parser_version: str
    serializer_version: str
    packer_version: str
    python_implementation: str
    python_version: str
    python_build: str
    zlib_build_version: str
    zlib_runtime_version: str
    image_id: str = field(repr=False)
    image_platform: str
    base_image_digest: str = field(repr=False)
    toolchain_sbom_sha256: str = field(repr=False)
    calibre_artifact_sha256: str = field(repr=False)
    epubcheck_version: str
    epubcheck_jar_sha256: str = field(repr=False)
    java_runtime: str
    config_sha256: str = field(repr=False)
    environment_sha256: str = field(repr=False)
    compression_method: str = "raw-deflate"
    compression_level: int = 9
    compression_wbits: int = -15
    compression_mem_level: int = 9
    compression_strategy: int = 0
    compression_chunk_bytes: int = 65_536
    compression_flush_mode: int = 4
    zip_datetime: tuple[int, int] = (0, 33)
    zip_version_made_by: int = 788
    zip_version_needed: int = 20
    zip_utf8_flag: int = 0x0800
    zip_external_attributes: int = 0o100644 << 16
    profile: str = CANONICAL_EPUB_PROFILE

    def __post_init__(self) -> None:
        required = (
            self.calibre_version,
            self.calibre_adapter_version,
            self.parser_version,
            self.serializer_version,
            self.packer_version,
            self.python_implementation,
            self.python_version,
            self.python_build,
            self.zlib_build_version,
            self.zlib_runtime_version,
            self.image_platform,
            self.epubcheck_version,
            self.java_runtime,
        )
        if self.profile != CANONICAL_EPUB_PROFILE or any(not value.strip() for value in required):
            fail(EbookTransformErrorCode.PROFILE_INVALID)
        if self.calibre_version != "9.13.0" or self.epubcheck_version != "5.3.0":
            fail(EbookTransformErrorCode.PROFILE_INVALID)
        if self.image_platform != "linux/amd64" or not self.image_id.startswith("sha256:"):
            fail(EbookTransformErrorCode.PROFILE_INVALID)
        require_sha256(
            self.image_id.removeprefix("sha256:"),
            EbookTransformErrorCode.PROFILE_INVALID,
        )
        for value in (
            self.base_image_digest,
            self.toolchain_sbom_sha256,
            self.calibre_artifact_sha256,
            self.epubcheck_jar_sha256,
            self.config_sha256,
            self.environment_sha256,
        ):
            require_sha256(value.removeprefix("sha256:"), EbookTransformErrorCode.PROFILE_INVALID)
        if (
            self.compression_method != "raw-deflate"
            or self.compression_level != 9
            or self.compression_wbits != -15
            or self.compression_mem_level != 9
            or self.compression_strategy != 0
            or self.compression_chunk_bytes != 65_536
            or self.compression_flush_mode != 4
            or self.zip_datetime != (0, 33)
            or self.zip_version_made_by != 788
            or self.zip_version_needed != 20
            or self.zip_utf8_flag != 0x0800
            or self.zip_external_attributes != 0o100644 << 16
        ):
            fail(EbookTransformErrorCode.PROFILE_INVALID)

    @property
    def identity_sha256(self) -> str:
        """Return the canonical identity of all output-relevant binders."""
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EpubMemberInspection:
    """Bounded uncompressed identity for one archive member."""

    name: str = field(repr=False)
    content_sha256: str = field(repr=False)
    uncompressed_size: int
    compression: int


@dataclass(frozen=True, slots=True)
class EpubInspection:
    """Safe byte-only inspection result for one synthetic EPUB."""

    source_sha256: str = field(repr=False)
    size_bytes: int
    package_member_name: str = field(repr=False)
    package_document_sha256: str = field(repr=False)
    package_structure_sha256: str = field(repr=False)
    members: tuple[EpubMemberInspection, ...] = field(repr=False)
    metadata_values: tuple[tuple[str, tuple[str, ...]], ...] = field(repr=False)

    @property
    def metadata_by_key(self) -> dict[str, tuple[str, ...]]:
        """Return the fixed metadata projection."""
        return dict(self.metadata_values)


@dataclass(frozen=True, slots=True)
class CanonicalEpubResult:
    """Canonical private output and independently re-read identities."""

    epub_bytes: bytes = field(repr=False)
    sha256: str = field(repr=False)
    size_bytes: int
    package_document_sha256: str = field(repr=False)
    snapshot_sha256: str = field(repr=False)
    profile_sha256: str = field(repr=False)
    members: tuple[EpubMemberInspection, ...] = field(repr=False)


__all__ = [
    "CANONICAL_EPUB_PROFILE",
    "MAX_ARCHIVE_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_CONTAINER_BYTES",
    "MAX_ENTRIES",
    "MAX_MEMBER_BYTES",
    "MAX_MEMBER_COMPONENT_BYTES",
    "MAX_MEMBER_NAME_BYTES",
    "MAX_PACKAGE_BYTES",
    "MAX_TOTAL_UNCOMPRESSED_BYTES",
    "MAX_XML_DEPTH",
    "MAX_XML_ELEMENTS",
    "METADATA_INVENTORY_KEYS",
    "METADATA_SNAPSHOT_PROFILE",
    "CanonicalEpubProfile",
    "CanonicalEpubResult",
    "EbookTransformError",
    "EbookTransformErrorCode",
    "EpubInspection",
    "EpubMemberInspection",
    "MetadataDisposition",
    "MetadataProvenance",
    "TransformMetadataField",
    "TransformMetadataSnapshot",
]
