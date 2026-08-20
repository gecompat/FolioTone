"""Atomic insert-only persistence for profiled book classification assertions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from typing import Any

from sqlalchemy import Engine, exists, insert, select
from sqlalchemy.engine import Connection

from foliotone.classification.contracts import (
    BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    BookClassificationAssertion,
    BookClassificationAssertionLineage,
    ClassificationDimension,
    ClassificationPriorityTier,
    ClassificationSourceKind,
    ClassificationSourceReferenceKind,
)
from foliotone.classification.projection import (
    BookClassificationProjection,
    BookClassificationProjectionAssertionLink,
    BookClassificationProjectionFacet,
    BookClassificationProjectionValue,
    ClassificationFacetStatus,
    ClassificationProjectionConflictCode,
    ClassificationProjectionLinkRole,
    ClassificationProjectionStatus,
    reduce_book_classification_assertions,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    ReviewCandidateKind,
    ReviewDecisionValue,
    ReviewType,
)
from foliotone.persistence import classification_schema, resolution_review_schema, schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db

MAX_CLASSIFICATION_ASSERTION_BATCH = 256
CLASSIFICATION_DECISION_COMPATIBILITY = "book-classification-decision-compatibility/v1"
MAX_CLASSIFICATION_ASSERTION_PAGE = 500
MAX_CLASSIFICATION_PROJECTION_VALUES = 81
MAX_CLASSIFICATION_PROJECTION_LINKS = 500


class ClassificationStoreError(RuntimeError):
    """A path-free immutable classification persistence failure."""


@dataclass(frozen=True, slots=True)
class ClassificationProjectionWriteResult:
    """One atomic immutable projection write result."""

    projection: BookClassificationProjection
    created: bool


class SQLiteClassificationStore:
    """Write profiled book assertions and lineage without update-by-ID semantics."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get(self, assertion: BookClassificationAssertion) -> BookClassificationAssertion:
        """Insert one assertion atomically, or return its exact immutable retry."""

        with self._engine.begin() as connection:
            self._validate_target(connection, assertion.target_kind, assertion.target_id)
            self._validate_source_reference(connection, assertion)
            self._ensure_no_key_collision(connection, assertion)
            existing = self._existing_by_id(connection, assertion)
            if existing:
                return assertion
            connection.execute(insert(schema.classification_assertions).values(**_assertion_row(assertion)))
            connection.execute(
                insert(classification_schema.book_classification_assertion_lineage).values(
                    **_lineage_row(assertion)
                )
            )
            return assertion

    def create_or_get_many(
        self,
        assertions: Iterable[BookClassificationAssertion],
    ) -> tuple[BookClassificationAssertion, ...]:
        """Atomically persist a bounded sequence of independent assertions."""

        materialized = tuple(islice(iter(assertions), MAX_CLASSIFICATION_ASSERTION_BATCH + 1))
        if len(materialized) > MAX_CLASSIFICATION_ASSERTION_BATCH:
            raise ClassificationStoreError("classification assertion batch exceeds the bound")
        with self._engine.begin() as connection:
            for assertion in materialized:
                self._validate_target(connection, assertion.target_kind, assertion.target_id)
                self._validate_source_reference(connection, assertion)
                self._ensure_no_key_collision(connection, assertion)
                if self._existing_by_id(connection, assertion):
                    continue
                connection.execute(
                    insert(schema.classification_assertions).values(**_assertion_row(assertion))
                )
                connection.execute(
                    insert(classification_schema.book_classification_assertion_lineage).values(
                        **_lineage_row(assertion)
                    )
                )
        return materialized

    def list_profiled_for_target(
        self,
        target_kind: EntityKind,
        target_id: EntityId,
        *,
        assertion_profile_version: str = BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        limit: int = 100,
    ) -> tuple[BookClassificationAssertion, ...]:
        """Return a complete bounded, canonical v1 assertion set for one target."""

        if target_kind not in {EntityKind.WORK, EntityKind.EDITION}:
            raise ValueError("classification queries require WORK or EDITION target kind")
        if assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE:
            raise ValueError("unsupported assertion profile version")
        _validate_page_limit(limit)

        assertions = schema.classification_assertions
        lineage = classification_schema.book_classification_assertion_lineage
        statement = (
            select(
                assertions.c.id,
                assertions.c.target_kind,
                assertions.c.target_id,
                assertions.c.dimension,
                assertions.c.value,
                assertions.c.taxonomy,
                assertions.c.confidence,
                assertions.c.source_kind,
                assertions.c.source_name,
                assertions.c.source_version,
                assertions.c.observed_at,
                lineage.c.assertion_key,
                lineage.c.assertion_profile_version,
                lineage.c.source_kind.label("lineage_source_kind"),
                lineage.c.source_reference_kind,
                lineage.c.source_reference,
                lineage.c.priority_tier,
                lineage.c.created_at,
            )
            .join(lineage, lineage.c.assertion_id == assertions.c.id)
            .where(
                assertions.c.target_kind == target_kind.value,
                assertions.c.target_id == str(target_id),
                lineage.c.assertion_profile_version == assertion_profile_version,
            )
        )
        order = (
            assertions.c.dimension,
            assertions.c.taxonomy,
            assertions.c.value,
            lineage.c.assertion_key,
        )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(statement.order_by(*order).limit(limit + 1))
                .mappings()
                .all()
        )
        if len(rows) > limit:
            raise ClassificationStoreError(
                "classification assertion query exceeds the requested bound"
            )
        return tuple(_assertion_from_row(dict(row)) for row in rows)

    def create_or_get_projection(
        self,
        projection: BookClassificationProjection,
    ) -> BookClassificationProjection:
        """Atomically persist one immutable projection, or return its exact retry."""

        return self.create_or_get_projection_result(projection).projection

    def create_or_get_projection_result(
        self,
        projection: BookClassificationProjection,
    ) -> ClassificationProjectionWriteResult:
        """Atomically persist one snapshot and report whether that transaction created it."""

        with self._engine.begin() as connection:
            self._validate_target(connection, projection.target_kind, projection.target_id)
            self._validate_projection_snapshot(connection, projection)
            existing = self._projection_from_connection(connection, projection.id)
            if existing is not None:
                if existing != projection:
                    raise ClassificationStoreError(
                        "projection identity has different immutable content"
                    )
                return ClassificationProjectionWriteResult(projection=existing, created=False)
            identity = connection.execute(
                select(classification_schema.book_classification_projections.c.id).where(
                    classification_schema.book_classification_projections.c.target_kind
                    == projection.target_kind.value,
                    classification_schema.book_classification_projections.c.target_id
                    == str(projection.target_id),
                    classification_schema.book_classification_projections.c.projection_profile_version
                    == projection.projection_profile_version,
                    classification_schema.book_classification_projections.c.input_fingerprint
                    == projection.input_fingerprint,
                )
            ).scalar_one_or_none()
            if identity is not None:
                raise ClassificationStoreError("projection identity collides with a different id")
            connection.execute(
                insert(classification_schema.book_classification_projections).values(
                    id=str(projection.id),
                    target_kind=projection.target_kind.value,
                    target_id=str(projection.target_id),
                    assertion_profile_version=projection.assertion_profile_version,
                    projection_profile_version=projection.projection_profile_version,
                    input_fingerprint=projection.input_fingerprint,
                    status=projection.status.value,
                    created_at=datetime_to_db(_projection_created_at()),
                )
            )
            connection.execute(
                insert(classification_schema.book_classification_projection_values),
                _projection_value_rows(projection),
            )
            if projection.assertion_links:
                connection.execute(
                    insert(classification_schema.book_classification_projection_assertions),
                    _projection_link_rows(projection),
                )
            stored = self._projection_from_connection(connection, projection.id)
            if stored != projection:
                raise ClassificationStoreError(
                    "persisted projection cannot be rehydrated losslessly"
                )
            return ClassificationProjectionWriteResult(projection=stored, created=True)

    def get_projection(self, projection_id: EntityId) -> BookClassificationProjection | None:
        """Return one immutable projection snapshot without a collection-wide fallback."""

        with self._engine.connect() as connection:
            return self._projection_from_connection(connection, projection_id)

    @staticmethod
    def _validate_projection_snapshot(
        connection: Connection,
        projection: BookClassificationProjection,
    ) -> None:
        assertions = SQLiteClassificationStore._linked_profiled_assertions(connection, projection)
        try:
            reduced = reduce_book_classification_assertions(
                target_kind=projection.target_kind,
                target_id=projection.target_id,
                assertions=assertions,
            )
        except ValueError as error:
            raise ClassificationStoreError("projection inputs cannot be reduced") from error
        if reduced != projection:
            raise ClassificationStoreError("projection snapshot differs from its immutable inputs")

    @staticmethod
    def _linked_profiled_assertions(
        connection: Connection,
        projection: BookClassificationProjection,
    ) -> tuple[BookClassificationAssertion, ...]:
        if len(projection.assertion_links) > MAX_CLASSIFICATION_PROJECTION_LINKS:
            raise ClassificationStoreError("projection assertion links exceed the bound")
        expected = {
            (str(link.assertion_id), link.assertion_key) for link in projection.assertion_links
        }
        if not expected:
            return ()
        assertions = schema.classification_assertions
        lineage = classification_schema.book_classification_assertion_lineage
        statement = (
            select(
                assertions.c.id,
                assertions.c.target_kind,
                assertions.c.target_id,
                assertions.c.dimension,
                assertions.c.value,
                assertions.c.taxonomy,
                assertions.c.confidence,
                assertions.c.source_kind,
                assertions.c.source_name,
                assertions.c.source_version,
                assertions.c.observed_at,
                lineage.c.assertion_key,
                lineage.c.assertion_profile_version,
                lineage.c.source_kind.label("lineage_source_kind"),
                lineage.c.source_reference_kind,
                lineage.c.source_reference,
                lineage.c.priority_tier,
                lineage.c.created_at,
            )
            .join(lineage, lineage.c.assertion_id == assertions.c.id)
            .where(
                assertions.c.id.in_([item[0] for item in expected]),
                assertions.c.target_kind == projection.target_kind.value,
                assertions.c.target_id == str(projection.target_id),
                lineage.c.assertion_profile_version == projection.assertion_profile_version,
            )
            .order_by(lineage.c.assertion_key)
            .limit(MAX_CLASSIFICATION_PROJECTION_LINKS + 1)
        )
        rows = connection.execute(statement).mappings().all()
        if len(rows) > MAX_CLASSIFICATION_PROJECTION_LINKS:
            raise ClassificationStoreError("projection assertion links exceed the bound")
        actual = {(str(row["id"]), str(row["assertion_key"])) for row in rows}
        if actual != expected:
            raise ClassificationStoreError(
                "projection assertion links do not match profiled inputs"
            )
        return tuple(_assertion_from_row(dict(row)) for row in rows)

    @staticmethod
    def _projection_from_connection(
        connection: Connection,
        projection_id: EntityId,
    ) -> BookClassificationProjection | None:
        projections = classification_schema.book_classification_projections
        row = connection.execute(
            select(projections).where(projections.c.id == str(projection_id))
        ).mappings().one_or_none()
        if row is None:
            return None
        values = connection.execute(
            select(classification_schema.book_classification_projection_values)
            .where(
                classification_schema.book_classification_projection_values.c.projection_id
                == str(projection_id)
            )
            .order_by(
                classification_schema.book_classification_projection_values.c.dimension,
                classification_schema.book_classification_projection_values.c.ordinal,
            )
            .limit(MAX_CLASSIFICATION_PROJECTION_VALUES + 1)
        ).mappings().all()
        if len(values) > MAX_CLASSIFICATION_PROJECTION_VALUES:
            raise ClassificationStoreError("projection values exceed the bound")
        lineage = classification_schema.book_classification_assertion_lineage
        links = connection.execute(
            select(
                classification_schema.book_classification_projection_assertions.c.assertion_id,
                lineage.c.assertion_key,
                classification_schema.book_classification_projection_assertions.c.link_role,
                classification_schema.book_classification_projection_assertions.c.conflict_code,
            )
            .join(
                lineage,
                lineage.c.assertion_id
                == classification_schema.book_classification_projection_assertions.c.assertion_id,
            )
            .where(
                classification_schema.book_classification_projection_assertions.c.projection_id
                == str(projection_id)
            )
            .order_by(lineage.c.assertion_key)
            .limit(MAX_CLASSIFICATION_PROJECTION_LINKS + 1)
        ).mappings().all()
        if len(links) > MAX_CLASSIFICATION_PROJECTION_LINKS:
            raise ClassificationStoreError("projection assertion links exceed the bound")
        try:
            facets = _projection_facets_from_rows(dict(value) for value in values)
            projection = BookClassificationProjection(
                id=EntityId.parse(str(row["id"])),
                target_kind=EntityKind(str(row["target_kind"])),
                target_id=EntityId.parse(str(row["target_id"])),
                assertion_profile_version=str(row["assertion_profile_version"]),
                projection_profile_version=str(row["projection_profile_version"]),
                input_fingerprint=str(row["input_fingerprint"]),
                status=ClassificationProjectionStatus(str(row["status"])),
                facets=facets,
                assertion_links=tuple(
                    BookClassificationProjectionAssertionLink(
                        assertion_id=EntityId.parse(str(link["assertion_id"])),
                        assertion_key=str(link["assertion_key"]),
                        role=ClassificationProjectionLinkRole(str(link["link_role"])),
                        conflict_code=(
                            None
                            if link["conflict_code"] is None
                            else ClassificationProjectionConflictCode(str(link["conflict_code"]))
                        ),
                    )
                    for link in links
                ),
            )
            SQLiteClassificationStore._validate_projection_snapshot(connection, projection)
            return projection
        except (TypeError, ValueError) as error:
            raise ClassificationStoreError("persisted projection is invalid") from error

    @staticmethod
    def _validate_target(connection: Connection, kind: EntityKind, target_id: object) -> None:
        table = {EntityKind.WORK: schema.works, EntityKind.EDITION: schema.editions}.get(kind)
        if table is None:
            raise ClassificationStoreError("classification target kind is unavailable")
        row = connection.execute(
            select(table.c.id).where(table.c.id == str(target_id))
        ).scalar_one_or_none()
        if row is None:
            raise ClassificationStoreError("classification target does not exist")

    @staticmethod
    def _validate_source_reference(
        connection: Connection,
        assertion: BookClassificationAssertion,
    ) -> None:
        lineage = assertion.lineage
        if lineage.source_reference_kind is ClassificationSourceReferenceKind.TOOL_RESULT:
            row = connection.execute(
                select(schema.tool_results.c.id).where(
                    schema.tool_results.c.id == lineage.source_reference,
                    schema.tool_results.c.target_kind == assertion.target_kind.value,
                    schema.tool_results.c.target_id == str(assertion.target_id),
                )
            ).scalar_one_or_none()
            if row is None:
                raise ClassificationStoreError("tool result does not bind to classification target")
        elif lineage.source_reference_kind is ClassificationSourceReferenceKind.REVIEW_DECISION:
            decisions = resolution_review_schema.review_decisions
            items = resolution_review_schema.review_items
            later_decisions = decisions.alias("later_decisions")
            row = connection.execute(
                select(decisions.c.id)
                .join(items, items.c.id == decisions.c.review_item_id)
                .join(
                    schema.classification_assertions,
                    schema.classification_assertions.c.id == items.c.candidate_id,
                )
                .where(
                    decisions.c.id == lineage.source_reference,
                    decisions.c.decision == ReviewDecisionValue.ACCEPT.value,
                    decisions.c.decision_compatibility_version
                    == CLASSIFICATION_DECISION_COMPATIBILITY,
                    decisions.c.decision_compatibility_version
                    == items.c.decision_compatibility_version,
                    decisions.c.evidence_fingerprint == items.c.evidence_fingerprint,
                    decisions.c.candidate_set_fingerprint == items.c.candidate_set_fingerprint,
                    ~exists(
                        select(later_decisions.c.id).where(
                            later_decisions.c.review_item_id == decisions.c.review_item_id,
                            later_decisions.c.sequence_no > decisions.c.sequence_no,
                        )
                    ),
                    items.c.review_type == ReviewType.CLASSIFICATION.value,
                    items.c.candidate_kind == ReviewCandidateKind.CLASSIFICATION_ASSERTION.value,
                    items.c.state == "DECIDED",
                    items.c.decision_compatibility_version
                    == CLASSIFICATION_DECISION_COMPATIBILITY,
                    items.c.subject_kind == assertion.target_kind.value,
                    items.c.subject_id == str(assertion.target_id),
                    schema.classification_assertions.c.target_kind == assertion.target_kind.value,
                    schema.classification_assertions.c.target_id == str(assertion.target_id),
                    schema.classification_assertions.c.dimension == assertion.dimension.value,
                    schema.classification_assertions.c.value == assertion.normalized_value,
                    schema.classification_assertions.c.taxonomy == assertion.taxonomy,
                )
            ).scalar_one_or_none()
            if row is None:
                raise ClassificationStoreError(
                    "accepted classification review decision does not bind to target"
                )

    @staticmethod
    def _ensure_no_key_collision(
        connection: Connection,
        assertion: BookClassificationAssertion,
    ) -> None:
        row = connection.execute(
            select(classification_schema.book_classification_assertion_lineage.c.assertion_id).where(
                classification_schema.book_classification_assertion_lineage.c.assertion_key
                == assertion.lineage.assertion_key
            )
        ).scalar_one_or_none()
        if row is not None and row != str(assertion.id):
            raise ClassificationStoreError("assertion key has different immutable content")

    @staticmethod
    def _existing_by_id(connection: Connection, assertion: BookClassificationAssertion) -> bool:
        raw = connection.execute(
            select(schema.classification_assertions).where(
                schema.classification_assertions.c.id == str(assertion.id)
            )
        ).mappings().one_or_none()
        lineage = connection.execute(
            select(classification_schema.book_classification_assertion_lineage).where(
                classification_schema.book_classification_assertion_lineage.c.assertion_id
                == str(assertion.id)
            )
        ).mappings().one_or_none()
        if raw is None and lineage is None:
            return False
        if raw is None or lineage is None:
            raise ClassificationStoreError("assertion identity collides with incomplete lineage")
        if dict(raw) != _assertion_row(assertion) or dict(lineage) != _lineage_row(assertion):
            raise ClassificationStoreError("assertion identity has different immutable content")
        return True


