from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from foliotone.core import (
    Agent,
    AgentName,
    AgentNameType,
    AgentType,
    CatalogDesignation,
    ClassificationAssertion,
    Contribution,
    Edition,
    EntityId,
    EntityKind,
    Evidence,
    ExternalIdentifier,
    FileObservation,
    FileRecord,
    Fingerprint,
    MatchStatus,
    MediaType,
    MusicWork,
    MusicWorkRelation,
    MusicWorkRelationType,
    PresenceState,
    Provenance,
    Recording,
    Relation,
    RelationType,
    Release,
    ReleaseGroup,
    ReleaseRecording,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
    Series,
    SeriesMembership,
    ToolCapability,
    ToolExecutionStatus,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.persistence.schema import ALL_TABLES
from foliotone.persistence.w2_schema import (
    file_relocation_candidates,
    file_scan_events,
    tool_artifacts,
)
from foliotone.tooling import ToolExecution, ToolResult

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=1)


def provenance() -> Provenance:
    return Provenance(
        source_kind="test",
        source_name="synthetic",
        source_version="1",
        observed_at=NOW,
    )


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "foliotone.db"
    migrate(path)
    return path


def test_migration_creates_current_schema_and_is_idempotent(database: Path) -> None:
    migrate(database)
    engine = create_sqlite_engine(database)
    table_names = set(inspect(engine).get_table_names())
    expected = {table.name for table in ALL_TABLES} | {
        "alembic_version",
        file_scan_events.name,
        file_relocation_candidates.name,
        tool_artifacts.name,
    }
    assert table_names == expected
    file_columns = {column["name"] for column in inspect(engine).get_columns("file_records")}
    assert {"missing_since_at", "consecutive_missing_scans"} <= file_columns

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "0004_relocation_candidates"


def test_migration_upgrades_0002_absence_state_conservatively(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    migrate(path, "0002_incremental_index")
    engine = create_sqlite_engine(path)
    root_id = "00000000-0000-0000-0000-000000000001"
    file_id = "00000000-0000-0000-0000-000000000002"
    timestamp = NOW.isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id, name, media_type, enabled) "
                "VALUES (:id, :name, :media_type, :enabled)"
            ),
            {"id": root_id, "name": "legacy", "media_type": "EBOOK", "enabled": True},
        )
        connection.execute(
            text(
                "INSERT INTO file_records "
                "(id, scan_root_id, relative_path, size_bytes, modified_at, media_type, "
                "presence_state, first_seen_at, last_seen_at) "
                "VALUES (:id, :root, :path, :size, :modified, :media_type, :presence, "
                ":first_seen, :last_seen)"
            ),
            {
                "id": file_id,
                "root": root_id,
                "path": "legacy.epub",
                "size": 1,
                "modified": timestamp,
                "media_type": "EBOOK",
                "presence": "MISSING",
                "first_seen": timestamp,
                "last_seen": timestamp,
            },
        )
    engine.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    with upgraded.connect() as connection:
        row = connection.execute(
            text(
                "SELECT missing_since_at, consecutive_missing_scans "
                "FROM file_records WHERE id = :id"
            ),
            {"id": file_id},
        ).mappings().one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert row["missing_since_at"] is None
    assert row["consecutive_missing_scans"] == 0
    assert revision == "0004_relocation_candidates"


