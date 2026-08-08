# Project Status

Last updated: 2026-08-08

## Current wave

**W1 — Core + Persistence**

W0 is complete. FolioTone now has a verified Python/Docker bootstrap plus the first concrete provider- and tool-independent core implementation.

The orchestration-first rule remains authoritative: specialist tools produce versioned evidence through replaceable ToolProvider contracts; FolioTone owns provenance, reconciliation, identity, review, and safety.

## Verification state

GitHub Actions run `31279709278` on PR #3 verified the current core slice and the W0 Docker acceptance criteria:

```text
Install                      PASS
Ruff                         PASS
Mypy                         PASS
Pytest                       PASS
Prepare Docker placeholders  PASS
Docker build                 PASS
Docker bootstrap/status      PASS
```

The first CI attempt on this branch failed only on Ruff formatting (`E501` and `datetime.UTC` modernization). Those three style findings were corrected before the successful run above.

`W0-006` is therefore complete.

## Implemented in the current W1 core slice

### Internal identity and validation

- opaque UUID-backed `EntityId` for FolioTone-owned identity;
- external IDs remain separate namespaced records;
- immutable/slotted dataclasses for core entities;
- timezone-aware datetime validation;
- bounded confidence values;
- safe scan-root-relative path normalization;
- ADR-0011 records the concrete identity/core-model decisions.

### Physical/index core

- `ScanRoot`;
- `ScanRun`;
- `FileRecord`;
- `FileObservation`;
- media/presence/scan-state enums.

Absolute host paths remain configuration concerns rather than durable domain identity.

### Provenance and authority

- `Provenance`;
- `ValueAssertion` with `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL`, `USER_CONFIRMED` states;
- `Agent` / `AgentName` / `AgentType`;
- `ExternalIdentifier`;
- `Contribution` / typed role strings.

### E-book identity

- `Work`;
- `Edition`;
- `Series`;
- `SeriesMembership` with explicit Work/Edition level.

### Music identity

- `MusicWork`;
- `MusicWorkRelation`;
- `CatalogDesignation`;
- `Recording`;
- `ReleaseGroup`;
- `Release`;
- `ReleaseRecording`.

### Classification and matching evidence

- `ClassificationAssertion`;
- `Fingerprint` with algorithm/version and optional ToolExecution link;
- `Relation`;
- `Evidence`;
- relation and review/match status enums.

### ToolProvider contracts

- `ToolProviderDescriptor`;
- `ToolExecution`;
- `ToolResult`;
- read-only `ToolCapability` vocabulary;
- explicit tool version + adapter version + input/config identities;
- terminal execution-state validation;
- write-capable ToolProviders rejected by the W1 contract through W9.

See `docs/planning/W1_CORE_IMPLEMENTATION.md`.

## Still not implemented

W1 is **not** complete yet. The next persistence slice is still required:

- SQLite migration mechanism (`W1-007`);
- persistence contracts/repositories (`W1-008`);
- migration, round-trip, constraint, provenance, and failure-mode tests (`W1-009`);
- final W1 documentation/status closure (`W1-011`).

Later waves remain unimplemented:

- generic ToolProvider execution runtime;
- incremental filesystem scanner/hash pipeline;
- filename/path parsing;
- calibre/ffprobe/fpcalc/beets/SongKong/Picard adapters;
- e-book content analysis;
- authority/entity resolution engine;
- external knowledge providers;
- classification engine;
- matching engine;
- review system;
- Calibre library reconciliation;
- consolidation planning/execution.

## Next implementation sequence

1. `W1-007` — select and implement the SQLite migration mechanism and record the decision in an ADR.
2. `W1-008` — implement provider-independent persistence contracts and SQLite repositories.
3. `W1-009` — add migration/round-trip/constraint/failure tests using temporary databases.
4. `W1-011` — synchronize schema/domain documentation and close W1.
5. Start W2 with incremental indexing plus the generic ToolProvider execution runtime.

## Open decisions

- Project license (`W0-007`) remains open but does not block internal development.
- SQLite migration approach is the immediate W1 decision.
- Exact process/container ToolProvider runtime belongs to W2.
- Concrete e-book/music tool compositions belong to W3/W4 after current license/maintenance/security review.
- External knowledge-provider adapters belong to W5 after current terms/API/bulk/cache review.
- Matching thresholds belong to W6 calibration.

## Safety gate

W10 remains explicitly blocked. No FolioTone-native or external-tool source-media mutation is authorized.

W9 may create non-executable consolidation plans only.
