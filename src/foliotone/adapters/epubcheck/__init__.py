"""Read-only EPUBCheck adapter package."""

from foliotone.adapters.epubcheck.validation import (
    EPUBCHECK_CONFIG_IDENTITY,
    EPUBCHECK_PROVIDER,
    EPUBCHECK_REPORT_ARTIFACT,
    EpubCheckAnalyzer,
    EpubCheckError,
    EpubCheckOutcome,
    epubcheck_version_policy,
    parse_epubcheck_report,
)

__all__ = [
    "EPUBCHECK_CONFIG_IDENTITY",
    "EPUBCHECK_PROVIDER",
    "EPUBCHECK_REPORT_ARTIFACT",
    "EpubCheckAnalyzer",
    "EpubCheckError",
    "EpubCheckOutcome",
    "epubcheck_version_policy",
    "parse_epubcheck_report",
]