def _assertion_row(assertion: BookClassificationAssertion) -> dict[str, object]:
    return {
        "id": str(assertion.id),
        "target_kind": assertion.target_kind.value,
        "target_id": str(assertion.target_id),
        "dimension": assertion.dimension.value,
        "value": assertion.normalized_value,
        "taxonomy": assertion.taxonomy,
        "confidence": assertion.confidence,
        "source_kind": assertion.lineage.source_kind.value,
        "source_name": assertion.source_name,
        "source_version": assertion.source_version,
        "observed_at": datetime_to_db(assertion.observed_at),
    }


def _lineage_row(assertion: BookClassificationAssertion) -> dict[str, object]:
    lineage = assertion.lineage
    return {
        "assertion_id": str(assertion.id),
        "assertion_key": lineage.assertion_key,
        "assertion_profile_version": lineage.assertion_profile_version,
        "source_kind": lineage.source_kind.value,
        "source_reference_kind": lineage.source_reference_kind.value,
        "source_reference": lineage.source_reference,
        "priority_tier": lineage.priority_tier.value,
        "created_at": datetime_to_db(lineage.created_at),
    }


def _validate_page_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer between 1 and 500")
    if not 1 <= limit <= MAX_CLASSIFICATION_ASSERTION_PAGE:
        raise ValueError("limit must be between 1 and 500")


