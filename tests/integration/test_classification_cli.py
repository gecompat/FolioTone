"""Synthetic, path-free read-only classification CLI coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from foliotone.classification.contracts import (
    BookClassificationAssertion,
    ClassificationDimension,
    ClassificationSourceKind,
)
from foliotone.cli.main import main
from foliotone.core import EntityId, EntityKind, Work
from foliotone.persistence import classification_schema, create_sqlite_engine, repository
from foliotone.persistence.classification import SQLiteClassificationStore
from foliotone.workflows.classification import (
    BookClassificationProjectionWorkflow,
    ClassificationFacetReport,
    ClassificationReadOnlyReport,
    ClassificationReportCounts,
)

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _seed(database: Path) -> tuple[Work, EntityId]:
    engine = create_sqlite_engine(database)
    work = Work(id=EntityId.new())
    repository(engine, Work).save(work)
    store = SQLiteClassificationStore(engine)
    assertion = BookClassificationAssertion.create(
        target_kind=EntityKind.WORK,
        target_id=work.id,
        dimension=ClassificationDimension.TOPIC,
        value="Synthetic Topic",
        taxonomy="synthetic",
        confidence=0.5,
        source_name="synthetic",
        source_version="v1",
        source_kind=ClassificationSourceKind.LOCAL_DERIVED,
        source_reference="a" * 64,
        observed_at=NOW,
        created_at=NOW,
    )
    store.create_or_get_many((assertion,))
    projection = BookClassificationProjectionWorkflow(store).reproject(EntityKind.WORK, work.id)
    engine.dispose()
    return work, projection.projection.id


def test_classification_report_json_is_bounded_and_path_free(head_database: Path, capsys) -> None:
    work, projection_id = _seed(head_database)
    assert main(
        [
            "ebook-classification-report",
            "--target-kind",
            "WORK",
            "--target-id",
            str(work.id),
            "--projection-id",
            str(projection_id),
            "--database",
            str(head_database),
            "--output",
            "json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "PROJECTED"
    assert payload["truncated"] is False
    assert len(payload["facets"]) == 7
    assert payload["counts"]["projected_values"] == 1
    rendered = json.dumps(payload)
    assert "Synthetic Topic" not in rendered
    assert "synthetic" not in rendered
    assert str(head_database) not in rendered


def test_classification_report_fails_closed_for_missing_or_invalid_state(
    head_database: Path, capsys
) -> None:
    missing = EntityId.new()
    assert main(
        [
            "ebook-classification-report",
            "--target-kind",
            "WORK",
            "--target-id",
            str(missing),
            "--database",
            str(head_database),
            "--output",
            "json",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "ebook-classification-report",
        "error": {"code": "CLASSIFICATION_UNAVAILABLE"},
        "ok": False,
        "schema_version": 1,
    }


def test_classification_report_fails_closed_on_missing_facet_row(
    head_database: Path, capsys
) -> None:
    work, projection_id = _seed(head_database)
    engine = create_sqlite_engine(head_database)
    with engine.begin() as connection:
        connection.execute(
            classification_schema.book_classification_projection_values.delete().where(
                classification_schema.book_classification_projection_values.c.projection_id
                == str(projection_id),
                classification_schema.book_classification_projection_values.c.dimension == "domain",
            )
        )
    engine.dispose()

    assert main(
        [
            "ebook-classification-report",
            "--target-kind",
            "WORK",
            "--target-id",
            str(work.id),
            "--projection-id",
            str(projection_id),
            "--database",
            str(head_database),
            "--output",
            "json",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "CLASSIFICATION_UNAVAILABLE"


def test_classification_report_dtos_reject_invalid_counts_and_order() -> None:
    import pytest

    with pytest.raises(ValueError):
        ClassificationFacetReport("topic", "EMPTY", 1, None)
    with pytest.raises(ValueError):
        ClassificationFacetReport("topic", "PROJECTED", 0, None)
    with pytest.raises(ValueError):
        ClassificationReportCounts(7, 1, 2, 1, 0, 0)
    facets = tuple(
        ClassificationFacetReport(dimension, "EMPTY", 0, None)
        for dimension in ("domain", "genre", "subgenre", "topic", "audience", "language", "form")
    )
    with pytest.raises(ValueError):
        ClassificationReadOnlyReport(
            "WORK",
            "not-an-id",
            "not-an-id",
            "book-classification-assertion/v1",
            "book-classification-projection/v1",
            "EMPTY",
            facets,
            ClassificationReportCounts(7, 0, 0, 0, 0, 0),
        )
