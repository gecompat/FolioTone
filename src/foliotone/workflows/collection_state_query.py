"""Path-free diff and bounded local metadata-query application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final

from sqlalchemy.engine import Engine

from foliotone.collection_state import (
    COLLECTION_QUERY_PROFILE,
    CollectionQuerySpec,
    CollectionStateDiffRequest,
    CollectionStateDiffResult,
)
from foliotone.core.ids import EntityId
from foliotone.persistence.collection_query import (
    CollectionQueryHit,
    CollectionQueryPage,
    CollectionQueryPrivateValue,
    CollectionQueryStoreError,
    SQLiteCollectionQueryStore,
)
from foliotone.persistence.collection_state_diff import (
    CollectionStateDiffStoreError,
    SQLiteCollectionStateDiffReader,
)

COLLECTION_STATE_DIFF_REPORT_PROFILE: Final = "collection-state-diff-report/v1"
COLLECTION_QUERY_REPORT_PROFILE: Final = "collection-query-report/v1"


class CollectionStateDiffWorkflowError(RuntimeError):
    """A path-free state diff cannot be rendered safely."""


class CollectionQueryWorkflowError(RuntimeError):
    """A bounded local metadata query cannot be executed safely."""


@dataclass(frozen=True, slots=True)
class CollectionStateDiffReport:
    result: CollectionStateDiffResult
    profile: str = COLLECTION_STATE_DIFF_REPORT_PROFILE

    def __post_init__(self) -> None:
        if not isinstance(self.result, CollectionStateDiffResult):
            raise ValueError("CollectionState diff report result is invalid")
        if self.profile != COLLECTION_STATE_DIFF_REPORT_PROFILE:
            raise ValueError("CollectionState diff report profile is invalid")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "collection-state-diff",
            "ok": True,
            "profile": self.profile,
            "diff_profile": self.result.profile,
            "before_snapshot_id": str(self.result.before_snapshot_id),
            "after_snapshot_id": str(self.result.after_snapshot_id),
            "scan_root_id": str(self.result.scan_root_id),
            "coverage": "COMPLETE",
            "counts": {category.value: count for category, count in self.result.category_counts},
            "total_changed_items": self.result.total_changed_items,
            "result_count": len(self.result.entries),
            "entries": [
                {
                    "file_id": str(entry.file_id),
                    "categories": [category.value for category in entry.categories],
                    "before_observation_id": (
                        None
                        if entry.before_observation_id is None
                        else str(entry.before_observation_id)
                    ),
                    "after_observation_id": (
                        None
                        if entry.after_observation_id is None
                        else str(entry.after_observation_id)
                    ),
                }
                for entry in self.result.entries
            ],
            "truncated": self.result.truncated,
            "next_after_file_id": (
                None
                if self.result.next_after_file_id is None
                else str(self.result.next_after_file_id)
            ),
        }


@dataclass(frozen=True, slots=True)
class CollectionQueryReport:
    snapshot_id: EntityId
    page: CollectionQueryPage
    profile: str = COLLECTION_QUERY_REPORT_PROFILE

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, EntityId) or not isinstance(
            self.page, CollectionQueryPage
        ):
            raise ValueError("Collection query report input is invalid")
        if self.profile != COLLECTION_QUERY_REPORT_PROFILE:
            raise ValueError("Collection query report profile is invalid")
        if self.snapshot_id != self.page.index.snapshot_id:
            raise ValueError("Collection query report snapshot is inconsistent")

    def payload(self) -> dict[str, object]:
        hits: list[dict[str, object]] = []
        for hit in self.page.hits:
            hits.append(
                {
                    "file_id": str(hit.file_id),
                    "observation_id": str(hit.observation_id),
                    "format": hit.format_name,
                    "statuses": {
                        component.value: state for component, state in hit.component_states
                    },
                }
            )
        return {
            "schema_version": 1,
            "command": "collection-search",
            "ok": True,
            "profile": self.profile,
            "query_profile": COLLECTION_QUERY_PROFILE,
            "index_profile": self.page.index.profile,
            "snapshot_id": str(self.snapshot_id),
            "query_fields": [field.value for field in self.page.query_fields],
            "coverage": self.page.index.coverage_state.value,
            "index_truncation": self.page.index.truncation_state.value,
            "indexed_counts": {
                "documents": self.page.index.document_count,
                "values": self.page.index.value_count,
                "metadata_values": self.page.index.metadata_value_count,
                "finding_values": self.page.index.finding_value_count,
                "truncated_values": self.page.index.truncated_value_count,
            },
            "result_count": len(hits),
            "hits": hits,
            "private_details": False,
            "truncated": self.page.truncated,
            "next_after_file_id": (
                None if self.page.next_after_file_id is None else str(self.page.next_after_file_id)
            ),
        }

    @staticmethod
    def private_values(hit: CollectionQueryHit) -> tuple[CollectionQueryPrivateValue, ...]:
        """Return path-filtered values only for the interactive text adapter."""

        if not isinstance(hit, CollectionQueryHit):
            raise ValueError("Collection query hit is invalid")
        return tuple(value for value in hit.private_values if not _looks_absolute(value.value))


class CollectionStateDiffService:
    def __init__(self, engine: Engine, *, batch_size: int = 500) -> None:
        self._reader = SQLiteCollectionStateDiffReader(engine, batch_size=batch_size)

    def diff(self, request: CollectionStateDiffRequest) -> CollectionStateDiffReport:
        try:
            return CollectionStateDiffReport(self._reader.read(request))
        except (CollectionStateDiffStoreError, ValueError) as error:
            raise CollectionStateDiffWorkflowError(str(error)) from error


class CollectionQueryService:
    def __init__(self, engine: Engine, *, batch_size: int = 250) -> None:
        self._store = SQLiteCollectionQueryStore(engine, batch_size=batch_size)

    def search(
        self,
        snapshot_id: EntityId,
        spec: CollectionQuerySpec,
        *,
        private_details: bool = False,
    ) -> CollectionQueryReport:
        try:
            page = self._store.search(
                snapshot_id,
                spec,
                private_details=private_details,
            )
        except (CollectionQueryStoreError, ValueError) as error:
            raise CollectionQueryWorkflowError(str(error)) from error
        return CollectionQueryReport(snapshot_id, page)


def _looks_absolute(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
