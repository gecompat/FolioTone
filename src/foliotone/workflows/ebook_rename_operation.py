"""Operational RN04 service for one bounded same-parent e-book rename."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NoReturn, Protocol

from sqlalchemy import Engine, select

from foliotone.collection_state import CollectionStateSnapshot
from foliotone.core import (
    EntityId,
    EntityKind,
    FileChangeState,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRunStatus,
)
from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.ebook_rename.authority import (
    MAX_EBOOK_RENAME_AUTHORIZATION_LIFETIME,
    EbookRenameAuthorizationSnapshot,
    EbookRenameBackendBinding,
    EbookRenameCapabilityProbeSnapshot,
    EbookRenameExecutionEvent,
    EbookRenameExecutionRun,
    EbookRenamePhysicalPreparationEvidence,
    EbookRenamePreparationSnapshot,
    EbookRenameRunStatus,
    build_ebook_rename_authorization,
    build_ebook_rename_backend_binding,
    build_ebook_rename_preparation,
    build_ebook_rename_run,
    ebook_rename_dependencies_fingerprint,
)
from foliotone.ebook_rename.capabilities import (
    EbookRenameCapabilityResolver,
    EbookRenameCapabilityUnavailable,
    ResolvedEbookRenameCapability,
)
from foliotone.ebook_rename.confirmation import (
    EbookRenameConfirmationError,
    ebook_rename_confirmation_digest,
    ebook_rename_confirmation_text,
)
from foliotone.ebook_rename.dependency_scopes import (
    EbookRenameDependencyScopeResolver,
    EbookRenameDependencyScopeUnavailable,
)
from foliotone.ebook_rename.executor import (
    MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING,
    EbookRenameExecutorError,
    EbookRenameExecutorErrorCode,
    EbookRenameFilesystemBackend,
    execute_ebook_file_rename,
    recover_ebook_file_rename,
    verify_ebook_file_rename_physical_state,
)
from foliotone.ebook_rename.linux_backend import (
    LinuxEbookRenameBackend,
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
)
from foliotone.ebook_rename.reconciliation import (
    EbookRenameReconciliationOutcome,
    EbookRenameReconciliationSnapshot,
    build_ebook_rename_reconciliation,
)
from foliotone.index import (
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import repository, schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.ebook_operation_recipe import (
    EbookOperationRecipeStoreError,
    SQLiteEbookOperationRecipeStore,
)
from foliotone.persistence.ebook_rename import (
    EbookRenameStoreError,
    SQLiteEbookRenameStore,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.persistence.w2_schema import file_scan_events
from foliotone.workflows.collection_state import CollectionStateBuildService
from foliotone.workflows.ebook_rename_planning import (
    EbookRenamePlanningError,
    EbookRenamePlanningService,
)

EBOOK_RENAME_OPERATOR_PROFILE = "ebook-file-rename-operator/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LEASE_DURATION = timedelta(minutes=30)
_MAX_RECONCILIATION_SCAN_CANDIDATES = 128


class EbookRenameOperatorErrorCode(StrEnum):
    PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    AUTHORIZATION_UNAVAILABLE = "AUTHORIZATION_UNAVAILABLE"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    RUN_UNAVAILABLE = "RUN_UNAVAILABLE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    TARGET_COLLISION = "TARGET_COLLISION"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    STALE = "STALE"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EbookRenameOperatorError(RuntimeError):
    """One fixed path-, hash-, attribute-, and fence-free operator failure."""

    def __init__(self, code: EbookRenameOperatorErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class EbookRenameAuthorizationResult:
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    capability_id: EntityId
    probe_id: EntityId
    authorized_at: datetime
    expires_at: datetime
    status: str = "AUTHORIZED"
    profile: str = EBOOK_RENAME_OPERATOR_PROFILE


@dataclass(frozen=True, slots=True)
class EbookRenameOperationResult:
    authorization_id: EntityId
    run_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    status: EbookRenameRunStatus
    scan_run_id: EntityId | None = None
    source_observation_id: EntityId | None = None
    target_observation_id: EntityId | None = None
    collection_state_snapshot_id: EntityId | None = None
    profile: str = EBOOK_RENAME_OPERATOR_PROFILE


@dataclass(frozen=True, slots=True)
class EbookRenameScanReconciliation:
    scan_run_id: EntityId
    source_scan_event_id: EntityId
    source_observation_id: EntityId | None
    target_file_id: EntityId | None
    target_observation_id: EntityId | None
    target_scan_event_id: EntityId | None
    collection_state: CollectionStateSnapshot


@dataclass(frozen=True, slots=True)
class _MatchedEbookRenameScan:
    scan_run_id: EntityId
    source_scan_event_id: EntityId
    source_observation_id: EntityId | None
    target_file_id: EntityId | None
    target_observation_id: EntityId | None
    target_scan_event_id: EntityId | None


class EbookRenameOperatorBackend(EbookRenameFilesystemBackend, Protocol):
    def probe(
        self,
        capability: ResolvedEbookRenameCapability,
        *,
        probed_at: datetime,
    ) -> EbookRenameCapabilityProbeSnapshot: ...

    def capture_preparation_evidence(
        self,
        *,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        plan: EbookOperationRecipePlan,
        target_historically_absent: bool,
        captured_at: datetime,
    ) -> EbookRenamePhysicalPreparationEvidence: ...


class EbookRenameReconciler(Protocol):
    def reconcile(
        self,
        *,
        run: EbookRenameExecutionRun,
        preparation: EbookRenamePreparationSnapshot,
        capability: ResolvedEbookRenameCapability,
        plan: EbookOperationRecipePlan,
        outcome: EbookRenameReconciliationOutcome,
        not_before: datetime,
    ) -> EbookRenameScanReconciliation: ...


class SQLiteEbookRenameReconciler:
    """Create or reuse one exact post-rename scan and CollectionState."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._clock = clock or _system_clock

    def reconcile(
        self,
        *,
        run: EbookRenameExecutionRun,
        preparation: EbookRenamePreparationSnapshot,
        capability: ResolvedEbookRenameCapability,
        plan: EbookOperationRecipePlan,
        outcome: EbookRenameReconciliationOutcome,
        not_before: datetime,
    ) -> EbookRenameScanReconciliation:
        candidate = self._latest_matching_scan(
            run,
            preparation,
            plan,
            outcome,
            not_before,
        )
        if candidate is None:
            scan_run_id = self._scan(run, capability)
            candidate = self._matching_evidence(
                scan_run_id,
                run,
                preparation,
                plan,
                outcome,
            )
        if candidate is None:
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        report = CollectionStateBuildService(self._engine).build(
            candidate.scan_run_id,
            _now(self._clock),
        )
        snapshot = report.snapshot
        if (
            snapshot.scan_root_id != run.scan_root_id
            or snapshot.source_scan_run_id != candidate.scan_run_id
        ):
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        return EbookRenameScanReconciliation(
            scan_run_id=candidate.scan_run_id,
            source_scan_event_id=candidate.source_scan_event_id,
            source_observation_id=candidate.source_observation_id,
            target_file_id=candidate.target_file_id,
            target_observation_id=candidate.target_observation_id,
            target_scan_event_id=candidate.target_scan_event_id,
            collection_state=snapshot,
        )

    def _scan(
        self,
        run: EbookRenameExecutionRun,
        capability: ResolvedEbookRenameCapability,
    ) -> EntityId:
        root = repository(self._engine, ScanRoot).get(run.scan_root_id)
        if (
            root is None
            or not root.enabled
            or root.media_type is not MediaType.EBOOK
            or capability.scan_root_id != root.id
        ):
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        scanner = IncrementalScanner(
            SQLiteIndexStore(self._engine),
            batch_size=500,
            hash_mode=HashMode.FULL,
            hash_workers=1,
            fingerprint_writer=FingerprintWriter(self._engine),
            clock=self._clock,
        )
        summary = scanner.scan(root, ScanRootBinding(capability.scan_root_directory))
        if summary.run.status is not ScanRunStatus.COMPLETED:
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        return summary.run.id

    def _latest_matching_scan(
        self,
        run: EbookRenameExecutionRun,
        preparation: EbookRenamePreparationSnapshot,
        plan: EbookOperationRecipePlan,
        outcome: EbookRenameReconciliationOutcome,
        not_before: datetime,
    ) -> _MatchedEbookRenameScan | None:
        with self._engine.connect() as connection:
            rows = tuple(
                connection.execute(
                    select(schema.scan_runs.c.id)
                    .where(
                        schema.scan_runs.c.scan_root_id == str(run.scan_root_id),
                        schema.scan_runs.c.status == ScanRunStatus.COMPLETED.value,
                        schema.scan_runs.c.started_at > datetime_to_db(not_before),
                    )
                    .order_by(
                        schema.scan_runs.c.started_at.desc(),
                        schema.scan_runs.c.id.desc(),
                    )
                    .limit(_MAX_RECONCILIATION_SCAN_CANDIDATES)
                )
            )
        for row in rows:
            candidate = self._matching_evidence(
                EntityId.parse(str(row.id)),
                run,
                preparation,
                plan,
                outcome,
            )
            if candidate is not None:
                return candidate
        return None

    def _matching_evidence(
        self,
        scan_run_id: EntityId,
        run: EbookRenameExecutionRun,
        preparation: EbookRenamePreparationSnapshot,
        plan: EbookOperationRecipePlan,
        outcome: EbookRenameReconciliationOutcome,
    ) -> _MatchedEbookRenameScan | None:
        source_locator = plan.candidate.sources[0].relative_locator
        target_locator = plan.candidate.target.relative_locator
        with self._engine.connect() as connection:
            source_record = (
                connection.execute(
                    select(schema.file_records).where(
                        schema.file_records.c.id == str(run.source_file_id),
                        schema.file_records.c.scan_root_id == str(run.scan_root_id),
                        schema.file_records.c.relative_path == source_locator,
                    )
                )
                .mappings()
                .one_or_none()
            )
            source_events = tuple(
                connection.execute(
                    select(file_scan_events).where(
                        file_scan_events.c.scan_run_id == str(scan_run_id),
                        file_scan_events.c.file_id == str(run.source_file_id),
                    )
                ).mappings()
            )
            if source_record is None or len(source_events) != 1:
                return None
            source_event = source_events[0]
            if outcome is EbookRenameReconciliationOutcome.VERIFIED:
                target_records = tuple(
                    connection.execute(
                        select(schema.file_records).where(
                            schema.file_records.c.scan_root_id == str(run.scan_root_id),
                            schema.file_records.c.relative_path == target_locator,
                            schema.file_records.c.presence_state
                            == PresenceState.PRESENT.value,
                        )
                    ).mappings()
                )
                if (
                    len(target_records) != 1
                    or str(source_record["presence_state"])
                    != PresenceState.MISSING.value
                    or str(source_event["change_state"]) != FileChangeState.MISSING.value
                ):
                    return None
                target = target_records[0]
                target_id = EntityId.parse(str(target["id"]))
                observations = tuple(
                    connection.execute(
                        select(schema.file_observations.c.id)
                        .select_from(
                            schema.file_observations.join(
                                schema.fingerprints,
                                schema.fingerprints.c.target_id
                                == schema.file_observations.c.id,
                            )
                        )
                        .where(
                            schema.file_observations.c.scan_run_id == str(scan_run_id),
                            schema.file_observations.c.file_id == str(target_id),
                            schema.file_observations.c.relative_path == target_locator,
                            schema.file_observations.c.size_bytes
                            == preparation.source_size_bytes,
                            schema.fingerprints.c.target_kind
                            == EntityKind.FILE_OBSERVATION.value,
                            schema.fingerprints.c.kind == "FILE_SHA256",
                            schema.fingerprints.c.algorithm == "sha256",
                            schema.fingerprints.c.algorithm_version == "1",
                            schema.fingerprints.c.value
                            == preparation.source_full_sha256,
                            schema.fingerprints.c.tool_execution_id.is_(None),
                        )
                    )
                )
                target_events = tuple(
                    connection.execute(
                        select(file_scan_events).where(
                            file_scan_events.c.scan_run_id == str(scan_run_id),
                            file_scan_events.c.file_id == str(target_id),
                            file_scan_events.c.change_state == FileChangeState.NEW.value,
                        )
                    ).mappings()
                )
                if len(observations) != 1 or len(target_events) != 1:
                    return None
                return _MatchedEbookRenameScan(
                    scan_run_id=scan_run_id,
                    source_scan_event_id=EntityId.parse(str(source_event["id"])),
                    source_observation_id=None,
                    target_file_id=target_id,
                    target_observation_id=EntityId.parse(str(observations[0].id)),
                    target_scan_event_id=EntityId.parse(str(target_events[0]["id"])),
                )

            target_history = connection.execute(
                select(schema.file_records.c.id).where(
                    schema.file_records.c.scan_root_id == str(run.scan_root_id),
                    schema.file_records.c.relative_path == target_locator,
                )
            ).first()
            observations = tuple(
                connection.execute(
                    select(schema.file_observations.c.id)
                    .select_from(
                        schema.file_observations.join(
                            schema.fingerprints,
                            schema.fingerprints.c.target_id
                            == schema.file_observations.c.id,
                        )
                    )
                    .where(
                        schema.file_observations.c.scan_run_id == str(scan_run_id),
                        schema.file_observations.c.file_id == str(run.source_file_id),
                        schema.file_observations.c.relative_path == source_locator,
                        schema.file_observations.c.size_bytes
                        == preparation.source_size_bytes,
                        schema.fingerprints.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        schema.fingerprints.c.kind == "FILE_SHA256",
                        schema.fingerprints.c.algorithm == "sha256",
                        schema.fingerprints.c.algorithm_version == "1",
                        schema.fingerprints.c.value == preparation.source_full_sha256,
                        schema.fingerprints.c.tool_execution_id.is_(None),
                    )
                )
            )
            if (
                target_history is not None
                or len(observations) != 1
                or str(source_record["presence_state"]) != PresenceState.PRESENT.value
                or str(source_event["change_state"])
                not in {FileChangeState.UNCHANGED.value, FileChangeState.REAPPEARED.value}
            ):
                return None
            return _MatchedEbookRenameScan(
                scan_run_id=scan_run_id,
                source_scan_event_id=EntityId.parse(str(source_event["id"])),
                source_observation_id=EntityId.parse(str(observations[0].id)),
                target_file_id=None,
                target_observation_id=None,
                target_scan_event_id=None,
            )


