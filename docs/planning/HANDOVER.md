# Handover / Continuation Guide

## One-minute orientation

FolioTone is an orchestration and reconciliation platform for large e-book and music collections. It combines filesystem evidence, mature specialist tools, metadata services, authority resolution, classification and content/audio fingerprints into one provenance-preserving evidence model.

It is intentionally non-destructive during W0–W9.

Current repository state: **W0 is fully verified; W1 core domain and ToolProvider contracts are implemented; SQLite persistence is next.**

## Do this next

1. Read `AGENTS.md`.
2. Read `PROJECT_STATUS.md` and confirm it still matches repository reality.
3. Read `W1_CORE_IMPLEMENTATION.md` and ADR-0011 before changing the concrete core model.
4. Implement `W1-007`: choose the SQLite migration mechanism and record it in an ADR.
5. Implement `W1-008`: provider-independent persistence contracts plus SQLite repositories.
6. Implement `W1-009`: temporary-database migration/round-trip/constraint/failure tests.
7. Update schema/domain/status docs and mark `W1-011` done only when W1 persistence is actually complete.
8. Do not start concrete calibre/ffprobe/fpcalc/beets/SongKong/Picard adapters before the generic W2 ToolProvider execution runtime exists.

## Verified baseline

GitHub Actions run `31279709278` passed:

```text
Install
Ruff
Mypy
Pytest
Docker build
Docker bootstrap/status
```

This closes the W0 Docker verification gate.

## Implemented W1 core

Provider/tool-independent immutable models now exist for:

- ScanRoot / ScanRun / FileRecord / FileObservation;
- Provenance / ValueAssertion;
- Agent / AgentName / ExternalIdentifier / Contribution;
- Work / Edition / Series / SeriesMembership;
- MusicWork / MusicWorkRelation / CatalogDesignation;
- Recording / ReleaseGroup / Release / ReleaseRecording;
- ClassificationAssertion / Fingerprint / Relation / Evidence;
- ToolProviderDescriptor / ToolExecution / ToolResult.

Internal identity uses opaque UUID-backed `EntityId`; external catalog/provider IDs remain separate evidence.

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

## External tools and knowledge

Read `docs/reference/EXTERNAL_TOOLS.md` before implementing media-specific capabilities and `docs/reference/EXTERNAL_DATA_SOURCES.md` before implementing knowledge-provider adapters.

Candidate tools/providers are not automatically dependencies. Re-check current maintenance, license, API/CLI/container interfaces, output formats and security behavior before implementing an adapter.

## What not to assume

- SQLite schema/migrations are not implemented yet.
- Persistence table decomposition is not frozen until W1 persistence lands.
- Generic ToolProvider process/container execution belongs to W2, not W1.
- Concrete media tools are still candidates; commercial tools remain optional.
- Matching/entity-resolution thresholds are not calibrated yet.
- OCR, perceptual cover hashing, quality ranking and consolidation execution are later work.

## Handover quality rule

At the end of a substantial work session, update `PROJECT_STATUS.md` and `BACKLOG.md` so the next agent can continue without previous chat history. Never claim verification that was not actually executed.
