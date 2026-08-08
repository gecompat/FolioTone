"""Auditable incremental file-scan outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import require_aware_datetime, require_relative_path
from foliotone.core.enums import FileChangeState
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class FileScanEvent:
    """Per-file scan outcome, including absence without inventing observations."""

    id: EntityId
    file_id: EntityId
    scan_run_id: EntityId
    change_state: FileChangeState
    recorded_at: datetime
    previous_relative_path: str | None = None
    current_relative_path: str | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.recorded_at, "recorded_at")
        for field_name in ("previous_relative_path", "current_relative_path"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_relative_path(value))
