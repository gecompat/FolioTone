"""Provider-independent persistence contracts used by application code."""

from __future__ import annotations

from typing import Protocol, TypeVar

from foliotone.core.ids import EntityId

T = TypeVar("T")


class Repository(Protocol[T]):
    """Minimal repository contract for immutable EntityId-backed domain records."""

    def save(self, value: T) -> None:
        """Insert or replace the durable representation of one domain record."""
        ...

    def get(self, entity_id: EntityId) -> T | None:
        """Return one record by FolioTone internal ID, or None if absent."""
        ...

    def list_all(self) -> list[T]:
        """Return all records in deterministic primary-key order."""
        ...
