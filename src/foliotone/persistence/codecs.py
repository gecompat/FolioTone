"""Explicit domain-to-row codecs for the W1 persistence schema."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Table

from foliotone.core import (
    Agent,
    AgentName,
    AgentNameType,
    AgentType,
    CatalogDesignation,
    ClassificationAssertion,
    Contribution,
    Edition,
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
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.core.ids import EntityId
from foliotone.persistence import schema
from foliotone.persistence._mapping import (
    datetime_to_db,
    id_to_db,
    provenance_from_row,
    provenance_to_row,
    required_datetime_from_db,
    required_id_from_db,
)
from foliotone.tooling import ToolExecution, ToolResult
from foliotone.core.enums import ToolCapability, ToolExecutionStatus

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Codec(Generic[T]):
    """Maps one immutable domain type to one SQL table."""

    table: Table
    encode: Callable[[T], Mapping[str, object]]
    decode: Callable[[Mapping[str, Any]], T]


def _text(row: Mapping[str, Any], name: str) -> str:
    return str(row[name])


def _optional_text(row: Mapping[str, Any], name: str) -> str | None:
    value = row[name]
    return None if value is None else str(value)


def _optional_int(row: Mapping[str, Any], name: str) -> int | None:
    value = row[name]
    return None if value is None else int(value)


def _optional_float(row: Mapping[str, Any], name: str) -> float | None:
    value = row[name]
    return None if value is None else float(value)


def encode_scan_root(value: ScanRoot) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "name": value.name,
        "media_type": value.media_type.value,
        "enabled": value.enabled,
    }


def decode_scan_root(row: Mapping[str, Any]) -> ScanRoot:
    return ScanRoot(
        id=required_id_from_db(_text(row, "id")),
        name=_text(row, "name"),
        media_type=MediaType(_text(row, "media_type")),
        enabled=bool(row["enabled"]),
    )


def encode_scan_run(value: ScanRun) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "scan_root_id": str(value.scan_root_id),
        "started_at": datetime_to_db(value.started_at),
        "status": value.status.value,
        "completed_at": datetime_to_db(value.completed_at),
    }


def decode_scan_run(row: Mapping[str, Any]) -> ScanRun:
    completed = _optional_text(row, "completed_at")
    return ScanRun(
        id=required_id_from_db(_text(row, "id")),
        scan_root_id=required_id_from_db(_text(row, "scan_root_id")),
        started_at=required_datetime_from_db(_text(row, "started_at")),
        status=ScanRunStatus(_text(row, "status")),
        completed_at=None if completed is None else required_datetime_from_db(completed),
    )


def encode_file_record(value: FileRecord) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "scan_root_id": str(value.scan_root_id),
        "relative_path": value.relative_path,
        "size_bytes": value.size_bytes,
        "modified_at": datetime_to_db(value.modified_at),
        "media_type": value.media_type.value,
        "presence_state": value.presence_state.value,
        "first_seen_at": datetime_to_db(value.first_seen_at),
        "last_seen_at": datetime_to_db(value.last_seen_at),
    }


def decode_file_record(row: Mapping[str, Any]) -> FileRecord:
    return FileRecord(
        id=required_id_from_db(_text(row, "id")),
        scan_root_id=required_id_from_db(_text(row, "scan_root_id")),
        relative_path=_text(row, "relative_path"),
        size_bytes=int(row["size_bytes"]),
        modified_at=required_datetime_from_db(_text(row, "modified_at")),
        media_type=MediaType(_text(row, "media_type")),
        presence_state=PresenceState(_text(row, "presence_state")),
        first_seen_at=required_datetime_from_db(_text(row, "first_seen_at")),
        last_seen_at=required_datetime_from_db(_text(row, "last_seen_at")),
    )


def encode_file_observation(value: FileObservation) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "file_id": str(value.file_id),
        "scan_run_id": str(value.scan_run_id),
        "relative_path": value.relative_path,
        "size_bytes": value.size_bytes,
        "modified_at": datetime_to_db(value.modified_at),
        "observed_at": datetime_to_db(value.observed_at),
    }


def decode_file_observation(row: Mapping[str, Any]) -> FileObservation:
    return FileObservation(
        id=required_id_from_db(_text(row, "id")),
        file_id=required_id_from_db(_text(row, "file_id")),
        scan_run_id=required_id_from_db(_text(row, "scan_run_id")),
        relative_path=_text(row, "relative_path"),
        size_bytes=int(row["size_bytes"]),
        modified_at=required_datetime_from_db(_text(row, "modified_at")),
        observed_at=required_datetime_from_db(_text(row, "observed_at")),
    )


def encode_value_assertion(value: ValueAssertion) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "field_name": value.field_name,
        "value": value.value,
        "state": value.state.value,
        "confidence": value.confidence,
        "explanation": value.explanation,
        **provenance_to_row(value.provenance),
    }


def decode_value_assertion(row: Mapping[str, Any]) -> ValueAssertion:
    return ValueAssertion(
        id=required_id_from_db(_text(row, "id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        field_name=_text(row, "field_name"),
        value=_text(row, "value"),
        state=ValueState(_text(row, "state")),
        provenance=provenance_from_row(row),
        confidence=_optional_float(row, "confidence"),
        explanation=_optional_text(row, "explanation"),
    )


def encode_agent(value: Agent) -> Mapping[str, object]:
    return {"id": str(value.id), "agent_type": value.agent_type.value}


def decode_agent(row: Mapping[str, Any]) -> Agent:
    return Agent(
        id=required_id_from_db(_text(row, "id")),
        agent_type=AgentType(_text(row, "agent_type")),
    )


def encode_agent_name(value: AgentName) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "agent_id": str(value.agent_id),
        "name_type": value.name_type.value,
        "value": value.value,
        "normalized_value": value.normalized_value,
        "language": value.language,
        "script": value.script,
        **provenance_to_row(value.provenance),
    }


def decode_agent_name(row: Mapping[str, Any]) -> AgentName:
    return AgentName(
        id=required_id_from_db(_text(row, "id")),
        agent_id=required_id_from_db(_text(row, "agent_id")),
        name_type=AgentNameType(_text(row, "name_type")),
        value=_text(row, "value"),
        provenance=provenance_from_row(row),
        normalized_value=_optional_text(row, "normalized_value"),
        language=_optional_text(row, "language"),
        script=_optional_text(row, "script"),
    )


def encode_external_identifier(value: ExternalIdentifier) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "namespace": value.namespace,
        "value": value.value,
        **provenance_to_row(value.provenance),
    }


def decode_external_identifier(row: Mapping[str, Any]) -> ExternalIdentifier:
    return ExternalIdentifier(
        id=required_id_from_db(_text(row, "id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        namespace=_text(row, "namespace"),
        value=_text(row, "value"),
        provenance=provenance_from_row(row),
    )


def encode_contribution(value: Contribution) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "agent_id": str(value.agent_id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "role": value.role,
        "credited_as": value.credited_as,
        **provenance_to_row(value.provenance),
    }


def decode_contribution(row: Mapping[str, Any]) -> Contribution:
    return Contribution(
        id=required_id_from_db(_text(row, "id")),
        agent_id=required_id_from_db(_text(row, "agent_id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        role=_text(row, "role"),
        credited_as=_optional_text(row, "credited_as"),
        provenance=provenance_from_row(row),
    )


def encode_work(value: Work) -> Mapping[str, object]:
    return {"id": str(value.id), "canonical_title": value.canonical_title}


def decode_work(row: Mapping[str, Any]) -> Work:
    return Work(
        id=required_id_from_db(_text(row, "id")),
        canonical_title=_optional_text(row, "canonical_title"),
    )


def encode_edition(value: Edition) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "work_id": str(value.work_id),
        "canonical_title": value.canonical_title,
        "language": value.language,
    }


def decode_edition(row: Mapping[str, Any]) -> Edition:
    return Edition(
        id=required_id_from_db(_text(row, "id")),
        work_id=required_id_from_db(_text(row, "work_id")),
        canonical_title=_optional_text(row, "canonical_title"),
        language=_optional_text(row, "language"),
    )


def encode_series(value: Series) -> Mapping[str, object]:
    return {"id": str(value.id), "canonical_name": value.canonical_name}


def decode_series(row: Mapping[str, Any]) -> Series:
    return Series(
        id=required_id_from_db(_text(row, "id")),
        canonical_name=_optional_text(row, "canonical_name"),
    )


def encode_series_membership(value: SeriesMembership) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "series_id": str(value.series_id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "position": value.position,
    }


def decode_series_membership(row: Mapping[str, Any]) -> SeriesMembership:
    return SeriesMembership(
        id=required_id_from_db(_text(row, "id")),
        series_id=required_id_from_db(_text(row, "series_id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        position=_optional_text(row, "position"),
    )


def encode_music_work(value: MusicWork) -> Mapping[str, object]:
    return {"id": str(value.id), "canonical_title": value.canonical_title}


def decode_music_work(row: Mapping[str, Any]) -> MusicWork:
    return MusicWork(
        id=required_id_from_db(_text(row, "id")),
        canonical_title=_optional_text(row, "canonical_title"),
    )


def encode_music_work_relation(value: MusicWorkRelation) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "source_work_id": str(value.source_work_id),
        "target_work_id": str(value.target_work_id),
        "relation_type": value.relation_type.value,
    }


def decode_music_work_relation(row: Mapping[str, Any]) -> MusicWorkRelation:
    return MusicWorkRelation(
        id=required_id_from_db(_text(row, "id")),
        source_work_id=required_id_from_db(_text(row, "source_work_id")),
        target_work_id=required_id_from_db(_text(row, "target_work_id")),
        relation_type=MusicWorkRelationType(_text(row, "relation_type")),
    )


def encode_catalog_designation(value: CatalogDesignation) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "music_work_id": str(value.music_work_id),
        "system": value.system,
        "value": value.value,
    }


def decode_catalog_designation(row: Mapping[str, Any]) -> CatalogDesignation:
    return CatalogDesignation(
        id=required_id_from_db(_text(row, "id")),
        music_work_id=required_id_from_db(_text(row, "music_work_id")),
        system=_text(row, "system"),
        value=_text(row, "value"),
    )


def encode_recording(value: Recording) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "canonical_title": value.canonical_title,
        "duration_ms": value.duration_ms,
    }


def decode_recording(row: Mapping[str, Any]) -> Recording:
    return Recording(
        id=required_id_from_db(_text(row, "id")),
        canonical_title=_optional_text(row, "canonical_title"),
        duration_ms=_optional_int(row, "duration_ms"),
    )


def encode_release_group(value: ReleaseGroup) -> Mapping[str, object]:
    return {"id": str(value.id), "canonical_title": value.canonical_title}


def decode_release_group(row: Mapping[str, Any]) -> ReleaseGroup:
    return ReleaseGroup(
        id=required_id_from_db(_text(row, "id")),
        canonical_title=_optional_text(row, "canonical_title"),
    )


def encode_release(value: Release) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "release_group_id": id_to_db(value.release_group_id),
        "canonical_title": value.canonical_title,
        "release_date": value.release_date,
    }


def decode_release(row: Mapping[str, Any]) -> Release:
    release_group = _optional_text(row, "release_group_id")
    return Release(
        id=required_id_from_db(_text(row, "id")),
        release_group_id=None if release_group is None else required_id_from_db(release_group),
        canonical_title=_optional_text(row, "canonical_title"),
        release_date=_optional_text(row, "release_date"),
    )


def encode_release_recording(value: ReleaseRecording) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "release_id": str(value.release_id),
        "recording_id": str(value.recording_id),
        "disc_number": value.disc_number,
        "track_number": value.track_number,
        "observed_title": value.observed_title,
    }


def decode_release_recording(row: Mapping[str, Any]) -> ReleaseRecording:
    return ReleaseRecording(
        id=required_id_from_db(_text(row, "id")),
        release_id=required_id_from_db(_text(row, "release_id")),
        recording_id=required_id_from_db(_text(row, "recording_id")),
        disc_number=_optional_int(row, "disc_number"),
        track_number=_optional_int(row, "track_number"),
        observed_title=_optional_text(row, "observed_title"),
    )


def encode_classification(value: ClassificationAssertion) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "dimension": value.dimension,
        "value": value.value,
        "taxonomy": value.taxonomy,
        "confidence": value.confidence,
        **provenance_to_row(value.provenance),
    }


def decode_classification(row: Mapping[str, Any]) -> ClassificationAssertion:
    return ClassificationAssertion(
        id=required_id_from_db(_text(row, "id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        dimension=_text(row, "dimension"),
        value=_text(row, "value"),
        provenance=provenance_from_row(row),
        taxonomy=_optional_text(row, "taxonomy"),
        confidence=_optional_float(row, "confidence"),
    )


def encode_fingerprint(value: Fingerprint) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "kind": value.kind,
        "algorithm": value.algorithm,
        "algorithm_version": value.algorithm_version,
        "value": value.value,
        "created_at": datetime_to_db(value.created_at),
        "tool_execution_id": id_to_db(value.tool_execution_id),
    }


def decode_fingerprint(row: Mapping[str, Any]) -> Fingerprint:
    execution = _optional_text(row, "tool_execution_id")
    return Fingerprint(
        id=required_id_from_db(_text(row, "id")),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        kind=_text(row, "kind"),
        algorithm=_text(row, "algorithm"),
        algorithm_version=_text(row, "algorithm_version"),
        value=_text(row, "value"),
        created_at=required_datetime_from_db(_text(row, "created_at")),
        tool_execution_id=None if execution is None else required_id_from_db(execution),
    )


def encode_tool_execution(value: ToolExecution) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "provider_id": value.provider_id,
        "tool_version": value.tool_version,
        "adapter_version": value.adapter_version,
        "capability": value.capability.value,
        "input_identity": value.input_identity,
        "config_identity": value.config_identity,
        "started_at": datetime_to_db(value.started_at),
        "finished_at": datetime_to_db(value.finished_at),
        "status": value.status.value,
        "exit_code": value.exit_code,
        "error_summary": value.error_summary,
    }


def decode_tool_execution(row: Mapping[str, Any]) -> ToolExecution:
    finished = _optional_text(row, "finished_at")
    return ToolExecution(
        id=required_id_from_db(_text(row, "id")),
        provider_id=_text(row, "provider_id"),
        tool_version=_text(row, "tool_version"),
        adapter_version=_text(row, "adapter_version"),
        capability=ToolCapability(_text(row, "capability")),
        input_identity=_text(row, "input_identity"),
        config_identity=_optional_text(row, "config_identity"),
        started_at=required_datetime_from_db(_text(row, "started_at")),
        finished_at=None if finished is None else required_datetime_from_db(finished),
        status=ToolExecutionStatus(_text(row, "status")),
        exit_code=_optional_int(row, "exit_code"),
        error_summary=_optional_text(row, "error_summary"),
    )


def encode_tool_result(value: ToolResult) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "execution_id": str(value.execution_id),
        "result_type": value.result_type,
        "target_kind": value.target_kind.value,
        "target_id": str(value.target_id),
        "key": value.key,
        "value": value.value,
        "confidence": value.confidence,
        "explanation": value.explanation,
    }


def decode_tool_result(row: Mapping[str, Any]) -> ToolResult:
    return ToolResult(
        id=required_id_from_db(_text(row, "id")),
        execution_id=required_id_from_db(_text(row, "execution_id")),
        result_type=_text(row, "result_type"),
        target_kind=EntityKind(_text(row, "target_kind")),
        target_id=required_id_from_db(_text(row, "target_id")),
        key=_text(row, "key"),
        value=_text(row, "value"),
        confidence=_optional_float(row, "confidence"),
        explanation=_optional_text(row, "explanation"),
    )


def encode_relation(value: Relation) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "left_kind": value.left_kind.value,
        "left_id": str(value.left_id),
        "right_kind": value.right_kind.value,
        "right_id": str(value.right_id),
        "relation_type": value.relation_type.value,
        "confidence": value.confidence,
        "status": value.status.value,
        "created_at": datetime_to_db(value.created_at),
    }


def decode_relation(row: Mapping[str, Any]) -> Relation:
    return Relation(
        id=required_id_from_db(_text(row, "id")),
        left_kind=EntityKind(_text(row, "left_kind")),
        left_id=required_id_from_db(_text(row, "left_id")),
        right_kind=EntityKind(_text(row, "right_kind")),
        right_id=required_id_from_db(_text(row, "right_id")),
        relation_type=RelationType(_text(row, "relation_type")),
        confidence=float(row["confidence"]),
        status=MatchStatus(_text(row, "status")),
        created_at=required_datetime_from_db(_text(row, "created_at")),
    )


def encode_evidence(value: Evidence) -> Mapping[str, object]:
    return {
        "id": str(value.id),
        "relation_id": str(value.relation_id),
        "evidence_type": value.evidence_type,
        "summary": value.summary,
        "strength": value.strength,
        "tool_execution_id": id_to_db(value.tool_execution_id),
        **provenance_to_row(value.provenance),
    }


def decode_evidence(row: Mapping[str, Any]) -> Evidence:
    execution = _optional_text(row, "tool_execution_id")
    return Evidence(
        id=required_id_from_db(_text(row, "id")),
        relation_id=required_id_from_db(_text(row, "relation_id")),
        evidence_type=_text(row, "evidence_type"),
        summary=_text(row, "summary"),
        provenance=provenance_from_row(row),
        strength=_optional_float(row, "strength"),
        tool_execution_id=None if execution is None else required_id_from_db(execution),
    )


CODECS: dict[type[Any], Codec[Any]] = {
    ScanRoot: Codec(schema.scan_roots, encode_scan_root, decode_scan_root),
    ScanRun: Codec(schema.scan_runs, encode_scan_run, decode_scan_run),
    FileRecord: Codec(schema.file_records, encode_file_record, decode_file_record),
    FileObservation: Codec(
        schema.file_observations,
        encode_file_observation,
        decode_file_observation,
    ),
    ValueAssertion: Codec(
        schema.value_assertions,
        encode_value_assertion,
        decode_value_assertion,
    ),
    Agent: Codec(schema.agents, encode_agent, decode_agent),
    AgentName: Codec(schema.agent_names, encode_agent_name, decode_agent_name),
    ExternalIdentifier: Codec(
        schema.external_identifiers,
        encode_external_identifier,
        decode_external_identifier,
    ),
    Contribution: Codec(schema.contributions, encode_contribution, decode_contribution),
    Work: Codec(schema.works, encode_work, decode_work),
    Edition: Codec(schema.editions, encode_edition, decode_edition),
    Series: Codec(schema.series, encode_series, decode_series),
    SeriesMembership: Codec(
        schema.series_memberships,
        encode_series_membership,
        decode_series_membership,
    ),
    MusicWork: Codec(schema.music_works, encode_music_work, decode_music_work),
    MusicWorkRelation: Codec(
        schema.music_work_relations,
        encode_music_work_relation,
        decode_music_work_relation,
    ),
    CatalogDesignation: Codec(
        schema.catalog_designations,
        encode_catalog_designation,
        decode_catalog_designation,
    ),
    Recording: Codec(schema.recordings, encode_recording, decode_recording),
    ReleaseGroup: Codec(schema.release_groups, encode_release_group, decode_release_group),
    Release: Codec(schema.releases, encode_release, decode_release),
    ReleaseRecording: Codec(
        schema.release_recordings,
        encode_release_recording,
        decode_release_recording,
    ),
    ToolExecution: Codec(
        schema.tool_executions,
        encode_tool_execution,
        decode_tool_execution,
    ),
    ToolResult: Codec(schema.tool_results, encode_tool_result, decode_tool_result),
    ClassificationAssertion: Codec(
        schema.classification_assertions,
        encode_classification,
        decode_classification,
    ),
    Fingerprint: Codec(schema.fingerprints, encode_fingerprint, decode_fingerprint),
    Relation: Codec(schema.relations, encode_relation, decode_relation),
    Evidence: Codec(schema.evidence, encode_evidence, decode_evidence),
}


def codec_for(model_type: type[T]) -> Codec[T]:
    """Return the registered codec for a supported domain type."""
    codec = CODECS.get(model_type)
    if codec is None:
        raise KeyError(f"no persistence codec registered for {model_type!r}")
    return codec  # type: ignore[return-value]
