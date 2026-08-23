"""Concrete composition root for the first read-only Application services."""

from __future__ import annotations

from collections.abc import Callable

from foliotone.application.contracts import MediaLineRegistry
from foliotone.application.services import FolioToneApplication
from foliotone.tooling.ebook_readiness import (
    EbookToolchainReadinessReport,
    inspect_ebook_toolchain,
)


def create_application(
    *,
    toolchain_inspector: Callable[..., EbookToolchainReadinessReport] = inspect_ebook_toolchain,
) -> FolioToneApplication:
    """Compose the adapter-neutral read-only Application surface."""
    return FolioToneApplication(
        media_lines=MediaLineRegistry.default(),
        toolchain_inspector=toolchain_inspector,
    )
