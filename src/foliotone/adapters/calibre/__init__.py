"""Read-only calibre adapter package."""

from foliotone.adapters.calibre.metadata import (
    CALIBRE_PROVIDER,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    calibre_version_policy,
    parse_calibre_opf,
)

__all__ = [
    "CALIBRE_PROVIDER",
    "CalibreMetadataAnalyzer",
    "CalibreMetadataError",
    "CalibreMetadataOutcome",
    "calibre_version_policy",
    "parse_calibre_opf",
]
