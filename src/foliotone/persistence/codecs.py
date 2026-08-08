"""Generic domain-to-row codecs for the W1 persistence schema."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from typing import Any, cast, get_args, get_type_hints

from sqlalchemy import Table

from foliotone.core import (
    Agent,
    AgentName,
    CatalogDesignation,
    ClassificationAssertion,
    Contribution,
    Edition,
    EntityId,
    Evidence,
    ExternalIdentifier,
    FileObservation,
    FileRecord,
    Fingerprint,
    MusicWork,
    MusicWorkRelation,
    Provenance,
    Recording,
    Relation,
    Release,
    ReleaseGroup,
    ReleaseRecording,
    ScanRoot,
    ScanRun,
    Series,
    SeriesMembership,
    ValueAssertion,
    Work,
)
from foliotone.persistence import schema
from foliotone.persistence._mapping import (
    datetime_to_db,
    provenance_from_row,
    provenance_to_row,
    required_datetime_from_db,
)
from foliotone.tooling import ToolExecution, ToolResult


@dataclass(frozen=True, slots=True)
class Codec[T]:
    """Maps one immutable dataclass domain type to one SQLAlchemy Core table."""

    model_type: type[T]
    table: Table

    def encode(self, value: T) -> Mapping[str, object]:
        """Flatten a supported immutable domain record into SQL column values."""
        row: dict[str, object] = {}
        for field in fields(cast(Any, value)):
            field_value = getattr(value, field.name)
            if field.name == "provenance":
                if not isinstance(field_value, Provenance):
                    raise TypeError("provenance field must contain Provenance")
                row.update(provenance_to_row(field_value))
            else:
                row[field.name] = _encode_scalar(field_value)
        return row

    def decode(self, row: Mapping[str, Any]) -> T:
        """Rebuild a supported immutable domain record from one SQL row."""
        hints = get_type_hints(self.model_type)
        values: dict[str, object] = {}
        for field in fields(cast(Any, self.model_type)):
            if field.name == "provenance":
                values[field.name] = provenance_from_row(row)
            else:
                values[field.name] = _decode_scalar(hints[field.name], row[field.name])
        constructor = cast(Any, self.model_type)
        return cast(T, constructor(**values))


def _encode_scalar(value: object) -> object:
    if isinstance(value, EntityId):
        return str(value)
    if isinstance(value, datetime):
        encoded = datetime_to_db(value)
        if encoded is None:
            raise AssertionError("non-null datetime encoded as None")
        return encoded
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported persistence value type: {type(value)!r}")


def _decode_scalar(annotation: Any, value: object) -> object:
    if value is None:
        return None

    target = _unwrap_optional(annotation)
    if target is EntityId:
        return EntityId.parse(str(value))
    if target is datetime:
        return required_datetime_from_db(str(value))
    if isinstance(target, type) and issubclass(target, StrEnum):
        return target(str(value))
    if target in {str, int, float, bool}:
        converter = cast(Any, target)
        return converter(value)
    return value


def _unwrap_optional(annotation: Any) -> Any:
    args = get_args(annotation)
    non_none = tuple(arg for arg in args if arg is not type(None))
    if len(args) == 2 and len(non_none) == 1:
        return non_none[0]
    return annotation


_MODEL_TABLES: dict[type[Any], Table] = {
    ScanRoot: schema.scan_roots,
    ScanRun: schema.scan_runs,
    FileRecord: schema.file_records,
    FileObservation: schema.file_observations,
    ValueAssertion: schema.value_assertions,
    Agent: schema.agents,
    AgentName: schema.agent_names,
    ExternalIdentifier: schema.external_identifiers,
    Contribution: schema.contributions,
    Work: schema.works,
    Edition: schema.editions,
    Series: schema.series,
    SeriesMembership: schema.series_memberships,
    MusicWork: schema.music_works,
    MusicWorkRelation: schema.music_work_relations,
    CatalogDesignation: schema.catalog_designations,
    Recording: schema.recordings,
    ReleaseGroup: schema.release_groups,
    Release: schema.releases,
    ReleaseRecording: schema.release_recordings,
    ToolExecution: schema.tool_executions,
    ToolResult: schema.tool_results,
    ClassificationAssertion: schema.classification_assertions,
    Fingerprint: schema.fingerprints,
    Relation: schema.relations,
    Evidence: schema.evidence,
}


def codec_for[T](model_type: type[T]) -> Codec[T]:
    """Return the registered codec for a supported domain type."""
    table = _MODEL_TABLES.get(model_type)
    if table is None:
        raise KeyError(f"no persistence codec registered for {model_type!r}")
    return Codec(model_type=model_type, table=table)
