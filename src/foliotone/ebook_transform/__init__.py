"""Pure byte-in/byte-out EPUB transformation profile for GATE-0002."""

from .contracts import (
    CANONICAL_EPUB_PROFILE,
    METADATA_INVENTORY_KEYS,
    METADATA_SNAPSHOT_PROFILE,
    CanonicalEpubProfile,
    CanonicalEpubResult,
    EbookTransformError,
    EbookTransformErrorCode,
    EpubInspection,
    EpubMemberInspection,
    MetadataDisposition,
    MetadataProvenance,
    TransformMetadataField,
    TransformMetadataSnapshot,
)
from .profile import canonicalize_epub3, inspect_epub3, verify_canonical_epub3

__all__ = [
    "CANONICAL_EPUB_PROFILE",
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
    "canonicalize_epub3",
    "inspect_epub3",
    "verify_canonical_epub3",
]
