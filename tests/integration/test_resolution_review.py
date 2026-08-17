from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from foliotone.authority import (
    resolution_candidate_set_fingerprint,
    resolution_evidence_fingerprint,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileRecord,
    MediaType,
    PresenceState,
    Provenance,
    ResolutionCandidate,
    ResolutionDisposition,
    ResolutionEvidenceKind,
    ResolutionEvidenceLink,
    ResolutionEvidenceRole,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ScanRoot,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.persistence import (
    ResolutionReviewStoreError,
    SQLiteResolutionReviewStore,
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
)
from foliotone.persistence import resolution_review_schema as rr_schema

NOW = datetime(2026, 8, 17, 18, 30, tzinfo=UTC)
MATERIAL = "1" * 64
COMPATIBILITY = "authority-decision/v1"


def _graph(database: Path) -> tuple[FileRecord, Work, ValueAssertion]:
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name="synthetic-resolution", media_type=MediaType.EBOOK)
    file = FileRecord(
        id=EntityId.new(),
        scan_root_id=root.id,
        relative_path="synthetic.epub",
        size_bytes=10,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    work = Work(id=EntityId.new())
    assertion = ValueAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.FILE,
        target_id=file.id,
        field_name="work.title.normalized",
        value="synthetic title",
        state=ValueState.DERIVED,
        provenance=Provenance(
            source_kind="synthetic",
            source_name="offline-resolution-test",
            source_version="1",
            observed_at=NOW,
        ),
        confidence=0.5,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, FileRecord).save(file)
    repository(engine, Work).save(work)
    repository(engine, ValueAssertion).save(assertion)
    engine.dispose()
    return file, work, assertion


def _candidate_and_links(
    file: FileRecord,
    work: Work,
    assertion: ValueAssertion,
    *,
    candidate_id: EntityId | None = None,
    resolver_version: str = "offline-resolution/v1",
    disposition: ResolutionDisposition = ResolutionDisposition.REVIEW_REQUIRED,
    accepted_decision_id: EntityId | None = None,
) -> tuple[ResolutionCandidate, tuple[ResolutionEvidenceLink, ...]]:
    candidate_id = candidate_id or EntityId.new()
    material_link = ResolutionEvidenceLink(
        id=EntityId.new(),
        resolution_candidate_id=candidate_id,
        ordinal=0,
        evidence_kind=ResolutionEvidenceKind.VALUE_ASSERTION,
        evidence_id=assertion.id,
        evidence_role=ResolutionEvidenceRole.SUPPORTS,
        asserted_entity_kind=EntityKind.WORK,
        material_fingerprint=MATERIAL,
    )
    links = [material_link]
    if accepted_decision_id is not None:
        links.append(
            ResolutionEvidenceLink(
                id=EntityId.new(),
                resolution_candidate_id=candidate_id,
                ordinal=1,
                evidence_kind=ResolutionEvidenceKind.REVIEW_DECISION,
                evidence_id=accepted_decision_id,
                evidence_role=ResolutionEvidenceRole.SUPPORTS,
                asserted_entity_kind=EntityKind.WORK,
                material_fingerprint="2" * 64,
            )
        )
    candidate_set = resolution_candidate_set_fingerprint(((EntityKind.WORK, work.id),))
    candidate = ResolutionCandidate(
        id=candidate_id,
        subject_kind=EntityKind.FILE,
        subject_id=file.id,
        candidate_kind=EntityKind.WORK,
        candidate_entity_id=work.id,
        resolver_name="offline-book-resolution",
        resolver_version=resolver_version,
        decision_compatibility_version=COMPATIBILITY,
        evidence_fingerprint=resolution_evidence_fingerprint(links),
        candidate_set_fingerprint=candidate_set,
        confidence=0.6,
        disposition=disposition,
        created_at=NOW,
    )
    return candidate, tuple(links)