class EbookRenameOperatorService:
    """Authorize, execute, recover, and reconcile the exact ADR-0066 profile."""

    def __init__(
        self,
        engine: Engine,
        *,
        capability_resolver: EbookRenameCapabilityResolver | None = None,
        dependency_scope_resolver: EbookRenameDependencyScopeResolver | None = None,
        backend: EbookRenameOperatorBackend | None = None,
        reconciler: EbookRenameReconciler | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], EntityId] | None = None,
    ) -> None:
        self._engine = engine
        self._capabilities = capability_resolver or EbookRenameCapabilityResolver()
        self._dependency_scopes = (
            dependency_scope_resolver or EbookRenameDependencyScopeResolver()
        )
        self._backend = backend or LinuxEbookRenameBackend()
        self._clock = clock or _system_clock
        self._id_factory = id_factory or EntityId.new
        self._reconciler = reconciler or SQLiteEbookRenameReconciler(
            engine,
            clock=self._clock,
        )
        self._rename_store = SQLiteEbookRenameStore(engine)
        self._plan_store = SQLiteEbookOperationRecipeStore(engine)
        self._leases = SQLiteScanRootWriteLeaseStore(engine)
        self._planning = EbookRenamePlanningService(
            engine,
            self._dependency_scopes,
            clock=self._clock,
        )

    def confirmation_prompt(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> str:
        _plan, authorization, _preparation, _probe, _capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        return ebook_rename_confirmation_text(authorization)

    def confirmation_digest(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
        confirmation_text: str,
    ) -> str:
        """Derive the existing domain-bound confirmation digest without persisting text."""
        _plan, authorization, _preparation, _probe, _capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        try:
            return ebook_rename_confirmation_digest(authorization, confirmation_text)
        except EbookRenameConfirmationError:
            _operator_fail(EbookRenameOperatorErrorCode.CONFIRMATION_INVALID)

    def authorize(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
    ) -> EbookRenameAuthorizationResult:
        plan = self._plan(plan_id, plan_content_hash)
        capability = self._capability(capability_id, plan)
        try:
            dependency_scope = self._planning.current_dependency_scope(plan)
        except EbookRenamePlanningError:
            _operator_fail(EbookRenameOperatorErrorCode.STALE)
        authorized_at = _now(self._clock).replace(microsecond=0)
        owner_id = self._id_factory()
        lease = self._acquire_new_lease(
            plan.candidate.sources[0].scan_root_id,
            ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION,
            owner_id,
            authorized_at,
        )
        try:
            self._rename_store.require_historical_target_absence(
                plan,
                lease,
                checked_at=_now(self._clock),
            )
            probe = self._backend.probe(capability, probed_at=_now(self._clock))
            probe = self._rename_store.create_or_get_probe(probe)
            physical = self._backend.capture_preparation_evidence(
                capability=capability,
                probe=probe,
                plan=plan,
                target_historically_absent=True,
                captured_at=_now(self._clock),
            )
            preparation = build_ebook_rename_preparation(
                plan,
                physical,
                capability,
                probe,
                dependency_scope,
                lease,
                authorized_at=authorized_at,
                prepared_at=_now(self._clock),
            )
            authorization = build_ebook_rename_authorization(
                preparation,
                expires_at=(
                    authorized_at + MAX_EBOOK_RENAME_AUTHORIZATION_LIFETIME
                ),
            )
            persisted = self._rename_store.create_or_get_authorization(
                plan,
                preparation,
                authorization,
                capability,
                probe,
                dependency_scope,
                lease,
                persisted_at=_now(self._clock),
            )
        except EbookRenameOperatorError:
            raise
        except (EbookRenameCapabilityUnavailable, EbookRenameDependencyScopeUnavailable):
            _operator_fail(EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE)
        except LinuxEbookRenameBackendError as error:
            _operator_fail(_backend_error_code(error))
        except (EbookRenameStoreError, TypeError, ValueError):
            _operator_fail(EbookRenameOperatorErrorCode.STALE)
        finally:
            self._release_lease(lease)
        return EbookRenameAuthorizationResult(
            authorization_id=persisted.id,
            plan_id=persisted.plan_id,
            scan_root_id=persisted.scan_root_id,
            capability_id=persisted.ebook_rename_capability_id,
            probe_id=persisted.probe_id,
            authorized_at=persisted.authorized_at,
            expires_at=persisted.expires_at,
        )

    def execute(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
        confirmation_text: str,
    ) -> EbookRenameOperationResult:
        plan, authorization, preparation, probe, capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        try:
            confirmation_digest = ebook_rename_confirmation_digest(
                authorization,
                confirmation_text,
            )
        except EbookRenameConfirmationError:
            _operator_fail(EbookRenameOperatorErrorCode.CONFIRMATION_INVALID)
        run = self._rename_store.get_run_for_authorization(authorization.id)
        if run is not None:
            existing = self._rename_store.get_reconciliation(run.id)
            if existing is not None:
                return self._result_from_reconciliation(plan, existing)
            self._require_confirmation(run, confirmation_digest)
        run_id = self._id_factory() if run is None else run.id
        lease = self._acquire_run_lease(run_id, authorization.scan_root_id)
        try:
            if run is None:
                created_at = _now(self._clock)
                if (
                    authorization.expires_at - created_at
                    < MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING
                ):
                    _operator_fail(EbookRenameOperatorErrorCode.AUTHORIZATION_UNAVAILABLE)
                run = build_ebook_rename_run(
                    authorization,
                    capability,
                    probe,
                    lease,
                    run_id=run_id,
                    created_at=created_at,
                )
                binding = build_ebook_rename_backend_binding(
                    run,
                    authorization,
                    probe,
                    bound_at=created_at,
                )
                prepared_event = EbookRenameExecutionEvent(
                    run_id=run.id,
                    sequence_no=1,
                    status=EbookRenameRunStatus.PREPARED,
                    occurred_at=created_at,
                    fence_epoch=lease.fence_epoch,
                    confirmation_digest=confirmation_digest,
                )
                run = self._rename_store.create_run(
                    run,
                    authorization,
                    probe,
                    binding,
                    prepared_event,
                    lease,
                )
            else:
                binding = self._binding(run)
            latest = self._latest_status(run)
            if latest not in {
                EbookRenameRunStatus.IMMEDIATE_VERIFIED,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
                EbookRenameRunStatus.SCAN_HANDOFF,
                EbookRenameRunStatus.CANCELLED,
                EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
            }:
                latest = execute_ebook_file_rename(
                    store=self._rename_store,
                    plan=plan,
                    preparation=preparation,
                    authorization=authorization,
                    capability=capability,
                    probe=probe,
                    binding=binding,
                    run=run,
                    lease=lease,
                    clock=self._clock,
                    backend=self._backend,
                ).status
            handoff = self._prepare_handoff(run, latest, lease)
            if handoff is None:
                return self._non_reconciled_result(plan, authorization, run, latest)
        except EbookRenameOperatorError:
            raise
        except EbookRenameExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (EbookRenameStoreError, ScanRootWriteLeaseError, TypeError, ValueError):
            _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)
        finally:
            self._release_lease(lease)
        return self._reconcile(
            plan,
            preparation,
            authorization,
            probe,
            binding,
            run,
            capability,
            handoff[0],
            handoff[1],
        )

    def recover(self, *, run_id: EntityId) -> EbookRenameOperationResult:
        (
            plan,
            preparation,
            authorization,
            probe,
            binding,
            run,
            capability,
        ) = self._historical_material(run_id)
        existing = self._rename_store.get_reconciliation(run.id)
        if existing is not None:
            if existing.outcome is EbookRenameReconciliationOutcome.VERIFIED:
                _operator_fail(EbookRenameOperatorErrorCode.ALREADY_VERIFIED)
            return self._result_from_reconciliation(plan, existing)
        lease = self._acquire_run_lease(run.id, run.scan_root_id)
        try:
            latest = self._latest_status(run)
            if latest is EbookRenameRunStatus.VERIFIED:
                _operator_fail(EbookRenameOperatorErrorCode.ALREADY_VERIFIED)
            if latest not in {
                EbookRenameRunStatus.IMMEDIATE_VERIFIED,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
                EbookRenameRunStatus.SCAN_HANDOFF,
                EbookRenameRunStatus.CANCELLED,
                EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
                EbookRenameRunStatus.RECOVERED,
            }:
                latest = recover_ebook_file_rename(
                    store=self._rename_store,
                    plan=plan,
                    preparation=preparation,
                    authorization=authorization,
                    capability=capability,
                    probe=probe,
                    binding=binding,
                    run=run,
                    lease=lease,
                    clock=self._clock,
                    backend=self._backend,
                ).status
            handoff = self._prepare_handoff(run, latest, lease)
            if handoff is None:
                return self._non_reconciled_result(plan, authorization, run, latest)
        except EbookRenameOperatorError:
            raise
        except EbookRenameExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (EbookRenameStoreError, ScanRootWriteLeaseError, TypeError, ValueError):
            _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)
        finally:
            self._release_lease(lease)
        return self._reconcile(
            plan,
            preparation,
            authorization,
            probe,
            binding,
            run,
            capability,
            handoff[0],
            handoff[1],
        )

    def _reconcile(
        self,
        plan: EbookOperationRecipePlan,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        probe: EbookRenameCapabilityProbeSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        capability: ResolvedEbookRenameCapability,
        outcome: EbookRenameReconciliationOutcome,
        not_before: datetime,
    ) -> EbookRenameOperationResult:
        try:
            evidence = self._reconciler.reconcile(
                run=run,
                preparation=preparation,
                capability=capability,
                plan=plan,
                outcome=outcome,
                not_before=not_before,
            )
        except EbookRenameOperatorError:
            raise
        except Exception:
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        lease = self._acquire_run_lease(run.id, run.scan_root_id)
        try:
            terminal = EbookRenameRunStatus(outcome.value)
            physical = verify_ebook_file_rename_physical_state(
                store=self._rename_store,
                plan=plan,
                preparation=preparation,
                authorization=authorization,
                capability=capability,
                probe=probe,
                binding=binding,
                run=run,
                lease=lease,
                expected_outcome=terminal,
                clock=self._clock,
                backend=self._backend,
            )
            snapshot = build_ebook_rename_reconciliation(
                run_id=run.id,
                authorization_id=authorization.id,
                authorization_content_hash=authorization.content_hash,
                preparation_id=preparation.id,
                preparation_content_hash=preparation.content_hash,
                outcome=outcome,
                scan_run_id=evidence.scan_run_id,
                source_file_id=run.source_file_id,
                source_before_observation_id=preparation.source_observation_id,
                source_scan_event_id=evidence.source_scan_event_id,
                source_observation_id=evidence.source_observation_id,
                target_file_id=evidence.target_file_id,
                target_observation_id=evidence.target_observation_id,
                target_scan_event_id=evidence.target_scan_event_id,
                collection_state_snapshot_id=evidence.collection_state.id,
                collection_state_content_digest=evidence.collection_state.content_digest,
                expected_full_sha256=preparation.source_full_sha256,
                expected_size_bytes=preparation.source_size_bytes,
                target_absence_fingerprint=preparation.target_absence_fingerprint,
                physical_confirmation_digest=physical.confirmation_digest,
                reconciled_at=_now(self._clock),
            )
            persisted = self._rename_store.record_reconciliation(
                snapshot,
                plan,
                preparation,
                authorization,
                capability,
                probe,
                binding,
                run,
                lease,
            )
        except EbookRenameOperatorError:
            raise
        except EbookRenameExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (EbookRenameStoreError, ScanRootWriteLeaseError, TypeError, ValueError):
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        finally:
            self._release_lease(lease)
        return self._result_from_reconciliation(plan, persisted)

    def _prepare_handoff(
        self,
        run: EbookRenameExecutionRun,
        latest: EbookRenameRunStatus,
        lease: OwnedScanRootWriteLease,
    ) -> tuple[EbookRenameReconciliationOutcome, datetime] | None:
        if latest is EbookRenameRunStatus.CANCELLED:
            return None
        if latest is EbookRenameRunStatus.RECOVERED:
            _operator_fail(EbookRenameOperatorErrorCode.RECONCILIATION_PENDING)
        if latest is EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED:
            _operator_fail(EbookRenameOperatorErrorCode.MANUAL_RECOVERY_REQUIRED)
        if latest in {
            EbookRenameRunStatus.VERIFIED,
        }:
            _operator_fail(EbookRenameOperatorErrorCode.ALREADY_VERIFIED)
        if latest in {
            EbookRenameRunStatus.IMMEDIATE_VERIFIED,
            EbookRenameRunStatus.RECOVERY_VERIFIED,
        }:
            outcome = (
                EbookRenameReconciliationOutcome.VERIFIED
                if latest is EbookRenameRunStatus.IMMEDIATE_VERIFIED
                else EbookRenameReconciliationOutcome.RECOVERED
            )
            event = self._append_event(
                run,
                lease,
                EbookRenameRunStatus.SCAN_HANDOFF,
                "SCAN_HANDOFF_STARTED",
            )
            return outcome, event.occurred_at
        if latest is EbookRenameRunStatus.SCAN_HANDOFF:
            events = self._rename_store.events_for_run(run.id)
            forward = any(
                event.status is EbookRenameRunStatus.IMMEDIATE_VERIFIED
                for event in events
            )
            recovered = any(
                event.status is EbookRenameRunStatus.RECOVERY_VERIFIED
                for event in events
            )
            if forward == recovered:
                _operator_fail(EbookRenameOperatorErrorCode.INTERNAL_ERROR)
            return (
                EbookRenameReconciliationOutcome.VERIFIED
                if forward
                else EbookRenameReconciliationOutcome.RECOVERED,
                events[-1].occurred_at,
            )
        _operator_fail(EbookRenameOperatorErrorCode.RECOVERY_REQUIRED)

    def _append_event(
        self,
        run: EbookRenameExecutionRun,
        lease: OwnedScanRootWriteLease,
        status: EbookRenameRunStatus,
        finding_code: str,
    ) -> EbookRenameExecutionEvent:
        events = self._rename_store.events_for_run(run.id)
        return self._rename_store.append_event(
            EbookRenameExecutionEvent(
                run_id=run.id,
                sequence_no=len(events) + 1,
                status=status,
                occurred_at=_now(self._clock),
                fence_epoch=lease.fence_epoch,
                finding_code=finding_code,
            ),
            lease,
        )

    def _plan(
        self,
        plan_id: EntityId,
        plan_content_hash: str,
    ) -> EbookOperationRecipePlan:
        if not isinstance(plan_id, EntityId) or _SHA256.fullmatch(plan_content_hash) is None:
            _operator_fail(EbookRenameOperatorErrorCode.PLAN_MISMATCH)
        try:
            plan = self._plan_store.get_plan(plan_id)
            if plan is None:
                _operator_fail(EbookRenameOperatorErrorCode.PLAN_UNAVAILABLE)
            if plan.content_hash != plan_content_hash:
                _operator_fail(EbookRenameOperatorErrorCode.PLAN_MISMATCH)
            ebook_rename_dependencies_fingerprint(plan)
            return plan
        except EbookRenameOperatorError:
            raise
        except (EbookOperationRecipeStoreError, TypeError, ValueError, RuntimeError):
            _operator_fail(EbookRenameOperatorErrorCode.PLAN_UNAVAILABLE)

    def _capability(
        self,
        capability_id: EntityId,
        plan: EbookOperationRecipePlan,
    ) -> ResolvedEbookRenameCapability:
        try:
            capability = self._capabilities.resolve(capability_id)
        except EbookRenameCapabilityUnavailable:
            _operator_fail(EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE)
        if (
            capability.ebook_rename_capability_id != capability_id
            or capability.scan_root_id != plan.candidate.sources[0].scan_root_id
        ):
            _operator_fail(EbookRenameOperatorErrorCode.AUTHORIZATION_MISMATCH)
        return capability

    def _bound_material(
        self,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> tuple[
        EbookOperationRecipePlan,
        EbookRenameAuthorizationSnapshot,
        EbookRenamePreparationSnapshot,
        EbookRenameCapabilityProbeSnapshot,
        ResolvedEbookRenameCapability,
    ]:
        plan = self._plan(plan_id, plan_content_hash)
        authorization = self._rename_store.get_authorization(authorization_id)
        if authorization is None:
            _operator_fail(EbookRenameOperatorErrorCode.AUTHORIZATION_UNAVAILABLE)
        preparation = self._rename_store.get_preparation(authorization.preparation_id)
        probe = self._rename_store.get_probe(authorization.probe_id)
        capability = self._capability(capability_id, plan)
        if (
            preparation is None
            or probe is None
            or authorization.plan_id != plan.id
            or authorization.plan_content_hash != plan.content_hash
            or authorization.ebook_rename_capability_id != capability_id
            or authorization.scan_root_id != capability.scan_root_id
            or authorization.preparation_content_hash != preparation.content_hash
            or preparation.plan_id != plan.id
            or preparation.probe_id != probe.id
            or preparation.probe_content_hash != probe.content_hash
        ):
            _operator_fail(EbookRenameOperatorErrorCode.AUTHORIZATION_MISMATCH)
        return plan, authorization, preparation, probe, capability

    def _historical_material(
        self,
        run_id: EntityId,
    ) -> tuple[
        EbookOperationRecipePlan,
        EbookRenamePreparationSnapshot,
        EbookRenameAuthorizationSnapshot,
        EbookRenameCapabilityProbeSnapshot,
        EbookRenameBackendBinding,
        EbookRenameExecutionRun,
        ResolvedEbookRenameCapability,
    ]:
        if not isinstance(run_id, EntityId):
            _operator_fail(EbookRenameOperatorErrorCode.RUN_UNAVAILABLE)
        run = self._rename_store.get_run(run_id)
        if run is None:
            _operator_fail(EbookRenameOperatorErrorCode.RUN_UNAVAILABLE)
        authorization = self._rename_store.get_authorization(run.authorization_id)
        if authorization is None:
            _operator_fail(EbookRenameOperatorErrorCode.RUN_UNAVAILABLE)
        preparation = self._rename_store.get_preparation(authorization.preparation_id)
        probe = self._rename_store.get_probe(run.probe_id)
        binding = self._rename_store.get_backend_binding(run.id)
        plan = self._plan_store.get_plan(run.plan_id)
        if preparation is None or probe is None or binding is None or plan is None:
            _operator_fail(EbookRenameOperatorErrorCode.RUN_UNAVAILABLE)
        capability = self._capability(run.ebook_rename_capability_id, plan)
        if (
            run.authorization_content_hash != authorization.content_hash
            or authorization.preparation_content_hash != preparation.content_hash
            or preparation.probe_content_hash != probe.content_hash
            or binding.run_id != run.id
            or binding.probe_content_hash != probe.content_hash
            or plan.content_hash != authorization.plan_content_hash
        ):
            _operator_fail(EbookRenameOperatorErrorCode.AUTHORIZATION_MISMATCH)
        return plan, preparation, authorization, probe, binding, run, capability

    def _binding(self, run: EbookRenameExecutionRun) -> EbookRenameBackendBinding:
        value = self._rename_store.get_backend_binding(run.id)
        if value is None:
            _operator_fail(EbookRenameOperatorErrorCode.RUN_UNAVAILABLE)
        return value

    def _require_confirmation(
        self,
        run: EbookRenameExecutionRun,
        confirmation_digest: str,
    ) -> None:
        events = self._rename_store.events_for_run(run.id)
        persisted = events[0].confirmation_digest
        if persisted is None or not hmac.compare_digest(persisted, confirmation_digest):
            _operator_fail(EbookRenameOperatorErrorCode.CONFIRMATION_INVALID)

    def _acquire_new_lease(
        self,
        scan_root_id: EntityId,
        owner_kind: ScanRootWriteOwnerKind,
        owner_run_id: EntityId,
        acquired_at: datetime,
    ) -> OwnedScanRootWriteLease:
        try:
            return self._leases.acquire(
                scan_root_id,
                owner_kind,
                owner_run_id,
                lease_token=str(self._id_factory()),
                acquired_at=acquired_at,
                lease_expires_at=acquired_at + _LEASE_DURATION,
            )
        except (ScanRootWriteLeaseError, TypeError, ValueError):
            _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)

    def _acquire_run_lease(
        self,
        run_id: EntityId,
        scan_root_id: EntityId,
    ) -> OwnedScanRootWriteLease:
        acquired_at = _now(self._clock)
        current = self._leases.current(scan_root_id)
        if current is None:
            return self._acquire_new_lease(
                scan_root_id,
                ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
                run_id,
                acquired_at,
            )
        if (
            current.owner_kind is ScanRootWriteOwnerKind.EBOOK_RENAME_RUN
            and current.owner_run_id == run_id
            and current.lease_expires_at <= acquired_at
        ):
            try:
                return self._leases.takeover_expired(
                    current,
                    run_id,
                    lease_token=str(self._id_factory()),
                    acquired_at=acquired_at,
                    lease_expires_at=acquired_at + _LEASE_DURATION,
                )
            except (ScanRootWriteLeaseError, TypeError, ValueError):
                pass
        _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)

    def _release_lease(self, lease: OwnedScanRootWriteLease) -> None:
        try:
            current = self._leases.current(lease.scan_root_id)
            if current == lease:
                self._leases.release(lease, released_at=_now(self._clock))
        except (ScanRootWriteLeaseError, TypeError, ValueError):
            pass

    def _latest_status(self, run: EbookRenameExecutionRun) -> EbookRenameRunStatus:
        events = self._rename_store.events_for_run(run.id)
        if not events:
            _operator_fail(EbookRenameOperatorErrorCode.INTERNAL_ERROR)
        return events[-1].status

    @staticmethod
    def _non_reconciled_result(
        plan: EbookOperationRecipePlan,
        authorization: EbookRenameAuthorizationSnapshot,
        run: EbookRenameExecutionRun,
        status: EbookRenameRunStatus,
    ) -> EbookRenameOperationResult:
        if status is not EbookRenameRunStatus.CANCELLED:
            _operator_fail(EbookRenameOperatorErrorCode.RECOVERY_REQUIRED)
        return EbookRenameOperationResult(
            authorization_id=authorization.id,
            run_id=run.id,
            plan_id=plan.id,
            scan_root_id=run.scan_root_id,
            status=status,
        )

    @staticmethod
    def _result_from_reconciliation(
        plan: EbookOperationRecipePlan,
        reconciliation: EbookRenameReconciliationSnapshot,
    ) -> EbookRenameOperationResult:
        return EbookRenameOperationResult(
            authorization_id=reconciliation.authorization_id,
            run_id=reconciliation.run_id,
            plan_id=plan.id,
            scan_root_id=plan.candidate.sources[0].scan_root_id,
            status=EbookRenameRunStatus(reconciliation.outcome.value),
            scan_run_id=reconciliation.scan_run_id,
            source_observation_id=reconciliation.source_observation_id,
            target_observation_id=reconciliation.target_observation_id,
            collection_state_snapshot_id=reconciliation.collection_state_snapshot_id,
        )


