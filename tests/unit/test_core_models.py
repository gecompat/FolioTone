from datetime import datetime, timezone

import pytest

from foliotone.core import (
    Agent,
    AgentName,
    AgentNameType,
    AgentType,
    EntityId,
    EntityKind,
    FileRecord,
    MatchStatus,
    MediaType,
    MusicWorkRelation,
    MusicWorkRelationType,
    PresenceState,
    Provenance,
    Relation,
    RelationType,
    ReleaseRecording,
    ScanRun,
    ScanRunStatus,
    SeriesMembership,
    ValueAssertion,
    ValueState,
)

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=timezone.utc)


def provenance() -> Provenance:
    return Provenance(source_kind="test", source_name="synthetic", observed_at=NOW)


def test_entity_id_round_trip() -> None:
    entity_id = EntityId.new()
    assert EntityId.parse(str(entity_id)) == entity_id


def test_file_record_normalizes_relative_path() -> None:
    record = FileRecord(
        id=EntityId.new(),
        scan_root_id=EntityId.new(),
        relative_path=r"Author\Book.epub",
        size_bytes=42,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    assert record.relative_path == "Author/Book.epub"


def test_file_record_rejects_absolute_or_parent_path() -> None:
    common = dict(
        id=EntityId.new(),
        scan_root_id=EntityId.new(),
        size_bytes=42,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    with pytest.raises(ValueError):
        FileRecord(relative_path="/private/book.epub", **common)
    with pytest.raises(ValueError):
        FileRecord(relative_path="../book.epub", **common)


def test_finished_scan_requires_completion_timestamp() -> None:
    with pytest.raises(ValueError):
        ScanRun(
            id=EntityId.new(),
            scan_root_id=EntityId.new(),
            started_at=NOW,
            status=ScanRunStatus.COMPLETED,
        )


def test_assertion_preserves_observed_and_normalized_values_separately() -> None:
    agent = Agent(id=EntityId.new(), agent_type=AgentType.PERSON)
    name = AgentName(
        id=EntityId.new(),
        agent_id=agent.id,
        name_type=AgentNameType.CREDITED_AS,
        value="Asimov, Isaac",
        normalized_value="isaac asimov",
        provenance=provenance(),
    )
    assertion = ValueAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.AGENT,
        target_id=agent.id,
        field_name="display_name",
        value="Isaac Asimov",
        state=ValueState.CANONICAL,
        provenance=provenance(),
        confidence=0.99,
    )
    assert name.value == "Asimov, Isaac"
    assert name.normalized_value == "isaac asimov"
    assert assertion.value == "Isaac Asimov"


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValueError):
        ValueAssertion(
            id=EntityId.new(),
            target_kind=EntityKind.WORK,
            target_id=EntityId.new(),
            field_name="title",
            value="Synthetic Book",
            state=ValueState.DERIVED,
            provenance=provenance(),
            confidence=1.1,
        )


def test_music_work_relation_rejects_self_reference() -> None:
    work_id = EntityId.new()
    with pytest.raises(ValueError):
        MusicWorkRelation(
            id=EntityId.new(),
            source_work_id=work_id,
            target_work_id=work_id,
            relation_type=MusicWorkRelationType.PART_OF,
        )


def test_release_recording_requires_positive_positions() -> None:
    with pytest.raises(ValueError):
        ReleaseRecording(
            id=EntityId.new(),
            release_id=EntityId.new(),
            recording_id=EntityId.new(),
            track_number=0,
        )


def test_series_membership_has_explicit_identity_level() -> None:
    membership = SeriesMembership(
        id=EntityId.new(),
        series_id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=EntityId.new(),
        position="1.5",
    )
    assert membership.target_kind is EntityKind.WORK
    assert membership.position == "1.5"


def test_relation_cannot_connect_entity_to_itself() -> None:
    entity_id = EntityId.new()
    with pytest.raises(ValueError):
        Relation(
            id=EntityId.new(),
            left_kind=EntityKind.FILE,
            left_id=entity_id,
            right_kind=EntityKind.FILE,
            right_id=entity_id,
            relation_type=RelationType.EXACT_DUPLICATE,
            confidence=1.0,
            status=MatchStatus.CONFIRMED,
            created_at=NOW,
        )
