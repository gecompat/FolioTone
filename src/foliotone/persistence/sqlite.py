"""SQLite persistence implementation backed by SQLAlchemy Core."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable

from foliotone.core.ids import EntityId
from foliotone.persistence.codecs import Codec, codec_for
from foliotone.persistence.scan_root_lease import fence_scoped_write


def create_sqlite_engine(database: Path | str) -> Engine:
    """Create a SQLite engine with foreign keys, WAL, and bounded lock waiting."""
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def create_sqlite_read_only_engine(database: Path | str) -> Engine:
    """Open an existing SQLite database without creating or mutating storage."""

    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError("SQLite database is unavailable")
    database_uri = f"file:{path.resolve().as_posix()}?mode=ro&uri=true"
    engine = create_engine(f"sqlite+pysqlite:///{database_uri}")

    @event.listens_for(engine, "connect")
    def _enforce_read_only(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA query_only=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    return engine


def alembic_config(database: Path | str) -> Config:
    """Create an Alembic configuration for FolioTone's packaged migration environment."""
    migration_dir = Path(__file__).with_name("alembic")
    config = Config()
    config.set_main_option("script_location", str(migration_dir))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{Path(database)}")
    return config


def migrate(database: Path | str, revision: str = "head") -> None:
    """Upgrade a SQLite database to the requested Alembic revision."""
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        _repair_empty_interrupted_consolidation_migration(path)
    command.upgrade(alembic_config(path), revision)


def _repair_empty_interrupted_consolidation_migration(path: Path) -> None:
    """Remove only exact empty 0016 DDL left behind before Alembic stamped it."""

    from foliotone.persistence.consolidation_schema import CONSOLIDATION_TABLES

    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            existing_names = {
                str(row[0])
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            if "alembic_version" not in existing_names:
                return
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
            if version != "0015_calibre_library_reconciliation":
                return
            partial = tuple(table for table in CONSOLIDATION_TABLES if table.name in existing_names)
            if not partial:
                return
            for table in partial:
                stored_sql = connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
                    {"name": table.name},
                ).scalar_one()
                expected_sql = str(CreateTable(table).compile(connection))
                if _normalized_ddl(stored_sql) != _normalized_ddl(expected_sql):
                    raise RuntimeError(
                        "interrupted consolidation migration has an incompatible table"
                    )
                if connection.execute(text(f'SELECT 1 FROM "{table.name}" LIMIT 1')).first():
                    raise RuntimeError(
                        "interrupted consolidation migration contains data and cannot be repaired"
                    )
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            with connection.begin():
                for table in reversed(partial):
                    table.drop(connection)
    finally:
        engine.dispose()


def _normalized_ddl(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(" (", "(")


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Expose a committed SQLAlchemy transaction for integration code."""
    with engine.begin() as connection:
        yield connection


class SQLiteRepository[T]:
    """Generic EntityId-keyed repository using an explicit domain codec."""

    def __init__(self, engine: Engine, model_type: type[T]) -> None:
        self._engine = engine
        self._codec: Codec[T] = codec_for(model_type)

    def save(self, value: T) -> None:
        """Insert or update one immutable domain record by its internal ID."""
        row = dict(self._codec.encode(value))
        entity_id = row.get("id")
        if not isinstance(entity_id, str):
            raise TypeError("persistence codec must encode an 'id' string")

        table = self._codec.table
        with self._engine.begin() as connection:
            fence_scoped_write(connection)
            exists = connection.execute(
                select(table.c.id).where(table.c.id == entity_id)
            ).scalar_one_or_none()
            if exists is None:
                connection.execute(insert(table).values(**row))
            else:
                connection.execute(update(table).where(table.c.id == entity_id).values(**row))

    def get(self, entity_id: EntityId) -> T | None:
        """Load one domain record by internal ID."""
        table = self._codec.table
        with self._engine.connect() as connection:
            row = connection.execute(
                select(table).where(table.c.id == str(entity_id))
            ).mappings().one_or_none()
        return None if row is None else self._codec.decode(row)

    def list_all(self) -> list[T]:
        """Load all records in deterministic primary-key order."""
        table = self._codec.table
        with self._engine.connect() as connection:
            rows = connection.execute(select(table).order_by(table.c.id)).mappings().all()
        return [self._codec.decode(row) for row in rows]


def repository[T](engine: Engine, model_type: type[T]) -> SQLiteRepository[T]:
    """Create a typed repository for one supported domain model."""
    return SQLiteRepository(engine, model_type)