def _assertion_from_row(row: Mapping[str, Any]) -> BookClassificationAssertion:
    if row["source_kind"] != row["lineage_source_kind"]:
        raise ClassificationStoreError("profiled assertion source lineage is inconsistent")
    return BookClassificationAssertion(
        id=EntityId.parse(str(row["id"])),
        target_kind=EntityKind(str(row["target_kind"])),
        target_id=EntityId.parse(str(row["target_id"])),
        dimension=ClassificationDimension(str(row["dimension"])),
        normalized_value=str(row["value"]),
        taxonomy=str(row["taxonomy"]),
        confidence=None if row["confidence"] is None else float(row["confidence"]),
        source_name=str(row["source_name"]),
        source_version=str(row["source_version"]),
        observed_at=required_datetime_from_db(str(row["observed_at"])),
        lineage=BookClassificationAssertionLineage(
            assertion_key=str(row["assertion_key"]),
            assertion_profile_version=str(row["assertion_profile_version"]),
            source_kind=ClassificationSourceKind(str(row["lineage_source_kind"])),
            source_reference_kind=ClassificationSourceReferenceKind(
                str(row["source_reference_kind"])
            ),
            source_reference=str(row["source_reference"]),
            priority_tier=ClassificationPriorityTier(str(row["priority_tier"])),
            created_at=required_datetime_from_db(str(row["created_at"])),
        ),
    )


