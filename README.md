# FolioTone

FolioTone is an **orchestration and reconciliation platform for large e-book and music collections**. Instead of reimplementing mature media tooling, it connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves real-world identities, detects duplicates and quality/completeness issues, supports human review, and later produces safe consolidation plans.

## Current state

The repository is in **W0 – Project Foundation**. The project structure, architecture, safety/privacy rules, development roadmap, AI handover contract, Docker baseline, Python packaging, bootstrap tests, Authority/Enrichment design, and ToolProvider strategy are documented.

Production file indexing, media analyzers/tool adapters, authority resolution, external provider adapters, matching, review and consolidation planning are **not implemented yet**.

The immediate next task is W0 bootstrap verification (`W0-006`). After that, implementation starts with **W1 – Core + Persistence** using the provider- and tool-independent domain model. See [Project Status](docs/planning/PROJECT_STATUS.md) and [Implementation Plan](docs/planning/IMPLEMENTATION_PLAN.md).

## Positioning: orchestrate specialists, do not reinvent them

FolioTone should first evaluate mature tools before implementing format-specific functionality itself.

Examples of high-value ToolProvider candidates:

- calibre CLI / Content Server for e-book metadata and library access;
- FFmpeg / `ffprobe` for technical audio/media observations;
- Chromaprint / `fpcalc` for acoustic fingerprints;
- beets for music metadata, duplicate and completeness analysis;
- SongKong for automated music analysis/status/preview evidence;
- MusicBrainz Picard as an optional specialist/validator;
- a local MusicBrainz mirror later when collection scale justifies the infrastructure.

These tools remain **replaceable specialists**. Their outputs become observations and evidence. FolioTone owns provenance, cross-tool reconciliation, entity resolution, canonical decisions, matching, review knowledge and safety.

See [External Analysis Tools](docs/reference/EXTERNAL_TOOLS.md) and [ADR-0010](docs/decisions/ADR-0010-tool-provider-orchestration.md).

## Core principles

- Python is the implementation language.
- Docker/Linux is the primary runtime.
- Runtime state is persistent on the host and mounted into the container at `/data`.
- Media collections are mounted **read-only** under `/media`.
- FolioTone is analysis-only until an explicitly separate, later consolidation execution phase.
- SQLite is the initial persistence engine, behind a persistence boundary so it can be replaced later.
- Prefer orchestration of maintained specialist tools over unnecessary native reimplementation.
- Tool-specific commands/schemas remain behind `ToolProvider`/adapter boundaries.
- External tool results are Evidence, not unquestioned truth.
- Calibre is an external read-only library/metadata source; FolioTone does not depend on Calibre.
- E-book and music analyzers share core/index infrastructure but remain media-specific.
- Filename/path parsing emits candidates; it does not silently rewrite metadata.
- Authority/Entity Resolution is separate from duplicate Matching.
- Observed, derived, external, canonical and user-confirmed values retain provenance.
- Contributors are Agent identities with aliases/name forms and typed roles/credits.
- MusicWork, Recording, ReleaseGroup, Release and File are distinct identity levels.
- Classification is multidimensional rather than a single genre string.
- External enrichment is provider-based, cached, privacy-bounded and optional for ordinary local scans.
- Duplicate decisions must be evidence-based, explainable, versioned, and reviewable.
- No destructive file operation may be inferred from one tool, score, provider, AI or web result.

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
                   local/bulk/online          Tool evidence
                   knowledge providers              |
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

Shared domain/persistence contracts sit underneath these components.

## Identity model highlights

E-books:

```text
Agent --role--> Work -> Edition -> File
                    \
                     -> SeriesMembership
```

Music:

```text
Agent --role--> MusicWork -> Recording -> ReleaseRecording -> Release -> ReleaseGroup
```

These are conceptual relations, not simple ownership trees. Many-to-many relationships are expected.

For classical music, FolioTone plans explicit work hierarchies/derivations, catalog designations, contributor roles, and separate classification facets for broad domain, period/era, form and instrumentation.

## External knowledge strategy

Initial candidate sources include Open Library, GND/DNB, Wikidata, MusicBrainz and AcoustID/Chromaprint. They are documented as candidate providers, not mandatory dependencies.

