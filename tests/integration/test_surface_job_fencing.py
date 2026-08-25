from __future__ import annotations

import pytest
from sqlalchemy import select, update

from foliotone.application.contracts import EbookRenameOperatorJobProfile
from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import EbookRenameOperatorJobBinder, SQLiteSurfaceStore
from foliotone.persistence.surface_schema import (
    application_job_events,
    ebook_rename_operator_job_binders,
    ebook_rename_operator_job_results,
)
from foliotone.surface.contracts import JobStatus, ProcessRole, Scope
from foliotone.surface.service import LocalSurfaceService


def test_analysis_job_claim_is_monotone_and_operator_claims_nothing(head_database_factory) -> None:
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
    job_id = store.enqueue_job(
        actor_id=user.id,
        command_profile="read-only-analysis/v1",
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        worker_role=ProcessRole.ANALYSIS_WORKER,
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
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    user = service.setup(
        bootstrap_code=bootstrap,
        username="Märta",
        password="ein sehr langes Passwort",
    )
    assert user is not None
    store.enqueue_job(
        actor_id=user.id,
        command_profile="read-only-analysis/v1",
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        worker_role=ProcessRole.ANALYSIS_WORKER,
    )

    try:
        store.enqueue_job(
            actor_id=user.id,
            command_profile="read-only-analysis/v1",
            input_digest="c" * 64,
            idempotency_digest="b" * 64,
            worker_role=ProcessRole.ANALYSIS_WORKER,
        )
    except ValueError as error:
        assert str(error) == "idempotency key was reused with different input"
    else:
        raise AssertionError("changed input must be rejected")


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
