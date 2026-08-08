"""Shared provenance and assertion models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import (
    require_aware_datetime,
    require_confidence,
    require_non_empty,
)
from foliotone.core.enums import EntityKind, ValueState
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class Provenance:
    """Identifies where an observation or derived value came from."""

    source_kind: str
    source_name: str
    observed_at: datetime
    source_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", require_non_empty(self.source_kind, "source_kind"))
        object.__setattr__(self, "source_name", require_non_empty(self.source_name, "source_name"))
        require_aware_datetime(self.observed_at, "observed_at")
        if self.source_version is not None:
            object.__setattr__(
                self,
                "source_version",
                require_non_empty(self.source_version, "source_version"),
            )


@dataclass(frozen=True, slots=True)
class ValueAssertion:
    """One provenance-preserving value attached to a domain entity."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    field_name: str
    value: str
    state: ValueState
    provenance: Provenance
    confidence: float | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_name", require_non_empty(self.field_name, "field_name"))
        object.__setattr__(self, "value", require_non_empty(self.value, "value"))
        require_confidence(self.confidence)
        if self.explanation is not None:
            object.__setattr__(
                self,
                "explanation",
                require_non_empty(self.explanation, "explanation"),
            )
