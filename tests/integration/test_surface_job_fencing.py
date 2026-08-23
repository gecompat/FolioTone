from __future__ import annotations

from sqlalchemy import select

from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.persistence.surface_schema import application_job_events
from foliotone.surface.contracts import JobStatus, ProcessRole
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