def _review(candidate: ResolutionCandidate, *, producer_version: str = "1") -> ReviewItem:
    return ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.AUTHORITY_RESOLUTION,
        subject_kind=candidate.subject_kind,
        subject_id=candidate.subject_id,
        candidate_kind=ReviewCandidateKind.RESOLUTION_CANDIDATE,
        candidate_id=candidate.id,
        producer_name=candidate.resolver_name,
        producer_version=producer_version,
        decision_compatibility_version=candidate.decision_compatibility_version,
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.candidate_set_fingerprint,
        state=ReviewItemState.PENDING,
        created_at=NOW,
    )


def _decision(
    item: ReviewItem,
    *,
    sequence: int,
    value: ReviewDecisionValue,
    decision_id: EntityId | None = None,
) -> ReviewDecision:
    return ReviewDecision(
        id=decision_id or EntityId.new(),
        review_item_id=item.id,
        sequence_no=sequence,
        decision=value,
        decision_reason="REVIEWED_LOCAL_EVIDENCE",
        evidence_fingerprint=item.evidence_fingerprint,
        candidate_set_fingerprint=item.candidate_set_fingerprint,
        decision_compatibility_version=item.decision_compatibility_version,
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW,
    )


def test_candidate_review_and_append_only_decision_history(tmp_path: Path) -> None:
    database = tmp_path / "resolution.db"
    file, work, assertion = _graph(database)
    engine = create_sqlite_engine(database)
    store = SQLiteResolutionReviewStore(engine)
    candidate, links = _candidate_and_links(file, work, assertion)

    persisted = store.create_or_get_candidate(candidate, links)
    retry_candidate, retry_links = _candidate_and_links(
        file,
        work,
        assertion,
        candidate_id=EntityId.new(),
    )
    assert store.create_or_get_candidate(retry_candidate, retry_links).id == persisted.id
    assert store.list_candidates_for_subject(EntityKind.FILE, file.id).items == (persisted,)
    assert store.list_evidence(persisted.id) == links

    item = store.enqueue_or_get_review(_review(persisted))
    same_case = store.enqueue_or_get_review(
        replace(_review(persisted, producer_version="2"), candidate_id=persisted.id)
    )
    assert same_case.id == item.id
    assert store.list_queue().items == (item,)

    deferred = _decision(item, sequence=1, value=ReviewDecisionValue.DEFER)
    store.append_decision(deferred, expected_latest_decision_id=None)
    accepted = _decision(item, sequence=2, value=ReviewDecisionValue.ACCEPT)
    store.append_decision(accepted, expected_latest_decision_id=deferred.id)

    assert store.list_history(item.id) == (deferred, accepted)
    assert store.get_effective_decision(item.id) == accepted
    assert store.list_queue().items == ()
    assert store.find_reusable_decision(
        replace(candidate, resolver_version="refactor/v2")
    ) == accepted
    assert store.find_reusable_decision(
        replace(candidate, candidate_set_fingerprint="f" * 64)
    ) is None

    auto_candidate, auto_links = _candidate_and_links(
        file,
        work,
        assertion,
        resolver_version="offline-resolution/v2",
        disposition=ResolutionDisposition.AUTO_SAFE,
        accepted_decision_id=accepted.id,
    )
    assert store.create_or_get_candidate(auto_candidate, auto_links) == auto_candidate
    incompatible_candidate, incompatible_links = _candidate_and_links(
        file,
        work,
        assertion,
        resolver_version="offline-resolution/v3",
        disposition=ResolutionDisposition.AUTO_SAFE,
        accepted_decision_id=accepted.id,
    )
    incompatible_candidate = replace(
        incompatible_candidate,
        candidate_set_fingerprint="f" * 64,
    )
    with pytest.raises(ResolutionReviewStoreError, match="not compatible"):
        store.create_or_get_candidate(incompatible_candidate, incompatible_links)
    with pytest.raises(ResolutionReviewStoreError, match="must not enter review"):
        store.enqueue_or_get_review(_review(auto_candidate))

    deferred_again = _decision(item, sequence=3, value=ReviewDecisionValue.DEFER)
    store.append_decision(deferred_again, expected_latest_decision_id=accepted.id)
    assert store.find_reusable_decision(candidate) is None
    assert store.list_queue().items == (replace(item, state=ReviewItemState.DEFERRED),)

    assert repository(engine, ValueAssertion).get(assertion.id) == assertion


