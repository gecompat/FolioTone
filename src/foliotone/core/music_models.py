"""Music work, recording, and release domain models."""

from __future__ import annotations

from dataclasses import dataclass

from foliotone.core._validation import require_non_empty
from foliotone.core.enums import MusicWorkRelationType
from foliotone.core.ids import EntityId


@dataclass(frozen=True, slots=True)
class MusicWork:
    """Composition or musical work independent of a recording."""

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
class MusicWorkRelation:
    """Hierarchy or derivation relationship between two MusicWorks."""

    id: EntityId
    source_work_id: EntityId
    target_work_id: EntityId
    relation_type: MusicWorkRelationType

    def __post_init__(self) -> None:
        if self.source_work_id == self.target_work_id:
            raise ValueError("a MusicWork cannot relate to itself")


@dataclass(frozen=True, slots=True)
class CatalogDesignation:
    """Namespace-qualified catalog designation such as BWV or KV."""

    id: EntityId
    music_work_id: EntityId
    system: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "system", require_non_empty(self.system, "system"))
        object.__setattr__(self, "value", require_non_empty(self.value, "value"))


@dataclass(frozen=True, slots=True)
class Recording:
    """A particular recorded performance or production."""

    id: EntityId
    canonical_title: str | None = None
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        if self.canonical_title is not None:
            object.__setattr__(
                self,
                "canonical_title",
                require_non_empty(self.canonical_title, "canonical_title"),
            )
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")


@dataclass(frozen=True, slots=True)
class ReleaseGroup:
    """Logical album, single, or related release concept."""

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
class Release:
    """Concrete issued release or edition."""

    id: EntityId
    release_group_id: EntityId | None = None
    canonical_title: str | None = None
    release_date: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("canonical_title", "release_date"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_non_empty(value, field_name))


@dataclass(frozen=True, slots=True)
class ReleaseRecording:
    """Placement of a Recording on a concrete Release."""

    id: EntityId
    release_id: EntityId
    recording_id: EntityId
    disc_number: int | None = None
    track_number: int | None = None
    observed_title: str | None = None

    def __post_init__(self) -> None:
        if self.disc_number is not None and self.disc_number <= 0:
            raise ValueError("disc_number must be positive")
        if self.track_number is not None and self.track_number <= 0:
            raise ValueError("track_number must be positive")
        if self.observed_title is not None:
            object.__setattr__(
                self,
                "observed_title",
                require_non_empty(self.observed_title, "observed_title"),
            )
