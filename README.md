# FolioTone

FolioTone is an **orchestration and reconciliation platform for large e-book and music collections**. Instead of reimplementing mature media tooling, it connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves real-world identities, detects duplicates and quality/completeness issues, supports human review, and later produces safe consolidation plans.

## Current state

FolioTone is in **W1 — Core + Persistence**.

W0 is complete and verified through GitHub Actions, including the Docker image build and `foliotone status` bootstrap. The first W1 slice is implemented: provider-independent domain entities, provenance/assertion models, classification/matching evidence, and read-only ToolProvider execution contracts.

The immediate next task is **SQLite migrations and persistence** (`W1-007` through `W1-009`). See [Project Status](docs/planning/PROJECT_STATUS.md) and [Backlog](docs/planning/BACKLOG.md).

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

## Implemented W1 domain model

Internal identities use opaque UUID-backed `EntityId` values. External IDs remain namespaced evidence.

Implemented model groups:

```text
Physical/index
  ScanRoot
  ScanRun
  FileRecord
  FileObservation

Provenance/authority
  Provenance
  ValueAssertion
  Agent / AgentName
  ExternalIdentifier
  Contribution

E-books
  Work
  Edition
  Series
  SeriesMembership

Music
  MusicWork
  MusicWorkRelation
  CatalogDesignation
  Recording
  ReleaseGroup
  Release
  ReleaseRecording

Evidence
  ClassificationAssertion
  Fingerprint
  Relation
  Evidence

Tool orchestration contracts
  ToolProviderDescriptor
  ToolExecution
  ToolResult
```

See [W1 Core Implementation Notes](docs/planning/W1_CORE_IMPLEMENTATION.md) and [ADR-0011](docs/decisions/ADR-0011-internal-identifiers-and-core-model.md).

## Repository guide

- [`AGENTS.md`](AGENTS.md) — mandatory working contract for AI agents and contributors.
- [`docs/architecture/`](docs/architecture/) — architecture and domain model.
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

GitHub Actions runs the Python quality checks plus Docker build/bootstrap.

## Safety status

There is currently **no** scan-time source mutation, move, rename, delete, metadata-write, Calibre-write, external-tool-write, or consolidation execution command. External ToolProvider contracts are read-only by construction through W9.

## License

No project license has been selected yet. Until a license is explicitly added, do not assume redistribution or reuse rights beyond GitHub's normal viewing/forking functionality.
