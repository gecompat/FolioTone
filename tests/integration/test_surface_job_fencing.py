from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import delete, insert, inspect, select, update

from foliotone.application.contracts import (
    EbookFixityAnalysisJobProfile,
    EbookFixityBaselineActivationCommand,
    EbookRenameOperatorJobProfile,
)
from foliotone.core import EntityId, MediaType
from foliotone.fixity import expected_fixity_baseline_confirmation
from foliotone.persistence import schema
from foliotone.persistence.fixity import SQLiteEbookFixityBaselineStore
from foliotone.persistence.fixity_surface import SQLiteEbookFixityBaselineActivationOperation
from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import (
    EbookFixityAnalysisJobBinder,
    EbookRenameOperatorJobBinder,
    SQLiteSurfaceStore,
)
from foliotone.persistence.surface_schema import (
    application_job_events,
    application_jobs,
    ebook_fixity_analysis_job_binders,
    ebook_fixity_analysis_job_results,
    ebook_rename_operator_job_binders,
    ebook_rename_operator_job_results,
)
from foliotone.surface.contracts import JobStatus, ProcessRole, Scope
from foliotone.surface.service import LocalSurfaceService

_FIXITY_ROOT_ID = "00000000-0000-4000-8000-000000000001"


def _add_fixity_root(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots).values(
                id=_FIXITY_ROOT_ID,
                name="synthetic-ebooks",
                media_type=MediaType.EBOOK.value,
                enabled=True,
            )
        )


def _add_ready_manifest(engine) -> str:
    now = datetime.now(UTC).replace(microsecond=0)
    scan_id = EntityId.new()
    manifest_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_runs).values(
                id=str(scan_id),
                scan_root_id=_FIXITY_ROOT_ID,
                started_at=now - timedelta(minutes=2),
                status="COMPLETED",
                completed_at=now - timedelta(minutes=1),
            )
        )
    store = SQLiteEbookFixityBaselineStore(engine)
    root_id = EntityId.parse(_FIXITY_ROOT_ID)
    lease = store.acquire_lease(root_id, manifest_id, acquired_at=now)
    store.start_build(manifest_id, scan_id, started_at=now, lease=lease)
    store.finalize_manifest(
        manifest_id,
        prepared_at=now,
        expires_at=now + timedelta(minutes=15),
        lease=lease,
    )
    store.release(lease, released_at=now)
    return str(manifest_id)


def test_analysis_job_claim_is_monotone_and_operator_claims_nothing(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )

    assert store.claim_next_job(ProcessRole.OPERATOR_WORKER, "operator") is None
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "lease")
    assert claim is not None
    assert claim.id == job_id
    assert claim.fence_epoch == 1
    assert store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "other") is None
    with engine.connect() as connection:
        states = (
            connection.execute(
                select(application_job_events.c.status)
                .where(application_job_events.c.job_id == job_id)
                .order_by(application_job_events.c.sequence_no)
            )
            .scalars()
            .all()
        )
    assert states == [JobStatus.WAITING.value, JobStatus.ACTIVE.value]


def test_job_idempotency_key_cannot_change_semantic_input(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )

    try:
        store.enqueue_ebook_fixity_analysis_job(
            actor_id=user.id,
            input_digest="c" * 64,
            idempotency_digest="b" * 64,
            binder=EbookFixityAnalysisJobBinder(
                profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
                scan_root_id=_FIXITY_ROOT_ID,
            ),
        )
    except ValueError as error:
        assert str(error) == "idempotency key was reused with different input"
    else:
        raise AssertionError("changed input must be rejected")


