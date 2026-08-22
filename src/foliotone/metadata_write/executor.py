"""Fenced MW04 executor and crash recovery for one authorized EPUB title write."""

from __future__ import annotations

import io
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import NoReturn, Protocol

from foliotone.core import EntityId
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.metadata_write.authorization import (
    MetadataWriteAuthorizationSnapshot,
    MetadataWriteExecutionEvent,
    MetadataWriteExecutionRun,
    MetadataWriteRunStatus,
)
from foliotone.metadata_write.capabilities import ResolvedMetadataWriteCapability
from foliotone.metadata_write.contracts import (
    EpubConformanceStatus,
    EpubInputConformance,
    EpubPublicationKind,
    EpubTitleWriteContractError,
)
from foliotone.metadata_write.epub_title import (
    build_epub3_title_package_patch,
    preflight_epub3_title_write,
)
from foliotone.metadata_write.linux_backend import (
    LinuxMetadataWriteBackend,
    LinuxMetadataWriteBackendError,
    LinuxMetadataWriteBackendErrorCode,
    LinuxMetadataWritePhysicalSnapshot,
    LinuxMetadataWritePhysicalState,
)
from foliotone.metadata_write.staging import EpubTitleStagingError
from foliotone.metadata_write.validation import (
    EpubTitleVerifiedStage,
    FixedEpubTitleStagingValidator,
    build_and_verify_private_epub3_title_stage,
)
from foliotone.persistence.metadata_write import (
    MetadataWriteSourceSnapshot,
    MetadataWriteStoreError,
    SQLiteMetadataWriteStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease

_REPARSE_POINT = 0x0400
MIN_METADATA_WRITE_MUTATION_LEASE_REMAINING = timedelta(minutes=2)


class MetadataWriteExecutorErrorCode(StrEnum):
    """Fixed path-, hash-, and metadata-free executor failures."""

    STALE = "STALE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"


class MetadataWriteExecutorError(RuntimeError):
    """One bounded application failure with no private material."""

    def __init__(self, code: MetadataWriteExecutorErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class MetadataWriteExecutionResult:
    """Opaque outcome of one execution or recovery invocation."""

    run_id: EntityId
    status: MetadataWriteRunStatus


class MetadataWriteFilesystemSession(Protocol):
    """Internal fixed filesystem operations used by the application executor."""

    def __enter__(self) -> MetadataWriteFilesystemSession: ...

    def __exit__(self, *_args: object) -> None: ...

    def close(self) -> None: ...

    def read_source_bytes(self) -> bytes: ...

    def prepare_output(self, staged_output: Path) -> LinuxMetadataWritePhysicalSnapshot: ...

    def revalidate_prepared(self) -> LinuxMetadataWritePhysicalSnapshot: ...

    def exchange(self) -> LinuxMetadataWritePhysicalSnapshot: ...

    def preserve_original(self) -> LinuxMetadataWritePhysicalSnapshot: ...

    def restore_original(self) -> LinuxMetadataWritePhysicalSnapshot: ...

    def classify(self) -> LinuxMetadataWritePhysicalSnapshot: ...

    def confirmation_for(
        self,
        state: LinuxMetadataWritePhysicalState,
    ) -> LinuxMetadataWritePhysicalSnapshot: ...


class MetadataWriteFilesystemBackend(Protocol):
    """Backend seam that never accepts caller-selected names or flags."""

    def open_session(
        self,
        *,
        capability: ResolvedMetadataWriteCapability,
        source_relative_path: str,
        authorization: MetadataWriteAuthorizationSnapshot,
        run: MetadataWriteExecutionRun,
        expected_modified_at: datetime,
    ) -> MetadataWriteFilesystemSession: ...


def execute_epub3_title_metadata_write(
    *,
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    authorization: MetadataWriteAuthorizationSnapshot,
    plan: MetadataCorrectionPlan,
    capability: ResolvedMetadataWriteCapability,
    lease: OwnedScanRootWriteLease,
    private_stage_root: Path,
    clock: Callable[[], datetime] | None = None,
    backend: MetadataWriteFilesystemBackend | None = None,
    validator: FixedEpubTitleStagingValidator | None = None,
) -> MetadataWriteExecutionResult:
    """Execute exactly one bound title replacement and preserve the original.

    Success intentionally stops at ``ORIGINAL_PRESERVED``.  MW05 owns the new
    scan, reconciliation, and final ``VERIFIED`` transition.
    """

    active_clock = clock if clock is not None else _system_clock
    at = _clock_time(active_clock)
    session: MetadataWriteFilesystemSession | None = None
    try:
        stage_directory = _private_stage_directory(
            private_stage_root,
            capability,
            run,
            lease,
        )
        store.bind_backend(
            run,
            authorization,
            plan,
            lease,
            bound_at=at,
        )
        source_at = _clock_time(active_clock)
        source = store.require_execution_source(
            run,
            authorization,
            plan,
            lease,
            checked_at=source_at,
        )
        filesystem = backend if backend is not None else LinuxMetadataWriteBackend()
        session = filesystem.open_session(
            capability=capability,
            source_relative_path=source.relative_path,
            authorization=authorization,
            run=run,
            expected_modified_at=source.expected_modified_at,
        )
        return _execute_session(
            store=store,
            session=session,
            run=run,
            authorization=authorization,
            plan=plan,
            lease=lease,
            source=source,
            stage_directory=stage_directory,
            clock=active_clock,
            validator=validator,
        )
    except Exception as error:
        code = _error_code(error)
        failure_at = _clock_time(active_clock)
        events = _events_or_fenced(store, run.id)
        if session is not None and _exchange_may_have_started(events):
            try:
                _recover_session(
                    store=store,
                    session=session,
                    run=run,
                    authorization=authorization,
                    plan=plan,
                    lease=lease,
                    clock=active_clock,
                    failure_status=(
                        MetadataWriteRunStatus.FENCED_OUT
                        if code is MetadataWriteExecutorErrorCode.FENCED_OUT
                        else MetadataWriteRunStatus.VALIDATION_FAILED
                    ),
                )
            except Exception as recovery_error:
                recovery_code = _error_code(recovery_error)
                if recovery_code is MetadataWriteExecutorErrorCode.FENCED_OUT:
                    _raise(recovery_code)
                _require_manual_event(store, run, lease, failure_at)
                _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
        else:
            status = _status_for_error(code)
            if not _append_terminal_if_possible(
                store,
                run,
                lease,
                status,
                failure_at,
            ):
                _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)
        _raise(code)
    finally:
        if session is not None:
            _close_session(session)


def recover_epub3_title_metadata_write(
    *,
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    authorization: MetadataWriteAuthorizationSnapshot,
    plan: MetadataCorrectionPlan,
    capability: ResolvedMetadataWriteCapability,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime] | None = None,
    backend: MetadataWriteFilesystemBackend | None = None,
) -> MetadataWriteExecutionResult:
    """Idempotently restore only an exact pre-VERIFIED physical distribution."""

    active_clock = clock if clock is not None else _system_clock
    at = _clock_time(active_clock)
    events = _events_or_fenced(store, run.id)
    latest = _latest_status(events)
    if latest in {
        MetadataWriteRunStatus.VERIFIED,
        MetadataWriteRunStatus.RECOVERED,
        MetadataWriteRunStatus.CANCELLED,
        MetadataWriteRunStatus.STALE,
        MetadataWriteRunStatus.TOOL_UNAVAILABLE,
    } or (
        latest
        in {
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
        }
        and not _exchange_recorded(events)
    ):
        return MetadataWriteExecutionResult(run.id, latest)

    try:
        binding = store.get_backend_binding(run.id)
    except Exception:
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)
    if binding is None:
        if latest is MetadataWriteRunStatus.CREATED:
            _append_simple(
                store,
                run,
                lease,
                MetadataWriteRunStatus.CANCELLED,
                at,
                finding_code="NO_BACKEND_BOUND",
            )
            return MetadataWriteExecutionResult(
                run.id,
                MetadataWriteRunStatus.CANCELLED,
            )
        _require_manual_event(store, run, lease, at)
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)

    session: MetadataWriteFilesystemSession | None = None
    try:
        source = store.require_recovery_source(
            run,
            authorization,
            plan,
            lease,
            checked_at=at,
        )
        filesystem = backend if backend is not None else LinuxMetadataWriteBackend()
        session = filesystem.open_session(
            capability=capability,
            source_relative_path=source.relative_path,
            authorization=authorization,
            run=run,
            expected_modified_at=source.expected_modified_at,
        )
        status = _recover_session(
            store=store,
            session=session,
            run=run,
            authorization=authorization,
            plan=plan,
            lease=lease,
            clock=active_clock,
            failure_status=None,
        )
        return MetadataWriteExecutionResult(run.id, status)
    except Exception as error:
        code = _error_code(error)
        if code is MetadataWriteExecutorErrorCode.FENCED_OUT:
            _raise(code)
        _require_manual_event(
            store,
            run,
            lease,
            _clock_time(active_clock),
        )
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
    finally:
        if session is not None:
            _close_session(session)


