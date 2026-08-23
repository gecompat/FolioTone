from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

import pytest

from foliotone.core import EntityId
from foliotone.ebook_rename import (
    EbookRenameExecutionEvent,
    EbookRenameRunStatus,
    build_ebook_rename_backend_binding,
    build_ebook_rename_run,
)
from foliotone.ebook_rename.executor import (
    EbookRenameExecutorError,
    EbookRenameExecutorErrorCode,
    execute_ebook_file_rename,
    recover_ebook_file_rename,
)
from foliotone.ebook_rename.linux_backend import (
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
    LinuxEbookRenamePhysicalSnapshot,
    LinuxEbookRenamePhysicalState,
)
from foliotone.persistence import OwnedScanRootWriteLease, ScanRootWriteOwnerKind
from foliotone.persistence.ebook_rename import (
    EbookRenameSourceSnapshot,
    SQLiteEbookRenameStore,
)
from tests.unit.test_ebook_rename_authority import _material


def _snapshot(state: LinuxEbookRenamePhysicalState) -> LinuxEbookRenamePhysicalSnapshot:
    return LinuxEbookRenamePhysicalSnapshot(state=state, confirmation_digest="f" * 64)


class _Session:
    def __init__(
        self,
        state: LinuxEbookRenamePhysicalState,
        *,
        fail_forward_verification: bool = False,
    ) -> None:
        self.state = state
        self.fail_forward_verification = fail_forward_verification
        self.forward_count = 0
        self.reverse_count = 0
        self.closed = False

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def classify(self) -> LinuxEbookRenamePhysicalSnapshot:
        return _snapshot(self.state)

    def revalidate_forward_preconditions(self) -> LinuxEbookRenamePhysicalSnapshot:
        return _snapshot(self.state)

    def rename_forward(self) -> None:
        self.forward_count += 1
        self.state = LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT

    def verify_forward(self) -> LinuxEbookRenamePhysicalSnapshot:
        if self.fail_forward_verification:
            raise LinuxEbookRenameBackendError(
                LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS
            )
        return _snapshot(self.state)

    def rename_reverse(self) -> None:
        self.reverse_count += 1
        self.state = LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT

    def verify_recovery(self) -> LinuxEbookRenamePhysicalSnapshot:
        return _snapshot(self.state)


class _Backend:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.open_count = 0

    def open_session(self, **_kwargs: object) -> _Session:
        self.open_count += 1
        return self.session


