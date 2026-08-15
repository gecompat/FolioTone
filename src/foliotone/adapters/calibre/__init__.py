"""Read-only calibre adapter package."""

from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.cover import (
    CALIBRE_COVER_FORMATS,
    CALIBRE_COVER_PROVIDER,
    CALIBRE_COVER_SUFFIXES,
    CalibreCoverAnalyzer,
    CalibreCoverError,
    CalibreCoverExtractionResult,
    CalibreCoverOutcome,
    parse_calibre_cover_result,
)
from foliotone.adapters.calibre.metadata import (
    CALIBRE_PROVIDER,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    CalibreMetadataProjection,
    parse_calibre_opf,
    project_calibre_opf,
)
from foliotone.adapters.calibre.text import (
    CALIBRE_TEXT_FORMATS,
    CALIBRE_TEXT_PROVIDER,
    CALIBRE_TEXT_SUFFIXES,
    CalibreTextAnalyzer,
    CalibreTextError,
    CalibreTextOutcome,
    NormalizedEbookText,
    normalize_ebook_text,
)
from foliotone.analyzers.ebook import (
    EBOOK_METADATA_CANDIDATE_PROFILE,
    EBOOK_METADATA_CANDIDATE_RESULT,
)

__all__ = [
    "CALIBRE_COVER_FORMATS",
    "CALIBRE_COVER_PROVIDER",
    "CALIBRE_COVER_SUFFIXES",
    "CALIBRE_PROVIDER",
    "CALIBRE_TEXT_FORMATS",
    "CALIBRE_TEXT_PROVIDER",
    "CALIBRE_TEXT_SUFFIXES",
    "EBOOK_METADATA_CANDIDATE_PROFILE",
    "EBOOK_METADATA_CANDIDATE_RESULT",
    "CalibreCoverAnalyzer",
    "CalibreCoverError",
    "CalibreCoverExtractionResult",
    "CalibreCoverOutcome",
    "CalibreMetadataAnalyzer",
    "CalibreMetadataError",
    "CalibreMetadataOutcome",
    "CalibreMetadataProjection",
    "CalibreTextAnalyzer",
    "CalibreTextError",
    "CalibreTextOutcome",
    "NormalizedEbookText",
    "calibre_version_policy",
    "normalize_ebook_text",
    "parse_calibre_opf",
    "parse_calibre_cover_result",
    "project_calibre_opf",
]
