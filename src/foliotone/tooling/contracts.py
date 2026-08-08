"""Provider-neutral contracts for specialist tool orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import (
    require_aware_datetime,
    require_confidence,
    require_non_empty,
)
from foliotone.core.enums import EntityKind, ToolCapability, ToolExecutionStatus
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class ToolProviderDescriptor:
    """Stable FolioTone-facing description of a replaceable specialist tool adapter."""

    provider_id: str
    display_name: str
    adapter_version: str
    capabilities: frozenset[ToolCapability]
    optional: bool = True
    default_read_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", require_non_empty(self.provider_id, "provider_id"))
        object.__setattr__(self, "display_name", require_non_empty(self.display_name, "display_name"))
        object.__setattr__(
            self,
            "adapter_version",
            require_non_empty(self.adapter_version, "adapter_version"),
        )
        if not self.capabilities:
            raise ValueError("a ToolProviderDescriptor requires at least one capability")
        if not self.default_read_only:
            raise ValueError("write-capable ToolProviders are not permitted before W10")


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Auditable invocation of one specialist tool capability."""

    id: EntityId
    provider_id: str
    tool_version: str
    adapter_version: str
    capability: ToolCapability
    input_identity: str
    started_at: datetime
    status: ToolExecutionStatus
    finished_at: datetime | None = None
    exit_code: int | None = None
    config_identity: str | None = None
    error_summary: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "tool_version", "adapter_version", "input_identity"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, require_non_empty(value, field_name))
        require_aware_datetime(self.started_at, "started_at")
        if self.finished_at is not None:
            require_aware_datetime(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise ValueError("finished_at must not be before started_at")
        terminal = {
            ToolExecutionStatus.SUCCEEDED,
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
        }
        if self.status in terminal and self.finished_at is None:
            raise ValueError("terminal ToolExecution status requires finished_at")
        if self.status not in terminal and self.finished_at is not None:
            raise ValueError("non-terminal ToolExecution status must not have finished_at")
        if self.status is ToolExecutionStatus.SUCCEEDED and self.exit_code not in {None, 0}:
            raise ValueError("successful ToolExecution must have exit code 0 or no exit code")
        if self.config_identity is not None:
            object.__setattr__(
                self,
                "config_identity",
                require_non_empty(self.config_identity, "config_identity"),
            )
        if self.error_summary is not None:
            object.__setattr__(
                self,
                "error_summary",
                require_non_empty(self.error_summary, "error_summary"),
            )


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalized result derived from a specific ToolExecution."""

    id: EntityId
    execution_id: EntityId
    result_type: str
    target_kind: EntityKind
    target_id: EntityId
    key: str
    value: str
    confidence: float | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("result_type", "key", "value"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, require_non_empty(value, field_name))
        require_confidence(self.confidence)
        if self.explanation is not None:
            object.__setattr__(
                self,
                "explanation",
                require_non_empty(self.explanation, "explanation"),
            )