Preferred high-volume order:

1. existing local FolioTone knowledge/cache;
2. locally imported provider datasets where appropriate;
3. structured online APIs for unresolved targeted lookups;
4. generic web research only as a separately enabled fallback.

Absolute local paths must never be sent to providers. Provider data becomes provenance-preserving evidence rather than silently replacing file metadata.

See [External Data Sources](docs/reference/EXTERNAL_DATA_SOURCES.md).

## External tool strategy

Preferred integration modes are documented CLI/API/service/container interfaces with machine-readable outputs where possible.

Through W9:

- source media remains read-only;
- FolioTone uses report/status/scan/probe/preview modes;
- external delete/move/rename/retag operations are prohibited just like FolioTone-native writes;
- tool identity, version, adapter/parser version and execution context must remain traceable.

A commercial or optional tool must not silently become a hard requirement for the essential local pipeline.

## Repository guide

- [`AGENTS.md`](AGENTS.md) — mandatory working contract for AI agents and contributors.
- [`docs/architecture/OVERVIEW.md`](docs/architecture/OVERVIEW.md) — component boundaries and dependency rules.
- [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md) — planned expanded domain model.
- [`docs/architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`](docs/architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md) — authority resolution, external enrichment, provenance and classification design.
- [`docs/architecture/INDEXING_AND_MATCHING.md`](docs/architecture/INDEXING_AND_MATCHING.md) — incremental indexing, entity resolution inputs and explainable matching design.
- [`docs/architecture/SAFETY.md`](docs/architecture/SAFETY.md) — non-destructive and external-lookup privacy rules.
- [`docs/reference/EXTERNAL_DATA_SOURCES.md`](docs/reference/EXTERNAL_DATA_SOURCES.md) — candidate knowledge-provider/source registry.
- [`docs/reference/EXTERNAL_TOOLS.md`](docs/reference/EXTERNAL_TOOLS.md) — candidate specialist tools and integration/safety rules.
- [`docs/decisions/ADR-0010-tool-provider-orchestration.md`](docs/decisions/ADR-0010-tool-provider-orchestration.md) — orchestration-first architecture decision.
- [`docs/decisions/`](docs/decisions/) — all accepted Architecture Decision Records.
- [`docs/planning/IMPLEMENTATION_PLAN.md`](docs/planning/IMPLEMENTATION_PLAN.md) — W0–W10 development sequence and acceptance criteria.
- [`docs/planning/BACKLOG.md`](docs/planning/BACKLOG.md) — actionable work items.
- [`docs/planning/PROJECT_STATUS.md`](docs/planning/PROJECT_STATUS.md) — authoritative current state and next action.
- [`docs/planning/HANDOVER.md`](docs/planning/HANDOVER.md) — compact continuation guide.
- [`docs/planning/CI_WORKFLOW.md`](docs/planning/CI_WORKFLOW.md) — installed GitHub Actions workflow contract and verification notes.

## Python package boundaries

The current package skeleton includes:

```text
foliotone/
├── core/
├── persistence/
├── index/
├── parsing/
├── analyzers/
│   ├── ebook/
│   └── music/
├── tooling/
├── authority/
├── enrichment/
├── classification/
├── matching/
├── review/
├── consolidation/
├── adapters/
│   └── calibre/
└── cli/
```

These are boundaries/placeholders; most production functionality is intentionally not implemented yet.

## Bootstrap

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
foliotone status
pytest
ruff check .
mypy src/foliotone
```

On Windows PowerShell, activate the virtual environment with `.venv\Scripts\Activate.ps1`.

Docker baseline:

```bash
cp .env.example .env
docker compose build
docker compose run --rm foliotone status
```

The sample compose configuration uses project-local placeholder directories. Real collection paths belong in `.env`, which is ignored by Git.

## Safety status

The current code has **no scan, move, rename, delete, metadata-write, provider-write, Calibre-write, external-tool-write, or consolidation execution command**. The Docker media mounts are read-only. This is intentional.

W9 may eventually create non-executable plans. Write-capable consolidation remains blocked until W10 and a future accepted ADR.

## License

No project license has been selected yet. Until a license is explicitly added, do not assume redistribution or reuse rights beyond GitHub's normal viewing/forking functionality.
