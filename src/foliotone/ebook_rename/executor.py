"""Fenced RN03 executor and exact-state recovery for one e-book rename."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NoReturn, Protocol

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.ebook_rename.authority import (
    EbookRenameAuthorizationSnapshot,
    EbookRenameBackendBinding,
    EbookRenameCapabilityProbeSnapshot,
    EbookRenameExecutionEvent,
    EbookRenameExecutionRun,
    EbookRenamePreparationSnapshot,
    EbookRenameRunStatus,
)
from foliotone.ebook_rename.capabilities import ResolvedEbookRenameCapability
from foliotone.ebook_rename.linux_backend import (
    LinuxEbookRenameBackend,
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
    LinuxEbookRenamePhysicalSnapshot,
    LinuxEbookRenamePhysicalState,
)
from foliotone.persistence.ebook_rename import (
    EbookRenameSourceSnapshot,
    EbookRenameStoreError,
    SQLiteEbookRenameStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease

MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING = timedelta(minutes=2)

_TERMINAL_STATUSES = frozenset(
    {
        EbookRenameRunStatus.VERIFIED,
        EbookRenameRunStatus.CANCELLED,
        EbookRenameRunStatus.RECOVERED,
        EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
    }
)


class EbookRenameExecutorErrorCode(StrEnum):
    """Fixed locator-, hash-, attribute-, and fence-free executor failures."""

    STALE = "STALE"
    TARGET_COLLISION = "TARGET_COLLISION"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    IO_FAILED = "IO_FAILED"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"


class EbookRenameExecutorError(RuntimeError):
    """One bounded application failure without private runtime material."""

    def __init__(self, code: EbookRenameExecutorErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class EbookRenameExecutionResult:
    """Opaque outcome of one execution or recovery invocation."""

    run_id: EntityId
    status: EbookRenameRunStatus


class EbookRenameFilesystemSession(Protocol):
    """Internal fixed filesystem operations used by the application executor."""

    def __enter__(self) -> EbookRenameFilesystemSession: ...

    def __exit__(self, *_args: object) -> None: ...

    def close(self) -> None: ...

    def classify(self) -> LinuxEbookRenamePhysicalSnapshot: ...

    def revalidate_forward_preconditions(self) -> LinuxEbookRenamePhysicalSnapshot: ...

    def rename_forward(self) -> None: ...

    def verify_forward(self) -> LinuxEbookRenamePhysicalSnapshot: ...

    def rename_reverse(self) -> None: ...

    def verify_recovery(self) -> LinuxEbookRenamePhysicalSnapshot: ...


class EbookRenameFilesystemBackend(Protocol):
    """Backend seam that accepts neither caller-selected flags nor commands."""

    def open_session(
        self,
        *,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        source_relative_locator: str,
        target_relative_locator: str,
    ) -> EbookRenameFilesystemSession: ...


def execute_ebook_file_rename(
    *,
    store: SQLiteEbookRenameStore,
    plan: EbookOperationRecipePlan,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime] | None = None,
    backend: EbookRenameFilesystemBackend | None = None,
) -> EbookRenameExecutionResult:
    """Execute one no-replace rename and stop at ``IMMEDIATE_VERIFIED``.

    RN04 owns scan handoff, reconciliation, and the terminal ``VERIFIED``
    transition.  A retry after the first journal phase enters the same exact
    recovery matrix instead of creating another rename attempt.
    """

    active_clock = clock if clock is not None else _system_clock
    initial_events = _events_or_fenced(store, run.id)
    latest = initial_events[-1].status
    if latest is not EbookRenameRunStatus.PREPARED:
        return recover_ebook_file_rename(
            store=store,
            plan=plan,
            preparation=preparation,
            authorization=authorization,
            capability=capability,
            probe=probe,
            binding=binding,
            run=run,
            lease=lease,
            clock=active_clock,
            backend=backend,
        )
    if _clock_time(active_clock) >= authorization.expires_at:
        return recover_ebook_file_rename(
            store=store,
            plan=plan,
            preparation=preparation,
            authorization=authorization,
            capability=capability,
            probe=probe,
            binding=binding,
            run=run,
            lease=lease,
            clock=active_clock,
            backend=backend,
        )

    session: EbookRenameFilesystemSession | None = None
    original_error: EbookRenameExecutorErrorCode | None = None
    try:
        checked_at = _clock_time(active_clock)
        _require_mutation_window(lease, checked_at, authorization=authorization)
        source = store.require_execution_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=checked_at,
        )
        filesystem = backend if backend is not None else LinuxEbookRenameBackend()
        session = _open_session(
            filesystem,
            source,
            capability,
            probe,
            preparation,
            authorization,
            binding,
            run,
        )
        immediately_before = _clock_time(active_clock)
        _require_mutation_window(
            lease,
            immediately_before,
            authorization=authorization,
        )
        store.require_execution_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=immediately_before,
        )
        _require_state(
            session.revalidate_forward_preconditions(),
            LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
        )
        session.rename_forward()
        _append(
            store,
            run,
            lease,
            EbookRenameRunStatus.RELOCATED,
            "RENAME_RELOCATED",
            _clock_time(active_clock),
        )
        postcheck_at = _clock_time(active_clock)
        store.require_recovery_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=postcheck_at,
        )
        _require_state(
            session.verify_forward(),
            LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT,
        )
        _append(
            store,
            run,
            lease,
            EbookRenameRunStatus.IMMEDIATE_VERIFIED,
            "IMMEDIATE_VERIFICATION_PASSED",
            _clock_time(active_clock),
        )
        return EbookRenameExecutionResult(
            run_id=run.id,
            status=EbookRenameRunStatus.IMMEDIATE_VERIFIED,
        )
    except Exception as error:
        original_error = _error_code(error)
        if original_error is EbookRenameExecutorErrorCode.FENCED_OUT:
            _raise(original_error)
        if session is None:
            _raise(original_error)
        try:
            _recover_session(
                store=store,
                session=session,
                plan=plan,
                preparation=preparation,
                authorization=authorization,
                capability=capability,
                probe=probe,
                binding=binding,
                run=run,
                lease=lease,
                clock=active_clock,
            )
        except Exception as recovery_error:
            recovery_code = _error_code(recovery_error)
            if recovery_code is EbookRenameExecutorErrorCode.FENCED_OUT:
                _raise(recovery_code)
            _append_manual_if_possible(store, run, lease, active_clock)
            _raise(EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
        if original_error is EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED:
            original_error = EbookRenameExecutorErrorCode.STALE
        _raise(original_error)
    finally:
        if session is not None:
            _close_session(session)


def recover_ebook_file_rename(
    *,
    store: SQLiteEbookRenameStore,
    plan: EbookOperationRecipePlan,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime] | None = None,
    backend: EbookRenameFilesystemBackend | None = None,
) -> EbookRenameExecutionResult:
    """Apply only the ADR-0066 matrix to one already-created execution run."""

    active_clock = clock if clock is not None else _system_clock
    events = _events_or_fenced(store, run.id)
    latest = events[-1].status
    if latest in _TERMINAL_STATUSES:
        return EbookRenameExecutionResult(run_id=run.id, status=latest)
    session: EbookRenameFilesystemSession | None = None
    try:
        checked_at = _clock_time(active_clock)
        source = store.require_recovery_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            lease,
            checked_at=checked_at,
        )
        filesystem = backend if backend is not None else LinuxEbookRenameBackend()
        session = _open_session(
            filesystem,
            source,
            capability,
            probe,
            preparation,
            authorization,
            binding,
            run,
        )
        return _recover_session(
            store=store,
            session=session,
            plan=plan,
            preparation=preparation,
            authorization=authorization,
            capability=capability,
            probe=probe,
            binding=binding,
            run=run,
            lease=lease,
            clock=active_clock,
        )
    except Exception as error:
        code = _error_code(error)
        if code is EbookRenameExecutorErrorCode.FENCED_OUT:
            _raise(code)
        _append_manual_if_possible(store, run, lease, active_clock)
        _raise(EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)
    finally:
        if session is not None:
            _close_session(session)


def _recover_session(
    *,
    store: SQLiteEbookRenameStore,
    session: EbookRenameFilesystemSession,
    plan: EbookOperationRecipePlan,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
) -> EbookRenameExecutionResult:
    events = _events_or_fenced(store, run.id)
    latest = events[-1].status
    if latest in _TERMINAL_STATUSES:
        return EbookRenameExecutionResult(run.id, latest)
    physical = session.classify()

    if latest is EbookRenameRunStatus.PREPARED:
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            _append(
                store,
                run,
                lease,
                EbookRenameRunStatus.CANCELLED,
                "SOURCE_UNCHANGED_CANCELLED",
                _clock_time(clock),
            )
            return EbookRenameExecutionResult(run.id, EbookRenameRunStatus.CANCELLED)
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
        ):
            return _reverse_and_verify(
                store=store,
                session=session,
                plan=plan,
                preparation=preparation,
                authorization=authorization,
                capability=capability,
                probe=probe,
                binding=binding,
                run=run,
                lease=lease,
                clock=clock,
            )

    if latest is EbookRenameRunStatus.RELOCATED:
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
        ):
            return _reverse_and_verify(
                store=store,
                session=session,
                plan=plan,
                preparation=preparation,
                authorization=authorization,
                capability=capability,
                probe=probe,
                binding=binding,
                run=run,
                lease=lease,
                clock=clock,
            )
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            _require_state(
                session.verify_recovery(),
                LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
            )
            _append(
                store,
                run,
                lease,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
                "RECOVERY_VERIFICATION_PASSED",
                _clock_time(clock),
            )
            return EbookRenameExecutionResult(
                run.id,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
            )

    if latest is EbookRenameRunStatus.RECOVERY_RELOCATED:
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            _require_state(
                session.verify_recovery(),
                LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
            )
            _append(
                store,
                run,
                lease,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
                "RECOVERY_VERIFICATION_PASSED",
                _clock_time(clock),
            )
            return EbookRenameExecutionResult(
                run.id,
                EbookRenameRunStatus.RECOVERY_VERIFIED,
            )

    if latest is EbookRenameRunStatus.RECOVERY_VERIFIED:
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            return EbookRenameExecutionResult(run.id, latest)

    if latest is EbookRenameRunStatus.IMMEDIATE_VERIFIED:
        if (
            physical.state
            is LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
        ):
            return EbookRenameExecutionResult(run.id, latest)

    if latest is EbookRenameRunStatus.SCAN_HANDOFF and physical.state in {
        LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
        LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT,
    }:
        return EbookRenameExecutionResult(run.id, latest)

    _append(
        store,
        run,
        lease,
        EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
        "PHYSICAL_STATE_AMBIGUOUS",
        _clock_time(clock),
    )
    _raise(EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)


def _reverse_and_verify(
    *,
    store: SQLiteEbookRenameStore,
    session: EbookRenameFilesystemSession,
    plan: EbookOperationRecipePlan,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
) -> EbookRenameExecutionResult:
    immediately_before = _clock_time(clock)
    _require_mutation_window(lease, immediately_before, authorization=None)
    store.require_recovery_source(
        plan,
        preparation,
        authorization,
        capability,
        probe,
        binding,
        run,
        lease,
        checked_at=immediately_before,
    )
    _require_state(
        session.classify(),
        LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT,
    )
    session.rename_reverse()
    _append(
        store,
        run,
        lease,
        EbookRenameRunStatus.RECOVERY_RELOCATED,
        "RECOVERY_RELOCATED",
        _clock_time(clock),
    )
    postcheck_at = _clock_time(clock)
    store.require_recovery_source(
        plan,
        preparation,
        authorization,
        capability,
        probe,
        binding,
        run,
        lease,
        checked_at=postcheck_at,
    )
    _require_state(
        session.verify_recovery(),
        LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
    )
    _append(
        store,
        run,
        lease,
        EbookRenameRunStatus.RECOVERY_VERIFIED,
        "RECOVERY_VERIFICATION_PASSED",
        _clock_time(clock),
    )
    return EbookRenameExecutionResult(run.id, EbookRenameRunStatus.RECOVERY_VERIFIED)


def _open_session(
    backend: EbookRenameFilesystemBackend,
    source: EbookRenameSourceSnapshot,
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
) -> EbookRenameFilesystemSession:
    return backend.open_session(
        capability=capability,
        probe=probe,
        preparation=preparation,
        authorization=authorization,
        binding=binding,
        run=run,
        source_relative_locator=source.source_relative_locator,
        target_relative_locator=source.target_relative_locator,
    )


def _append(
    store: SQLiteEbookRenameStore,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: EbookRenameRunStatus,
    finding_code: str,
    occurred_at: datetime,
) -> None:
    events = store.events_for_run(run.id)
    store.append_event(
        EbookRenameExecutionEvent(
            run_id=run.id,
            sequence_no=len(events) + 1,
            status=status,
            occurred_at=occurred_at,
            fence_epoch=lease.fence_epoch,
            finding_code=finding_code,
        ),
        lease,
    )


def _append_manual_if_possible(
    store: SQLiteEbookRenameStore,
    run: EbookRenameExecutionRun,
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
) -> None:
    try:
        latest = store.events_for_run(run.id)[-1].status
        if latest not in _TERMINAL_STATUSES:
            _append(
                store,
                run,
                lease,
                EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED,
                "PHYSICAL_STATE_AMBIGUOUS",
                _clock_time(clock),
            )
    except Exception:
        pass


def _events_or_fenced(
    store: SQLiteEbookRenameStore,
    run_id: EntityId,
) -> tuple[EbookRenameExecutionEvent, ...]:
    try:
        events = store.events_for_run(run_id)
    except Exception:
        _raise(EbookRenameExecutorErrorCode.FENCED_OUT)
    if not events:
        _raise(EbookRenameExecutorErrorCode.FENCED_OUT)
    return events


def _require_state(
    snapshot: LinuxEbookRenamePhysicalSnapshot,
    expected: LinuxEbookRenamePhysicalState,
) -> None:
    if not isinstance(snapshot, LinuxEbookRenamePhysicalSnapshot) or snapshot.state is not expected:
        _raise(EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED)


def _close_session(session: EbookRenameFilesystemSession) -> None:
    try:
        session.close()
    except Exception:
        pass


def _error_code(error: Exception) -> EbookRenameExecutorErrorCode:
    if isinstance(error, EbookRenameExecutorError):
        return error.code
    if isinstance(error, EbookRenameStoreError):
        return EbookRenameExecutorErrorCode.FENCED_OUT
    if isinstance(error, LinuxEbookRenameBackendError):
        return {
            LinuxEbookRenameBackendErrorCode.SOURCE_STALE: EbookRenameExecutorErrorCode.STALE,
            LinuxEbookRenameBackendErrorCode.TARGET_COLLISION: (
                EbookRenameExecutorErrorCode.TARGET_COLLISION
            ),
            LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE: (
                EbookRenameExecutorErrorCode.TOOL_UNAVAILABLE
            ),
            LinuxEbookRenameBackendErrorCode.IO_FAILED: EbookRenameExecutorErrorCode.IO_FAILED,
            LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS: (
                EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED
            ),
        }[error.code]
    return EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _clock_time(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _raise(EbookRenameExecutorErrorCode.FENCED_OUT)
    return value.astimezone(UTC)


def _require_mutation_window(
    lease: OwnedScanRootWriteLease,
    checked_at: datetime,
    *,
    authorization: EbookRenameAuthorizationSnapshot | None,
) -> None:
    if (
        not isinstance(lease, OwnedScanRootWriteLease)
        or checked_at < lease.acquired_at
        or lease.lease_expires_at - checked_at
        < MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING
        or (
            authorization is not None
            and (
                checked_at < authorization.authorized_at
                or authorization.expires_at - checked_at
                < MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING
            )
        )
    ):
        _raise(EbookRenameExecutorErrorCode.FENCED_OUT)


def _raise(code: EbookRenameExecutorErrorCode) -> NoReturn:
    raise EbookRenameExecutorError(code) from None


__all__ = [
    "MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING",
    "EbookRenameExecutionResult",
    "EbookRenameExecutorError",
    "EbookRenameExecutorErrorCode",
    "EbookRenameFilesystemBackend",
    "EbookRenameFilesystemSession",
    "execute_ebook_file_rename",
    "recover_ebook_file_rename",
]