def test_parallel_identical_fixity_enqueue_replays_the_same_job(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    user = service.setup(
        bootstrap_code=service.bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    barrier = Barrier(2)

    def enqueue() -> str:
        barrier.wait()
        return store.enqueue_ebook_fixity_analysis_job(
            actor_id=user.id,
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
            binder=EbookFixityAnalysisJobBinder(
                profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
                scan_root_id=_FIXITY_ROOT_ID,
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        job_ids = list(executor.map(lambda _index: enqueue(), range(2)))

    assert job_ids[0] == job_ids[1]
    with engine.connect() as connection:
        assert connection.execute(select(application_jobs.c.id)).scalars().all() == [
            job_ids[0]
        ]
        assert connection.execute(
            select(ebook_fixity_analysis_job_binders.c.job_id)
        ).scalars().all() == [job_ids[0]]


def test_stale_fixity_claim_cannot_bind_a_result_or_succeed(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    user = LocalSurfaceService(store).setup(
        bootstrap_code=LocalSurfaceService(store).bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "lease")
    assert claim is not None
    with engine.begin() as connection:
        connection.execute(
            update(application_jobs)
            .where(application_jobs.c.id == job_id)
            .values(fence_epoch=claim.fence_epoch + 1)
        )
    assert not store.complete_ebook_fixity_analysis_job(
        claim,
        manifest_id="00000000-0000-4000-8000-000000000002",
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(ebook_fixity_analysis_job_results.c.job_id).where(
                    ebook_fixity_analysis_job_results.c.job_id == job_id
                )
            ).scalar_one_or_none()
            is None
        )


def test_fixity_result_and_succeeded_state_roll_back_together(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    user = LocalSurfaceService(store).setup(
        bootstrap_code=LocalSurfaceService(store).bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "lease")
    assert claim is not None
    with pytest.raises(Exception, match="FOREIGN KEY constraint failed"):
        store.complete_ebook_fixity_analysis_job(
            claim,
            manifest_id="00000000-0000-4000-8000-000000000099",
        )
    assert store.job_detail(job_id)["status"] == JobStatus.ACTIVE.value
    with engine.connect() as connection:
        assert connection.execute(
            select(ebook_fixity_analysis_job_results.c.job_id).where(
                ebook_fixity_analysis_job_results.c.job_id == job_id
            )
        ).scalar_one_or_none() is None
        states = connection.execute(
            select(application_job_events.c.status)
            .where(application_job_events.c.job_id == job_id)
            .order_by(application_job_events.c.sequence_no)
        ).scalars().all()
    assert states == [JobStatus.WAITING.value, JobStatus.ACTIVE.value]


def test_fixity_result_and_succeeded_state_commit_together(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    manifest_id = _add_ready_manifest(engine)
    store = SQLiteSurfaceStore(engine)
    user = LocalSurfaceService(store).setup(
        bootstrap_code=LocalSurfaceService(store).bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "lease")
    assert claim is not None
    assert store.complete_ebook_fixity_analysis_job(claim, manifest_id=manifest_id)
    assert store.job_detail(job_id)["status"] == JobStatus.SUCCEEDED.value
    with engine.connect() as connection:
        assert connection.execute(
            select(ebook_fixity_analysis_job_results.c.manifest_id).where(
                ebook_fixity_analysis_job_results.c.job_id == job_id
            )
        ).scalar_one() == manifest_id


def test_fixity_activation_serializes_concurrent_identical_retries(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    manifest_id = EntityId.parse(_add_ready_manifest(engine))
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    user = service.setup(
        bootstrap_code=service.bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    authenticated = service.login(username="Märta", password="ein sehr langes Passwort")
    assert authenticated is not None
    _token, _csrf, session = authenticated
    store.create_grant(session, Scope.REVIEW)
    operation = SQLiteEbookFixityBaselineActivationOperation(engine)
    command = EbookFixityBaselineActivationCommand(
        manifest_id=manifest_id,
        confirmation=expected_fixity_baseline_confirmation(manifest_id),
    )
    barrier = Barrier(2)

    def activate_once():
        barrier.wait()
        return operation.activate(
            command,
            actor_id=user.id,
            session_id=session.id,
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
            activated_at=datetime.now(UTC).replace(microsecond=0),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: activate_once(), range(2)))
    assert results[0] == results[1]
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM ebook_fixity_baseline_activations"
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM surface_command_receipts WHERE command_profile="
            "'ebook-fixity-baseline-activation/v1'"
        ).scalar_one() == 1


def test_0037_fixity_job_binders_enforce_role_profile_fks_and_immutability(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    _add_fixity_root(engine)
    store = SQLiteSurfaceStore(engine)
    user = LocalSurfaceService(store).setup(
        bootstrap_code=LocalSurfaceService(store).bootstrap(),
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    binder_fks = {
        fk["referred_table"]
        for fk in inspect(engine).get_foreign_keys("ebook_fixity_analysis_job_binders")
    }
    result_fks = {
        fk["referred_table"]
        for fk in inspect(engine).get_foreign_keys("ebook_fixity_analysis_job_results")
    }
    assert binder_fks == {"application_jobs", "scan_roots"}
    assert result_fks == {
        "application_jobs",
        "ebook_fixity_baseline_manifests",
        "ebook_fixity_verification_runs",
    }
    with engine.begin() as connection:
        with pytest.raises(Exception, match="binder does not match application job"):
            connection.execute(
                insert(ebook_fixity_analysis_job_binders).values(
                    job_id="00000000-0000-4000-8000-000000000099",
                    profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD.value,
                    scan_root_id=_FIXITY_ROOT_ID,
                    worker_count=1,
                )
            )
    wrong_job_id = "00000000-0000-4000-8000-000000000098"
    with engine.begin() as connection:
        connection.execute(
            insert(application_jobs).values(
                id=wrong_job_id,
                actor_id=user.id,
                command_profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD.value,
                input_digest="c" * 64,
                idempotency_digest="d" * 64,
                created_at="2026-08-25T10:00:00+00:00",
                status=JobStatus.WAITING.value,
                worker_role=ProcessRole.OPERATOR_WORKER.value,
                lease_digest=None,
                lease_expires_at=None,
                fence_epoch=0,
            )
        )
        with pytest.raises(Exception, match="binder does not match application job"):
            connection.execute(
                insert(ebook_fixity_analysis_job_binders).values(
                    job_id=wrong_job_id,
                    profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD.value,
                    scan_root_id=_FIXITY_ROOT_ID,
                    worker_count=1,
                )
            )
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="e" * 64,
        idempotency_digest="f" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )
    with engine.begin() as connection:
        with pytest.raises(Exception, match="immutable fixity application job identity"):
            connection.execute(
                update(application_jobs)
                .where(application_jobs.c.id == job_id)
                .values(command_profile=EbookFixityAnalysisJobProfile.VERIFICATION.value)
            )
        with pytest.raises(Exception, match="result does not match binder profile"):
            connection.execute(
                insert(ebook_fixity_analysis_job_results).values(
                    job_id=job_id,
                    manifest_id=None,
                    verification_run_id="00000000-0000-4000-8000-000000000097",
                )
            )
        with pytest.raises(Exception, match="immutable fixity surface job record"):
            connection.execute(
                update(ebook_fixity_analysis_job_binders)
                .where(ebook_fixity_analysis_job_binders.c.job_id == job_id)
                .values(worker_count=2)
            )
        with pytest.raises(Exception, match="immutable fixity surface job record"):
            connection.execute(
                delete(ebook_fixity_analysis_job_binders).where(
                    ebook_fixity_analysis_job_binders.c.job_id == job_id
                )
            )
        trigger_names = set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'ebook_fixity_analysis_job_results_no_%'"
            ).scalars()
        )
    assert trigger_names == {
        "ebook_fixity_analysis_job_results_no_update",
        "ebook_fixity_analysis_job_results_no_delete",
    }


def test_rename_planning_receipt_replays_only_the_same_actor_command_and_input(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    response = {"candidate_id": "candidate", "review_state": "PENDING"}

    assert (
        store.claim_ebook_rename_command_receipt(
            actor_id=user.id,
            command_profile="ebook-rename-proposal/v1",
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
        )
        is None
    )
    with pytest.raises(RuntimeError, match="idempotency command is pending"):
        store.claim_ebook_rename_command_receipt(
            actor_id=user.id,
            command_profile="ebook-rename-proposal/v1",
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
        )
    assert (
        store.record_ebook_rename_command_receipt(
            actor_id=user.id,
            command_profile="ebook-rename-proposal/v1",
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
            response=response,
        )
        == response
    )
    assert (
        store.ebook_rename_command_receipt(
            actor_id=user.id,
            command_profile="ebook-rename-proposal/v1",
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
        )
        == response
    )
    with pytest.raises(ValueError, match="idempotency key was reused with different input"):
        store.ebook_rename_command_receipt(
            actor_id=user.id,
            command_profile="ebook-rename-proposal/v1",
            input_digest="c" * 64,
            idempotency_digest="b" * 64,
        )


def test_operator_claim_requires_immutable_rename_binder(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    engine = create_sqlite_engine(database)
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    authenticated = service.login(username="Märta", password="ein sehr langes Passwort")
    assert authenticated is not None
    _token, _csrf, session = authenticated
    grant_id = store.create_grant(session, Scope.OPERATE)
    binder = EbookRenameOperatorJobBinder(
        profile=EbookRenameOperatorJobProfile.EXECUTE,
        plan_id="plan-id",
        plan_content_hash="a" * 64,
        capability_id="capability-id",
        operate_grant_id=grant_id,
        authorization_id="authorization-id",
        confirmation_digest="b" * 64,
    )
    job_id = store.enqueue_ebook_rename_operator_job(
        actor_id=user.id,
        input_digest="c" * 64,
        idempotency_digest="d" * 64,
        binder=binder,
    )

    claim = store.claim_next_job(ProcessRole.OPERATOR_WORKER, "operator-lease")
    assert claim is not None
    assert claim.id == job_id
    assert store.heartbeat_claimed_job(claim)
    assert store.complete_claimed_job(claim, status=JobStatus.SUCCEEDED)
    store.record_ebook_rename_operator_job_result(
        job_id=job_id,
        outcome="VERIFIED",
        run_id="run-id",
    )
    with engine.connect() as connection:
        persisted = (
            connection.execute(
                select(ebook_rename_operator_job_binders).where(
                    ebook_rename_operator_job_binders.c.job_id == job_id
                )
            )
            .mappings()
            .one()
        )
    assert persisted["confirmation_digest"] == "b" * 64
    assert store.ebook_rename_operator_job_binder(job_id) == binder
    with engine.connect() as connection:
        result = (
            connection.execute(
                select(ebook_rename_operator_job_results).where(
                    ebook_rename_operator_job_results.c.job_id == job_id
                )
            )
            .mappings()
            .one()
        )
    assert result["run_id"] == "run-id"
    with (
        engine.begin() as connection,
        pytest.raises(Exception, match="immutable e-book rename operator job"),
    ):
        connection.execute(
            update(ebook_rename_operator_job_binders)
            .where(ebook_rename_operator_job_binders.c.job_id == job_id)
            .values(capability_id="different-capability")
        )


def test_lost_operator_lease_becomes_queryable_recovery_required(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    authenticated = service.login(username="Märta", password="ein sehr langes Passwort")
    assert authenticated is not None
    _token, _csrf, session = authenticated
    job_id = store.enqueue_ebook_rename_operator_job(
        actor_id=user.id,
        input_digest="c" * 64,
        idempotency_digest="d" * 64,
        binder=EbookRenameOperatorJobBinder(
            profile=EbookRenameOperatorJobProfile.RECOVER,
            plan_id=None,
            plan_content_hash=None,
            capability_id=None,
            operate_grant_id=store.create_grant(session, Scope.OPERATE),
            run_id="run-id",
        ),
    )
    claim = store.claim_next_job(ProcessRole.OPERATOR_WORKER, "operator-lease")
    assert claim is not None

    assert store.abandon_claimed_job_for_recovery(claim, finding_code="JOB_LEASE_LOST")
    assert store.job_detail(job_id)["status"] == JobStatus.RECOVERY_REQUIRED.value
    assert store.claim_next_job(ProcessRole.OPERATOR_WORKER, "new-lease") is None