def _projection_created_at() -> datetime:
    return datetime.now(UTC)


def _projection_value_rows(projection: BookClassificationProjection) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for facet in projection.facets:
        if facet.status is ClassificationFacetStatus.PROJECTED:
            rows.extend(
                {
                    "projection_id": str(projection.id),
                    "dimension": facet.dimension.value,
                    "ordinal": value.ordinal,
                    "taxonomy": value.taxonomy,
                    "normalized_value": value.normalized_value,
                    "facet_status": facet.status.value,
                    "conflict_code": None,
                }
                for value in facet.values
            )
        else:
            rows.append(
                {
                    "projection_id": str(projection.id),
                    "dimension": facet.dimension.value,
                    "ordinal": 0,
                    "taxonomy": None,
                    "normalized_value": None,
                    "facet_status": facet.status.value,
                    "conflict_code": (
                        None if facet.conflict_code is None else facet.conflict_code.value
                    ),
                }
            )
    return rows


def _projection_link_rows(projection: BookClassificationProjection) -> list[dict[str, object]]:
    return [
        {
            "projection_id": str(projection.id),
            "assertion_id": str(link.assertion_id),
            "link_role": link.role.value,
            "conflict_code": None if link.conflict_code is None else link.conflict_code.value,
        }
        for link in projection.assertion_links
    ]


