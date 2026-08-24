"""Versioned adapter-neutral Application contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from foliotone.collection_state import DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT, CollectionQuerySpec
from foliotone.core.ids import EntityId

APPLICATION_CONTRACTS_PROFILE: Final = "application-contracts/v1"


class ApplicationError(RuntimeError):
    """A caller supplied an invalid request for the Application boundary."""


class MediaLine(StrEnum):
    """A separately activated product entry point."""

    EBOOK = "EBOOK"
    MUSIC = "MUSIC"
    IMAGE = "IMAGE"


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    """Versioned request context independent of CLI, HTTP, or worker transport."""

    profile: str = APPLICATION_CONTRACTS_PROFILE
    media_line: MediaLine = MediaLine.EBOOK

    def __post_init__(self) -> None:
        if self.profile != APPLICATION_CONTRACTS_PROFILE:
            raise ApplicationError("Application context profile is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationCommand:
    """Base contract for a future state-changing Application request."""

    context: ApplicationContext = field(default_factory=ApplicationContext)


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicationQuery:
    """Base contract for a read-only Application request."""

    context: ApplicationContext = field(default_factory=ApplicationContext)


@dataclass(frozen=True, slots=True)
class MediaLineDescriptor:
    """One bounded product entry point without a transport-specific route."""

    media_line: MediaLine
    enabled: bool


@dataclass(frozen=True, slots=True)
class MediaLineRegistry:
    """Stable registry of active and future media lines."""

    profile: str
    entries: tuple[MediaLineDescriptor, ...]

    def __post_init__(self) -> None:
        if self.profile != APPLICATION_CONTRACTS_PROFILE:
            raise ApplicationError("Application registry profile is invalid")
        if tuple(entry.media_line for entry in self.entries) != tuple(MediaLine):
            raise ApplicationError("Application media-line registry is incomplete")
        if not self.entries[0].enabled or any(entry.enabled for entry in self.entries[1:]):
            raise ApplicationError("Application media-line activation is invalid")

    @classmethod
    def default(cls) -> MediaLineRegistry:
        return cls(
            profile=APPLICATION_CONTRACTS_PROFILE,
            entries=(
                MediaLineDescriptor(MediaLine.EBOOK, True),
                MediaLineDescriptor(MediaLine.MUSIC, False),
                MediaLineDescriptor(MediaLine.IMAGE, False),
            ),
        )


@dataclass(frozen=True, slots=True)
class EbookToolchainReadinessQuery(ApplicationQuery):
    """Read-only request for the existing E-Book toolchain Doctor."""

    ebook_meta_executable: str
    ebook_convert_executable: str
    calibre_debug_executable: str
    pdfinfo_executable: str
    pdftotext_executable: str
    java_executable: str
    epubcheck_jar: Path


@dataclass(frozen=True, slots=True)
class LibraryHealthQuery(ApplicationQuery):
    """Read-only request for one persisted Library Health projection."""

    snapshot_id: EntityId
    baseline_snapshot_id: EntityId | None = None
    sample_limit: int = DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT


@dataclass(frozen=True, slots=True)
class CollectionStateQuery(ApplicationQuery):
    """Read-only request for one immutable CollectionState snapshot."""

    snapshot_id: EntityId


@dataclass(frozen=True, slots=True)
class CollectionSearchQuery(ApplicationQuery):
    """Read-only, bounded search request for one CollectionState snapshot."""

    snapshot_id: EntityId
    spec: CollectionQuerySpec
    private_details: bool = False


@dataclass(frozen=True, slots=True)
class SurfacePageQuery(ApplicationQuery):
    """Bounded opaque-id page request for surface-owned read models."""

    after_id: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ApplicationError("Surface page limit is invalid")


@dataclass(frozen=True, slots=True)
class ApplicationJobDetailQuery(ApplicationQuery):
    """Read exactly one public ApplicationJob projection."""

    job_id: str


@dataclass(frozen=True, slots=True)
class EbookProjectionQuery(ApplicationQuery):
    """Read one bounded E-Book projection by its opaque persisted identifier."""

    projection_id: EntityId
