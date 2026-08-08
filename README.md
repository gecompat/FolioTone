# FolioTone

---
---
# ⚠️ READ BEFORE USE

## License notice

**NOTICE: This software is NOT Open Source. Use is governed by a custom Community & Attribution License.**

1. **NO RESALE:** Selling or charging for access to this software is strictly prohibited.
2. **ATTRIBUTION REQUIRED:** You must preserve the copyright notice for **gecompat - Gerhard Pisch**.
3. **NO LIABILITY:** Use this software at your own risk. The author is **NOT liable** for any damages, data loss, or business interruptions.

Full legal terms can be found in the [LICENSE.md](./LICENSE.md) file.

---
## Lizenzhinweis

**NOTIZ: FolioTone ist keine Open-Source-Software. Die Nutzung richtet sich nach der projektspezifischen Community & Attribution License.**

1. **NO RESALE:** Der Verkauf der Software und das Entgelt für den Zugang zur Software sind untersagt.
2. **ATTRIBUTION REQUIRED:** Der Copyright-Hinweis für **gecompat – Gerhard Pisch** muss erhalten bleiben.
3. **NO LIABILITY:** Die Nutzung erfolgt auf eigenes Risiko; der Autor **haftet nicht** für Schäden, Datenverlust oder Betriebsunterbrechungen.

Maßgeblich ist der vollständige Wortlaut in [LICENSE.md](./LICENSE.md).

# ⚠️ READ BEFORE USE

---
---

FolioTone is an **orchestration and reconciliation platform for large e-book and music collections**. Instead of reimplementing mature media tooling, it connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves real-world identities, detects duplicates and quality/completeness issues, supports human review, and later produces safe consolidation plans.

## Current state

FolioTone is in **W2 — Incremental Index + Filename/Path Context + Tool Runtime**.

W0 and W1 are complete. The repository now contains:

- a verified Python/Docker bootstrap;
- provider/tool-independent immutable domain models;
- read-only ToolProvider execution/evidence contracts;
- SQLite persistence via SQLAlchemy Core;
- Alembic migrations with explicit `0001_initial` schema;
- generic repositories/codecs for the complete W1 model;
- integration tests for migration, round-trip persistence, constraints and Docker-packaged migrations.

The immediate next task is `W2-001`: implement configured scan roots and the scan-run lifecycle on top of the W1 persistence layer. See [Project Status](docs/planning/PROJECT_STATUS.md) and [Backlog](docs/planning/BACKLOG.md).

## Positioning: orchestrate specialists, do not reinvent them

FolioTone evaluates mature tools before implementing equivalent format-specific functionality itself.

High-value ToolProvider candidates include:

- calibre CLI / Content Server for e-book metadata and library access;
- FFmpeg / `ffprobe` for technical audio/media observations;
- Chromaprint / `fpcalc` for acoustic fingerprints;
- beets for music metadata, duplicate and completeness analysis;
- SongKong for optional automated status/report/preview evidence;
- MusicBrainz Picard as an optional specialist/validator;
- a local MusicBrainz mirror later when scale justifies the infrastructure.

These tools remain **replaceable specialists**. Their outputs become observations and evidence. FolioTone owns provenance, cross-tool reconciliation, entity resolution, canonical decisions, matching, review knowledge, and safety.

See [External Analysis Tools](docs/reference/EXTERNAL_TOOLS.md) and [ADR-0010](docs/decisions/ADR-0010-tool-provider-orchestration.md).

## Core principles

- Python 3.12+; Docker/Linux is the primary runtime.
- Runtime state is host-persistent under `/data`; source media is mounted read-only under `/media`.
- SQLite is the initial persistence engine behind provider-independent persistence contracts.
- SQLAlchemy Core is used for schema/query mechanics; domain dataclasses are not ORM entities.
- Alembic owns immutable versioned schema migrations.
- Prefer maintained specialist tools over unnecessary native reimplementation.
- Tool/provider schemas and commands terminate at adapter boundaries.
- External tool/provider results are evidence, not unquestioned truth.
- Observed, derived, external, canonical, and user-confirmed values remain distinct and provenance-preserving.
- Authors/artists/composers are `Agent` identities connected through roles, not flattened strings.
- Book `Work`/`Edition` and music `MusicWork`/`Recording`/`ReleaseGroup`/`Release` remain separate identity levels.
- Matching is explainable, versioned, reviewable, and candidate-based rather than global all-vs-all.
- No destructive operation may be inferred from one tool, score, provider, AI, or web result.
- Source-media mutation remains blocked until W10 and a future accepted ADR.

