"""Read-only Poppler adapter package."""

from foliotone.adapters.poppler.pdf import (
    POPPLER_INFO_PROVIDER,
    POPPLER_TEXT_PROVIDER,
    PopplerPdfAnalyzer,
    PopplerPdfError,
    PopplerPdfOutcome,
    parse_pdfinfo_output,
    poppler_version_policy,
)

__all__ = [
    "POPPLER_INFO_PROVIDER",
    "POPPLER_TEXT_PROVIDER",
    "PopplerPdfAnalyzer",
    "PopplerPdfError",
    "PopplerPdfOutcome",
    "parse_pdfinfo_output",
    "poppler_version_policy",
]
