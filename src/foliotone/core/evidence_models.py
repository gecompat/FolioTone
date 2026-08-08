"""Classification, fingerprint, relation, and evidence models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import (
    require_aware_datetime,
    require_confidence,
    require_non_empty,
)
from foliotone.core.common import Provenance
from foliotone.core.enums import EntityKind, MatchStatus, RelationType
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class ClassificationAssertion:
    """Typed classification facet with provenance."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    dimension: str
    value: str
    provenance: Provenance
    taxonomy: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", require_non_empty(self.dimension, "dimension"))
        object.__setattr__(self, "value", require_non_empty(self.value, "value"))
        require_confidence(self.confidence)
        if self.taxonomy is not None:
            object.__setattr__(self, "taxonomy", require_non_empty(self.taxonomy, "taxonomy"))


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Versioned fingerprint attached to a file or resolved entity."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    kind: str
    algorithm: str
    algorithm_version: str
    value: str
    created_at: datetime
    tool_execution_id: EntityId | None = None

    def __post_init__(self) -> None:
        for field_name in ("kind", "algorithm", "algorithm_version", "value"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, require_non_empty(value, field_name))
        require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Relation:
    """Typed relationship between two entities at an explicit identity level."""

    id: EntityId
    left_kind: EntityKind
    left_id: EntityId
    right_kind: EntityKind
    right_id: EntityId
    relation_type: RelationType
    confidence: float
    status: MatchStatus
    created_at: datetime

    def __post_init__(self) -> None:
        require_confidence(self.confidence)
        require_aware_datetime(self.created_at, "created_at")
        if self.left_kind == self.right_kind and self.left_id == self.right_id:
            raise ValueError("a Relation must connect two distinct entities")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Human-readable supporting or contradicting evidence for a Relation."""

    id: EntityId
    relation_id: EntityId
    evidence_type: str
    summary: str
    provenance: Provenance
    strength: float | None = None
    tool_execution_id: EntityId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_type",
            require_non_empty(self.evidence_type, "evidence_type"),
        )
        object.__setattr__(self, "summary", require_non_empty(self.summary, "summary"))
        if self.strength is not None and not -1.0 <= self.strength <= 1.0:
            raise ValueError("strength must be between -1.0 and 1.0")
