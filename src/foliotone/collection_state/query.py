"""Validated and bounded metadata-query contracts for CollectionState v1."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from typing import Final

from foliotone.core.ids import EntityId

COLLECTION_QUERY_PROFILE: Final = "collection-query/v1"
COLLECTION_QUERY_INDEX_PROFILE: Final = "collection-query-index/v1"
COLLECTION_QUERY_SERIALIZER: Final = "canonical-json/v1"
DEFAULT_COLLECTION_QUERY_LIMIT: Final = 50
MAX_COLLECTION_QUERY_LIMIT: Final = 100
MAX_COLLECTION_QUERY_DEPTH: Final = 4
MAX_COLLECTION_QUERY_PREDICATES: Final = 16
MAX_COLLECTION_QUERY_VALUE_CHARS: Final = 256
MAX_COLLECTION_QUERY_INDEX_VALUE_CHARS: Final = 4096
MAX_COLLECTION_QUERY_METADATA_VALUES_PER_DOCUMENT: Final = 256
MAX_COLLECTION_QUERY_FINDINGS_PER_DOCUMENT: Final = 128

_TECHNICAL_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_WORD = re.compile(r"\w+", re.UNICODE)


class _DuplicateQueryKeyError(ValueError):
    pass


class CollectionQueryField(StrEnum):
    FILE_ID = "file_id"
    OBSERVATION_ID = "observation_id"
    FORMAT = "format"
    ANALYSIS_STATUS = "analysis_status"
    RESOLUTION_STATUS = "resolution_status"
    CLASSIFICATION_STATUS = "classification_status"
    MATCHING_STATUS = "matching_status"
    REVIEW_STATUS = "review_status"
    CALIBRE_STATUS = "calibre_status"
    ARCHIVE_STATUS = "archive_status"
    CONSOLIDATION_STATUS = "consolidation_status"
    QUARANTINE_STATUS = "quarantine_status"
    FINDING_CODE = "finding_code"
    TITLE = "title"
    CONTRIBUTOR = "contributor"
    IDENTIFIER = "identifier"
    LANGUAGE = "language"
    PUBLISHER = "publisher"


COLLECTION_QUERY_METADATA_FIELDS: Final = frozenset(
    {
        CollectionQueryField.TITLE,
        CollectionQueryField.CONTRIBUTOR,
        CollectionQueryField.IDENTIFIER,
        CollectionQueryField.LANGUAGE,
        CollectionQueryField.PUBLISHER,
    }
)
COLLECTION_QUERY_STATUS_FIELDS: Final = frozenset(
    {
        CollectionQueryField.ANALYSIS_STATUS,
        CollectionQueryField.RESOLUTION_STATUS,
        CollectionQueryField.CLASSIFICATION_STATUS,
        CollectionQueryField.MATCHING_STATUS,
        CollectionQueryField.REVIEW_STATUS,
        CollectionQueryField.CALIBRE_STATUS,
        CollectionQueryField.ARCHIVE_STATUS,
        CollectionQueryField.CONSOLIDATION_STATUS,
        CollectionQueryField.QUARANTINE_STATUS,
    }
)


class CollectionQueryOperator(StrEnum):
    EQ = "EQ"
    PREFIX = "PREFIX"
    MATCH = "MATCH"


class CollectionQueryBooleanOperator(StrEnum):
    AND = "AND"
    OR = "OR"


class CollectionQuerySort(StrEnum):
    FILE_ID_ASC = "FILE_ID_ASC"


class CollectionQueryValueKind(StrEnum):
    OPAQUE_ID = "OPAQUE_ID"
    STATUS = "STATUS"
    FINDING_CODE = "FINDING_CODE"
    METADATA_CANDIDATE = "METADATA_CANDIDATE"


class CollectionQueryCoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class CollectionQueryTruncationState(StrEnum):
    NONE = "NONE"
    VALUE_LIMIT = "VALUE_LIMIT"


def normalize_collection_query_value(value: str) -> str:
    """Normalize local search terms without claiming canonical metadata."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def collection_query_fts_expression(value: str) -> str:
    """Build an injection-safe FTS token conjunction from a validated value."""

    tokens = tuple(_WORD.findall(normalize_collection_query_value(value)))
    if not tokens:
        raise ValueError("MATCH requires at least one searchable token")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


