from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DatabaseError

from foliotone.core import (
    EntityId,
    EntityKind,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.fixity import (
    EbookFixityBaselineEntry,
    expected_fixity_baseline_confirmation,
)
from foliotone.fixity.verification_contracts import (
    EBOOK_FIXITY_DECISION_PROFILE,
    EbookFixityExpectationAction,
    EbookFixityExpectationDecisionInput,
    EbookFixityVerificationResult,
    EbookFixityVerificationResultRecord,
    EbookFixityVerificationRun,
    EbookFixityVerificationRunStatus,
)
from foliotone.fixity.verification_fingerprints import (
    verification_candidate_set_fingerprint,
    verification_evidence_fingerprint,
)
from foliotone.persistence import (
    ScanRootWriteOwnerKind,
    SQLiteEbookFixityBaselineStore,
    SQLiteResolutionReviewStore,
    SQLiteScanRootWriteLeaseStore,
    alembic_config,
    create_sqlite_engine,
)
from foliotone.persistence.fixity_verification import (
    EbookFixityVerificationStoreError,
    SQLiteEbookFixityVerificationStore,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
SHA = hashlib.sha256(b"synthetic-book").hexdigest()
CHANGED_SHA = hashlib.sha256(b"changed-synthetic-book").hexdigest()
TABLES = {
    "ebook_fixity_verification_runs",
    "ebook_fixity_verification_events",
    "ebook_fixity_verification_results",
    "ebook_fixity_expectation_revisions",
}


def _seed_active_baseline(
    database: Path,
    *,
    count: int = 3,
) -> tuple[EntityId, tuple[tuple[EntityId, EntityId, str], ...]]:
    root_id = EntityId.new()
    scan_id = EntityId.new()
    entries: list[tuple[EntityId, EntityId, str]] = []
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id,name,media_type,enabled) "
                "VALUES (:id,'synthetic-books','EBOOK',1)"
            ),
            {"id": str(root_id)},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'COMPLETED',:completed)"
            ),
            {
                "id": str(scan_id),
                "root": str(root_id),
                "started": (NOW - timedelta(minutes=3)).isoformat(),
                "completed": (NOW - timedelta(minutes=2)).isoformat(),
            },
        )
        for index in range(count):
            file_id = EntityId.new()
            observation_id = EntityId.new()
            locator = f"book-{index}.epub"
            connection.execute(
                text(
                    "INSERT INTO file_records "
                    "(id,scan_root_id,relative_path,size_bytes,modified_at,media_type,"
                    "presence_state,first_seen_at,last_seen_at,missing_since_at,"
                    "consecutive_missing_scans) VALUES "
                    "(:id,:root,:path,14,:modified,'EBOOK','PRESENT',:seen,:seen,NULL,0)"
                ),
                {
                    "id": str(file_id),
                    "root": str(root_id),
                    "path": locator,
                    "modified": (NOW - timedelta(minutes=5)).isoformat(),
                    "seen": NOW.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO file_observations "
                    "(id,file_id,scan_run_id,relative_path,size_bytes,modified_at,observed_at) "
                    "VALUES (:id,:file,:scan,:path,14,:modified,:observed)"
                ),
                {
                    "id": str(observation_id),
                    "file": str(file_id),
                    "scan": str(scan_id),
                    "path": locator,
                    "modified": (NOW - timedelta(minutes=5)).isoformat(),
                    "observed": NOW.isoformat(),
                },
            )
            entries.append((file_id, observation_id, locator))

    baseline = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = baseline.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW - timedelta(minutes=1),
        lease_duration=timedelta(minutes=5),
    )
    baseline.start_build(
        manifest_id,
        scan_id,
        started_at=NOW - timedelta(minutes=1),
        lease=lease,
    )
    baseline.append_entries(
        manifest_id,
        tuple(
            EbookFixityBaselineEntry(
                ordinal=index,
                file_id=file_id,
                observation_id=observation_id,
                expected_size_bytes=14,
                relative_locator=locator,
                expected_sha256=SHA,
            )
            for index, (file_id, observation_id, locator) in enumerate(entries)
        ),
        lease=lease,
        committed_at=NOW - timedelta(seconds=50),
    )
    baseline.finalize_manifest(
        manifest_id,
        prepared_at=NOW - timedelta(seconds=45),
        expires_at=NOW + timedelta(minutes=14),
        lease=lease,
    )
    baseline.release(lease, released_at=NOW - timedelta(seconds=40))
    baseline.activate(
        manifest_id,
        expected_fixity_baseline_confirmation(manifest_id),
        activated_at=NOW - timedelta(seconds=30),
    )
    engine.dispose()
    return root_id, tuple(entries)


