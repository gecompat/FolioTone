"""Opaque provider-independent internal identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class EntityId:
    """Opaque UUID-backed identifier used for FolioTone-owned entities."""

    value: UUID

    @classmethod
    def new(cls) -> EntityId:
        """Create a new random internal identifier."""
        return cls(uuid4())

    @classmethod
    def parse(cls, value: str) -> EntityId:
        """Parse a persisted UUID string."""
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)
