from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, insert, text
from sqlalchemy.exc import IntegrityError

from foliotone.core import EntityId, ReviewDecisionValue
from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.ebook_rename import (
    EbookRenameExecutionEvent,
    EbookRenameRunStatus,
    ResolvedEbookRenameCapability,
    build_ebook_rename_authorization,
    build_ebook_rename_backend_binding,
    build_ebook_rename_capability_probe,
    build_ebook_rename_physical_evidence,
    build_ebook_rename_preparation,
    build_ebook_rename_run,
)
from foliotone.ebook_rename.executor import execute_ebook_file_rename
from foliotone.ebook_rename.linux_backend import LinuxEbookRenamePhysicalState
from foliotone.persistence import (
    ScanRootWriteOwnerKind,
    SQLiteEbookOperationRecipeStore,
    SQLiteScanRootWriteLeaseStore,
    alembic_config,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    schema,
)
from foliotone.persistence.ebook_rename import (
    EbookRenameStoreError,
    SQLiteEbookRenameStore,
)
from foliotone.workflows.ebook_rename_planning import EbookRenamePlanningService
from foliotone.workflows.ebook_rename_status import (
    SQLiteEbookRenameStatusReportReader,
)
from tests.integration.test_ebook_rename_workflow import (
    NOW,
    OBSERVATION_ID,
    PRIVATE_SOURCE,
    ROOT_ID,
    SCOPE_ID,
    _scope,
    _ScopeResolver,
    _seed_source,
)
from tests.unit.test_ebook_rename_executor import _Backend, _Session


def _approved_plan(engine: Engine):
    scope = _scope()
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(scope),
        clock=lambda: NOW,
    )
    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "authorized.epub")
    service.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    result = service.plan(proposal.candidate_id)
    plan = SQLiteEbookOperationRecipeStore(engine).get_plan(result.plan_id)
    assert plan is not None
    return plan, scope


def _capability(tmp_path: Path) -> ResolvedEbookRenameCapability:
    source = tmp_path / "runtime-source"
    probe = tmp_path / "runtime-probe"
    source.mkdir()
    probe.mkdir()
    return ResolvedEbookRenameCapability(
        ebook_rename_capability_id=EntityId.new(),
        scan_root_id=ROOT_ID,
        scan_root_directory=source,
        probe_directory=probe,
        version=1,
        configuration_fingerprint="b" * 64,
    )


def _authorization_material(
    engine: Engine,
    tmp_path: Path,
    *,
    before_persist: Callable[[Engine, EbookOperationRecipePlan], None] | None = None,
):
    plan, scope = _approved_plan(engine)
    capability = _capability(tmp_path)
    probe = build_ebook_rename_capability_probe(
        capability,
        filesystem_type="ext4",
        filesystem_identity_fingerprint="c" * 64,
        kernel_release="6.12.0-synthetic",
        probed_at=NOW + timedelta(seconds=1),
        openat2_supported=True,
        renameat2_noreplace_supported=True,
        directory_fsync_supported=True,
        root_probe_same_filesystem=True,
    )
    store = SQLiteEbookRenameStore(engine)
    assert store.create_or_get_probe(probe) == probe
    leases = SQLiteScanRootWriteLeaseStore(engine)
    preparation_owner_id = EntityId.new()
    preparation_lease = leases.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION,
        preparation_owner_id,
        lease_token="synthetic-preparation-token",
        acquired_at=NOW + timedelta(seconds=2),
        lease_expires_at=NOW + timedelta(minutes=20),
    )
    physical = build_ebook_rename_physical_evidence(
        plan,
        source_device=101,
        source_inode=202,
        source_mode=stat.S_IFREG | 0o600,
        source_uid=1000,
        source_gid=1000,
        source_link_count=1,
        source_size_bytes=4096,
        source_mtime_ns=1_776_969_600_000_000_000,
        source_modified_at=NOW,
        source_full_sha256="a" * 64,
        source_xattr_fingerprint="d" * 64,
        target_physically_absent=True,
        target_historically_absent=True,
        captured_at=NOW + timedelta(seconds=3),
    )
    preparation = build_ebook_rename_preparation(
        plan,
        physical,
        capability,
        probe,
        scope,
        preparation_lease,
        authorized_at=NOW + timedelta(seconds=2),
        prepared_at=NOW + timedelta(seconds=4),
    )
    authorization = build_ebook_rename_authorization(
        preparation,
        expires_at=NOW + timedelta(minutes=10),
    )
    if before_persist is not None:
        before_persist(engine, plan)
    persisted = store.create_or_get_authorization(
        plan,
        preparation,
        authorization,
        capability,
        probe,
        scope,
        preparation_lease,
        persisted_at=NOW + timedelta(seconds=4),
    )
    return (
        store,
        leases,
        plan,
        scope,
        capability,
        probe,
        preparation_lease,
        preparation,
        persisted,
    )


