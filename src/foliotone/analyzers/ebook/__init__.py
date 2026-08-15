"""Shared contracts for e-book analyzers and replaceable tool adapters."""

from foliotone.analyzers.ebook.cover import (
    COVER_FINGERPRINT_KIND,
    COVER_FINGERPRINT_PROFILE,
    DEFAULT_MAX_EBOOK_COVER_BYTES,
    DEFAULT_MAX_EBOOK_COVER_PIXELS,
    EbookCoverError,
    EbookCoverFingerprint,
    build_cover_fingerprint,
    fingerprint_ebook_cover,
)
from foliotone.analyzers.ebook.metadata import (
    EBOOK_METADATA_CANDIDATE_PROFILE,
    EBOOK_METADATA_CANDIDATE_RESULT,
    EbookMetadataCandidate,
)
from foliotone.analyzers.ebook.observations import ObservedFileError, resolve_observed_file
from foliotone.analyzers.ebook.text import (
    DEFAULT_MAX_EBOOK_TEXT_BYTES,
    TEXT_FINGERPRINT_KIND,
    TEXT_NORMALIZATION_PROFILE,
    EbookTextError,
    NormalizedEbookText,
    build_normalized_text_fingerprint,
    normalize_ebook_text,
)

__all__ = [
    "COVER_FINGERPRINT_KIND",
    "COVER_FINGERPRINT_PROFILE",
    "DEFAULT_MAX_EBOOK_COVER_BYTES",
    "DEFAULT_MAX_EBOOK_COVER_PIXELS",
    "DEFAULT_MAX_EBOOK_TEXT_BYTES",
    "EBOOK_METADATA_CANDIDATE_PROFILE",
    "EBOOK_METADATA_CANDIDATE_RESULT",
    "TEXT_FINGERPRINT_KIND",
    "TEXT_NORMALIZATION_PROFILE",
    "EbookCoverError",
    "EbookCoverFingerprint",
    "EbookTextError",
    "EbookMetadataCandidate",
    "NormalizedEbookText",
    "ObservedFileError",
    "build_cover_fingerprint",
    "build_normalized_text_fingerprint",
    "fingerprint_ebook_cover",
    "normalize_ebook_text",
    "resolve_observed_file",
]
