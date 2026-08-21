"""Pure bounded archive signature and volume-name observations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import islice
from pathlib import PurePath
from typing import Final

ARCHIVE_SIGNATURE_PROFILE: Final = "archive-signature-observer/v1"
ARCHIVE_SIGNATURE_PROFILE_V2: Final = "archive-signature-observer/v2"
ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY: Final = (
    "archive-publication-storage-compatibility/v1"
)
MAX_ARCHIVE_HEADER_BYTES: Final = 512
MAX_ARCHIVE_VOLUMES: Final = 256


class ArchiveContainerClass(StrEnum):
    PUBLICATION_CONTAINER = "PUBLICATION_CONTAINER"
    GENERIC_ARCHIVE = "GENERIC_ARCHIVE"
    UNSUPPORTED_CONTAINER = "UNSUPPORTED_CONTAINER"
    UNKNOWN_CONTAINER = "UNKNOWN_CONTAINER"


class ArchiveFormatKind(StrEnum):
    EPUB = "EPUB"
    CBZ = "CBZ"
    CBR = "CBR"
    ZIP = "ZIP"
    RAR4 = "RAR4"
    RAR5 = "RAR5"
    SEVEN_Z = "SEVEN_Z"
    TAR = "TAR"
    TAR_GZIP = "TAR_GZIP"
    TAR_BZIP2 = "TAR_BZIP2"
    TAR_XZ = "TAR_XZ"
    TAR_ZSTD = "TAR_ZSTD"
    UNKNOWN = "UNKNOWN"


class ArchivePublicationKind(StrEnum):
    NONE = "NONE"
    EPUB = "EPUB"
    CBZ = "CBZ"
    CBR = "CBR"


class ArchiveStorageFamily(StrEnum):
    ZIP = "ZIP"
    RAR4 = "RAR4"
    RAR5 = "RAR5"
    SEVEN_Z = "SEVEN_Z"
    TAR = "TAR"
    UNKNOWN = "UNKNOWN"


class ArchiveOuterCompressionKind(StrEnum):
    NONE = "NONE"
    GZIP = "GZIP"
    BZIP2 = "BZIP2"
    XZ = "XZ"
    ZSTD = "ZSTD"


class ArchiveSuffixKind(StrEnum):
    EPUB = "EPUB"
    CBZ = "CBZ"
    CBR = "CBR"
    ZIP = "ZIP"
    RAR = "RAR"
    SEVEN_Z = "SEVEN_Z"
    TAR = "TAR"
    TAR_GZIP = "TAR_GZIP"
    TAR_BZIP2 = "TAR_BZIP2"
    TAR_XZ = "TAR_XZ"
    TAR_ZSTD = "TAR_ZSTD"
    UNSUPPORTED = "UNSUPPORTED"
    OTHER = "OTHER"


class ArchiveRecognitionStatus(StrEnum):
    MATCHED = "MATCHED"
    SIGNATURE_SUFFIX_MISMATCH = "SIGNATURE_SUFFIX_MISMATCH"
    OUTER_COMPRESSION_ONLY = "OUTER_COMPRESSION_ONLY"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNKNOWN_SIGNATURE = "UNKNOWN_SIGNATURE"


class ArchiveListingStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    LISTED = "LISTED"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_METHOD = "UNSUPPORTED_METHOD"
    MISSING_VOLUME = "MISSING_VOLUME"
    CORRUPT = "CORRUPT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TIMED_OUT = "TIMED_OUT"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_FAILED = "TOOL_FAILED"
    POLICY_REJECTED = "POLICY_REJECTED"


class ArchiveVolumePartitionFinding(StrEnum):
    MISSING_VOLUME = "MISSING_VOLUME"
    UNSUPPORTED_VOLUME = "UNSUPPORTED_VOLUME"
    AMBIGUOUS_VOLUME = "AMBIGUOUS_VOLUME"
    NAME_COLLISION = "NAME_COLLISION"
    ORPHAN_VOLUME = "ORPHAN_VOLUME"


@dataclass(frozen=True, slots=True)
class ArchiveSignatureObservation:
    profile: str
    container_class: ArchiveContainerClass
    format_kind: ArchiveFormatKind
    recognition_status: ArchiveRecognitionStatus
    inspected_bytes: int
    structural_confirmation_required: bool

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_SIGNATURE_PROFILE:
            raise ValueError("unsupported archive signature profile")
        if not isinstance(self.container_class, ArchiveContainerClass):
            raise ValueError("container_class must be ArchiveContainerClass")
        if not isinstance(self.format_kind, ArchiveFormatKind):
            raise ValueError("format_kind must be ArchiveFormatKind")
        if not isinstance(self.recognition_status, ArchiveRecognitionStatus):
            raise ValueError("recognition_status must be ArchiveRecognitionStatus")
        if isinstance(self.inspected_bytes, bool) or not isinstance(self.inspected_bytes, int):
            raise ValueError("inspected_bytes must be an integer")
        if not 0 <= self.inspected_bytes <= MAX_ARCHIVE_HEADER_BYTES:
            raise ValueError("inspected_bytes exceeds the signature bound")
        if not isinstance(self.structural_confirmation_required, bool):
            raise ValueError("structural_confirmation_required must be bool")


@dataclass(frozen=True, slots=True)
class ArchiveSignatureObservationV2:
    profile: str
    container_class: ArchiveContainerClass
    suffix_kind: ArchiveSuffixKind
    publication_kind: ArchivePublicationKind
    storage_family: ArchiveStorageFamily
    outer_compression_kind: ArchiveOuterCompressionKind
    recognition_status: ArchiveRecognitionStatus
    inspected_bytes: int
    structural_confirmation_required: bool
    compatibility: str = ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_SIGNATURE_PROFILE_V2:
            raise ValueError("unsupported archive signature profile")
        if self.compatibility != ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY:
            raise ValueError("unsupported publication storage compatibility")
        for value, expected, name in (
            (self.container_class, ArchiveContainerClass, "container_class"),
            (self.suffix_kind, ArchiveSuffixKind, "suffix_kind"),
            (self.publication_kind, ArchivePublicationKind, "publication_kind"),
            (self.storage_family, ArchiveStorageFamily, "storage_family"),
            (
                self.outer_compression_kind,
                ArchiveOuterCompressionKind,
                "outer_compression_kind",
            ),
            (self.recognition_status, ArchiveRecognitionStatus, "recognition_status"),
        ):
            if not isinstance(value, expected):
                raise ValueError(f"{name} has an invalid type")
        if isinstance(self.inspected_bytes, bool) or not isinstance(self.inspected_bytes, int):
            raise ValueError("inspected_bytes must be an integer")
        if not 0 <= self.inspected_bytes <= MAX_ARCHIVE_HEADER_BYTES:
            raise ValueError("inspected_bytes exceeds the signature bound")
        if not isinstance(self.structural_confirmation_required, bool):
            raise ValueError("structural_confirmation_required must be bool")
        expected_publication = _publication_for_suffix(self.suffix_kind)
        if self.publication_kind is not expected_publication:
            raise ValueError("publication_kind does not match suffix_kind")
        expected_status = _recognition_for_axes(
            self.suffix_kind,
            self.storage_family,
            self.outer_compression_kind,
        )
        if self.recognition_status is not expected_status:
            raise ValueError("recognition_status does not match signature axes")
        expected_container = _container_for_axes(
            self.publication_kind,
            self.storage_family,
            self.outer_compression_kind,
            self.recognition_status,
        )
        if self.container_class is not expected_container:
            raise ValueError("container_class does not match signature axes")
        expected_structural = (
            self.publication_kind is not ArchivePublicationKind.NONE
            or self.outer_compression_kind is not ArchiveOuterCompressionKind.NONE
        )
        if self.structural_confirmation_required is not expected_structural:
            raise ValueError("structural confirmation does not match signature axes")


@dataclass(frozen=True, slots=True)
class ArchiveVolumeGroup:
    status: ArchiveListingStatus
    entry_name: str | None = field(default=None, repr=False)
    members: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ArchiveListingStatus):
            raise ValueError("status must be ArchiveListingStatus")
        if not isinstance(self.members, tuple):
            raise ValueError("archive volume members must be a tuple")
        if len(self.members) > MAX_ARCHIVE_VOLUMES:
            raise ValueError("archive volume group exceeds the bound")
        for member in self.members:
            _require_basename(member)
        if len(set(self.members)) != len(self.members):
            raise ValueError("archive volume members must be unique")
        if self.entry_name is not None:
            _require_basename(self.entry_name)
        if self.status in {ArchiveListingStatus.LISTED, ArchiveListingStatus.UNSUPPORTED_FORMAT}:
            if self.entry_name is None or not self.members or self.entry_name not in self.members:
                raise ValueError("complete volume groups require a canonical entry")
        elif self.entry_name is not None:
            raise ValueError("incomplete volume groups cannot expose an entry")


@dataclass(frozen=True, slots=True)
class ArchiveVolumePartition:
    groups: tuple[ArchiveVolumeGroup, ...]
    findings: tuple[ArchiveVolumePartitionFinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.groups, tuple) or any(
            not isinstance(group, ArchiveVolumeGroup) for group in self.groups
        ):
            raise ValueError("archive volume partition groups are invalid")
        if not isinstance(self.findings, tuple) or any(
            not isinstance(finding, ArchiveVolumePartitionFinding)
            for finding in self.findings
        ):
            raise ValueError("archive volume partition findings are invalid")
        members = tuple(member for group in self.groups for member in group.members)
        if len(members) != len(set(members)):
            raise ValueError("archive volume partition reuses an input")


_ZIP_SIGNATURES: Final = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR4: Final = b"Rar!\x1a\x07\x00"
_RAR5: Final = b"Rar!\x1a\x07\x01\x00"
_SEVEN_Z: Final = b"7z\xbc\xaf'\x1c"
_OUTER_SIGNATURES: Final = (
    (b"\x1f\x8b", ArchiveFormatKind.TAR_GZIP, (".tar.gz", ".tgz")),
    (b"BZh", ArchiveFormatKind.TAR_BZIP2, (".tar.bz2", ".tbz2")),
    (b"\xfd7zXZ\x00", ArchiveFormatKind.TAR_XZ, (".tar.xz", ".txz")),
    (b"(\xb5/\xfd", ArchiveFormatKind.TAR_ZSTD, (".tar.zst", ".tzst")),
)
_UNSUPPORTED_SUFFIXES: Final = (
    ".arj",
    ".cab",
    ".exe",
    ".iso",
    ".wim",
    ".gz",
    ".bz2",
    ".xz",
    ".zst",
)
_NEW_RAR = re.compile(r"^(?P<stem>.+)\.part(?P<number>[0-9]{1,6})\.rar$", re.IGNORECASE)
_OLD_RAR_PART = re.compile(r"^(?P<stem>.+)\.r(?P<number>[0-9]{2})$", re.IGNORECASE)
_SEVEN_Z_PART = re.compile(r"^(?P<stem>.+)\.7z\.(?P<number>[0-9]{3,6})$", re.IGNORECASE)
_SPLIT_ZIP_PART = re.compile(r"^(?P<stem>.+)\.z(?P<number>[0-9]{2})$", re.IGNORECASE)

_DIRECT_SUFFIX_COMPATIBILITY: Final = {
    ArchiveStorageFamily.ZIP: frozenset(
        {ArchiveSuffixKind.EPUB, ArchiveSuffixKind.CBZ, ArchiveSuffixKind.ZIP}
    ),
    ArchiveStorageFamily.RAR4: frozenset({ArchiveSuffixKind.CBR, ArchiveSuffixKind.RAR}),
    ArchiveStorageFamily.RAR5: frozenset({ArchiveSuffixKind.CBR, ArchiveSuffixKind.RAR}),
    ArchiveStorageFamily.SEVEN_Z: frozenset({ArchiveSuffixKind.SEVEN_Z}),
    ArchiveStorageFamily.TAR: frozenset({ArchiveSuffixKind.TAR}),
}
_OUTER_SUFFIX_COMPATIBILITY: Final = {
    ArchiveOuterCompressionKind.GZIP: ArchiveSuffixKind.TAR_GZIP,
    ArchiveOuterCompressionKind.BZIP2: ArchiveSuffixKind.TAR_BZIP2,
    ArchiveOuterCompressionKind.XZ: ArchiveSuffixKind.TAR_XZ,
    ArchiveOuterCompressionKind.ZSTD: ArchiveSuffixKind.TAR_ZSTD,
}


def observe_archive_signature_v2(
    basename: str, header: bytes
) -> ArchiveSignatureObservationV2:
    """Observe independent publication, storage, and outer-compression axes."""

    name = _require_basename(basename)
    if not isinstance(header, bytes) or len(header) > MAX_ARCHIVE_HEADER_BYTES:
        raise ValueError("archive header must be bytes bounded to 512")
    suffix_kind = _suffix_kind(name.lower())
    storage_family = ArchiveStorageFamily.UNKNOWN
    outer_kind = ArchiveOuterCompressionKind.NONE
    if any(header.startswith(signature) for signature in _ZIP_SIGNATURES):
        storage_family = ArchiveStorageFamily.ZIP
    elif header.startswith(_RAR5):
        storage_family = ArchiveStorageFamily.RAR5
    elif header.startswith(_RAR4):
        storage_family = ArchiveStorageFamily.RAR4
    elif header.startswith(_SEVEN_Z):
        storage_family = ArchiveStorageFamily.SEVEN_Z
    elif _valid_tar_header(header):
        storage_family = ArchiveStorageFamily.TAR
    else:
        for signature, candidate in (
            (b"\x1f\x8b", ArchiveOuterCompressionKind.GZIP),
            (b"BZh", ArchiveOuterCompressionKind.BZIP2),
            (b"\xfd7zXZ\x00", ArchiveOuterCompressionKind.XZ),
            (b"(\xb5/\xfd", ArchiveOuterCompressionKind.ZSTD),
        ):
            if header.startswith(signature):
                outer_kind = candidate
                break
    publication_kind = _publication_for_suffix(suffix_kind)
    recognition = _recognition_for_axes(suffix_kind, storage_family, outer_kind)
    container = _container_for_axes(
        publication_kind, storage_family, outer_kind, recognition
    )
    return ArchiveSignatureObservationV2(
        profile=ARCHIVE_SIGNATURE_PROFILE_V2,
        container_class=container,
        suffix_kind=suffix_kind,
        publication_kind=publication_kind,
        storage_family=storage_family,
        outer_compression_kind=outer_kind,
        recognition_status=recognition,
        inspected_bytes=len(header),
        structural_confirmation_required=(
            publication_kind is not ArchivePublicationKind.NONE
            or outer_kind is not ArchiveOuterCompressionKind.NONE
        ),
    )


def observe_archive_signature(basename: str, header: bytes) -> ArchiveSignatureObservation:
    """Observe supplied bounded bytes without opening or decompressing a source."""

    name = _require_basename(basename)
    if not isinstance(header, bytes) or len(header) > MAX_ARCHIVE_HEADER_BYTES:
        raise ValueError("archive header must be bytes bounded to 512")
    lower = name.lower()
    inspected = len(header)

    if any(header.startswith(signature) for signature in _ZIP_SIGNATURES):
        expected = _zip_suffix_kind(lower)
        if expected is None:
            return _observation(
                ArchiveContainerClass.GENERIC_ARCHIVE,
                ArchiveFormatKind.ZIP,
                ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH,
                inspected,
            )
        container = (
            ArchiveContainerClass.PUBLICATION_CONTAINER
            if expected in {ArchiveFormatKind.EPUB, ArchiveFormatKind.CBZ}
            else ArchiveContainerClass.GENERIC_ARCHIVE
        )
        return _observation(
            container,
            expected,
            ArchiveRecognitionStatus.MATCHED,
            inspected,
            structural=container is ArchiveContainerClass.PUBLICATION_CONTAINER,
        )

    if header.startswith(_RAR5) or header.startswith(_RAR4):
        signature_kind = (
            ArchiveFormatKind.RAR5 if header.startswith(_RAR5) else ArchiveFormatKind.RAR4
        )
        if lower.endswith(".cbr"):
            return _observation(
                ArchiveContainerClass.PUBLICATION_CONTAINER,
                ArchiveFormatKind.CBR,
                ArchiveRecognitionStatus.MATCHED,
                inspected,
                structural=True,
            )
        if _is_rar_suffix(lower):
            return _observation(
                ArchiveContainerClass.GENERIC_ARCHIVE,
                signature_kind,
                ArchiveRecognitionStatus.MATCHED,
                inspected,
            )
        return _observation(
            ArchiveContainerClass.GENERIC_ARCHIVE,
            signature_kind,
            ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH,
            inspected,
        )

    if header.startswith(_SEVEN_Z):
        status = (
            ArchiveRecognitionStatus.MATCHED
            if _is_seven_z_suffix(lower)
            else ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
        )
        return _observation(
            ArchiveContainerClass.GENERIC_ARCHIVE,
            ArchiveFormatKind.SEVEN_Z,
            status,
            inspected,
        )

    if _valid_tar_header(header):
        status = (
            ArchiveRecognitionStatus.MATCHED
            if lower.endswith(".tar")
            else ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
        )
        return _observation(
            ArchiveContainerClass.GENERIC_ARCHIVE,
            ArchiveFormatKind.TAR,
            status,
            inspected,
        )

    for signature, format_kind, suffixes in _OUTER_SIGNATURES:
        if header.startswith(signature):
            if lower.endswith(suffixes):
                return _observation(
                    ArchiveContainerClass.GENERIC_ARCHIVE,
                    format_kind,
                    ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY,
                    inspected,
                    structural=True,
                )
            if lower.endswith(_UNSUPPORTED_SUFFIXES):
                return _observation(
                    ArchiveContainerClass.UNSUPPORTED_CONTAINER,
                    ArchiveFormatKind.UNKNOWN,
                    ArchiveRecognitionStatus.UNSUPPORTED_FORMAT,
                    inspected,
                )
            return _observation(
                ArchiveContainerClass.GENERIC_ARCHIVE,
                format_kind,
                ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH,
                inspected,
            )

    if lower.endswith(_UNSUPPORTED_SUFFIXES) or lower.endswith((".z01", ".z02")):
        return _observation(
            ArchiveContainerClass.UNSUPPORTED_CONTAINER,
            ArchiveFormatKind.UNKNOWN,
            ArchiveRecognitionStatus.UNSUPPORTED_FORMAT,
            inspected,
        )
    return _observation(
        ArchiveContainerClass.UNKNOWN_CONTAINER,
        ArchiveFormatKind.UNKNOWN,
        ArchiveRecognitionStatus.UNKNOWN_SIGNATURE,
        inspected,
    )


def group_archive_volume_names(names: Iterable[str]) -> ArchiveVolumeGroup:
    """Classify one already bounded set of basenames without filesystem access."""

    iterator = iter(names)
    materialized = tuple(
        _require_basename(name) for name in islice(iterator, MAX_ARCHIVE_VOLUMES + 1)
    )
    if not materialized or len(materialized) > MAX_ARCHIVE_VOLUMES:
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    if len(set(materialized)) != len(materialized):
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    if len({name.casefold() for name in materialized}) != len(materialized):
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)

    matchers = (_group_new_rar, _group_old_rar, _group_seven_z, _group_split_zip)
    results = tuple(result for matcher in matchers if (result := matcher(materialized)) is not None)
    if len(results) != 1:
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    return results[0]


def partition_archive_volume_names(names: Iterable[str]) -> ArchiveVolumePartition:
    """Consume one private parent directory into disjoint deterministic groups."""

    materialized = tuple(_require_basename(name) for name in names)
    by_fold: dict[str, list[str]] = {}
    for name in materialized:
        by_fold.setdefault(name.casefold(), []).append(name)
    collisions = {fold for fold, values in by_fold.items() if len(values) > 1}
    consumed = {
        name for fold in collisions for name in by_fold[fold]
    }
    findings: list[ArchiveVolumePartitionFinding] = [
        ArchiveVolumePartitionFinding.NAME_COLLISION for _ in sorted(collisions)
    ]
    available = tuple(name for name in materialized if name not in consumed)
    lower_lookup = {name.casefold(): name for name in available}
    schemes: dict[str, dict[str, tuple[str, ...]]] = {}

    def add_scheme(logical: str, family: str, members: tuple[str, ...]) -> None:
        schemes.setdefault(logical.casefold(), {})[family] = members

    new_rar: dict[str, list[str]] = {}
    seven_z: dict[str, list[str]] = {}
    old_rar: dict[str, list[str]] = {}
    split_zip: dict[str, list[str]] = {}
    for name in available:
        if match := _NEW_RAR.fullmatch(name):
            new_rar.setdefault(match.group("stem").casefold(), []).append(name)
        if match := _SEVEN_Z_PART.fullmatch(name):
            seven_z.setdefault(match.group("stem").casefold(), []).append(name)
        if match := _OLD_RAR_PART.fullmatch(name):
            old_rar.setdefault(match.group("stem").casefold(), []).append(name)
        if match := _SPLIT_ZIP_PART.fullmatch(name):
            split_zip.setdefault(match.group("stem").casefold(), []).append(name)
    for stem, bucket_members in new_rar.items():
        add_scheme(stem, "NEW_RAR", tuple(bucket_members))
        if entry := lower_lookup.get(f"{stem}.rar"):
            add_scheme(stem, "DIRECT_RAR_CONFLICT", (entry,))
    for stem, bucket_members in seven_z.items():
        add_scheme(stem, "SEVEN_Z", tuple(bucket_members))
        if entry := lower_lookup.get(f"{stem}.7z"):
            add_scheme(stem, "DIRECT_SEVEN_Z_CONFLICT", (entry,))
    for stem, bucket_members in old_rar.items():
        entry = lower_lookup.get(f"{stem}.rar")
        prefix = () if entry is None else (entry,)
        add_scheme(stem, "OLD_RAR", (*prefix, *bucket_members))
    for stem, bucket_members in split_zip.items():
        entry = lower_lookup.get(f"{stem}.zip")
        prefix = () if entry is None else (entry,)
        add_scheme(stem, "SPLIT_ZIP", (*prefix, *bucket_members))

    groups: list[ArchiveVolumeGroup] = []
    for logical in sorted(schemes):
        families = schemes[logical]
        family_members = {name for values in families.values() for name in values}
        if len(families) != 1:
            consumed.update(family_members)
            findings.append(ArchiveVolumePartitionFinding.AMBIGUOUS_VOLUME)
            continue
        family, family_sources = next(iter(families.items()))
        consumed.update(family_sources)
        if family in {"OLD_RAR", "SPLIT_ZIP"}:
            suffix = ".rar" if family == "OLD_RAR" else ".zip"
            if not any(name.casefold() == f"{logical}{suffix}" for name in family_sources):
                findings.append(ArchiveVolumePartitionFinding.ORPHAN_VOLUME)
                continue
        if len(family_sources) > MAX_ARCHIVE_VOLUMES:
            findings.append(ArchiveVolumePartitionFinding.UNSUPPORTED_VOLUME)
            continue
        observed = group_archive_volume_names(family_sources)
        if observed.status is ArchiveListingStatus.MISSING_VOLUME:
            findings.append(ArchiveVolumePartitionFinding.MISSING_VOLUME)
        elif observed.status is ArchiveListingStatus.POLICY_REJECTED:
            findings.append(ArchiveVolumePartitionFinding.AMBIGUOUS_VOLUME)
        else:
            groups.append(observed)

    for name in sorted(
        (name for name in available if name not in consumed),
        key=lambda value: (value.casefold(), value),
    ):
        if _suffix_kind(name.lower()) is not ArchiveSuffixKind.OTHER:
            groups.append(ArchiveVolumeGroup(ArchiveListingStatus.LISTED, name, (name,)))

    groups.sort(key=lambda group: ((group.entry_name or "").casefold(), group.entry_name or ""))
    findings.sort(key=lambda finding: finding.value)
    return ArchiveVolumePartition(tuple(groups), tuple(findings))


def _observation(
    container_class: ArchiveContainerClass,
    format_kind: ArchiveFormatKind,
    status: ArchiveRecognitionStatus,
    inspected: int,
    *,
    structural: bool = False,
) -> ArchiveSignatureObservation:
    return ArchiveSignatureObservation(
        profile=ARCHIVE_SIGNATURE_PROFILE,
        container_class=container_class,
        format_kind=format_kind,
        recognition_status=status,
        inspected_bytes=inspected,
        structural_confirmation_required=structural,
    )


def _zip_suffix_kind(lower: str) -> ArchiveFormatKind | None:
    if lower.endswith(".epub"):
        return ArchiveFormatKind.EPUB
    if lower.endswith(".cbz"):
        return ArchiveFormatKind.CBZ
    if lower.endswith(".zip"):
        return ArchiveFormatKind.ZIP
    return None


def _suffix_kind(lower: str) -> ArchiveSuffixKind:
    if lower.endswith(".epub"):
        return ArchiveSuffixKind.EPUB
    if lower.endswith(".cbz"):
        return ArchiveSuffixKind.CBZ
    if lower.endswith(".cbr"):
        return ArchiveSuffixKind.CBR
    if lower.endswith(".zip"):
        return ArchiveSuffixKind.ZIP
    if _is_rar_suffix(lower):
        return ArchiveSuffixKind.RAR
    if _is_seven_z_suffix(lower):
        return ArchiveSuffixKind.SEVEN_Z
    if lower.endswith(".tar"):
        return ArchiveSuffixKind.TAR
    for suffixes, kind in (
        ((".tar.gz", ".tgz"), ArchiveSuffixKind.TAR_GZIP),
        ((".tar.bz2", ".tbz2"), ArchiveSuffixKind.TAR_BZIP2),
        ((".tar.xz", ".txz"), ArchiveSuffixKind.TAR_XZ),
        ((".tar.zst", ".tzst"), ArchiveSuffixKind.TAR_ZSTD),
    ):
        if lower.endswith(suffixes):
            return kind
    if lower.endswith((*_UNSUPPORTED_SUFFIXES, ".z01", ".z02")):
        return ArchiveSuffixKind.UNSUPPORTED
    return ArchiveSuffixKind.OTHER


def _publication_for_suffix(suffix_kind: ArchiveSuffixKind) -> ArchivePublicationKind:
    return {
        ArchiveSuffixKind.EPUB: ArchivePublicationKind.EPUB,
        ArchiveSuffixKind.CBZ: ArchivePublicationKind.CBZ,
        ArchiveSuffixKind.CBR: ArchivePublicationKind.CBR,
    }.get(suffix_kind, ArchivePublicationKind.NONE)


def _recognition_for_axes(
    suffix_kind: ArchiveSuffixKind,
    storage_family: ArchiveStorageFamily,
    outer_kind: ArchiveOuterCompressionKind,
) -> ArchiveRecognitionStatus:
    direct = storage_family is not ArchiveStorageFamily.UNKNOWN
    outer = outer_kind is not ArchiveOuterCompressionKind.NONE
    if direct and outer:
        raise ValueError("direct storage and outer compression are mutually exclusive")
    if direct:
        compatible = _DIRECT_SUFFIX_COMPATIBILITY[storage_family]
        return (
            ArchiveRecognitionStatus.MATCHED
            if suffix_kind in compatible
            else ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
        )
    if outer:
        if suffix_kind is ArchiveSuffixKind.UNSUPPORTED:
            return ArchiveRecognitionStatus.UNSUPPORTED_FORMAT
        if suffix_kind is _OUTER_SUFFIX_COMPATIBILITY[outer_kind]:
            return ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY
        return ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
    if suffix_kind is ArchiveSuffixKind.UNSUPPORTED:
        return ArchiveRecognitionStatus.UNSUPPORTED_FORMAT
    return ArchiveRecognitionStatus.UNKNOWN_SIGNATURE


def _container_for_axes(
    publication_kind: ArchivePublicationKind,
    storage_family: ArchiveStorageFamily,
    outer_kind: ArchiveOuterCompressionKind,
    recognition: ArchiveRecognitionStatus,
) -> ArchiveContainerClass:
    if publication_kind is not ArchivePublicationKind.NONE:
        return ArchiveContainerClass.PUBLICATION_CONTAINER
    if recognition is ArchiveRecognitionStatus.UNSUPPORTED_FORMAT:
        return ArchiveContainerClass.UNSUPPORTED_CONTAINER
    if (
        storage_family is not ArchiveStorageFamily.UNKNOWN
        or outer_kind is not ArchiveOuterCompressionKind.NONE
        or recognition is ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
    ):
        return ArchiveContainerClass.GENERIC_ARCHIVE
    return ArchiveContainerClass.UNKNOWN_CONTAINER


def _is_rar_suffix(lower: str) -> bool:
    return bool(
        lower.endswith(".rar") or re.search(r"\.r[0-9]{2}$", lower) or _NEW_RAR.fullmatch(lower)
    )


def _is_seven_z_suffix(lower: str) -> bool:
    return lower.endswith(".7z") or _SEVEN_Z_PART.fullmatch(lower) is not None


def _valid_tar_header(header: bytes) -> bool:
    if len(header) < 512:
        return False
    checksum_field = header[148:156]
    try:
        stored = int(checksum_field.rstrip(b" \x00") or b"0", 8)
    except ValueError:
        return False
    candidate = bytearray(header[:512])
    candidate[148:156] = b"        "
    return stored == sum(candidate)


def _require_basename(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1_024:
        raise ValueError("archive name must be a bounded basename")
    if PurePath(value).name != value or any(character in value for character in ("/", "\\", ":")):
        raise ValueError("archive name must not contain a path")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("archive name contains control characters")
    return value


def _group_new_rar(names: tuple[str, ...]) -> ArchiveVolumeGroup | None:
    matches = tuple(_NEW_RAR.fullmatch(name) for name in names)
    if not all(matches):
        return None
    return _numbered_group(names, matches, unsupported=False)


def _group_seven_z(names: tuple[str, ...]) -> ArchiveVolumeGroup | None:
    matches = tuple(_SEVEN_Z_PART.fullmatch(name) for name in names)
    if not all(matches):
        return None
    return _numbered_group(names, matches, unsupported=False)


def _numbered_group(
    names: tuple[str, ...],
    matches: tuple[re.Match[str] | None, ...],
    *,
    unsupported: bool,
) -> ArchiveVolumeGroup:
    captured = tuple(match for match in matches if match is not None)
    stems = {match.group("stem") for match in captured}
    widths = {len(match.group("number")) for match in captured}
    if len(stems) != 1 or len(widths) != 1:
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    ordered = tuple(
        sorted(zip(names, captured, strict=True), key=lambda item: int(item[1].group("number")))
    )
    numbers = tuple(int(match.group("number")) for _, match in ordered)
    if numbers != tuple(range(1, len(numbers) + 1)):
        return ArchiveVolumeGroup(ArchiveListingStatus.MISSING_VOLUME)
    members = tuple(name for name, _ in ordered)
    status = ArchiveListingStatus.UNSUPPORTED_FORMAT if unsupported else ArchiveListingStatus.LISTED
    return ArchiveVolumeGroup(status=status, entry_name=members[0], members=members)


def _group_old_rar(names: tuple[str, ...]) -> ArchiveVolumeGroup | None:
    rar_names = tuple(name for name in names if name.lower().endswith(".rar"))
    part_pairs = tuple(
        (name, _OLD_RAR_PART.fullmatch(name)) for name in names if name not in rar_names
    )
    if len(rar_names) != 1 or not part_pairs or not all(match for _, match in part_pairs):
        return None
    entry = rar_names[0]
    entry_stem = entry[:-4]
    captured = tuple((name, match) for name, match in part_pairs if match is not None)
    if any(match.group("stem") != entry_stem for _, match in captured):
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    ordered = tuple(sorted(captured, key=lambda item: int(item[1].group("number"))))
    numbers = tuple(int(match.group("number")) for _, match in ordered)
    if numbers != tuple(range(len(numbers))):
        return ArchiveVolumeGroup(ArchiveListingStatus.MISSING_VOLUME)
    members = (entry, *(name for name, _ in ordered))
    return ArchiveVolumeGroup(ArchiveListingStatus.LISTED, entry, tuple(members))


def _group_split_zip(names: tuple[str, ...]) -> ArchiveVolumeGroup | None:
    zip_names = tuple(name for name in names if name.lower().endswith(".zip"))
    part_pairs = tuple(
        (name, _SPLIT_ZIP_PART.fullmatch(name)) for name in names if name not in zip_names
    )
    if len(zip_names) != 1 or not part_pairs or not all(match for _, match in part_pairs):
        return None
    entry = zip_names[0]
    entry_stem = entry[:-4]
    captured = tuple((name, match) for name, match in part_pairs if match is not None)
    if any(match.group("stem") != entry_stem for _, match in captured):
        return ArchiveVolumeGroup(ArchiveListingStatus.POLICY_REJECTED)
    ordered = tuple(sorted(captured, key=lambda item: int(item[1].group("number"))))
    numbers = tuple(int(match.group("number")) for _, match in ordered)
    if numbers != tuple(range(1, len(numbers) + 1)):
        return ArchiveVolumeGroup(ArchiveListingStatus.MISSING_VOLUME)
    members = (*(name for name, _ in ordered), entry)
    return ArchiveVolumeGroup(ArchiveListingStatus.UNSUPPORTED_FORMAT, entry, tuple(members))
