from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text

from foliotone.core import (
    EntityId,
    EntityKind,
    FileRecord,
    Fingerprint,
    MatchStatus,
    MediaType,
    PresenceState,
    Provenance,
    RelationType,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.matching import (
    EbookRelationMatcher,
    MatcherFeature,
    MatcherFeatureCode,
    MatcherFeatureState,
    RelationCandidate,
    RelationCandidateEvidenceKind,
    RelationCandidateEvidenceLink,
    relation_candidate_set_fingerprint,
)
from foliotone.persistence import (
    RelationCandidateStoreError,
    SQLiteRelationCandidateStore,
    SQLiteResolutionReviewStore,
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
)
from foliotone.persistence import relation_candidate_schema as rc_schema

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
MATERIAL = "a" * 64


def _graph(database: Path):
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-matching", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    files = tuple(
        sorted(
            (
                FileRecord(
                    EntityId.new(),
                    root.id,
                    f"synthetic-{ordinal}.epub",
                    10,
                    NOW,
                    MediaType.EBOOK,
                    PresenceState.PRESENT,
                    NOW,
                    NOW,
                )
                for ordinal in range(2)
            ),
            key=lambda item: str(item.id),
        )
    )
    fingerprints = []
    for file in files:
        repository(engine, FileRecord).save(file)
        fingerprint = Fingerprint(
            EntityId.new(), EntityKind.FILE, file.id, "FILE_SHA256", "sha256", "1", MATERIAL, NOW
        )
        repository(engine, Fingerprint).save(fingerprint)
        fingerprints.append(fingerprint)
    return engine, root, scan, files, tuple(fingerprints)


def _candidate(root, scan, files, fingerprints, *, candidate_id=None, evidence_id=None):
    referenced_ids = tuple(
        evidence_id if evidence_id is not None and ordinal == 0 else item.id
        for ordinal, item in enumerate(fingerprints)
    )
    evidence_ids = tuple(sorted(referenced_ids, key=str))
    feature = MatcherFeature(
        MatcherFeatureCode.FILE_SHA256_EQUAL,
        MatcherFeatureState.PRESENT,
        MATERIAL,
        evidence_ids,
    )
    outcome = EbookRelationMatcher().score(
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        files[0].id,
        EntityKind.FILE,
        files[1].id,
        (feature,),
    )
    candidate_set = relation_candidate_set_fingerprint(
        (
            (
                outcome.relation_type,
                outcome.left_kind,
                outcome.left_id,
                outcome.right_kind,
                outcome.right_id,
            ),
        )
    )
    candidate = RelationCandidate.from_outcome(
        candidate_id or EntityId.new(), root.id, scan.id, candidate_set, outcome, NOW
    )
    links = tuple(
        RelationCandidateEvidenceLink(
            EntityId.new(),
            candidate.id,
            ordinal,
            feature.code,
            feature.state,
            feature.material_fingerprint,
            RelationCandidateEvidenceKind.FINGERPRINT,
            referenced_ids[ordinal],
        )
        for ordinal, fingerprint in enumerate(fingerprints)
    )
    return candidate, links


def test_relation_candidate_is_insert_only_idempotent_and_path_free(
    head_database: Path,
) -> None:
    engine, root, scan, files, fingerprints = _graph(head_database)
    store = SQLiteRelationCandidateStore(engine)
    candidate, links = _candidate(root, scan, files, fingerprints)

    assert candidate.status is MatchStatus.CONFIRMED
    assert store.create_or_get(candidate, links) == candidate
    retry, retry_links = _candidate(root, scan, files, fingerprints)
    assert store.create_or_get(retry, retry_links).id == candidate.id
    assert store.get(candidate.id) == candidate
    assert store.evidence(candidate.id) == links
    rendered = repr(candidate)
    assert "synthetic-0.epub" not in rendered
    assert MATERIAL not in rendered


def test_invalid_reference_rolls_back_candidate_and_links(head_database: Path) -> None:
    engine, root, scan, files, fingerprints = _graph(head_database)
    store = SQLiteRelationCandidateStore(engine)
    candidate, links = _candidate(root, scan, files, fingerprints, evidence_id=EntityId.new())
    with pytest.raises(RelationCandidateStoreError, match="does not exist"):
        store.create_or_get(candidate, links)
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(rc_schema.relation_candidates)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(func.count()).select_from(rc_schema.relation_candidate_evidence)
            ).scalar_one()
            == 0
        )


