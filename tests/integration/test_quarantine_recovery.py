"""Synthetic crash/recovery acceptance for S-W10-05D."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from foliotone.core import EntityId
from foliotone.persistence import schema
from foliotone.persistence.quarantine import (
    QuarantineExecutionEvent,
    QuarantineExecutionRun,
    SQLiteQuarantineStore,
)
from foliotone.persistence.quarantine_schema import quarantine_execution_events
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import QuarantineRunStatus
from foliotone.quarantine.capabilities import QuarantineCapabilityUnavailable
from foliotone.workflows.quarantine_operation import (
    QuarantineOperatorError,
    QuarantineOperatorErrorCode,
    QuarantineOperatorService,
)
from tests.integration.test_quarantine_execution import (
    CAPABILITY_ID,
    CONTENT,
    NOW,
    _authorize,
    _execution_service,
)


def test_recovery_cancels_exact_unmoved_prepared_run_without_rename(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )

    result = service.recover(run_id=run.id)

    assert result.status is QuarantineRunStatus.CANCELLED
    assert source.read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    assert _statuses(service, run) == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.CANCELLED,
    ]
    service._plans._engine.dispose()


@pytest.mark.parametrize(
    "latest",
    (
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
    ),
)
def test_recovery_completes_only_missing_events_for_an_exact_bound_target(
    head_database: Path,
    tmp_path: Path,
    latest: QuarantineRunStatus,
) -> None:
    service, plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    _append_until(service, run, latest)
    target = quarantine / run.target_token
    source.rename(target)

    result = service.recover(run_id=run.id)

    assert result.status is QuarantineRunStatus.COMPLETED
    assert not source.exists()
    assert target.read_bytes() == CONTENT
    assert _statuses(service, run) == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
        QuarantineRunStatus.COMPLETED,
    ]
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(
        plan.scan_root_id
    ) is None
    service._plans._engine.dispose()


@pytest.mark.parametrize(
    "distribution",
    ("both-absent", "both-present", "foreign-target", "foreign-source"),
)
def test_recovery_persists_manual_review_for_every_ambiguous_distribution(
    head_database: Path,
    tmp_path: Path,
    distribution: str,
) -> None:
    service, _plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    target = quarantine / run.target_token
    if distribution == "both-absent":
        source.unlink()
    elif distribution == "both-present":
        target.write_bytes(CONTENT)
        os.utime(target, (NOW.timestamp(), NOW.timestamp()))
    elif distribution == "foreign-target":
        source.unlink()
        target.write_bytes(b"foreign-target")
        os.utime(target, (NOW.timestamp(), NOW.timestamp()))
    else:
        source.write_bytes(b"foreign-source")
        os.utime(source, (NOW.timestamp(), NOW.timestamp()))

    with pytest.raises(QuarantineOperatorError) as captured:
        service.recover(run_id=run.id)

    assert captured.value.code is QuarantineOperatorErrorCode.MANUAL_REVIEW
    assert captured.value.run_id == run.id
    assert _statuses(service, run) == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MANUAL_REVIEW,
    ]
    service._plans._engine.dispose()


def test_active_root_writer_blocks_recovery_without_new_event(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    blocker = leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="synthetic-active-recovery-blocker",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    try:
        with pytest.raises(QuarantineOperatorError) as captured:
            service.recover(run_id=run.id)
        assert captured.value.code is QuarantineOperatorErrorCode.FENCED_OUT
        assert captured.value.run_id == run.id
        assert _statuses(service, run) == [QuarantineRunStatus.PREPARED]
        assert source.read_bytes() == CONTENT
        assert tuple(quarantine.iterdir()) == ()
    finally:
        leases.release(blocker, released_at=NOW)
        service._plans._engine.dispose()


def test_capability_failure_reports_the_known_run_without_new_event(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, _plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )

    class _UnavailableCapabilities:
        @staticmethod
        def resolve(_capability_id: EntityId) -> None:
            raise QuarantineCapabilityUnavailable()

    service._capabilities = _UnavailableCapabilities()

    with pytest.raises(QuarantineOperatorError) as captured:
        service.recover(run_id=run.id)

    assert captured.value.code is QuarantineOperatorErrorCode.TOOL_UNAVAILABLE
    assert captured.value.run_id == run.id
    assert _statuses(service, run) == [QuarantineRunStatus.PREPARED]
    assert source.read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    service._plans._engine.dispose()


def test_recovery_uses_historical_locator_after_authorization_and_file_state_expire(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    target = quarantine / run.target_token
    source.rename(target)
    with service._plans._engine.begin() as connection:
        connection.execute(
            schema.file_records.update()
            .where(schema.file_records.c.id == str(run.candidate_file_id))
            .values(
                presence_state="MISSING",
                size_bytes=0,
                modified_at=(NOW + timedelta(minutes=16)).isoformat(),
            )
        )
    assert authorization.expires_at < NOW + timedelta(minutes=16)
    service._clock = lambda: NOW + timedelta(minutes=16)

    result = service.recover(run_id=run.id)

    assert result.status is QuarantineRunStatus.COMPLETED
    assert target.read_bytes() == CONTENT
    assert _statuses(service, run)[-1] is QuarantineRunStatus.COMPLETED
    service._plans._engine.dispose()


def test_terminal_recovery_is_idempotent_and_releases_its_expired_lease(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    source.rename(quarantine / run.target_token)
    assert service.recover(run_id=run.id).status is QuarantineRunStatus.COMPLETED
    events_before = _statuses(service, run)
    later = NOW + timedelta(minutes=40)
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        run.id,
        lease_token="synthetic-expired-terminal-owner",
        acquired_at=later - timedelta(minutes=2),
        lease_expires_at=later - timedelta(minutes=1),
    )
    service._clock = lambda: later

    retry = service.recover(run_id=run.id)

    assert retry.status is QuarantineRunStatus.COMPLETED
    assert _statuses(service, run) == events_before
    assert leases.current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_recovery_refuses_a_low_level_prepared_run_without_confirmation(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(
        head_database,
        tmp_path,
    )
    authorization_result = _authorize(service, plan)
    store = SQLiteQuarantineStore(service._plans._engine)
    authorization = store.get_authorization(authorization_result.authorization_id)
    assert authorization is not None
    assert plan.keeper is not None and plan.candidate is not None
    run = QuarantineExecutionRun(
        EntityId.new(),
        authorization.id,
        plan.id,
        plan.scan_root_id,
        plan.keeper.file_id,
        plan.candidate.file_id,
        "f" * 64,
        NOW,
    )
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    lease = leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        run.id,
        lease_token="synthetic-unconfirmed-prepared-owner",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    store.create_prepared_run(run, lease, NOW)
    leases.release(lease, released_at=NOW)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.recover(run_id=run.id)

    assert captured.value.code is QuarantineOperatorErrorCode.MANUAL_REVIEW
    assert captured.value.run_id == run.id
    assert _statuses(service, run) == [QuarantineRunStatus.PREPARED]
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    service._plans._engine.dispose()


def test_recovery_takes_over_only_its_expired_same_run_lease(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    later = NOW + timedelta(minutes=40)
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    expired = leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        run.id,
        lease_token="synthetic-expired-recovery-owner",
        acquired_at=later - timedelta(minutes=2),
        lease_expires_at=later - timedelta(minutes=1),
    )
    service._clock = lambda: later

    result = service.recover(run_id=run.id)

    events = SQLiteQuarantineStore(service._plans._engine).events_for_run(run.id)
    assert result.status is QuarantineRunStatus.CANCELLED
    assert [event.status for event in events] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.CANCELLED,
    ]
    assert events[-1].fence_epoch == expired.fence_epoch + 1
    assert source.read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    assert leases.current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_recovery_refuses_a_gapless_but_contradictory_event_journal(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, _plan, _authorization, run, source, quarantine = _prepared_run(
        head_database,
        tmp_path,
    )
    with service._plans._engine.begin() as connection:
        connection.execute(
            quarantine_execution_events.insert().values(
                run_id=str(run.id),
                sequence_no=2,
                status=QuarantineRunStatus.VERIFIED.value,
                occurred_at=NOW.isoformat(),
                fence_epoch=1,
                finding_code="SYNTHETIC_INVALID_TRANSITION",
                confirmation_digest=None,
            )
        )

    with pytest.raises(QuarantineOperatorError) as captured:
        service.recover(run_id=run.id)

    assert captured.value.code is QuarantineOperatorErrorCode.MANUAL_REVIEW
    assert captured.value.run_id == run.id
    with service._plans._engine.connect() as connection:
        assert list(
            connection.execute(
                select(quarantine_execution_events.c.status)
                .where(quarantine_execution_events.c.run_id == str(run.id))
                .order_by(quarantine_execution_events.c.sequence_no)
            ).scalars()
        ) == [
            QuarantineRunStatus.PREPARED.value,
            QuarantineRunStatus.VERIFIED.value,
        ]
    assert source.read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    service._plans._engine.dispose()


def _prepared_run(
    database: Path,
    tmp_path: Path,
):
    service, plan, source_root, quarantine = _execution_service(database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )

    def stop_after_prepared(**values):
        values["store"].create_confirmed_prepared_run(
            values["run"],
            values["authorization"],
            values["plan"],
            values["lease"],
            confirmation_digest=values["confirmation_digest"],
            confirmed_at=values["occurred_at"],
            persisted_at=values["persisted_at"],
        )
        raise RuntimeError("synthetic crash after PREPARED")

    service._executor = stop_after_prepared
    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )
    assert captured.value.code is QuarantineOperatorErrorCode.MANUAL_REVIEW
    assert captured.value.run_id is not None
    run = SQLiteQuarantineStore(service._plans._engine).get_run(captured.value.run_id)
    assert run is not None
    return (
        service,
        plan,
        authorization,
        run,
        source_root / "Synthetic" / "Book-1.epub",
        quarantine,
    )


def _append_until(
    service: QuarantineOperatorService,
    run: QuarantineExecutionRun,
    latest: QuarantineRunStatus,
) -> None:
    statuses = {
        QuarantineRunStatus.PREPARED: (),
        QuarantineRunStatus.MOVED: (QuarantineRunStatus.MOVED,),
        QuarantineRunStatus.VERIFIED: (
            QuarantineRunStatus.MOVED,
            QuarantineRunStatus.VERIFIED,
        ),
    }[latest]
    if not statuses:
        return
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    lease = leases.acquire(
        run.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        run.id,
        lease_token="synthetic-pre-recovery-progress",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    store = SQLiteQuarantineStore(service._plans._engine)
    for status in statuses:
        sequence = len(store.events_for_run(run.id)) + 1
        store.append_event(
            QuarantineExecutionEvent(
                run.id,
                sequence,
                status,
                NOW,
                lease.fence_epoch,
            ),
            lease,
        )
    leases.release(lease, released_at=NOW)


def _statuses(
    service: QuarantineOperatorService,
    run: QuarantineExecutionRun,
) -> list[QuarantineRunStatus]:
    return [
        event.status
        for event in SQLiteQuarantineStore(
            service._plans._engine
        ).events_for_run(run.id)
    ]