@dataclass(frozen=True, slots=True)
class CollectionQueryPredicate:
    field: CollectionQueryField
    operator: CollectionQueryOperator
    value: str = dataclass_field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.field, CollectionQueryField) or not isinstance(
            self.operator, CollectionQueryOperator
        ):
            raise ValueError("Collection query predicate uses an invalid field or operator")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Collection query predicate value must not be empty")
        if len(self.value) > MAX_COLLECTION_QUERY_VALUE_CHARS:
            raise ValueError("Collection query predicate value exceeds the bounded contract")
        if self.operator is not CollectionQueryOperator.EQ and self.field not in (
            COLLECTION_QUERY_METADATA_FIELDS
        ):
            raise ValueError("PREFIX and MATCH are restricted to selected metadata fields")

        normalized = normalize_collection_query_value(self.value)
        if not normalized:
            raise ValueError("Collection query predicate value normalizes to empty")
        if len(normalized) > MAX_COLLECTION_QUERY_VALUE_CHARS:
            raise ValueError("normalized Collection query value exceeds the bounded contract")
        if self.field in {CollectionQueryField.FILE_ID, CollectionQueryField.OBSERVATION_ID}:
            if self.operator is not CollectionQueryOperator.EQ:
                raise ValueError("opaque IDs support EQ only")
            normalized = str(EntityId.parse(self.value))
        elif self.field is CollectionQueryField.FORMAT:
            canonical = self.value.strip().upper()
            if canonical not in {"EPUB", "MOBI", "AZW", "AZW3", "PDF", "OTHER"}:
                raise ValueError("format is outside the book-only allowlist")
            normalized = normalize_collection_query_value(canonical)
        elif self.field in COLLECTION_QUERY_STATUS_FIELDS:
            canonical = self.value.strip().upper()
            if canonical not in {
                "CURRENT",
                "CURRENT_CONFLICT",
                "STALE",
                "STALE_CONFLICT",
                "UNSCOPED",
                "UNSCOPED_CONFLICT",
                "MISSING",
            }:
                raise ValueError("status is outside the CollectionState allowlist")
            normalized = normalize_collection_query_value(canonical)
        elif self.field is CollectionQueryField.FINDING_CODE:
            canonical = self.value.strip().upper()
            if _TECHNICAL_KEY.fullmatch(canonical) is None:
                raise ValueError("finding code is outside the bounded technical allowlist")
            normalized = normalize_collection_query_value(canonical)
        elif self.operator is CollectionQueryOperator.MATCH:
            collection_query_fts_expression(normalized)
        object.__setattr__(self, "value", normalized)

    def canonical_payload(self) -> dict[str, str]:
        return {
            "field": self.field.value,
            "operator": self.operator.value,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class CollectionQueryGroup:
    operator: CollectionQueryBooleanOperator
    children: tuple[CollectionQueryExpression, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operator, CollectionQueryBooleanOperator):
            raise ValueError("Collection query group operator is invalid")
        children = tuple(self.children)
        if not 1 <= len(children) <= MAX_COLLECTION_QUERY_PREDICATES:
            raise ValueError("Collection query group is empty or oversized")
        if any(
            not isinstance(child, (CollectionQueryPredicate, CollectionQueryGroup))
            for child in children
        ):
            raise ValueError("Collection query group contains an invalid child")
        object.__setattr__(self, "children", children)

    def canonical_payload(self) -> dict[str, object]:
        return {
            self.operator.value.casefold(): [child.canonical_payload() for child in self.children]
        }


type CollectionQueryExpression = CollectionQueryPredicate | CollectionQueryGroup


@dataclass(frozen=True, slots=True)
class CollectionQuerySpec:
    where: CollectionQueryExpression
    sort: CollectionQuerySort = CollectionQuerySort.FILE_ID_ASC
    limit: int = DEFAULT_COLLECTION_QUERY_LIMIT
    after_file_id: EntityId | None = None
    profile: str = COLLECTION_QUERY_PROFILE

    def __post_init__(self) -> None:
        if self.profile != COLLECTION_QUERY_PROFILE:
            raise ValueError("Collection query profile is invalid")
        if not isinstance(self.where, (CollectionQueryPredicate, CollectionQueryGroup)):
            raise ValueError("Collection query requires a validated expression")
        if self.sort is not CollectionQuerySort.FILE_ID_ASC:
            raise ValueError("Collection query sort is outside the fixed allowlist")
        if isinstance(self.limit, bool) or not 1 <= self.limit <= MAX_COLLECTION_QUERY_LIMIT:
            raise ValueError(
                f"Collection query limit must be between 1 and {MAX_COLLECTION_QUERY_LIMIT}"
            )
        if self.after_file_id is not None and not isinstance(self.after_file_id, EntityId):
            raise ValueError("Collection query cursor is invalid")
        depth, predicates = _expression_shape(self.where)
        if depth > MAX_COLLECTION_QUERY_DEPTH:
            raise ValueError("Collection query exceeds the maximum AST depth")
        if predicates > MAX_COLLECTION_QUERY_PREDICATES:
            raise ValueError("Collection query exceeds the maximum predicate count")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "where": self.where.canonical_payload(),
            "sort": self.sort.value,
            "limit": self.limit,
            "after_file_id": (None if self.after_file_id is None else str(self.after_file_id)),
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.canonical_payload())).hexdigest()

    @property
    def fields(self) -> tuple[CollectionQueryField, ...]:
        fields = {predicate.field for predicate in iter_collection_query_predicates(self.where)}
        return tuple(field for field in CollectionQueryField if field in fields)


