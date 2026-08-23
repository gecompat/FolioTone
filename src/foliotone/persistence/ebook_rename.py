"""Fenced insert-only persistence for ADR-0066 e-book rename authority."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, TypeVar

from sqlalchemy import Engine, func, insert, select
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from foliotone.core import (
    EntityId,
    EntityKind,
    FileChangeState,
    PresenceState,
    ScanRunStatus,
)
from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.ebook_rename.authority import (
    MAX_EBOOK_RENAME_EVENTS,
    EbookRenameAuthorizationSnapshot,
    EbookRenameBackendBinding,
    EbookRenameCapabilityProbeSnapshot,
    EbookRenameExecutionEvent,
    EbookRenameExecutionRun,
    EbookRenamePreparationSnapshot,
    EbookRenameRunStatus,
    ebook_rename_dependencies_fingerprint,
    ebook_rename_locator_digest,
    validate_ebook_rename_event_history,
)
from foliotone.ebook_rename.capabilities import ResolvedEbookRenameCapability
from foliotone.ebook_rename.dependency_scopes import (
    ResolvedEbookRenameDependencyScope,
    ebook_rename_dependency_scope_material_fingerprint,
)
from foliotone.ebook_rename.reconciliation import (
    EbookRenameReconciliationOutcome,
    EbookRenameReconciliationSnapshot,
)
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.collection_state_schema import (
    collection_state_items,
    collection_state_snapshots,
)
from foliotone.persistence.ebook_operation_recipe import (
    EbookOperationRecipeStoreError,
    SQLiteEbookOperationRecipeStore,
)
from foliotone.persistence.ebook_rename_schema import (
    ebook_rename_authorizations,
    ebook_rename_backend_bindings,
    ebook_rename_capability_probes,
    ebook_rename_events,
    ebook_rename_preparations,
    ebook_rename_reconciliations,
    ebook_rename_runs,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.persistence.w2_schema import file_scan_events


class EbookRenameStoreError(RuntimeError):
    """A path-free lineage, fence, replay, or journal invariant failed."""


_T = TypeVar("_T")

_RECOVERY_SOURCE_STATUSES = frozenset(
    {
        EbookRenameRunStatus.PREPARED,
        EbookRenameRunStatus.RELOCATED,
        EbookRenameRunStatus.IMMEDIATE_VERIFIED,
        EbookRenameRunStatus.RECOVERY_RELOCATED,
        EbookRenameRunStatus.RECOVERY_VERIFIED,
        EbookRenameRunStatus.SCAN_HANDOFF,
    }
)


@dataclass(frozen=True, slots=True)
class EbookRenameStatusEventSnapshot:
    """Only journal material allowed in the standard status projection."""

    sequence_no: int
    status: EbookRenameRunStatus
    occurred_at: datetime
    finding_code: str | None


@dataclass(frozen=True, slots=True)
class EbookRenameStatusReconciliationSnapshot:
    """Only opaque reconciliation material safe for standard status output."""

    outcome: EbookRenameReconciliationOutcome
    scan_run_id: EntityId
    source_file_id: EntityId
    source_observation_id: EntityId | None
    target_file_id: EntityId | None
    target_observation_id: EntityId | None
    collection_state_snapshot_id: EntityId
    reconciled_at: datetime


@dataclass(frozen=True, slots=True)
class EbookRenameStatusSnapshot:
    """Bounded locator-, hash-, attribute-, capability-, and fence-free state."""

    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    ebook_rename_capability_id: EntityId
    probe_id: EntityId
    backend_profile: str
    run_profile: str
    authorization_profile: str
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    events: tuple[EbookRenameStatusEventSnapshot, ...]
    reconciliation: EbookRenameStatusReconciliationSnapshot | None = None

    @property
    def status(self) -> EbookRenameRunStatus:
        return self.events[-1].status


@dataclass(frozen=True, slots=True)
class EbookRenameSourceSnapshot:
    """Private persistence-derived locators for one exact authorized run."""

    run_id: EntityId
    authorization_id: EntityId
    preparation_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    source_file_id: EntityId
    source_relative_locator: str = field(repr=False)
    target_relative_locator: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.run_id,
                self.authorization_id,
                self.preparation_id,
                self.plan_id,
                self.scan_root_id,
                self.source_file_id,
            )
        ):
            raise EbookRenameStoreError("e-book rename source binding is invalid")
        try:
            source = PurePosixPath(self.source_relative_locator)
            target = PurePosixPath(self.target_relative_locator)
            ebook_rename_locator_digest(
                self.scan_root_id,
                self.source_relative_locator,
                target=False,
            )
            ebook_rename_locator_digest(
                self.scan_root_id,
                self.target_relative_locator,
                target=True,
            )
        except (TypeError, ValueError):
            raise EbookRenameStoreError("e-book rename source binding is invalid") from None
        if (
            source.parent != target.parent
            or source.name == target.name
            or self.source_relative_locator == self.target_relative_locator
        ):
            raise EbookRenameStoreError("e-book rename source binding is invalid")


@contextmanager
def _transaction(engine: Engine) -> Iterator[Connection]:
    try:
        with engine.begin() as connection:
            yield connection
    except SQLAlchemyError:
        raise EbookRenameStoreError("e-book rename database transaction failed") from None


@contextmanager
def _connection(engine: Engine) -> Iterator[Connection]:
    try:
        with engine.connect() as connection:
            yield connection
    except SQLAlchemyError:
        raise EbookRenameStoreError("e-book rename database read failed") from None


class SQLiteEbookRenameStore:
    """Persist successful probes and one-use fence-bound rename journals."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_probe(
        self,
        value: EbookRenameCapabilityProbeSnapshot,
    ) -> EbookRenameCapabilityProbeSnapshot:
        """Persist only one already successful content-addressed probe."""

        if not isinstance(value, EbookRenameCapabilityProbeSnapshot):
            raise EbookRenameStoreError("e-book rename probe is invalid")
        row = _probe_row(value)
        with _transaction(self._engine) as connection:
            connection.execute(
                insert(ebook_rename_capability_probes)
                .values(**row)
                .prefix_with("OR IGNORE")
            )
            persisted = (
                connection.execute(
                    select(ebook_rename_capability_probes).where(
                        ebook_rename_capability_probes.c.id == str(value.id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if persisted is None or dict(persisted) != row:
                raise EbookRenameStoreError("e-book rename probe retry differs")
            return _probe_from_row(persisted)

    def require_historical_target_absence(
        self,
        plan: EbookOperationRecipePlan,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> None:
        """Prove the reviewed target has no FileRecord history under a prep fence."""

        checked = _utc_timestamp(checked_at, "target absence timestamp")
        try:
            source = plan.candidate.sources[0]
            ebook_rename_dependencies_fingerprint(plan)
        except (AttributeError, IndexError, TypeError, ValueError, RuntimeError):
            raise EbookRenameStoreError("e-book rename target state is unavailable") from None
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION
            or lease.scan_root_id != source.scan_root_id
            or lease.acquired_at > checked
            or checked >= lease.lease_expires_at
        ):
            raise EbookRenameStoreError("e-book rename target state is unavailable")
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked,
                )
                SQLiteEbookOperationRecipeStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
                history = connection.execute(
                    select(func.count())
                    .select_from(schema.file_records)
                    .where(
                        schema.file_records.c.scan_root_id == str(source.scan_root_id),
                        schema.file_records.c.relative_path
                        == plan.candidate.target.relative_locator,
                    )
                ).scalar_one()
                if int(history) != 0:
                    raise EbookRenameStoreError("e-book rename target has history")
        except EbookRenameStoreError:
            raise
        except (EbookOperationRecipeStoreError, ScanRootWriteLeaseError, ValueError):
            raise EbookRenameStoreError("e-book rename target state is unavailable") from None

    def create_or_get_authorization(
        self,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        dependency_scope: ResolvedEbookRenameDependencyScope,
        lease: OwnedScanRootWriteLease,
        *,
        persisted_at: datetime,
    ) -> EbookRenameAuthorizationSnapshot:
        """Atomically revalidate and persist one preparation and authorization."""

        checked_at = _utc_timestamp(persisted_at, "authorization timestamp")
        self._require_authorization_material(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            dependency_scope,
            lease,
            checked_at,
        )
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked_at,
                )
                SQLiteEbookOperationRecipeStore(
                    self._engine
                ).require_current_approved_plan_in_transaction(connection, plan)
                self._require_current_source_and_target(connection, plan, preparation)
                self._require_probe(connection, probe)
                self._insert_or_require_exact(
                    connection,
                    ebook_rename_preparations,
                    "id",
                    str(preparation.id),
                    _preparation_row(preparation),
                    "e-book rename preparation retry differs",
                )
                existing = (
                    connection.execute(
                        select(ebook_rename_authorizations).where(
                            ebook_rename_authorizations.c.preparation_id
                            == str(preparation.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                expected = _authorization_row(authorization)
                if existing is not None:
                    if dict(existing) != expected:
                        raise EbookRenameStoreError(
                            "e-book rename preparation was already authorized"
                        )
                    return _authorization_from_row(existing)
                connection.execute(insert(ebook_rename_authorizations).values(**expected))
        except EbookRenameStoreError:
            raise
        except (EbookOperationRecipeStoreError, ScanRootWriteLeaseError, ValueError):
            raise EbookRenameStoreError(
                "e-book rename authorization could not be persisted"
            ) from None
        return authorization

    def create_run(
        self,
        run: EbookRenameExecutionRun,
        authorization: EbookRenameAuthorizationSnapshot,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        prepared_event: EbookRenameExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> EbookRenameExecutionRun:
        """Consume one authorization with its binding and PREPARED event atomically."""

        self._require_run_material(
            run,
            authorization,
            probe,
            binding,
            prepared_event,
            lease,
        )
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    run.created_at,
                )
                persisted_authorization = (
                    connection.execute(
                        select(ebook_rename_authorizations).where(
                            ebook_rename_authorizations.c.id == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    persisted_authorization is None
                    or dict(persisted_authorization) != _authorization_row(authorization)
                    or not authorization.authorized_at
                    <= run.created_at
                    < authorization.expires_at
                ):
                    raise EbookRenameStoreError(
                        "e-book rename authorization is unavailable"
                    )
                self._require_probe(connection, probe)
                existing = (
                    connection.execute(
                        select(ebook_rename_runs).where(
                            ebook_rename_runs.c.authorization_id
                            == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != _run_row(run):
                        raise EbookRenameStoreError(
                            "e-book rename authorization was already consumed"
                        )
                    self._require_binding(connection, binding)
                    self._require_event(connection, prepared_event)
                    return _run_from_row(existing)
                connection.execute(insert(ebook_rename_runs).values(**_run_row(run)))
                connection.execute(
                    insert(ebook_rename_backend_bindings).values(
                        **_backend_binding_row(binding)
                    )
                )
                connection.execute(
                    insert(ebook_rename_events).values(**_event_row(prepared_event))
                )
        except EbookRenameStoreError:
            raise
        except (ScanRootWriteLeaseError, ValueError):
            raise EbookRenameStoreError("e-book rename run could not be created") from None
        return run

    def require_execution_source(
        self,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> EbookRenameSourceSnapshot:
        """Return private locators only while every live execution gate is current."""

        return self._require_operation_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=checked_at,
            allowed_statuses=frozenset({EbookRenameRunStatus.PREPARED}),
            require_current_plan=True,
            require_active_authorization=True,
        )

    def require_recovery_source(
        self,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
    ) -> EbookRenameSourceSnapshot:
        """Return historical locators for exact-state recovery under a fresh fence."""

        return self._require_operation_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=checked_at,
            allowed_statuses=_RECOVERY_SOURCE_STATUSES,
            require_current_plan=False,
            require_active_authorization=False,
        )

    def _require_operation_source(
        self,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
        *,
        checked_at: datetime,
        allowed_statuses: frozenset[EbookRenameRunStatus],
        require_current_plan: bool,
        require_active_authorization: bool,
    ) -> EbookRenameSourceSnapshot:
        checked = _utc_timestamp(checked_at, "source check timestamp")
        self._require_active_run_lease(run, lease, checked)
        self._require_operation_bindings(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
        )
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    checked,
                )
                self._require_persisted_operation_material(
                    connection,
                    preparation,
                    authorization,
                    probe,
                    binding,
                    run,
                )
                latest = self._require_latest_status(connection, run)
                if latest not in allowed_statuses:
                    raise EbookRenameStoreError(
                        "e-book rename execution status is unavailable"
                    )
                if require_active_authorization and not (
                    authorization.authorized_at <= checked < authorization.expires_at
                ):
                    raise EbookRenameStoreError(
                        "e-book rename authorization is unavailable"
                    )
                recipe_store = SQLiteEbookOperationRecipeStore(self._engine)
                if require_current_plan:
                    recipe_store.require_current_approved_plan_in_transaction(
                        connection,
                        plan,
                    )
                    self._require_current_source_and_target(
                        connection,
                        plan,
                        preparation,
                    )
                else:
                    recipe_store.require_persisted_approved_plan_in_transaction(
                        connection,
                        plan,
                    )
                source = plan.candidate.sources[0]
                return EbookRenameSourceSnapshot(
                    run_id=run.id,
                    authorization_id=authorization.id,
                    preparation_id=preparation.id,
                    plan_id=plan.id,
                    scan_root_id=source.scan_root_id,
                    source_file_id=source.file_id,
                    source_relative_locator=source.relative_locator,
                    target_relative_locator=plan.candidate.target.relative_locator,
                )
        except EbookRenameStoreError:
            raise
        except (
            EbookOperationRecipeStoreError,
            ScanRootWriteLeaseError,
            TypeError,
            ValueError,
        ):
            raise EbookRenameStoreError(
                "e-book rename operation source is unavailable"
            ) from None

    def append_event(
        self,
        value: EbookRenameExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> EbookRenameExecutionEvent:
        """Append one valid next event under the currently held run fence."""

        if not isinstance(value, EbookRenameExecutionEvent):
            raise EbookRenameStoreError("e-book rename event is invalid")
        if value.status in {
            EbookRenameRunStatus.VERIFIED,
            EbookRenameRunStatus.RECOVERED,
        }:
            raise EbookRenameStoreError(
                "e-book rename terminal reconciliation event is reserved"
            )
        self._require_event_lease(value, lease)
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.occurred_at,
                )
                run_row = (
                    connection.execute(
                        select(ebook_rename_runs).where(
                            ebook_rename_runs.c.id == str(value.run_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if run_row is None or str(run_row["scan_root_id"]) != str(
                    lease.scan_root_id
                ):
                    raise EbookRenameStoreError("e-book rename run is unavailable")
                existing = (
                    connection.execute(
                        select(ebook_rename_events).where(
                            ebook_rename_events.c.run_id == str(value.run_id),
                            ebook_rename_events.c.sequence_no == value.sequence_no,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != _event_row(value):
                        raise EbookRenameStoreError("e-book rename event retry differs")
                    return _event_from_row(existing)
                rows = (
                    connection.execute(
                        select(ebook_rename_events)
                        .where(ebook_rename_events.c.run_id == str(value.run_id))
                        .order_by(ebook_rename_events.c.sequence_no)
                        .limit(MAX_EBOOK_RENAME_EVENTS + 1)
                    )
                    .mappings()
                    .all()
                )
                history = tuple(_event_from_row(row) for row in rows)
                validate_ebook_rename_event_history((*history, value))
                connection.execute(insert(ebook_rename_events).values(**_event_row(value)))
        except EbookRenameStoreError:
            raise
        except (ScanRootWriteLeaseError, ValueError):
            raise EbookRenameStoreError(
                "e-book rename event could not be appended"
            ) from None
        return value

    def get_probe(
        self,
        probe_id: EntityId,
    ) -> EbookRenameCapabilityProbeSnapshot | None:
        return self._read_one(
            ebook_rename_capability_probes,
            ebook_rename_capability_probes.c.id == str(probe_id),
            _probe_from_row,
        )

    def get_preparation(
        self,
        preparation_id: EntityId,
    ) -> EbookRenamePreparationSnapshot | None:
        return self._read_one(
            ebook_rename_preparations,
            ebook_rename_preparations.c.id == str(preparation_id),
            _preparation_from_row,
        )

    def get_authorization(
        self,
        authorization_id: EntityId,
    ) -> EbookRenameAuthorizationSnapshot | None:
        return self._read_one(
            ebook_rename_authorizations,
            ebook_rename_authorizations.c.id == str(authorization_id),
            _authorization_from_row,
        )

    def get_run(self, run_id: EntityId) -> EbookRenameExecutionRun | None:
        return self._read_one(
            ebook_rename_runs,
            ebook_rename_runs.c.id == str(run_id),
            _run_from_row,
        )

    def get_run_for_authorization(
        self,
        authorization_id: EntityId,
    ) -> EbookRenameExecutionRun | None:
        return self._read_one(
            ebook_rename_runs,
            ebook_rename_runs.c.authorization_id == str(authorization_id),
            _run_from_row,
        )

    def get_backend_binding(
        self,
        run_id: EntityId,
    ) -> EbookRenameBackendBinding | None:
        return self._read_one(
            ebook_rename_backend_bindings,
            ebook_rename_backend_bindings.c.run_id == str(run_id),
            _backend_binding_from_row,
        )

    def get_reconciliation(
        self,
        run_id: EntityId,
    ) -> EbookRenameReconciliationSnapshot | None:
        return self._read_one(
            ebook_rename_reconciliations,
            ebook_rename_reconciliations.c.run_id == str(run_id),
            _reconciliation_from_row,
        )

    def record_reconciliation(
        self,
        value: EbookRenameReconciliationSnapshot,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
    ) -> EbookRenameReconciliationSnapshot:
        """Persist one exact rescan binding and terminal event atomically."""

        if (
            not isinstance(value, EbookRenameReconciliationSnapshot)
            or value.run_id != run.id
            or value.authorization_id != authorization.id
            or value.authorization_content_hash != authorization.content_hash
            or value.preparation_id != preparation.id
            or value.preparation_content_hash != preparation.content_hash
            or value.source_file_id != run.source_file_id
            or value.source_before_observation_id != preparation.source_observation_id
            or value.expected_full_sha256 != preparation.source_full_sha256
            or value.expected_size_bytes != preparation.source_size_bytes
            or value.target_absence_fingerprint
            != preparation.target_absence_fingerprint
        ):
            raise EbookRenameStoreError("e-book rename reconciliation is invalid")
        self._require_active_run_lease(run, lease, value.reconciled_at)
        self._require_operation_bindings(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
        )
        terminal = EbookRenameRunStatus(value.outcome.value)
        row = _reconciliation_row(value)
        try:
            with _transaction(self._engine) as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.reconciled_at,
                )
                self._require_persisted_operation_material(
                    connection,
                    preparation,
                    authorization,
                    probe,
                    binding,
                    run,
                )
                SQLiteEbookOperationRecipeStore(
                    self._engine
                ).require_persisted_approved_plan_in_transaction(connection, plan)
                events = self._event_history_in_transaction(connection, run)
                latest = events[-1].status
                existing = (
                    connection.execute(
                        select(ebook_rename_reconciliations).where(
                            ebook_rename_reconciliations.c.run_id == str(run.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != row or latest is not terminal:
                        raise EbookRenameStoreError(
                            "e-book rename reconciliation retry differs"
                        )
                    return _reconciliation_from_row(existing)
                if latest is not EbookRenameRunStatus.SCAN_HANDOFF:
                    raise EbookRenameStoreError(
                        "e-book rename reconciliation status is unavailable"
                    )
                self._require_reconciliation_evidence(
                    connection,
                    value,
                    plan,
                    preparation,
                    run,
                )
                terminal_event = EbookRenameExecutionEvent(
                    run_id=run.id,
                    sequence_no=len(events) + 1,
                    status=terminal,
                    occurred_at=value.reconciled_at,
                    fence_epoch=lease.fence_epoch,
                    finding_code=(
                        "RECONCILIATION_VERIFIED"
                        if terminal is EbookRenameRunStatus.VERIFIED
                        else "RECONCILIATION_RECOVERED"
                    ),
                )
                validate_ebook_rename_event_history((*events, terminal_event))
                connection.execute(insert(ebook_rename_reconciliations).values(**row))
                connection.execute(insert(ebook_rename_events).values(**_event_row(terminal_event)))
        except EbookRenameStoreError:
            raise
        except (
            EbookOperationRecipeStoreError,
            IntegrityError,
            ScanRootWriteLeaseError,
            TypeError,
            ValueError,
        ):
            raise EbookRenameStoreError(
                "e-book rename reconciliation could not be persisted"
            ) from None
        return value

    def events_for_run(
        self,
        run_id: EntityId,
    ) -> tuple[EbookRenameExecutionEvent, ...]:
        try:
            with _connection(self._engine) as connection:
                rows = (
                    connection.execute(
                        select(ebook_rename_events)
                        .where(ebook_rename_events.c.run_id == str(run_id))
                        .order_by(ebook_rename_events.c.sequence_no)
                        .limit(MAX_EBOOK_RENAME_EVENTS + 1)
                    )
                    .mappings()
                    .all()
                )
                events = tuple(_event_from_row(row) for row in rows)
            validate_ebook_rename_event_history(events)
            return events
        except EbookRenameStoreError:
            raise
        except (TypeError, ValueError):
            raise EbookRenameStoreError("e-book rename journal is invalid") from None

    def read_status_snapshot(
        self,
        run_id: EntityId,
    ) -> EbookRenameStatusSnapshot | None:
        """Read only the fixed standard subset, never private binders."""

        try:
            with _connection(self._engine) as connection:
                row = (
                    connection.execute(
                        select(
                            ebook_rename_runs.c.id,
                            ebook_rename_runs.c.authorization_id,
                            ebook_rename_runs.c.plan_id,
                            ebook_rename_runs.c.scan_root_id,
                            ebook_rename_runs.c.ebook_rename_capability_id,
                            ebook_rename_runs.c.probe_id,
                            ebook_rename_runs.c.backend_profile,
                            ebook_rename_runs.c.profile.label("run_profile"),
                            ebook_rename_runs.c.created_at,
                            ebook_rename_authorizations.c.profile.label(
                                "authorization_profile"
                            ),
                            ebook_rename_authorizations.c.authorized_at,
                            ebook_rename_authorizations.c.expires_at,
                        )
                        .join(
                            ebook_rename_authorizations,
                            ebook_rename_runs.c.authorization_id
                            == ebook_rename_authorizations.c.id,
                        )
                        .where(ebook_rename_runs.c.id == str(run_id))
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                event_rows = (
                    connection.execute(
                        select(
                            ebook_rename_events.c.sequence_no,
                            ebook_rename_events.c.status,
                            ebook_rename_events.c.occurred_at,
                            ebook_rename_events.c.finding_code,
                        )
                        .where(ebook_rename_events.c.run_id == str(run_id))
                        .order_by(ebook_rename_events.c.sequence_no)
                        .limit(MAX_EBOOK_RENAME_EVENTS + 1)
                    )
                    .mappings()
                    .all()
                )
                reconciliation_row = (
                    connection.execute(
                        select(
                            ebook_rename_reconciliations.c.outcome_status,
                            ebook_rename_reconciliations.c.scan_run_id,
                            ebook_rename_reconciliations.c.source_file_id,
                            ebook_rename_reconciliations.c.source_observation_id,
                            ebook_rename_reconciliations.c.target_file_id,
                            ebook_rename_reconciliations.c.target_observation_id,
                            ebook_rename_reconciliations.c.collection_state_snapshot_id,
                            ebook_rename_reconciliations.c.reconciled_at,
                        ).where(ebook_rename_reconciliations.c.run_id == str(run_id))
                    )
                    .mappings()
                    .one_or_none()
                )
            events = tuple(
                EbookRenameStatusEventSnapshot(
                    sequence_no=int(event["sequence_no"]),
                    status=EbookRenameRunStatus(str(event["status"])),
                    occurred_at=_required_datetime(event["occurred_at"]),
                    finding_code=(
                        None
                        if event["finding_code"] is None
                        else str(event["finding_code"])
                    ),
                )
                for event in event_rows
            )
            _validate_public_events(EntityId.parse(str(row["id"])), events)
            reconciliation = (
                None
                if reconciliation_row is None
                else EbookRenameStatusReconciliationSnapshot(
                    outcome=EbookRenameReconciliationOutcome(
                        str(reconciliation_row["outcome_status"])
                    ),
                    scan_run_id=EntityId.parse(str(reconciliation_row["scan_run_id"])),
                    source_file_id=EntityId.parse(
                        str(reconciliation_row["source_file_id"])
                    ),
                    source_observation_id=(
                        None
                        if reconciliation_row["source_observation_id"] is None
                        else EntityId.parse(
                            str(reconciliation_row["source_observation_id"])
                        )
                    ),
                    target_file_id=(
                        None
                        if reconciliation_row["target_file_id"] is None
                        else EntityId.parse(str(reconciliation_row["target_file_id"]))
                    ),
                    target_observation_id=(
                        None
                        if reconciliation_row["target_observation_id"] is None
                        else EntityId.parse(
                            str(reconciliation_row["target_observation_id"])
                        )
                    ),
                    collection_state_snapshot_id=EntityId.parse(
                        str(reconciliation_row["collection_state_snapshot_id"])
                    ),
                    reconciled_at=_required_datetime(
                        reconciliation_row["reconciled_at"]
                    ),
                )
            )
            if (
                reconciliation is None
                and events[-1].status
                in {EbookRenameRunStatus.VERIFIED, EbookRenameRunStatus.RECOVERED}
            ) or (
                reconciliation is not None
                and events[-1].status.value != reconciliation.outcome.value
            ):
                raise EbookRenameStoreError(
                    "e-book rename status reconciliation is invalid"
                )
            return EbookRenameStatusSnapshot(
                run_id=EntityId.parse(str(row["id"])),
                authorization_id=EntityId.parse(str(row["authorization_id"])),
                plan_id=EntityId.parse(str(row["plan_id"])),
                scan_root_id=EntityId.parse(str(row["scan_root_id"])),
                ebook_rename_capability_id=EntityId.parse(
                    str(row["ebook_rename_capability_id"])
                ),
                probe_id=EntityId.parse(str(row["probe_id"])),
                backend_profile=str(row["backend_profile"]),
                run_profile=str(row["run_profile"]),
                authorization_profile=str(row["authorization_profile"]),
                created_at=_required_datetime(row["created_at"]),
                authorized_at=_required_datetime(row["authorized_at"]),
                expires_at=_required_datetime(row["expires_at"]),
                events=events,
                reconciliation=reconciliation,
            )
        except EbookRenameStoreError:
            raise
        except (TypeError, ValueError):
            raise EbookRenameStoreError("e-book rename status is invalid") from None

    def _read_one(
        self,
        table: Any,
        condition: Any,
        mapper: Callable[[RowMapping], _T],
    ) -> _T | None:
        try:
            with _connection(self._engine) as connection:
                row = (
                    connection.execute(select(table).where(condition))
                    .mappings()
                    .one_or_none()
                )
                return None if row is None else mapper(row)
        except EbookRenameStoreError:
            raise
        except (TypeError, ValueError):
            raise EbookRenameStoreError("e-book rename persisted state is invalid") from None

    @staticmethod
    def _insert_or_require_exact(
        connection: Connection,
        table: Any,
        key_name: str,
        key_value: str,
        row: dict[str, object],
        error_message: str,
    ) -> None:
        existing = (
            connection.execute(select(table).where(table.c[key_name] == key_value))
            .mappings()
            .one_or_none()
        )
        if existing is None:
            connection.execute(insert(table).values(**row))
        elif dict(existing) != row:
            raise EbookRenameStoreError(error_message)

    @staticmethod
    def _require_active_run_lease(
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
        checked_at: datetime,
    ) -> None:
        if (
            not isinstance(run, EbookRenameExecutionRun)
            or not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_RENAME_RUN
            or lease.owner_run_id != run.id
            or lease.scan_root_id != run.scan_root_id
            or lease.acquired_at > checked_at
            or checked_at < run.created_at
            or checked_at >= lease.lease_expires_at
        ):
            raise EbookRenameStoreError("e-book rename run lease is unavailable")

    @staticmethod
    def _require_operation_bindings(
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
    ) -> None:
        if (
            not isinstance(plan, EbookOperationRecipePlan)
            or not isinstance(preparation, EbookRenamePreparationSnapshot)
            or not isinstance(authorization, EbookRenameAuthorizationSnapshot)
            or not isinstance(capability, ResolvedEbookRenameCapability)
            or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
            or not isinstance(binding, EbookRenameBackendBinding)
            or not isinstance(run, EbookRenameExecutionRun)
        ):
            raise EbookRenameStoreError("e-book rename operation binding is invalid")
        try:
            source = plan.candidate.sources[0]
            source_locator_digest = ebook_rename_locator_digest(
                source.scan_root_id,
                source.relative_locator,
                target=False,
            )
            target_locator_digest = ebook_rename_locator_digest(
                source.scan_root_id,
                plan.candidate.target.relative_locator,
                target=True,
            )
            dependencies = ebook_rename_dependencies_fingerprint(plan)
        except (IndexError, TypeError, ValueError, RuntimeError):
            raise EbookRenameStoreError("e-book rename operation binding is invalid") from None
        if (
            preparation.plan_id != plan.id
            or preparation.plan_content_hash != plan.content_hash
            or preparation.candidate_id != plan.candidate.id
            or preparation.candidate_content_hash != plan.candidate.content_hash
            or preparation.scan_root_id != source.scan_root_id
            or preparation.source_scan_run_id != source.source_scan_run_id
            or preparation.source_file_id != source.file_id
            or preparation.source_observation_id != source.observation_id
            or preparation.source_locator_digest != source_locator_digest
            or preparation.target_locator_digest != target_locator_digest
            or preparation.source_format_label != source.format_label
            or preparation.source_full_sha256 != source.expected_full_sha256
            or preparation.source_size_bytes != source.expected_size_bytes
            or preparation.source_modified_at != source.expected_modified_at
            or preparation.dependencies_fingerprint != dependencies
            or preparation.ebook_rename_capability_id
            != capability.ebook_rename_capability_id
            or preparation.capability_configuration_fingerprint
            != capability.configuration_fingerprint
            or preparation.probe_id != probe.id
            or preparation.probe_content_hash != probe.content_hash
            or capability.scan_root_id != source.scan_root_id
            or probe.ebook_rename_capability_id
            != capability.ebook_rename_capability_id
            or probe.scan_root_id != capability.scan_root_id
            or probe.capability_configuration_fingerprint
            != capability.configuration_fingerprint
            or authorization.preparation_id != preparation.id
            or authorization.preparation_content_hash != preparation.content_hash
            or authorization.plan_id != preparation.plan_id
            or authorization.plan_content_hash != preparation.plan_content_hash
            or authorization.candidate_id != preparation.candidate_id
            or authorization.scan_root_id != preparation.scan_root_id
            or authorization.source_file_id != preparation.source_file_id
            or authorization.ebook_rename_capability_id
            != preparation.ebook_rename_capability_id
            or authorization.capability_configuration_fingerprint
            != preparation.capability_configuration_fingerprint
            or authorization.probe_id != preparation.probe_id
            or authorization.probe_content_hash != preparation.probe_content_hash
            or authorization.authorized_at != preparation.authorized_at
            or authorization.prepared_at != preparation.prepared_at
            or run.authorization_id != authorization.id
            or run.authorization_content_hash != authorization.content_hash
            or run.plan_id != authorization.plan_id
            or run.scan_root_id != authorization.scan_root_id
            or run.source_file_id != authorization.source_file_id
            or run.ebook_rename_capability_id
            != authorization.ebook_rename_capability_id
            or run.probe_id != authorization.probe_id
            or binding.run_id != run.id
            or binding.ebook_rename_capability_id
            != run.ebook_rename_capability_id
            or binding.capability_configuration_fingerprint
            != authorization.capability_configuration_fingerprint
            or binding.probe_id != run.probe_id
            or binding.probe_content_hash != probe.content_hash
            or binding.bound_at != run.created_at
        ):
            raise EbookRenameStoreError("e-book rename operation binding differs")

    @staticmethod
    def _require_persisted_operation_material(
        connection: Connection,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
    ) -> None:
        rows = (
            (
                ebook_rename_preparations,
                ebook_rename_preparations.c.id == str(preparation.id),
                _preparation_row(preparation),
            ),
            (
                ebook_rename_authorizations,
                ebook_rename_authorizations.c.id == str(authorization.id),
                _authorization_row(authorization),
            ),
            (
                ebook_rename_runs,
                ebook_rename_runs.c.id == str(run.id),
                _run_row(run),
            ),
            (
                ebook_rename_capability_probes,
                ebook_rename_capability_probes.c.id == str(probe.id),
                _probe_row(probe),
            ),
            (
                ebook_rename_backend_bindings,
                ebook_rename_backend_bindings.c.run_id == str(run.id),
                _backend_binding_row(binding),
            ),
        )
        for table, condition, expected in rows:
            row = connection.execute(select(table).where(condition)).mappings().one_or_none()
            if row is None or dict(row) != expected:
                raise EbookRenameStoreError(
                    "e-book rename persisted operation binding differs"
                )

    @staticmethod
    def _require_latest_status(
        connection: Connection,
        run: EbookRenameExecutionRun,
    ) -> EbookRenameRunStatus:
        return SQLiteEbookRenameStore._event_history_in_transaction(
            connection,
            run,
        )[-1].status

    @staticmethod
    def _event_history_in_transaction(
        connection: Connection,
        run: EbookRenameExecutionRun,
    ) -> tuple[EbookRenameExecutionEvent, ...]:
        rows = (
            connection.execute(
                select(ebook_rename_events)
                .where(ebook_rename_events.c.run_id == str(run.id))
                .order_by(ebook_rename_events.c.sequence_no)
                .limit(MAX_EBOOK_RENAME_EVENTS + 1)
            )
            .mappings()
            .all()
        )
        events = tuple(_event_from_row(row) for row in rows)
        try:
            validate_ebook_rename_event_history(events)
        except (TypeError, ValueError):
            raise EbookRenameStoreError("e-book rename journal is invalid") from None
        return events

    @staticmethod
    def _require_reconciliation_evidence(
        connection: Connection,
        value: EbookRenameReconciliationSnapshot,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        run: EbookRenameExecutionRun,
    ) -> None:
        source_locator = plan.candidate.sources[0].relative_locator
        target_locator = plan.candidate.target.relative_locator
        handoff = connection.execute(
            select(ebook_rename_events.c.occurred_at)
            .where(
                ebook_rename_events.c.run_id == str(run.id),
                ebook_rename_events.c.status == EbookRenameRunStatus.SCAN_HANDOFF.value,
            )
            .order_by(ebook_rename_events.c.sequence_no.desc())
            .limit(1)
        ).one_or_none()
        scan = (
            connection.execute(
                select(schema.scan_runs).where(
                    schema.scan_runs.c.id == str(value.scan_run_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        source_before = (
            connection.execute(
                select(schema.file_observations).where(
                    schema.file_observations.c.id
                    == str(value.source_before_observation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        source_record = (
            connection.execute(
                select(schema.file_records).where(
                    schema.file_records.c.id == str(value.source_file_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        source_events = tuple(
            connection.execute(
                select(file_scan_events).where(
                    file_scan_events.c.scan_run_id == str(value.scan_run_id),
                    file_scan_events.c.file_id == str(value.source_file_id),
                )
            ).mappings()
        )
        expected_item_file = (
            value.target_file_id
            if value.outcome is EbookRenameReconciliationOutcome.VERIFIED
            else value.source_file_id
        )
        expected_item_observation = (
            value.target_observation_id
            if value.outcome is EbookRenameReconciliationOutcome.VERIFIED
            else value.source_observation_id
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
                        collection_state_items.c.snapshot_id
                        == collection_state_snapshots.c.id,
                    )
                )
                .where(
                    collection_state_snapshots.c.id
                    == str(value.collection_state_snapshot_id),
                    collection_state_items.c.file_id == str(expected_item_file),
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            handoff is None
            or scan is None
            or source_before is None
            or source_record is None
            or len(source_events) != 1
            or collection is None
            or expected_item_observation is None
        ):
            raise EbookRenameStoreError(
                "e-book rename reconciliation evidence is unavailable"
            )
        handoff_at = _required_datetime(handoff.occurred_at)
        scan_started = _required_datetime(scan["started_at"])
        scan_completed = (
            None
            if scan["completed_at"] is None
            else _required_datetime(scan["completed_at"])
        )
        source_event = source_events[0]
        if (
            str(scan["scan_root_id"]) != str(run.scan_root_id)
            or str(scan["status"]) != ScanRunStatus.COMPLETED.value
            or scan_completed is None
            or scan_started <= handoff_at
            or scan_completed > value.reconciled_at
            or str(source_before["id"]) != str(preparation.source_observation_id)
            or str(source_before["file_id"]) != str(run.source_file_id)
            or str(source_before["scan_run_id"]) != str(preparation.source_scan_run_id)
            or str(source_before["relative_path"]) != source_locator
            or str(source_record["scan_root_id"]) != str(run.scan_root_id)
            or str(source_record["relative_path"]) != source_locator
            or int(source_record["size_bytes"]) != preparation.source_size_bytes
            or str(source_event["id"]) != str(value.source_scan_event_id)
            or str(source_event["scan_run_id"]) != str(value.scan_run_id)
            or str(source_event["file_id"]) != str(run.source_file_id)
            or str(collection["scan_root_id"]) != str(run.scan_root_id)
            or str(collection["source_scan_run_id"]) != str(value.scan_run_id)
            or str(collection["content_digest"])
            != value.collection_state_content_digest
            or _required_datetime(collection["created_at"]) > value.reconciled_at
            or str(collection["file_id"]) != str(expected_item_file)
            or str(collection["observation_id"]) != str(expected_item_observation)
            or int(collection["size_bytes"]) != preparation.source_size_bytes
        ):
            raise EbookRenameStoreError("e-book rename reconciliation evidence differs")

        if value.outcome is EbookRenameReconciliationOutcome.VERIFIED:
            target_record = (
                connection.execute(
                    select(schema.file_records).where(
                        schema.file_records.c.id == str(value.target_file_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            target_observations = tuple(
                connection.execute(
                    select(schema.file_observations).where(
                        schema.file_observations.c.scan_run_id == str(value.scan_run_id),
                        schema.file_observations.c.file_id == str(value.target_file_id),
                    )
                ).mappings()
            )
            target_events = tuple(
                connection.execute(
                    select(file_scan_events).where(
                        file_scan_events.c.scan_run_id == str(value.scan_run_id),
                        file_scan_events.c.file_id == str(value.target_file_id),
                    )
                ).mappings()
            )
            if target_record is None or len(target_observations) != 1 or len(target_events) != 1:
                raise EbookRenameStoreError(
                    "e-book rename reconciliation evidence is unavailable"
                )
            observation = target_observations[0]
            target_event = target_events[0]
            fingerprints = tuple(
                str(row.value)
                for row in connection.execute(
                    select(schema.fingerprints.c.value).where(
                        schema.fingerprints.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        schema.fingerprints.c.target_id
                        == str(value.target_observation_id),
                        schema.fingerprints.c.kind == "FILE_SHA256",
                        schema.fingerprints.c.algorithm == "sha256",
                        schema.fingerprints.c.algorithm_version == "1",
                        schema.fingerprints.c.tool_execution_id.is_(None),
                    )
                )
            )
            if (
                fingerprints != (preparation.source_full_sha256,)
                or str(source_record["presence_state"]) != PresenceState.MISSING.value
                or str(source_event["change_state"]) != FileChangeState.MISSING.value
                or str(source_event["previous_relative_path"]) != source_locator
                or source_event["current_relative_path"] is not None
                or str(target_record["id"]) != str(value.target_file_id)
                or str(target_record["scan_root_id"]) != str(run.scan_root_id)
                or str(target_record["relative_path"]) != target_locator
                or int(target_record["size_bytes"]) != preparation.source_size_bytes
                or str(target_record["presence_state"]) != PresenceState.PRESENT.value
                or str(observation["id"]) != str(value.target_observation_id)
                or str(observation["scan_run_id"]) != str(value.scan_run_id)
                or str(observation["file_id"]) != str(value.target_file_id)
                or str(observation["relative_path"]) != target_locator
                or int(observation["size_bytes"]) != preparation.source_size_bytes
                or str(target_event["id"]) != str(value.target_scan_event_id)
                or str(target_event["change_state"]) != FileChangeState.NEW.value
                or target_event["previous_relative_path"] is not None
                or str(target_event["current_relative_path"]) != target_locator
            ):
                raise EbookRenameStoreError(
                    "e-book rename forward reconciliation evidence differs"
                )
            return

        source_observations = tuple(
            connection.execute(
                select(schema.file_observations).where(
                    schema.file_observations.c.scan_run_id == str(value.scan_run_id),
                    schema.file_observations.c.file_id == str(value.source_file_id),
                )
            ).mappings()
        )
        target_history = connection.execute(
            select(func.count())
            .select_from(schema.file_records)
            .where(
                schema.file_records.c.scan_root_id == str(run.scan_root_id),
                schema.file_records.c.relative_path == target_locator,
            )
        ).scalar_one()
        if len(source_observations) != 1:
            raise EbookRenameStoreError(
                "e-book rename recovery reconciliation evidence is unavailable"
            )
        observation = source_observations[0]
        fingerprints = tuple(
            str(row.value)
            for row in connection.execute(
                select(schema.fingerprints.c.value).where(
                    schema.fingerprints.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                    schema.fingerprints.c.target_id == str(value.source_observation_id),
                    schema.fingerprints.c.kind == "FILE_SHA256",
                    schema.fingerprints.c.algorithm == "sha256",
                    schema.fingerprints.c.algorithm_version == "1",
                    schema.fingerprints.c.tool_execution_id.is_(None),
                )
            )
        )
        if (
            fingerprints != (preparation.source_full_sha256,)
            or int(target_history) != 0
            or str(source_record["presence_state"]) != PresenceState.PRESENT.value
            or str(source_event["change_state"])
            not in {FileChangeState.UNCHANGED.value, FileChangeState.REAPPEARED.value}
            or str(source_event["current_relative_path"]) != source_locator
            or str(observation["id"]) != str(value.source_observation_id)
            or str(observation["scan_run_id"]) != str(value.scan_run_id)
            or str(observation["file_id"]) != str(value.source_file_id)
            or str(observation["relative_path"]) != source_locator
            or int(observation["size_bytes"]) != preparation.source_size_bytes
        ):
            raise EbookRenameStoreError(
                "e-book rename recovery reconciliation evidence differs"
            )

    @staticmethod
    def _require_probe(
        connection: Connection,
        probe: EbookRenameCapabilityProbeSnapshot,
    ) -> None:
        row = (
            connection.execute(
                select(ebook_rename_capability_probes).where(
                    ebook_rename_capability_probes.c.id == str(probe.id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or dict(row) != _probe_row(probe):
            raise EbookRenameStoreError("e-book rename capability probe differs")

    @staticmethod
    def _require_current_source_and_target(
        connection: Connection,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
    ) -> None:
        source = plan.candidate.sources[0]
        latest_scan = connection.execute(
            select(schema.scan_runs.c.id)
            .where(
                schema.scan_runs.c.scan_root_id == str(source.scan_root_id),
                schema.scan_runs.c.status == ScanRunStatus.COMPLETED.value,
                schema.scan_runs.c.completed_at.is_not(None),
            )
            .order_by(
                schema.scan_runs.c.completed_at.desc(),
                schema.scan_runs.c.started_at.desc(),
                schema.scan_runs.c.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        fingerprint_filter = (
            schema.fingerprints.c.target_kind == EntityKind.FILE_OBSERVATION.value,
            schema.fingerprints.c.target_id == str(source.observation_id),
            schema.fingerprints.c.kind == "FILE_SHA256",
            schema.fingerprints.c.algorithm == "sha256",
            schema.fingerprints.c.algorithm_version == "1",
        )
        distinct_hashes = connection.execute(
            select(func.count(schema.fingerprints.c.value.distinct())).where(
                *fingerprint_filter
            )
        ).scalar_one()
        target_history = connection.execute(
            select(func.count())
            .select_from(schema.file_records)
            .where(
                schema.file_records.c.scan_root_id == str(source.scan_root_id),
                schema.file_records.c.relative_path
                == plan.candidate.target.relative_locator,
            )
        ).scalar_one()
        if (
            str(latest_scan) != str(source.source_scan_run_id)
            or int(distinct_hashes) != 1
            or int(target_history) != 0
            or preparation.source_full_sha256 != source.expected_full_sha256
        ):
            raise EbookRenameStoreError("e-book rename source or target state differs")

    @staticmethod
    def _require_authorization_material(
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        dependency_scope: ResolvedEbookRenameDependencyScope,
        lease: OwnedScanRootWriteLease,
        checked_at: datetime,
    ) -> None:
        if (
            not isinstance(preparation, EbookRenamePreparationSnapshot)
            or not isinstance(authorization, EbookRenameAuthorizationSnapshot)
            or not isinstance(capability, ResolvedEbookRenameCapability)
            or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
            or not isinstance(dependency_scope, ResolvedEbookRenameDependencyScope)
            or not isinstance(lease, OwnedScanRootWriteLease)
        ):
            raise EbookRenameStoreError("e-book rename authorization is invalid")
        try:
            source = plan.candidate.sources[0]
            scope_material = ebook_rename_dependency_scope_material_fingerprint(
                dependency_scope
            )
            dependencies_fingerprint = ebook_rename_dependencies_fingerprint(plan)
            source_locator_digest = ebook_rename_locator_digest(
                source.scan_root_id,
                source.relative_locator,
                target=False,
            )
            target_locator_digest = ebook_rename_locator_digest(
                source.scan_root_id,
                plan.candidate.target.relative_locator,
                target=True,
            )
        except (IndexError, TypeError, ValueError, RuntimeError):
            raise EbookRenameStoreError("e-book rename authorization is invalid") from None
        review = plan.review
        if (
            preparation.plan_id != plan.id
            or preparation.plan_content_hash != plan.content_hash
            or preparation.candidate_id != plan.candidate.id
            or preparation.candidate_content_hash != plan.candidate.content_hash
            or preparation.scan_root_id != source.scan_root_id
            or preparation.source_scan_run_id != source.source_scan_run_id
            or preparation.source_file_id != source.file_id
            or preparation.source_observation_id != source.observation_id
            or preparation.source_locator_digest != source_locator_digest
            or preparation.target_locator_digest != target_locator_digest
            or preparation.source_format_label != source.format_label
            or preparation.source_full_sha256 != source.expected_full_sha256
            or preparation.source_size_bytes != source.expected_size_bytes
            or preparation.source_modified_at != source.expected_modified_at
            or preparation.target_state_fingerprint
            != plan.candidate.target.target_state_fingerprint
            or preparation.dependencies_fingerprint != dependencies_fingerprint
            or preparation.review_item_id != review.review_item_id
            or preparation.review_decision_id != review.decision_id
            or preparation.review_decision_sequence_no != review.decision_sequence_no
            or preparation.review_evidence_fingerprint != review.evidence_fingerprint
            or preparation.review_candidate_set_fingerprint
            != review.candidate_set_fingerprint
            or preparation.dependency_scope_id
            != dependency_scope.dependency_scope_id
            or preparation.dependency_scope_material_fingerprint != scope_material
            or dependency_scope.scan_root_id != source.scan_root_id
            or preparation.ebook_rename_capability_id
            != capability.ebook_rename_capability_id
            or preparation.capability_configuration_fingerprint
            != capability.configuration_fingerprint
            or capability.scan_root_id != source.scan_root_id
            or preparation.probe_id != probe.id
            or preparation.probe_content_hash != probe.content_hash
            or probe.ebook_rename_capability_id
            != capability.ebook_rename_capability_id
            or probe.scan_root_id != source.scan_root_id
            or probe.capability_configuration_fingerprint
            != capability.configuration_fingerprint
            or authorization.preparation_id != preparation.id
            or authorization.preparation_content_hash != preparation.content_hash
            or authorization.plan_id != preparation.plan_id
            or authorization.plan_content_hash != preparation.plan_content_hash
            or authorization.candidate_id != preparation.candidate_id
            or authorization.scan_root_id != preparation.scan_root_id
            or authorization.source_file_id != preparation.source_file_id
            or authorization.ebook_rename_capability_id
            != preparation.ebook_rename_capability_id
            or authorization.capability_configuration_fingerprint
            != preparation.capability_configuration_fingerprint
            or authorization.probe_id != preparation.probe_id
            or authorization.probe_content_hash != preparation.probe_content_hash
            or authorization.authorized_at != preparation.authorized_at
            or authorization.prepared_at != preparation.prepared_at
            or lease.owner_kind
            is not ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION
            or lease.owner_run_id != preparation.preparation_owner_id
            or lease.scan_root_id != preparation.scan_root_id
            or lease.fence_epoch != preparation.preparation_fence_epoch
            or lease.acquired_at > preparation.authorized_at
            or checked_at < preparation.prepared_at
            or checked_at >= authorization.expires_at
            or checked_at >= lease.lease_expires_at
        ):
            raise EbookRenameStoreError("e-book rename authorization binding differs")

    @staticmethod
    def _require_run_material(
        run: EbookRenameExecutionRun,
        authorization: EbookRenameAuthorizationSnapshot,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        prepared_event: EbookRenameExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if (
            not isinstance(run, EbookRenameExecutionRun)
            or not isinstance(authorization, EbookRenameAuthorizationSnapshot)
            or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
            or not isinstance(binding, EbookRenameBackendBinding)
            or not isinstance(prepared_event, EbookRenameExecutionEvent)
            or not isinstance(lease, OwnedScanRootWriteLease)
            or run.authorization_id != authorization.id
            or run.authorization_content_hash != authorization.content_hash
            or run.plan_id != authorization.plan_id
            or run.scan_root_id != authorization.scan_root_id
            or run.source_file_id != authorization.source_file_id
            or run.ebook_rename_capability_id
            != authorization.ebook_rename_capability_id
            or run.probe_id != authorization.probe_id
            or probe.id != run.probe_id
            or probe.content_hash != authorization.probe_content_hash
            or binding.run_id != run.id
            or binding.ebook_rename_capability_id
            != run.ebook_rename_capability_id
            or binding.capability_configuration_fingerprint
            != authorization.capability_configuration_fingerprint
            or binding.probe_id != probe.id
            or binding.probe_content_hash != probe.content_hash
            or binding.bound_at != run.created_at
            or prepared_event.run_id != run.id
            or prepared_event.sequence_no != 1
            or prepared_event.status is not EbookRenameRunStatus.PREPARED
            or prepared_event.occurred_at != run.created_at
            or prepared_event.fence_epoch != run.initial_fence_epoch
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_RENAME_RUN
            or lease.owner_run_id != run.id
            or lease.scan_root_id != run.scan_root_id
            or lease.fence_epoch != run.initial_fence_epoch
            or lease.acquired_at > run.created_at
            or lease.lease_expires_at <= run.created_at
        ):
            raise EbookRenameStoreError("e-book rename run binding differs")

    @staticmethod
    def _require_event_lease(
        value: EbookRenameExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_RENAME_RUN
            or lease.owner_run_id != value.run_id
            or lease.fence_epoch != value.fence_epoch
            or value.occurred_at < lease.acquired_at
            or value.occurred_at >= lease.lease_expires_at
        ):
            raise EbookRenameStoreError("e-book rename event requires its run lease")

    @staticmethod
    def _require_binding(
        connection: Connection,
        value: EbookRenameBackendBinding,
    ) -> None:
        row = (
            connection.execute(
                select(ebook_rename_backend_bindings).where(
                    ebook_rename_backend_bindings.c.run_id == str(value.run_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or dict(row) != _backend_binding_row(value):
            raise EbookRenameStoreError("e-book rename backend binding differs")

    @staticmethod
    def _require_event(
        connection: Connection,
        value: EbookRenameExecutionEvent,
    ) -> None:
        row = (
            connection.execute(
                select(ebook_rename_events).where(
                    ebook_rename_events.c.run_id == str(value.run_id),
                    ebook_rename_events.c.sequence_no == value.sequence_no,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or dict(row) != _event_row(value):
            raise EbookRenameStoreError("e-book rename PREPARED event differs")


def _probe_row(value: EbookRenameCapabilityProbeSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "ebook_rename_capability_id": str(value.ebook_rename_capability_id),
        "scan_root_id": str(value.scan_root_id),
        "capability_configuration_fingerprint": (
            value.capability_configuration_fingerprint
        ),
        "filesystem_type": value.filesystem_type,
        "filesystem_identity_fingerprint": value.filesystem_identity_fingerprint,
        "kernel_release": value.kernel_release,
        "probed_at": datetime_to_db(value.probed_at),
        "content_hash": value.content_hash,
        "openat2_supported": int(value.openat2_supported),
        "renameat2_noreplace_supported": int(value.renameat2_noreplace_supported),
        "directory_fsync_supported": int(value.directory_fsync_supported),
        "root_probe_same_filesystem": int(value.root_probe_same_filesystem),
        "platform_profile": value.platform_profile,
        "backend_profile": value.backend_profile,
        "capability_profile": value.capability_profile,
    }


def _probe_from_row(row: RowMapping) -> EbookRenameCapabilityProbeSnapshot:
    return EbookRenameCapabilityProbeSnapshot(
        id=EntityId.parse(str(row["id"])),
        ebook_rename_capability_id=EntityId.parse(
            str(row["ebook_rename_capability_id"])
        ),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        capability_configuration_fingerprint=str(
            row["capability_configuration_fingerprint"]
        ),
        filesystem_type=str(row["filesystem_type"]),
        filesystem_identity_fingerprint=str(row["filesystem_identity_fingerprint"]),
        kernel_release=str(row["kernel_release"]),
        probed_at=_required_datetime(row["probed_at"]),
        content_hash=str(row["content_hash"]),
        openat2_supported=bool(row["openat2_supported"]),
        renameat2_noreplace_supported=bool(row["renameat2_noreplace_supported"]),
        directory_fsync_supported=bool(row["directory_fsync_supported"]),
        root_probe_same_filesystem=bool(row["root_probe_same_filesystem"]),
        platform_profile=str(row["platform_profile"]),
        backend_profile=str(row["backend_profile"]),
        capability_profile=str(row["capability_profile"]),
        profile=str(row["profile"]),
    )


def _preparation_row(value: EbookRenamePreparationSnapshot) -> dict[str, object]:
    fields: dict[str, object] = {
        "id": str(value.id),
        "profile": value.profile,
        "preparation_owner_id": str(value.preparation_owner_id),
        "preparation_fence_epoch": value.preparation_fence_epoch,
        "plan_id": str(value.plan_id),
        "plan_content_hash": value.plan_content_hash,
        "candidate_id": str(value.candidate_id),
        "candidate_content_hash": value.candidate_content_hash,
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "source_file_id": str(value.source_file_id),
        "source_observation_id": str(value.source_observation_id),
        "source_locator_digest": value.source_locator_digest,
        "target_locator_digest": value.target_locator_digest,
        "source_format_label": value.source_format_label,
        "source_full_sha256": value.source_full_sha256,
        "source_size_bytes": value.source_size_bytes,
        "source_modified_at": datetime_to_db(value.source_modified_at),
        "source_device": value.source_device,
        "source_inode": value.source_inode,
        "source_mode": value.source_mode,
        "source_uid": value.source_uid,
        "source_gid": value.source_gid,
        "source_link_count": value.source_link_count,
        "source_mtime_ns": value.source_mtime_ns,
        "source_xattr_fingerprint": value.source_xattr_fingerprint,
        "target_state_fingerprint": value.target_state_fingerprint,
        "target_absence_fingerprint": value.target_absence_fingerprint,
        "dependency_scope_id": str(value.dependency_scope_id),
        "dependency_scope_material_fingerprint": (
            value.dependency_scope_material_fingerprint
        ),
        "dependencies_fingerprint": value.dependencies_fingerprint,
        "review_item_id": str(value.review_item_id),
        "review_decision_id": str(value.review_decision_id),
        "review_decision_sequence_no": value.review_decision_sequence_no,
        "review_evidence_fingerprint": value.review_evidence_fingerprint,
        "review_candidate_set_fingerprint": value.review_candidate_set_fingerprint,
        "ebook_rename_capability_id": str(value.ebook_rename_capability_id),
        "capability_configuration_fingerprint": (
            value.capability_configuration_fingerprint
        ),
        "probe_id": str(value.probe_id),
        "probe_content_hash": value.probe_content_hash,
        "authorized_at": datetime_to_db(value.authorized_at),
        "prepared_at": datetime_to_db(value.prepared_at),
        "content_hash": value.content_hash,
        "backend_profile": value.backend_profile,
        "probe_profile": value.probe_profile,
    }
    return fields


def _preparation_from_row(row: RowMapping) -> EbookRenamePreparationSnapshot:
    return EbookRenamePreparationSnapshot(
        id=EntityId.parse(str(row["id"])),
        preparation_owner_id=EntityId.parse(str(row["preparation_owner_id"])),
        preparation_fence_epoch=int(row["preparation_fence_epoch"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        plan_content_hash=str(row["plan_content_hash"]),
        candidate_id=EntityId.parse(str(row["candidate_id"])),
        candidate_content_hash=str(row["candidate_content_hash"]),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])),
        source_file_id=EntityId.parse(str(row["source_file_id"])),
        source_observation_id=EntityId.parse(str(row["source_observation_id"])),
        source_locator_digest=str(row["source_locator_digest"]),
        target_locator_digest=str(row["target_locator_digest"]),
        source_format_label=str(row["source_format_label"]),
        source_full_sha256=str(row["source_full_sha256"]),
        source_size_bytes=int(row["source_size_bytes"]),
        source_modified_at=_required_datetime(row["source_modified_at"]),
        source_device=int(row["source_device"]),
        source_inode=int(row["source_inode"]),
        source_mode=int(row["source_mode"]),
        source_uid=int(row["source_uid"]),
        source_gid=int(row["source_gid"]),
        source_link_count=int(row["source_link_count"]),
        source_mtime_ns=int(row["source_mtime_ns"]),
        source_xattr_fingerprint=str(row["source_xattr_fingerprint"]),
        target_state_fingerprint=str(row["target_state_fingerprint"]),
        target_absence_fingerprint=str(row["target_absence_fingerprint"]),
        dependency_scope_id=EntityId.parse(str(row["dependency_scope_id"])),
        dependency_scope_material_fingerprint=str(
            row["dependency_scope_material_fingerprint"]
        ),
        dependencies_fingerprint=str(row["dependencies_fingerprint"]),
        review_item_id=EntityId.parse(str(row["review_item_id"])),
        review_decision_id=EntityId.parse(str(row["review_decision_id"])),
        review_decision_sequence_no=int(row["review_decision_sequence_no"]),
        review_evidence_fingerprint=str(row["review_evidence_fingerprint"]),
        review_candidate_set_fingerprint=str(
            row["review_candidate_set_fingerprint"]
        ),
        ebook_rename_capability_id=EntityId.parse(
            str(row["ebook_rename_capability_id"])
        ),
        capability_configuration_fingerprint=str(
            row["capability_configuration_fingerprint"]
        ),
        probe_id=EntityId.parse(str(row["probe_id"])),
        probe_content_hash=str(row["probe_content_hash"]),
        authorized_at=_required_datetime(row["authorized_at"]),
        prepared_at=_required_datetime(row["prepared_at"]),
        content_hash=str(row["content_hash"]),
        backend_profile=str(row["backend_profile"]),
        probe_profile=str(row["probe_profile"]),
        profile=str(row["profile"]),
    )


def _authorization_row(value: EbookRenameAuthorizationSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "preparation_id": str(value.preparation_id),
        "preparation_content_hash": value.preparation_content_hash,
        "plan_id": str(value.plan_id),
        "plan_content_hash": value.plan_content_hash,
        "candidate_id": str(value.candidate_id),
        "scan_root_id": str(value.scan_root_id),
        "source_file_id": str(value.source_file_id),
        "ebook_rename_capability_id": str(value.ebook_rename_capability_id),
        "capability_configuration_fingerprint": (
            value.capability_configuration_fingerprint
        ),
        "probe_id": str(value.probe_id),
        "probe_content_hash": value.probe_content_hash,
        "authorized_at": datetime_to_db(value.authorized_at),
        "prepared_at": datetime_to_db(value.prepared_at),
        "expires_at": datetime_to_db(value.expires_at),
        "content_hash": value.content_hash,
        "backend_profile": value.backend_profile,
        "probe_profile": value.probe_profile,
    }


def _authorization_from_row(row: RowMapping) -> EbookRenameAuthorizationSnapshot:
    return EbookRenameAuthorizationSnapshot(
        id=EntityId.parse(str(row["id"])),
        preparation_id=EntityId.parse(str(row["preparation_id"])),
        preparation_content_hash=str(row["preparation_content_hash"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        plan_content_hash=str(row["plan_content_hash"]),
        candidate_id=EntityId.parse(str(row["candidate_id"])),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        source_file_id=EntityId.parse(str(row["source_file_id"])),
        ebook_rename_capability_id=EntityId.parse(
            str(row["ebook_rename_capability_id"])
        ),
        capability_configuration_fingerprint=str(
            row["capability_configuration_fingerprint"]
        ),
        probe_id=EntityId.parse(str(row["probe_id"])),
        probe_content_hash=str(row["probe_content_hash"]),
        authorized_at=_required_datetime(row["authorized_at"]),
        prepared_at=_required_datetime(row["prepared_at"]),
        expires_at=_required_datetime(row["expires_at"]),
        content_hash=str(row["content_hash"]),
        backend_profile=str(row["backend_profile"]),
        probe_profile=str(row["probe_profile"]),
        profile=str(row["profile"]),
    )


def _run_row(value: EbookRenameExecutionRun) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "authorization_id": str(value.authorization_id),
        "authorization_content_hash": value.authorization_content_hash,
        "plan_id": str(value.plan_id),
        "scan_root_id": str(value.scan_root_id),
        "source_file_id": str(value.source_file_id),
        "ebook_rename_capability_id": str(value.ebook_rename_capability_id),
        "probe_id": str(value.probe_id),
        "initial_fence_epoch": value.initial_fence_epoch,
        "created_at": datetime_to_db(value.created_at),
        "backend_profile": value.backend_profile,
    }


def _run_from_row(row: RowMapping) -> EbookRenameExecutionRun:
    return EbookRenameExecutionRun(
        id=EntityId.parse(str(row["id"])),
        authorization_id=EntityId.parse(str(row["authorization_id"])),
        authorization_content_hash=str(row["authorization_content_hash"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        source_file_id=EntityId.parse(str(row["source_file_id"])),
        ebook_rename_capability_id=EntityId.parse(
            str(row["ebook_rename_capability_id"])
        ),
        probe_id=EntityId.parse(str(row["probe_id"])),
        initial_fence_epoch=int(row["initial_fence_epoch"]),
        created_at=_required_datetime(row["created_at"]),
        backend_profile=str(row["backend_profile"]),
        profile=str(row["profile"]),
    )


def _backend_binding_row(value: EbookRenameBackendBinding) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "ebook_rename_capability_id": str(value.ebook_rename_capability_id),
        "capability_configuration_fingerprint": (
            value.capability_configuration_fingerprint
        ),
        "probe_id": str(value.probe_id),
        "probe_content_hash": value.probe_content_hash,
        "bound_at": datetime_to_db(value.bound_at),
        "content_hash": value.content_hash,
        "backend_profile": value.backend_profile,
        "probe_profile": value.probe_profile,
    }


def _backend_binding_from_row(row: RowMapping) -> EbookRenameBackendBinding:
    return EbookRenameBackendBinding(
        run_id=EntityId.parse(str(row["run_id"])),
        ebook_rename_capability_id=EntityId.parse(
            str(row["ebook_rename_capability_id"])
        ),
        capability_configuration_fingerprint=str(
            row["capability_configuration_fingerprint"]
        ),
        probe_id=EntityId.parse(str(row["probe_id"])),
        probe_content_hash=str(row["probe_content_hash"]),
        bound_at=_required_datetime(row["bound_at"]),
        content_hash=str(row["content_hash"]),
        backend_profile=str(row["backend_profile"]),
        probe_profile=str(row["probe_profile"]),
    )


def _reconciliation_row(
    value: EbookRenameReconciliationSnapshot,
) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "profile": value.profile,
        "authorization_id": str(value.authorization_id),
        "authorization_content_hash": value.authorization_content_hash,
        "preparation_id": str(value.preparation_id),
        "preparation_content_hash": value.preparation_content_hash,
        "outcome_status": value.outcome.value,
        "scan_run_id": str(value.scan_run_id),
        "source_file_id": str(value.source_file_id),
        "source_before_observation_id": str(value.source_before_observation_id),
        "source_scan_event_id": str(value.source_scan_event_id),
        "source_observation_id": (
            None if value.source_observation_id is None else str(value.source_observation_id)
        ),
        "target_file_id": None if value.target_file_id is None else str(value.target_file_id),
        "target_observation_id": (
            None if value.target_observation_id is None else str(value.target_observation_id)
        ),
        "target_scan_event_id": (
            None if value.target_scan_event_id is None else str(value.target_scan_event_id)
        ),
        "collection_state_snapshot_id": str(value.collection_state_snapshot_id),
        "collection_state_content_digest": value.collection_state_content_digest,
        "expected_full_sha256": value.expected_full_sha256,
        "expected_size_bytes": value.expected_size_bytes,
        "target_absence_fingerprint": value.target_absence_fingerprint,
        "physical_confirmation_digest": value.physical_confirmation_digest,
        "reconciled_at": datetime_to_db(value.reconciled_at),
        "content_hash": value.content_hash,
    }


def _reconciliation_from_row(
    row: RowMapping,
) -> EbookRenameReconciliationSnapshot:
    return EbookRenameReconciliationSnapshot(
        run_id=EntityId.parse(str(row["run_id"])),
        authorization_id=EntityId.parse(str(row["authorization_id"])),
        authorization_content_hash=str(row["authorization_content_hash"]),
        preparation_id=EntityId.parse(str(row["preparation_id"])),
        preparation_content_hash=str(row["preparation_content_hash"]),
        outcome=EbookRenameReconciliationOutcome(str(row["outcome_status"])),
        scan_run_id=EntityId.parse(str(row["scan_run_id"])),
        source_file_id=EntityId.parse(str(row["source_file_id"])),
        source_before_observation_id=EntityId.parse(
            str(row["source_before_observation_id"])
        ),
        source_scan_event_id=EntityId.parse(str(row["source_scan_event_id"])),
        source_observation_id=(
            None
            if row["source_observation_id"] is None
            else EntityId.parse(str(row["source_observation_id"]))
        ),
        target_file_id=(
            None
            if row["target_file_id"] is None
            else EntityId.parse(str(row["target_file_id"]))
        ),
        target_observation_id=(
            None
            if row["target_observation_id"] is None
            else EntityId.parse(str(row["target_observation_id"]))
        ),
        target_scan_event_id=(
            None
            if row["target_scan_event_id"] is None
            else EntityId.parse(str(row["target_scan_event_id"]))
        ),
        collection_state_snapshot_id=EntityId.parse(
            str(row["collection_state_snapshot_id"])
        ),
        collection_state_content_digest=str(row["collection_state_content_digest"]),
        expected_full_sha256=str(row["expected_full_sha256"]),
        expected_size_bytes=int(row["expected_size_bytes"]),
        target_absence_fingerprint=str(row["target_absence_fingerprint"]),
        physical_confirmation_digest=str(row["physical_confirmation_digest"]),
        reconciled_at=_required_datetime(row["reconciled_at"]),
        content_hash=str(row["content_hash"]),
        profile=str(row["profile"]),
    )


def _event_row(value: EbookRenameExecutionEvent) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "sequence_no": value.sequence_no,
        "status": value.status.value,
        "occurred_at": datetime_to_db(value.occurred_at),
        "fence_epoch": value.fence_epoch,
        "finding_code": value.finding_code,
        "confirmation_digest": value.confirmation_digest,
    }


def _event_from_row(row: RowMapping) -> EbookRenameExecutionEvent:
    return EbookRenameExecutionEvent(
        run_id=EntityId.parse(str(row["run_id"])),
        sequence_no=int(row["sequence_no"]),
        status=EbookRenameRunStatus(str(row["status"])),
        occurred_at=_required_datetime(row["occurred_at"]),
        fence_epoch=int(row["fence_epoch"]),
        finding_code=(
            None if row["finding_code"] is None else str(row["finding_code"])
        ),
        confirmation_digest=(
            None
            if row["confirmation_digest"] is None
            else str(row["confirmation_digest"])
        ),
    )


def _validate_public_events(
    run_id: EntityId,
    events: tuple[EbookRenameStatusEventSnapshot, ...],
) -> None:
    projected = tuple(
        EbookRenameExecutionEvent(
            run_id=run_id,
            sequence_no=value.sequence_no,
            status=value.status,
            occurred_at=value.occurred_at,
            fence_epoch=1,
            finding_code=value.finding_code,
            confirmation_digest=("0" * 64 if value.sequence_no == 1 else None),
        )
        for value in events
    )
    validate_ebook_rename_event_history(projected)


def _required_datetime(value: object) -> datetime:
    return required_datetime_from_db(str(value)).astimezone(UTC)


def _utc_timestamp(value: object, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise EbookRenameStoreError(f"e-book rename {label} is invalid")
    return value.astimezone(UTC)


__all__ = [
    "EbookRenameSourceSnapshot",
    "EbookRenameStatusEventSnapshot",
    "EbookRenameStatusReconciliationSnapshot",
    "EbookRenameStatusSnapshot",
    "EbookRenameStoreError",
    "SQLiteEbookRenameStore",
]
