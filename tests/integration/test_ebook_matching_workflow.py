from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, func, select

from foliotone.authority import (
    resolution_candidate_set_fingerprint,
    resolution_evidence_fingerprint,
)
from foliotone.cli.main import main
from foliotone.core import (
    Edition,
    EntityId,
    EntityKind,
    ExternalIdentifier,
    FileObservation,
    FileRecord,
    Fingerprint,
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
    ScanRun,
    ScanRunStatus,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.persistence import (
    SQLiteResolutionReviewStore,
    create_sqlite_engine,
    migrate,
    repository,
)
from foliotone.persistence import relation_candidate_schema as rc_schema
from foliotone.persistence import resolution_review_schema as rr_schema
from foliotone.workflows import EbookMatchingService

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
MATERIAL = "a" * 64


def _graph(database: Path, count: int = 3):
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-matching-workflow", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    observations = []
    for ordinal in range(count):
        record = FileRecord(
            EntityId.new(),
            root.id,
            f"private-sentinel/book-{ordinal}.epub",
            100 + ordinal,
            NOW,
            MediaType.EBOOK,
            PresenceState.PRESENT,
            NOW,
            NOW,
        )
        observation = FileObservation(
            EntityId.new(),
            record.id,
            scan.id,
            record.relative_path,
            record.size_bytes,
            NOW,
            NOW,
        )
        repository(engine, FileRecord).save(record)
        repository(engine, FileObservation).save(observation)
        observations.append(observation)
    return engine, root, scan, tuple(observations)


def _accept_resolution(
    engine: Engine,
    observation: FileObservation,
    entity_id: EntityId,
    ordinal: int,
) -> None:
    assertion = ValueAssertion(
        EntityId.new(),
        EntityKind.FILE_OBSERVATION,
        observation.id,
        "resolution.edition",
        f"synthetic-{ordinal}",
        ValueState.DERIVED,
        Provenance("synthetic", "matching-workflow-test", NOW, "1"),
    )
    repository(engine, ValueAssertion).save(assertion)
    candidate_id = EntityId.new()
    link = ResolutionEvidenceLink(
        EntityId.new(),
        candidate_id,
        0,
        ResolutionEvidenceKind.VALUE_ASSERTION,
        assertion.id,
        ResolutionEvidenceRole.SUPPORTS,
        EntityKind.EDITION,
        MATERIAL,
    )
    candidate = ResolutionCandidate(
        candidate_id,
        EntityKind.FILE_OBSERVATION,
        observation.id,
        EntityKind.EDITION,
        entity_id,
        "offline-book-resolution",
        "1",
        "authority-decision/v1",
        resolution_evidence_fingerprint((link,)),
        resolution_candidate_set_fingerprint(((EntityKind.EDITION, entity_id),)),
        0.6,
        ResolutionDisposition.REVIEW_REQUIRED,
        NOW,
    )
    store = SQLiteResolutionReviewStore(engine)
    store.create_or_get_candidate(candidate, (link,))
    item = ReviewItem(
        EntityId.new(),
        ReviewType.AUTHORITY_RESOLUTION,
        candidate.subject_kind,
        candidate.subject_id,
        ReviewCandidateKind.RESOLUTION_CANDIDATE,
        candidate.id,
        candidate.resolver_name,
        candidate.resolver_version,
        candidate.decision_compatibility_version,
        candidate.evidence_fingerprint,
        candidate.candidate_set_fingerprint,
        ReviewItemState.PENDING,
        NOW,
    )
    store.enqueue_or_get_review(item)
    store.append_decision(
        ReviewDecision(
            EntityId.new(),
            item.id,
            1,
            ReviewDecisionValue.ACCEPT,
            "SYNTHETIC_ACCEPT",
            item.evidence_fingerprint,
            item.candidate_set_fingerprint,
            item.decision_compatibility_version,
            ReviewActorKind.SYSTEM,
            NOW,
        ),
        expected_latest_decision_id=None,
    )


def _edition_candidates(database: Path):
    engine, root, scan, observations = _graph(database, 2)
    work = Work(EntityId.new())
    editions = (Edition(EntityId.new(), work.id), Edition(EntityId.new(), work.id))
    repository(engine, Work).save(work)
    for ordinal, (edition, observation) in enumerate(zip(editions, observations, strict=True)):
        repository(engine, Edition).save(edition)
        repository(engine, ExternalIdentifier).save(
            ExternalIdentifier(
                EntityId.new(),
                EntityKind.EDITION,
                edition.id,
                "isbn",
                "9780000000001",
                Provenance("synthetic", "matching-workflow-test", NOW, "1"),
            )
        )
        _accept_resolution(engine, observation, edition.id, ordinal)
    return engine, root, scan


def test_exact_duplicate_workflow_is_bounded_idempotent_and_has_no_review(
    tmp_path: Path,
) -> None:
    engine, root, scan, observations = _graph(tmp_path / "exact.db")
    for observation in observations:
        repository(engine, Fingerprint).save(
            Fingerprint(
                EntityId.new(),
                EntityKind.FILE_OBSERVATION,
                observation.id,
                "FILE_SHA256",
                "sha256",
                "1",
                "f" * 64,
                NOW,
            )
        )
    service = EbookMatchingService(engine, clock=lambda: NOW)
    partial = service.run(root.id, scan.id, candidate_limit=1)
    completed = service.run(root.id, scan.id)

    assert partial.candidates_available == 2
    assert partial.candidates_processed == partial.confirmed == 1
    assert partial.truncated
    assert completed.candidates_available == completed.candidates_processed == 2
    assert completed.confirmed == 2
    assert completed.review_queued == 0
    with engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(rc_schema.relation_candidates)
            ).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                select(func.count())
                .select_from(rr_schema.review_items)
                .where(rr_schema.review_items.c.review_type == ReviewType.MATCH_RELATION.value)
            ).scalar_one()
            == 0
        )