def _projection_facets_from_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[BookClassificationProjectionFacet, ...]:
    grouped: dict[ClassificationDimension, list[Mapping[str, Any]]] = {
        dimension: [] for dimension in ClassificationDimension
    }
    for row in rows:
        grouped[ClassificationDimension(str(row["dimension"]))].append(row)
    facets: list[BookClassificationProjectionFacet] = []
    for dimension in ClassificationDimension:
        dimension_rows = grouped[dimension]
        if not dimension_rows:
            raise ValueError("projection is missing a canonical facet")
        status = ClassificationFacetStatus(str(dimension_rows[0]["facet_status"]))
        conflict = dimension_rows[0]["conflict_code"]
        if any(
            ClassificationFacetStatus(str(item["facet_status"])) is not status
            or item["conflict_code"] != conflict
            for item in dimension_rows
        ):
            raise ValueError("projection facet rows disagree")
        values = tuple(
            BookClassificationProjectionValue(
                ordinal=int(item["ordinal"]),
                taxonomy=str(item["taxonomy"]),
                normalized_value=str(item["normalized_value"]),
            )
            for item in dimension_rows
            if item["taxonomy"] is not None and item["normalized_value"] is not None
        )
        facets.append(
            BookClassificationProjectionFacet(
                dimension=dimension,
                status=status,
                values=values,
                conflict_code=(
                    None
                    if conflict is None
                    else ClassificationProjectionConflictCode(str(conflict))
                ),
            )
        )
    return tuple(facets)
