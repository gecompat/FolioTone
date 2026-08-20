"""Synthetic integration coverage for ADR-0037's insert-only assertion store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, func, select

from foliotone.classification.contracts import (
    BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    BookClassificationAssertion,
    BookClassificationAssertionLineage,
    ClassificationDimension,
    ClassificationPriorityTier,
    ClassificationSourceKind,
    ClassificationSourceReferenceKind,
    classification_assertion_id,
    classification_assertion_key,
)
from foliotone.core import EntityId, EntityKind, Work
from foliotone.persistence import (
    classification_schema,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
)
from foliotone.persistence import resolution_review_schema as rr_schema
from foliotone.persistence.classification import ClassificationStoreError, SQLiteClassificationStore

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _store(tmp_path: Path) -> tuple[SQLiteClassificationStore, Engine, Work]:
    database = tmp_path / "classification-store.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    work = Work(id=EntityId.new())
    repository(engine, Work).save(work)
    return SQLiteClassificationStore(engine), engine, work


def _assertion(
    work: Work,
    *,
    value: str = "Synthetic Topic",
    source_reference: str = "a" * 64,
    source_kind: ClassificationSourceKind = ClassificationSourceKind.LOCAL_DERIVED,
) -> BookClassificationAssertion:
    return BookClassificationAssertion.create(
        target_kind=EntityKind.WORK,
        target_id=work.id,
        dimension=ClassificationDimension.TOPIC,
        value=value,
        taxonomy="synthetic.taxonomy",
        confidence=0.7,
        source_name="synthetic-classifier",
        source_version="v1",
        source_kind=source_kind,
        source_reference=source_reference,
        observed_at=NOW,
        created_at=NOW,
    )


def test_contract_literals_canonical_key_and_uuid_are_deterministic() -> None:
    assert {item.value for item in ClassificationDimension} == {
        "domain", "genre", "subgenre", "topic", "audience", "language", "form"
    }
    assert {item.value for item in ClassificationSourceKind} == {
        "LOCAL_DERIVED", "TOOL_PROVIDER", "KNOWLEDGE_PROVIDER", "USER_CONFIRMED"
    }
    assert {item.value for item in ClassificationSourceReferenceKind} == {
        "LOCAL_RULE_RUN", "TOOL_RESULT", "PROVIDER_MAPPING_OUTPUT", "REVIEW_DECISION"
    }
    assert {item.value for item in ClassificationPriorityTier} == {"AUTOMATED", "USER_CONFIRMED"}
    key = classification_assertion_key(
        target_kind=EntityKind.WORK,
        target_id=EntityId.parse("00000000-0000-0000-0000-000000000001"),
        dimension=ClassificationDimension.TOPIC,
        normalized_value="cafe\u0301",
        taxonomy="synthetic",
        assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        source_kind=ClassificationSourceKind.LOCAL_DERIVED,
        source_reference="a" * 64,
    )
    assert key == classification_assertion_key(
        target_kind=EntityKind.WORK,
        target_id=EntityId.parse("00000000-0000-0000-0000-000000000001"),
        dimension=ClassificationDimension.TOPIC,
        normalized_value="café",
        taxonomy="synthetic",
        assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        source_kind=ClassificationSourceKind.LOCAL_DERIVED,
        source_reference="a" * 64,
    )
    assert classification_assertion_id(key) == classification_assertion_id(key)


@pytest.mark.parametrize("source_name", ("C:private", ".", "private\x00label"))
def test_profiled_assertion_rejects_private_source_labels_and_bool_confidence(
    source_name: str,
) -> None:
    with pytest.raises(ValueError, match="path-free"):
        BookClassificationAssertion.create(
            target_kind=EntityKind.WORK,
            target_id=EntityId.new(),
            dimension=ClassificationDimension.TOPIC,
            value="synthetic",
            taxonomy="synthetic",
            confidence=0.5,
            source_name=source_name,
            source_version="v1",
            source_kind=ClassificationSourceKind.LOCAL_DERIVED,
            source_reference="a" * 64,
            observed_at=NOW,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="finite number"):
        BookClassificationAssertion.create(
            target_kind=EntityKind.WORK,
            target_id=EntityId.new(),
            dimension=ClassificationDimension.TOPIC,
            value="synthetic",
            taxonomy="synthetic",
            confidence=True,
            source_name="synthetic",
            source_version="v1",
            source_kind=ClassificationSourceKind.LOCAL_DERIVED,
            source_reference="a" * 64,
            observed_at=NOW,
            created_at=NOW,
        )


def test_assertion_batch_rejects_after_bounded_materialization() -> None:
    consumed = 0

    def assertions():
        nonlocal consumed
        for _ in range(10_000):
            consumed += 1
            yield object()

    store = SQLiteClassificationStore(None)  # type: ignore[arg-type]
    with pytest.raises(ClassificationStoreError, match="exceeds the bound"):
        store.create_or_get_many(assertions())  # type: ignore[arg-type]
    assert consumed == 257


def test_contract_rejects_invalid_lineage_and_path_like_labels() -> None:
    with pytest.raises(ValueError, match="source kind and source reference kind"):
        BookClassificationAssertionLineage(
            assertion_key="a" * 64,
            assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
            source_kind=ClassificationSourceKind.LOCAL_DERIVED,
            source_reference_kind=ClassificationSourceReferenceKind.TOOL_RESULT,
            source_reference="00000000-0000-0000-0000-000000000001",
            priority_tier=ClassificationPriorityTier.AUTOMATED,
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="path-free"):
        BookClassificationAssertion.create(
            target_kind=EntityKind.WORK,
            target_id=EntityId.new(),
            dimension=ClassificationDimension.TOPIC,
            value="synthetic",
            taxonomy="synthetic",
            confidence=None,
            source_name="C:\\private",
            source_version="v1",
            source_kind=ClassificationSourceKind.LOCAL_DERIVED,
            source_reference="a" * 64,
            observed_at=NOW,
            created_at=NOW,
        )


def test_exact_retry_is_noop_and_provider_evidence_remains_separate(tmp_path: Path) -> None:
    store, engine, work = _store(tmp_path)
    first = _assertion(work, value="Databases", source_reference="a" * 64)
    provider_one = _assertion(
        work,
        value="Fiction",
        source_reference="b" * 64,
        source_kind=ClassificationSourceKind.KNOWLEDGE_PROVIDER,
    )
    provider_two = _assertion(
        work,
        value="Computer Science",
        source_reference="c" * 64,
        source_kind=ClassificationSourceKind.KNOWLEDGE_PROVIDER,
    )

    assert store.create_or_get(first) == first
    assert store.create_or_get(first) == first
    assert store.create_or_get_many((provider_one, provider_two)) == (provider_one, provider_two)
    with engine.connect() as connection:
        assertion_count = connection.execute(
            select(func.count()).select_from(schema.classification_assertions)
        ).scalar_one()
        assert assertion_count == 3
        assert (
            connection.execute(
                select(func.count()).select_from(
                    classification_schema.book_classification_assertion_lineage
                )
            ).scalar_one()
            == 3
        )
    engine.dispose()


def test_different_content_under_existing_identity_fails_closed(tmp_path: Path) -> None:
    store, engine, work = _store(tmp_path)
    assertion = _assertion(work)
    store.create_or_get(assertion)
    with engine.begin() as connection:
        connection.execute(
            schema.classification_assertions.update()
            .where(schema.classification_assertions.c.id == str(assertion.id))
            .values(value="tampered")
        )
    with pytest.raises(ClassificationStoreError, match="different immutable content"):
        store.create_or_get(assertion)
    engine.dispose()


def test_target_and_local_source_references_are_validated_in_the_same_transaction(
    tmp_path: Path,
) -> None:
    store, engine, work = _store(tmp_path)
    missing_target = BookClassificationAssertion.create(
        target_kind=EntityKind.WORK,
        target_id=EntityId.new(),
        dimension=ClassificationDimension.TOPIC,
        value="synthetic",
        taxonomy="synthetic",
        confidence=None,
        source_name="synthetic",
        source_version="v1",
        source_kind=ClassificationSourceKind.LOCAL_DERIVED,
        source_reference="d" * 64,
        observed_at=NOW,
        created_at=NOW,
    )
    with pytest.raises(ClassificationStoreError, match="target does not exist"):
        store.create_or_get(missing_target)
    valid = _assertion(work, source_reference="e" * 64)
    with pytest.raises(RuntimeError, match="injected lineage failure"):
        with _raise_on_lineage_insert(engine):
            store.create_or_get(valid)
    with engine.connect() as connection:
        assertion_count = connection.execute(
            select(func.count()).select_from(schema.classification_assertions)
        ).scalar_one()
        assert assertion_count == 0
    engine.dispose()


def test_tool_result_and_review_decision_must_bind_to_the_same_target(tmp_path: Path) -> None:
    store, engine, work = _store(tmp_path)
    other = Work(id=EntityId.new())
    repository(engine, Work).save(other)
    reviewed_evidence = store.create_or_get(_assertion(work, source_reference="f" * 64))
    tool_result_id = EntityId.new()
    review_decision_id = EntityId.new()
    with engine.begin() as connection:
        execution_id = EntityId.new()
        connection.execute(
            schema.tool_executions.insert().values(
                id=str(execution_id),
                provider_id="synthetic-tool",
                tool_version="v1",
                adapter_version="v1",
                capability="READ_METADATA",
                input_identity="synthetic-input",
                started_at=NOW.isoformat(),
                finished_at=NOW.isoformat(),
                status="SUCCEEDED",
                exit_code=0,
                config_identity=None,
                error_summary=None,
            )
        )
        connection.execute(
            schema.tool_results.insert().values(
                id=str(tool_result_id),
                execution_id=str(execution_id),
                result_type="classification",
                target_kind=EntityKind.WORK.value,
                target_id=str(other.id),
                key="topic",
                value="synthetic",
                confidence=None,
                explanation=None,
            )
        )
        item_id = EntityId.new()
        connection.execute(
            rr_schema.review_items.insert().values(
                id=str(item_id),
                review_type="CLASSIFICATION",
                subject_kind=EntityKind.WORK.value,
                subject_id=str(other.id),
                candidate_kind="CLASSIFICATION_ASSERTION",
                candidate_id=str(EntityId.new()),
                producer_name="synthetic-review",
                producer_version="v1",
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                evidence_fingerprint="1" * 64,
                candidate_set_fingerprint="2" * 64,
                state="DECIDED",
                created_at=NOW.isoformat(),
            )
        )
        connection.execute(
            rr_schema.review_decisions.insert().values(
                id=str(review_decision_id),
                review_item_id=str(item_id),
                sequence_no=1,
                decision="ACCEPT",
                decision_reason="SYNTHETIC",
                evidence_fingerprint="1" * 64,
                candidate_set_fingerprint="2" * 64,
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )
    for source_kind, reference in (
        (ClassificationSourceKind.TOOL_PROVIDER, str(tool_result_id)),
        (ClassificationSourceKind.USER_CONFIRMED, str(review_decision_id)),
    ):
        with pytest.raises(ClassificationStoreError, match="does not bind to"):
            store.create_or_get(
                _assertion(
                    work,
                    source_kind=source_kind,
                    source_reference=reference,
                )
            )
    matching_tool_result_id = EntityId.new()
    matching_review_decision_id = EntityId.new()
    with engine.begin() as connection:
        matching_execution_id = EntityId.new()
        connection.execute(
            schema.tool_executions.insert().values(
                id=str(matching_execution_id),
                provider_id="synthetic-tool",
                tool_version="v1",
                adapter_version="v1",
                capability="READ_METADATA",
                input_identity="matching-synthetic-input",
                started_at=NOW.isoformat(),
                finished_at=NOW.isoformat(),
                status="SUCCEEDED",
                exit_code=0,
                config_identity=None,
                error_summary=None,
            )
        )
        connection.execute(
            schema.tool_results.insert().values(
                id=str(matching_tool_result_id),
                execution_id=str(matching_execution_id),
                result_type="classification",
                target_kind=EntityKind.WORK.value,
                target_id=str(work.id),
                key="topic",
                value="synthetic",
                confidence=None,
                explanation=None,
            )
        )
        matching_item_id = EntityId.new()
        connection.execute(
            rr_schema.review_items.insert().values(
                id=str(matching_item_id),
                review_type="CLASSIFICATION",
                subject_kind=EntityKind.WORK.value,
                subject_id=str(work.id),
                candidate_kind="CLASSIFICATION_ASSERTION",
                candidate_id=str(reviewed_evidence.id),
                producer_name="synthetic-review",
                producer_version="v1",
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                evidence_fingerprint="3" * 64,
                candidate_set_fingerprint="4" * 64,
                state="DECIDED",
                created_at=NOW.isoformat(),
            )
        )
        connection.execute(
            rr_schema.review_decisions.insert().values(
                id=str(matching_review_decision_id),
                review_item_id=str(matching_item_id),
                sequence_no=1,
                decision="ACCEPT",
                decision_reason="SYNTHETIC",
                evidence_fingerprint="3" * 64,
                candidate_set_fingerprint="4" * 64,
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )
    assert store.create_or_get(
        _assertion(
            work,
            source_kind=ClassificationSourceKind.TOOL_PROVIDER,
            source_reference=str(matching_tool_result_id),
        )
    ).target_id == work.id
    with pytest.raises(ClassificationStoreError, match="does not bind to target"):
        store.create_or_get(
            _assertion(
                work,
                value="different synthetic topic",
                source_kind=ClassificationSourceKind.USER_CONFIRMED,
                source_reference=str(matching_review_decision_id),
            )
        )
    assert store.create_or_get(
        _assertion(
            work,
            source_kind=ClassificationSourceKind.USER_CONFIRMED,
            source_reference=str(matching_review_decision_id),
        )
    ).target_id == work.id
    with engine.begin() as connection:
        connection.execute(
            rr_schema.review_decisions.insert().values(
                id=str(EntityId.new()),
                review_item_id=str(matching_item_id),
                sequence_no=2,
                decision="REJECT",
                decision_reason="SYNTHETIC_REJECT",
                evidence_fingerprint="3" * 64,
                candidate_set_fingerprint="4" * 64,
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )
    with pytest.raises(ClassificationStoreError, match="does not bind to target"):
        store.create_or_get(
            _assertion(
                work,
                source_kind=ClassificationSourceKind.USER_CONFIRMED,
                source_reference=str(matching_review_decision_id),
            )
        )
    with engine.begin() as connection:
        connection.execute(
            rr_schema.review_decisions.insert().values(
                id=str(EntityId.new()),
                review_item_id=str(matching_item_id),
                sequence_no=3,
                decision="DEFER",
                decision_reason="SYNTHETIC_DEFER",
                evidence_fingerprint="3" * 64,
                candidate_set_fingerprint="4" * 64,
                decision_compatibility_version="book-classification-decision-compatibility/v1",
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )
    with pytest.raises(ClassificationStoreError, match="does not bind to target"):
        store.create_or_get(
            _assertion(
                work,
                source_kind=ClassificationSourceKind.USER_CONFIRMED,
                source_reference=str(matching_review_decision_id),
            )
        )
    engine.dispose()


class _raise_on_lineage_insert:
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
        if "INSERT INTO book_classification_assertion_lineage" in statement:
            raise RuntimeError("injected lineage failure")
