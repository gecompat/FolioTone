"""Immutable Calibre library snapshot and ownership contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath

from foliotone.core import EntityId
from foliotone.core._validation import require_aware_datetime, require_non_empty

CALIBRE_LIBRARY_SNAPSHOT_PROFILE = "calibre-library-snapshot/v1"
MAX_CALIBRE_METADATA_CHARS = 4096
MAX_CALIBRE_AUTHORS = 256
MAX_CALIBRE_IDENTIFIERS = 128

_FORMAT_LABEL = re.compile(r"[A-Z0-9]{1,16}\Z")


class CalibreLibrarySnapshotStatus(StrEnum):
    """Lifecycle of one consistency-checked external library capture."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"
    FAILED = "FAILED"


class CalibreLibrarySidecarKind(StrEnum):
    """Fixed ownership classifications from ADR-0033."""

    METADATA_OPF = "METADATA_OPF"
    COVER = "COVER"
    EXTRA_DATA = "EXTRA_DATA"
    KNOWN_SIDECAR = "KNOWN_SIDECAR"
    UNKNOWN_SIDECAR = "UNKNOWN_SIDECAR"


_TERMINAL_SNAPSHOT_STATUSES = frozenset(
    {
        CalibreLibrarySnapshotStatus.COMPLETED,
        CalibreLibrarySnapshotStatus.INVALIDATED,
        CalibreLibrarySnapshotStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class CalibreLibrarySnapshot:
    """Path-free lineage for one bounded Calibre library capture."""

    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    profile: str
    adapter_version: str
    tool_version: str
    parser_version: str
    library_identity_digest: str = field(repr=False)
    initial_inventory_digest: str | None = field(repr=False)
    final_inventory_digest: str | None = field(repr=False)
    status: CalibreLibrarySnapshotStatus
    started_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CalibreLibrarySnapshotStatus):
            raise ValueError("status must be a CalibreLibrarySnapshotStatus")
        for field_name in ("profile", "adapter_version", "tool_version", "parser_version"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "library_identity_digest",
            _require_sha256(self.library_identity_digest, "library_identity_digest"),
        )
        for field_name in ("initial_inventory_digest", "final_inventory_digest"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _require_sha256(value, field_name))
        require_aware_datetime(self.started_at, "started_at")
        terminal = self.status in _TERMINAL_SNAPSHOT_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError("only terminal Calibre snapshots require completed_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("Calibre snapshot completion precedes its start")
        if self.status is CalibreLibrarySnapshotStatus.RUNNING:
            if self.final_inventory_digest is not None:
                raise ValueError("running Calibre snapshot cannot have a final digest")
        elif self.status is CalibreLibrarySnapshotStatus.COMPLETED:
            if (
                self.initial_inventory_digest is None
                or self.final_inventory_digest is None
                or self.initial_inventory_digest != self.final_inventory_digest
            ):
                raise ValueError("completed Calibre snapshot requires equal inventory digests")
        elif self.status is CalibreLibrarySnapshotStatus.INVALIDATED:
            if (
                self.initial_inventory_digest is None
                or self.final_inventory_digest is None
                or self.initial_inventory_digest == self.final_inventory_digest
            ):
                raise ValueError("invalidated Calibre snapshot requires changed inventory")


@dataclass(frozen=True, slots=True)
class CalibreLibraryRecordSnapshot:
    """Bounded observed metadata for one record in one library snapshot."""

    id: EntityId
    snapshot_id: EntityId
    calibre_record_id: int
    metadata_fingerprint: str = field(repr=False)
    calibre_uuid: str | None = field(default=None, repr=False)
    title: str | None = field(default=None, repr=False)
    authors: tuple[str, ...] = field(default=(), repr=False)
    identifiers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    last_modified_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.calibre_record_id, bool)
            or not isinstance(self.calibre_record_id, int)
            or self.calibre_record_id < 0
        ):
            raise ValueError("calibre_record_id must be a nonnegative integer")
        object.__setattr__(
            self,
            "metadata_fingerprint",
            _require_sha256(self.metadata_fingerprint, "metadata_fingerprint"),
        )
        for field_name in ("calibre_uuid", "title"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _require_bounded_text(value, field_name))
        if len(self.authors) > MAX_CALIBRE_AUTHORS:
            raise ValueError("authors exceed the configured count limit")
        authors = tuple(_require_bounded_text(value, "author") for value in self.authors)
        object.__setattr__(self, "authors", authors)
        if len(self.identifiers) > MAX_CALIBRE_IDENTIFIERS:
            raise ValueError("identifiers exceed the configured count limit")
        identifiers = tuple(
            sorted(
                (
                    _require_bounded_text(namespace, "identifier namespace"),
                    _require_bounded_text(value, "identifier value"),
                )
                for namespace, value in self.identifiers
            )
        )
        if len({namespace for namespace, _value in identifiers}) != len(identifiers):
            raise ValueError("identifier namespaces must be unique")
        object.__setattr__(self, "identifiers", identifiers)
        if self.last_modified_at is not None:
            require_aware_datetime(self.last_modified_at, "last_modified_at")


@dataclass(frozen=True, slots=True)
class CalibreLibraryFormatSnapshot:
    """Private relative locator and optional file ownership for one record format."""

    id: EntityId
    record_snapshot_id: EntityId
    format_label: str
    relative_locator: str = field(repr=False)
    declared_size_bytes: int | None = None
    observation_id: EntityId | None = None

    def __post_init__(self) -> None:
        label = require_non_empty(self.format_label, "format_label").upper()
        if _FORMAT_LABEL.fullmatch(label) is None:
            raise ValueError("format_label is invalid")
        object.__setattr__(self, "format_label", label)
        locator = _require_private_relative_locator(self.relative_locator)
        suffix = PurePosixPath(locator).suffix[1:].upper()
        if suffix != label:
            raise ValueError("format_label does not match the locator suffix")
        object.__setattr__(self, "relative_locator", locator)
        if self.declared_size_bytes is not None:
            if (
                isinstance(self.declared_size_bytes, bool)
                or not isinstance(self.declared_size_bytes, int)
                or self.declared_size_bytes < 0
            ):
                raise ValueError("declared_size_bytes must not be negative")


@dataclass(frozen=True, slots=True)
class CalibreLibrarySidecarSnapshot:
    """One classified record-local sidecar with optional file ownership."""

    id: EntityId
    record_snapshot_id: EntityId
    kind: CalibreLibrarySidecarKind
    relative_locator: str = field(repr=False)
    observation_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CalibreLibrarySidecarKind):
            raise ValueError("kind must be a CalibreLibrarySidecarKind")
        object.__setattr__(
            self,
            "relative_locator",
            _require_private_relative_locator(self.relative_locator),
        )


def _require_sha256(value: str, field_name: str) -> str:
    digest = require_non_empty(value, field_name).casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    return digest


def _require_bounded_text(value: str, field_name: str) -> str:
    text = require_non_empty(value, field_name)
    if len(text) > MAX_CALIBRE_METADATA_CHARS:
        raise ValueError(f"{field_name} exceeds the configured size limit")
    if any(ord(character) < 32 for character in text):
        raise ValueError(f"{field_name} contains control characters")
    return text


def _require_private_relative_locator(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_CALIBRE_METADATA_CHARS:
        raise ValueError("relative_locator is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError("relative_locator is invalid")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ":" in normalized
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or path.as_posix() != normalized
    ):
        raise ValueError("relative_locator must be a safe private relative path")
    return normalized
