"""Application services over existing FolioTone workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from foliotone.application.contracts import (
    EbookToolchainReadinessQuery,
    LibraryHealthQuery,
    MediaLineRegistry,
)
from foliotone.core.ids import EntityId
from foliotone.tooling.ebook_readiness import EbookToolchainReadinessReport
from foliotone.workflows.library_health import LibraryHealthReport


class LibraryHealthReader(Protocol):
    """Port for reading a persisted Health projection."""

    def read(
        self,
        snapshot_id: EntityId,
        *,
        baseline_snapshot_id: EntityId | None,
        sample_limit: int,
    ) -> LibraryHealthReport: ...


class FolioToneApplication:
    """Adapter-neutral read-only Application surface for the first product slice."""

    def __init__(
        self,
        *,
        media_lines: MediaLineRegistry,
        toolchain_inspector: Callable[..., EbookToolchainReadinessReport],
    ) -> None:
        self._media_lines = media_lines
        self._toolchain_inspector = toolchain_inspector

    @property
    def media_lines(self) -> MediaLineRegistry:
        """Return the stable product-entry registry."""
        return self._media_lines

    def ebook_toolchain_readiness(
        self, query: EbookToolchainReadinessQuery
    ) -> EbookToolchainReadinessReport:
        """Run the existing non-mutating Doctor through the Application boundary."""
        return self._toolchain_inspector(
            ebook_meta_executable=query.ebook_meta_executable,
            ebook_convert_executable=query.ebook_convert_executable,
            calibre_debug_executable=query.calibre_debug_executable,
            pdfinfo_executable=query.pdfinfo_executable,
            pdftotext_executable=query.pdftotext_executable,
            java_executable=query.java_executable,
            epubcheck_jar=query.epubcheck_jar,
        )

    def library_health_report(
        self, reader: LibraryHealthReader, query: LibraryHealthQuery
    ) -> LibraryHealthReport:
        """Read an immutable Health projection through an injected persistence port."""
        return reader.read(
            query.snapshot_id,
            baseline_snapshot_id=query.baseline_snapshot_id,
            sample_limit=query.sample_limit,
        )
