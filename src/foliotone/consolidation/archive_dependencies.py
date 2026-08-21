"""Pure archive-source dependency projection for consolidation plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Final

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
)
from foliotone.consolidation.contracts import (
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationFileRole,
)
from foliotone.core import EntityId

CONSOLIDATION_ARCHIVE_DEPENDENCY_PROFILE: Final = (
    "consolidation-archive-dependency/v1"
)
ARCHIVE_OBSERVATION_SNAPSHOT_KIND: Final = "ARCHIVE_OBSERVATION"
ARCHIVE_OBSERVATION_PROFILE: Final = "archive-observation/v1"
MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS: Final = 16

_FINGERPRINT_DOMAIN: Final = b"consolidation-archive-dependency/v1\x00"
_SHA256: Final = re.compile(r"[0-9a-f]{64}\Z")
_DIRECT_STORAGE_FAMILIES: Final = frozenset(
    {
        ArchiveStorageFamily.ZIP,
        ArchiveStorageFamily.RAR4,
        ArchiveStorageFamily.RAR5,
        ArchiveStorageFamily.SEVEN_Z,
        ArchiveStorageFamily.TAR,
    }
)


def _entity_id(value: EntityId, field_name: str) -> None:
    if not isinstance(value, EntityId):
        raise ValueError(f"{field_name} must be an EntityId")


@dataclass(frozen=True, slots=True)
class ArchiveSourceDependencyBinding:
    """Locator-free material proving one archive graph uses one file source."""

    archive_observation_id: EntityId
    file_observation_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    source_ordinal: int
    container_class: ArchiveContainerClass
    publication_kind: ArchivePublicationKind
    storage_family: ArchiveStorageFamily
    outer_compression_kind: ArchiveOuterCompressionKind
    recognition_status: ArchiveRecognitionStatus
    archive_content_hash: str = field(repr=False)
    archive_profile: str = ARCHIVE_OBSERVATION_PROFILE

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.archive_observation_id, "archive_observation_id"),
            (self.file_observation_id, "file_observation_id"),
            (self.scan_root_id, "scan_root_id"),
            (self.source_scan_run_id, "source_scan_run_id"),
        ):
            _entity_id(value, field_name)
        if (
            isinstance(self.source_ordinal, bool)
            or not isinstance(self.source_ordinal, int)
            or not 0 <= self.source_ordinal <= 255
        ):
            raise ValueError("source_ordinal is outside the supported bound")
        if not isinstance(self.container_class, ArchiveContainerClass):
            raise ValueError("container_class has an invalid type")
        if not isinstance(self.publication_kind, ArchivePublicationKind):
            raise ValueError("publication_kind has an invalid type")
        if not isinstance(self.storage_family, ArchiveStorageFamily):
            raise ValueError("storage_family has an invalid type")
        if not isinstance(
            self.outer_compression_kind, ArchiveOuterCompressionKind
        ):
            raise ValueError("outer_compression_kind has an invalid type")
        if not isinstance(self.recognition_status, ArchiveRecognitionStatus):
            raise ValueError("recognition_status has an invalid type")
        if (
            not isinstance(self.archive_content_hash, str)
            or _SHA256.fullmatch(self.archive_content_hash) is None
        ):
            raise ValueError("archive_content_hash must be a lowercase SHA-256")
        if self.archive_profile != ARCHIVE_OBSERVATION_PROFILE:
            raise ValueError("archive_profile is incompatible")
        if not _binding_shape_is_consistent(self):
            raise ValueError("archive source binding shape is inconsistent")


@dataclass(frozen=True, slots=True)
class ArchiveDependencyProjectionInputs:
    """Bounded same-run inputs for one directed consolidation endpoint."""

    file_role: ConsolidationFileRole
    file_observation_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    bindings: tuple[ArchiveSourceDependencyBinding, ...] = field(
        default=(), repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.file_role, ConsolidationFileRole):
            raise ValueError("file_role must be a ConsolidationFileRole")
        for value, field_name in (
            (self.file_observation_id, "file_observation_id"),
            (self.scan_root_id, "scan_root_id"),
            (self.source_scan_run_id, "source_scan_run_id"),
        ):
            _entity_id(value, field_name)
        if (
            not isinstance(self.bindings, tuple)
            or len(self.bindings) > MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS
            or any(
                not isinstance(item, ArchiveSourceDependencyBinding)
                for item in self.bindings
            )
        ):
            raise ValueError("bindings are invalid or exceed the supported bound")
        if len(set(self.bindings)) != len(self.bindings):
            raise ValueError("bindings must be unique")
        for binding in self.bindings:
            if (
                binding.file_observation_id != self.file_observation_id
                or binding.scan_root_id != self.scan_root_id
                or binding.source_scan_run_id != self.source_scan_run_id
            ):
                raise ValueError("archive source binding lineage is inconsistent")

    def build(self) -> ConsolidationDependency:
        """Project one canonical archive dependency without performing I/O."""

        bindings = tuple(sorted(self.bindings, key=_binding_sort_key))
        generic = tuple(item for item in bindings if _is_generic_archive_source(item))
        publications = tuple(
            item
            for item in bindings
            if item.publication_kind is not ArchivePublicationKind.NONE
        )
        if publications and generic:
            raise ValueError("publication and generic archive source evidence conflict")
        if len(generic) > 1:
            raise ValueError("archive source evidence is ambiguous")

        state = (
            ConsolidationDependencyState.KNOWN_PRESENT
            if generic
            else ConsolidationDependencyState.UNKNOWN
        )
        archive = generic[0] if generic else None
        material = {
            "profile": CONSOLIDATION_ARCHIVE_DEPENDENCY_PROFILE,
            "file_role": self.file_role.value,
            "file_observation_id": str(self.file_observation_id),
            "scan_root_id": str(self.scan_root_id),
            "source_scan_run_id": str(self.source_scan_run_id),
            "state": state.value,
            "archive_observation_id": (
                str(archive.archive_observation_id) if archive is not None else None
            ),
            "archive_content_hash": (
                archive.archive_content_hash if archive is not None else None
            ),
        }
        encoded = json.dumps(
            material,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hashlib.sha256(_FINGERPRINT_DOMAIN + encoded).hexdigest()
        return ConsolidationDependency(
            file_role=self.file_role,
            kind=ConsolidationDependencyKind.ARCHIVE,
            state=state,
            material_fingerprint=fingerprint,
            snapshot_kind=(ARCHIVE_OBSERVATION_SNAPSHOT_KIND if archive else None),
            snapshot_id=(archive.archive_observation_id if archive else None),
        )


def _binding_shape_is_consistent(binding: ArchiveSourceDependencyBinding) -> bool:
    direct = binding.storage_family in _DIRECT_STORAGE_FAMILIES
    outer = binding.outer_compression_kind is not ArchiveOuterCompressionKind.NONE
    if direct and outer:
        return False
    if binding.publication_kind is not ArchivePublicationKind.NONE:
        if binding.container_class is not ArchiveContainerClass.PUBLICATION_CONTAINER:
            return False
        if binding.recognition_status is ArchiveRecognitionStatus.MATCHED:
            return direct and not outer
        if binding.recognition_status is ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH:
            return direct is not outer
        return (
            binding.recognition_status is ArchiveRecognitionStatus.UNKNOWN_SIGNATURE
            and binding.storage_family is ArchiveStorageFamily.UNKNOWN
            and not outer
        )
    if binding.recognition_status is ArchiveRecognitionStatus.MATCHED:
        return (
            binding.container_class is ArchiveContainerClass.GENERIC_ARCHIVE
            and direct
            and not outer
        )
    if binding.recognition_status is ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY:
        return (
            binding.container_class is ArchiveContainerClass.GENERIC_ARCHIVE
            and binding.storage_family is ArchiveStorageFamily.UNKNOWN
            and outer
        )
    if binding.recognition_status is ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH:
        return (
            binding.container_class is ArchiveContainerClass.GENERIC_ARCHIVE
            and direct is not outer
        )
    if binding.recognition_status is ArchiveRecognitionStatus.UNSUPPORTED_FORMAT:
        return (
            binding.container_class is ArchiveContainerClass.UNSUPPORTED_CONTAINER
            and binding.storage_family is ArchiveStorageFamily.UNKNOWN
        )
    return (
        binding.recognition_status is ArchiveRecognitionStatus.UNKNOWN_SIGNATURE
        and binding.container_class is ArchiveContainerClass.UNKNOWN_CONTAINER
        and binding.storage_family is ArchiveStorageFamily.UNKNOWN
        and not outer
    )


def _is_generic_archive_source(binding: ArchiveSourceDependencyBinding) -> bool:
    return (
        binding.publication_kind is ArchivePublicationKind.NONE
        and binding.recognition_status
        in {
            ArchiveRecognitionStatus.MATCHED,
            ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY,
            ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH,
        }
    )


def _binding_sort_key(binding: ArchiveSourceDependencyBinding) -> tuple[object, ...]:
    return (
        str(binding.archive_observation_id),
        binding.source_ordinal,
        binding.container_class.value,
        binding.publication_kind.value,
        binding.storage_family.value,
        binding.outer_compression_kind.value,
        binding.recognition_status.value,
        binding.archive_content_hash,
    )


build_archive_dependency = ArchiveDependencyProjectionInputs.build


__all__ = [
    "ARCHIVE_OBSERVATION_PROFILE",
    "ARCHIVE_OBSERVATION_SNAPSHOT_KIND",
    "CONSOLIDATION_ARCHIVE_DEPENDENCY_PROFILE",
    "MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS",
    "ArchiveDependencyProjectionInputs",
    "ArchiveSourceDependencyBinding",
    "build_archive_dependency",
]
