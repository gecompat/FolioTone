"""Deterministic, path-free contracts for CollectionState diff v1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from foliotone.core.ids import EntityId

from .contracts import CollectionStateItem, CollectionStateItemState

COLLECTION_STATE_DIFF_PROFILE: Final = "collection-state-diff/v1"
DEFAULT_COLLECTION_STATE_DIFF_LIMIT: Final = 100
MAX_COLLECTION_STATE_DIFF_LIMIT: Final = 1000


class CollectionStateDiffCategory(StrEnum):
    ADDED = "ADDED"
    DISAPPEARED = "DISAPPEARED"
    TECHNICALLY_CHANGED = "TECHNICALLY_CHANGED"
    NEWLY_ANALYZED = "NEWLY_ANALYZED"
    NEWLY_RESOLVED = "NEWLY_RESOLVED"
    NEWLY_REVIEWED = "NEWLY_REVIEWED"
    NEWLY_BLOCKED = "NEWLY_BLOCKED"


COLLECTION_STATE_DIFF_CATEGORY_ORDER: Final = tuple(CollectionStateDiffCategory)


@dataclass(frozen=True, slots=True)
class CollectionStateDiffRequest:
    before_snapshot_id: EntityId
    after_snapshot_id: EntityId
    limit: int = DEFAULT_COLLECTION_STATE_DIFF_LIMIT
    after_file_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.before_snapshot_id, EntityId) or not isinstance(
            self.after_snapshot_id, EntityId
        ):
            raise ValueError("CollectionState diff snapshot IDs are invalid")
        if self.before_snapshot_id == self.after_snapshot_id:
            raise ValueError("CollectionState diff requires two distinct snapshots")
        if isinstance(self.limit, bool) or not 1 <= self.limit <= MAX_COLLECTION_STATE_DIFF_LIMIT:
            raise ValueError(
                f"CollectionState diff limit must be between 1 and "
                f"{MAX_COLLECTION_STATE_DIFF_LIMIT}"
            )
        if self.after_file_id is not None and not isinstance(self.after_file_id, EntityId):
            raise ValueError("CollectionState diff cursor is invalid")


@dataclass(frozen=True, slots=True)
class CollectionStateDiffEntry:
    file_id: EntityId
    categories: tuple[CollectionStateDiffCategory, ...]
    before_observation_id: EntityId | None
    after_observation_id: EntityId | None

    def __post_init__(self) -> None:
        if not isinstance(self.file_id, EntityId):
            raise ValueError("CollectionState diff file ID is invalid")
        if self.before_observation_id is not None and not isinstance(
            self.before_observation_id, EntityId
        ):
            raise ValueError("CollectionState diff before observation ID is invalid")
        if self.after_observation_id is not None and not isinstance(
            self.after_observation_id, EntityId
        ):
            raise ValueError("CollectionState diff after observation ID is invalid")
        categories = tuple(self.categories)
        expected = tuple(
            category for category in COLLECTION_STATE_DIFF_CATEGORY_ORDER if category in categories
        )
        if not categories or categories != expected or len(categories) != len(set(categories)):
            raise ValueError("CollectionState diff categories must be non-empty and ordered")
        if CollectionStateDiffCategory.ADDED in categories:
            if categories != (CollectionStateDiffCategory.ADDED,) or (
                self.before_observation_id is not None or self.after_observation_id is None
            ):
                raise ValueError("added diff entries require only an after observation")
        elif CollectionStateDiffCategory.DISAPPEARED in categories:
            if categories != (CollectionStateDiffCategory.DISAPPEARED,) or (
                self.before_observation_id is None or self.after_observation_id is not None
            ):
                raise ValueError("disappeared diff entries require only a before observation")
        elif self.before_observation_id is None or self.after_observation_id is None:
            raise ValueError("transition diff entries require both observations")


@dataclass(frozen=True, slots=True)
class CollectionStateDiffResult:
    before_snapshot_id: EntityId
    after_snapshot_id: EntityId
    scan_root_id: EntityId
    category_counts: tuple[tuple[CollectionStateDiffCategory, int], ...]
    total_changed_items: int
    entries: tuple[CollectionStateDiffEntry, ...]
    truncated: bool
    next_after_file_id: EntityId | None
    profile: str = COLLECTION_STATE_DIFF_PROFILE

    def __post_init__(self) -> None:
        if self.profile != COLLECTION_STATE_DIFF_PROFILE:
            raise ValueError("CollectionState diff profile is invalid")
        if any(
            not isinstance(value, EntityId)
            for value in (self.before_snapshot_id, self.after_snapshot_id, self.scan_root_id)
        ):
            raise ValueError("CollectionState diff IDs are invalid")
        if self.before_snapshot_id == self.after_snapshot_id:
            raise ValueError("CollectionState diff result snapshots must be distinct")
        if tuple(category for category, _count in self.category_counts) != (
            COLLECTION_STATE_DIFF_CATEGORY_ORDER
        ):
            raise ValueError("CollectionState diff counts must be complete and ordered")
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for _category, count in self.category_counts
        ):
            raise ValueError("CollectionState diff counts must be nonnegative")
        if (
            isinstance(self.total_changed_items, bool)
            or not isinstance(self.total_changed_items, int)
            or self.total_changed_items < 0
        ):
            raise ValueError("CollectionState diff total must be nonnegative")
        entries = tuple(self.entries)
        file_ids = tuple(str(entry.file_id) for entry in entries)
        if file_ids != tuple(sorted(set(file_ids))):
            raise ValueError("CollectionState diff entries must be sorted and unique")
        if self.total_changed_items < len(entries) or any(
            count > self.total_changed_items for _category, count in self.category_counts
        ):
            raise ValueError("CollectionState diff totals are inconsistent")
        if self.truncated != (self.next_after_file_id is not None):
            raise ValueError("CollectionState diff cursor and truncation marker disagree")
        if self.truncated and (not entries or self.next_after_file_id != entries[-1].file_id):
            raise ValueError("CollectionState diff cursor must identify the last result")


def collection_state_item_diff_categories(
    before: CollectionStateItem,
    after: CollectionStateItem,
) -> tuple[CollectionStateDiffCategory, ...]:
    """Classify only changes directly supported by both persisted item states."""

    if before.file_id != after.file_id:
        raise ValueError("CollectionState item diff requires the same file ID")
    changed: set[CollectionStateDiffCategory] = set()
    stable_technical_changed = (
        before.format_name != after.format_name
        or before.size_bytes != after.size_bytes
        or (
            before.observation_id == after.observation_id
            and before.technical_digest != after.technical_digest
        )
    )
    if stable_technical_changed:
        changed.add(CollectionStateDiffCategory.TECHNICALLY_CHANGED)
    for category, component in (
        (CollectionStateDiffCategory.NEWLY_ANALYZED, "analysis"),
        (CollectionStateDiffCategory.NEWLY_RESOLVED, "resolution"),
        (CollectionStateDiffCategory.NEWLY_REVIEWED, "review"),
    ):
        before_state = getattr(before, f"{component}_state")
        after_state = getattr(after, f"{component}_state")
        if not _is_current(before_state) and _is_current(after_state):
            changed.add(category)
    if not _is_blocked(before) and _is_blocked(after):
        changed.add(CollectionStateDiffCategory.NEWLY_BLOCKED)
    return tuple(
        category for category in COLLECTION_STATE_DIFF_CATEGORY_ORDER if category in changed
    )


def _is_current(state: CollectionStateItemState) -> bool:
    return state in {
        CollectionStateItemState.CURRENT,
        CollectionStateItemState.CURRENT_CONFLICT,
    }


def _is_blocked(item: CollectionStateItem) -> bool:
    conflict_states = {
        CollectionStateItemState.CURRENT_CONFLICT,
        CollectionStateItemState.STALE_CONFLICT,
        CollectionStateItemState.UNSCOPED_CONFLICT,
    }
    return item.consolidation_state in conflict_states or item.quarantine_state in conflict_states
