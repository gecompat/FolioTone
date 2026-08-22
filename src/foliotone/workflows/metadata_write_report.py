"""Read-only path- and value-free status for one metadata-write run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from foliotone.core import EntityId
from foliotone.metadata_write.authorization import (
    METADATA_WRITE_AUTHORIZATION_PROFILE,
    METADATA_WRITE_RUN_PROFILE,
    MetadataWriteRunStatus,
)
from foliotone.metadata_write.contracts import EPUB_TITLE_WRITE_PROFILE
from foliotone.persistence.metadata_write import (
    MetadataWriteStatusSnapshot,
    MetadataWriteStoreError,
    SQLiteMetadataWriteStore,
)

METADATA_WRITE_STATUS_REPORT_PROFILE = "metadata-write-status-report/v1"


class MetadataWriteStatusReportError(RuntimeError):
    """Persisted status cannot be projected through the privacy boundary."""

    def __init__(self) -> None:
        super().__init__("METADATA_WRITE_STATUS_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusEvent:
    sequence_no: int
    status: MetadataWriteRunStatus
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusReport:
    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    status: MetadataWriteRunStatus
    events: tuple[MetadataWriteStatusEvent, ...]
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE
    run_profile: str = METADATA_WRITE_RUN_PROFILE
    authorization_profile: str = METADATA_WRITE_AUTHORIZATION_PROFILE
    profile: str = METADATA_WRITE_STATUS_REPORT_PROFILE

    def __post_init__(self) -> None:
        if (
            self.profile != METADATA_WRITE_STATUS_REPORT_PROFILE
            or self.writer_profile != EPUB_TITLE_WRITE_PROFILE
            or self.run_profile != METADATA_WRITE_RUN_PROFILE
            or self.authorization_profile != METADATA_WRITE_AUTHORIZATION_PROFILE
            or not all(
                isinstance(value, EntityId)
                for value in (
                    self.run_id,
                    self.authorization_id,
                    self.plan_id,
                    self.scan_root_id,
                )
            )
            or not self.events
            or self.status is not self.events[-1].status
            or tuple(event.sequence_no for event in self.events)
            != tuple(range(1, len(self.events) + 1))
        ):
            raise ValueError("metadata write status report is invalid")

    @classmethod
    def from_snapshot(
        cls,
        snapshot: MetadataWriteStatusSnapshot,
    ) -> MetadataWriteStatusReport:
        if not isinstance(snapshot, MetadataWriteStatusSnapshot):
            raise TypeError("snapshot must be a metadata write status snapshot")
        events = tuple(
            MetadataWriteStatusEvent(event.sequence_no, event.status, event.occurred_at)
            for event in snapshot.events
        )
        return cls(
            run_id=snapshot.run_id,
            authorization_id=snapshot.authorization_id,
            plan_id=snapshot.plan_id,
            scan_root_id=snapshot.scan_root_id,
            created_at=snapshot.created_at,
            authorized_at=snapshot.authorized_at,
            expires_at=snapshot.expires_at,
            status=events[-1].status,
            events=events,
            writer_profile=snapshot.writer_profile,
            run_profile=snapshot.run_profile,
            authorization_profile=snapshot.authorization_profile,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "metadata-write-status",
            "ok": True,
            "profile": self.profile,
            "writer_profile": self.writer_profile,
            "run_profile": self.run_profile,
            "authorization_profile": self.authorization_profile,
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


class SQLiteMetadataWriteStatusReportReader:
    """Project one persisted run without source media, tools, or writes."""

    def __init__(self, store: SQLiteMetadataWriteStore) -> None:
        if type(store) is not SQLiteMetadataWriteStore:
            raise ValueError("metadata write status requires the exact store")
        self._store = store

    def read(self, run_id: EntityId) -> MetadataWriteStatusReport:
        try:
            snapshot = self._store.read_status_snapshot(run_id)
            if snapshot is None:
                raise MetadataWriteStatusReportError()
            return MetadataWriteStatusReport.from_snapshot(snapshot)
        except MetadataWriteStatusReportError:
            raise
        except (MetadataWriteStoreError, SQLAlchemyError, TypeError, ValueError):
            raise MetadataWriteStatusReportError() from None


__all__ = [
    "METADATA_WRITE_STATUS_REPORT_PROFILE",
    "MetadataWriteStatusEvent",
    "MetadataWriteStatusReport",
    "MetadataWriteStatusReportError",
    "SQLiteMetadataWriteStatusReportReader",
]
