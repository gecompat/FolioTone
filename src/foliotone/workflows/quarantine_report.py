"""Read-only, path-free status projection for one persisted W10 quarantine run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core import EntityId
from foliotone.persistence.quarantine import (
    QuarantineStatusSnapshot,
    QuarantineStoreError,
    SQLiteQuarantineStore,
)
from foliotone.quarantine import QuarantineRunStatus

QUARANTINE_STATUS_REPORT_PROFILE = "quarantine-status-report/v1"


class QuarantineStatusReportError(RuntimeError):
    """The persisted quarantine state cannot be exposed safely."""


@dataclass(frozen=True, slots=True)
class QuarantineStatusEvent:
    sequence_no: int
    status: QuarantineRunStatus
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantineStatusReport:
    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    status: QuarantineRunStatus
    events: tuple[QuarantineStatusEvent, ...]
    profile: str = QUARANTINE_STATUS_REPORT_PROFILE

    def __post_init__(self) -> None:
        if self.profile != QUARANTINE_STATUS_REPORT_PROFILE:
            raise ValueError("quarantine status profile is invalid")
        if not all(
            isinstance(value, EntityId)
            for value in (self.run_id, self.authorization_id, self.plan_id, self.scan_root_id)
        ):
            raise ValueError("quarantine status IDs are invalid")
        if not self.events or self.status is not self.events[-1].status:
            raise ValueError("quarantine status events are invalid")
        if tuple(event.sequence_no for event in self.events) != tuple(
            range(1, len(self.events) + 1)
        ):
            raise ValueError("quarantine status events are not gapless")

    @classmethod
    def from_snapshot(cls, snapshot: QuarantineStatusSnapshot) -> QuarantineStatusReport:
        if not isinstance(snapshot, QuarantineStatusSnapshot):
            raise TypeError("snapshot must be a quarantine status snapshot")
        events = tuple(
            QuarantineStatusEvent(event.sequence_no, event.status, event.occurred_at)
            for event in snapshot.events
        )
        return cls(
            snapshot.run_id,
            snapshot.authorization_id,
            snapshot.plan_id,
            snapshot.scan_root_id,
            snapshot.created_at,
            snapshot.authorized_at,
            snapshot.expires_at,
            events[-1].status,
            events,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "quarantine-status",
            "ok": True,
            "profile": self.profile,
            "run_id": str(self.run_id),
            "authorization_id": str(self.authorization_id),
            "plan_id": str(self.plan_id),
            "scan_root_id": str(self.scan_root_id),
            "created_at": self.created_at.isoformat(),
            "authorized_at": self.authorized_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status.value,
            "events": [
                {
                    "sequence_no": event.sequence_no,
                    "status": event.status.value,
                    "occurred_at": event.occurred_at.isoformat(),
                }
                for event in self.events
            ],
        }


class SQLiteQuarantineStatusReportReader:
    """Project one persisted run without opening source media or writing SQLite."""

    def __init__(self, store: SQLiteQuarantineStore) -> None:
        if type(store) is not SQLiteQuarantineStore:
            raise ValueError("quarantine status requires the exact store")
        self._store = store

    def read(self, run_id: EntityId) -> QuarantineStatusReport:
        try:
            snapshot = self._store.read_status_snapshot(run_id)
        except (QuarantineStoreError, ValueError):
            raise QuarantineStatusReportError("quarantine status is unavailable") from None
        if snapshot is None:
            raise QuarantineStatusReportError("quarantine status is unavailable")
        try:
            return QuarantineStatusReport.from_snapshot(snapshot)
        except (TypeError, ValueError):
            raise QuarantineStatusReportError("quarantine status is unavailable") from None
