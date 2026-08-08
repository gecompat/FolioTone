"""Physical file and incremental-scan domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import (
    require_aware_datetime,
    require_non_empty,
    require_relative_path,
)
from foliotone.core.enums import MediaType, PresenceState, ScanRunStatus
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class ScanRoot:
    """Logical source root; host mount paths remain configuration concerns."""

    id: EntityId
    name: str
    media_type: MediaType
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "name"))


@dataclass(frozen=True, slots=True)
class ScanRun:
    """One auditable scan attempt for a configured root."""

    id: EntityId
    scan_root_id: EntityId
    started_at: datetime
    status: ScanRunStatus
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not be before started_at")
        if self.status is ScanRunStatus.RUNNING and self.completed_at is not None:
            raise ValueError("a running scan cannot have completed_at")
        if self.status is not ScanRunStatus.RUNNING and self.completed_at is None:
            raise ValueError("a finished scan requires completed_at")


@dataclass(frozen=True, slots=True)
class FileRecord:
    """A concrete file known to FolioTone, independent of media identity."""

    id: EntityId
    scan_root_id: EntityId
    relative_path: str
    size_bytes: int
    modified_at: datetime
    media_type: MediaType
    presence_state: PresenceState
    first_seen_at: datetime
    last_seen_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", require_relative_path(self.relative_path))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        require_aware_datetime(self.modified_at, "modified_at")
        require_aware_datetime(self.first_seen_at, "first_seen_at")
        require_aware_datetime(self.last_seen_at, "last_seen_at")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at must not be before first_seen_at")


@dataclass(frozen=True, slots=True)
class FileObservation:
    """Observed file state tied to a particular scan run."""

    id: EntityId
    file_id: EntityId
    scan_run_id: EntityId
    relative_path: str
    size_bytes: int
    modified_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", require_relative_path(self.relative_path))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        require_aware_datetime(self.modified_at, "modified_at")
        require_aware_datetime(self.observed_at, "observed_at")