## Target architecture

```text
                      Specialist tools
       calibre / ffprobe / fpcalc / beets / SongKong / Picard
                              |
                              v
                         Tool Providers
                              |
Filesystem -> Index -> Parsing -> Media analysis/orchestration
                              |
                              +----------------------+
                              |                      |
                              v                      v
                   knowledge providers        Tool evidence
                              |                      |
                              +----------+-----------+
                                         v
                              Authority / Entity Resolution
                                         |
                                         v
                                  Classification
                                         |
                                         v
                                  Matching Engine
                                         |
                                         v
                                       Review
                                         |
                                         v
                            Consolidation Planning (W9)
                                         |
                                         v
                          [future gated execution: W10]
```

## Implemented W1 foundation

Internal identities use opaque UUID-backed `EntityId` values. External IDs remain namespaced evidence.

```text
Physical/index
  ScanRoot / ScanRun / FileRecord / FileObservation

Provenance/authority
  Provenance / ValueAssertion
  Agent / AgentName / ExternalIdentifier / Contribution

E-books
  Work / Edition / Series / SeriesMembership

Music
  MusicWork / MusicWorkRelation / CatalogDesignation
  Recording / ReleaseGroup / Release / ReleaseRecording

Evidence
  ClassificationAssertion / Fingerprint / Relation / Evidence

Tool orchestration
  ToolProviderDescriptor / ToolExecution / ToolResult

Persistence
  Repository[T] / SQLiteRepository[T]
  SQLAlchemy Core schema
  Alembic 0001_initial migration
```

See:

- [W1 Core Implementation Notes](docs/planning/W1_CORE_IMPLEMENTATION.md)
- [Persistence Architecture](docs/architecture/PERSISTENCE.md)
- [ADR-0011](docs/decisions/ADR-0011-internal-identifiers-and-core-model.md)
- [ADR-0012](docs/decisions/ADR-0012-sqlalchemy-alembic-persistence.md)

## Repository guide

- [`AGENTS.md`](AGENTS.md) — mandatory working contract for AI agents and contributors.
- [`docs/architecture/`](docs/architecture/) — architecture, domain and persistence design.
- [`docs/decisions/`](docs/decisions/) — accepted Architecture Decision Records.
- [`docs/reference/EXTERNAL_TOOLS.md`](docs/reference/EXTERNAL_TOOLS.md) — specialist tool candidates and integration rules.
- [`docs/reference/EXTERNAL_DATA_SOURCES.md`](docs/reference/EXTERNAL_DATA_SOURCES.md) — external knowledge-provider registry.
- [`docs/planning/IMPLEMENTATION_PLAN.md`](docs/planning/IMPLEMENTATION_PLAN.md) — W0–W10 development sequence.
- [`docs/planning/BACKLOG.md`](docs/planning/BACKLOG.md) — actionable status by wave.
- [`docs/planning/PROJECT_STATUS.md`](docs/planning/PROJECT_STATUS.md) — authoritative current state and next action.
- [`docs/planning/HANDOVER.md`](docs/planning/HANDOVER.md) — compact continuation guide.

## Bootstrap and quality checks

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
mypy src/foliotone
pytest
foliotone status
```

Docker:

```bash
cp .env.example .env
docker compose build
docker compose run --rm foliotone status
```

Programmatic database migration:

```python
from foliotone.persistence import migrate

migrate("/data/foliotone.db")
```

GitHub Actions runs Python quality checks, integration tests, Docker build, a migration inside the built image, and the Docker bootstrap.

## Safety status

There is currently **no** scan-time source mutation, move, rename, delete, metadata-write, Calibre-write, external-tool-write, or consolidation execution command. External ToolProvider contracts are read-only by construction through W9.

## License

FolioTone is **not Open Source**. Use is governed by the project's custom Community & Attribution License. See [LICENSE.md](./LICENSE.md) for the legally binding terms.
