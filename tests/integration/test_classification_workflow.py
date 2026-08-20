"""Synthetic integration coverage for ADR-0037 reprojection snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, func, select

from foliotone.classification.contracts import (
    BookClassificationAssertion,
    ClassificationDimension,
    ClassificationSourceKind,
)
from foliotone.classification.projection import (
    ClassificationProjectionConflictCode,
    ClassificationProjectionLinkRole,
    ClassificationProjectionStatus,
)
from foliotone.core import EntityId, EntityKind, Work
from foliotone.persistence import classification_schema, create_sqlite_engine, repository, schema
from foliotone.persistence.classification import ClassificationStoreError, SQLiteClassificationStore
from foliotone.workflows.classification import (
    BookClassificationProjectionWorkflow,
    ClassificationWorkflowError,
)

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _workflow(
    database: Path,
) -> tuple[BookClassificationProjectionWorkflow, SQLiteClassificationStore, Engine, Work]:
    engine = create_sqlite_engine(database)
    work = Work(id=EntityId.new())
    repository(engine, Work).save(work)
    store = SQLiteClassificationStore(engine)
    return BookClassificationProjectionWorkflow(store), store, engine, work


def _assertion(
    work: Work,
    *,
    reference: str,
    value: str = "Synthetic topic",
    dimension: ClassificationDimension = ClassificationDimension.TOPIC,
    taxonomy: str = "synthetic",
) -> BookClassificationAssertion:
    return BookClassificationAssertion.create(
        target_kind=EntityKind.WORK,
        target_id=work.id,
        dimension=dimension,
        value=value,
        taxonomy=taxonomy,
        confidence=0.5,
        source_name="synthetic-classifier",
        source_version="v1",
        source_kind=ClassificationSourceKind.LOCAL_DERIVED,
        source_reference=reference,
        observed_at=NOW,
        created_at=NOW,
    )


def test_reprojection_is_deterministic_noop_and_losslessly_rehydrated(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    assertions = (
        _assertion(work, reference="a" * 64, value="Beta", taxonomy="zeta"),
        _assertion(work, reference="b" * 64, value="Alpha", taxonomy="alpha"),
    )
    store.create_or_get_many(assertions)

    first = workflow.reproject(EntityKind.WORK, work.id)
    second = workflow.reproject(EntityKind.WORK, work.id)

    assert first.created is True
    assert second.created is False
    assert second.projection == first.projection
    values = tuple(
        (value.taxonomy, value.normalized_value, value.ordinal)
        for value in first.projection.facets[3].values
    )
    assert values == (
        ("alpha", "alpha", 0),
        ("zeta", "beta", 1),
    )
    assert store.get_projection(first.projection.id) == first.projection
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(classification_schema.book_classification_projections)
        ).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(schema.classification_assertions)
        ).scalar_one() == 2
    engine.dispose()


def test_new_input_creates_new_snapshot_without_mutating_source_rows(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    initial = _assertion(work, reference="a" * 64)
    store.create_or_get(initial)
    first = workflow.reproject(EntityKind.WORK, work.id)
    added = _assertion(work, reference="b" * 64, value="Another topic")
    store.create_or_get(added)

    second = workflow.reproject(EntityKind.WORK, work.id)

    assert second.created is True
    assert second.projection.id != first.projection.id
    assert second.projection.input_fingerprint != first.projection.input_fingerprint
    with engine.connect() as connection:
        assert connection.execute(
            select(schema.classification_assertions.c.value)
            .where(schema.classification_assertions.c.id == str(initial.id))
        ).scalar_one() == initial.normalized_value
        assert connection.execute(
            select(func.count()).select_from(classification_schema.book_classification_projections)
        ).scalar_one() == 2
    engine.dispose()


def test_conflict_snapshot_preserves_exact_ordered_links(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    left = _assertion(
        work,
        reference="a" * 64,
        dimension=ClassificationDimension.DOMAIN,
        value="Fiction",
    )
    right = _assertion(
        work,
        reference="b" * 64,
        dimension=ClassificationDimension.DOMAIN,
        value="Reference",
    )
    store.create_or_get_many((left, right))

    outcome = workflow.reproject(EntityKind.WORK, work.id)

    assert outcome.projection.status is ClassificationProjectionStatus.REVIEW_REQUIRED
    domain = outcome.projection.facets[0]
    assert domain.conflict_code is ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES
    assert tuple(link.assertion_key for link in outcome.projection.assertion_links) == tuple(
        sorted((left.lineage.assertion_key, right.lineage.assertion_key))
    )
    assert {link.role for link in outcome.projection.assertion_links} == {
        ClassificationProjectionLinkRole.CONFLICTING
    }
    assert store.get_projection(outcome.projection.id) == outcome.projection
    engine.dispose()


def test_projection_insert_rolls_back_and_profile_changes_fail_closed(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    store.create_or_get(_assertion(work, reference="a" * 64))
    with _raise_on_projection_values(engine):
        with pytest.raises(ClassificationWorkflowError, match="failed closed"):
            workflow.reproject(EntityKind.WORK, work.id)
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(classification_schema.book_classification_projections)
        ).scalar_one() == 0
    with pytest.raises(ClassificationWorkflowError, match="unsupported projection profile"):
        workflow.reproject(
            EntityKind.WORK, work.id, projection_profile_version="book-classification-projection/v2"
        )
    engine.dispose()


def test_existing_projection_with_divergent_rows_fails_closed(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    store.create_or_get(_assertion(work, reference="a" * 64))
    outcome = workflow.reproject(EntityKind.WORK, work.id)
    with engine.begin() as connection:
        connection.execute(
            classification_schema.book_classification_projection_values.update()
            .where(
                classification_schema.book_classification_projection_values.c.projection_id
                == str(outcome.projection.id)
            )
            .where(
                classification_schema.book_classification_projection_values.c.dimension == "topic"
            )
            .values(normalized_value="tampered")
        )
    with pytest.raises(ClassificationWorkflowError, match="failed closed"):
        workflow.reproject(EntityKind.WORK, work.id)
    engine.dispose()


def test_manipulated_link_role_and_bounded_child_reads_fail_closed(head_database: Path) -> None:
    workflow, store, engine, work = _workflow(head_database)
    store.create_or_get(_assertion(work, reference="a" * 64))
    outcome = workflow.reproject(EntityKind.WORK, work.id)
    with engine.begin() as connection:
        connection.execute(
            classification_schema.book_classification_projection_assertions.update()
            .where(
                classification_schema.book_classification_projection_assertions.c.projection_id
                == str(outcome.projection.id)
            )
            .values(link_role=ClassificationProjectionLinkRole.CONSIDERED.value)
        )
    with pytest.raises(ClassificationWorkflowError, match="failed closed"):
        workflow.reproject(EntityKind.WORK, work.id)

    engine.dispose()
    workflow, store, engine, work = _workflow(head_database)
    store.create_or_get(_assertion(work, reference="b" * 64))
    outcome = workflow.reproject(EntityKind.WORK, work.id)
    with engine.begin() as connection:
        connection.execute(
            classification_schema.book_classification_projection_values.insert(),
            [
                {
                    "projection_id": str(outcome.projection.id),
                    "dimension": ClassificationDimension.TOPIC.value,
                    "ordinal": ordinal,
                    "taxonomy": "synthetic",
                    "normalized_value": f"overflow-{ordinal}",
                    "facet_status": "PROJECTED",
                    "conflict_code": None,
                }
                for ordinal in range(1, 76)
            ],
        )
    with pytest.raises(ClassificationStoreError, match="values exceed the bound"):
        store.get_projection(outcome.projection.id)
    engine.dispose()


class _raise_on_projection_values:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __enter__(self) -> None:
        event.listen(self._engine, "before_cursor_execute", self._raise)

    def __exit__(self, *_: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._raise)

    @staticmethod
    def _raise(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if "INSERT INTO book_classification_projection_values" in statement:
            raise RuntimeError("injected projection value failure")