def _create_run(
    store: SQLiteEbookRenameStore,
    leases: SQLiteScanRootWriteLeaseStore,
    capability: ResolvedEbookRenameCapability,
    probe,
    authorization,
):
    run_id = EntityId.new()
    lease = leases.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        run_id,
        lease_token="synthetic-run-token",
        acquired_at=NOW + timedelta(seconds=6),
        lease_expires_at=NOW + timedelta(minutes=20),
    )
    run = build_ebook_rename_run(
        authorization,
        capability,
        probe,
        lease,
        run_id=run_id,
        created_at=NOW + timedelta(seconds=7),
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
    assert store.create_run(run, authorization, probe, binding, prepared, lease) == run
    return run, binding, prepared, lease


def test_target_history_race_blocks_authorization(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)

    def add_target_history(
        current: Engine,
        raw_plan: EbookOperationRecipePlan,
    ) -> None:
        target = raw_plan.candidate.target.relative_locator
        with current.begin() as connection:
            connection.execute(
                insert(schema.file_records),
                {
                    "id": str(EntityId.new()),
                    "scan_root_id": str(ROOT_ID),
                    "relative_path": target,
                    "size_bytes": 4096,
                    "modified_at": NOW.isoformat(),
                    "media_type": "EBOOK",
                    "presence_state": "MISSING",
                    "first_seen_at": NOW.isoformat(),
                    "last_seen_at": NOW.isoformat(),
                    "missing_since_at": NOW.isoformat(),
                    "consecutive_missing_scans": 1,
                },
            )

    with pytest.raises(
        EbookRenameStoreError,
        match="source or target state differs",
    ):
        _authorization_material(
            engine,
            tmp_path,
            before_persist=add_target_history,
        )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_rename_authorizations")
        ).scalar_one() == 0
    engine.dispose()


def test_conflicting_full_hash_blocks_authorization(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)

    def add_conflicting_hash(
        current: Engine,
        _raw_plan: EbookOperationRecipePlan,
    ) -> None:
        with current.begin() as connection:
            connection.execute(
                insert(schema.fingerprints),
                {
                    "id": str(EntityId.new()),
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(OBSERVATION_ID),
                    "kind": "FILE_SHA256",
                    "algorithm": "sha256",
                    "algorithm_version": "1",
                    "value": "f" * 64,
                    "created_at": NOW.isoformat(),
                    "tool_execution_id": None,
                },
            )

    with pytest.raises(
        EbookRenameStoreError,
        match="source or target state differs",
    ):
        _authorization_material(
            engine,
            tmp_path,
            before_persist=add_conflicting_hash,
        )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_rename_authorizations")
        ).scalar_one() == 0
    engine.dispose()


