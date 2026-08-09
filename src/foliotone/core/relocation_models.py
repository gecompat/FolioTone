"""Conservative file relocation candidate contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from foliotone.core._validation import (
    require_aware_datetime,
    require_non_empty,
    require_relative_path,
)
from foliotone.core.ids import EntityId


class RelocationCandidateKind(StrEnum):
    """Path-change shape observed for an unconfirmed relocation candidate."""

    RENAMED = "RENAMED"
    MOVED = "MOVED"
    MOVED_AND_RENAMED = "MOVED_AND_RENAMED"


@dataclass(frozen=True, slots=True)
class FileRelocationCandidate:
    """Evidence-backed candidate linking an absent FileRecord to a new FileRecord."""

    id: EntityId
    scan_run_id: EntityId
    source_file_id: EntityId
    target_file_id: EntityId
    kind: RelocationCandidateKind
    source_relative_path: str
    target_relative_path: str
    source_fingerprint_id: EntityId
    target_fingerprint_id: EntityId
    fingerprint_kind: str
    fingerprint_algorithm: str
    fingerprint_algorithm_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.source_file_id == self.target_file_id:
            raise ValueError("a relocation candidate must connect distinct FileRecords")
        object.__setattr__(
            self,
            "source_relative_path",
            require_relative_path(self.source_relative_path),
        )
        object.__setattr__(
            self,
            "target_relative_path",
            require_relative_path(self.target_relative_path),
        )
        if self.source_relative_path == self.target_relative_path:
            raise ValueError("a relocation candidate requires distinct relative paths")
        for field_name in (
            "fingerprint_kind",
            "fingerprint_algorithm",
            "fingerprint_algorithm_version",
        ):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, require_non_empty(value, field_name))
        require_aware_datetime(self.created_at, "created_at")