def test_invalid_evidence_and_optimistic_decision_fence_roll_back(tmp_path: Path) -> None:
    database = tmp_path / "rollback.db"
    file, work, assertion = _graph(database)
    engine = create_sqlite_engine(database)
    store = SQLiteResolutionReviewStore(engine)
    candidate, links = _candidate_and_links(file, work, assertion)
    invalid = replace(links[0], evidence_id=EntityId.new())
    with pytest.raises(ResolutionReviewStoreError, match="does not exist"):
        store.create_or_get_candidate(candidate, (invalid,))
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(rr_schema.resolution_candidates)
        ).scalar_one() == 0

    store.create_or_get_candidate(candidate, links)
    item = store.enqueue_or_get_review(_review(candidate))
    stale = replace(
        _decision(item, sequence=1, value=ReviewDecisionValue.REJECT),
        evidence_fingerprint="e" * 64,
    )
    with pytest.raises(ResolutionReviewStoreError, match="snapshot is stale"):
        store.append_decision(stale, expected_latest_decision_id=None)
    assert store.list_history(item.id) == ()


def test_decision_sequence_and_same_id_are_strict(tmp_path: Path) -> None:
    database = tmp_path / "sequence.db"
    file, work, assertion = _graph(database)
    engine = create_sqlite_engine(database)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                rr_schema.resolution_candidates.insert().values(
                    id=str(EntityId.new()),
                    subject_kind=EntityKind.FILE.value,
                    subject_id=str(file.id),
                    candidate_kind=EntityKind.WORK.value,
                    candidate_entity_id=str(work.id),
                    resolver_name="offline-book-resolution",
                    resolver_version="1",
                    decision_compatibility_version=COMPATIBILITY,
                    evidence_fingerprint="A" * 64,
                    candidate_set_fingerprint="b" * 64,
                    confidence=0.5,
                    disposition=ResolutionDisposition.REVIEW_REQUIRED.value,
                    created_at=NOW.isoformat(),
                )
            )
    store = SQLiteResolutionReviewStore(engine)
    candidate, links = _candidate_and_links(file, work, assertion)
    store.create_or_get_candidate(candidate, links)
    item = store.enqueue_or_get_review(_review(candidate))
    accepted = _decision(item, sequence=1, value=ReviewDecisionValue.ACCEPT)
    assert store.append_decision(accepted, expected_latest_decision_id=None) == accepted
    assert store.append_decision(accepted, expected_latest_decision_id=None) == accepted

    with pytest.raises(ResolutionReviewStoreError, match="different content"):
        store.append_decision(
            replace(accepted, decision=ReviewDecisionValue.REJECT),
            expected_latest_decision_id=accepted.id,
        )
    with pytest.raises(ResolutionReviewStoreError, match="sequence"):
        store.append_decision(
            _decision(item, sequence=3, value=ReviewDecisionValue.REJECT),
            expected_latest_decision_id=accepted.id,
        )


def test_migration_0012_upgrade_and_nonempty_downgrade_guard(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    migrate(database, "0012_scan_root_write_leases")
    legacy = create_sqlite_engine(database)
    assert "resolution_candidates" not in inspect(legacy).get_table_names()
    legacy.dispose()

    migrate(database)
    upgraded = create_sqlite_engine(database)
    assert {
        "resolution_candidates",
        "resolution_candidate_evidence",
        "review_items",
        "review_decisions",
    } <= set(inspect(upgraded).get_table_names())
    command.downgrade(alembic_config(database), "0012_scan_root_write_leases")
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0012_scan_root_write_leases"
        )
    upgraded.dispose()

    file, work, assertion = _graph(database)
    store = SQLiteResolutionReviewStore(create_sqlite_engine(database))
    candidate, links = _candidate_and_links(file, work, assertion)
    store.create_or_get_candidate(candidate, links)
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(database), "0012_scan_root_write_leases")
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0013_resolution_review_core"
        )