def test_one_use_authority_and_read_only_status_are_private(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    (
        store,
        leases,
        plan,
        scope,
        capability,
        probe,
        preparation_lease,
        preparation,
        authorization,
    ) = _authorization_material(engine, tmp_path)

    assert store.get_preparation(preparation.id) == preparation
    assert store.get_authorization(authorization.id) == authorization
    assert PRIVATE_SOURCE not in repr(preparation)
    assert "a" * 64 not in repr(preparation)
    assert (
        store.create_or_get_authorization(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            scope,
            preparation_lease,
            persisted_at=NOW + timedelta(seconds=4),
        )
        == authorization
    )
    leases.release(preparation_lease, released_at=NOW + timedelta(seconds=5))
    run, binding, prepared, run_lease = _create_run(
        store,
        leases,
        capability,
        probe,
        authorization,
    )
    assert (
        store.create_run(
            run,
            authorization,
            probe,
            binding,
            prepared,
            run_lease,
        )
        == run
    )
    cancelled = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=2,
        status=EbookRenameRunStatus.CANCELLED,
        occurred_at=NOW + timedelta(seconds=8),
        fence_epoch=run_lease.fence_epoch,
        finding_code="OPERATOR_CANCELLED",
    )
    assert store.append_event(cancelled, run_lease) == cancelled
    leases.release(run_lease, released_at=NOW + timedelta(seconds=9))

    second_id = EntityId.new()
    second_lease = leases.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        second_id,
        lease_token="synthetic-replay-token",
        acquired_at=NOW + timedelta(seconds=10),
        lease_expires_at=NOW + timedelta(minutes=20),
    )
    second_run = build_ebook_rename_run(
        authorization,
        capability,
        probe,
        second_lease,
        run_id=second_id,
        created_at=NOW + timedelta(seconds=11),
    )
    second_binding = build_ebook_rename_backend_binding(
        second_run,
        authorization,
        probe,
        bound_at=second_run.created_at,
    )
    second_prepared = replace(
        prepared,
        run_id=second_id,
        occurred_at=second_run.created_at,
        fence_epoch=second_lease.fence_epoch,
    )
    with pytest.raises(
        EbookRenameStoreError,
        match="already consumed",
    ):
        store.create_run(
            second_run,
            authorization,
            probe,
            second_binding,
            second_prepared,
            second_lease,
        )
    leases.release(second_lease, released_at=NOW + timedelta(seconds=12))
    engine.dispose()

    before = hashlib.sha256(head_database.read_bytes()).hexdigest()
    read_only_engine = create_sqlite_read_only_engine(head_database)
    report = SQLiteEbookRenameStatusReportReader(
        SQLiteEbookRenameStore(read_only_engine)
    ).read(run.id)
    payload = report.payload()
    read_only_engine.dispose()
    after = hashlib.sha256(head_database.read_bytes()).hexdigest()

    assert before == after
    assert report.status is EbookRenameRunStatus.CANCELLED
    assert tuple(event.sequence_no for event in report.events) == (1, 2)
    rendered = repr(payload)
    for private in (
        PRIVATE_SOURCE,
        "authorized.epub",
        "a" * 64,
        "b" * 64,
        "source_inode",
        "fence_epoch",
        "confirmation_digest",
    ):
        assert private not in rendered


def test_execution_source_is_live_but_recovery_keeps_historical_authority(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    (
        store,
        leases,
        plan,
        _scope_value,
        capability,
        probe,
        preparation_lease,
        preparation,
        authorization,
    ) = _authorization_material(engine, tmp_path)
    leases.release(preparation_lease, released_at=NOW + timedelta(seconds=5))
    run, binding, _prepared, run_lease = _create_run(
        store,
        leases,
        capability,
        probe,
        authorization,
    )

    source = store.require_execution_source(
        plan,
        preparation,
        authorization,
        capability,
        probe,
        binding,
        run,
        run_lease,
        checked_at=NOW + timedelta(seconds=8),
    )
    rendered = repr(source)
    assert PRIVATE_SOURCE not in rendered
    assert plan.candidate.target.relative_locator not in rendered
    assert "a" * 64 not in rendered

    after_authorization = authorization.expires_at + timedelta(seconds=1)
    with pytest.raises(EbookRenameStoreError, match="authorization is unavailable"):
        store.require_execution_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            run_lease,
            checked_at=after_authorization,
        )
    assert (
        store.require_recovery_source(
            plan,
            preparation,
            authorization,
            capability,
            probe,
            binding,
            run,
            run_lease,
            checked_at=after_authorization,
        )
        == source
    )

    with pytest.raises(EbookRenameStoreError, match="operation binding differs"):
        store.require_recovery_source(
            plan,
            preparation,
            authorization,
            replace(capability, configuration_fingerprint="f" * 64),
            probe,
            binding,
            run,
            run_lease,
            checked_at=after_authorization,
        )
    leases.release(run_lease, released_at=after_authorization + timedelta(seconds=1))
    engine.dispose()