def _execute_session(
    *,
    store: SQLiteMetadataWriteStore,
    session: MetadataWriteFilesystemSession,
    run: MetadataWriteExecutionRun,
    authorization: MetadataWriteAuthorizationSnapshot,
    plan: MetadataCorrectionPlan,
    lease: OwnedScanRootWriteLease,
    source: MetadataWriteSourceSnapshot,
    stage_directory: Path,
    clock: Callable[[], datetime],
    validator: FixedEpubTitleStagingValidator | None,
) -> MetadataWriteExecutionResult:
    source_bytes = session.read_source_bytes()
    conformance = EpubInputConformance(
        input_sha256=authorization.source_sha256,
        publication_kind=EpubPublicationKind.EPUB3,
        status=EpubConformanceStatus.CONFORMANT,
    )
    preflight = preflight_epub3_title_write(plan, source_bytes, conformance)
    patch = build_epub3_title_package_patch(
        preflight,
        authorized_at=authorization.authorized_at,
    )
    verified = build_and_verify_private_epub3_title_stage(
        stage_directory,
        io.BytesIO(source_bytes),
        preflight,
        patch,
        validator=validator,
    )
    _require_authorized_stage(verified, authorization)

    before_draft_at = _clock_time(clock)
    _require_mutation_window(lease, before_draft_at)
    current_source = store.require_execution_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=before_draft_at,
    )
    if current_source != source:
        _raise(MetadataWriteExecutorErrorCode.STALE)
    session.prepare_output(verified.staged_files.output_path)

    prepared_at = _clock_time(clock)
    _require_mutation_window(lease, prepared_at)
    current_source = store.require_execution_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=prepared_at,
    )
    if current_source != source:
        _raise(MetadataWriteExecutorErrorCode.STALE)
    prepared = session.revalidate_prepared()
    _require_state(
        prepared,
        LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT,
    )
    _append_phase(
        store,
        run,
        lease,
        MetadataWriteRunStatus.PREPARED,
        prepared_at,
        prepared,
    )

    exchange_gate_at = _clock_time(clock)
    _require_mutation_window(lease, exchange_gate_at)
    store.require_prepared_execution_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=exchange_gate_at,
    )
    exchanged = session.exchange()
    _require_state(
        exchanged,
        LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT,
    )
    exchanged_at = _clock_time(clock)
    _append_phase(
        store,
        run,
        lease,
        MetadataWriteRunStatus.EXCHANGED,
        exchanged_at,
        exchanged,
    )

    preserve_at = _clock_time(clock)
    _require_mutation_window(lease, preserve_at)
    store.require_recovery_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=preserve_at,
    )
    preserved = session.preserve_original()
    _require_state(
        preserved,
        LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL,
    )
    _append_phase(
        store,
        run,
        lease,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        _clock_time(clock),
        preserved,
    )
    return MetadataWriteExecutionResult(
        run.id,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
    )


