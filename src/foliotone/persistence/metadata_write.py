"""Fenced insert-only persistence for ADR-0063 metadata-write operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from foliotone.core import EntityId, PresenceState, ScanRunStatus
from foliotone.core._validation import require_relative_path
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.metadata_write.authorization import (
    MAX_METADATA_WRITE_EVENTS,
    MetadataWriteAuthorizationSnapshot,
    MetadataWriteExecutionEvent,
    MetadataWriteExecutionRun,
    MetadataWriteRunStatus,
)
from foliotone.metadata_write.contracts import (
    LINUX_METADATA_WRITE_BACKEND_PROFILE,
    LINUX_METADATA_WRITE_PROBE_PROFILE,
)
from foliotone.metadata_write.reconciliation import (
    MetadataWriteReconciliationOutcome,
    MetadataWriteReconciliationSnapshot,
)
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_from_db, datetime_to_db
from foliotone.persistence.collection_state_schema import (
    collection_state_items,
    collection_state_snapshots,
)
from foliotone.persistence.metadata_correction import (
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
)
from foliotone.persistence.metadata_write_schema import (
    metadata_write_authorizations,
    metadata_write_backend_bindings,
    metadata_write_events,
    metadata_write_reconciliations,
    metadata_write_runs,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)


class MetadataWriteStoreError(RuntimeError):
    """A path-free authorization, lineage, fence, or journal invariant failed."""


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusEventSnapshot:
    """Only event material safe for a standard status projection."""

    sequence_no: int
    status: MetadataWriteRunStatus
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusReconciliationSnapshot:
    """Only opaque reconciliation material safe for a standard status report."""

    outcome: MetadataWriteReconciliationOutcome
    scan_run_id: EntityId
    observation_id: EntityId
    collection_state_snapshot_id: EntityId
    reconciled_at: datetime


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusSnapshot:
    """Bounded path-, hash-, value-, capability-, and fence-free status material."""

    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    writer_profile: str
    run_profile: str
    authorization_profile: str
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    events: tuple[MetadataWriteStatusEventSnapshot, ...]
    reconciliation: MetadataWriteStatusReconciliationSnapshot | None = None


@dataclass(frozen=True, slots=True)
class MetadataWriteBackendBinding:
    """Immutable path-free selection of the one accepted MW04 backend."""

    run_id: EntityId
    bound_at: datetime
    backend_profile: str = LINUX_METADATA_WRITE_BACKEND_PROFILE
    conformance_profile: str = LINUX_METADATA_WRITE_PROBE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_id, EntityId)
            or self.backend_profile != LINUX_METADATA_WRITE_BACKEND_PROFILE
            or self.conformance_profile != LINUX_METADATA_WRITE_PROBE_PROFILE
            or not isinstance(self.bound_at, datetime)
            or self.bound_at.tzinfo is None
            or self.bound_at.utcoffset() is None
        ):
            raise MetadataWriteStoreError("metadata write backend binding is invalid")
        object.__setattr__(self, "bound_at", self.bound_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class MetadataWriteSourceSnapshot:
    """Private persistence-derived locator for one exact authorized source."""

    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    relative_path: str = field(repr=False)
    source_sha256: str = field(repr=False)
    source_size_bytes: int
    expected_modified_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.run_id,
                self.authorization_id,
                self.plan_id,
                self.scan_root_id,
                self.file_id,
                self.observation_id,
            )
        ):
            raise MetadataWriteStoreError("metadata write source binding is invalid")
        try:
            relative_path = require_relative_path(self.relative_path)
        except (TypeError, ValueError):
            raise MetadataWriteStoreError("metadata write source binding is invalid") from None
        if (
            len(self.source_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.source_sha256)
            or isinstance(self.source_size_bytes, bool)
            or not isinstance(self.source_size_bytes, int)
            or self.source_size_bytes <= 0
            or not isinstance(self.expected_modified_at, datetime)
            or self.expected_modified_at.tzinfo is None
            or self.expected_modified_at.utcoffset() is None
        ):
            raise MetadataWriteStoreError("metadata write source binding is invalid")
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(
            self,
            "expected_modified_at",
            self.expected_modified_at.astimezone(UTC),
        )


@dataclass(frozen=True, slots=True)
class MetadataWritePreparationSourceSnapshot:
    """Private current locator returned only under the preparation fence."""

    scan_root_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    relative_path: str = field(repr=False)
    source_sha256: str = field(repr=False)
    source_size_bytes: int
    expected_modified_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId)
            for value in (self.scan_root_id, self.file_id, self.observation_id)
        ):
            raise MetadataWriteStoreError("metadata write preparation source is invalid")
        try:
            relative_path = require_relative_path(self.relative_path)
        except (TypeError, ValueError):
            raise MetadataWriteStoreError("metadata write preparation source is invalid") from None
        if (
            len(self.source_sha256) != 64
            or any(value not in "0123456789abcdef" for value in self.source_sha256)
            or isinstance(self.source_size_bytes, bool)
            or not isinstance(self.source_size_bytes, int)
            or self.source_size_bytes <= 0
            or not isinstance(self.expected_modified_at, datetime)
            or self.expected_modified_at.tzinfo is None
            or self.expected_modified_at.utcoffset() is None
        ):
            raise MetadataWriteStoreError("metadata write preparation source is invalid")
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(
            self,
            "expected_modified_at",
            self.expected_modified_at.astimezone(UTC),
        )


_FAIL_BEFORE_EXCHANGE = frozenset(
    {
        MetadataWriteRunStatus.STALE,
        MetadataWriteRunStatus.TOOL_UNAVAILABLE,
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
        MetadataWriteRunStatus.CANCELLED,
    }
)
_NEXT: dict[MetadataWriteRunStatus, frozenset[MetadataWriteRunStatus]] = {
    MetadataWriteRunStatus.CREATED: frozenset(
        {
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            *_FAIL_BEFORE_EXCHANGE,
        }
    ),
    MetadataWriteRunStatus.PREPARED: frozenset(
        {
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            *_FAIL_BEFORE_EXCHANGE,
        }
    ),
    MetadataWriteRunStatus.EXCHANGED: frozenset(
        {
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
        }
    ),
    MetadataWriteRunStatus.ORIGINAL_PRESERVED: frozenset(
        {
            MetadataWriteRunStatus.VERIFIED,
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
        }
    ),
    MetadataWriteRunStatus.VALIDATION_FAILED: frozenset(
        {
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    MetadataWriteRunStatus.FENCED_OUT: frozenset(
        {
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED: frozenset({MetadataWriteRunStatus.RECOVERED}),
}
_RECOVERABLE_FAILURES = frozenset(
    {
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
    }
)
_RECOVERY_OUTCOMES = frozenset(
    {
        MetadataWriteRunStatus.RECOVERED,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
    }
)
_RECOVERY_SOURCE_STATUSES = frozenset(
    {
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        MetadataWriteRunStatus.RECOVERED,
    }
)


class SQLiteMetadataWriteStore:
    """Persist one-use authorizations and gapless fence-bound execution journals."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def require_preparation_source(
        self,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> MetadataWritePreparationSourceSnapshot:
        """Return the current private locator only under a preparation fence."""

        candidate = plan.candidate
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION
            or lease.scan_root_id != candidate.scan_root_id
            or not isinstance(checked_at, datetime)
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or checked_at < lease.acquired_at
            or checked_at >= lease.lease_expires_at
        ):
            raise MetadataWriteStoreError("metadata write preparation lease is unavailable")
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked_at,
                )
                SQLiteMetadataCorrectionStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
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
                            schema.file_observations.c.relative_path.label(
                                "observation_relative_path"
                            ),
                            schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                            schema.file_observations.c.modified_at.label("observation_modified_at"),
                        )
                        .select_from(
                            schema.file_records.join(
                                schema.file_observations,
                                schema.file_observations.c.file_id == schema.file_records.c.id,
                            )
                        )
                        .where(
                            schema.file_records.c.id == str(candidate.file_id),
                            schema.file_observations.c.id == str(candidate.observation_id),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise MetadataWriteStoreError(
                        "metadata write preparation source is unavailable"
                    )
                observation_modified_at = _required_datetime(row["observation_modified_at"])
                observation_path = str(row["observation_relative_path"])
                if (
                    str(row["scan_root_id"]) != str(candidate.scan_root_id)
                    or str(row["media_type"]) != "EBOOK"
                    or str(row["presence_state"]) != PresenceState.PRESENT.value
                    or str(row["observation_file_id"]) != str(candidate.file_id)
                    or str(row["file_relative_path"]) != observation_path
                    or int(row["file_size_bytes"]) != candidate.expected_size_bytes
                    or int(row["observation_size_bytes"]) != candidate.expected_size_bytes
                    or _required_datetime(row["file_modified_at"]) != candidate.expected_modified_at
                    or observation_modified_at != candidate.expected_modified_at
                ):
                    raise MetadataWriteStoreError("metadata write preparation source differs")
                return MetadataWritePreparationSourceSnapshot(
                    scan_root_id=candidate.scan_root_id,
                    file_id=candidate.file_id,
                    observation_id=candidate.observation_id,
                    relative_path=observation_path,
                    source_sha256=candidate.expected_full_sha256,
                    source_size_bytes=candidate.expected_size_bytes,
                    expected_modified_at=observation_modified_at,
                )
        except MetadataWriteStoreError:
            raise
        except (
            MetadataCorrectionStoreError,
            ScanRootWriteLeaseError,
            ValueError,
        ) as error:
            raise MetadataWriteStoreError(
                "metadata write preparation source is unavailable"
            ) from error

    def create_or_get_authorization(
        self,
        value: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        persisted_at: datetime,
    ) -> MetadataWriteAuthorizationSnapshot:
        """Persist a new authorization only while its preparation fence is owned."""

        if not isinstance(value, MetadataWriteAuthorizationSnapshot):
            raise MetadataWriteStoreError("metadata write authorization is invalid")
        row = _authorization_row(value)
        try:
            with self._engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(metadata_write_authorizations).where(
                            metadata_write_authorizations.c.id == str(value.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != row:
                        raise MetadataWriteStoreError("metadata write authorization retry differs")
                    return _authorization_from_row(existing)
                self._require_preparation_lease(value, lease, persisted_at)
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    persisted_at,
                )
                self._require_plan(connection, value, plan)
                connection.execute(insert(metadata_write_authorizations).values(**row))
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, MetadataCorrectionStoreError, ScanRootWriteLeaseError) as error:
            raise MetadataWriteStoreError(
                "metadata write authorization could not be persisted"
            ) from error
        return value

    def create_run(
        self,
        value: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        confirmation_digest: str,
    ) -> MetadataWriteExecutionRun:
        """Consume one authorization once and append CREATED in the same fence."""

        self._require_run_material(value, authorization, lease)
        if (
            not isinstance(confirmation_digest, str)
            or len(confirmation_digest) != 64
            or any(value not in "0123456789abcdef" for value in confirmation_digest)
        ):
            raise MetadataWriteStoreError("metadata write execution confirmation is invalid")
        run_row = _run_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.created_at,
                )
                existing_by_authorization = (
                    connection.execute(
                        select(metadata_write_runs).where(
                            metadata_write_runs.c.authorization_id == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_by_authorization is not None:
                    if dict(existing_by_authorization) != run_row:
                        raise MetadataWriteStoreError(
                            "metadata write authorization was already consumed"
                        )
                    self._require_created_event(
                        connection,
                        value,
                        confirmation_digest,
                    )
                    return _run_from_row(existing_by_authorization)
                persisted_authorization = (
                    connection.execute(
                        select(metadata_write_authorizations).where(
                            metadata_write_authorizations.c.id == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    persisted_authorization is None
                    or dict(persisted_authorization) != _authorization_row(authorization)
                    or not authorization.authorized_at
                    <= value.created_at
                    < authorization.expires_at
                ):
                    raise MetadataWriteStoreError("metadata write authorization is unavailable")
                self._require_plan(connection, authorization, plan)
                connection.execute(insert(metadata_write_runs).values(**run_row))
                connection.execute(
                    insert(metadata_write_events).values(
                        run_id=str(value.id),
                        sequence_no=1,
                        status=MetadataWriteRunStatus.CREATED.value,
                        occurred_at=datetime_to_db(value.created_at),
                        fence_epoch=lease.fence_epoch,
                        finding_code=None,
                        confirmation_digest=confirmation_digest,
                    )
                )
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, MetadataCorrectionStoreError, ScanRootWriteLeaseError) as error:
            raise MetadataWriteStoreError("metadata write run could not be created") from error
        return value

    def require_execution_confirmation(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
        *,
        confirmation_digest: str,
        checked_at: datetime,
    ) -> None:
        """Revalidate a retry against the immutable CREATED confirmation."""

        self._require_active_run_lease(run, authorization, lease, checked_at)
        if (
            not isinstance(confirmation_digest, str)
            or len(confirmation_digest) != 64
            or any(value not in "0123456789abcdef" for value in confirmation_digest)
        ):
            raise MetadataWriteStoreError("metadata write execution confirmation is invalid")
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked_at,
                )
                self._require_persisted_execution_material(
                    connection,
                    run,
                    authorization,
                )
                self._require_created_event(
                    connection,
                    run,
                    confirmation_digest,
                )
        except MetadataWriteStoreError:
            raise
        except (ScanRootWriteLeaseError, ValueError) as error:
            raise MetadataWriteStoreError(
                "metadata write execution confirmation is unavailable"
            ) from error

    def bind_backend(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        bound_at: datetime,
    ) -> MetadataWriteBackendBinding:
        """Select the fixed backend once under the current authorization fence."""

        self._require_active_run_lease(run, authorization, lease, bound_at)
        binding = MetadataWriteBackendBinding(run.id, bound_at)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    binding.bound_at,
                )
                self._require_persisted_execution_material(
                    connection,
                    run,
                    authorization,
                )
                if not (authorization.authorized_at <= binding.bound_at < authorization.expires_at):
                    raise MetadataWriteStoreError("metadata write authorization is unavailable")
                self._require_latest_status(
                    connection,
                    run,
                    frozenset({MetadataWriteRunStatus.CREATED}),
                )
                self._require_plan(connection, authorization, plan)
                existing = (
                    connection.execute(
                        select(metadata_write_backend_bindings).where(
                            metadata_write_backend_bindings.c.run_id == str(run.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    persisted = _backend_binding_from_row(existing)
                    if (
                        persisted.backend_profile != binding.backend_profile
                        or persisted.conformance_profile != binding.conformance_profile
                        or persisted.bound_at < run.created_at
                        or not authorization.authorized_at
                        <= persisted.bound_at
                        < authorization.expires_at
                        or persisted.bound_at > binding.bound_at
                    ):
                        raise MetadataWriteStoreError("metadata write backend binding differs")
                    return persisted
                connection.execute(
                    insert(metadata_write_backend_bindings).values(**_backend_binding_row(binding))
                )
        except MetadataWriteStoreError:
            raise
        except (
            IntegrityError,
            MetadataCorrectionStoreError,
            ScanRootWriteLeaseError,
            ValueError,
        ) as error:
            raise MetadataWriteStoreError("metadata write backend could not be bound") from error
        return binding

    def require_execution_source(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> MetadataWriteSourceSnapshot:
        """Return the private locator only while every live gate remains current."""

        return self._require_live_execution_source(
            run,
            authorization,
            plan,
            lease,
            checked_at=checked_at,
            required_status=MetadataWriteRunStatus.CREATED,
        )

    def require_prepared_execution_source(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> MetadataWriteSourceSnapshot:
        """Recheck every live gate immediately before the atomic exchange."""

        return self._require_live_execution_source(
            run,
            authorization,
            plan,
            lease,
            checked_at=checked_at,
            required_status=MetadataWriteRunStatus.PREPARED,
        )

    def _require_live_execution_source(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
        required_status: MetadataWriteRunStatus,
    ) -> MetadataWriteSourceSnapshot:
        self._require_active_run_lease(run, authorization, lease, checked_at)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked_at,
                )
                self._require_persisted_execution_material(
                    connection,
                    run,
                    authorization,
                )
                if not (authorization.authorized_at <= checked_at < authorization.expires_at):
                    raise MetadataWriteStoreError("metadata write authorization is unavailable")
                self._require_latest_status(
                    connection,
                    run,
                    frozenset({required_status}),
                )
                self._require_backend_binding(
                    connection,
                    run,
                    authorization,
                    checked_at=checked_at,
                )
                self._require_plan(connection, authorization, plan)
                return self._source_snapshot(
                    connection,
                    run,
                    authorization,
                    plan,
                    require_current_file=True,
                )
        except MetadataWriteStoreError:
            raise
        except (
            MetadataCorrectionStoreError,
            ScanRootWriteLeaseError,
            ValueError,
        ) as error:
            raise MetadataWriteStoreError(
                "metadata write execution source is unavailable"
            ) from error

    def require_recovery_source(
        self,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> MetadataWriteSourceSnapshot:
        """Return the historical locator for bounded recovery under a fresh fence."""

        self._require_active_run_lease(run, authorization, lease, checked_at)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked_at,
                )
                self._require_persisted_execution_material(
                    connection,
                    run,
                    authorization,
                )
                self._require_backend_binding(
                    connection,
                    run,
                    authorization,
                    checked_at=checked_at,
                )
                self._require_latest_status(
                    connection,
                    run,
                    _RECOVERY_SOURCE_STATUSES,
                )
                self._require_plan_binding(authorization, plan)
                SQLiteMetadataCorrectionStore(
                    self._engine
                ).require_persisted_approved_plan_in_transaction(connection, plan)
                return self._source_snapshot(
                    connection,
                    run,
                    authorization,
                    plan,
                    require_current_file=False,
                )
        except MetadataWriteStoreError:
            raise
        except (
            MetadataCorrectionStoreError,
            ScanRootWriteLeaseError,
            ValueError,
        ) as error:
            raise MetadataWriteStoreError(
                "metadata write recovery source is unavailable"
            ) from error

    def append_event(
        self,
        value: MetadataWriteExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> MetadataWriteExecutionEvent:
        """Append exactly one valid next phase under the run's current fence."""

        if not isinstance(value, MetadataWriteExecutionEvent):
            raise MetadataWriteStoreError("metadata write event is invalid")
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            or lease.owner_run_id != value.run_id
            or lease.fence_epoch != value.fence_epoch
            or value.occurred_at < lease.acquired_at
            or value.occurred_at >= lease.lease_expires_at
        ):
            raise MetadataWriteStoreError("metadata write event requires its run lease")
        event_row = _event_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.occurred_at,
                )
                run = (
                    connection.execute(
                        select(metadata_write_runs).where(
                            metadata_write_runs.c.id == str(value.run_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if run is None or str(run["scan_root_id"]) != str(lease.scan_root_id):
                    raise MetadataWriteStoreError("metadata write run is unavailable")
                existing = (
                    connection.execute(
                        select(metadata_write_events).where(
                            metadata_write_events.c.run_id == str(value.run_id),
                            metadata_write_events.c.sequence_no == value.sequence_no,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != event_row:
                        raise MetadataWriteStoreError("metadata write event retry differs")
                    return _event_from_row(existing)
                previous = (
                    connection.execute(
                        select(metadata_write_events)
                        .where(metadata_write_events.c.run_id == str(value.run_id))
                        .order_by(metadata_write_events.c.sequence_no.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous is None:
                    raise MetadataWriteStoreError("metadata write CREATED event is missing")
                previous_status = MetadataWriteRunStatus(str(previous["status"]))
                previous_at = _required_datetime(previous["occurred_at"])
                exchange_recorded = False
                if previous_status in _RECOVERABLE_FAILURES and value.status in _RECOVERY_OUTCOMES:
                    exchange_recorded = (
                        connection.execute(
                            select(metadata_write_events.c.run_id)
                            .where(
                                metadata_write_events.c.run_id == str(value.run_id),
                                metadata_write_events.c.status
                                == MetadataWriteRunStatus.EXCHANGED.value,
                            )
                            .limit(1)
                        ).first()
                        is not None
                    )
                if (
                    value.sequence_no != int(previous["sequence_no"]) + 1
                    or not _transition_allowed(
                        previous_status,
                        value.status,
                        exchange_recorded=exchange_recorded,
                    )
                    or value.occurred_at < previous_at
                ):
                    raise MetadataWriteStoreError("metadata write event transition is invalid")
                connection.execute(insert(metadata_write_events).values(**event_row))
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise MetadataWriteStoreError("metadata write event could not be appended") from error
        return value

    def get_authorization(
        self,
        authorization_id: EntityId,
    ) -> MetadataWriteAuthorizationSnapshot | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_authorizations).where(
                        metadata_write_authorizations.c.id == str(authorization_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _authorization_from_row(row)

    def get_run(self, run_id: EntityId) -> MetadataWriteExecutionRun | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_runs).where(metadata_write_runs.c.id == str(run_id))
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _run_from_row(row)

    def get_run_for_authorization(
        self,
        authorization_id: EntityId,
    ) -> MetadataWriteExecutionRun | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_runs).where(
                        metadata_write_runs.c.authorization_id == str(authorization_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _run_from_row(row)

    def get_reconciliation(
        self,
        run_id: EntityId,
    ) -> MetadataWriteReconciliationSnapshot | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_reconciliations).where(
                        metadata_write_reconciliations.c.run_id == str(run_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _reconciliation_from_row(row)

    def record_reconciliation(
        self,
        value: MetadataWriteReconciliationSnapshot,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
    ) -> MetadataWriteReconciliationSnapshot:
        """Bind one exact rescan and optionally append VERIFIED atomically."""

        if (
            not isinstance(value, MetadataWriteReconciliationSnapshot)
            or value.run_id != run.id
            or value.authorization_id != authorization.id
            or value.authorization_content_hash != authorization.content_hash
        ):
            raise MetadataWriteStoreError("metadata write reconciliation is invalid")
        self._require_active_run_lease(
            run,
            authorization,
            lease,
            value.reconciled_at,
        )
        expected_previous = (
            MetadataWriteRunStatus.ORIGINAL_PRESERVED
            if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
            else MetadataWriteRunStatus.RECOVERED
        )
        row = _reconciliation_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.reconciled_at,
                )
                self._require_persisted_execution_material(
                    connection,
                    run,
                    authorization,
                )
                self._require_backend_binding(
                    connection,
                    run,
                    authorization,
                    checked_at=value.reconciled_at,
                )
                existing = (
                    connection.execute(
                        select(metadata_write_reconciliations).where(
                            metadata_write_reconciliations.c.run_id == str(run.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                latest = self._require_latest_status(
                    connection,
                    run,
                    frozenset(
                        {
                            expected_previous,
                            MetadataWriteRunStatus.VERIFIED,
                        }
                        if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
                        else {expected_previous}
                    ),
                )
                if existing is not None:
                    if dict(existing) != row or (
                        value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
                        and latest is not MetadataWriteRunStatus.VERIFIED
                    ):
                        raise MetadataWriteStoreError("metadata write reconciliation retry differs")
                    return _reconciliation_from_row(existing)
                if latest is not expected_previous:
                    raise MetadataWriteStoreError(
                        "metadata write reconciliation status is unavailable"
                    )
                self._require_reconciliation_evidence(
                    connection,
                    value,
                    run,
                    authorization,
                )
                connection.execute(insert(metadata_write_reconciliations).values(**row))
                if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED:
                    previous = (
                        connection.execute(
                            select(metadata_write_events)
                            .where(metadata_write_events.c.run_id == str(run.id))
                            .order_by(metadata_write_events.c.sequence_no.desc())
                            .limit(1)
                        )
                        .mappings()
                        .one()
                    )
                    sequence_no = int(previous["sequence_no"]) + 1
                    if sequence_no > MAX_METADATA_WRITE_EVENTS:
                        raise MetadataWriteStoreError("metadata write event capacity is exhausted")
                    connection.execute(
                        insert(metadata_write_events).values(
                            run_id=str(run.id),
                            sequence_no=sequence_no,
                            status=MetadataWriteRunStatus.VERIFIED.value,
                            occurred_at=datetime_to_db(value.reconciled_at),
                            fence_epoch=lease.fence_epoch,
                            finding_code="RECONCILIATION_VERIFIED",
                            confirmation_digest=value.content_hash,
                        )
                    )
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise MetadataWriteStoreError(
                "metadata write reconciliation could not be persisted"
            ) from error
        return value

    def get_backend_binding(
        self,
        run_id: EntityId,
    ) -> MetadataWriteBackendBinding | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_backend_bindings).where(
                        metadata_write_backend_bindings.c.run_id == str(run_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _backend_binding_from_row(row)

    def events_for_run(
        self,
        run_id: EntityId,
    ) -> tuple[MetadataWriteExecutionEvent, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(metadata_write_events)
                .where(metadata_write_events.c.run_id == str(run_id))
                .order_by(metadata_write_events.c.sequence_no)
            ).mappings()
            return tuple(_event_from_row(row) for row in rows)

    def read_status_snapshot(
        self,
        run_id: EntityId,
    ) -> MetadataWriteStatusSnapshot | None:
        """Read only the fixed public subset; private material is not selected."""

        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    select(
                        metadata_write_runs.c.id,
                        metadata_write_runs.c.authorization_id,
                        metadata_write_runs.c.plan_id,
                        metadata_write_runs.c.scan_root_id,
                        metadata_write_runs.c.writer_profile,
                        metadata_write_runs.c.profile.label("run_profile"),
                        metadata_write_runs.c.created_at,
                        metadata_write_authorizations.c.profile.label("authorization_profile"),
                        metadata_write_authorizations.c.authorized_at,
                        metadata_write_authorizations.c.expires_at,
                    )
                    .join(
                        metadata_write_authorizations,
                        metadata_write_runs.c.authorization_id
                        == metadata_write_authorizations.c.id,
                    )
                    .where(metadata_write_runs.c.id == str(run_id))
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            events = tuple(
                MetadataWriteStatusEventSnapshot(
                    int(row["sequence_no"]),
                    MetadataWriteRunStatus(str(row["status"])),
                    _required_datetime(row["occurred_at"]),
                )
                for row in connection.execute(
                    select(
                        metadata_write_events.c.sequence_no,
                        metadata_write_events.c.status,
                        metadata_write_events.c.occurred_at,
                    )
                    .where(metadata_write_events.c.run_id == str(run_id))
                    .order_by(metadata_write_events.c.sequence_no)
                    .limit(MAX_METADATA_WRITE_EVENTS + 1)
                ).mappings()
            )
            reconciliation_row = (
                connection.execute(
                    select(
                        metadata_write_reconciliations.c.outcome_status,
                        metadata_write_reconciliations.c.scan_run_id,
                        metadata_write_reconciliations.c.observation_id,
                        metadata_write_reconciliations.c.collection_state_snapshot_id,
                        metadata_write_reconciliations.c.reconciled_at,
                    ).where(metadata_write_reconciliations.c.run_id == str(run_id))
                )
                .mappings()
                .one_or_none()
            )
        created_at = _required_datetime(run["created_at"])
        if (
            not events
            or len(events) > MAX_METADATA_WRITE_EVENTS
            or tuple(event.sequence_no for event in events) != tuple(range(1, len(events) + 1))
            or events[0].status is not MetadataWriteRunStatus.CREATED
            or events[0].occurred_at != created_at
            or not _status_events_are_valid(events)
        ):
            raise MetadataWriteStoreError("metadata write status journal is invalid")
        reconciliation = (
            None
            if reconciliation_row is None
            else MetadataWriteStatusReconciliationSnapshot(
                outcome=MetadataWriteReconciliationOutcome(
                    str(reconciliation_row["outcome_status"])
                ),
                scan_run_id=EntityId.parse(str(reconciliation_row["scan_run_id"])),
                observation_id=EntityId.parse(str(reconciliation_row["observation_id"])),
                collection_state_snapshot_id=EntityId.parse(
                    str(reconciliation_row["collection_state_snapshot_id"])
                ),
                reconciled_at=_required_datetime(reconciliation_row["reconciled_at"]),
            )
        )
        if (
            events[-1].status is MetadataWriteRunStatus.VERIFIED
            and (
                reconciliation is None
                or reconciliation.outcome is not MetadataWriteReconciliationOutcome.VERIFIED
            )
        ) or (
            reconciliation is not None
            and (
                reconciliation.outcome is MetadataWriteReconciliationOutcome.VERIFIED
                and events[-1].status is not MetadataWriteRunStatus.VERIFIED
                or reconciliation.outcome is MetadataWriteReconciliationOutcome.RECOVERED
                and events[-1].status is not MetadataWriteRunStatus.RECOVERED
            )
        ):
            raise MetadataWriteStoreError("metadata write status reconciliation is invalid")
        return MetadataWriteStatusSnapshot(
            run_id=EntityId.parse(str(run["id"])),
            authorization_id=EntityId.parse(str(run["authorization_id"])),
            plan_id=EntityId.parse(str(run["plan_id"])),
            scan_root_id=EntityId.parse(str(run["scan_root_id"])),
            writer_profile=str(run["writer_profile"]),
            run_profile=str(run["run_profile"]),
            authorization_profile=str(run["authorization_profile"]),
            created_at=created_at,
            authorized_at=_required_datetime(run["authorized_at"]),
            expires_at=_required_datetime(run["expires_at"]),
            events=events,
            reconciliation=reconciliation,
        )

    @staticmethod
    def _require_reconciliation_evidence(
        connection: Any,
        value: MetadataWriteReconciliationSnapshot,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
    ) -> None:
        expected_phase = (
            MetadataWriteRunStatus.ORIGINAL_PRESERVED
            if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
            else MetadataWriteRunStatus.RECOVERED
        )
        phase = connection.execute(
            select(metadata_write_events.c.occurred_at)
            .where(
                metadata_write_events.c.run_id == str(run.id),
                metadata_write_events.c.status == expected_phase.value,
            )
            .order_by(metadata_write_events.c.sequence_no.desc())
            .limit(1)
        ).one_or_none()
        scan = (
            connection.execute(
                select(schema.scan_runs).where(schema.scan_runs.c.id == str(value.scan_run_id))
            )
            .mappings()
            .one_or_none()
        )
        original_observation = (
            connection.execute(
                select(
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.relative_path,
                ).where(schema.file_observations.c.id == str(authorization.observation_id))
            )
            .mappings()
            .one_or_none()
        )
        observed = (
            connection.execute(
                select(
                    schema.file_observations.c.file_id,
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.relative_path,
                    schema.file_observations.c.size_bytes,
                    schema.file_observations.c.modified_at,
                    schema.file_records.c.scan_root_id,
                    schema.file_records.c.relative_path.label("file_relative_path"),
                    schema.file_records.c.size_bytes.label("file_size_bytes"),
                    schema.file_records.c.modified_at.label("file_modified_at"),
                    schema.file_records.c.presence_state,
                )
                .select_from(
                    schema.file_observations.join(
                        schema.file_records,
                        schema.file_records.c.id == schema.file_observations.c.file_id,
                    )
                )
                .where(schema.file_observations.c.id == str(value.observation_id))
            )
            .mappings()
            .one_or_none()
        )
        collection = (
            connection.execute(
                select(
                    collection_state_snapshots.c.scan_root_id,
                    collection_state_snapshots.c.source_scan_run_id,
                    collection_state_snapshots.c.created_at,
                    collection_state_snapshots.c.content_digest,
                    collection_state_items.c.file_id,
                    collection_state_items.c.observation_id,
                    collection_state_items.c.size_bytes,
                )
                .select_from(
                    collection_state_snapshots.join(
                        collection_state_items,
                        collection_state_items.c.snapshot_id == collection_state_snapshots.c.id,
                    )
                )
                .where(
                    collection_state_snapshots.c.id == str(value.collection_state_snapshot_id),
                    collection_state_items.c.file_id == str(run.file_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        fingerprints = tuple(
            str(row.value)
            for row in connection.execute(
                select(schema.fingerprints.c.value).where(
                    schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                    schema.fingerprints.c.target_id == str(value.observation_id),
                    schema.fingerprints.c.kind == "FILE_SHA256",
                    schema.fingerprints.c.algorithm == "sha256",
                    schema.fingerprints.c.algorithm_version == "1",
                    schema.fingerprints.c.tool_execution_id.is_(None),
                )
            )
        )
        expected_hash = (
            authorization.expected_output_sha256
            if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
            else authorization.source_sha256
        )
        expected_size = (
            authorization.expected_output_size_bytes
            if value.outcome is MetadataWriteReconciliationOutcome.VERIFIED
            else authorization.source_size_bytes
        )
        if (
            phase is None
            or scan is None
            or original_observation is None
            or observed is None
            or collection is None
            or fingerprints != (expected_hash,)
        ):
            raise MetadataWriteStoreError("metadata write reconciliation evidence is unavailable")
        phase_at = _required_datetime(phase.occurred_at)
        scan_started = _required_datetime(scan["started_at"])
        scan_completed = (
            None if scan["completed_at"] is None else _required_datetime(scan["completed_at"])
        )
        observation_modified = _required_datetime(observed["modified_at"])
        if (
            str(scan["scan_root_id"]) != str(run.scan_root_id)
            or str(scan["status"]) != ScanRunStatus.COMPLETED.value
            or scan_completed is None
            or scan_started <= phase_at
            or scan_completed > value.reconciled_at
            or str(original_observation["scan_run_id"]) == str(value.scan_run_id)
            or value.observation_id == authorization.observation_id
            or str(observed["file_id"]) != str(run.file_id)
            or str(observed["scan_run_id"]) != str(value.scan_run_id)
            or str(observed["relative_path"]) != str(original_observation["relative_path"])
            or int(observed["size_bytes"]) != expected_size
            or str(observed["scan_root_id"]) != str(run.scan_root_id)
            or str(observed["presence_state"]) != PresenceState.PRESENT.value
            or str(observed["file_relative_path"]) != str(observed["relative_path"])
            or int(observed["file_size_bytes"]) != expected_size
            or _required_datetime(observed["file_modified_at"]) != observation_modified
            or str(collection["scan_root_id"]) != str(run.scan_root_id)
            or str(collection["source_scan_run_id"]) != str(value.scan_run_id)
            or str(collection["content_digest"]) != value.collection_state_content_digest
            or _required_datetime(collection["created_at"]) > value.reconciled_at
            or str(collection["file_id"]) != str(run.file_id)
            or str(collection["observation_id"]) != str(value.observation_id)
            or int(collection["size_bytes"]) != expected_size
        ):
            raise MetadataWriteStoreError("metadata write reconciliation evidence differs")

    def _require_preparation_lease(
        self,
        value: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
        persisted_at: datetime,
    ) -> None:
        if (
            not isinstance(persisted_at, datetime)
            or persisted_at.tzinfo is None
            or persisted_at.utcoffset() is None
        ):
            raise MetadataWriteStoreError("metadata write authorization timestamp is invalid")
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION
            or lease.owner_run_id != value.preparation_owner_id
            or lease.scan_root_id != value.scan_root_id
            or lease.fence_epoch != value.preparation_fence_epoch
            or lease.acquired_at > value.authorized_at
            or persisted_at < value.prepared_at
            or persisted_at >= value.expires_at
        ):
            raise MetadataWriteStoreError(
                "metadata write authorization requires its preparation lease"
            )

    def _require_plan(
        self,
        connection: Any,
        value: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
    ) -> None:
        self._require_plan_binding(value, plan)
        SQLiteMetadataCorrectionStore(self._engine).require_current_approved_plan_in_transaction(
            connection, plan
        )

    @staticmethod
    def _require_plan_binding(
        value: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
    ) -> None:
        candidate = plan.candidate
        if (
            value.plan_id != plan.id
            or value.plan_content_hash != plan.content_hash
            or value.scan_root_id != candidate.scan_root_id
            or value.file_id != candidate.file_id
            or value.observation_id != candidate.observation_id
            or value.source_sha256 != candidate.expected_full_sha256
            or value.source_size_bytes != candidate.expected_size_bytes
        ):
            raise MetadataWriteStoreError("metadata write plan binding differs")

    @staticmethod
    def _require_active_run_lease(
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
        checked_at: datetime,
    ) -> None:
        if (
            not isinstance(run, MetadataWriteExecutionRun)
            or not isinstance(authorization, MetadataWriteAuthorizationSnapshot)
            or run.authorization_id != authorization.id
            or run.authorization_content_hash != authorization.content_hash
            or run.plan_id != authorization.plan_id
            or run.scan_root_id != authorization.scan_root_id
            or run.file_id != authorization.file_id
            or run.metadata_write_capability_id != authorization.metadata_write_capability_id
            or not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            or lease.owner_run_id != run.id
            or lease.scan_root_id != run.scan_root_id
            or not isinstance(checked_at, datetime)
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or checked_at < run.created_at
            or checked_at < lease.acquired_at
            or checked_at >= lease.lease_expires_at
        ):
            raise MetadataWriteStoreError("metadata write run lease is unavailable")

    @staticmethod
    def _require_persisted_execution_material(
        connection: Any,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
    ) -> None:
        persisted_run = (
            connection.execute(
                select(metadata_write_runs).where(metadata_write_runs.c.id == str(run.id))
            )
            .mappings()
            .one_or_none()
        )
        persisted_authorization = (
            connection.execute(
                select(metadata_write_authorizations).where(
                    metadata_write_authorizations.c.id == str(authorization.id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            persisted_run is None
            or dict(persisted_run) != _run_row(run)
            or persisted_authorization is None
            or dict(persisted_authorization) != _authorization_row(authorization)
        ):
            raise MetadataWriteStoreError("metadata write persisted binding differs")

    @staticmethod
    def _require_latest_status(
        connection: Any,
        run: MetadataWriteExecutionRun,
        allowed: frozenset[MetadataWriteRunStatus],
    ) -> MetadataWriteRunStatus:
        row = connection.execute(
            select(metadata_write_events.c.status)
            .where(metadata_write_events.c.run_id == str(run.id))
            .order_by(metadata_write_events.c.sequence_no.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            raise MetadataWriteStoreError("metadata write CREATED event is missing")
        status = MetadataWriteRunStatus(str(row.status))
        if status not in allowed:
            raise MetadataWriteStoreError("metadata write run status is unavailable")
        return status

    @staticmethod
    def _require_backend_binding(
        connection: Any,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        *,
        checked_at: datetime,
    ) -> MetadataWriteBackendBinding:
        row = (
            connection.execute(
                select(metadata_write_backend_bindings).where(
                    metadata_write_backend_bindings.c.run_id == str(run.id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise MetadataWriteStoreError("metadata write backend binding is missing")
        binding = _backend_binding_from_row(row)
        if (
            binding.run_id != run.id
            or binding.bound_at < run.created_at
            or not authorization.authorized_at <= binding.bound_at < authorization.expires_at
            or binding.bound_at > checked_at
        ):
            raise MetadataWriteStoreError("metadata write backend binding differs")
        return binding

    @staticmethod
    def _source_snapshot(
        connection: Any,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        *,
        require_current_file: bool,
    ) -> MetadataWriteSourceSnapshot:
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
                    schema.file_observations.c.relative_path.label("observation_relative_path"),
                    schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                    schema.file_observations.c.modified_at.label("observation_modified_at"),
                )
                .select_from(
                    schema.file_records.join(
                        schema.file_observations,
                        schema.file_observations.c.file_id == schema.file_records.c.id,
                    )
                )
                .where(
                    schema.file_records.c.id == str(authorization.file_id),
                    schema.file_observations.c.id == str(authorization.observation_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        candidate = plan.candidate
        if row is None:
            raise MetadataWriteStoreError("metadata write source binding is missing")
        observation_modified_at = _required_datetime(row["observation_modified_at"])
        observation_path = str(row["observation_relative_path"])
        if (
            str(row["scan_root_id"]) != str(run.scan_root_id)
            or str(row["media_type"]) != "EBOOK"
            or str(row["observation_file_id"]) != str(run.file_id)
            or int(row["observation_size_bytes"]) != authorization.source_size_bytes
            or observation_modified_at != candidate.expected_modified_at
            or (
                require_current_file
                and (
                    str(row["presence_state"]) != PresenceState.PRESENT.value
                    or str(row["file_relative_path"]) != observation_path
                    or int(row["file_size_bytes"]) != authorization.source_size_bytes
                    or _required_datetime(row["file_modified_at"]) != candidate.expected_modified_at
                )
            )
        ):
            raise MetadataWriteStoreError("metadata write source binding differs")
        return MetadataWriteSourceSnapshot(
            run_id=run.id,
            authorization_id=authorization.id,
            plan_id=plan.id,
            scan_root_id=run.scan_root_id,
            file_id=run.file_id,
            observation_id=authorization.observation_id,
            relative_path=observation_path,
            source_sha256=authorization.source_sha256,
            source_size_bytes=authorization.source_size_bytes,
            expected_modified_at=observation_modified_at,
        )

    @staticmethod
    def _require_run_material(
        value: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if (
            not isinstance(value, MetadataWriteExecutionRun)
            or not isinstance(authorization, MetadataWriteAuthorizationSnapshot)
            or value.authorization_id != authorization.id
            or value.authorization_content_hash != authorization.content_hash
            or value.plan_id != authorization.plan_id
            or value.scan_root_id != authorization.scan_root_id
            or value.file_id != authorization.file_id
            or value.metadata_write_capability_id != authorization.metadata_write_capability_id
            or not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            or lease.owner_run_id != value.id
            or lease.scan_root_id != value.scan_root_id
            or lease.fence_epoch != value.initial_fence_epoch
            or lease.acquired_at > value.created_at
            or lease.lease_expires_at <= value.created_at
        ):
            raise MetadataWriteStoreError("metadata write run binding differs")

    @staticmethod
    def _require_created_event(
        connection: Any,
        value: MetadataWriteExecutionRun,
        confirmation_digest: str,
    ) -> None:
        event = (
            connection.execute(
                select(metadata_write_events).where(
                    metadata_write_events.c.run_id == str(value.id),
                    metadata_write_events.c.sequence_no == 1,
                )
            )
            .mappings()
            .one_or_none()
        )
        expected = {
            "run_id": str(value.id),
            "sequence_no": 1,
            "status": MetadataWriteRunStatus.CREATED.value,
            "occurred_at": datetime_to_db(value.created_at),
            "fence_epoch": value.initial_fence_epoch,
            "finding_code": None,
            "confirmation_digest": confirmation_digest,
        }
        if event is None or dict(event) != expected:
            raise MetadataWriteStoreError("metadata write CREATED event differs")


def _authorization_row(value: MetadataWriteAuthorizationSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "preparation_id": str(value.preparation_id),
        "preparation_content_hash": value.preparation_content_hash,
        "preparation_owner_id": str(value.preparation_owner_id),
        "preparation_fence_epoch": value.preparation_fence_epoch,
        "plan_id": str(value.plan_id),
        "plan_content_hash": value.plan_content_hash,
        "scan_root_id": str(value.scan_root_id),
        "file_id": str(value.file_id),
        "observation_id": str(value.observation_id),
        "source_sha256": value.source_sha256,
        "source_size_bytes": value.source_size_bytes,
        "expected_output_sha256": value.expected_output_sha256,
        "expected_output_size_bytes": value.expected_output_size_bytes,
        "metadata_write_capability_id": str(value.metadata_write_capability_id),
        "dcterms_modified": value.dcterms_modified,
        "authorized_at": datetime_to_db(value.authorized_at),
        "prepared_at": datetime_to_db(value.prepared_at),
        "expires_at": datetime_to_db(value.expires_at),
        "metadata_tool_version": value.metadata_tool_version,
        "epubcheck_tool_version": value.epubcheck_tool_version,
        "text_tool_version": value.text_tool_version,
        "cover_tool_version": value.cover_tool_version,
        "validator_set_fingerprint": value.validator_set_fingerprint,
        "writer_profile": value.writer_profile,
        "patcher_version": value.patcher_version,
        "staging_profile": value.staging_profile,
        "validation_profile": value.validation_profile,
        "validator_set": value.validator_set,
        "content_hash": value.content_hash,
    }


def _authorization_from_row(row: RowMapping) -> MetadataWriteAuthorizationSnapshot:
    return MetadataWriteAuthorizationSnapshot(
        id=EntityId.parse(str(row["id"])),
        preparation_id=EntityId.parse(str(row["preparation_id"])),
        preparation_content_hash=str(row["preparation_content_hash"]),
        preparation_owner_id=EntityId.parse(str(row["preparation_owner_id"])),
        preparation_fence_epoch=int(row["preparation_fence_epoch"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        plan_content_hash=str(row["plan_content_hash"]),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        source_sha256=str(row["source_sha256"]),
        source_size_bytes=int(row["source_size_bytes"]),
        expected_output_sha256=str(row["expected_output_sha256"]),
        expected_output_size_bytes=int(row["expected_output_size_bytes"]),
        metadata_write_capability_id=EntityId.parse(str(row["metadata_write_capability_id"])),
        dcterms_modified=str(row["dcterms_modified"]),
        authorized_at=_required_datetime(row["authorized_at"]),
        prepared_at=_required_datetime(row["prepared_at"]),
        expires_at=_required_datetime(row["expires_at"]),
        metadata_tool_version=str(row["metadata_tool_version"]),
        epubcheck_tool_version=str(row["epubcheck_tool_version"]),
        text_tool_version=str(row["text_tool_version"]),
        cover_tool_version=str(row["cover_tool_version"]),
        validator_set_fingerprint=str(row["validator_set_fingerprint"]),
        writer_profile=str(row["writer_profile"]),
        patcher_version=str(row["patcher_version"]),
        staging_profile=str(row["staging_profile"]),
        validation_profile=str(row["validation_profile"]),
        validator_set=str(row["validator_set"]),
        content_hash=str(row["content_hash"]),
        profile=str(row["profile"]),
    )


def _run_row(value: MetadataWriteExecutionRun) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "authorization_id": str(value.authorization_id),
        "authorization_content_hash": value.authorization_content_hash,
        "plan_id": str(value.plan_id),
        "scan_root_id": str(value.scan_root_id),
        "file_id": str(value.file_id),
        "metadata_write_capability_id": str(value.metadata_write_capability_id),
        "initial_fence_epoch": value.initial_fence_epoch,
        "created_at": datetime_to_db(value.created_at),
        "writer_profile": value.writer_profile,
    }


def _run_from_row(row: RowMapping) -> MetadataWriteExecutionRun:
    return MetadataWriteExecutionRun(
        id=EntityId.parse(str(row["id"])),
        authorization_id=EntityId.parse(str(row["authorization_id"])),
        authorization_content_hash=str(row["authorization_content_hash"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        metadata_write_capability_id=EntityId.parse(str(row["metadata_write_capability_id"])),
        initial_fence_epoch=int(row["initial_fence_epoch"]),
        created_at=_required_datetime(row["created_at"]),
        writer_profile=str(row["writer_profile"]),
        profile=str(row["profile"]),
    )


def _backend_binding_row(value: MetadataWriteBackendBinding) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "backend_profile": value.backend_profile,
        "conformance_profile": value.conformance_profile,
        "bound_at": datetime_to_db(value.bound_at),
    }


def _backend_binding_from_row(row: RowMapping) -> MetadataWriteBackendBinding:
    return MetadataWriteBackendBinding(
        run_id=EntityId.parse(str(row["run_id"])),
        backend_profile=str(row["backend_profile"]),
        conformance_profile=str(row["conformance_profile"]),
        bound_at=_required_datetime(row["bound_at"]),
    )


def _reconciliation_row(
    value: MetadataWriteReconciliationSnapshot,
) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "profile": value.profile,
        "authorization_id": str(value.authorization_id),
        "authorization_content_hash": value.authorization_content_hash,
        "outcome_status": value.outcome.value,
        "scan_run_id": str(value.scan_run_id),
        "observation_id": str(value.observation_id),
        "collection_state_snapshot_id": str(value.collection_state_snapshot_id),
        "collection_state_content_digest": value.collection_state_content_digest,
        "physical_confirmation_digest": value.physical_confirmation_digest,
        "reconciled_at": datetime_to_db(value.reconciled_at),
        "content_hash": value.content_hash,
    }


def _reconciliation_from_row(
    row: RowMapping,
) -> MetadataWriteReconciliationSnapshot:
    return MetadataWriteReconciliationSnapshot(
        run_id=EntityId.parse(str(row["run_id"])),
        authorization_id=EntityId.parse(str(row["authorization_id"])),
        authorization_content_hash=str(row["authorization_content_hash"]),
        outcome=MetadataWriteReconciliationOutcome(str(row["outcome_status"])),
        scan_run_id=EntityId.parse(str(row["scan_run_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        collection_state_snapshot_id=EntityId.parse(str(row["collection_state_snapshot_id"])),
        collection_state_content_digest=str(row["collection_state_content_digest"]),
        physical_confirmation_digest=str(row["physical_confirmation_digest"]),
        reconciled_at=_required_datetime(row["reconciled_at"]),
        content_hash=str(row["content_hash"]),
        profile=str(row["profile"]),
    )


def _event_row(value: MetadataWriteExecutionEvent) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "sequence_no": value.sequence_no,
        "status": value.status.value,
        "occurred_at": datetime_to_db(value.occurred_at),
        "fence_epoch": value.fence_epoch,
        "finding_code": value.finding_code,
        "confirmation_digest": value.confirmation_digest,
    }


def _event_from_row(row: RowMapping) -> MetadataWriteExecutionEvent:
    return MetadataWriteExecutionEvent(
        run_id=EntityId.parse(str(row["run_id"])),
        sequence_no=int(row["sequence_no"]),
        status=MetadataWriteRunStatus(str(row["status"])),
        occurred_at=_required_datetime(row["occurred_at"]),
        fence_epoch=int(row["fence_epoch"]),
        finding_code=(None if row["finding_code"] is None else str(row["finding_code"])),
        confirmation_digest=(
            None if row["confirmation_digest"] is None else str(row["confirmation_digest"])
        ),
    )


def _transition_allowed(
    previous: MetadataWriteRunStatus,
    current: MetadataWriteRunStatus,
    *,
    exchange_recorded: bool,
) -> bool:
    if current not in _NEXT.get(previous, frozenset()):
        return False
    return not (
        previous in _RECOVERABLE_FAILURES
        and current in _RECOVERY_OUTCOMES
        and not exchange_recorded
    )


def _status_events_are_valid(
    events: tuple[MetadataWriteStatusEventSnapshot, ...],
) -> bool:
    exchange_recorded = events[0].status is MetadataWriteRunStatus.EXCHANGED
    for previous, current in zip(events, events[1:], strict=False):
        if (
            not _transition_allowed(
                previous.status,
                current.status,
                exchange_recorded=exchange_recorded,
            )
            or current.occurred_at < previous.occurred_at
        ):
            return False
        exchange_recorded = exchange_recorded or current.status is MetadataWriteRunStatus.EXCHANGED
    return True


def _required_datetime(value: object) -> datetime:
    decoded = datetime_from_db(str(value))
    if decoded is None or decoded.tzinfo is None or decoded.utcoffset() is None:
        raise MetadataWriteStoreError("metadata write timestamp is missing")
    return decoded.astimezone(UTC)


__all__ = [
    "MetadataWriteBackendBinding",
    "MetadataWriteSourceSnapshot",
    "MetadataWriteStatusEventSnapshot",
    "MetadataWriteStatusReconciliationSnapshot",
    "MetadataWriteStatusSnapshot",
    "MetadataWriteStoreError",
    "SQLiteMetadataWriteStore",
]
