"""Operational MW05 application service for the bounded EPUB title writer."""

from __future__ import annotations

import io
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import NoReturn, Protocol

from sqlalchemy import Engine, select

from foliotone.collection_state import CollectionStateSnapshot
from foliotone.core import EntityId, MediaType, ScanRoot, ScanRunStatus
from foliotone.index import (
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.metadata_write.authorization import (
    MAX_METADATA_WRITE_AUTHORIZATION_LIFETIME,
    MetadataWriteAuthorizationSnapshot,
    MetadataWriteExecutionRun,
    MetadataWriteRunStatus,
    build_epub3_title_write_preparation,
    build_metadata_write_authorization,
    build_metadata_write_run,
)
from foliotone.metadata_write.capabilities import (
    MetadataWriteCapabilityResolver,
    MetadataWriteCapabilityUnavailable,
    ResolvedMetadataWriteCapability,
)
from foliotone.metadata_write.confirmation import (
    MetadataWriteConfirmationError,
    metadata_write_confirmation_digest,
    metadata_write_confirmation_text,
)
from foliotone.metadata_write.contracts import (
    EpubConformanceStatus,
    EpubInputConformance,
    EpubPublicationKind,
)
from foliotone.metadata_write.epub_title import (
    build_epub3_title_package_patch,
    preflight_epub3_title_write,
    validate_epub3_title_write_plan,
)
from foliotone.metadata_write.executor import (
    MetadataWriteExecutorError,
    MetadataWriteExecutorErrorCode,
    MetadataWriteFilesystemBackend,
    execute_epub3_title_metadata_write,
    recover_epub3_title_metadata_write,
    verify_epub3_title_metadata_write_physical_state,
)
from foliotone.metadata_write.linux_backend import (
    LinuxMetadataWriteBackend,
    LinuxMetadataWriteBackendError,
    LinuxMetadataWriteBackendErrorCode,
    LinuxMetadataWriteSourceReader,
)
from foliotone.metadata_write.reconciliation import (
    MetadataWriteReconciliationOutcome,
    MetadataWriteReconciliationSnapshot,
    build_metadata_write_reconciliation,
)
from foliotone.metadata_write.staging import EpubTitleStagingError
from foliotone.metadata_write.validation import (
    FixedEpubTitleStagingValidator,
    build_and_verify_private_epub3_title_stage,
)
from foliotone.persistence import repository, schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.metadata_correction import (
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
)
from foliotone.persistence.metadata_write import (
    MetadataWritePreparationSourceSnapshot,
    MetadataWriteStoreError,
    SQLiteMetadataWriteStore,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.workflows.collection_state import CollectionStateBuildService

METADATA_WRITE_STAGE_ROOT_ENV = "FOLIOTONE_METADATA_WRITE_STAGE_ROOT"
METADATA_WRITE_OPERATOR_PROFILE = "metadata-write-operator/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LEASE_DURATION = timedelta(minutes=30)
_MAX_RECONCILIATION_SCAN_CANDIDATES = 128
_REPARSE_POINT = 0x0400


class MetadataWriteOperatorErrorCode(StrEnum):
    PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    AUTHORIZATION_UNAVAILABLE = "AUTHORIZATION_UNAVAILABLE"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    RUN_UNAVAILABLE = "RUN_UNAVAILABLE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    STALE = "STALE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MetadataWriteOperatorError(RuntimeError):
    """One fixed path-, hash-, and metadata-value-free operator failure."""

    def __init__(self, code: MetadataWriteOperatorErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class MetadataWriteAuthorizationResult:
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    authorized_at: datetime
    expires_at: datetime
    status: str = "AUTHORIZED"
    profile: str = METADATA_WRITE_OPERATOR_PROFILE


@dataclass(frozen=True, slots=True)
class MetadataWriteOperationResult:
    authorization_id: EntityId
    run_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    status: MetadataWriteRunStatus
    scan_run_id: EntityId | None = None
    observation_id: EntityId | None = None
    collection_state_snapshot_id: EntityId | None = None
    profile: str = METADATA_WRITE_OPERATOR_PROFILE


@dataclass(frozen=True, slots=True)
class MetadataWriteScanReconciliation:
    scan_run_id: EntityId
    observation_id: EntityId
    collection_state: CollectionStateSnapshot


class MetadataWritePreparationSourceReader(Protocol):
    def read_source(
        self,
        *,
        capability: ResolvedMetadataWriteCapability,
        source_relative_path: str,
        expected_sha256: str,
        expected_size_bytes: int,
        expected_modified_at: datetime,
    ) -> bytes: ...


class MetadataWriteReconciler(Protocol):
    def reconcile(
        self,
        *,
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        capability: ResolvedMetadataWriteCapability,
        outcome: MetadataWriteReconciliationOutcome,
        not_before: datetime,
    ) -> MetadataWriteScanReconciliation: ...


class SQLiteMetadataWriteReconciler:
    """Create or reuse one exact post-mutation scan and CollectionState."""

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
        run: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        capability: ResolvedMetadataWriteCapability,
        outcome: MetadataWriteReconciliationOutcome,
        not_before: datetime,
    ) -> MetadataWriteScanReconciliation:
        expected_hash = (
            authorization.expected_output_sha256
            if outcome is MetadataWriteReconciliationOutcome.VERIFIED
            else authorization.source_sha256
        )
        candidate = self._latest_matching_scan(
            run,
            expected_hash=expected_hash,
            not_before=not_before,
        )
        if candidate is None:
            candidate = self._scan(run, capability, expected_hash)
        report = CollectionStateBuildService(self._engine).build(
            candidate[0],
            _now(self._clock),
        )
        snapshot = report.snapshot
        if snapshot.scan_root_id != run.scan_root_id or snapshot.source_scan_run_id != candidate[0]:
            raise MetadataWriteOperatorError(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
        return MetadataWriteScanReconciliation(
            scan_run_id=candidate[0],
            observation_id=candidate[1],
            collection_state=snapshot,
        )

    def _scan(
        self,
        run: MetadataWriteExecutionRun,
        capability: ResolvedMetadataWriteCapability,
        expected_hash: str,
    ) -> tuple[EntityId, EntityId]:
        root = repository(self._engine, ScanRoot).get(run.scan_root_id)
        if (
            root is None
            or not root.enabled
            or root.media_type is not MediaType.EBOOK
            or capability.scan_root_id != root.id
        ):
            raise MetadataWriteOperatorError(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
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
            raise MetadataWriteOperatorError(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
        candidate = self._matching_observation(
            summary.run.id,
            run.file_id,
            expected_hash,
        )
        if candidate is None:
            raise MetadataWriteOperatorError(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
        return summary.run.id, candidate

    def _latest_matching_scan(
        self,
        run: MetadataWriteExecutionRun,
        *,
        expected_hash: str,
        not_before: datetime,
    ) -> tuple[EntityId, EntityId] | None:
        with self._engine.connect() as connection:
            rows = connection.execute(
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
            for row in rows:
                scan_id = EntityId.parse(str(row.id))
                observation_id = self._matching_observation(
                    scan_id,
                    run.file_id,
                    expected_hash,
                )
                if observation_id is not None:
                    return scan_id, observation_id
        return None

    def _matching_observation(
        self,
        scan_run_id: EntityId,
        file_id: EntityId,
        expected_hash: str,
    ) -> EntityId | None:
        with self._engine.connect() as connection:
            rows = tuple(
                connection.execute(
                    select(schema.file_observations.c.id)
                    .select_from(
                        schema.file_observations.join(
                            schema.fingerprints,
                            schema.fingerprints.c.target_id == schema.file_observations.c.id,
                        )
                    )
                    .where(
                        schema.file_observations.c.scan_run_id == str(scan_run_id),
                        schema.file_observations.c.file_id == str(file_id),
                        schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                        schema.fingerprints.c.kind == "FILE_SHA256",
                        schema.fingerprints.c.algorithm == "sha256",
                        schema.fingerprints.c.algorithm_version == "1",
                        schema.fingerprints.c.value == expected_hash,
                        schema.fingerprints.c.tool_execution_id.is_(None),
                    )
                )
            )
        if len(rows) != 1:
            return None
        return EntityId.parse(str(rows[0].id))


class MetadataWriteOperatorService:
    """Authorize, execute, reconcile, or recover one exact ADR-0063 operation."""

    def __init__(
        self,
        engine: Engine,
        private_stage_root: Path,
        *,
        capability_resolver: MetadataWriteCapabilityResolver | None = None,
        source_reader: MetadataWritePreparationSourceReader | None = None,
        validator: FixedEpubTitleStagingValidator | None = None,
        backend: MetadataWriteFilesystemBackend | None = None,
        reconciler: MetadataWriteReconciler | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._stage_root = private_stage_root
        self._capabilities = capability_resolver or MetadataWriteCapabilityResolver()
        self._source_reader = source_reader or LinuxMetadataWriteSourceReader()
        self._validator = validator or FixedEpubTitleStagingValidator()
        self._backend = backend or LinuxMetadataWriteBackend()
        self._clock = clock or _system_clock
        self._reconciler = reconciler or SQLiteMetadataWriteReconciler(
            engine,
            clock=self._clock,
        )
        self._write_store = SQLiteMetadataWriteStore(engine)
        self._plan_store = SQLiteMetadataCorrectionStore(engine)
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def confirmation_prompt(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> str:
        """Return the sole prompt after revalidating all opaque binders."""

        _plan, authorization, _capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        return metadata_write_confirmation_text(authorization)

    def authorize(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
    ) -> MetadataWriteAuthorizationResult:
        plan = self._plan(plan_id, plan_content_hash)
        capability = self._capability(capability_id, plan)
        authorized_at = _now(self._clock).replace(microsecond=0)
        owner_id = EntityId.new()
        lease = self._acquire_new_lease(
            plan.candidate.scan_root_id,
            ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION,
            owner_id,
            authorized_at,
        )
        try:
            source = self._write_store.require_preparation_source(
                plan,
                lease,
                checked_at=_now(self._clock),
            )
            source_bytes = self._read_preparation_source(capability, source)
            conformance = EpubInputConformance(
                input_sha256=source.source_sha256,
                publication_kind=EpubPublicationKind.EPUB3,
                status=EpubConformanceStatus.CONFORMANT,
            )
            preflight = preflight_epub3_title_write(
                plan,
                source_bytes,
                conformance,
            )
            patch = build_epub3_title_package_patch(
                preflight,
                authorized_at=authorized_at,
            )
            stage_directory = _private_stage_directory(
                self._stage_root,
                capability,
                owner_id,
                lease.fence_epoch,
                "preparation",
            )
            verified = build_and_verify_private_epub3_title_stage(
                stage_directory,
                io.BytesIO(source_bytes),
                preflight,
                patch,
                validator=self._validator,
            )
            input_epubcheck_version = self._validator.validate_input_conformance(
                verified.staged_files
            )
            if input_epubcheck_version != verified.validation.epubcheck_tool_version:
                raise MetadataWriteOperatorError(MetadataWriteOperatorErrorCode.VALIDATION_FAILED)
            prepared_at = _now(self._clock)
            preparation = build_epub3_title_write_preparation(
                plan=plan,
                preflight=preflight,
                patch=patch,
                verified_stage=verified,
                capability=capability,
                preparation_lease=lease,
                authorized_at=authorized_at,
                prepared_at=prepared_at,
            )
            authorization = build_metadata_write_authorization(
                preparation,
                expires_at=authorized_at + MAX_METADATA_WRITE_AUTHORIZATION_LIFETIME,
            )
            persisted = self._write_store.create_or_get_authorization(
                authorization,
                plan,
                lease,
                persisted_at=_now(self._clock),
            )
        except MetadataWriteOperatorError:
            raise
        except MetadataWriteCapabilityUnavailable:
            _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
        except LinuxMetadataWriteBackendError as error:
            _operator_fail(_backend_error_code(error))
        except (EpubTitleStagingError, MetadataWriteStoreError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.VALIDATION_FAILED)
        finally:
            self._release_lease(lease)
        return MetadataWriteAuthorizationResult(
            authorization_id=persisted.id,
            plan_id=persisted.plan_id,
            scan_root_id=persisted.scan_root_id,
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
    ) -> MetadataWriteOperationResult:
        plan, authorization, capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        try:
            confirmation_digest = metadata_write_confirmation_digest(
                authorization,
                confirmation_text,
            )
        except MetadataWriteConfirmationError:
            _operator_fail(MetadataWriteOperatorErrorCode.CONFIRMATION_INVALID)
        run = self._write_store.get_run_for_authorization(authorization.id)
        if run is not None:
            existing_reconciliation = self._write_store.get_reconciliation(run.id)
            if existing_reconciliation is not None:
                return self._result_from_reconciliation(plan, existing_reconciliation)
        run_id = EntityId.new() if run is None else run.id
        lease = self._acquire_run_lease(run_id, authorization.scan_root_id)
        try:
            if run is None:
                created_at = _now(self._clock)
                run = build_metadata_write_run(
                    authorization,
                    capability,
                    lease,
                    run_id=run_id,
                    created_at=created_at,
                )
                run = self._write_store.create_run(
                    run,
                    authorization,
                    plan,
                    lease,
                    confirmation_digest=confirmation_digest,
                )
            self._write_store.require_execution_confirmation(
                run,
                authorization,
                lease,
                confirmation_digest=confirmation_digest,
                checked_at=_now(self._clock),
            )
            latest = self._latest_status(run)
            if latest is MetadataWriteRunStatus.CREATED:
                execution = execute_epub3_title_metadata_write(
                    store=self._write_store,
                    run=run,
                    authorization=authorization,
                    plan=plan,
                    capability=capability,
                    lease=lease,
                    private_stage_root=self._stage_root,
                    clock=self._clock,
                    backend=self._backend,
                    validator=self._validator,
                )
                latest = execution.status
            if latest is MetadataWriteRunStatus.VERIFIED:
                reconciliation = self._write_store.get_reconciliation(run.id)
                if reconciliation is None:
                    _operator_fail(MetadataWriteOperatorErrorCode.INTERNAL_ERROR)
                return self._result_from_reconciliation(plan, reconciliation)
            if latest is not MetadataWriteRunStatus.ORIGINAL_PRESERVED:
                _operator_fail(_execute_status_error(latest))
            handoff_at = self._latest_event_time(run)
        except MetadataWriteOperatorError:
            raise
        except MetadataWriteExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (MetadataWriteStoreError, ScanRootWriteLeaseError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)
        finally:
            self._release_lease(lease)
        return self._reconcile(
            plan,
            authorization,
            run,
            capability,
            MetadataWriteReconciliationOutcome.VERIFIED,
            handoff_at,
        )

    def recover(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> MetadataWriteOperationResult:
        plan, authorization, capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
        )
        run = self._write_store.get_run_for_authorization(authorization.id)
        if run is None:
            _operator_fail(MetadataWriteOperatorErrorCode.RUN_UNAVAILABLE)
        existing = self._write_store.get_reconciliation(run.id)
        if existing is not None:
            if existing.outcome is MetadataWriteReconciliationOutcome.VERIFIED:
                _operator_fail(MetadataWriteOperatorErrorCode.ALREADY_VERIFIED)
            return self._result_from_reconciliation(plan, existing)
        lease = self._acquire_run_lease(run.id, run.scan_root_id)
        try:
            latest = self._latest_status(run)
            if latest is MetadataWriteRunStatus.VERIFIED:
                _operator_fail(MetadataWriteOperatorErrorCode.ALREADY_VERIFIED)
            recovery = recover_epub3_title_metadata_write(
                store=self._write_store,
                run=run,
                authorization=authorization,
                plan=plan,
                capability=capability,
                lease=lease,
                clock=self._clock,
                backend=self._backend,
            )
            latest = recovery.status
            if latest is not MetadataWriteRunStatus.RECOVERED:
                return MetadataWriteOperationResult(
                    authorization_id=authorization.id,
                    run_id=run.id,
                    plan_id=plan.id,
                    scan_root_id=run.scan_root_id,
                    status=latest,
                )
            handoff_at = self._latest_event_time(run)
        except MetadataWriteOperatorError:
            raise
        except MetadataWriteExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (MetadataWriteStoreError, ScanRootWriteLeaseError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)
        finally:
            self._release_lease(lease)
        return self._reconcile(
            plan,
            authorization,
            run,
            capability,
            MetadataWriteReconciliationOutcome.RECOVERED,
            handoff_at,
        )

    def _reconcile(
        self,
        plan: MetadataCorrectionPlan,
        authorization: MetadataWriteAuthorizationSnapshot,
        run: MetadataWriteExecutionRun,
        capability: ResolvedMetadataWriteCapability,
        outcome: MetadataWriteReconciliationOutcome,
        not_before: datetime,
    ) -> MetadataWriteOperationResult:
        try:
            evidence = self._reconciler.reconcile(
                run=run,
                authorization=authorization,
                capability=capability,
                outcome=outcome,
                not_before=not_before,
            )
        except MetadataWriteOperatorError:
            raise
        except Exception:
            _operator_fail(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
        lease = self._acquire_run_lease(run.id, run.scan_root_id)
        try:
            expected_status = (
                MetadataWriteRunStatus.ORIGINAL_PRESERVED
                if outcome is MetadataWriteReconciliationOutcome.VERIFIED
                else MetadataWriteRunStatus.RECOVERED
            )
            physical = verify_epub3_title_metadata_write_physical_state(
                store=self._write_store,
                run=run,
                authorization=authorization,
                plan=plan,
                capability=capability,
                lease=lease,
                expected_status=expected_status,
                clock=self._clock,
                backend=self._backend,
            )
            reconciled_at = _now(self._clock)
            snapshot = build_metadata_write_reconciliation(
                run_id=run.id,
                authorization_id=authorization.id,
                authorization_content_hash=authorization.content_hash,
                outcome=outcome,
                scan_run_id=evidence.scan_run_id,
                observation_id=evidence.observation_id,
                collection_state_snapshot_id=evidence.collection_state.id,
                collection_state_content_digest=evidence.collection_state.content_digest,
                physical_confirmation_digest=physical.confirmation_digest,
                reconciled_at=reconciled_at,
            )
            persisted = self._write_store.record_reconciliation(
                snapshot,
                run,
                authorization,
                lease,
            )
        except MetadataWriteOperatorError:
            raise
        except MetadataWriteExecutorError as error:
            _operator_fail(_executor_error_code(error))
        except (MetadataWriteStoreError, ScanRootWriteLeaseError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.RECONCILIATION_PENDING)
        finally:
            self._release_lease(lease)
        return self._result_from_reconciliation(plan, persisted)

    def _plan(self, plan_id: EntityId, plan_content_hash: str) -> MetadataCorrectionPlan:
        if not isinstance(plan_id, EntityId) or _SHA256.fullmatch(plan_content_hash) is None:
            _operator_fail(MetadataWriteOperatorErrorCode.PLAN_MISMATCH)
        try:
            plan = self._plan_store.get_plan(plan_id)
            if plan is None:
                _operator_fail(MetadataWriteOperatorErrorCode.PLAN_UNAVAILABLE)
            if plan.content_hash != plan_content_hash:
                _operator_fail(MetadataWriteOperatorErrorCode.PLAN_MISMATCH)
            validate_epub3_title_write_plan(plan)
            return plan
        except MetadataWriteOperatorError:
            raise
        except (MetadataCorrectionStoreError, TypeError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.PLAN_UNAVAILABLE)

    def _capability(
        self,
        capability_id: EntityId,
        plan: MetadataCorrectionPlan,
    ) -> ResolvedMetadataWriteCapability:
        try:
            capability = self._capabilities.resolve(capability_id)
        except MetadataWriteCapabilityUnavailable:
            _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
        if (
            capability.metadata_write_capability_id != capability_id
            or capability.scan_root_id != plan.candidate.scan_root_id
        ):
            _operator_fail(MetadataWriteOperatorErrorCode.AUTHORIZATION_MISMATCH)
        return capability

    def _bound_material(
        self,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> tuple[
        MetadataCorrectionPlan,
        MetadataWriteAuthorizationSnapshot,
        ResolvedMetadataWriteCapability,
    ]:
        plan = self._plan(plan_id, plan_content_hash)
        authorization = self._write_store.get_authorization(authorization_id)
        if authorization is None:
            _operator_fail(MetadataWriteOperatorErrorCode.AUTHORIZATION_UNAVAILABLE)
        capability = self._capability(capability_id, plan)
        if (
            authorization.plan_id != plan.id
            or authorization.plan_content_hash != plan.content_hash
            or authorization.metadata_write_capability_id != capability_id
            or authorization.scan_root_id != capability.scan_root_id
        ):
            _operator_fail(MetadataWriteOperatorErrorCode.AUTHORIZATION_MISMATCH)
        return plan, authorization, capability

    def _read_preparation_source(
        self,
        capability: ResolvedMetadataWriteCapability,
        source: MetadataWritePreparationSourceSnapshot,
    ) -> bytes:
        return self._source_reader.read_source(
            capability=capability,
            source_relative_path=source.relative_path,
            expected_sha256=source.source_sha256,
            expected_size_bytes=source.source_size_bytes,
            expected_modified_at=source.expected_modified_at,
        )

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
                lease_token=str(EntityId.new()),
                acquired_at=acquired_at,
                lease_expires_at=acquired_at + _LEASE_DURATION,
            )
        except (ScanRootWriteLeaseError, TypeError, ValueError):
            _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)

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
                ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
                run_id,
                acquired_at,
            )
        if (
            current.owner_kind is ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            and current.owner_run_id == run_id
            and current.lease_expires_at <= acquired_at
        ):
            try:
                return self._leases.takeover_expired(
                    current,
                    run_id,
                    lease_token=str(EntityId.new()),
                    acquired_at=acquired_at,
                    lease_expires_at=acquired_at + _LEASE_DURATION,
                )
            except (ScanRootWriteLeaseError, TypeError, ValueError):
                pass
        _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)

    def _release_lease(self, lease: OwnedScanRootWriteLease) -> None:
        try:
            current = self._leases.current(lease.scan_root_id)
            if current == lease:
                self._leases.release(lease, released_at=_now(self._clock))
        except (ScanRootWriteLeaseError, TypeError, ValueError):
            pass

    def _latest_status(self, run: MetadataWriteExecutionRun) -> MetadataWriteRunStatus:
        events = self._write_store.events_for_run(run.id)
        if not events:
            _operator_fail(MetadataWriteOperatorErrorCode.INTERNAL_ERROR)
        return events[-1].status

    def _latest_event_time(self, run: MetadataWriteExecutionRun) -> datetime:
        events = self._write_store.events_for_run(run.id)
        if not events:
            _operator_fail(MetadataWriteOperatorErrorCode.INTERNAL_ERROR)
        return events[-1].occurred_at

    @staticmethod
    def _result_from_reconciliation(
        plan: MetadataCorrectionPlan,
        reconciliation: MetadataWriteReconciliationSnapshot,
    ) -> MetadataWriteOperationResult:
        return MetadataWriteOperationResult(
            authorization_id=reconciliation.authorization_id,
            run_id=reconciliation.run_id,
            plan_id=plan.id,
            scan_root_id=plan.candidate.scan_root_id,
            status=MetadataWriteRunStatus(reconciliation.outcome.value),
            scan_run_id=reconciliation.scan_run_id,
            observation_id=reconciliation.observation_id,
            collection_state_snapshot_id=reconciliation.collection_state_snapshot_id,
        )


def create_metadata_write_operator_service(
    engine: Engine,
    private_stage_root: Path,
    *,
    metadata_executable: str = "ebook-meta",
    text_executable: str = "ebook-convert",
    cover_executable: str = "calibre-debug",
    java_executable: str = "java",
    epubcheck_jar: Path = Path("epubcheck.jar"),
) -> MetadataWriteOperatorService:
    """Compose the fixed validator behind the application boundary."""

    validator = FixedEpubTitleStagingValidator(
        metadata_executable=metadata_executable,
        text_executable=text_executable,
        cover_executable=cover_executable,
        java_executable=java_executable,
        epubcheck_jar=epubcheck_jar,
    )
    return MetadataWriteOperatorService(
        engine,
        private_stage_root,
        validator=validator,
    )


def _private_stage_directory(
    root: Path,
    capability: ResolvedMetadataWriteCapability,
    owner_id: EntityId,
    fence_epoch: int,
    phase: str,
) -> Path:
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or phase not in {"preparation", "execution"}
    ):
        _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
    try:
        resolved = root.resolve(strict=True)
        details = root.lstat()
        protected = (
            capability.scan_root_directory.resolve(strict=True),
            capability.recovery_directory.resolve(strict=True),
        )
    except OSError:
        _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
    if (
        resolved != root
        or not stat.S_ISDIR(details.st_mode)
        or root.is_symlink()
        or int(getattr(details, "st_file_attributes", 0)) & _REPARSE_POINT
        or any(
            resolved == value or resolved in value.parents or value in resolved.parents
            for value in protected
        )
    ):
        _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
    geteuid = getattr(os, "geteuid", None)
    if os.name == "posix" and (
        not callable(geteuid)
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        _operator_fail(MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE)
    target = root / f"metadata-write-{phase}-{owner_id}-{fence_epoch}"
    if target.exists() or os.path.lexists(target):
        _operator_fail(MetadataWriteOperatorErrorCode.VALIDATION_FAILED)
    return target


def _execute_status_error(
    status: MetadataWriteRunStatus,
) -> MetadataWriteOperatorErrorCode:
    if status in {
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        MetadataWriteRunStatus.RECOVERED,
    }:
        return MetadataWriteOperatorErrorCode.RECOVERY_REQUIRED
    return {
        MetadataWriteRunStatus.STALE: MetadataWriteOperatorErrorCode.STALE,
        MetadataWriteRunStatus.TOOL_UNAVAILABLE: (MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE),
        MetadataWriteRunStatus.VALIDATION_FAILED: (
            MetadataWriteOperatorErrorCode.VALIDATION_FAILED
        ),
        MetadataWriteRunStatus.FENCED_OUT: MetadataWriteOperatorErrorCode.FENCED_OUT,
        MetadataWriteRunStatus.CANCELLED: MetadataWriteOperatorErrorCode.RUN_UNAVAILABLE,
    }.get(status, MetadataWriteOperatorErrorCode.INTERNAL_ERROR)


def _executor_error_code(
    error: MetadataWriteExecutorError,
) -> MetadataWriteOperatorErrorCode:
    return {
        MetadataWriteExecutorErrorCode.STALE: MetadataWriteOperatorErrorCode.STALE,
        MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE: (
            MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE
        ),
        MetadataWriteExecutorErrorCode.VALIDATION_FAILED: (
            MetadataWriteOperatorErrorCode.VALIDATION_FAILED
        ),
        MetadataWriteExecutorErrorCode.FENCED_OUT: (MetadataWriteOperatorErrorCode.FENCED_OUT),
        MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED: (
            MetadataWriteOperatorErrorCode.MANUAL_RECOVERY_REQUIRED
        ),
    }[error.code]


def _backend_error_code(error: LinuxMetadataWriteBackendError) -> MetadataWriteOperatorErrorCode:
    return {
        LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE: (
            MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE
        ),
        LinuxMetadataWriteBackendErrorCode.SOURCE_STALE: MetadataWriteOperatorErrorCode.STALE,
        LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID: (
            MetadataWriteOperatorErrorCode.VALIDATION_FAILED
        ),
        LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS: (
            MetadataWriteOperatorErrorCode.MANUAL_RECOVERY_REQUIRED
        ),
        LinuxMetadataWriteBackendErrorCode.IO_FAILED: (
            MetadataWriteOperatorErrorCode.TOOL_UNAVAILABLE
        ),
    }[error.code]


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _operator_fail(MetadataWriteOperatorErrorCode.FENCED_OUT)
    return value.astimezone(UTC)


def _operator_fail(code: MetadataWriteOperatorErrorCode) -> NoReturn:
    raise MetadataWriteOperatorError(code) from None


__all__ = [
    "METADATA_WRITE_OPERATOR_PROFILE",
    "METADATA_WRITE_STAGE_ROOT_ENV",
    "MetadataWriteAuthorizationResult",
    "MetadataWriteOperationResult",
    "MetadataWriteOperatorError",
    "MetadataWriteOperatorErrorCode",
    "MetadataWriteOperatorService",
    "MetadataWritePreparationSourceReader",
    "MetadataWriteReconciler",
    "MetadataWriteScanReconciliation",
    "SQLiteMetadataWriteReconciler",
    "create_metadata_write_operator_service",
]
