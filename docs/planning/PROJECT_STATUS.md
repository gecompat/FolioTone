# Project Status

Last updated: 2026-08-08

## Current wave

**W0 — Project Foundation**

The full planning/foundation state has been migrated to the new FolioTone repository and renamed consistently at project, Python-package, CLI, Docker-service and environment-variable level.

Foundation content includes Authority/Entity Resolution, provenance, external enrichment, classical-aware music modeling and multidimensional classification.

The GitHub Actions workflow is installed. The immediate next action is `W0-006`: execute/inspect FolioTone bootstrap verification and fix any remaining foundation defect before starting W1.

## Implemented/documented foundation

- repository/package directory skeleton under `src/foliotone`;
- Python packaging metadata and a minimal `foliotone status` bootstrap command;
- neutral package boundaries for parsing, authority, enrichment and classification;
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
- external provider modes/cache/privacy rules;
- initial external data-source registry for Open Library, GND/DNB, Wikidata, MusicBrainz and AcoustID/Chromaprint;
- accepted ADRs for Python, Docker/persistence, analysis-first, Calibre adapter, explainable/versioned matching, authority/provenance, music identity levels, multidimensional classification and external-enrichment privacy;
- W0–W10 implementation plan and actionable backlog;
- AI/contributor working contract in `AGENTS.md`;
- bootstrap unit test.

## Migration/CI note

The predecessor PR's GitHub Actions run reached package installation successfully and then failed at Ruff with `E501` because one bootstrap status line exceeded the configured 100-character line length. The FolioTone CLI has been reformatted so that specific defect is not carried forward.

The FolioTone workflow is now present at `.github/workflows/ci.yml` and targets `src/foliotone`. `docs/planning/CI_WORKFLOW.md` preserves the workflow contract and the predecessor failure context.

Do not claim FolioTone CI, Mypy or Pytest passed until an actual FolioTone run exists.

## Not implemented

No production media functionality exists yet:

- no database schema/migrations;
- no concrete expanded domain model classes beyond package skeleton;
- no file scan/index;
- no filename/path parser implementation;
- no hashes/fingerprints;
- no EPUB/PDF/MOBI parser;
- no audio analyzer;
- no authority/entity resolver;
- no external provider adapter/cache/importer;
- no classification engine;
- no matching engine;
- no review queue;
- no Calibre reader;
- no consolidation planner;
- no source-media write operations.

## Verification state

W0 bootstrap verification remains outstanding until an actual FolioTone CI and/or clean local/container result is recorded.

Required verification commands:

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src/foliotone
pytest
docker compose build
docker compose run --rm foliotone status
```

Record actual results here before marking `W0-006` done.

## Next implementation sequence

1. `W0-006` — verify/fix bootstrap and record actual results.
2. `W1-001` — design concrete entity/value-object boundaries and internal ID strategy for the expanded model.
3. `W1-002` — physical/index core models.
4. `W1-003` — Agent/AgentName/ExternalIdentifier/Contribution and provenance assertion model.
5. `W1-004`/`W1-005` — e-book and music entity models, including Series, MusicWork and ReleaseGroup.
6. `W1-006` — Classification/Fingerprint/Relation/Evidence/version concepts.
7. `W1-007` — select/document SQLite migration mechanism.
8. `W1-008`/`W1-009` — persistence implementation and tests.
9. `W1-010` — synchronize documentation/status and close W1.

Do not start W5 external provider implementation before the W1 provenance/provider-independent core contracts exist.

## Open decisions

- Project license (`W0-007`). This does not block W1 internal development.
- Concrete SQLite migration library/mechanism (`W1-007`). Decide during W1 and record an ADR.
- Concrete third-party media libraries: decide in W3/W4 after current maintenance/license review.
- Concrete provider adapters/access modes: decide in W5B after reviewing current provider terms, bulk/API options and cache rules.
- Matching thresholds: decide/calibrate in W6 using controlled fixtures.

## Safety gate

W10 remains explicitly blocked. No source-media mutation is authorized by current architecture decisions.

W9 may create non-executable consolidation plans only.
