"""Pure, bounded classification of already-indexed archive sidecar names."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import islice
from typing import Final

from foliotone.archive.signatures import ArchiveListingStatus

ARCHIVE_SIDECAR_PROFILE: Final = "archive-sidecar-classifier/v1"
MAX_ARCHIVE_SIDECAR_FILES: Final = 32


class ArchiveSidecarKind(StrEnum):
    """The fixed sidecar classes permitted by ADR-0038."""

    NFO = "NFO"
    TEXT = "TEXT"
    DIZ = "DIZ"
    INFO = "INFO"
    URL = "URL"
    HTML = "HTML"
    SFV = "SFV"
    README = "README"
    PASSWORD = "PASSWORD"


@dataclass(frozen=True, slots=True)
class ArchiveSidecar:
    """A name-only sidecar observation; no content is accepted or retained."""

    basename: str = field(repr=False)
    kind: ArchiveSidecarKind

    def __post_init__(self) -> None:
        if not isinstance(self.basename, str) or not _is_direct_basename(self.basename):
            raise ValueError("archive sidecar must be a bounded direct basename")
        if not isinstance(self.kind, ArchiveSidecarKind):
            raise ValueError("kind must be ArchiveSidecarKind")
        if _classify_basename(self.basename) is not self.kind:
            raise ValueError("archive sidecar kind does not match basename")


@dataclass(frozen=True, slots=True)
class ArchiveSidecarClassification:
    profile: str
    status: ArchiveListingStatus
    sidecars: tuple[ArchiveSidecar, ...] = ()

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_SIDECAR_PROFILE:
            raise ValueError("unsupported archive sidecar profile")
        if self.status not in {
            ArchiveListingStatus.LISTED,
            ArchiveListingStatus.LIMIT_EXCEEDED,
            ArchiveListingStatus.POLICY_REJECTED,
        }:
            raise ValueError("unsupported archive sidecar status")
        if not isinstance(self.sidecars, tuple):
            raise ValueError("sidecars must be a tuple")
        if len(self.sidecars) > MAX_ARCHIVE_SIDECAR_FILES:
            raise ValueError("archive sidecar classification exceeds the bound")
        if any(not isinstance(sidecar, ArchiveSidecar) for sidecar in self.sidecars):
            raise ValueError("sidecars must contain ArchiveSidecar values")
        expected = tuple(
            sorted(
                self.sidecars,
                key=lambda item: (item.basename.casefold(), item.kind.value),
            )
        )
        if self.sidecars != expected:
            raise ValueError("archive sidecars must be canonically ordered")
        if self.status is not ArchiveListingStatus.LISTED and self.sidecars:
            raise ValueError("non-listed sidecar classifications must be empty")


_EXTENSION_KINDS: Final = {
    ".nfo": ArchiveSidecarKind.NFO,
    ".txt": ArchiveSidecarKind.TEXT,
    ".diz": ArchiveSidecarKind.DIZ,
    ".info": ArchiveSidecarKind.INFO,
    ".url": ArchiveSidecarKind.URL,
    ".html": ArchiveSidecarKind.HTML,
    ".htm": ArchiveSidecarKind.HTML,
    ".sfv": ArchiveSidecarKind.SFV,
}
_EXTENSIONLESS_KINDS: Final = {
    "readme": ArchiveSidecarKind.README,
    "read.me": ArchiveSidecarKind.README,
    "password": ArchiveSidecarKind.PASSWORD,
    "passwort": ArchiveSidecarKind.PASSWORD,
    "pass": ArchiveSidecarKind.PASSWORD,
    "pw": ArchiveSidecarKind.PASSWORD,
}


def classify_archive_sidecars(
    basenames: Iterable[str],
) -> ArchiveSidecarClassification:
    """Classify at most 32 already-indexed direct-directory basenames.

    The input is deliberately names only.  Paths are ignored, which makes a
    nested entry unclassifiable without traversing or opening anything.
    """

    # Consume only the bounded prefix plus one sentinel; an accidental
    # unbounded iterator can therefore never turn this pure classifier into an
    # unbounded operation.
    names = tuple(islice(basenames, MAX_ARCHIVE_SIDECAR_FILES + 1))
    if len(names) > MAX_ARCHIVE_SIDECAR_FILES:
        return ArchiveSidecarClassification(
            ARCHIVE_SIDECAR_PROFILE, ArchiveListingStatus.LIMIT_EXCEEDED
        )
    if any(not isinstance(name, str) for name in names):
        return ArchiveSidecarClassification(
            ARCHIVE_SIDECAR_PROFILE, ArchiveListingStatus.POLICY_REJECTED
        )

    classified = tuple(
        ArchiveSidecar(name, kind)
        for name in names
        if (kind := _classify_basename(name)) is not None
    )
    # Casefolded locator order is deterministic while retaining the observed
    # spelling for evidence; the kind is a stable tie-breaker.
    ordered = tuple(
        sorted(classified, key=lambda item: (item.basename.casefold(), item.kind.value))
    )
    return ArchiveSidecarClassification(
        ARCHIVE_SIDECAR_PROFILE, ArchiveListingStatus.LISTED, ordered
    )


def _classify_basename(name: str) -> ArchiveSidecarKind | None:
    if not _is_direct_basename(name):
        return None
    lowered = name.casefold()
    if lowered in _EXTENSIONLESS_KINDS:
        return _EXTENSIONLESS_KINDS[lowered]
    for extension, kind in _EXTENSION_KINDS.items():
        if lowered.endswith(extension):
            return kind
    return None


def _is_direct_basename(name: str) -> bool:
    return bool(
        name
        and len(name) <= 1_024
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and ":" not in name
        and not any(ord(character) < 32 or ord(character) == 127 for character in name)
    )
