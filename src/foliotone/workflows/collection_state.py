"""Application services and path-free reports for book-only CollectionState v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Engine

from foliotone.collection_state import (
    CollectionStateComponentSummary,
    CollectionStateSnapshot,
)
from foliotone.core import EntityId
from foliotone.persistence.collection_state import (
    CollectionStateBuildResult,
    CollectionStateStoreError,
    SQLiteCollectionStateStore,
)

COLLECTION_STATE_REPORT_PROFILE = "collection-state-report/v1"


class CollectionStateWorkflowError(RuntimeError):
    """A CollectionState snapshot cannot be built or reported safely."""


@dataclass(frozen=True, slots=True)
class CollectionStateReport:
    snapshot: CollectionStateSnapshot
    created: bool | None = None
    profile: str = COLLECTION_STATE_REPORT_PROFILE

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, CollectionStateSnapshot):
            raise ValueError("snapshot must be a CollectionStateSnapshot")
        if self.created is not None and not isinstance(self.created, bool):
            raise ValueError("created must be boolean when present")
        if self.profile != COLLECTION_STATE_REPORT_PROFILE:
            raise ValueError("CollectionState report profile is invalid")

    def payload(self, *, command: str) -> dict[str, object]:
        if command not in {"collection-state-build", "collection-state-report"}:
            raise ValueError("CollectionState report command is invalid")
        payload: dict[str, object] = {
            "schema_version": 1,
            "command": command,
            "ok": True,
            "profile": self.profile,
            "snapshot_profile": self.snapshot.profile,
            "snapshot_id": str(self.snapshot.id),
            "scan_root_id": str(self.snapshot.scan_root_id),
            "source_scan_run_id": str(self.snapshot.source_scan_run_id),
            "created_at": self.snapshot.created_at.isoformat(),
            "content_digest": self.snapshot.content_digest,
            "counts": {count.key: count.value for count in self.snapshot.counts},
            "components": [_component_payload(component) for component in self.snapshot.components],
            "truncated": any(
                component.truncation_state.value != "NONE" for component in self.snapshot.components
            ),
        }
        if command == "collection-state-build":
            if self.created is None:
                raise ValueError("build report requires created state")
            payload["created"] = self.created
        return payload


def _component_payload(component: CollectionStateComponentSummary) -> dict[str, object]:
    return {
        "component": component.component.value,
        "profile_versions": list(component.profile_versions),
        "evidence_count": component.evidence_count,
        "current_item_count": component.current_item_count,
        "stale_item_count": component.stale_item_count,
        "unscoped_item_count": component.unscoped_item_count,
        "missing_item_count": component.missing_item_count,
        "conflict_item_count": component.conflict_item_count,
        "coverage_state": component.coverage_state.value,
        "freshness_state": component.freshness_state.value,
        "conflict_state": component.conflict_state.value,
        "truncation_state": component.truncation_state.value,
    }


class CollectionStateBuildService:
    """Build a deterministic snapshot without opening Source Media or invoking tools."""

    def __init__(self, engine: Engine, *, batch_size: int = 500) -> None:
        self._store = SQLiteCollectionStateStore(engine, batch_size=batch_size)

    def build(self, source_scan_run_id: EntityId, created_at: datetime) -> CollectionStateReport:
        try:
            result: CollectionStateBuildResult = self._store.build(source_scan_run_id, created_at)
        except (CollectionStateStoreError, ValueError) as error:
            raise CollectionStateWorkflowError(str(error)) from error
        return CollectionStateReport(result.snapshot, result.created)


class SQLiteCollectionStateReportReader:
    """Read and verify one persisted snapshot through an existing SQLite engine."""

    def __init__(self, engine: Engine, *, batch_size: int = 500) -> None:
        self._store = SQLiteCollectionStateStore(engine, batch_size=batch_size)

    def read(self, snapshot_id: EntityId) -> CollectionStateReport:
        try:
            snapshot = self._store.get(snapshot_id)
        except (CollectionStateStoreError, ValueError) as error:
            raise CollectionStateWorkflowError(str(error)) from error
        if snapshot is None:
            raise CollectionStateWorkflowError("CollectionState snapshot is unavailable")
        return CollectionStateReport(snapshot)