def parse_collection_query_spec(value: str | Mapping[str, object]) -> CollectionQuerySpec:
    """Parse one exact JSON object and reject every unknown or oversized shape."""

    if isinstance(value, str):
        if len(value) > 16384:
            raise ValueError("Collection query JSON exceeds the bounded contract")
        try:
            raw = json.loads(value, object_pairs_hook=_unique_query_object)
        except (json.JSONDecodeError, RecursionError, _DuplicateQueryKeyError) as error:
            raise ValueError("Collection query is not valid JSON") from error
    else:
        raw = value
    if not isinstance(raw, Mapping):
        raise ValueError("Collection query must be a JSON object")
    allowed = {"profile", "where", "sort", "limit", "after_file_id"}
    if set(raw) - allowed or "where" not in raw:
        raise ValueError("Collection query contains unknown fields or no where expression")
    profile = raw.get("profile", COLLECTION_QUERY_PROFILE)
    if profile != COLLECTION_QUERY_PROFILE:
        raise ValueError("Collection query profile is invalid")
    where = _parse_expression(raw["where"], depth=1)
    try:
        sort = CollectionQuerySort(raw.get("sort", CollectionQuerySort.FILE_ID_ASC.value))
    except (TypeError, ValueError) as error:
        raise ValueError("Collection query sort is invalid") from error
    limit = raw.get("limit", DEFAULT_COLLECTION_QUERY_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("Collection query limit must be an integer")
    after_raw = raw.get("after_file_id")
    if after_raw is None:
        after_file_id = None
    elif isinstance(after_raw, str):
        after_file_id = EntityId.parse(after_raw)
    else:
        raise ValueError("Collection query cursor must be an opaque ID")
    return CollectionQuerySpec(where, sort, limit, after_file_id, profile)


def iter_collection_query_predicates(
    expression: CollectionQueryExpression,
) -> tuple[CollectionQueryPredicate, ...]:
    if isinstance(expression, CollectionQueryPredicate):
        return (expression,)
    return tuple(
        predicate
        for child in expression.children
        for predicate in iter_collection_query_predicates(child)
    )


def _parse_expression(value: object, *, depth: int) -> CollectionQueryExpression:
    if depth > MAX_COLLECTION_QUERY_DEPTH:
        raise ValueError("Collection query exceeds the maximum AST depth")
    if not isinstance(value, Mapping):
        raise ValueError("Collection query expression must be an object")
    keys = set(value)
    if keys == {"field", "operator", "value"}:
        field_value = value["field"]
        operator_value = value["operator"]
        predicate_value = value["value"]
        if not all(
            isinstance(item, str) for item in (field_value, operator_value, predicate_value)
        ):
            raise ValueError("Collection query predicate values must be strings")
        try:
            query_field = CollectionQueryField(field_value)
            query_operator = CollectionQueryOperator(operator_value)
        except ValueError as error:
            raise ValueError("Collection query field or operator is invalid") from error
        return CollectionQueryPredicate(query_field, query_operator, predicate_value)
    if keys not in ({"and"}, {"or"}):
        raise ValueError("Collection query expression contains unknown fields")
    key = next(iter(keys))
    children = value[key]
    if not isinstance(children, list):
        raise ValueError("Collection query group children must be an array")
    if not 1 <= len(children) <= MAX_COLLECTION_QUERY_PREDICATES:
        raise ValueError("Collection query group is empty or oversized")
    operator = (
        CollectionQueryBooleanOperator.AND if key == "and" else CollectionQueryBooleanOperator.OR
    )
    return CollectionQueryGroup(
        operator,
        tuple(_parse_expression(child, depth=depth + 1) for child in children),
    )


def _expression_shape(expression: CollectionQueryExpression) -> tuple[int, int]:
    maximum_depth = 0
    predicate_count = 0
    pending: list[tuple[CollectionQueryExpression, int]] = [(expression, 1)]
    while pending:
        current, depth = pending.pop()
        maximum_depth = max(maximum_depth, depth)
        if isinstance(current, CollectionQueryPredicate):
            predicate_count += 1
            continue
        pending.extend((child, depth + 1) for child in current.children)
    return maximum_depth, predicate_count


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _unique_query_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateQueryKeyError("duplicate Collection query JSON key")
        result[key] = value
    return result
