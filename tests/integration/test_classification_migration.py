"""Synthetic migration coverage for ADR-0037 book classification persistence."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from foliotone.persistence import (
    alembic_config,
    create_sqlite_engine,
    migrate,
)
from foliotone.persistence import (
    classification_schema as classification,
)

NOW = datetime(2026, 8, 20, tzinfo=UTC)
ASSERTION_ID = "00000000-0000-0000-0000-000000000101"
PROJECTION_ID = "00000000-0000-0000-0000-000000000102"


def _legacy_assertion(engine: Engine, assertion_id: str = ASSERTION_ID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO classification_assertions ("
                "id, target_kind, target_id, dimension, value, taxonomy, confidence, "
                "source_kind, source_name, source_version, observed_at"
                ") VALUES (:id, 'WORK', :target_id, 'topic', 'synthetic topic', "
                "'synthetic', 0.5, 'classification', 'synthetic-source', 'v1', :observed_at)"
            ),
            {
                "id": assertion_id,
                "target_id": "00000000-0000-0000-0000-000000000103",
                "observed_at": NOW.isoformat(),
            },
        )


def _valid_lineage(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            classification.book_classification_assertion_lineage.insert().values(
                assertion_id=ASSERTION_ID,
                assertion_key="a" * 64,
                assertion_profile_version="book-classification-assertion/v1",
                source_kind="LOCAL_DERIVED",
                source_reference_kind="LOCAL_RULE_RUN",
                source_reference="b" * 64,
                priority_tier="AUTOMATED",
                created_at=NOW,
            )
        )


def _valid_projection(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            classification.book_classification_projections.insert().values(
                id=PROJECTION_ID,
                target_kind="WORK",
                target_id="00000000-0000-0000-0000-000000000103",
                assertion_profile_version="book-classification-assertion/v1",
                projection_profile_version="book-classification-projection/v1",
                input_fingerprint="c" * 64,
                status="PROJECTED",
                created_at=NOW,
            )
        )


def test_migration_0018_upgrades_0017_without_reprofiling_legacy_assertions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "classification-upgrade.db"
    migrate(path, "0017_provider_cache_schema")
    legacy = create_sqlite_engine(path)
    _legacy_assertion(legacy)
    assert (
        classification.book_classification_assertion_lineage.name
        not in inspect(legacy).get_table_names()
    )
    legacy.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    with upgraded.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        legacy_count = connection.execute(
            text("SELECT count(*) FROM classification_assertions")
        ).scalar_one()
        lineage_count = connection.execute(
            text("SELECT count(*) FROM book_classification_assertion_lineage")
        ).scalar_one()
    upgraded.dispose()

    assert revision == "0018_book_classification_projection"
    assert legacy_count == 1
    assert lineage_count == 0


def test_migration_0018_empty_database_has_exact_schema_and_lookup_indexes(tmp_path: Path) -> None:
    path = tmp_path / "classification-empty.db"
    migrate(path)
    engine = create_sqlite_engine(path)
    inspector = inspect(engine)

    assert {table.name for table in classification.CLASSIFICATION_PROJECTION_TABLES} <= set(
        inspector.get_table_names()
    )
    assert {
        "ix_book_classification_lineage_profile_assertion",
        "ix_book_classification_projections_target_profile_created",
    } <= {
        str(index["name"])
        for table in (
            classification.book_classification_assertion_lineage,
            classification.book_classification_projections,
        )
        for index in inspector.get_indexes(table.name)
    }
    assert {"classification_assertions"} == {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys(
            classification.book_classification_assertion_lineage.name
        )
    }
    assert {"book_classification_projections"} == {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys(
            classification.book_classification_projection_values.name
        )
    }
    assert {"book_classification_projections", "book_classification_assertion_lineage"} == {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys(
            classification.book_classification_projection_assertions.name
        )
    }
    assert "uq_book_classification_lineage_assertion_key" in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            classification.book_classification_assertion_lineage.name
        )
    }
    assert "uq_book_classification_projection_identity" in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            classification.book_classification_projections.name
        )
    }
    with engine.connect() as connection:
        query_plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT id FROM classification_assertions "
                "WHERE target_kind = :target_kind AND target_id = :target_id "
                "ORDER BY id"
            ),
            {
                "target_kind": "WORK",
                "target_id": "00000000-0000-0000-0000-000000000103",
            },
        ).all()
    assert any("ix_classification_assertions_target_id" in str(row[-1]) for row in query_plan)
    engine.dispose()


def test_migration_0018_enforces_lineage_projection_and_link_shapes(tmp_path: Path) -> None:
    path = tmp_path / "classification-constraints.db"
    migrate(path)
    engine = create_sqlite_engine(path)
    _legacy_assertion(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                classification.book_classification_assertion_lineage.insert().values(
                    assertion_id=ASSERTION_ID,
                    assertion_key="a" * 64,
                    assertion_profile_version="book-classification-assertion/v1",
                    source_kind="LOCAL_DERIVED",
                    source_reference_kind="TOOL_RESULT",
                    source_reference="b" * 64,
                    priority_tier="AUTOMATED",
                    created_at=NOW,
                )
            )
    _valid_lineage(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                classification.book_classification_projections.insert().values(
                    id=PROJECTION_ID,
                    target_kind="FILE",
                    target_id="00000000-0000-0000-0000-000000000103",
                    assertion_profile_version="book-classification-assertion/v1",
                    projection_profile_version="book-classification-projection/v1",
                    input_fingerprint="c" * 64,
                    status="PROJECTED",
                    created_at=NOW,
                )
            )
    _valid_projection(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                classification.book_classification_projection_values.insert().values(
                    projection_id=PROJECTION_ID,
                    dimension="domain",
                    ordinal=0,
                    taxonomy=None,
                    normalized_value=None,
                    facet_status="PROJECTED",
                    conflict_code=None,
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                classification.book_classification_projection_assertions.insert().values(
                    projection_id=PROJECTION_ID,
                    assertion_id="00000000-0000-0000-0000-000000000104",
                    link_role="SELECTED",
                    conflict_code=None,
                )
            )
    engine.dispose()


def test_migration_0018_empty_downgrade_is_safe(tmp_path: Path) -> None:
    path = tmp_path / "classification-empty-downgrade.db"
    migrate(path)

    command.downgrade(alembic_config(path), "0017_provider_cache_schema")
    engine = create_sqlite_engine(path)
    assert (
        classification.book_classification_projections.name not in inspect(engine).get_table_names()
    )
    assert "ix_classification_assertions_target_id" not in {
        str(index["name"])
        for index in inspect(engine).get_indexes("classification_assertions")
    }
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0017_provider_cache_schema"
        )
    engine.dispose()


def test_migration_0018_populated_downgrade_is_guarded(tmp_path: Path) -> None:
    path = tmp_path / "classification-populated-downgrade.db"
    migrate(path)
    engine = create_sqlite_engine(path)
    _legacy_assertion(engine)
    _valid_lineage(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="book-classification data prevents migration downgrade"):
        command.downgrade(alembic_config(path), "0017_provider_cache_schema")