def test_bibliographic_workflow_and_review_cli_are_path_free_and_reusable(
    tmp_path: Path,
    capsys,
) -> None:
    database = tmp_path / "edition.db"
    engine, root, scan = _edition_candidates(database)
    engine.dispose()
    match_args = [
        "ebook-match",
        "--scan-root",
        root.name,
        "--scan-run",
        str(scan.id),
        "--database",
        str(database),
        "--output",
        "json",
    ]
    assert main(match_args) == 0
    match_payload = json.loads(capsys.readouterr().out)
    assert match_payload["review_queued"] == 1
    assert match_payload["confirmed"] == 0
    assert "private-sentinel" not in json.dumps(match_payload)

    list_args = [
        "ebook-match-review-list",
        "--database",
        str(database),
        "--output",
        "json",
    ]
    assert main(list_args) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload["items"]) == 1
    item = list_payload["items"][0]
    assert item["latest_decision"] is None
    assert item["relation_type"] == "SAME_EDITION"
    assert item["status"] == "REVIEW_REQUIRED"
    assert item["explanation"] == [
        {
            "code": "EDITION_IDENTIFIER_COMPATIBLE",
            "state": "PRESENT",
            "evidence_count": 2,
        }
    ]
    assert "private-sentinel" not in json.dumps(list_payload)

    decide_args = [
        "ebook-match-review-decide",
        "--database",
        str(database),
        "--review-item",
        item["id"],
        "--decision",
        "accept",
        "--reason-code",
        "MATCH_REVIEWED",
        "--expected-latest-decision",
        "NONE",
        "--output",
        "json",
    ]
    assert main(decide_args) == 0
    decision_payload = json.loads(capsys.readouterr().out)
    assert decision_payload["decision"] == "ACCEPT"
    assert decision_payload["sequence_no"] == 1

    assert main(match_args) == 0
    reuse_payload = json.loads(capsys.readouterr().out)
    assert reuse_payload["decisions_reused"] == 1
    assert reuse_payload["review_queued"] == 0
