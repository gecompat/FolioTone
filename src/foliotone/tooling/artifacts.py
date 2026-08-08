"""Runtime artifacts produced by specialist tool executions."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.core._validation import require_non_empty, require_relative_path
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class ToolArtifact:
    """Artifact stored in FolioTone runtime state, never in source media."""

    id: EntityId
    execution_id: EntityId
    artifact_type: str
    relative_path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_type",
            require_non_empty(self.artifact_type, "artifact_type"),
        )
        object.__setattr__(self, "relative_path", require_relative_path(self.relative_path))
        object.__setattr__(self, "sha256", require_non_empty(self.sha256, "sha256"))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
