"""Immutable metadata index and bounded query execution for CollectionState v1."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from sqlalchemy import Integer, Text, and_, column, insert, literal, or_, select, table
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from foliotone.collection_state import (
    COLLECTION_QUERY_INDEX_PROFILE,
    COLLECTION_QUERY_METADATA_FIELDS,
    COLLECTION_QUERY_SERIALIZER,
    MAX_COLLECTION_QUERY_FINDINGS_PER_DOCUMENT,
    MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS,
    MAX_COLLECTION_QUERY_LIMIT,
    MAX_COLLECTION_QUERY_METADATA_VALUES_PER_DOCUMENT,
    CollectionQueryBooleanOperator,
    CollectionQueryCoverageState,
    CollectionQueryExpression,
    CollectionQueryField,
    CollectionQueryOperator,
    CollectionQueryPredicate,
    CollectionQuerySpec,
    CollectionQueryTruncationState,
    CollectionQueryValueKind,
    CollectionStateComponentName,
    CollectionStateItemState,
    CollectionStateSnapshot,
    collection_query_fts_expression,
    normalize_collection_query_value,
)
from foliotone.collection_state.contracts import canonical_json_bytes, sha256_digest
from foliotone.core.ids import EntityId
from foliotone.persistence import schema, w3_schema
from foliotone.persistence.collection_query_schema import (
    collection_query_documents,
    collection_query_indexes,
    collection_query_values,
)
from foliotone.persistence.collection_state_schema import collection_state_items

_METADATA_CONTRIBUTOR = re.compile(r"contributor\.\d+\.name\Z")
_METADATA_IDENTIFIER = re.compile(r"identifier\.\d+\.value\Z")
_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_COMPONENT_COLUMN = {
    component: f"{component.value.casefold()}_state" for component in CollectionStateComponentName
}
_FIELD_ORDER = {value: ordinal for ordinal, value in enumerate(CollectionQueryField)}


class CollectionQueryStoreError(RuntimeError):
    """The immutable query projection is unavailable or inconsistent."""


@dataclass(frozen=True, slots=True)
class CollectionQueryIndexSummary:
    snapshot_id: EntityId
    document_count: int
    value_count: int
    metadata_value_count: int
    finding_value_count: int
    truncated_value_count: int
    coverage_state: CollectionQueryCoverageState
    truncation_state: CollectionQueryTruncationState
    values_digest: str
    content_digest: str
    profile: str = COLLECTION_QUERY_INDEX_PROFILE
    serializer: str = COLLECTION_QUERY_SERIALIZER

    def material_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "serializer": self.serializer,
            "snapshot_id": str(self.snapshot_id),
            "document_count": self.document_count,
            "value_count": self.value_count,
            "metadata_value_count": self.metadata_value_count,
            "finding_value_count": self.finding_value_count,
            "truncated_value_count": self.truncated_value_count,
            "coverage_state": self.coverage_state.value,
            "truncation_state": self.truncation_state.value,
            "values_digest": self.values_digest,
        }

    def __post_init__(self) -> None:
        if self.profile != COLLECTION_QUERY_INDEX_PROFILE or self.serializer != (
            COLLECTION_QUERY_SERIALIZER
        ):
            raise ValueError("Collection query index profile is invalid")
        if not isinstance(self.snapshot_id, EntityId):
            raise ValueError("Collection query index snapshot ID is invalid")
        for name in (
            "document_count",
            "value_count",
            "metadata_value_count",
            "finding_value_count",
            "truncated_value_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.metadata_value_count + self.finding_value_count > self.value_count:
            raise ValueError("Collection query index counts are inconsistent")
        if self.document_count == 0 and self.value_count != 0:
            raise ValueError("an empty Collection query index cannot contain values")
        if self.truncated_value_count == 0:
            if self.coverage_state is not CollectionQueryCoverageState.COMPLETE or (
                self.truncation_state is not CollectionQueryTruncationState.NONE
            ):
                raise ValueError("Collection query index complete coverage is inconsistent")
        elif self.coverage_state is not CollectionQueryCoverageState.PARTIAL or (
            self.truncation_state is not CollectionQueryTruncationState.VALUE_LIMIT
        ):
            raise ValueError("Collection query index partial coverage is inconsistent")
        _require_sha256(self.values_digest, "values_digest")
        _require_sha256(self.content_digest, "content_digest")
        if self.content_digest != sha256_digest(self.material_payload()):
            raise ValueError("Collection query index content digest is inconsistent")


@dataclass(frozen=True, slots=True)
class CollectionQueryPrivateValue:
    field: CollectionQueryField
    value: str = dataclass_field(repr=False)
    evidence_kind: CollectionQueryValueKind = CollectionQueryValueKind.METADATA_CANDIDATE

    def __post_init__(self) -> None:
        if self.field not in COLLECTION_QUERY_METADATA_FIELDS:
            raise ValueError("private query values are restricted to selected metadata")
        if self.evidence_kind is not CollectionQueryValueKind.METADATA_CANDIDATE:
            raise ValueError("private query value evidence kind is invalid")
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("private query value must not be empty")


@dataclass(frozen=True, slots=True)
class CollectionQueryHit:
    file_id: EntityId
    observation_id: EntityId
    format_name: str
    component_states: tuple[tuple[CollectionStateComponentName, str], ...]
    private_values: tuple[CollectionQueryPrivateValue, ...] = dataclass_field(
        default=(), repr=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("Collection query hit IDs are invalid")
        if self.format_name not in {"EPUB", "MOBI", "AZW", "AZW3", "PDF", "OTHER"}:
            raise ValueError("Collection query hit format is invalid")
        if tuple(component for component, _state in self.component_states) != tuple(
            CollectionStateComponentName
        ):
            raise ValueError("Collection query hit states are incomplete")
        if any(
            state not in {candidate.value for candidate in CollectionStateItemState}
            for _component, state in self.component_states
        ):
            raise ValueError("Collection query hit state is invalid")
        if any(not isinstance(value, CollectionQueryPrivateValue) for value in self.private_values):
            raise ValueError("Collection query hit private values are invalid")


@dataclass(frozen=True, slots=True)
class CollectionQueryPage:
    index: CollectionQueryIndexSummary
    query_fields: tuple[CollectionQueryField, ...]
    hits: tuple[CollectionQueryHit, ...]
    truncated: bool
    next_after_file_id: EntityId | None

    def __post_init__(self) -> None:
        fields = tuple(self.query_fields)
        ordered_fields = tuple(field for field in CollectionQueryField if field in fields)
        if not fields or fields != ordered_fields:
            raise ValueError("Collection query page fields must be non-empty, ordered and unique")
        if len(self.hits) > MAX_COLLECTION_QUERY_LIMIT:
            raise ValueError("Collection query page exceeds the result limit")
        if self.truncated != (self.next_after_file_id is not None):
            raise ValueError("Collection query cursor and truncation marker disagree")
        file_ids = tuple(str(hit.file_id) for hit in self.hits)
        if file_ids != tuple(sorted(set(file_ids))):
            raise ValueError("Collection query hits must be sorted and unique")
        if self.truncated and (
            not self.hits or self.next_after_file_id != self.hits[-1].file_id
        ):
            raise ValueError("Collection query cursor must identify the last result")


@dataclass(frozen=True, slots=True)
class _ProjectedValue:
    ordinal: int
    field_name: CollectionQueryField
    value_kind: CollectionQueryValueKind
    value: str = dataclass_field(repr=False)
    normalized_value: str = dataclass_field(repr=False)
    value_digest: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("Collection query value ordinal is invalid")
        if not self.value or not self.normalized_value:
            raise ValueError("Collection query values must not be empty")
        if (
            len(self.value) > MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS
            or len(self.normalized_value) > MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS
        ):
            raise ValueError("Collection query value exceeds the index contract")
        expected = sha256_digest(self.material_payload())
        if not self.value_digest:
            object.__setattr__(self, "value_digest", expected)
        _require_sha256(self.value_digest, "value_digest")
        if self.value_digest != expected:
            raise ValueError("Collection query value digest is inconsistent")

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "field_name": self.field_name.value,
            "value_kind": self.value_kind.value,
            "value": self.value,
            "normalized_value": self.normalized_value,
        }

    def canonical_payload(self) -> dict[str, object]:
        return {**self.material_payload(), "value_digest": self.value_digest}


@dataclass(frozen=True, slots=True)
class _ProjectedDocument:
    ordinal: int
    file_id: EntityId
    observation_id: EntityId
    format_name: str
    component_states: tuple[tuple[CollectionStateComponentName, str], ...]
    values: tuple[_ProjectedValue, ...] = dataclass_field(repr=False)
    truncated_value_count: int = 0
    document_digest: str = ""

    def __post_init__(self) -> None:
        if tuple(component for component, _state in self.component_states) != tuple(
            CollectionStateComponentName
        ):
            raise ValueError("Collection query document states are incomplete")
        if tuple(value.ordinal for value in self.values) != tuple(range(len(self.values))):
            raise ValueError("Collection query values must be contiguous")
        expected = sha256_digest(self.material_payload())
        if not self.document_digest:
            object.__setattr__(self, "document_digest", expected)
        _require_sha256(self.document_digest, "document_digest")
        if self.document_digest != expected:
            raise ValueError("Collection query document digest is inconsistent")

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "file_id": str(self.file_id),
            "observation_id": str(self.observation_id),
            "format_name": self.format_name,
            "component_states": [
                {"component": component.value, "state": state}
                for component, state in self.component_states
            ],
            "values": [value.canonical_payload() for value in self.values],
            "truncated_value_count": self.truncated_value_count,
        }


class _ProjectionHasher:
    def __init__(self) -> None:
        self._digest = hashlib.sha256(b"foliotone:collection-query-index-values/v1\x00")
        self.document_count = 0
        self.value_count = 0
        self.metadata_value_count = 0
        self.finding_value_count = 0
        self.truncated_value_count = 0

    def update(self, document: _ProjectedDocument) -> None:
        if document.ordinal != self.document_count:
            raise ValueError("Collection query documents must be contiguous")
        payload = canonical_json_bytes(document.material_payload())
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        self.document_count += 1
        self.value_count += len(document.values)
        self.metadata_value_count += sum(
            value.value_kind is CollectionQueryValueKind.METADATA_CANDIDATE
            for value in document.values
        )
        self.finding_value_count += sum(
            value.value_kind is CollectionQueryValueKind.FINDING_CODE for value in document.values
        )
        self.truncated_value_count += document.truncated_value_count

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class SQLiteCollectionQueryStore:
    """Build immutable index rows and execute only validated query expressions."""

    def __init__(self, engine: Engine, *, batch_size: int = 250) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
            raise ValueError("Collection query batch_size must be between 1 and 1000")
        self._engine = engine
        self._batch_size = batch_size

    def ensure_for_snapshot(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
    ) -> tuple[CollectionQueryIndexSummary, bool]:
        """Create or verify the query projection in the caller's transaction."""

        try:
            existing = self._read_summary(connection, snapshot.id)
            if existing is not None:
                self._verify_persisted_projection(connection, existing)
                return existing, False
            summary = self._compute_projection_summary(connection, snapshot)
            self._insert_projection(connection, snapshot, summary)
            return summary, True
        except CollectionQueryStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise CollectionQueryStoreError("Collection query index persistence failed") from error

    def search(
        self,
        snapshot_id: EntityId,
        spec: CollectionQuerySpec,
        *,
        private_details: bool = False,
    ) -> CollectionQueryPage:
        if not isinstance(snapshot_id, EntityId) or not isinstance(spec, CollectionQuerySpec):
            raise ValueError("Collection query request is invalid")
        try:
            with self._engine.connect() as connection:
                summary = self._read_summary(connection, snapshot_id)
                if summary is None:
                    raise CollectionQueryStoreError("Collection query index is unavailable")
                expression = _query_expression_clause(spec.where)
                statement = select(collection_query_documents).where(
                    collection_query_documents.c.snapshot_id == str(snapshot_id),
                    expression,
                )
                if spec.after_file_id is not None:
                    statement = statement.where(
                        collection_query_documents.c.file_id > str(spec.after_file_id)
                    )
                rows = (
                    connection.execute(
                        statement.order_by(collection_query_documents.c.file_id).limit(
                            spec.limit + 1
                        )
                    )
                    .mappings()
                    .all()
                )
                truncated = len(rows) > spec.limit
                page_rows = rows[: spec.limit]
                private_by_document = (
                    self._private_values(
                        connection,
                        snapshot_id,
                        tuple(int(row["ordinal"]) for row in page_rows),
                        spec,
                    )
                    if private_details
                    else {}
                )
                hits = tuple(
                    _hit_from_row(
                        row,
                        private_by_document.get(int(row["ordinal"]), ()),
                    )
                    for row in page_rows
                )
                next_after = hits[-1].file_id if truncated and hits else None
                return CollectionQueryPage(summary, spec.fields, hits, truncated, next_after)
        except CollectionQueryStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise CollectionQueryStoreError("Collection query execution failed") from error

    def _compute_projection_summary(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
    ) -> CollectionQueryIndexSummary:
        hasher = _ProjectionHasher()
        for document in self._iter_source_projection(connection, snapshot):
            hasher.update(document)
        return _index_summary(snapshot.id, hasher)

    def _insert_projection(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
        summary: CollectionQueryIndexSummary,
    ) -> None:
        connection.execute(insert(collection_query_indexes), _summary_row(summary))
        hasher = _ProjectionHasher()
        for document in self._iter_source_projection(connection, snapshot):
            hasher.update(document)
            connection.execute(
                insert(collection_query_documents), _document_row(snapshot.id, document)
            )
            if document.values:
                connection.execute(
                    insert(collection_query_values),
                    [_value_row(snapshot.id, document.ordinal, value) for value in document.values],
                )
        repeated = _index_summary(snapshot.id, hasher)
        if repeated != summary:
            raise CollectionQueryStoreError("Collection query source evidence changed during build")

    def _iter_source_projection(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
    ) -> Iterator[_ProjectedDocument]:
        after_ordinal = -1
        expected_ordinal = 0
        while True:
            rows = (
                connection.execute(
                    select(collection_state_items)
                    .where(
                        collection_state_items.c.snapshot_id == str(snapshot.id),
                        collection_state_items.c.ordinal > after_ordinal,
                    )
                    .order_by(collection_state_items.c.ordinal)
                    .limit(self._batch_size)
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            if int(rows[0]["ordinal"]) != expected_ordinal:
                raise CollectionQueryStoreError("CollectionState items are incomplete for query")
            observation_ids = tuple(str(row["observation_id"]) for row in rows)
            metadata_values, metadata_truncation = _load_metadata_values(
                connection, observation_ids
            )
            finding_values, finding_truncation = _load_finding_values(
                connection,
                snapshot.source_scan_run_id,
                observation_ids,
            )
            for row in rows:
                ordinal = int(row["ordinal"])
                if ordinal != expected_ordinal:
                    raise CollectionQueryStoreError("CollectionState items are not contiguous")
                observation_id = str(row["observation_id"])
                values = _project_values(
                    row,
                    metadata_values.get(observation_id, ()),
                    finding_values.get(observation_id, ()),
                )
                yield _ProjectedDocument(
                    ordinal=ordinal,
                    file_id=EntityId.parse(str(row["file_id"])),
                    observation_id=EntityId.parse(observation_id),
                    format_name=str(row["format_name"]),
                    component_states=tuple(
                        (component, str(row[_COMPONENT_COLUMN[component]]))
                        for component in CollectionStateComponentName
                    ),
                    values=values,
                    truncated_value_count=(
                        metadata_truncation.get(observation_id, 0)
                        + finding_truncation.get(observation_id, 0)
                    ),
                )
                expected_ordinal += 1
            after_ordinal = int(rows[-1]["ordinal"])
        if expected_ordinal != snapshot.item_count:
            raise CollectionQueryStoreError("CollectionState item count is inconsistent for query")

    def _read_summary(
        self, connection: Connection, snapshot_id: EntityId
    ) -> CollectionQueryIndexSummary | None:
        row = (
            connection.execute(
                select(collection_query_indexes).where(
                    collection_query_indexes.c.snapshot_id == str(snapshot_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _summary_from_row(row)

    def _verify_persisted_projection(
        self,
        connection: Connection,
        summary: CollectionQueryIndexSummary,
    ) -> None:
        hasher = _ProjectionHasher()
        after_ordinal = -1
        while True:
            document_rows = (
                connection.execute(
                    select(collection_query_documents)
                    .where(
                        collection_query_documents.c.snapshot_id == str(summary.snapshot_id),
                        collection_query_documents.c.ordinal > after_ordinal,
                    )
                    .order_by(collection_query_documents.c.ordinal)
                    .limit(self._batch_size)
                )
                .mappings()
                .all()
            )
            if not document_rows:
                break
            ordinals = tuple(int(row["ordinal"]) for row in document_rows)
            value_rows = (
                connection.execute(
                    select(collection_query_values)
                    .where(
                        collection_query_values.c.snapshot_id == str(summary.snapshot_id),
                        collection_query_values.c.document_ordinal.in_(ordinals),
                    )
                    .order_by(
                        collection_query_values.c.document_ordinal,
                        collection_query_values.c.ordinal,
                    )
                )
                .mappings()
                .all()
            )
            values_by_document: dict[int, list[_ProjectedValue]] = {value: [] for value in ordinals}
            for row in value_rows:
                values_by_document[int(row["document_ordinal"])].append(_value_from_row(row))
            for row in document_rows:
                ordinal = int(row["ordinal"])
                document = _document_from_row(row, tuple(values_by_document[ordinal]))
                hasher.update(document)
            after_ordinal = ordinals[-1]
        if _index_summary(summary.snapshot_id, hasher) != summary:
            raise CollectionQueryStoreError("Collection query index rows are incomplete")

    @staticmethod
    def _private_values(
        connection: Connection,
        snapshot_id: EntityId,
        document_ordinals: tuple[int, ...],
        spec: CollectionQuerySpec,
    ) -> dict[int, tuple[CollectionQueryPrivateValue, ...]]:
        if not document_ordinals:
            return {}
        metadata_fields = tuple(
            field.value for field in spec.fields if field in COLLECTION_QUERY_METADATA_FIELDS
        )
        if not metadata_fields:
            return {}
        rows = (
            connection.execute(
                select(
                    collection_query_values.c.document_ordinal,
                    collection_query_values.c.field_name,
                    collection_query_values.c.value,
                )
                .where(
                    collection_query_values.c.snapshot_id == str(snapshot_id),
                    collection_query_values.c.document_ordinal.in_(document_ordinals),
                    collection_query_values.c.field_name.in_(metadata_fields),
                    collection_query_values.c.value_kind
                    == CollectionQueryValueKind.METADATA_CANDIDATE.value,
                )
                .order_by(
                    collection_query_values.c.document_ordinal,
                    collection_query_values.c.ordinal,
                )
            )
            .mappings()
            .all()
        )
        values: dict[int, list[CollectionQueryPrivateValue]] = {}
        for row in rows:
            values.setdefault(int(row["document_ordinal"]), []).append(
                CollectionQueryPrivateValue(
                    CollectionQueryField(str(row["field_name"])),
                    str(row["value"]),
                )
            )
        return {key: tuple(items) for key, items in values.items()}


def _load_metadata_values(
    connection: Connection,
    observation_ids: tuple[str, ...],
) -> tuple[
    dict[str, tuple[tuple[CollectionQueryField, str], ...]],
    dict[str, int],
]:
    selected: dict[str, list[tuple[CollectionQueryField, str]]] = {
        observation_id: [] for observation_id in observation_ids
    }
    seen: dict[str, set[tuple[CollectionQueryField, str]]] = {
        observation_id: set() for observation_id in observation_ids
    }
    truncated: dict[str, int] = {}
    rows = (
        connection.execution_options(stream_results=True)
        .execute(
            select(
                schema.tool_results.c.target_id,
                schema.tool_results.c.key,
                schema.tool_results.c.value,
                schema.tool_results.c.id,
            )
            .where(
                schema.tool_results.c.target_kind == "FILE_OBSERVATION",
                schema.tool_results.c.target_id.in_(observation_ids),
                schema.tool_results.c.result_type == "ebook_metadata_candidate",
            )
            .order_by(
                schema.tool_results.c.target_id,
                schema.tool_results.c.key,
                schema.tool_results.c.value,
                schema.tool_results.c.id,
            )
        )
        .mappings()
    )
    for row in rows:
        observation_id = str(row["target_id"])
        field_name = _metadata_field(str(row["key"]))
        if field_name is None:
            continue
        raw_value = str(row["value"])
        if not raw_value or len(raw_value) > MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        normalized = normalize_collection_query_value(raw_value)
        if not normalized or len(normalized) > MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        identity = (field_name, raw_value)
        if identity in seen[observation_id]:
            continue
        if len(selected[observation_id]) >= MAX_COLLECTION_QUERY_METADATA_VALUES_PER_DOCUMENT:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        seen[observation_id].add(identity)
        selected[observation_id].append(identity)
    return {key: tuple(values) for key, values in selected.items()}, truncated


def _load_finding_values(
    connection: Connection,
    source_scan_run_id: EntityId,
    observation_ids: tuple[str, ...],
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    selected: dict[str, list[str]] = {observation_id: [] for observation_id in observation_ids}
    seen: dict[str, set[str]] = {observation_id: set() for observation_id in observation_ids}
    truncated: dict[str, int] = {}
    rows = (
        connection.execution_options(stream_results=True)
        .execute(
            select(
                w3_schema.ebook_collection_items.c.observation_id,
                w3_schema.ebook_collection_findings.c.code,
                w3_schema.ebook_collection_findings.c.id,
            )
            .select_from(
                w3_schema.ebook_collection_findings.join(
                    w3_schema.ebook_collection_items,
                    w3_schema.ebook_collection_findings.c.item_id
                    == w3_schema.ebook_collection_items.c.id,
                ).join(
                    w3_schema.ebook_collection_runs,
                    w3_schema.ebook_collection_items.c.run_id
                    == w3_schema.ebook_collection_runs.c.id,
                )
            )
            .where(
                w3_schema.ebook_collection_runs.c.source_scan_run_id == str(source_scan_run_id),
                w3_schema.ebook_collection_items.c.observation_id.in_(observation_ids),
            )
            .order_by(
                w3_schema.ebook_collection_items.c.observation_id,
                w3_schema.ebook_collection_findings.c.code,
                w3_schema.ebook_collection_findings.c.id,
            )
        )
        .mappings()
    )
    for row in rows:
        observation_id = str(row["observation_id"])
        raw_code = str(row["code"])
        if not raw_code or len(raw_code) > 128:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        code = raw_code.upper()
        if _FINDING_CODE.fullmatch(code) is None:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        if code in seen[observation_id]:
            continue
        if len(selected[observation_id]) >= MAX_COLLECTION_QUERY_FINDINGS_PER_DOCUMENT:
            truncated[observation_id] = truncated.get(observation_id, 0) + 1
            continue
        seen[observation_id].add(code)
        selected[observation_id].append(code)
    return {key: tuple(values) for key, values in selected.items()}, truncated


def _metadata_field(key: str) -> CollectionQueryField | None:
    if key == "title":
        return CollectionQueryField.TITLE
    if key == "language":
        return CollectionQueryField.LANGUAGE
    if key == "publisher":
        return CollectionQueryField.PUBLISHER
    if _METADATA_CONTRIBUTOR.fullmatch(key):
        return CollectionQueryField.CONTRIBUTOR
    if _METADATA_IDENTIFIER.fullmatch(key):
        return CollectionQueryField.IDENTIFIER
    return None


def _project_values(
    item_row: Mapping[Any, Any],
    metadata_values: tuple[tuple[CollectionQueryField, str], ...],
    finding_values: tuple[str, ...],
) -> tuple[_ProjectedValue, ...]:
    specs: list[tuple[CollectionQueryField, CollectionQueryValueKind, str]] = [
        (
            CollectionQueryField.FILE_ID,
            CollectionQueryValueKind.OPAQUE_ID,
            str(item_row["file_id"]),
        ),
        (
            CollectionQueryField.OBSERVATION_ID,
            CollectionQueryValueKind.OPAQUE_ID,
            str(item_row["observation_id"]),
        ),
        (
            CollectionQueryField.FORMAT,
            CollectionQueryValueKind.STATUS,
            str(item_row["format_name"]),
        ),
    ]
    specs.extend(
        (
            CollectionQueryField(f"{component.value.casefold()}_status"),
            CollectionQueryValueKind.STATUS,
            str(item_row[_COMPONENT_COLUMN[component]]),
        )
        for component in CollectionStateComponentName
    )
    specs.extend(
        (CollectionQueryField.FINDING_CODE, CollectionQueryValueKind.FINDING_CODE, code)
        for code in finding_values
    )
    specs.extend(
        (query_field, CollectionQueryValueKind.METADATA_CANDIDATE, value)
        for query_field, value in metadata_values
    )
    specs.sort(
        key=lambda item: (
            _FIELD_ORDER[item[0]],
            normalize_collection_query_value(item[2]),
            item[2],
            item[1].value,
        )
    )
    return tuple(
        _ProjectedValue(
            ordinal,
            query_field,
            kind,
            value,
            normalize_collection_query_value(value),
        )
        for ordinal, (query_field, kind, value) in enumerate(specs)
    )


def _metadata_clause(
    predicate: CollectionQueryPredicate,
    alias_suffix: str,
) -> Any:
    values = collection_query_values.alias(f"query_value_{alias_suffix}")
    conditions = [
        values.c.snapshot_id == collection_query_documents.c.snapshot_id,
        values.c.document_ordinal == collection_query_documents.c.ordinal,
        values.c.field_name == predicate.field.value,
    ]
    source: Any = values
    if predicate.operator is CollectionQueryOperator.EQ:
        conditions.append(values.c.normalized_value == predicate.value)
    elif predicate.operator is CollectionQueryOperator.PREFIX:
        escaped = predicate.value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(values.c.normalized_value.like(f"{escaped}%", escape="\\"))
    else:
        fts = table(
            "collection_query_values_fts",
            column("rowid", Integer),
            column("normalized_value", Text),
        ).alias(f"query_fts_{alias_suffix}")
        source = values.join(fts, values.c.row_id == fts.c.rowid)
        conditions.append(
            fts.c.normalized_value.match(collection_query_fts_expression(predicate.value))
        )
    return select(literal(1)).select_from(source).where(*conditions).exists()


def _query_expression_clause(
    expression: CollectionQueryExpression, counter: list[int] | None = None
) -> Any:
    counter = [0] if counter is None else counter
    if isinstance(expression, CollectionQueryPredicate):
        counter[0] += 1
        return _metadata_clause(expression, str(counter[0]))
    children = tuple(_query_expression_clause(child, counter) for child in expression.children)
    if expression.operator is CollectionQueryBooleanOperator.AND:
        return and_(*children)
    return or_(*children)


def _index_summary(snapshot_id: EntityId, hasher: _ProjectionHasher) -> CollectionQueryIndexSummary:
    coverage = (
        CollectionQueryCoverageState.COMPLETE
        if hasher.truncated_value_count == 0
        else CollectionQueryCoverageState.PARTIAL
    )
    truncation = (
        CollectionQueryTruncationState.NONE
        if hasher.truncated_value_count == 0
        else CollectionQueryTruncationState.VALUE_LIMIT
    )
    material = {
        "profile": COLLECTION_QUERY_INDEX_PROFILE,
        "serializer": COLLECTION_QUERY_SERIALIZER,
        "snapshot_id": str(snapshot_id),
        "document_count": hasher.document_count,
        "value_count": hasher.value_count,
        "metadata_value_count": hasher.metadata_value_count,
        "finding_value_count": hasher.finding_value_count,
        "truncated_value_count": hasher.truncated_value_count,
        "coverage_state": coverage.value,
        "truncation_state": truncation.value,
        "values_digest": hasher.hexdigest(),
    }
    return CollectionQueryIndexSummary(
        snapshot_id=snapshot_id,
        document_count=hasher.document_count,
        value_count=hasher.value_count,
        metadata_value_count=hasher.metadata_value_count,
        finding_value_count=hasher.finding_value_count,
        truncated_value_count=hasher.truncated_value_count,
        coverage_state=coverage,
        truncation_state=truncation,
        values_digest=hasher.hexdigest(),
        content_digest=sha256_digest(material),
    )


def _summary_row(summary: CollectionQueryIndexSummary) -> dict[str, object]:
    return {
        "snapshot_id": str(summary.snapshot_id),
        "profile": summary.profile,
        "serializer": summary.serializer,
        "document_count": summary.document_count,
        "value_count": summary.value_count,
        "metadata_value_count": summary.metadata_value_count,
        "finding_value_count": summary.finding_value_count,
        "truncated_value_count": summary.truncated_value_count,
        "coverage_state": summary.coverage_state.value,
        "truncation_state": summary.truncation_state.value,
        "values_digest": summary.values_digest,
        "content_digest": summary.content_digest,
    }


def _summary_from_row(row: Mapping[Any, Any]) -> CollectionQueryIndexSummary:
    return CollectionQueryIndexSummary(
        snapshot_id=EntityId.parse(str(row["snapshot_id"])),
        profile=str(row["profile"]),
        serializer=str(row["serializer"]),
        document_count=int(row["document_count"]),
        value_count=int(row["value_count"]),
        metadata_value_count=int(row["metadata_value_count"]),
        finding_value_count=int(row["finding_value_count"]),
        truncated_value_count=int(row["truncated_value_count"]),
        coverage_state=CollectionQueryCoverageState(str(row["coverage_state"])),
        truncation_state=CollectionQueryTruncationState(str(row["truncation_state"])),
        values_digest=str(row["values_digest"]),
        content_digest=str(row["content_digest"]),
    )


def _document_row(snapshot_id: EntityId, document: _ProjectedDocument) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_id": str(snapshot_id),
        "ordinal": document.ordinal,
        "file_id": str(document.file_id),
        "observation_id": str(document.observation_id),
        "format_name": document.format_name,
        "value_count": len(document.values),
        "truncated_value_count": document.truncated_value_count,
        "document_digest": document.document_digest,
    }
    row.update(
        {_COMPONENT_COLUMN[component]: state for component, state in document.component_states}
    )
    return row


def _value_row(
    snapshot_id: EntityId, document_ordinal: int, value: _ProjectedValue
) -> dict[str, object]:
    return {
        "snapshot_id": str(snapshot_id),
        "document_ordinal": document_ordinal,
        "ordinal": value.ordinal,
        "field_name": value.field_name.value,
        "value_kind": value.value_kind.value,
        "value": value.value,
        "normalized_value": value.normalized_value,
        "value_digest": value.value_digest,
    }


def _value_from_row(row: Mapping[Any, Any]) -> _ProjectedValue:
    return _ProjectedValue(
        ordinal=int(row["ordinal"]),
        field_name=CollectionQueryField(str(row["field_name"])),
        value_kind=CollectionQueryValueKind(str(row["value_kind"])),
        value=str(row["value"]),
        normalized_value=str(row["normalized_value"]),
        value_digest=str(row["value_digest"]),
    )


def _document_from_row(
    row: Mapping[Any, Any], values: tuple[_ProjectedValue, ...]
) -> _ProjectedDocument:
    if int(row["value_count"]) != len(values):
        raise CollectionQueryStoreError("Collection query document value count is incomplete")
    return _ProjectedDocument(
        ordinal=int(row["ordinal"]),
        file_id=EntityId.parse(str(row["file_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        format_name=str(row["format_name"]),
        component_states=tuple(
            (component, str(row[_COMPONENT_COLUMN[component]]))
            for component in CollectionStateComponentName
        ),
        values=values,
        truncated_value_count=int(row["truncated_value_count"]),
        document_digest=str(row["document_digest"]),
    )


def _hit_from_row(
    row: Mapping[Any, Any], private_values: tuple[CollectionQueryPrivateValue, ...]
) -> CollectionQueryHit:
    return CollectionQueryHit(
        file_id=EntityId.parse(str(row["file_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        format_name=str(row["format_name"]),
        component_states=tuple(
            (component, str(row[_COMPONENT_COLUMN[component]]))
            for component in CollectionStateComponentName
        ),
        private_values=private_values,
    )


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
