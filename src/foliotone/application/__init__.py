"""Adapter-neutral application contracts and composition for FolioTone."""

from foliotone.application.composition import create_application
from foliotone.application.contracts import (
    APPLICATION_CONTRACTS_PROFILE,
    ApplicationCommand,
    ApplicationContext,
    ApplicationError,
    ApplicationQuery,
    EbookToolchainReadinessQuery,
    LibraryHealthQuery,
    MediaLine,
    MediaLineDescriptor,
    MediaLineRegistry,
)
from foliotone.application.services import FolioToneApplication

__all__ = [
    "APPLICATION_CONTRACTS_PROFILE",
    "ApplicationCommand",
    "ApplicationContext",
    "ApplicationError",
    "ApplicationQuery",
    "EbookToolchainReadinessQuery",
    "FolioToneApplication",
    "LibraryHealthQuery",
    "MediaLine",
    "MediaLineDescriptor",
    "MediaLineRegistry",
    "create_application",
]