def _result(
    run_id: EntityId,
    item: object,
    *,
    changed: bool = False,
) -> EbookFixityVerificationResultRecord:
    return EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=run_id,
        file_id=item.file_id,
        result=(
            EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE
            if changed
            else EbookFixityVerificationResult.VERIFIED
        ),
        expected_observation_id=item.expected_observation_id,
        expected_size_bytes=item.expected_size_bytes,
        expected_sha256=item.expected_sha256,
        expected_relative_locator=item.expected_relative_locator,
        current_observation_id=item.current_observation_id,
        current_size_bytes=item.current_size_bytes,
        current_sha256=CHANGED_SHA if changed else SHA,
        current_relative_locator=item.current_relative_locator,
    )


def _accept_result_review(
    engine: Engine,
    completed: EbookFixityVerificationRun,
    result: EbookFixityVerificationResultRecord,
    *,
    created_at: datetime,
) -> tuple[str, str, ReviewDecision]:
    assert completed.content_digest is not None
    evidence = verification_evidence_fingerprint(
        subject_id=result.file_id,
        scan_root_id=completed.scan_root_id,
        baseline_activation_id=completed.baseline_activation_id,
        expectation_revision_no=completed.expectation_revision_no,
        expectation_revision_digest=completed.expectation_revision_digest,
        scan_run_id=completed.source_scan_run_id,
        verification_run_id=completed.run_id,
        verification_run_content_digest=completed.content_digest,
        result_id=result.result_id,
        result_content_digest=result.content_digest,
    )
    candidates = verification_candidate_set_fingerprint(result)
    review = ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.FIXITY_EXPECTATION,
        subject_kind=EntityKind.FILE,
        subject_id=result.file_id,
        candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
        candidate_id=result.result_id,
        producer_name="ebook-fixity-verification",
        producer_version="1",
        decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
        evidence_fingerprint=evidence,
        candidate_set_fingerprint=candidates,
        state=ReviewItemState.PENDING,
        created_at=created_at,
    )
    reviews = SQLiteResolutionReviewStore(engine)
    reviews.enqueue_or_get_review(review)
    accepted = ReviewDecision(
        id=EntityId.new(),
        review_item_id=review.id,
        sequence_no=1,
        decision=ReviewDecisionValue.ACCEPT,
        decision_reason="REVIEWED_FIXITY_RESULT",
        evidence_fingerprint=evidence,
        candidate_set_fingerprint=candidates,
        decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
        actor_kind=ReviewActorKind.USER,
        decided_at=created_at + timedelta(seconds=1),
    )
    reviews.append_decision(accepted, expected_latest_decision_id=None)
    return evidence, candidates, accepted