def create_ebook_rename_operator_service(engine: Engine) -> EbookRenameOperatorService:
    return EbookRenameOperatorService(engine)


def _executor_error_code(error: EbookRenameExecutorError) -> EbookRenameOperatorErrorCode:
    return {
        EbookRenameExecutorErrorCode.STALE: EbookRenameOperatorErrorCode.STALE,
        EbookRenameExecutorErrorCode.TARGET_COLLISION: (
            EbookRenameOperatorErrorCode.TARGET_COLLISION
        ),
        EbookRenameExecutorErrorCode.TOOL_UNAVAILABLE: (
            EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE
        ),
        EbookRenameExecutorErrorCode.IO_FAILED: EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE,
        EbookRenameExecutorErrorCode.FENCED_OUT: EbookRenameOperatorErrorCode.FENCED_OUT,
        EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED: (
            EbookRenameOperatorErrorCode.MANUAL_RECOVERY_REQUIRED
        ),
    }[error.code]


def _backend_error_code(
    error: LinuxEbookRenameBackendError,
) -> EbookRenameOperatorErrorCode:
    return {
        LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE: (
            EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE
        ),
        LinuxEbookRenameBackendErrorCode.SOURCE_STALE: EbookRenameOperatorErrorCode.STALE,
        LinuxEbookRenameBackendErrorCode.TARGET_COLLISION: (
            EbookRenameOperatorErrorCode.TARGET_COLLISION
        ),
        LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS: (
            EbookRenameOperatorErrorCode.MANUAL_RECOVERY_REQUIRED
        ),
        LinuxEbookRenameBackendErrorCode.IO_FAILED: (
            EbookRenameOperatorErrorCode.TOOL_UNAVAILABLE
        ),
    }[error.code]


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _operator_fail(EbookRenameOperatorErrorCode.FENCED_OUT)
    return value.astimezone(UTC)


def _operator_fail(code: EbookRenameOperatorErrorCode) -> NoReturn:
    raise EbookRenameOperatorError(code) from None


__all__ = [
    "EBOOK_RENAME_OPERATOR_PROFILE",
    "EbookRenameAuthorizationResult",
    "EbookRenameOperationResult",
    "EbookRenameOperatorBackend",
    "EbookRenameOperatorError",
    "EbookRenameOperatorErrorCode",
    "EbookRenameOperatorService",
    "EbookRenameReconciler",
    "EbookRenameScanReconciliation",
    "SQLiteEbookRenameReconciler",
    "create_ebook_rename_operator_service",
]
