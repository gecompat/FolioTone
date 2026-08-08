# Project Status

Last updated: 2026-08-08

## Current wave

**W0 — Project Foundation**

The full planning/foundation state is in FolioTone. The architecture now explicitly adopts an **orchestration-first ToolProvider strategy**: mature specialist tools should be connected and reconciled before FolioTone reimplements equivalent media-specific functionality.

Foundation content includes Authority/Entity Resolution, provenance, external enrichment, classical-aware music modeling, multidimensional classification, ToolExecution provenance and an external-tool registry.

The immediate next action remains `W0-006`: verify the Docker bootstrap before starting W1.

## Implemented/documented foundation

- repository/package directory skeleton under `src/foliotone`;
- Python packaging metadata and a minimal `foliotone status` bootstrap command;
- package boundaries for parsing, tooling, authority, enrichment and classification;
- Dockerfile and Compose baseline;
- persistent writable `/data` mount and read-only e-book/music media mounts in Compose;
- `FOLIOTONE_*` host-path environment-variable convention;
- Git ignore rules for runtime/private data;
- GitHub Actions quality workflow for install, Ruff, Mypy and Pytest;
- architecture overview, domain model, indexing/matching design, and safety invariants;
- Authority/Entity Resolution architecture separated from duplicate matching;
- provenance/value states: `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL`, `USER_CONFIRMED`;
- Agent/AgentName/alias/pseudonym/credit role model;
- expanded music identity levels: MusicWork, Recording, ReleaseGroup, Release;
- classical-aware work hierarchy/catalog-designation planning;
- multidimensional classification planning;
- external knowledge-provider modes/cache/privacy rules;
- initial external data-source registry for Open Library, GND/DNB, Wikidata, MusicBrainz and AcoustID;
- orchestration-first `ToolProvider` architecture (ADR-0010);
- external specialist tool registry covering calibre, ffprobe, Chromaprint/fpcalc, beets, SongKong, Picard and local MusicBrainz mirror as candidates;
- ToolExecution/tool-version/adapter-version provenance requirements for specialist evidence;
- external-tool write/delete/move/retag operations explicitly blocked through W9;
- accepted ADRs for Python, Docker/persistence, analysis-first, Calibre adapter, explainable/versioned matching, authority/provenance, music identity levels, multidimensional classification, external-enrichment privacy and tool orchestration;
- W0–W10 implementation plan and actionable backlog;
- AI/contributor working contract in `AGENTS.md`;
- bootstrap unit test.

## Product positioning

Current recommended project description:

> FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves identities, detects duplicates and quality/completeness issues, supports review, and produces safe consolidation plans.

Short package/repository-description variant:

> Orchestrate specialist tools to reconcile, analyze, and deduplicate e-book and music collections.

## Tool strategy

High-value candidate integrations are documented in `docs/reference/EXTERNAL_TOOLS.md`.

Current architectural intent:

- calibre CLI / Content Server: e-book metadata/library specialist;
- `ffprobe`: technical audio/media observations;
- Chromaprint/`fpcalc`: acoustic fingerprints;
- beets: music metadata/duplicate/completeness specialist;
- SongKong: optional automated status/report/preview specialist;
- Picard: optional independent validator/specialist;
- local MusicBrainz mirror: later scale-dependent infrastructure option.

These tools are evidence sources, not canonical FolioTone authorities. FolioTone owns cross-tool reconciliation and review.

## Verification state

Verified on the migrated FolioTone foundation through GitHub Actions:

```text
Install  PASS
Ruff     PASS
Mypy     PASS
Pytest   PASS
```

The current tool-orchestration documentation/package-boundary change must also pass CI before merge.

Still unverified in FolioTone:

```bash
docker compose build
docker compose run --rm foliotone status
```

Do not mark `W0-006` done until the Docker bootstrap is actually verified or a documented reason explicitly removes it from the W0 acceptance criteria.

## Not implemented

No production media functionality exists yet:

- no database schema/migrations;
- no concrete expanded domain model classes beyond package skeleton;
- no ToolProvider runtime or concrete tool adapter;
- no file scan/index;
- no filename/path parser implementation;
- no hashes/fingerprints;
- no calibre metadata ToolProvider;
- no ffprobe/Chromaprint/beets/SongKong/Picard integration;
- no EPUB/PDF/MOBI content analyzer;
- no authority/entity resolver;
- no external knowledge-provider adapter/cache/importer;
- no classification engine;
- no matching engine;
- no review queue;
- no Calibre library reader;
- no consolidation planner;
- no source-media write operations.

## Next implementation sequence

1. `W0-006` — verify Docker bootstrap and record actual result.
2. `W1-001` — design concrete entity/value-object boundaries and internal ID strategy for the expanded model.
3. `W1-002` — physical/index core models.
4. `W1-003` — Agent/AgentName/ExternalIdentifier/Contribution and provenance assertion model.
5. `W1-004`/`W1-005` — e-book and music entity models, including Series, MusicWork and ReleaseGroup.
6. `W1-006` — Classification/Fingerprint/Relation/Evidence/version concepts.
7. `W1-010` — ToolProviderDescriptor/ToolExecution/tool-result provenance contracts.
8. `W1-007` — select/document SQLite migration mechanism.
9. `W1-008`/`W1-009` — persistence implementation and tests.
10. `W1-011` — synchronize documentation/status and close W1.
11. W2 includes the generic ToolProvider execution runtime before concrete W3/W4 media-tool adapters.

Do not start W5 external knowledge-provider implementation before the W1 provenance/provider-independent core contracts exist.

Do not implement W3/W4 specialist capabilities from scratch without first evaluating the relevant tools in `EXTERNAL_TOOLS.md`.

## Open decisions

- Project license (`W0-007`). This does not block W1 internal development.
- Concrete SQLite migration library/mechanism (`W1-007`). Decide during W1 and record an ADR.
- Exact ToolProvider process/container execution implementation (`W2-010`).
- Concrete e-book tool/library composition (`W3-001`) after current license/maintenance/security review.
- Concrete music tool composition (`W4-001`) after current license/maintenance/security review.
- Concrete external knowledge-provider adapters/access modes (`W5B`) after reviewing current terms, bulk/API options and cache rules.
- Matching thresholds: decide/calibrate in W6 using controlled fixtures.

## Safety gate

W10 remains explicitly blocked. No source-media mutation is authorized by current architecture decisions.

W9 may create non-executable consolidation plans only. External tool commands that write/delete/move/rename/retag source media are covered by the same gate.
