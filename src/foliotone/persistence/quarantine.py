"""Bounded insert-only persistence for the non-executing S-W10-02 slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, insert, select

from foliotone.core import EntityId
from foliotone.persistence._mapping import datetime_from_db, datetime_to_db
from foliotone.persistence.quarantine_schema import (
    quarantine_authorizations,
    quarantine_execution_events,
    quarantine_execution_runs,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import QuarantineAuthorizationSnapshot, QuarantineRunStatus


class QuarantineStoreError(RuntimeError):
    """An immutable quarantine persistence invariant was violated."""


@dataclass(frozen=True, slots=True)
class QuarantineExecutionRun:
    id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    keeper_file_id: EntityId
    candidate_file_id: EntityId
    target_token: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantineExecutionEvent:
    run_id: EntityId
    sequence_no: int
    status: QuarantineRunStatus
    occurred_at: datetime
    fence_epoch: int | None = None
    finding_code: str | None = None
    confirmation_digest: str | None = None


_NEXT = {
    QuarantineRunStatus.PREPARED: frozenset(QuarantineRunStatus) - {QuarantineRunStatus.PREPARED},
    QuarantineRunStatus.MOVED: frozenset(
        {
            QuarantineRunStatus.VERIFIED,
            QuarantineRunStatus.STALE,
            QuarantineRunStatus.VALIDATION_FAILED,
            QuarantineRunStatus.FENCED_OUT,
            QuarantineRunStatus.MANUAL_REVIEW,
        }
    ),
    QuarantineRunStatus.VERIFIED: frozenset(
        {
            QuarantineRunStatus.COMPLETED,
            QuarantineRunStatus.FENCED_OUT,
            QuarantineRunStatus.MANUAL_REVIEW,
        }
    ),
}


class SQLiteQuarantineStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_authorization(
        self, value: QuarantineAuthorizationSnapshot
    ) -> QuarantineAuthorizationSnapshot:
        row = _authorization_row(value)
        with self._engine.begin() as connection:
            inserted = connection.execute(
                insert(quarantine_authorizations).values(**row).prefix_with("OR IGNORE")
            )
            if inserted.rowcount == 0:
                existing = (
                    connection.execute(
                        select(quarantine_authorizations).where(
                            quarantine_authorizations.c.id == str(value.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None or dict(existing) != row:
                    raise QuarantineStoreError("authorization retry payload differs")
        return value

    def create_prepared_run(
        self,
        value: QuarantineExecutionRun,
        lease: OwnedScanRootWriteLease,
        occurred_at: datetime,
    ) -> QuarantineExecutionRun:
        if (
            lease.owner_kind is not ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN
            or lease.owner_run_id != value.id
            or lease.scan_root_id != value.scan_root_id
        ):
            raise QuarantineStoreError("quarantine run requires its owned root lease")
        with self._engine.begin() as connection:
            SQLiteScanRootWriteLeaseStore(self._engine).fence(connection, lease, occurred_at)
            connection.execute(insert(quarantine_execution_runs).values(**_run_row(value)))
            connection.execute(
                insert(quarantine_execution_events).values(
                    run_id=str(value.id),
                    sequence_no=1,
                    status=QuarantineRunStatus.PREPARED.value,
                    occurred_at=datetime_to_db(occurred_at),
                    fence_epoch=lease.fence_epoch,
                    finding_code=None,
                    confirmation_digest=None,
                )
            )
        return value

    def append_event(
        self,
        value: QuarantineExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> QuarantineExecutionEvent:
        with self._engine.begin() as connection:
            if (
                lease.owner_kind is not ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN
                or lease.owner_run_id != value.run_id
            ):
                raise QuarantineStoreError("event requires the owning quarantine lease")
            SQLiteScanRootWriteLeaseStore(self._engine).fence(connection, lease, value.occurred_at)
            if value.fence_epoch != lease.fence_epoch:
                raise QuarantineStoreError("event fence does not match lease")
            last = (
                connection.execute(
                    select(quarantine_execution_events)
                    .where(quarantine_execution_events.c.run_id == str(value.run_id))
                    .order_by(quarantine_execution_events.c.sequence_no.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if last is None:
                raise QuarantineStoreError("prepared event is required")
            previous = QuarantineRunStatus(str(last["status"]))
            if value.sequence_no != int(last["sequence_no"]) + 1 or value.status not in _NEXT.get(
                previous, frozenset()
            ):
                raise QuarantineStoreError("quarantine event transition is invalid")
            connection.execute(
                insert(quarantine_execution_events).values(
                    run_id=str(value.run_id),
                    sequence_no=value.sequence_no,
                    status=value.status.value,
                    occurred_at=datetime_to_db(value.occurred_at),
                    fence_epoch=value.fence_epoch,
                    finding_code=value.finding_code,
                    confirmation_digest=value.confirmation_digest,
                )
            )
        return value

    def events_for_run(self, run_id: EntityId) -> tuple[QuarantineExecutionEvent, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(quarantine_execution_events)
                .where(quarantine_execution_events.c.run_id == str(run_id))
                .order_by(quarantine_execution_events.c.sequence_no)
            ).mappings()
            return tuple(_event_from_row(run_id, dict(row)) for row in rows)


def _authorization_row(value: QuarantineAuthorizationSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "plan_id": str(value.plan_id),
        "plan_content_hash": value.plan_content_hash,
        "scan_root_id": str(value.scan_root_id),
        "keeper_file_id": str(value.keeper_file_id),
        "candidate_file_id": str(value.candidate_file_id),
        "keeper_observation_id": str(value.keeper_observation_id),
        "candidate_observation_id": str(value.candidate_observation_id),
        "keeper_full_sha256": value.keeper_full_sha256,
        "candidate_full_sha256": value.candidate_full_sha256,
        "quarantine_capability_id": str(value.quarantine_capability_id),
        "review_fingerprint": value.review_fingerprint,
        "authorized_at": datetime_to_db(value.authorized_at),
        "expires_at": datetime_to_db(value.expires_at),
        "content_hash": value.content_hash,
    }


def _run_row(value: QuarantineExecutionRun) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": "quarantine-execution/v1",
        "authorization_id": str(value.authorization_id),
        "plan_id": str(value.plan_id),
        "scan_root_id": str(value.scan_root_id),
        "keeper_file_id": str(value.keeper_file_id),
        "candidate_file_id": str(value.candidate_file_id),
        "target_token": value.target_token,
        "created_at": datetime_to_db(value.created_at),
    }


def _event_from_row(run_id: EntityId, values: dict[str, Any]) -> QuarantineExecutionEvent:
    occurred_at = datetime_from_db(str(values["occurred_at"]))
    if occurred_at is None:
        raise QuarantineStoreError("quarantine event timestamp is missing")
    return QuarantineExecutionEvent(
        run_id,
        int(values["sequence_no"]),
        QuarantineRunStatus(str(values["status"])),
        occurred_at,
        None if values["fence_epoch"] is None else int(values["fence_epoch"]),
        values["finding_code"],
        values["confirmation_digest"],
    )
