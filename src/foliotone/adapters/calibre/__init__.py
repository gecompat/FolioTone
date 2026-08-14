"""Read-only calibre adapter package."""

from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.metadata import (
    CALIBRE_PROVIDER,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    parse_calibre_opf,
)
from foliotone.adapters.calibre.text import (
    CALIBRE_TEXT_PROVIDER,
    CalibreTextAnalyzer,
    CalibreTextError,
    CalibreTextOutcome,
    NormalizedEbookText,
    normalize_ebook_text,
)

__all__ = [
    "CALIBRE_PROVIDER",
    "CALIBRE_TEXT_PROVIDER",
    "CalibreMetadataAnalyzer",
    "CalibreMetadataError",
    "CalibreMetadataOutcome",
    "CalibreTextAnalyzer",
    "CalibreTextError",
    "CalibreTextOutcome",
    "NormalizedEbookText",
    "calibre_version_policy",
    "normalize_ebook_text",
    "parse_calibre_opf",
]