def _recover_session(
    *,
    store: SQLiteMetadataWriteStore,
    session: MetadataWriteFilesystemSession,
    run: MetadataWriteExecutionRun,
    authorization: MetadataWriteAuthorizationSnapshot,
    plan: MetadataCorrectionPlan,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
    failure_status: MetadataWriteRunStatus | None,
) -> MetadataWriteRunStatus:
    checked_at = _clock_time(clock)
    store.require_recovery_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=checked_at,
    )
    physical = session.classify()
    events = _events_or_fenced(store, run.id)
    latest = _latest_status(events)

    if physical.state is LinuxMetadataWritePhysicalState.AMBIGUOUS:
        _require_manual_event(store, run, lease, _clock_time(clock))
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)

    if physical.state is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY:
        if latest is MetadataWriteRunStatus.CREATED:
            _append_simple(
                store,
                run,
                lease,
                MetadataWriteRunStatus.CANCELLED,
                _clock_time(clock),
                finding_code="NO_MUTATION_OBSERVED",
                snapshot=physical,
            )
            return MetadataWriteRunStatus.CANCELLED
        _require_manual_event(store, run, lease, _clock_time(clock))
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)

    if physical.state is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT:
        if _exchange_recorded(events):
            _append_simple(
                store,
                run,
                lease,
                MetadataWriteRunStatus.RECOVERED,
                _clock_time(clock),
                finding_code="ORIGINAL_RESTORED",
                snapshot=physical,
            )
            return MetadataWriteRunStatus.RECOVERED
        if latest in {MetadataWriteRunStatus.CREATED, MetadataWriteRunStatus.PREPARED}:
            status = failure_status or MetadataWriteRunStatus.CANCELLED
            _append_simple(
                store,
                run,
                lease,
                status,
                _clock_time(clock),
                finding_code=(
                    "PREPARED_EXECUTION_FAILED"
                    if failure_status is not None
                    else "PREPARED_WITHOUT_EXCHANGE"
                ),
                snapshot=physical,
            )
            return status
        if latest is MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED:
            _append_simple(
                store,
                run,
                lease,
                MetadataWriteRunStatus.RECOVERED,
                _clock_time(clock),
                finding_code="ORIGINAL_RESTORED",
                snapshot=physical,
            )
            return MetadataWriteRunStatus.RECOVERED
        _require_manual_event(store, run, lease, _clock_time(clock))
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)

    latest = _synchronize_exchange_events(
        store,
        session,
        run,
        lease,
        clock,
        physical,
    )
    if failure_status is not None and latest in {
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
    }:
        _append_simple(
            store,
            run,
            lease,
            failure_status,
            _clock_time(clock),
            finding_code="POST_EXCHANGE_FAILURE",
            snapshot=physical,
        )

    restore_at = _clock_time(clock)
    _require_mutation_window(lease, restore_at)
    store.require_recovery_source(
        run,
        authorization,
        plan,
        lease,
        checked_at=restore_at,
    )
    try:
        restored = session.restore_original()
    except LinuxMetadataWriteBackendError:
        restored = session.classify()
    if (
        restored.state
        is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
    ):
        _require_manual_event(store, run, lease, _clock_time(clock))
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
    _append_simple(
        store,
        run,
        lease,
        MetadataWriteRunStatus.RECOVERED,
        _clock_time(clock),
        finding_code="ORIGINAL_RESTORED",
        snapshot=restored,
    )
    return MetadataWriteRunStatus.RECOVERED


