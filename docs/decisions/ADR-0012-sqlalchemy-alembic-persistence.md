# ADR-0012: SQLAlchemy Core + Alembic for SQLite persistence and migrations

- Status: Accepted
- Date: 2026-08-08

## Context

W1 needs durable SQLite persistence and a migration mechanism that can evolve safely as indexing, ToolProvider evidence, entity resolution, review and matching expand.

FolioTone should not build a custom migration framework when mature, maintained Python tooling already exists. At the same time, the provider-independent immutable domain dataclasses must not become SQLAlchemy ORM entities or inherit database concerns.

SQLAlchemy 2.0 and Alembic provide the required Python 3.12-compatible engine/schema and migration functionality. Alembic explicitly supports SQLite's restricted ALTER behavior through batch migrations. Exact compatible minor releases float within the guarded dependency ranges and are verified by CI rather than being described as permanently "latest" in this ADR.

The initial persistence CI resolved SQLAlchemy 2.0.51 and Alembic 1.19.1 successfully.

## Decision

Use:

- SQLAlchemy **Core** for schema definitions, engines, transactions and query construction;
- Alembic for forward schema migrations;
- SQLite as the initial database engine;
- explicit mapping/codecs between immutable FolioTone domain dataclasses and SQL rows.

Do **not** map the domain dataclasses as SQLAlchemy ORM entities. Application/domain code depends on FolioTone persistence contracts, not SQLAlchemy sessions, tables or row objects.

Version policy for the initial implementation:

- `SQLAlchemy>=2.0,<2.1`;
- `alembic>=1.18,<2`.

A future upgrade across those guarded boundaries requires CI validation and may update this ADR or add a successor ADR.

## Migration rules

- migrations are immutable once merged;
- the initial migration contains an explicit schema snapshot rather than calling current metadata dynamically;
- SQLite foreign keys are enabled for every application connection;
- the Alembic environment enables foreign keys without leaving an implicit SQLAlchemy transaction open before the migration transaction begins;
- future SQLite schema changes use Alembic-compatible batch operations where needed;
- migrations run programmatically before repositories are opened for normal use;
- migration tests build a database from an empty file, assert it reaches the current head, and verify re-running `upgrade head` is idempotent.

## Persistence representation

- internal UUID-backed `EntityId` values are stored as canonical lowercase UUID strings;
- timezone-aware datetimes are serialized as UTC ISO-8601 text to avoid SQLite timezone ambiguity;
- enums are stored by stable string value;
- absolute host paths are not persisted in domain entity tables;
- provider/tool-specific payloads do not define core tables;
- ToolExecution and ToolResult preserve tool/adapter/input/config version identity.

## Consequences

- schema evolution uses a standard, well-documented migration tool;
- persistence stays replaceable and does not leak into the domain model;
- SQLite-specific limitations are handled by an established ecosystem rather than FolioTone-specific DDL machinery;
- a later PostgreSQL implementation can reuse the domain/persistence contracts and much of the SQLAlchemy Core schema while remaining a separate operational choice.

## Primary references checked for this decision

- SQLAlchemy 2.0 documentation: https://docs.sqlalchemy.org/en/20/
- Alembic documentation: https://alembic.sqlalchemy.org/en/latest/
- Alembic SQLite batch migrations: https://alembic.sqlalchemy.org/en/latest/batch.html