def test_matching_review_reuses_accept_and_reject_but_not_defer(
    head_database: Path,
) -> None:
    engine, root, scan, _, _ = _graph(head_database)
    works = tuple(
        sorted((Work(EntityId.new()), Work(EntityId.new())), key=lambda item: str(item.id))
    )
    assertions = []
    for work in works:
        repository(engine, Work).save(work)
        assertion = ValueAssertion(
            EntityId.new(),
            EntityKind.WORK,
            work.id,
            "work.title.normalized",
            "synthetic-title",
            ValueState.DERIVED,
            Provenance("synthetic", "matching-review", NOW, "1"),
        )
        repository(engine, ValueAssertion).save(assertion)
        assertions.append(assertion)
    evidence_ids = tuple(sorted((item.id for item in assertions), key=str))
    feature = MatcherFeature(
        MatcherFeatureCode.TITLE_COMPATIBLE,
        MatcherFeatureState.PRESENT,
        MATERIAL,
        evidence_ids,
    )
    outcome = EbookRelationMatcher().score(
        RelationType.SAME_WORK,
        EntityKind.WORK,
        works[0].id,
        EntityKind.WORK,
        works[1].id,
        (feature,),
    )
    candidate_set = relation_candidate_set_fingerprint(
        (
            (
                outcome.relation_type,
                outcome.left_kind,
                outcome.left_id,
                outcome.right_kind,
                outcome.right_id,
            ),
        )
    )
    candidate = RelationCandidate.from_outcome(
        EntityId.new(), root.id, scan.id, candidate_set, outcome, NOW
    )
    links = tuple(
        RelationCandidateEvidenceLink(
            EntityId.new(),
            candidate.id,
            ordinal,
            feature.code,
            feature.state,
            MATERIAL,
            RelationCandidateEvidenceKind.VALUE_ASSERTION,
            assertion.id,
        )
        for ordinal, assertion in enumerate(assertions)
    )
    store = SQLiteRelationCandidateStore(engine)
    store.create_or_get(candidate, links)
    item = ReviewItem(
        EntityId.new(),
        ReviewType.MATCH_RELATION,
        candidate.left_kind,
        candidate.left_id,
        ReviewCandidateKind.RELATION,
        candidate.id,
        candidate.matcher_name,
        candidate.matcher_version,
        candidate.decision_compatibility_version,
        candidate.evidence_fingerprint,
        candidate.candidate_set_fingerprint,
        ReviewItemState.PENDING,
        NOW,
    )
    assert store.enqueue_review(candidate.id, item) == item
    decision_store = SQLiteResolutionReviewStore(engine)
    accepted = ReviewDecision(
        EntityId.new(),
        item.id,
        1,
        ReviewDecisionValue.ACCEPT,
        "MATCH_REVIEWED",
        item.evidence_fingerprint,
        item.candidate_set_fingerprint,
        item.decision_compatibility_version,
        ReviewActorKind.USER,
        NOW,
    )
    decision_store.append_decision(accepted, expected_latest_decision_id=None)
    assert store.find_reusable_decision(candidate) == accepted
    rejected = ReviewDecision(
        EntityId.new(),
        item.id,
        2,
        ReviewDecisionValue.REJECT,
        "MATCH_REJECTED",
        item.evidence_fingerprint,
        item.candidate_set_fingerprint,
        item.decision_compatibility_version,
        ReviewActorKind.USER,
        NOW,
    )
    decision_store.append_decision(rejected, expected_latest_decision_id=accepted.id)
    assert store.find_reusable_decision(candidate) == rejected
    deferred = ReviewDecision(
        EntityId.new(),
        item.id,
        3,
        ReviewDecisionValue.DEFER,
        "MORE_EVIDENCE_REQUIRED",
        item.evidence_fingerprint,
        item.candidate_set_fingerprint,
        item.decision_compatibility_version,
        ReviewActorKind.USER,
        NOW,
    )
    decision_store.append_decision(deferred, expected_latest_decision_id=rejected.id)
    assert store.find_reusable_decision(candidate) is None


def test_migration_0013_upgrade_and_nonempty_downgrade_guard(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    migrate(database, "0013_resolution_review_core")
    legacy = create_sqlite_engine(database)
    assert "relation_candidates" not in inspect(legacy).get_table_names()
    legacy.dispose()

    migrate(database)
    upgraded = create_sqlite_engine(database)
    assert {"relation_candidates", "relation_candidate_evidence"} <= set(
        inspect(upgraded).get_table_names()
    )
    command.downgrade(alembic_config(database), "0013_resolution_review_core")
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0013_resolution_review_core"
        )
    upgraded.dispose()

    migrate(database)
    engine, root, scan, files, fingerprints = _graph(database)
    candidate, links = _candidate(root, scan, files, fingerprints)
    SQLiteRelationCandidateStore(engine).create_or_get(candidate, links)
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(database), "0013_resolution_review_core")
