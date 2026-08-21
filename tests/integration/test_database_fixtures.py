"""Regression coverage for fast isolated SQLite test databases."""

import pytest
from sqlalchemy import text

from foliotone.persistence import create_sqlite_engine


def test_head_database_factory_returns_isolated_schema_copies(
    head_database_factory,
) -> None:
    left = head_database_factory("left.db")
    right = head_database_factory("right.db")

    left_engine = create_sqlite_engine(left)
    with left_engine.begin() as connection:
        connection.execute(text("CREATE TABLE test_only_marker (id INTEGER PRIMARY KEY)"))
    left_engine.dispose()

    right_engine = create_sqlite_engine(right)
    with right_engine.connect() as connection:
        marker = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'test_only_marker'"
            )
        ).scalar_one_or_none()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    right_engine.dispose()

    assert marker is None
    assert revision == "0021_archive_sidecar_inventory"


def test_head_database_factory_rejects_reuse_and_nested_names(
    head_database_factory,
) -> None:
    head_database_factory("one.db")

    for invalid_name, error in (
        ("one.db", FileExistsError),
        ("", ValueError),
        ("nested/two.db", ValueError),
        ("nested\\two.db", ValueError),
    ):
        with pytest.raises(error):
            head_database_factory(invalid_name)
