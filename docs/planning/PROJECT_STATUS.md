# Project Status

Last updated: 2026-08-08

## Current wave

**W2 — Incremental Index + Filename/Path Context + Tool Runtime**

W0 and W1 are complete. FolioTone now has a verified Docker/Python foundation, provider/tool-independent immutable core domain, SQLite persistence with versioned migrations, and read-only ToolProvider provenance contracts.

The orchestration-first rule remains authoritative: specialist tools produce versioned evidence through replaceable ToolProvider integrations; FolioTone owns provenance, reconciliation, identity, review, and safety.

## W1 completion summary

### Core/domain

Implemented:

- opaque UUID-backed `EntityId`;
- ScanRoot / ScanRun / FileRecord / FileObservation;
- Provenance / ValueAssertion;
- Agent / AgentName / ExternalIdentifier / Contribution;
- Work / Edition / Series / SeriesMembership;
- MusicWork / MusicWorkRelation / CatalogDesignation;
- Recording / ReleaseGroup / Release / ReleaseRecording;
- ClassificationAssertion / Fingerprint / Relation / Evidence;
- ToolProviderDescriptor / ToolExecution / ToolResult.

See `docs/planning/W1_CORE_IMPLEMENTATION.md` and ADR-0011.

### Persistence

Implemented:

- SQLAlchemy Core schema behind provider-independent repository contracts;
- SQLite initial persistence engine;
- Alembic migration environment and explicit immutable `0001_initial` schema snapshot;
- generic `Repository[T]` protocol and `SQLiteRepository[T]` implementation;
- explicit generic domain/row codecs using FolioTone dataclass type information;
- UUID string, UTC ISO-8601 datetime and stable enum-value serialization;
- SQLite foreign-key enforcement for application connections;
- idempotent `migrate(..., "head")` behavior;
- packaged Alembic resources verified inside the built Docker image.

See `docs/architecture/PERSISTENCE.md` and ADR-0012.

## Verification state

GitHub Actions run `31280522927` verified the completed W1 persistence implementation before the final documentation-only closure changes:

```text
Install                       PASS
Ruff                          PASS
Mypy                          PASS
Pytest                        PASS
Prepare Docker placeholders   PASS
Docker build                  PASS
Docker migration smoke test   PASS
Docker bootstrap/status       PASS
```

Persistence integration tests cover:

- migration from an empty database to `0001_initial`;
- repeated `upgrade head` without replaying V1;
- current table set and Alembic revision;
- full synthetic W1 graph round-trip across all registered model groups;
- ID-based update of immutable records;
- SQLite foreign-key enforcement;
- unique scan-root-relative file paths;
- deterministic repository listing.

During development the tests found an actual SQLAlchemy 2.x/Alembic transaction issue: enabling the SQLite foreign-key PRAGMA opened an implicit transaction before Alembic's migration transaction, allowing the Alembic version row to roll back while DDL survived. The migration environment now explicitly commits the PRAGMA transaction before Alembic begins its migration transaction. The idempotence test prevents recurrence.

No real collection data is used by the test suite.

## Current persistence decisions

- SQLAlchemy **Core**, not ORM, so domain dataclasses remain database-independent;
- Alembic for versioned migrations;
- SQLite initially;
- current dependency bounds: `SQLAlchemy>=2.0,<2.1`, `alembic>=1.18,<2`;
- migration files are immutable after merge;
- polymorphic `(target_kind, target_id)` references remain domain/service-validated rather than pretending to be single-table foreign keys;
- speculative performance indexes are deferred until W2/W5/W6 query patterns exist.

## W2 immediate target

Start with `W2-001`: configured scan roots and scan-run lifecycle using the W1 persistence layer.

The first W2 vertical slice should establish:

```text
configured ScanRoot
        ↓
start ScanRun
        ↓
filesystem discovery
        ↓
FileRecord + FileObservation persistence
        ↓
complete/interrupted ScanRun
```

Then add incremental state comparison, streamed hashing and the generic ToolProvider execution runtime before concrete calibre/ffprobe/fpcalc/beets/SongKong/Picard adapters.

## Not implemented yet

- filesystem discovery/index execution;
- incremental NEW/UNCHANGED/MODIFIED/MISSING/DELETED logic;
- hashing pipeline;
- move/rename detection;
- filename/path parser;
- generic ToolProvider process/container runtime;
- calibre/ffprobe/fpcalc/beets/SongKong/Picard adapters;
- e-book content analysis;
- authority/entity resolution engine;
- external knowledge-provider adapters/cache/imports;
- classification engine;
- matching engine;
- review system;
- Calibre library reconciliation;
- consolidation planning/execution.

## Open decisions

- Project license (`W0-007`) remains open but does not block internal development.
- Exact process/container ToolProvider runtime belongs to W2.
- DELETED confirmation semantics belong to W2-004.
- Concrete e-book/music tool compositions belong to W3/W4 after current license/maintenance/security review.
- External knowledge-provider adapters belong to W5 after current terms/API/bulk/cache review.
- Matching thresholds belong to W6 calibration.

## Safety gate

W10 remains explicitly blocked. No FolioTone-native or external-tool source-media mutation is authorized.

W9 may create non-executable consolidation plans only.