def _synchronize_exchange_events(
    store: SQLiteMetadataWriteStore,
    session: MetadataWriteFilesystemSession,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
    physical: LinuxMetadataWritePhysicalSnapshot,
) -> MetadataWriteRunStatus:
    latest = _latest_status(_events_or_fenced(store, run.id))
    if latest is MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED:
        return latest
    if latest is MetadataWriteRunStatus.PREPARED:
        exchanged = session.confirmation_for(
            LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        )
        _append_phase(
            store,
            run,
            lease,
            MetadataWriteRunStatus.EXCHANGED,
            _clock_time(clock),
            exchanged,
            finding_code="CRASH_PHASE_RECONSTRUCTED",
        )
        latest = MetadataWriteRunStatus.EXCHANGED
    if (
        physical.state
        is LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
        and latest is MetadataWriteRunStatus.EXCHANGED
    ):
        _append_phase(
            store,
            run,
            lease,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            _clock_time(clock),
            physical,
            finding_code="CRASH_PHASE_RECONSTRUCTED",
        )
        latest = MetadataWriteRunStatus.ORIGINAL_PRESERVED
    if latest not in {
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
    }:
        _raise(MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
    return latest


def _require_authorized_stage(
    verified: EpubTitleVerifiedStage,
    authorization: MetadataWriteAuthorizationSnapshot,
) -> None:
    staged = verified.staged_files
    validation = verified.validation
    if (
        staged.plan_id != authorization.plan_id
        or staged.plan_content_hash != authorization.plan_content_hash
        or staged.input_sha256 != authorization.source_sha256
        or staged.input_size_bytes != authorization.source_size_bytes
        or staged.output_sha256 != authorization.expected_output_sha256
        or staged.output_size_bytes != authorization.expected_output_size_bytes
        or validation.output_sha256 != authorization.expected_output_sha256
        or validation.metadata_tool_version != authorization.metadata_tool_version
        or validation.epubcheck_tool_version != authorization.epubcheck_tool_version
        or validation.text_tool_version != authorization.text_tool_version
        or validation.cover_tool_version != authorization.cover_tool_version
        or validation.validator_set_fingerprint
        != authorization.validator_set_fingerprint
    ):
        _raise(MetadataWriteExecutorErrorCode.VALIDATION_FAILED)


def _private_stage_directory(
    root: Path,
    capability: ResolvedMetadataWriteCapability,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
) -> Path:
    if not isinstance(root, Path) or not root.is_absolute():
        _raise(MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE)
    try:
        resolved = root.resolve(strict=True)
        details = root.lstat()
        protected = (
            capability.scan_root_directory.resolve(strict=True),
            capability.recovery_directory.resolve(strict=True),
        )
    except OSError:
        _raise(MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE)
    if (
        resolved != root
        or not stat.S_ISDIR(details.st_mode)
        or root.is_symlink()
        or int(getattr(details, "st_file_attributes", 0)) & _REPARSE_POINT
        or any(
            resolved == value
            or resolved in value.parents
            or value in resolved.parents
            for value in protected
        )
    ):
        _raise(MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE)
    geteuid = getattr(os, "geteuid", None)
    if os.name == "posix" and (
        not callable(geteuid)
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        _raise(MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE)
    target = root / f"metadata-write-{run.id}-{lease.fence_epoch}"
    if target.exists() or os.path.lexists(target):
        _raise(MetadataWriteExecutorErrorCode.VALIDATION_FAILED)
    return target


def _append_phase(
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: MetadataWriteRunStatus,
    occurred_at: datetime,
    snapshot: LinuxMetadataWritePhysicalSnapshot,
    *,
    finding_code: str | None = None,
) -> None:
    _append_simple(
        store,
        run,
        lease,
        status,
        occurred_at,
        finding_code=finding_code,
        snapshot=snapshot,
    )


def _append_simple(
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: MetadataWriteRunStatus,
    occurred_at: datetime,
    *,
    finding_code: str | None = None,
    snapshot: LinuxMetadataWritePhysicalSnapshot | None = None,
) -> None:
    events = store.events_for_run(run.id)
    store.append_event(
        MetadataWriteExecutionEvent(
            run_id=run.id,
            sequence_no=len(events) + 1,
            status=status,
            occurred_at=occurred_at,
            fence_epoch=lease.fence_epoch,
            finding_code=finding_code,
            confirmation_digest=(
                None if snapshot is None else snapshot.confirmation_digest
            ),
        ),
        lease,
    )


def _append_terminal_if_possible(
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: MetadataWriteRunStatus,
    occurred_at: datetime,
) -> bool:
    try:
        latest = _latest_status(store.events_for_run(run.id))
        if latest in {
            MetadataWriteRunStatus.STALE,
            MetadataWriteRunStatus.TOOL_UNAVAILABLE,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
            MetadataWriteRunStatus.CANCELLED,
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            MetadataWriteRunStatus.VERIFIED,
        }:
            return True
        _append_simple(
            store,
            run,
            lease,
            status,
            occurred_at,
            finding_code=status.value,
        )
        return True
    except Exception:
        return False


def _append_manual_if_possible(
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    occurred_at: datetime,
) -> bool:
    try:
        events = store.events_for_run(run.id)
        if not events:
            return False
        if events[-1].status is MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED:
            return True
        _append_simple(
            store,
            run,
            lease,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            occurred_at,
            finding_code="PHYSICAL_STATE_AMBIGUOUS",
        )
    except Exception:
        return False
    return True


def _require_manual_event(
    store: SQLiteMetadataWriteStore,
    run: MetadataWriteExecutionRun,
    lease: OwnedScanRootWriteLease,
    occurred_at: datetime,
) -> None:
    if not _append_manual_if_possible(store, run, lease, occurred_at):
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)


def _events_or_fenced(
    store: SQLiteMetadataWriteStore,
    run_id: EntityId,
) -> tuple[MetadataWriteExecutionEvent, ...]:
    try:
        return store.events_for_run(run_id)
    except Exception:
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)


