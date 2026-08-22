"""Pure contracts for planned, still non-executable source-metadata writes."""

from foliotone.metadata_write import contracts as _contracts
from foliotone.metadata_write.contracts import *  # noqa: F403
from foliotone.metadata_write.epub_title import (
    build_epub3_title_package_patch,
    preflight_epub3_title_write,
    verify_epub3_title_archive_diff,
)

__all__ = [
    *_contracts.__all__,
    "build_epub3_title_package_patch",
    "preflight_epub3_title_write",
    "verify_epub3_title_archive_diff",
]