def test_round_trip_complete_w1_graph(database: Path) -> None:
    engine = create_sqlite_engine(database)

    root = ScanRoot(id=EntityId.new(), name="ebooks", media_type=MediaType.EBOOK)
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=LATER,
        status=ScanRunStatus.COMPLETED,
    )
    file_a = FileRecord(
        id=EntityId.new(),
        scan_root_id=root.id,
        relative_path="Author/Book.epub",
        size_bytes=100,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    file_b = FileRecord(
        id=EntityId.new(),
        scan_root_id=root.id,
        relative_path="Incoming/Book.epub",
        size_bytes=100,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    observation = FileObservation(
        id=EntityId.new(),
        file_id=file_a.id,
        scan_run_id=scan.id,
        relative_path=file_a.relative_path,
        size_bytes=file_a.size_bytes,
        modified_at=file_a.modified_at,
        observed_at=NOW,
    )

    agent = Agent(id=EntityId.new(), agent_type=AgentType.PERSON)
    agent_name = AgentName(
        id=EntityId.new(),
        agent_id=agent.id,
        name_type=AgentNameType.CREDITED_AS,
        value="Asimov, Isaac",
        normalized_value="isaac asimov",
        provenance=provenance(),
    )
    work = Work(id=EntityId.new(), canonical_title="Synthetic Work")
    edition = Edition(
        id=EntityId.new(),
        work_id=work.id,
        canonical_title="Synthetic Edition",
        language="en",
    )
    series = Series(id=EntityId.new(), canonical_name="Synthetic Series")
    membership = SeriesMembership(
        id=EntityId.new(),
        series_id=series.id,
        target_kind=EntityKind.WORK,
        target_id=work.id,
        position="1.5",
    )
    identifier = ExternalIdentifier(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        namespace="example",
        value="work-1",
        provenance=provenance(),
    )
    contribution = Contribution(
        id=EntityId.new(),
        agent_id=agent.id,
        target_kind=EntityKind.WORK,
        target_id=work.id,
        role="AUTHOR",
        credited_as="I. Asimov",
        provenance=provenance(),
    )
    assertion = ValueAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        field_name="title",
        value="Synthetic Work",
        state=ValueState.CANONICAL,
        provenance=provenance(),
        confidence=0.99,
    )

    parent_work = MusicWork(id=EntityId.new(), canonical_title="Synthetic Symphony")
    child_work = MusicWork(id=EntityId.new(), canonical_title="Movement I")
    work_relation = MusicWorkRelation(
        id=EntityId.new(),
        source_work_id=child_work.id,
        target_work_id=parent_work.id,
        relation_type=MusicWorkRelationType.PART_OF,
    )
    catalog = CatalogDesignation(
        id=EntityId.new(),
        music_work_id=parent_work.id,
        system="TEST",
        value="1",
    )
    recording = Recording(
        id=EntityId.new(),
        canonical_title="Synthetic Recording",
        duration_ms=123000,
    )
    release_group = ReleaseGroup(id=EntityId.new(), canonical_title="Synthetic Album")
    release = Release(
        id=EntityId.new(),
        release_group_id=release_group.id,
        canonical_title="Synthetic Album",
        release_date="2026",
    )
    release_recording = ReleaseRecording(
        id=EntityId.new(),
        release_id=release.id,
        recording_id=recording.id,
        disc_number=1,
        track_number=1,
        observed_title="Synthetic Track",
    )

    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="ffprobe",
        tool_version="8.0",
        adapter_version="1",
        capability=ToolCapability.TECHNICAL_METADATA,
        input_identity=f"file:{file_a.id}",
        config_identity="default-v1",
        started_at=NOW,
        finished_at=LATER,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    tool_result = ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type="technical_metadata",
        target_kind=EntityKind.FILE,
        target_id=file_a.id,
        key="codec_name",
        value="epub",
        confidence=1.0,
    )
    classification = ClassificationAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        dimension="genre",
        value="science fiction",
        taxonomy="synthetic",
        confidence=0.8,
        provenance=provenance(),
    )
    fingerprint = Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE,
        target_id=file_a.id,
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="1",
        value="0" * 64,
        created_at=NOW,
        tool_execution_id=execution.id,
    )
    relation = Relation(
        id=EntityId.new(),
        left_kind=EntityKind.FILE,
        left_id=file_a.id,
        right_kind=EntityKind.FILE,
        right_id=file_b.id,
        relation_type=RelationType.EXACT_DUPLICATE,
        confidence=1.0,
        status=MatchStatus.CONFIRMED,
        created_at=NOW,
    )
    evidence = Evidence(
        id=EntityId.new(),
        relation_id=relation.id,
        evidence_type="sha256",
        summary="Synthetic hashes match",
        strength=1.0,
        tool_execution_id=execution.id,
        provenance=provenance(),
    )

    values = [
        root,
        scan,
        file_a,
        file_b,
        observation,
        agent,
        agent_name,
        work,
        edition,
        series,
        membership,
        identifier,
        contribution,
        assertion,
        parent_work,
        child_work,
        work_relation,
        catalog,
        recording,
        release_group,
        release,
        release_recording,
        execution,
        tool_result,
        classification,
        fingerprint,
        relation,
        evidence,
    ]

    for value in values:
        repo = repository(engine, type(value))
        repo.save(value)
        assert repo.get(value.id) == value


def test_save_updates_existing_immutable_record(database: Path) -> None:
    engine = create_sqlite_engine(database)
    work_id = EntityId.new()
    repo = repository(engine, Work)
    repo.save(Work(id=work_id, canonical_title="Old"))
    repo.save(Work(id=work_id, canonical_title="New"))
    assert repo.get(work_id) == Work(id=work_id, canonical_title="New")


def test_foreign_keys_are_enforced(database: Path) -> None:
    engine = create_sqlite_engine(database)
    edition = Edition(
        id=EntityId.new(),
        work_id=EntityId.new(),
        canonical_title="Orphan",
    )
    with pytest.raises(IntegrityError):
        repository(engine, Edition).save(edition)


def test_unique_file_root_path_constraint(database: Path) -> None:
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name="ebooks", media_type=MediaType.EBOOK)
    repository(engine, ScanRoot).save(root)
    common = dict(
        scan_root_id=root.id,
        relative_path="same/book.epub",
        size_bytes=1,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    repository(engine, FileRecord).save(FileRecord(id=EntityId.new(), **common))
    with pytest.raises(IntegrityError):
        repository(engine, FileRecord).save(FileRecord(id=EntityId.new(), **common))


def test_list_all_is_deterministic(database: Path) -> None:
    engine = create_sqlite_engine(database)
    repo = repository(engine, Work)
    items = [
        Work(id=EntityId.parse("00000000-0000-0000-0000-000000000002"), canonical_title="B"),
        Work(id=EntityId.parse("00000000-0000-0000-0000-000000000001"), canonical_title="A"),
    ]
    for item in items:
        repo.save(item)
    assert [str(item.id) for item in repo.list_all()] == sorted(str(item.id) for item in items)
