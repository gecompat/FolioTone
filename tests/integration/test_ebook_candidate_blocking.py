from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, Table, func, insert, select

from foliotone.analyzers.ebook import TEXT_FINGERPRINT_KIND, TEXT_NORMALIZATION_PROFILE
from foliotone.authority import (
    resolution_candidate_set_fingerprint,
    resolution_evidence_fingerprint,
)
from foliotone.core import (
    Agent,
    AgentType,
    Contribution,
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
    Series,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.matching import (
    CandidateBlockStatus,
    CandidateBlockStrength,
    CandidateBlockType,
    EbookCandidateBlockingError,
    SQLiteEbookCandidateBlockReader,
)
from foliotone.persistence import (
    SQLiteResolutionReviewStore,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
)

NOW = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
COMPATIBILITY = "authority-decision/v1"
MATERIAL = "a" * 64


def _base_graph(
    database: Path,
) -> tuple[Engine, ScanRoot, ScanRun, tuple[FileObservation, ...]]:
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-blocking", MediaType.EBOOK)
    scan = ScanRun(
        EntityId.new(),
        root.id,
        NOW,
        ScanRunStatus.COMPLETED,
        completed_at=NOW,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    observations: list[FileObservation] = []
    for ordinal in range(3):
        file = FileRecord(
            EntityId.new(),
            root.id,
            f"synthetic/book-{ordinal}.epub",
            100 + ordinal,
            NOW,
            MediaType.EBOOK,
            PresenceState.PRESENT,
            NOW,
            NOW,
        )
        observation = FileObservation(
            EntityId.new(),
            file.id,
            scan.id,
            file.relative_path,
            file.size_bytes,
            NOW,
            NOW,
        )
        repository(engine, FileRecord).save(file)
        repository(engine, FileObservation).save(observation)
        observations.append(observation)
    return engine, root, scan, tuple(observations)


def _add_fingerprints(engine: Engine, observations: tuple[FileObservation, ...]) -> None:
    for ordinal, observation in enumerate(observations):
        repository(engine, Fingerprint).save(
            Fingerprint(
                EntityId.new(),
                EntityKind.FILE_OBSERVATION,
                observation.id,
                "FILE_SHA256",
                "sha256",
                "1",
                "1" * 64 if ordinal < 2 else "2" * 64,
                NOW,
            )
        )
        repository(engine, Fingerprint).save(
            Fingerprint(
                EntityId.new(),
                EntityKind.FILE_OBSERVATION,
                observation.id,
                TEXT_FINGERPRINT_KIND,
                "sha256",
                TEXT_NORMALIZATION_PROFILE,
                "3" * 64,
                NOW,
            )
        )


def _accept_resolution(
    engine: Engine,
    observation: FileObservation,
    kind: EntityKind,
    entity_id: EntityId,
    ordinal: int,
) -> None:
    assertion = ValueAssertion(
        EntityId.new(),
        EntityKind.FILE_OBSERVATION,
        observation.id,
        f"resolution.{kind.value.lower()}",
        f"synthetic-{ordinal}",
        ValueState.DERIVED,
        Provenance("synthetic", "blocking-test", NOW, "1"),
        confidence=0.5,
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
        kind,
        MATERIAL,
    )
    candidate = ResolutionCandidate(
        candidate_id,
        EntityKind.FILE_OBSERVATION,
        observation.id,
        kind,
        entity_id,
        "offline-book-resolution",
        "1",
        COMPATIBILITY,
        resolution_evidence_fingerprint((link,)),
        resolution_candidate_set_fingerprint(((kind, entity_id),)),
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
            ReviewActorKind.USER,
            NOW,
        ),
        expected_latest_decision_id=None,
    )


def test_all_book_block_sources_are_bounded_and_path_free(tmp_path: Path) -> None:
    database = tmp_path / "blocking.db"
    engine, root, scan, observations = _base_graph(database)
    _add_fingerprints(engine, observations)
    work = Work(EntityId.new())
    first_edition = Edition(EntityId.new(), work.id)
    second_edition = Edition(EntityId.new(), work.id)
    series = Series(EntityId.new())
    agent = Agent(EntityId.new(), AgentType.PERSON)
    for entity in (work, first_edition, second_edition, series, agent):
        repository(engine, type(entity)).save(entity)
    repository(engine, Contribution).save(
        Contribution(
            EntityId.new(),
            agent.id,
            EntityKind.WORK,
            work.id,
            "author",
            Provenance("synthetic", "blocking-test", NOW, "1"),
        )
    )
    repository(engine, ValueAssertion).save(
        ValueAssertion(
            EntityId.new(),
            EntityKind.WORK,
            work.id,
            "work.title.normalized",
            "synthetic title",
            ValueState.DERIVED,
            Provenance("synthetic", "blocking-test", NOW, "1"),
        )
    )
    for edition in (first_edition, second_edition):
        repository(engine, ExternalIdentifier).save(
            ExternalIdentifier(
                EntityId.new(),
                EntityKind.EDITION,
                edition.id,
                "isbn",
                "9780000000001",
                Provenance("synthetic", "blocking-test", NOW, "1"),
            )
        )
    for ordinal, observation in enumerate(observations):
        _accept_resolution(engine, observation, EntityKind.WORK, work.id, ordinal)
        _accept_resolution(
            engine,
            observation,
            EntityKind.EDITION,
            first_edition.id if ordinal < 2 else second_edition.id,
            ordinal,
        )
        _accept_resolution(engine, observation, EntityKind.SERIES, series.id, ordinal)

    before_relations = _count(engine, schema.relations)
    snapshot = SQLiteEbookCandidateBlockReader(engine).snapshot(
        root.id,
        scan.id,
        block_limit=20,
        member_limit=2,
        pairwise_limit=2,
    )
    blocks = {block.block_type: block for block in snapshot.blocks}
    assert set(blocks) == set(CandidateBlockType)
    assert blocks[CandidateBlockType.FILE_SHA256].status is CandidateBlockStatus.EXACT_GROUP
    assert not blocks[CandidateBlockType.FILE_SHA256].is_pairwise_expandable
    assert blocks[CandidateBlockType.RESOLVED_EDITION].status is CandidateBlockStatus.READY
    for block_type in (
        CandidateBlockType.EDITION_IDENTIFIER,
        CandidateBlockType.RESOLVED_WORK,
        CandidateBlockType.AGENT_TITLE,
        CandidateBlockType.TEXT_FINGERPRINT,
        CandidateBlockType.SERIES_CONTEXT,
    ):
        assert blocks[block_type].status is CandidateBlockStatus.SECONDARY_REQUIRED
        assert blocks[block_type].member_count == 3
        assert blocks[block_type].members_truncated
        assert not blocks[block_type].is_pairwise_expandable
    assert blocks[CandidateBlockType.SERIES_CONTEXT].strength is (
        CandidateBlockStrength.SUPPORTING_ONLY
    )
    rendered = repr(snapshot)
    assert "synthetic title" not in rendered
    assert "book-0.epub" not in rendered
    assert "9780000000001" not in rendered
    assert _count(engine, schema.relations) == before_relations


def test_latest_completed_scan_is_required(tmp_path: Path) -> None:
    database = tmp_path / "lineage.db"
    engine, root, scan, _ = _base_graph(database)
    newer = ScanRun(
        EntityId.new(),
        root.id,
        NOW.replace(minute=1),
        ScanRunStatus.COMPLETED,
        completed_at=NOW.replace(minute=1),
    )
    repository(engine, ScanRun).save(newer)
    with pytest.raises(EbookCandidateBlockingError, match="latest"):
        SQLiteEbookCandidateBlockReader(engine).snapshot(root.id, scan.id)


def test_later_failed_scan_does_not_replace_latest_completed_scan(tmp_path: Path) -> None:
    database = tmp_path / "failed-lineage.db"
    engine, root, scan, _ = _base_graph(database)
    failed = ScanRun(
        EntityId.new(),
        root.id,
        NOW.replace(minute=1),
        ScanRunStatus.FAILED,
        completed_at=NOW.replace(minute=1),
    )
    repository(engine, ScanRun).save(failed)

    snapshot = SQLiteEbookCandidateBlockReader(engine).snapshot(root.id, scan.id)

    assert snapshot.scan_run_id == scan.id
    assert snapshot.blocks == ()


def test_thousand_exact_duplicates_use_one_bounded_group(tmp_path: Path) -> None:
    database = tmp_path / "scale.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-scale", MediaType.EBOOK)
    scan = ScanRun(
        EntityId.new(),
        root.id,
        NOW,
        ScanRunStatus.COMPLETED,
        completed_at=NOW,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    files: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    fingerprints: list[dict[str, object]] = []
    for ordinal in range(1000):
        file_id = EntityId.new()
        observation_id = EntityId.new()
        relative_path = f"synthetic/scale-{ordinal:04d}.epub"
        files.append(
            {
                "id": str(file_id),
                "scan_root_id": str(root.id),
                "relative_path": relative_path,
                "size_bytes": 100,
                "modified_at": NOW.isoformat(),
                "media_type": MediaType.EBOOK.value,
                "presence_state": PresenceState.PRESENT.value,
                "first_seen_at": NOW.isoformat(),
                "last_seen_at": NOW.isoformat(),
                "missing_since_at": None,
                "consecutive_missing_scans": 0,
            }
        )
        observations.append(
            {
                "id": str(observation_id),
                "file_id": str(file_id),
                "scan_run_id": str(scan.id),
                "relative_path": relative_path,
                "size_bytes": 100,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            }
        )
        fingerprints.append(
            {
                "id": str(EntityId.new()),
                "target_kind": EntityKind.FILE_OBSERVATION.value,
                "target_id": str(observation_id),
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": "f" * 64,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            }
        )
    with engine.begin() as connection:
        connection.execute(insert(schema.file_records), files)
        connection.execute(insert(schema.file_observations), observations)
        connection.execute(insert(schema.fingerprints), fingerprints)
    snapshot = SQLiteEbookCandidateBlockReader(engine).snapshot(
        root.id,
        scan.id,
        block_types=(CandidateBlockType.FILE_SHA256,),
        block_limit=1,
        member_limit=4,
        pairwise_limit=4,
    )
    assert len(snapshot.blocks) == 1
    block = snapshot.blocks[0]
    assert block.member_count == 1000
    assert len(block.members) == 4
    assert block.members_truncated
    assert block.status is CandidateBlockStatus.EXACT_GROUP
    assert not block.is_pairwise_expandable


def _count(engine: Engine, table: Table) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())
