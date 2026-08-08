# Handover / Continuation Guide

## One-minute orientation

FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It combines filesystem evidence, mature specialist tools, metadata services, authority resolution, classification and content/audio fingerprints into one provenance-preserving evidence model.

It is intentionally non-destructive during W0–W9.

Current repository state: **W0 and W1 are complete. W2 incremental indexing and generic ToolProvider execution are next.**

## Do this next

1. Read `AGENTS.md`.
2. Read `PROJECT_STATUS.md` and confirm it still matches repository reality.
3. Read `docs/architecture/PERSISTENCE.md`, `W1_CORE_IMPLEMENTATION.md`, ADR-0011 and ADR-0012 before changing core/persistence contracts.
4. Start `W2-001`: implement configured ScanRoot and ScanRun lifecycle using the existing repositories/migrations.
5. Continue with filesystem discovery (`W2-002`) and incremental NEW/UNCHANGED/MODIFIED/MISSING behavior (`W2-003`).
6. Add streamed hashing (`W2-005`) without loading large media files into memory.
7. Implement the generic ToolProvider process/container runtime (`W2-010`) before concrete calibre/ffprobe/fpcalc/beets/SongKong/Picard adapters.
8. Keep `BACKLOG.md` and `PROJECT_STATUS.md` synchronized after each coherent vertical slice.

## Verified W1 baseline

The completed W1 implementation has passed:

```text
Install
Ruff
Mypy
Pytest
Docker build
Docker migration smoke test
Docker bootstrap/status
```

The persistence suite builds SQLite from an empty file, reaches Alembic head, repeats `upgrade head`, round-trips the complete synthetic W1 graph, and verifies foreign-key/uniqueness behavior.

## Implemented W1 core and persistence

Provider/tool-independent immutable models exist for:

- ScanRoot / ScanRun / FileRecord / FileObservation;
- Provenance / ValueAssertion;
- Agent / AgentName / ExternalIdentifier / Contribution;
- Work / Edition / Series / SeriesMembership;
- MusicWork / MusicWorkRelation / CatalogDesignation;
- Recording / ReleaseGroup / Release / ReleaseRecording;
- ClassificationAssertion / Fingerprint / Relation / Evidence;
- ToolProviderDescriptor / ToolExecution / ToolResult.

Persistence includes:

- SQLAlchemy Core schema;
- Alembic `0001_initial` migration;
- Repository protocol + SQLiteRepository;
- generic dataclass/row codecs;
- UUID -> canonical text serialization;
- timezone-aware datetime -> UTC ISO-8601 serialization;
- SQLite foreign-key enforcement;
- Docker-packaged migration verification.

Internal identity uses opaque UUID-backed `EntityId`; external catalog/provider IDs remain separate evidence.

## Important persistence invariant learned during W1

Do not execute SQL on an Alembic connection before `context.begin_transaction()` without understanding SQLAlchemy 2.x autobegin behavior.

The W1 tests found that `PRAGMA foreign_keys=ON` started an implicit transaction. If not ended before Alembic's migration transaction, SQLite DDL could survive while the Alembic version row rolled back. The environment now commits that small PRAGMA transaction first, and the idempotent migration test protects this behavior.

## Product description

> FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves identities, detects duplicates and quality/completeness issues, supports review, and produces safe consolidation plans.

## Non-negotiable constraints

- Python 3.12+; Docker/Linux primary runtime.
- Host-persistent `/data`; source media mounted read-only.
- Analysis only through W9; write-capable FolioTone/tool actions blocked until W10.
- Orchestration first: evaluate mature specialist tools before native reimplementation.
- Tool/provider-specific schemas and commands terminate at adapter boundaries.
- External specialist outputs are evidence, not canonical truth.
- Absolute host paths remain configuration concerns, not durable domain identity.
- Observed/derived/external/canonical/user-confirmed values keep provenance.
- Tool-derived values keep ToolExecution/tool/adapter version provenance.
- Authors/artists/composers are Agent identities plus role relationships.
- Book Work/Edition and music MusicWork/Recording/ReleaseGroup/Release are distinct identity levels.
- Classification is multidimensional and provenance-preserving.
- Candidate generation precedes expensive matching; decisions stay explainable/versioned.
- Migration files are immutable after merge; schema changes get new revisions.

## External tools and knowledge

Read `docs/reference/EXTERNAL_TOOLS.md` before implementing media-specific capabilities and `docs/reference/EXTERNAL_DATA_SOURCES.md` before implementing knowledge-provider adapters.

Candidate tools/providers are not automatically dependencies. Re-check current maintenance, license, API/CLI/container interfaces, output formats and security behavior before implementing an adapter.

## What not to assume

- The W1 database schema is a foundation, not the final optimized query schema.
- W2/W5/W6 may add indexes or service-level integrity rules through new migrations once real access patterns exist.
- Generic ToolProvider process/container execution is not implemented yet.
- Concrete media tools are still candidates; commercial tools remain optional.
- Matching/entity-resolution thresholds are not calibrated yet.
- OCR, perceptual cover hashing, quality ranking and consolidation execution are later work.

## Handover quality rule

At the end of a substantial work session, update `PROJECT_STATUS.md` and `BACKLOG.md` so the next agent can continue without previous chat history. Never claim verification that was not actually executed.
