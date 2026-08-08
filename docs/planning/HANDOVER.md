# Handover / Continuation Guide

## One-minute orientation

FolioTone will analyze large e-book and music collections and identify real-world entities/duplicates using filesystem evidence, metadata, filename/path context, authority resolution, controlled external enrichment, classification and content/audio fingerprints.

It is intentionally non-destructive during W0–W9.

Current repository state: **W0 foundation migrated and architecture expanded; bootstrap/CI verification is the immediate next task.**

## Do this next

1. Read `AGENTS.md`.
2. Read `PROJECT_STATUS.md` and confirm it still matches repository reality.
3. Read `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md` and ADR-0006 through ADR-0009 before changing the W1 model.
4. Ensure the documented CI workflow is installed at `.github/workflows/ci.yml`; the current ChatGPT GitHub connector blocked that single workflow-path write during migration.
5. Run/inspect W0 verification (`ruff`, `mypy`, `pytest`, Docker bootstrap). Mark `W0-006` done only after actual verification.
6. Start W1 with `W1-001`: turn the expanded conceptual model in `DOMAIN_MODEL.md` into concrete Python model/contracts without introducing SQLite, Calibre, Open Library, MusicBrainz or other provider schemas into the domain layer.
7. Keep `BACKLOG.md` and `PROJECT_STATUS.md` synchronized in every coherent implementation change.

## Non-negotiable constraints

- Python; Docker/Linux primary runtime.
- Host-persistent `/data`.
- Source media mounted read-only.
- Analysis only through W9.
- Calibre read-only adapter, external to core.
- Incremental indexing; bounded-memory processing.
- Filename/path parsing emits candidates, not canonical values.
- Authority/Entity Resolution is separate from duplicate Matching.
- Observed/derived/external/canonical/user-confirmed values keep provenance.
- Authors/artists/composers are Agent identities + role relationships, not plain canonical strings.
- MusicWork, Recording, ReleaseGroup and Release are distinct identity levels.
- Classification is multidimensional and provenance-preserving.
- External provider/network use is explicit, cached and privacy-bounded; never transmit absolute local paths.
- Candidate generation before expensive matching.
- Explainable/versioned evidence for resolution and matches.
- W10 write operations are blocked until a future accepted ADR.

## External knowledge

Initial provider candidates are documented in `docs/reference/EXTERNAL_DATA_SOURCES.md`.

Do not implement a provider adapter from memory alone. Before coding it, re-check current official documentation for:

- access/API/bulk options;
- licensing/attribution;
- caching/redistribution rules;
- rate/request constraints;
- authentication/credentials;
- current entity/schema behavior.

Provider data becomes provenance-preserving evidence; it does not overwrite observations.

## What not to assume

- The conceptual model field list is not yet a frozen database schema.
- The exact generic assertion/provenance table/class decomposition is not yet decided.
- Matching or entity-resolution thresholds are not yet calibrated.
- Third-party EPUB/PDF/audio libraries have not yet been selected.
- External provider adapters have not yet been selected/implemented.
- OCR is not part of the first PDF analyzer.
- Acoustic fingerprinting may begin behind a provider interface/stub.
- Cover perceptual hashing and quality ranking are future extensions, not W1 blockers.
- A public GitHub repository does not imply that a project license has been granted.

## Handover quality rule

At the end of work, update `PROJECT_STATUS.md` so the next agent can continue without access to your conversation, private scratchpad, or unstaged local state.
