"""Safe, read-only archive observation contracts."""

from foliotone.archive.sidecars import (
    ARCHIVE_SIDECAR_PROFILE,
    MAX_ARCHIVE_SIDECAR_FILES,
    ArchiveSidecar,
    ArchiveSidecarClassification,
    ArchiveSidecarKind,
    classify_archive_sidecars,
)
from foliotone.archive.signatures import (
    ARCHIVE_SIGNATURE_PROFILE,
    MAX_ARCHIVE_HEADER_BYTES,
    MAX_ARCHIVE_VOLUMES,
    ArchiveContainerClass,
    ArchiveFormatKind,
    ArchiveListingStatus,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservation,
    ArchiveVolumeGroup,
    group_archive_volume_names,
    observe_archive_signature,
)

__all__ = [
    "ARCHIVE_SIGNATURE_PROFILE",
    "MAX_ARCHIVE_HEADER_BYTES",
    "MAX_ARCHIVE_VOLUMES",
    "ArchiveContainerClass",
    "ArchiveFormatKind",
    "ArchiveListingStatus",
    "ArchiveRecognitionStatus",
    "ArchiveSignatureObservation",
    "ArchiveVolumeGroup",
    "group_archive_volume_names",
    "observe_archive_signature",
    "ARCHIVE_SIDECAR_PROFILE",
    "MAX_ARCHIVE_SIDECAR_FILES",
    "ArchiveSidecar",
    "ArchiveSidecarClassification",
    "ArchiveSidecarKind",
    "classify_archive_sidecars",
]