def test_executor_and_store_commit_only_relocated_then_immediate_verified(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    (
        store,
        leases,
        plan,
        _scope_value,
        capability,
        probe,
        preparation_lease,
        preparation,
        authorization,
    ) = _authorization_material(engine, tmp_path)
    leases.release(preparation_lease, released_at=NOW + timedelta(seconds=5))
    run, binding, _prepared, run_lease = _create_run(
        store,
        leases,
        capability,
        probe,
        authorization,
    )
    session = _Session(LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT)

    result = execute_ebook_file_rename(
        store=store,
        plan=plan,
        preparation=preparation,
        authorization=authorization,
        capability=capability,
        probe=probe,
        binding=binding,
        run=run,
        lease=run_lease,
        clock=lambda: NOW + timedelta(seconds=8),
        backend=_Backend(session),
    )

    assert result.status is EbookRenameRunStatus.IMMEDIATE_VERIFIED
    assert tuple(event.status for event in store.events_for_run(run.id)) == (
        EbookRenameRunStatus.PREPARED,
        EbookRenameRunStatus.RELOCATED,
        EbookRenameRunStatus.IMMEDIATE_VERIFIED,
    )
    assert session.forward_count == 1
    assert session.reverse_count == 0
    leases.release(run_lease, released_at=NOW + timedelta(seconds=9))
    engine.dispose()


def test_stale_fence_invalid_transition_and_reserved_success_are_blocked(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    (
        store,
        leases,
        _plan,
        _scope_value,
        capability,
        probe,
        preparation_lease,
        _preparation,
        authorization,
    ) = _authorization_material(engine, tmp_path)
    leases.release(preparation_lease, released_at=NOW + timedelta(seconds=5))
    run, _binding, _prepared, stale_lease = _create_run(
        store,
        leases,
        capability,
        probe,
        authorization,
    )
    leases.release(stale_lease, released_at=NOW + timedelta(seconds=8))
    current_lease = leases.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        run.id,
        lease_token="synthetic-recovery-token",
        acquired_at=NOW + timedelta(seconds=9),
        lease_expires_at=NOW + timedelta(minutes=20),
    )

    stale_event = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=2,
        status=EbookRenameRunStatus.CANCELLED,
        occurred_at=NOW + timedelta(seconds=10),
        fence_epoch=stale_lease.fence_epoch,
    )
    with pytest.raises(EbookRenameStoreError, match="requires its run lease"):
        store.append_event(stale_event, current_lease)

    invalid_transition = replace(
        stale_event,
        status=EbookRenameRunStatus.SCAN_HANDOFF,
        fence_epoch=current_lease.fence_epoch,
    )
    with pytest.raises(EbookRenameStoreError, match="could not be appended"):
        store.append_event(invalid_transition, current_lease)

    reserved = replace(
        invalid_transition,
        status=EbookRenameRunStatus.VERIFIED,
    )
    with pytest.raises(EbookRenameStoreError, match="is reserved"):
        store.append_event(reserved, current_lease)
    assert tuple(event.status for event in store.events_for_run(run.id)) == (
        EbookRenameRunStatus.PREPARED,
    )
    with pytest.raises(IntegrityError, match="must be gapless"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ebook_rename_events "
                    "(run_id,sequence_no,status,occurred_at,fence_epoch,"
                    "finding_code,confirmation_digest) "
                    "VALUES (:run_id,1,'PREPARED',:occurred_at,:fence,NULL,:confirmation)"
                ),
                {
                    "run_id": str(run.id),
                    "occurred_at": (NOW + timedelta(seconds=11)).isoformat(),
                    "fence": current_lease.fence_epoch,
                    "confirmation": "0" * 64,
                },
            )
    with pytest.raises(IntegrityError, match="invalid e-book rename event transition"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ebook_rename_events "
                    "(run_id,sequence_no,status,occurred_at,fence_epoch,"
                    "finding_code,confirmation_digest) "
                    "VALUES (:run_id,2,'SCAN_HANDOFF',:occurred_at,:fence,NULL,NULL)"
                ),
                {
                    "run_id": str(run.id),
                    "occurred_at": (NOW + timedelta(seconds=11)).isoformat(),
                    "fence": current_lease.fence_epoch,
                },
            )
    engine.dispose()


def test_migration_is_immutable_and_populated_downgrade_is_blocked(
    head_database: Path,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    store = SQLiteEbookRenameStore(engine)
    capability = _capability(tmp_path)
    probe = build_ebook_rename_capability_probe(
        capability,
        filesystem_type="ext4",
        filesystem_identity_fingerprint="f" * 64,
        kernel_release="6.12.0-synthetic",
        probed_at=NOW,
        openat2_supported=True,
        renameat2_noreplace_supported=True,
        directory_fsync_supported=True,
        root_probe_same_filesystem=True,
    )
    store.create_or_get_probe(probe)

    with pytest.raises(IntegrityError, match="immutable e-book rename record"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ebook_rename_capability_probes "
                    "SET kernel_release='changed' WHERE id=:id"
                ),
                {"id": str(probe.id)},
            )
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="e-book rename state prevents migration downgrade",
    ):
        command.downgrade(
            alembic_config(head_database),
            "0030_ebook_operation_recipe_plans",
        )
