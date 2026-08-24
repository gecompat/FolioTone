"""Adapter-neutral application contracts and composition for FolioTone."""

from foliotone.application.composition import create_application
from foliotone.application.contracts import (
    APPLICATION_CONTRACTS_PROFILE,
    ApplicationCommand,
    ApplicationContext,
    ApplicationError,
    ApplicationJobDetailQuery,
    ApplicationQuery,
    CollectionSearchQuery,
    CollectionStateQuery,
    EbookProjectionQuery,
    EbookToolchainReadinessQuery,
    LibraryHealthQuery,
    MediaLine,
    MediaLineDescriptor,
    MediaLineRegistry,
    SurfacePageQuery,
)
from foliotone.application.services import FolioToneApplication

__all__ = [
    "APPLICATION_CONTRACTS_PROFILE",
    "ApplicationCommand",
    "ApplicationContext",
    "ApplicationError",
    "ApplicationJobDetailQuery",
    "ApplicationQuery",
    "CollectionStateQuery",
    "CollectionSearchQuery",
    "EbookToolchainReadinessQuery",
    "EbookProjectionQuery",
    "FolioToneApplication",
    "LibraryHealthQuery",
    "MediaLine",
    "MediaLineDescriptor",
    "MediaLineRegistry",
    "SurfacePageQuery",
    "create_application",
]
