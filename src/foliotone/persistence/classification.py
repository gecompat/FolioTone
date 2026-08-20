"""Atomic insert-only persistence for profiled book classification assertions."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice

from sqlalchemy import Engine, exists, insert, select
from sqlalchemy.engine import Connection

from foliotone.classification.contracts import (
    BookClassificationAssertion,
    ClassificationSourceReferenceKind,
)
from foliotone.core import EntityKind, ReviewCandidateKind, ReviewDecisionValue, ReviewType
from foliotone.persistence import classification_schema, resolution_review_schema, schema
from foliotone.persistence._mapping import datetime_to_db

MAX_CLASSIFICATION_ASSERTION_BATCH = 256
CLASSIFICATION_DECISION_COMPATIBILITY = "book-classification-decision-compatibility/v1"


class ClassificationStoreError(RuntimeError):
    """A path-free immutable classification persistence failure."""


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