def _close_session(session: MetadataWriteFilesystemSession) -> None:
    try:
        session.close()
    except Exception:
        # Closing an already-opened directory descriptor does not mutate media.
        # The operation outcome is determined by the classified/journaled state.
        pass


def _require_state(
    snapshot: LinuxMetadataWritePhysicalSnapshot,
    expected: LinuxMetadataWritePhysicalState,
) -> None:
    if snapshot.state is not expected:
        raise LinuxMetadataWriteBackendError(
            LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS,
            mutation_may_have_occurred=(
                expected
                is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
            ),
        )


def _exchange_may_have_started(
    events: tuple[MetadataWriteExecutionEvent, ...],
) -> bool:
    return any(event.status is MetadataWriteRunStatus.PREPARED for event in events)


def _exchange_recorded(events: tuple[MetadataWriteExecutionEvent, ...]) -> bool:
    return any(event.status is MetadataWriteRunStatus.EXCHANGED for event in events)


def _latest_status(
    events: tuple[MetadataWriteExecutionEvent, ...],
) -> MetadataWriteRunStatus:
    if not events or events[0].status is not MetadataWriteRunStatus.CREATED:
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)
    return events[-1].status


def _status_for_error(
    code: MetadataWriteExecutorErrorCode,
) -> MetadataWriteRunStatus:
    return {
        MetadataWriteExecutorErrorCode.STALE: MetadataWriteRunStatus.STALE,
        MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE: (
            MetadataWriteRunStatus.TOOL_UNAVAILABLE
        ),
        MetadataWriteExecutorErrorCode.VALIDATION_FAILED: (
            MetadataWriteRunStatus.VALIDATION_FAILED
        ),
        MetadataWriteExecutorErrorCode.FENCED_OUT: MetadataWriteRunStatus.FENCED_OUT,
        MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED: (
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED
        ),
    }[code]


