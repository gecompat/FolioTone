"""Read-only locator-, hash-, attribute-, capability-, and fence-free rename status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core import EntityId
from foliotone.ebook_rename import (
    EBOOK_RENAME_AUTHORIZATION_PROFILE,
    EBOOK_RENAME_PROCESSOR_PROFILE,
    EBOOK_RENAME_RUN_PROFILE,
    EbookRenameReconciliationOutcome,
    EbookRenameRunStatus,
)
from foliotone.persistence.ebook_rename import (
    EbookRenameStatusReconciliationSnapshot,
    EbookRenameStatusSnapshot,
    EbookRenameStoreError,
    SQLiteEbookRenameStore,
)

EBOOK_RENAME_STATUS_REPORT_PROFILE = "ebook-file-rename-status-report/v1"


class EbookRenameStatusReportError(RuntimeError):
    """The persisted run cannot be projected through the privacy boundary."""

    def __init__(self) -> None:
        super().__init__("EBOOK_RENAME_STATUS_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class EbookRenameStatusEvent:
    sequence_no: int
    status: EbookRenameRunStatus
    occurred_at: datetime
    finding_code: str | None


@dataclass(frozen=True, slots=True)
class EbookRenameStatusReconciliation:
    outcome: EbookRenameReconciliationOutcome
    scan_run_id: EntityId
    source_file_id: EntityId
    source_observation_id: EntityId | None
    target_file_id: EntityId | None
    target_observation_id: EntityId | None
    collection_state_snapshot_id: EntityId
    reconciled_at: datetime

    @classmethod
    def from_snapshot(
        cls,
        snapshot: EbookRenameStatusReconciliationSnapshot,
    ) -> EbookRenameStatusReconciliation:
        return cls(
            outcome=snapshot.outcome,
            scan_run_id=snapshot.scan_run_id,
            source_file_id=snapshot.source_file_id,
            source_observation_id=snapshot.source_observation_id,
            target_file_id=snapshot.target_file_id,
            target_observation_id=snapshot.target_observation_id,
            collection_state_snapshot_id=snapshot.collection_state_snapshot_id,
            reconciled_at=snapshot.reconciled_at,
        )


@dataclass(frozen=True, slots=True)
class EbookRenameStatusReport:
    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    ebook_rename_capability_id: EntityId
    probe_id: EntityId
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    status: EbookRenameRunStatus
    events: tuple[EbookRenameStatusEvent, ...]
    reconciliation: EbookRenameStatusReconciliation | None = None
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE
    run_profile: str = EBOOK_RENAME_RUN_PROFILE
    authorization_profile: str = EBOOK_RENAME_AUTHORIZATION_PROFILE
    profile: str = EBOOK_RENAME_STATUS_REPORT_PROFILE

    def __post_init__(self) -> None:
        if (
            self.profile != EBOOK_RENAME_STATUS_REPORT_PROFILE
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or self.run_profile != EBOOK_RENAME_RUN_PROFILE
            or self.authorization_profile != EBOOK_RENAME_AUTHORIZATION_PROFILE
            or not all(
                isinstance(value, EntityId)
                for value in (
                    self.run_id,
                    self.authorization_id,
                    self.plan_id,
                    self.scan_root_id,
                    self.ebook_rename_capability_id,
                    self.probe_id,
                )
            )
            or not self.events
            or self.status is not self.events[-1].status
            or tuple(event.sequence_no for event in self.events)
            != tuple(range(1, len(self.events) + 1))
            or (
                self.reconciliation is not None
                and self.status.value != self.reconciliation.outcome.value
            )
            or (
                self.status in {
                    EbookRenameRunStatus.VERIFIED,
                    EbookRenameRunStatus.RECOVERED,
                }
                and self.reconciliation is None
            )
        ):
            raise ValueError("e-book rename status report is invalid")

    @classmethod
    def from_snapshot(
        cls,
        snapshot: EbookRenameStatusSnapshot,
    ) -> EbookRenameStatusReport:
        if not isinstance(snapshot, EbookRenameStatusSnapshot):
            raise TypeError("snapshot must be an e-book rename status snapshot")
        events = tuple(
            EbookRenameStatusEvent(
                value.sequence_no,
                value.status,
                value.occurred_at,
                value.finding_code,
            )
            for value in snapshot.events
        )
        return cls(
            run_id=snapshot.run_id,
            authorization_id=snapshot.authorization_id,
            plan_id=snapshot.plan_id,
            scan_root_id=snapshot.scan_root_id,
            ebook_rename_capability_id=snapshot.ebook_rename_capability_id,
            probe_id=snapshot.probe_id,
            created_at=snapshot.created_at,
            authorized_at=snapshot.authorized_at,
            expires_at=snapshot.expires_at,
            status=events[-1].status,
            events=events,
            reconciliation=(
                None
                if snapshot.reconciliation is None
                else EbookRenameStatusReconciliation.from_snapshot(
                    snapshot.reconciliation
                )
            ),
            backend_profile=snapshot.backend_profile,
            run_profile=snapshot.run_profile,
            authorization_profile=snapshot.authorization_profile,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "ebook-rename-status",
            "ok": True,
            "profile": self.profile,
            "backend_profile": self.backend_profile,
            "run_profile": self.run_profile,
            "authorization_profile": self.authorization_profile,
            "run_id": str(self.run_id),
            "authorization_id": str(self.authorization_id),
            "plan_id": str(self.plan_id),
            "scan_root_id": str(self.scan_root_id),
            "ebook_rename_capability_id": str(
                self.ebook_rename_capability_id
            ),
            "probe_id": str(self.probe_id),
            "created_at": self.created_at.isoformat(),
            "authorized_at": self.authorized_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status.value,
            "events": [
                {
                    "sequence_no": event.sequence_no,
                    "status": event.status.value,
                    "occurred_at": event.occurred_at.isoformat(),
                    "finding_code": event.finding_code,
                }
                for event in self.events
            ],
            "reconciliation": (
                None
                if self.reconciliation is None
                else {
                    "outcome": self.reconciliation.outcome.value,
                    "scan_run_id": str(self.reconciliation.scan_run_id),
                    "source_file_id": str(self.reconciliation.source_file_id),
                    "source_observation_id": (
                        None
                        if self.reconciliation.source_observation_id is None
                        else str(self.reconciliation.source_observation_id)
                    ),
                    "target_file_id": (
                        None
                        if self.reconciliation.target_file_id is None
                        else str(self.reconciliation.target_file_id)
                    ),
                    "target_observation_id": (
                        None
                        if self.reconciliation.target_observation_id is None
                        else str(self.reconciliation.target_observation_id)
                    ),
                    "collection_state_snapshot_id": str(
                        self.reconciliation.collection_state_snapshot_id
                    ),
                    "reconciled_at": self.reconciliation.reconciled_at.isoformat(),
                }
            ),
        }


class SQLiteEbookRenameStatusReportReader:
    """Project one run without source media, tools, migrations, or writes."""

    def __init__(self, store: SQLiteEbookRenameStore) -> None:
        if type(store) is not SQLiteEbookRenameStore:
            raise ValueError("e-book rename status requires the exact store")
        self._store = store

    def read(self, run_id: EntityId) -> EbookRenameStatusReport:
        try:
            snapshot = self._store.read_status_snapshot(run_id)
            if snapshot is None:
                raise EbookRenameStatusReportError()
            return EbookRenameStatusReport.from_snapshot(snapshot)
        except EbookRenameStatusReportError:
            raise
        except (EbookRenameStoreError, TypeError, ValueError):
            raise EbookRenameStatusReportError() from None


__all__ = [
    "EBOOK_RENAME_STATUS_REPORT_PROFILE",
    "EbookRenameStatusEvent",
    "EbookRenameStatusReconciliation",
    "EbookRenameStatusReport",
    "EbookRenameStatusReportError",
    "SQLiteEbookRenameStatusReportReader",
]
