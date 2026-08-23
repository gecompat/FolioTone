"""Synthetic end-to-end coverage for S-W10-05C quarantine execution."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import insert

from foliotone.consolidation.contracts import (
    ConsolidationFileRole,
    ConsolidationReviewState,
)
from foliotone.core import EntityId, ReviewType
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence.quarantine import (
    QuarantineAuthorizationSourceSnapshot,
    QuarantineExecutionRun,
    QuarantineStoreError,
    SQLiteQuarantineStore,
)
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import QuarantineRunStatus
from foliotone.quarantine.capabilities import ResolvedQuarantineCapability
from foliotone.quarantine.source_validation import InterimQuarantineSourceVerifier
from foliotone.workflows.quarantine_operation import (
    QuarantineOperatorError,
    QuarantineOperatorErrorCode,
    QuarantineOperatorService,
)
from tests.integration.test_consolidation_persistence import (
    NOW as PLAN_NOW,
)
from tests.integration.test_consolidation_persistence import (
    _planner_candidate_review_plan,
)

NOW = datetime(2026, 8, 23, 11, 30, tzinfo=UTC)
CAPABILITY_ID = EntityId.parse("e0000000-0000-0000-0000-000000000001")
CONTENT = b"ebook-data"


class _Resolver:
    def __init__(self, capability: ResolvedQuarantineCapability) -> None:
        self.capability = capability
        self.calls = 0

    def resolve(self, quarantine_capability_id: EntityId) -> ResolvedQuarantineCapability:
        assert quarantine_capability_id == CAPABILITY_ID
        self.calls += 1
        return self.capability


class _DriftAfterVerification:
    def __init__(self, candidate: Path) -> None:
        self.candidate = candidate

    def verify(
        self,
        *,
        capability: ResolvedQuarantineCapability,
        source: QuarantineAuthorizationSourceSnapshot,
    ) -> None:
        InterimQuarantineSourceVerifier().verify(capability=capability, source=source)
        if source.role is ConsolidationFileRole.CANDIDATE:
            self.candidate.write_bytes(b"post-verification-drift")
            os.utime(self.candidate, (PLAN_NOW.timestamp(), PLAN_NOW.timestamp()))


def test_execute_consumes_once_moves_one_file_and_persists_confirmation(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )

    result = service.execute(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
        confirmation_text=prompt,
    )

    candidate = source_root / "Synthetic" / "Book-1.epub"
    keeper = source_root / "Synthetic" / "Book-0.epub"
    targets = tuple(quarantine.iterdir())
    assert result.status is QuarantineRunStatus.COMPLETED
    assert keeper.read_bytes() == CONTENT
    assert not candidate.exists()
    assert len(targets) == 1
    assert len(targets[0].name) == 64
    assert targets[0].read_bytes() == CONTENT

    store = SQLiteQuarantineStore(service._plans._engine)
    run = store.get_run_for_authorization(authorization.authorization_id)
    assert run is not None and run.id == result.run_id
    events = store.events_for_run(run.id)
    assert [event.status for event in events] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
        QuarantineRunStatus.COMPLETED,
    ]
    assert events[0].confirmation_digest is not None
    assert all(event.confirmation_digest is None for event in events[1:])
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(plan.scan_root_id) is None
    assert isinstance(service._capabilities, _Resolver)
    assert service._capabilities.calls == 4

    with pytest.raises(QuarantineOperatorError) as consumed:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )
    assert consumed.value.code is QuarantineOperatorErrorCode.AUTHORIZATION_CONSUMED
    assert consumed.value.run_id == result.run_id
    service._plans._engine.dispose()


def test_invalid_confirmation_creates_no_run_or_move(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text="CONFIRM SOMETHING ELSE",
        )

    assert captured.value.code is QuarantineOperatorErrorCode.CONFIRMATION_INVALID
    assert SQLiteQuarantineStore(service._plans._engine).get_run_for_authorization(
        authorization.authorization_id
    ) is None
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    service._plans._engine.dispose()


def test_current_review_drift_after_prompt_consumes_nothing(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    review = next(
        item
        for item in plan.required_reviews
        if item.review_type is ReviewType.CONSOLIDATION_CANDIDATE
    )
    assert review.review_item_id is not None
    with service._plans._engine.begin() as connection:
        connection.execute(
            insert(review_schema.review_decisions).values(
                id=str(EntityId.new()),
                review_item_id=str(review.review_item_id),
                sequence_no=2,
                decision="REJECT",
                decision_reason="SYNTHETIC_DRIFT_BEFORE_EXECUTION",
                evidence_fingerprint=review.evidence_fingerprint,
                candidate_set_fingerprint=review.candidate_set_fingerprint,
                decision_compatibility_version=review.decision_compatibility_version,
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )

    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.STALE
    assert SQLiteQuarantineStore(service._plans._engine).get_run_for_authorization(
        authorization.authorization_id
    ) is None
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_candidate_drift_after_prompt_consumes_nothing(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    candidate = source_root / "Synthetic" / "Book-1.epub"
    candidate.write_bytes(b"other-data")
    os.utime(candidate, (PLAN_NOW.timestamp(), PLAN_NOW.timestamp()))

    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.STALE
    assert SQLiteQuarantineStore(service._plans._engine).get_run_for_authorization(
        authorization.authorization_id
    ) is None
    assert candidate.read_bytes() == b"other-data"
    assert tuple(quarantine.iterdir()) == ()
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_authorization_expiring_during_revalidation_consumes_nothing(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    expired = NOW + timedelta(minutes=16)
    clock_values = iter((NOW, NOW, NOW, expired, expired))
    service._clock = lambda: next(clock_values)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.AUTHORIZATION_EXPIRED
    assert SQLiteQuarantineStore(service._plans._engine).get_run_for_authorization(
        authorization.authorization_id
    ) is None
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_active_root_writer_blocks_execution_before_run_creation(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    blocker = leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.SCAN_RUN,
        EntityId.new(),
        lease_token="synthetic-active-root-writer",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=10),
    )
    try:
        with pytest.raises(QuarantineOperatorError) as captured:
            service.execute(
                plan_id=plan.id,
                plan_content_hash=plan.content_hash,
                capability_id=CAPABILITY_ID,
                authorization_id=authorization.authorization_id,
                confirmation_text=prompt,
            )
        assert captured.value.code is QuarantineOperatorErrorCode.FENCED_OUT
        assert SQLiteQuarantineStore(service._plans._engine).get_run_for_authorization(
            authorization.authorization_id
        ) is None
        assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
        assert tuple(quarantine.iterdir()) == ()
    finally:
        leases.release(blocker, released_at=NOW)
        service._plans._engine.dispose()


def test_expired_preparedless_lease_is_atomically_taken_over(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, _quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        EntityId.new(),
        lease_token="synthetic-preparedless-owner",
        acquired_at=NOW - timedelta(minutes=2),
        lease_expires_at=NOW - timedelta(minutes=1),
    )

    result = service.execute(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
        confirmation_text=prompt,
    )

    events = SQLiteQuarantineStore(service._plans._engine).events_for_run(result.run_id)
    assert result.status is QuarantineRunStatus.COMPLETED
    assert events[0].fence_epoch == 2
    assert not (source_root / "Synthetic" / "Book-1.epub").exists()
    assert leases.current(plan.scan_root_id) is None
    service._plans._engine.dispose()


def test_expired_lease_with_persisted_run_cannot_be_taken_over(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    store = SQLiteQuarantineStore(service._plans._engine)
    snapshot = store.get_authorization(authorization.authorization_id)
    assert snapshot is not None
    run = QuarantineExecutionRun(
        EntityId.new(),
        snapshot.id,
        snapshot.plan_id,
        snapshot.scan_root_id,
        snapshot.keeper_file_id,
        snapshot.candidate_file_id,
        "a" * 64,
        NOW,
    )
    leases = SQLiteScanRootWriteLeaseStore(service._plans._engine)
    expired = leases.acquire(
        plan.scan_root_id,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        run.id,
        lease_token="synthetic-persisted-owner",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )
    store.create_prepared_run(run, expired, NOW)

    with pytest.raises(QuarantineStoreError):
        store.takeover_expired_preparedless_lease(
            expired,
            EntityId.new(),
            lease_token="synthetic-replacement-owner",
            acquired_at=NOW + timedelta(minutes=2),
            lease_expires_at=NOW + timedelta(minutes=32),
        )

    assert leases.current(plan.scan_root_id) == expired
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    leases.release(expired, released_at=NOW)
    service._plans._engine.dispose()


def test_unexpected_executor_failure_after_prepared_requires_manual_review(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )

    def fail_after_prepared(**values):
        values["store"].create_confirmed_prepared_run(
            values["run"],
            values["authorization"],
            values["plan"],
            values["lease"],
            confirmation_digest=values["confirmation_digest"],
            confirmed_at=values["occurred_at"],
            persisted_at=values["persisted_at"],
        )
        raise RuntimeError("synthetic failure after PREPARED")

    service._executor = fail_after_prepared
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
    events = SQLiteQuarantineStore(service._plans._engine).events_for_run(
        captured.value.run_id
    )
    assert [event.status for event in events] == [QuarantineRunStatus.PREPARED]
    assert (source_root / "Synthetic" / "Book-1.epub").read_bytes() == CONTENT
    assert tuple(quarantine.iterdir()) == ()
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(
        plan.scan_root_id
    ) is None
    service._plans._engine.dispose()


def test_executor_revalidation_failure_persists_run_for_recovery(
    head_database: Path,
    tmp_path: Path,
) -> None:
    service, plan, source_root, quarantine = _execution_service(head_database, tmp_path)
    authorization = _authorize(service, plan)
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
        authorization_id=authorization.authorization_id,
    )
    candidate = source_root / "Synthetic" / "Book-1.epub"
    service._source_verifier = _DriftAfterVerification(candidate)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=CAPABILITY_ID,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.VALIDATION_FAILED
    assert captured.value.run_id is not None
    events = SQLiteQuarantineStore(service._plans._engine).events_for_run(
        captured.value.run_id
    )
    assert [event.status for event in events] == [
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.VALIDATION_FAILED,
    ]
    assert candidate.read_bytes() == b"post-verification-drift"
    assert tuple(quarantine.iterdir()) == ()
    assert SQLiteScanRootWriteLeaseStore(service._plans._engine).current(
        plan.scan_root_id
    ) is None
    service._plans._engine.dispose()


def _execution_service(
    database: Path,
    tmp_path: Path,
) -> tuple[QuarantineOperatorService, object, Path, Path]:
    full_hash = hashlib.sha256(CONTENT).hexdigest()
    store, plan, _inputs = _planner_candidate_review_plan(
        database,
        ConsolidationReviewState.ACCEPTED,
        full_hash=full_hash,
    )
    plan = store.create_or_get_plan(plan)
    source_root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    synthetic = source_root / "Synthetic"
    synthetic.mkdir(parents=True)
    quarantine.mkdir()
    for ordinal in range(2):
        source = synthetic / f"Book-{ordinal}.epub"
        source.write_bytes(CONTENT)
        os.utime(source, (PLAN_NOW.timestamp(), PLAN_NOW.timestamp()))
    capability = ResolvedQuarantineCapability(
        CAPABILITY_ID,
        plan.scan_root_id,
        source_root,
        quarantine,
    )
    return (
        QuarantineOperatorService(
            store._engine,
            capability_resolver=_Resolver(capability),
            clock=lambda: NOW,
        ),
        plan,
        source_root,
        quarantine,
    )


def _authorize(service: QuarantineOperatorService, plan: object):
    return service.authorize(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=CAPABILITY_ID,
    )
