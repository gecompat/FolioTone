"""Bounded insert-only persistence for ADR-0056 quarantine operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from foliotone.consolidation.contracts import (
    ConsolidationFileEndpoint,
    ConsolidationFileRole,
    ConsolidationPlan,
)
from foliotone.core import EntityId, MediaType, PresenceState
from foliotone.core._validation import require_relative_path
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_from_db, datetime_to_db
from foliotone.persistence.consolidation import (
    ConsolidationStoreError,
    SQLiteConsolidationStore,
)
from foliotone.persistence.quarantine_schema import (
    quarantine_authorizations,
    quarantine_execution_events,
    quarantine_execution_runs,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import (
    QuarantineAuthorizationSnapshot,
    QuarantineEligibilityStatus,
    QuarantineRunStatus,
    build_quarantine_authorization,
)


class QuarantineStoreError(RuntimeError):
    """An immutable quarantine persistence invariant was violated."""


class QuarantineAuthorizationConsumedError(QuarantineStoreError):
    """The one-use authorization already owns an execution run."""


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
class QuarantineAuthorizationSourceSnapshot:
    """Private current locator for one endpoint being authorized."""

    role: ConsolidationFileRole
    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    relative_path: str = field(repr=False)
    expected_full_sha256: str = field(repr=False)
    expected_size_bytes: int
    expected_modified_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.role, ConsolidationFileRole) or not all(
            isinstance(value, EntityId)
            for value in (self.scan_root_id, self.file_id, self.observation_id)
        ):
            raise QuarantineStoreError("quarantine authorization source is invalid")
        try:
            relative_path = require_relative_path(self.relative_path)
        except (TypeError, ValueError):
            raise QuarantineStoreError("quarantine authorization source is invalid") from None
        if (
            not isinstance(self.expected_full_sha256, str)
            or len(self.expected_full_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.expected_full_sha256)
            or isinstance(self.expected_size_bytes, bool)
            or not isinstance(self.expected_size_bytes, int)
            or self.expected_size_bytes < 0
            or not isinstance(self.expected_modified_at, datetime)
            or self.expected_modified_at.tzinfo is None
            or self.expected_modified_at.utcoffset() is None
        ):
            raise QuarantineStoreError("quarantine authorization source is invalid")
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(
            self,
            "expected_modified_at",
            self.expected_modified_at.astimezone(UTC),
        )


@dataclass(frozen=True, slots=True)
class QuarantineExecutionEvent:
    run_id: EntityId
    sequence_no: int
    status: QuarantineRunStatus
    occurred_at: datetime
    fence_epoch: int | None = None
    finding_code: str | None = None
    confirmation_digest: str | None = None


@dataclass(frozen=True, slots=True)
class QuarantineStatusSnapshot:
    """Bounded path-free material needed by the public W10 status reader."""

    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    events: tuple[QuarantineStatusEventSnapshot, ...]


@dataclass(frozen=True, slots=True)
class QuarantineStatusEventSnapshot:
    """Publicly reportable event fields only; private event material is not read."""

    sequence_no: int
    status: QuarantineRunStatus
    occurred_at: datetime


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
        self,
        value: QuarantineAuthorizationSnapshot,
        plan: ConsolidationPlan,
        *,
        persisted_at: datetime,
    ) -> QuarantineAuthorizationSnapshot:
        """Persist an authorization only while its exact plan is still current."""

        if (
            not isinstance(value, QuarantineAuthorizationSnapshot)
            or not isinstance(plan, ConsolidationPlan)
            or not isinstance(persisted_at, datetime)
            or persisted_at.tzinfo is None
            or persisted_at.utcoffset() is None
            or persisted_at < value.authorized_at
            or persisted_at >= value.expires_at
        ):
            raise QuarantineStoreError("quarantine authorization is invalid")
        if plan.keeper is None or plan.candidate is None:
            raise QuarantineStoreError("quarantine authorization plan binding differs")
        assessment = build_quarantine_authorization(
            plan=plan,
            current_keeper=plan.keeper,
            current_candidate=plan.candidate,
            current_dependencies=plan.dependencies,
            current_reviews=plan.required_reviews,
            quarantine_capability_id=value.quarantine_capability_id,
            authorized_at=value.authorized_at,
            expires_at=value.expires_at,
        )
        if (
            assessment.status is not QuarantineEligibilityStatus.ELIGIBLE
            or assessment.authorization != value
        ):
            raise QuarantineStoreError("quarantine authorization plan binding differs")
        row = _authorization_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteConsolidationStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
                existing = (
                    connection.execute(
                        select(quarantine_authorizations).where(
                            quarantine_authorizations.c.id == str(value.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != row:
                        raise QuarantineStoreError("authorization retry payload differs")
                    return value
                connection.execute(insert(quarantine_authorizations).values(**row))
        except QuarantineStoreError:
            raise
        except (ConsolidationStoreError, IntegrityError, ValueError) as error:
            raise QuarantineStoreError(
                "quarantine authorization could not be persisted"
            ) from error
        return value

    def get_authorization(
        self,
        authorization_id: EntityId,
    ) -> QuarantineAuthorizationSnapshot | None:
        """Load one immutable authorization without exposing private material."""

        try:
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        select(quarantine_authorizations).where(
                            quarantine_authorizations.c.id == str(authorization_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return None if row is None else _authorization_from_row(dict(row))
        except (TypeError, ValueError) as error:
            raise QuarantineStoreError(
                "quarantine authorization could not be read"
            ) from error

    def get_run_for_authorization(
        self,
        authorization_id: EntityId,
    ) -> QuarantineExecutionRun | None:
        """Return the sole run which consumes an authorization, if present."""

        try:
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        select(quarantine_execution_runs).where(
                            quarantine_execution_runs.c.authorization_id
                            == str(authorization_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return None if row is None else _run_from_row(dict(row))
        except (TypeError, ValueError) as error:
            raise QuarantineStoreError("quarantine execution run could not be read") from error

    def get_run(self, run_id: EntityId) -> QuarantineExecutionRun | None:
        """Load one immutable execution identity without reading event material."""

        try:
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        select(quarantine_execution_runs).where(
                            quarantine_execution_runs.c.id == str(run_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return None if row is None else _run_from_row(dict(row))
        except (TypeError, ValueError) as error:
            raise QuarantineStoreError("quarantine execution run could not be read") from error

    def takeover_expired_preparedless_lease(
        self,
        expired: OwnedScanRootWriteLease,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        """Atomically replace an expired quarantine lease that has no persisted run."""

        if (
            expired.owner_kind
            is not ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN
            or expired.owner_run_id == owner_run_id
        ):
            raise QuarantineStoreError("quarantine lease takeover is invalid")
        try:
            with _immediate_transaction(self._engine) as connection:
                persisted_run_id = connection.execute(
                    select(quarantine_execution_runs.c.id).where(
                        quarantine_execution_runs.c.id == str(expired.owner_run_id)
                    )
                ).scalar_one_or_none()
                if persisted_run_id is not None:
                    raise QuarantineStoreError(
                        "persisted quarantine run requires recovery"
                    )
                return SQLiteScanRootWriteLeaseStore(
                    self._engine
                ).takeover_expired_in_transaction(
                    connection,
                    expired,
                    owner_run_id,
                    lease_token=lease_token,
                    acquired_at=acquired_at,
                    lease_expires_at=lease_expires_at,
                )
        except (QuarantineStoreError, ScanRootWriteLeaseError):
            raise
        except (SQLAlchemyError, TypeError, ValueError) as error:
            raise QuarantineStoreError(
                "quarantine lease takeover could not be completed"
            ) from error

    def require_authorization_sources(
        self,
        plan: ConsolidationPlan,
    ) -> tuple[
        QuarantineAuthorizationSourceSnapshot,
        QuarantineAuthorizationSourceSnapshot,
    ]:
        """Return exact private locators after current-plan revalidation."""

        if plan.keeper is None or plan.candidate is None:
            raise QuarantineStoreError("quarantine authorization sources are unavailable")
        try:
            with self._engine.begin() as connection:
                SQLiteConsolidationStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
                keeper = self._authorization_source(connection, plan, plan.keeper)
                candidate = self._authorization_source(connection, plan, plan.candidate)
                if keeper.relative_path == candidate.relative_path:
                    raise QuarantineStoreError("quarantine authorization sources differ")
                return keeper, candidate
        except QuarantineStoreError:
            raise
        except (ConsolidationStoreError, ValueError) as error:
            raise QuarantineStoreError(
                "quarantine authorization sources are unavailable"
            ) from error

    @staticmethod
    def _authorization_source(
        connection: Any,
        plan: ConsolidationPlan,
        endpoint: ConsolidationFileEndpoint,
    ) -> QuarantineAuthorizationSourceSnapshot:
        row = (
            connection.execute(
                select(
                    schema.file_records.c.scan_root_id,
                    schema.file_records.c.relative_path.label("file_relative_path"),
                    schema.file_records.c.size_bytes.label("file_size_bytes"),
                    schema.file_records.c.modified_at.label("file_modified_at"),
                    schema.file_records.c.media_type,
                    schema.file_records.c.presence_state,
                    schema.file_observations.c.file_id.label("observation_file_id"),
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.relative_path.label(
                        "observation_relative_path"
                    ),
                    schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                    schema.file_observations.c.modified_at.label("observation_modified_at"),
                    schema.file_observations.c.observed_at,
                )
                .select_from(
                    schema.file_records.join(
                        schema.file_observations,
                        schema.file_observations.c.file_id == schema.file_records.c.id,
                    )
                )
                .where(
                    schema.file_records.c.id == str(endpoint.file_id),
                    schema.file_observations.c.id == str(endpoint.observation_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise QuarantineStoreError("quarantine authorization source is unavailable")
        file_modified_at = _required_datetime(row["file_modified_at"])
        observation_modified_at = _required_datetime(row["observation_modified_at"])
        observed_at = _required_datetime(row["observed_at"])
        relative_path = str(row["observation_relative_path"])
        if (
            str(row["scan_root_id"]) != str(plan.scan_root_id)
            or str(row["scan_run_id"]) != str(plan.source_scan_run_id)
            or str(row["media_type"]) != MediaType.EBOOK.value
            or str(row["presence_state"]) != PresenceState.PRESENT.value
            or str(row["observation_file_id"]) != str(endpoint.file_id)
            or str(row["file_relative_path"]) != relative_path
            or int(row["file_size_bytes"]) != endpoint.expected_size_bytes
            or int(row["observation_size_bytes"]) != endpoint.expected_size_bytes
            or file_modified_at != endpoint.expected_modified_at
            or observation_modified_at != endpoint.expected_modified_at
            or observed_at != endpoint.expected_observed_at
        ):
            raise QuarantineStoreError("quarantine authorization source differs")
        return QuarantineAuthorizationSourceSnapshot(
            role=endpoint.role,
            scan_root_id=endpoint.scan_root_id,
            file_id=endpoint.file_id,
            observation_id=endpoint.observation_id,
            relative_path=relative_path,
            expected_full_sha256=endpoint.expected_full_sha256,
            expected_size_bytes=endpoint.expected_size_bytes,
            expected_modified_at=observation_modified_at,
        )

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

    def create_confirmed_prepared_run(
        self,
        value: QuarantineExecutionRun,
        authorization: QuarantineAuthorizationSnapshot,
        plan: ConsolidationPlan,
        lease: OwnedScanRootWriteLease,
        *,
        confirmation_digest: str,
        confirmed_at: datetime,
        persisted_at: datetime,
    ) -> QuarantineExecutionRun:
        """Consume one authorization once and append confirmed PREPARED atomically."""

        if (
            not isinstance(value, QuarantineExecutionRun)
            or not isinstance(authorization, QuarantineAuthorizationSnapshot)
            or not isinstance(plan, ConsolidationPlan)
            or not isinstance(confirmed_at, datetime)
            or confirmed_at.tzinfo is None
            or confirmed_at.utcoffset() is None
            or not isinstance(persisted_at, datetime)
            or persisted_at.tzinfo is None
            or persisted_at.utcoffset() is None
            or value.created_at != confirmed_at
            or persisted_at < confirmed_at
            or not authorization.authorized_at
            <= confirmed_at
            <= persisted_at
            < authorization.expires_at
            or not isinstance(confirmation_digest, str)
            or len(confirmation_digest) != 64
            or any(character not in "0123456789abcdef" for character in confirmation_digest)
            or lease.owner_kind is not ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN
            or lease.owner_run_id != value.id
            or lease.scan_root_id != value.scan_root_id
            or value.authorization_id != authorization.id
            or value.plan_id != authorization.plan_id
            or value.scan_root_id != authorization.scan_root_id
            or value.keeper_file_id != authorization.keeper_file_id
            or value.candidate_file_id != authorization.candidate_file_id
        ):
            raise QuarantineStoreError("confirmed quarantine run is invalid")
        if plan.keeper is None or plan.candidate is None:
            raise QuarantineStoreError("confirmed quarantine plan binding differs")
        assessment = build_quarantine_authorization(
            plan=plan,
            current_keeper=plan.keeper,
            current_candidate=plan.candidate,
            current_dependencies=plan.dependencies,
            current_reviews=plan.required_reviews,
            quarantine_capability_id=authorization.quarantine_capability_id,
            authorized_at=authorization.authorized_at,
            expires_at=authorization.expires_at,
        )
        if (
            assessment.status is not QuarantineEligibilityStatus.ELIGIBLE
            or assessment.authorization != authorization
        ):
            raise QuarantineStoreError("confirmed quarantine plan binding differs")
        run_row = _run_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    persisted_at,
                )
                SQLiteConsolidationStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
                persisted_authorization = (
                    connection.execute(
                        select(quarantine_authorizations).where(
                            quarantine_authorizations.c.id == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    persisted_authorization is None
                    or dict(persisted_authorization) != _authorization_row(authorization)
                ):
                    raise QuarantineStoreError(
                        "confirmed quarantine authorization is unavailable"
                    )
                existing = (
                    connection.execute(
                        select(quarantine_execution_runs).where(
                            quarantine_execution_runs.c.authorization_id
                            == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    raise QuarantineAuthorizationConsumedError(
                        "quarantine authorization was already consumed"
                    )
                connection.execute(insert(quarantine_execution_runs).values(**run_row))
                connection.execute(
                    insert(quarantine_execution_events).values(
                        run_id=str(value.id),
                        sequence_no=1,
                        status=QuarantineRunStatus.PREPARED.value,
                        occurred_at=datetime_to_db(confirmed_at),
                        fence_epoch=lease.fence_epoch,
                        finding_code=None,
                        confirmation_digest=confirmation_digest,
                    )
                )
        except QuarantineAuthorizationConsumedError:
            raise
        except IntegrityError as error:
            if self.get_run_for_authorization(authorization.id) is not None:
                raise QuarantineAuthorizationConsumedError(
                    "quarantine authorization was already consumed"
                ) from None
            raise QuarantineStoreError(
                "confirmed quarantine run could not be persisted"
            ) from error
        except QuarantineStoreError:
            raise
        except (ConsolidationStoreError, ValueError) as error:
            raise QuarantineStoreError(
                "confirmed quarantine run could not be persisted"
            ) from error
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

    def read_status_snapshot(self, run_id: EntityId) -> QuarantineStatusSnapshot | None:
        """Read only the path-free fields permitted for a quarantine status report."""

        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    select(
                        quarantine_execution_runs.c.id,
                        quarantine_execution_runs.c.authorization_id,
                        quarantine_execution_runs.c.plan_id,
                        quarantine_execution_runs.c.scan_root_id,
                        quarantine_execution_runs.c.created_at,
                        quarantine_authorizations.c.authorized_at,
                        quarantine_authorizations.c.expires_at,
                    )
                    .join(
                        quarantine_authorizations,
                        quarantine_execution_runs.c.authorization_id
                        == quarantine_authorizations.c.id,
                    )
                    .where(quarantine_execution_runs.c.id == str(run_id))
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            events = tuple(
                _status_event_from_row(dict(row))
                for row in connection.execute(
                    select(
                        quarantine_execution_events.c.sequence_no,
                        quarantine_execution_events.c.status,
                        quarantine_execution_events.c.occurred_at,
                    )
                    .where(quarantine_execution_events.c.run_id == str(run_id))
                    .order_by(quarantine_execution_events.c.sequence_no)
                ).mappings()
            )
        created_at = datetime_from_db(str(run["created_at"]))
        authorized_at = datetime_from_db(str(run["authorized_at"]))
        expires_at = datetime_from_db(str(run["expires_at"]))
        if created_at is None or authorized_at is None or expires_at is None:
            raise QuarantineStoreError("quarantine status timestamp is missing")
        if not events:
            raise QuarantineStoreError("quarantine status has no prepared event")
        if tuple(event.sequence_no for event in events) != tuple(range(1, len(events) + 1)):
            raise QuarantineStoreError("quarantine status events are not gapless")
        return QuarantineStatusSnapshot(
            run_id,
            EntityId.parse(str(run["authorization_id"])),
            EntityId.parse(str(run["plan_id"])),
            EntityId.parse(str(run["scan_root_id"])),
            created_at,
            authorized_at,
            expires_at,
            events,
        )


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


def _authorization_from_row(values: dict[str, Any]) -> QuarantineAuthorizationSnapshot:
    return QuarantineAuthorizationSnapshot(
        EntityId.parse(str(values["id"])),
        EntityId.parse(str(values["plan_id"])),
        str(values["plan_content_hash"]),
        EntityId.parse(str(values["scan_root_id"])),
        EntityId.parse(str(values["keeper_file_id"])),
        EntityId.parse(str(values["candidate_file_id"])),
        EntityId.parse(str(values["keeper_observation_id"])),
        EntityId.parse(str(values["candidate_observation_id"])),
        str(values["keeper_full_sha256"]),
        str(values["candidate_full_sha256"]),
        EntityId.parse(str(values["quarantine_capability_id"])),
        str(values["review_fingerprint"]),
        _required_datetime(values["authorized_at"]),
        _required_datetime(values["expires_at"]),
        str(values["content_hash"]),
        str(values["profile"]),
    )


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


def _run_from_row(values: dict[str, Any]) -> QuarantineExecutionRun:
    if str(values["profile"]) != "quarantine-execution/v1":
        raise QuarantineStoreError("quarantine execution profile is invalid")
    return QuarantineExecutionRun(
        EntityId.parse(str(values["id"])),
        EntityId.parse(str(values["authorization_id"])),
        EntityId.parse(str(values["plan_id"])),
        EntityId.parse(str(values["scan_root_id"])),
        EntityId.parse(str(values["keeper_file_id"])),
        EntityId.parse(str(values["candidate_file_id"])),
        str(values["target_token"]),
        _required_datetime(values["created_at"]),
    )


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


def _status_event_from_row(values: dict[str, Any]) -> QuarantineStatusEventSnapshot:
    occurred_at = datetime_from_db(str(values["occurred_at"]))
    if occurred_at is None:
        raise QuarantineStoreError("quarantine event timestamp is missing")
    return QuarantineStatusEventSnapshot(
        int(values["sequence_no"]),
        QuarantineRunStatus(str(values["status"])),
        occurred_at,
    )


def _required_datetime(value: object) -> datetime:
    parsed = datetime_from_db(str(value))
    if parsed is None:
        raise QuarantineStoreError("quarantine authorization timestamp is missing")
    return parsed


@contextmanager
def _immediate_transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize a preparedless-run check with its expired-lease takeover."""

    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
