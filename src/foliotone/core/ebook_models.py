"""E-book work, edition, and series domain models."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.core._validation import require_non_empty
from foliotone.core.enums import EntityKind
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class Work:
    """Intellectual work independent of a concrete publication or file."""

    id: EntityId
    canonical_title: str | None = None

    def __post_init__(self) -> None:
        if self.canonical_title is not None:
            object.__setattr__(
                self,
                "canonical_title",
                require_non_empty(self.canonical_title, "canonical_title"),
            )


@dataclass(frozen=True, slots=True)
class Edition:
    """Publication, edition, or translation of a Work."""

    id: EntityId
    work_id: EntityId
    canonical_title: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("canonical_title", "language"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_non_empty(value, field_name))


@dataclass(frozen=True, slots=True)
class Series:
    """Bibliographic series identity independent of one observed spelling."""

    id: EntityId
    canonical_name: str | None = None

    def __post_init__(self) -> None:
        if self.canonical_name is not None:
            object.__setattr__(
                self,
                "canonical_name",
                require_non_empty(self.canonical_name, "canonical_name"),
            )


@dataclass(frozen=True, slots=True)
class SeriesMembership:
    """Work- or Edition-level membership in a Series."""

    id: EntityId
    series_id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    position: str | None = None

    def __post_init__(self) -> None:
        if self.target_kind not in {EntityKind.WORK, EntityKind.EDITION}:
            raise ValueError("SeriesMembership target must be WORK or EDITION")
        if self.position is not None:
            object.__setattr__(self, "position", require_non_empty(self.position, "position"))