class _Store:
    def __init__(
        self,
        source: EbookRenameSourceSnapshot,
        prepared: EbookRenameExecutionEvent,
    ) -> None:
        self.source = source
        self.events = [prepared]
        self.execution_checks = 0
        self.recovery_checks = 0

    def events_for_run(self, _run_id: EntityId) -> tuple[EbookRenameExecutionEvent, ...]:
        return tuple(self.events)

    def require_execution_source(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> EbookRenameSourceSnapshot:
        self.execution_checks += 1
        return self.source

    def require_recovery_source(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> EbookRenameSourceSnapshot:
        self.recovery_checks += 1
        return self.source

    def append_event(
        self,
        value: EbookRenameExecutionEvent,
        _lease: OwnedScanRootWriteLease,
    ) -> EbookRenameExecutionEvent:
        self.events.append(value)
        return value


def _execution_material() -> dict[str, Any]:
    plan, capability, probe, preparation, authorization = _material()
    run_id = EntityId.new()
    lease = OwnedScanRootWriteLease(
        scan_root_id=authorization.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        owner_run_id=run_id,
        lease_token="private-run-token",
        fence_epoch=11,
        acquired_at=authorization.prepared_at,
        heartbeat_at=authorization.prepared_at,
        lease_expires_at=authorization.expires_at + timedelta(minutes=5),
    )
    run = build_ebook_rename_run(
        authorization,
        capability,
        probe,
        lease,
        run_id=run_id,
        created_at=authorization.prepared_at + timedelta(seconds=1),
    )
    binding = build_ebook_rename_backend_binding(
        run,
        authorization,
        probe,
        bound_at=run.created_at,
    )
    prepared = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=1,
        status=EbookRenameRunStatus.PREPARED,
        occurred_at=run.created_at,
        fence_epoch=lease.fence_epoch,
        confirmation_digest="e" * 64,
    )
    source = plan.candidate.sources[0]
    private_source = EbookRenameSourceSnapshot(
        run_id=run.id,
        authorization_id=authorization.id,
        preparation_id=preparation.id,
        plan_id=plan.id,
        scan_root_id=source.scan_root_id,
        source_file_id=source.file_id,
        source_relative_locator=source.relative_locator,
        target_relative_locator=plan.candidate.target.relative_locator,
    )
    return {
        "plan": plan,
        "preparation": preparation,
        "authorization": authorization,
        "capability": capability,
        "probe": probe,
        "binding": binding,
        "run": run,
        "lease": lease,
        "prepared": prepared,
        "source": private_source,
        "clock": lambda: run.created_at + timedelta(minutes=1),
    }


def _invoke_execute(material: dict[str, Any], store: _Store, backend: _Backend):
    return execute_ebook_file_rename(
        store=cast(SQLiteEbookRenameStore, store),
        plan=material["plan"],
        preparation=material["preparation"],
        authorization=material["authorization"],
        capability=material["capability"],
        probe=material["probe"],
        binding=material["binding"],
        run=material["run"],
        lease=material["lease"],
        clock=material["clock"],
        backend=backend,
    )


def _invoke_recover(material: dict[str, Any], store: _Store, backend: _Backend):
    return recover_ebook_file_rename(
        store=cast(SQLiteEbookRenameStore, store),
        plan=material["plan"],
        preparation=material["preparation"],
        authorization=material["authorization"],
        capability=material["capability"],
        probe=material["probe"],
        binding=material["binding"],
        run=material["run"],
        lease=material["lease"],
        clock=material["clock"],
        backend=backend,
    )


def test_execute_revalidates_then_stops_at_immediate_verified() -> None:
    material = _execution_material()
    store = _Store(material["source"], material["prepared"])
    session = _Session(LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT)

    result = _invoke_execute(material, store, _Backend(session))

    assert result.status is EbookRenameRunStatus.IMMEDIATE_VERIFIED
    assert [event.status for event in store.events] == [
        EbookRenameRunStatus.PREPARED,
        EbookRenameRunStatus.RELOCATED,
        EbookRenameRunStatus.IMMEDIATE_VERIFIED,
    ]
    assert store.execution_checks == 2
    assert store.recovery_checks == 1
    assert session.forward_count == 1
    assert session.reverse_count == 0
    assert session.closed


def test_failed_immediate_verification_reverses_exact_target() -> None:
    material = _execution_material()
    store = _Store(material["source"], material["prepared"])
    session = _Session(
        LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
        fail_forward_verification=True,
    )

    with pytest.raises(
        EbookRenameExecutorError,
        match="^STALE$",
    ):
        _invoke_execute(material, store, _Backend(session))

    assert [event.status for event in store.events] == [
        EbookRenameRunStatus.PREPARED,
        EbookRenameRunStatus.RELOCATED,
        EbookRenameRunStatus.RECOVERY_RELOCATED,
        EbookRenameRunStatus.RECOVERY_VERIFIED,
    ]
    assert session.forward_count == 1
    assert session.reverse_count == 1


@pytest.mark.parametrize(
    ("physical", "expected", "reverse_count"),
    (
        (
            LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT,
            EbookRenameRunStatus.CANCELLED,
            0,
        ),
        (
            LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT,
            EbookRenameRunStatus.RECOVERY_VERIFIED,
            1,
        ),
    ),
)
def test_prepared_recovery_uses_only_the_exact_matrix(
    physical: LinuxEbookRenamePhysicalState,
    expected: EbookRenameRunStatus,
    reverse_count: int,
) -> None:
    material = _execution_material()
    store = _Store(material["source"], material["prepared"])
    session = _Session(physical)

    result = _invoke_recover(material, store, _Backend(session))

    assert result.status is expected
    assert store.events[-1].status is expected
    assert session.reverse_count == reverse_count


def test_immediate_verified_recovery_never_reverses() -> None:
    material = _execution_material()
    store = _Store(material["source"], material["prepared"])
    store.events.extend(
        (
            EbookRenameExecutionEvent(
                run_id=material["run"].id,
                sequence_no=2,
                status=EbookRenameRunStatus.RELOCATED,
                occurred_at=material["clock"](),
                fence_epoch=material["lease"].fence_epoch,
                finding_code="RENAME_RELOCATED",
            ),
            EbookRenameExecutionEvent(
                run_id=material["run"].id,
                sequence_no=3,
                status=EbookRenameRunStatus.IMMEDIATE_VERIFIED,
                occurred_at=material["clock"](),
                fence_epoch=material["lease"].fence_epoch,
                finding_code="IMMEDIATE_VERIFICATION_PASSED",
            ),
        )
    )
    session = _Session(LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT)

    result = _invoke_recover(material, store, _Backend(session))

    assert result.status is EbookRenameRunStatus.IMMEDIATE_VERIFIED
    assert session.reverse_count == 0


def test_ambiguous_recovery_requires_manual_action_without_mutation() -> None:
    material = _execution_material()
    store = _Store(material["source"], material["prepared"])
    session = _Session(LinuxEbookRenamePhysicalState.AMBIGUOUS)

    with pytest.raises(
        EbookRenameExecutorError,
        match="^MANUAL_RECOVERY_REQUIRED$",
    ) as failure:
        _invoke_recover(material, store, _Backend(session))

    assert failure.value.code is EbookRenameExecutorErrorCode.MANUAL_RECOVERY_REQUIRED
    assert store.events[-1].status is EbookRenameRunStatus.MANUAL_RECOVERY_REQUIRED
    assert session.forward_count == session.reverse_count == 0


def test_short_mutation_window_fences_before_backend_open() -> None:
    material = _execution_material()
    checked_at: datetime = material["clock"]()
    material["lease"] = replace(
        material["lease"],
        lease_expires_at=checked_at + timedelta(minutes=1),
    )
    store = _Store(material["source"], material["prepared"])
    backend = _Backend(
        _Session(LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT)
    )

    with pytest.raises(EbookRenameExecutorError, match="^FENCED_OUT$"):
        _invoke_execute(material, store, backend)

    assert backend.open_count == 0
    assert len(store.events) == 1
