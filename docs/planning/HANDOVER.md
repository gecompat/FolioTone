# Handover / Continuation Guide

## One-minute orientation

FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It combines filesystem evidence, mature specialist tools, metadata services, filename/path context, authority resolution, classification and content/audio fingerprints into one provenance-preserving evidence model.

It is intentionally non-destructive during W0–W9.

Current repository state: **W0 foundation complete except Docker bootstrap verification; orchestration-first ToolProvider architecture is accepted and documented.**

## Do this next

1. Read `AGENTS.md`.
2. Read `PROJECT_STATUS.md` and confirm it still matches repository reality.
3. Read `DOMAIN_MODEL.md`, `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`, ADR-0006 through ADR-0010.
4. Read `docs/reference/EXTERNAL_TOOLS.md` before implementing any specialist e-book/music capability.
5. Inspect the FolioTone GitHub Actions workflow at `.github/workflows/ci.yml` and its latest run.
6. Complete W0 Docker bootstrap verification. Mark `W0-006` done only after actual verification.
7. Start W1 with `W1-001`: turn the expanded conceptual model into concrete Python contracts without introducing SQLite, calibre, beets, SongKong, Picard, FFmpeg, MusicBrainz or other tool/provider schemas into the domain layer.
8. Include ToolExecution/tool-version provenance before closing W1.
9. Keep `BACKLOG.md` and `PROJECT_STATUS.md` synchronized in every coherent implementation change.

## Product description

Long form:

> FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It connects proven specialist tools and metadata services, normalizes their results into provenance-preserving evidence, resolves identities, detects duplicates and quality/completeness issues, supports review, and produces safe consolidation plans.

Short form:

> Orchestrate specialist tools to reconcile, analyze, and deduplicate e-book and music collections.

## Non-negotiable constraints

- Python; Docker/Linux primary runtime.
- Host-persistent `/data`.
- Source media mounted read-only.
- Analysis only through W9.
- Orchestration first: evaluate mature specialist tools before native reimplementation.
- External specialist tools remain replaceable ToolProviders; their outputs are Evidence, not canonical truth.
- Calibre read-only integration, external to core.
- Incremental indexing; bounded-memory processing.
- Filename/path parsing emits candidates, not canonical values.
- Authority/Entity Resolution is separate from duplicate Matching.
- Observed/derived/external/canonical/user-confirmed values keep provenance.
- Tool-derived values also keep ToolExecution/tool/adapter/parser provenance.
- Authors/artists/composers are Agent identities + role relationships, not plain canonical strings.
- MusicWork, Recording, ReleaseGroup and Release are distinct identity levels.
- Classification is multidimensional and provenance-preserving.
- External knowledge-provider/network use is explicit, cached and privacy-bounded; never transmit absolute local paths.
- Candidate generation before expensive matching.
- Explainable/versioned evidence for resolution and matches.
- W10 write operations are blocked until a future accepted ADR.
- External tool delete/move/rename/retag/write commands are covered by the same W10 gate.

## External specialist tools

Initial candidate ToolProviders are documented in `docs/reference/EXTERNAL_TOOLS.md`.

High-value current candidates:

- calibre CLI / Content Server;
- FFmpeg / `ffprobe`;
- Chromaprint / `fpcalc`;
- beets;
- SongKong;
- Picard as optional validator;
- local MusicBrainz mirror later if scale justifies it.

Before implementing an adapter, re-check current official documentation for:

- maintenance/version status;
- license and redistribution constraints;
- official CLI/API/service/container interface;
- machine-readable output;
- supported architectures/resources;
- read/write behavior and safe analysis mode;
- timeout/failure semantics;
- security/privacy implications.

Do not reverse-engineer internal GUI/web endpoints when a stable documented interface is unavailable.

## External knowledge

Initial knowledge-provider candidates are documented in `docs/reference/EXTERNAL_DATA_SOURCES.md`.

Before coding a knowledge-provider adapter, re-check current official documentation for:

- access/API/bulk options;
- licensing/attribution;
- caching/redistribution rules;
- rate/request constraints;
- authentication/credentials;
- current entity/schema behavior.

Provider data becomes provenance-preserving evidence; it does not overwrite observations.

## What not to assume

- The conceptual model field list is not yet a frozen database schema.
- The exact ToolExecution/assertion/provenance class/table decomposition is not yet decided.
- Matching or entity-resolution thresholds are not yet calibrated.
- Candidate tools in `EXTERNAL_TOOLS.md` are not automatically dependencies.
- SongKong or other commercial tools must remain optional unless a future ADR explicitly changes the baseline.
- Third-party EPUB/PDF/native libraries have not yet been selected because W3 now evaluates calibre/tool reuse first.
- OCR is not part of the first PDF analyzer.
- Cover perceptual hashing and quality ranking are future extensions, not W1 blockers.
- A public GitHub repository does not imply that a project license has been granted.

## Handover quality rule

At the end of work, update `PROJECT_STATUS.md` so the next agent can continue without access to your conversation, private scratchpad, or unstaged local state. Record which tool/provider versions changed whenever that affects stale derived data.
