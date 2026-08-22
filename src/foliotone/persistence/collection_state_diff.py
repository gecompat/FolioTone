"""Bounded deterministic comparison of two immutable CollectionState snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from foliotone.collection_state import (
    COLLECTION_STATE_DIFF_CATEGORY_ORDER,
    CollectionStateDiffCategory,
    CollectionStateDiffEntry,
    CollectionStateDiffRequest,
    CollectionStateDiffResult,
    CollectionStateItem,
    CollectionStateSnapshot,
    collection_state_item_diff_categories,
)
from foliotone.persistence.collection_state import (
    CollectionStateStoreError,
    SQLiteCollectionStateStore,
    _item_from_row,
)
from foliotone.persistence.collection_state_schema import collection_state_items


class CollectionStateDiffStoreError(RuntimeError):
    """Two CollectionState snapshots cannot be compared safely."""


class SQLiteCollectionStateDiffReader:
    """Compare persisted snapshots through bounded keyset reads."""

    def __init__(self, engine: Engine, *, batch_size: int = 500) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
            raise ValueError("CollectionState diff batch_size must be between 1 and 1000")
        self._engine = engine
        self._batch_size = batch_size
        self._state_store = SQLiteCollectionStateStore(engine, batch_size=batch_size)

    def read(self, request: CollectionStateDiffRequest) -> CollectionStateDiffResult:
        if not isinstance(request, CollectionStateDiffRequest):
            raise ValueError("CollectionState diff request is invalid")
        try:
            before = self._state_store.get(request.before_snapshot_id)
            after = self._state_store.get(request.after_snapshot_id)
            if before is None or after is None:
                raise CollectionStateDiffStoreError("CollectionState diff snapshot is unavailable")
            _require_compatible(before, after)
            with self._engine.connect() as connection:
                entries = self._iter_changes(connection, before, after)
                counts: Counter[CollectionStateDiffCategory] = Counter()
                total_changed_items = 0
                page: list[CollectionStateDiffEntry] = []
                cursor = None if request.after_file_id is None else str(request.after_file_id)
                for entry in entries:
                    total_changed_items += 1
                    counts.update(entry.categories)
                    if cursor is not None and str(entry.file_id) <= cursor:
                        continue
                    if len(page) <= request.limit:
                        page.append(entry)
                truncated = len(page) > request.limit
                if truncated:
                    page = page[: request.limit]
                next_after = page[-1].file_id if truncated and page else None
                return CollectionStateDiffResult(
                    before_snapshot_id=before.id,
                    after_snapshot_id=after.id,
                    scan_root_id=before.scan_root_id,
                    category_counts=tuple(
                        (category, counts[category])
                        for category in COLLECTION_STATE_DIFF_CATEGORY_ORDER
                    ),
                    total_changed_items=total_changed_items,
                    entries=tuple(page),
                    truncated=truncated,
                    next_after_file_id=next_after,
                )
        except CollectionStateDiffStoreError:
            raise
        except (CollectionStateStoreError, IntegrityError, ValueError) as error:
            raise CollectionStateDiffStoreError("CollectionState diff read failed") from error

    def _iter_changes(
        self,
        connection: Connection,
        before: CollectionStateSnapshot,
        after: CollectionStateSnapshot,
    ) -> Iterator[CollectionStateDiffEntry]:
        before_items = self._iter_snapshot_items(connection, before)
        after_items = self._iter_snapshot_items(connection, after)
        left = next(before_items, None)
        right = next(after_items, None)
        while left is not None or right is not None:
            if right is None or (left is not None and str(left.file_id) < str(right.file_id)):
                assert left is not None
                yield CollectionStateDiffEntry(
                    file_id=left.file_id,
                    categories=(CollectionStateDiffCategory.DISAPPEARED,),
                    before_observation_id=left.observation_id,
                    after_observation_id=None,
                )
                left = next(before_items, None)
                continue
            if left is None or str(right.file_id) < str(left.file_id):
                yield CollectionStateDiffEntry(
                    file_id=right.file_id,
                    categories=(CollectionStateDiffCategory.ADDED,),
                    before_observation_id=None,
                    after_observation_id=right.observation_id,
                )
                right = next(after_items, None)
                continue
            categories = collection_state_item_diff_categories(left, right)
            if categories:
                yield CollectionStateDiffEntry(
                    file_id=left.file_id,
                    categories=categories,
                    before_observation_id=left.observation_id,
                    after_observation_id=right.observation_id,
                )
            left = next(before_items, None)
            right = next(after_items, None)

    def _iter_snapshot_items(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
    ) -> Iterator[CollectionStateItem]:
        after_ordinal = -1
        count = 0
        while True:
            rows = (
                connection.execute(
                    select(collection_state_items)
                    .where(
                        collection_state_items.c.snapshot_id == str(snapshot.id),
                        collection_state_items.c.ordinal > after_ordinal,
                    )
                    .order_by(collection_state_items.c.ordinal)
                    .limit(self._batch_size)
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            for row in rows:
                item = _item_from_row(row)
                if item.ordinal != count:
                    raise CollectionStateDiffStoreError(
                        "CollectionState diff item rows are incomplete"
                    )
                yield item
                count += 1
            after_ordinal = int(rows[-1]["ordinal"])
        if count != snapshot.item_count:
            raise CollectionStateDiffStoreError("CollectionState diff item count is incomplete")


def _require_compatible(
    before: CollectionStateSnapshot,
    after: CollectionStateSnapshot,
) -> None:
    if before.scan_root_id != after.scan_root_id:
        raise CollectionStateDiffStoreError("CollectionState snapshots use different ScanRoots")
    if before.profile != after.profile or before.serializer != after.serializer:
        raise CollectionStateDiffStoreError("CollectionState snapshot profiles are incompatible")