def _error_code(error: Exception) -> MetadataWriteExecutorErrorCode:
    if isinstance(error, MetadataWriteExecutorError):
        return error.code
    if isinstance(error, LinuxMetadataWriteBackendError):
        return {
            LinuxMetadataWriteBackendErrorCode.SOURCE_STALE: (
                MetadataWriteExecutorErrorCode.STALE
            ),
            LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE: (
                MetadataWriteExecutorErrorCode.TOOL_UNAVAILABLE
            ),
            LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID: (
                MetadataWriteExecutorErrorCode.VALIDATION_FAILED
            ),
            LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS: (
                MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED
            ),
            LinuxMetadataWriteBackendErrorCode.IO_FAILED: (
                MetadataWriteExecutorErrorCode.VALIDATION_FAILED
            ),
        }[error.code]
    if isinstance(error, MetadataWriteStoreError):
        return MetadataWriteExecutorErrorCode.FENCED_OUT
    if isinstance(error, (EpubTitleStagingError, EpubTitleWriteContractError)):
        return MetadataWriteExecutorErrorCode.VALIDATION_FAILED
    return MetadataWriteExecutorErrorCode.VALIDATION_FAILED


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _clock_time(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)
    return value.astimezone(UTC)


def _require_mutation_window(
    lease: OwnedScanRootWriteLease,
    checked_at: datetime,
) -> None:
    if (
        checked_at < lease.acquired_at
        or checked_at + MIN_METADATA_WRITE_MUTATION_LEASE_REMAINING
        >= lease.lease_expires_at
    ):
        _raise(MetadataWriteExecutorErrorCode.FENCED_OUT)


def _raise(code: MetadataWriteExecutorErrorCode) -> NoReturn:
    raise MetadataWriteExecutorError(code) from None


__all__ = [
    "MIN_METADATA_WRITE_MUTATION_LEASE_REMAINING",
    "MetadataWriteExecutionResult",
    "MetadataWriteExecutorError",
    "MetadataWriteExecutorErrorCode",
    "MetadataWriteFilesystemBackend",
    "MetadataWriteFilesystemSession",
    "execute_epub3_title_metadata_write",
    "recover_epub3_title_metadata_write",
]