def test_0036_schema_and_bounded_exact_verification_flow(head_database: Path) -> None:
    root_id, _ = _seed_active_baseline(head_database)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityVerificationStore(engine)
    owned = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW,
        lease_token="verification-one",
        lease_expires_at=NOW + timedelta(minutes=5),
    )

    first_page = store.read_workset_batch(
        owned,
        observed_at=NOW + timedelta(seconds=1),
        batch_size=2,
    )
    second_page = store.read_workset_batch(
        owned,
        observed_at=NOW + timedelta(seconds=2),
        after_file_id=first_page[-1].file_id,
        batch_size=2,
    )
    items = first_page + second_page
    assert len(first_page) == 2
    assert len(second_page) == 1
    assert len({item.file_id for item in items}) == 3
    assert "book-" not in repr(items)
    assert SHA not in repr(items)

    results = tuple(
        _result(owned.run.run_id, item, changed=index == 0) for index, item in enumerate(items)
    )
    store.append_results(
        owned,
        results[:2],
        recorded_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(EbookFixityVerificationStoreError, match="exact bound workset"):
        store.complete_run(owned, completed_at=NOW + timedelta(seconds=4))
    store.append_results(
        owned,
        results[2:],
        recorded_at=NOW + timedelta(seconds=5),
    )
    completed = store.complete_run(owned, completed_at=NOW + timedelta(seconds=6))

    assert completed.result_count == 3
    assert completed.content_digest is not None
    assert store.read_result(results[0].result_id) == results[0]
    assert store.read_run(owned.run.run_id) == completed
    assert TABLES.issubset(inspect(engine).get_table_names())
    with engine.begin() as connection, pytest.raises(DatabaseError):
        connection.execute(
            text("DELETE FROM ebook_fixity_verification_results WHERE id=:id"),
            {"id": str(results[0].result_id)},
        )

    repeated = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW + timedelta(seconds=7),
        lease_token="verification-repeat",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    assert repeated.run.source_scan_run_id == owned.run.source_scan_run_id
    store.fail_run(
        repeated,
        failed_at=NOW + timedelta(seconds=8),
        failure_code="TEST_STOP",
    )
    failed = store.read_run(repeated.run.run_id)
    assert failed is not None
    assert failed.status is EbookFixityVerificationRunStatus.FAILED
    assert failed.completed_at == NOW + timedelta(seconds=8)
    assert failed.content_digest is None
    engine.dispose()


def test_0036_downgrade_refuses_an_active_verification_lease(
    head_database: Path,
) -> None:
    root_id, _ = _seed_active_baseline(head_database, count=1)
    engine = create_sqlite_engine(head_database)
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.acquire(
        root_id,
        ScanRootWriteOwnerKind.EBOOK_FIXITY_VERIFICATION,
        EntityId.new(),
        lease_token="active-verification-lease",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    engine.dispose()

    with pytest.raises(RuntimeError, match="state prevents migration downgrade"):
        command.downgrade(
            alembic_config(head_database),
            "0035_ebook_fixity_baseline",
        )


def test_completed_actionable_result_review_and_revision_are_exactly_bound(
    head_database: Path,
) -> None:
    root_id, _ = _seed_active_baseline(head_database, count=1)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityVerificationStore(engine)
    owned = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW,
        lease_token="verification-review",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    item = store.read_workset_batch(
        owned,
        observed_at=NOW + timedelta(seconds=1),
        batch_size=1,
    )[0]
    result = _result(owned.run.run_id, item, changed=True)
    store.append_results(owned, (result,), recorded_at=NOW + timedelta(seconds=2))
    completed = store.complete_run(owned, completed_at=NOW + timedelta(seconds=3))
    evidence = verification_evidence_fingerprint(
        subject_id=result.file_id,
        scan_root_id=completed.scan_root_id,
        baseline_activation_id=completed.baseline_activation_id,
        expectation_revision_no=completed.expectation_revision_no,
        expectation_revision_digest=completed.expectation_revision_digest,
        scan_run_id=completed.source_scan_run_id,
        verification_run_id=completed.run_id,
        verification_run_content_digest=completed.content_digest,
        result_id=result.result_id,
        result_content_digest=result.content_digest,
    )
    candidates = verification_candidate_set_fingerprint(result)
    review = ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.FIXITY_EXPECTATION,
        subject_kind=EntityKind.FILE,
        subject_id=result.file_id,
        candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
        candidate_id=result.result_id,
        producer_name="ebook-fixity-verification",
        producer_version="1",
        decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
        evidence_fingerprint=evidence,
        candidate_set_fingerprint=candidates,
        state=ReviewItemState.PENDING,
        created_at=NOW + timedelta(seconds=4),
    )
    reviews = SQLiteResolutionReviewStore(engine)
    reviews.enqueue_or_get_review(review)
    accepted = ReviewDecision(
        id=EntityId.new(),
        review_item_id=review.id,
        sequence_no=1,
        decision=ReviewDecisionValue.ACCEPT,
        decision_reason="REVIEWED_FIXITY_RESULT",
        evidence_fingerprint=evidence,
        candidate_set_fingerprint=candidates,
        decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW + timedelta(seconds=5),
    )
    reviews.append_decision(accepted, expected_latest_decision_id=None)
    request = EbookFixityExpectationDecisionInput(
        result_id=result.result_id,
        run_id=result.run_id,
        file_id=result.file_id,
        action=EbookFixityExpectationAction.ACCEPT_CURRENT,
        evidence_fingerprint=evidence,
        candidate_set_fingerprint=candidates,
        review_decision_id=accepted.id,
    )
    created_at = NOW + timedelta(seconds=6)
    revision = store.append_expectation_revision(
        request,
        created_at=created_at,
        lease_token="expectation-revision",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    assert revision.revision_no == 1
    assert (
        store.append_expectation_revision(
            request,
            created_at=created_at,
            lease_token="exact-retry",
            lease_expires_at=NOW + timedelta(minutes=5),
        )
        == revision
    )
    with pytest.raises(EbookFixityVerificationStoreError, match="different immutable"):
        store.append_expectation_revision(
            replace(request, action=EbookFixityExpectationAction.RETIRE_MISSING),
            created_at=created_at,
            lease_token="divergent-retry",
            lease_expires_at=NOW + timedelta(minutes=5),
        )
    with pytest.raises(EbookFixityVerificationStoreError, match="different immutable"):
        store.append_expectation_revision(
            replace(request, run_id=EntityId.new()),
            created_at=created_at,
            lease_token="divergent-run-retry",
            lease_expires_at=NOW + timedelta(minutes=5),
        )
    engine.dispose()


def test_newer_verification_invalidates_older_accepted_review(
    head_database: Path,
) -> None:
    root_id, _ = _seed_active_baseline(head_database, count=1)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityVerificationStore(engine)
    older = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW,
        lease_token="older-verification",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    work = store.read_workset_batch(
        older,
        observed_at=NOW + timedelta(seconds=1),
        batch_size=1,
    )[0]
    result = _result(older.run.run_id, work, changed=True)
    store.append_results(older, (result,), recorded_at=NOW + timedelta(seconds=2))
    completed = store.complete_run(older, completed_at=NOW + timedelta(seconds=3))
    evidence, candidates, accepted = _accept_result_review(
        engine,
        completed,
        result,
        created_at=NOW + timedelta(seconds=4),
    )

    newer = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW + timedelta(seconds=6),
        lease_token="newer-verification",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    store.fail_run(
        newer,
        failed_at=NOW + timedelta(seconds=7),
        failure_code="TEST_STOP",
    )
    with pytest.raises(EbookFixityVerificationStoreError, match="latest verification run"):
        store.append_expectation_revision(
            EbookFixityExpectationDecisionInput(
                result_id=result.result_id,
                run_id=result.run_id,
                file_id=result.file_id,
                action=EbookFixityExpectationAction.ACCEPT_CURRENT,
                evidence_fingerprint=evidence,
                candidate_set_fingerprint=candidates,
                review_decision_id=accepted.id,
            ),
            created_at=NOW + timedelta(seconds=8),
            lease_token="stale-expectation",
            lease_expires_at=NOW + timedelta(minutes=5),
        )
    engine.dispose()


def test_retire_missing_appends_tombstone_and_removes_next_workset(
    head_database: Path,
) -> None:
    root_id, entries = _seed_active_baseline(head_database, count=1)
    file_id = entries[0][0]
    current_scan_id = EntityId.new()
    engine = create_sqlite_engine(head_database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'COMPLETED',:completed)"
            ),
            {
                "id": str(current_scan_id),
                "root": str(root_id),
                "started": (NOW + timedelta(seconds=1)).isoformat(),
                "completed": (NOW + timedelta(seconds=2)).isoformat(),
            },
        )
        connection.execute(
            text(
                "UPDATE file_records SET presence_state='MISSING',"
                "missing_since_at=:missing,consecutive_missing_scans=1 WHERE id=:id"
            ),
            {
                "missing": (NOW + timedelta(seconds=2)).isoformat(),
                "id": str(file_id),
            },
        )

    store = SQLiteEbookFixityVerificationStore(engine)
    owned = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW + timedelta(seconds=3),
        lease_token="missing-verification",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    work = store.read_workset_batch(
        owned,
        observed_at=NOW + timedelta(seconds=4),
        batch_size=1,
    )[0]
    assert work.current_observation_id is None
    missing = EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=owned.run.run_id,
        file_id=work.file_id,
        result=EbookFixityVerificationResult.MISSING,
        expected_observation_id=work.expected_observation_id,
        expected_size_bytes=work.expected_size_bytes,
        expected_sha256=work.expected_sha256,
        expected_relative_locator=work.expected_relative_locator,
    )
    store.append_results(owned, (missing,), recorded_at=NOW + timedelta(seconds=5))
    completed = store.complete_run(owned, completed_at=NOW + timedelta(seconds=6))
    evidence, candidates, accepted = _accept_result_review(
        engine,
        completed,
        missing,
        created_at=NOW + timedelta(seconds=7),
    )
    revision = store.append_expectation_revision(
        EbookFixityExpectationDecisionInput(
            result_id=missing.result_id,
            run_id=missing.run_id,
            file_id=missing.file_id,
            action=EbookFixityExpectationAction.RETIRE_MISSING,
            evidence_fingerprint=evidence,
            candidate_set_fingerprint=candidates,
            review_decision_id=accepted.id,
        ),
        created_at=NOW + timedelta(seconds=9),
        lease_token="retire-missing",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    assert revision.revision_no == 1
    assert revision.action is EbookFixityExpectationAction.RETIRE_MISSING
    assert revision.expected_observation_id is None

    following = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW + timedelta(seconds=10),
        lease_token="post-retirement-verification",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    assert following.run.expectation_revision_no == 1
    assert following.run.expectation_revision_digest == revision.revision_digest
    assert following.expected_result_count == 0
    assert (
        store.read_workset_batch(
            following,
            observed_at=NOW + timedelta(seconds=11),
            batch_size=1,
        )
        == ()
    )
    completed_following = store.complete_run(
        following,
        completed_at=NOW + timedelta(seconds=12),
    )
    assert completed_following.result_count == 0
    engine.dispose()


def test_expired_lease_takeover_fails_prior_run_and_preserves_partial_results(
    head_database: Path,
) -> None:
    root_id, _ = _seed_active_baseline(head_database, count=1)
    engine = create_sqlite_engine(head_database)
    store = SQLiteEbookFixityVerificationStore(engine)
    expired = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW,
        lease_token="expiring-verification",
        lease_expires_at=NOW + timedelta(seconds=5),
    )
    item = store.read_workset_batch(
        expired,
        observed_at=NOW + timedelta(seconds=1),
        batch_size=1,
    )[0]
    unsafe = EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=expired.run.run_id,
        file_id=item.file_id,
        result=EbookFixityVerificationResult.UNREADABLE,
        expected_observation_id=item.expected_observation_id,
        expected_size_bytes=item.expected_size_bytes,
        expected_sha256=item.expected_sha256,
        expected_relative_locator=item.expected_relative_locator,
        current_observation_id=item.current_observation_id,
        current_size_bytes=item.current_size_bytes,
        current_sha256=None,
        current_relative_locator=item.current_relative_locator,
        failure_code="SOURCE_UNREADABLE",
    )
    store.append_results(
        expired,
        (unsafe,),
        recorded_at=NOW + timedelta(seconds=2),
    )

    replacement = store.start_run(
        EntityId.new(),
        root_id,
        started_at=NOW + timedelta(seconds=6),
        lease_token="replacement-verification",
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    old_status = store.read_status(expired.run.run_id)
    assert old_status is not None
    assert old_status.status.value == "FAILED"
    assert old_status.failure_code == "LEASE_EXPIRED"
    assert store.read_result(unsafe.result_id) == unsafe
    with pytest.raises(EbookFixityVerificationStoreError):
        store.append_results(
            expired,
            (unsafe,),
            recorded_at=NOW + timedelta(seconds=7),
        )
    store.fail_run(
        replacement,
        failed_at=NOW + timedelta(seconds=8),
        failure_code="TEST_STOP",
    )
    engine.dispose()


@pytest.mark.parametrize("latest_status", ["RUNNING", "FAILED"])
def test_start_fails_closed_when_latest_scan_is_not_completed(
    head_database: Path,
    latest_status: str,
) -> None:
    root_id, _ = _seed_active_baseline(head_database, count=1)
    engine = create_sqlite_engine(head_database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,:status,:completed)"
            ),
            {
                "id": str(EntityId.new()),
                "root": str(root_id),
                "started": (NOW + timedelta(seconds=1)).isoformat(),
                "status": latest_status,
                "completed": None,
            },
        )
    store = SQLiteEbookFixityVerificationStore(engine)
    with pytest.raises(EbookFixityVerificationStoreError, match="latest completed"):
        store.start_run(
            EntityId.new(),
            root_id,
            started_at=NOW + timedelta(seconds=2),
            lease_token="blocked",
            lease_expires_at=NOW + timedelta(minutes=5),
        )
    engine.dispose()
