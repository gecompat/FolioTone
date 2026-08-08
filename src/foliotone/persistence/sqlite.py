"""SQLite persistence implementation backed by SQLAlchemy Core."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, insert, select, update
from sqlalchemy.engine import Connection

from foliotone.core.ids import EntityId
from foliotone.persistence.codecs import Codec, codec_for


def create_sqlite_engine(database: Path | str) -> Engine:
    """Create a SQLite engine with foreign-key enforcement enabled."""
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
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
    command.upgrade(alembic_config(path), revision)


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
