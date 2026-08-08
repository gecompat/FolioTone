# W1 Core Implementation Notes

This document records the concrete W1 core slice implemented before SQLite persistence.

## Internal identity

- all FolioTone-owned entities use opaque UUID-backed `EntityId` values;
- external provider/catalog identifiers are separate namespaced `ExternalIdentifier` records;
- an external ID is evidence/cross-reference, never the FolioTone primary key.

See `ADR-0011-internal-identifiers-and-core-model.md`.

## Implemented model groups

### Physical/index

- `ScanRoot`
- `ScanRun`
- `FileRecord`
- `FileObservation`

Absolute host paths deliberately remain outside the domain model. `FileRecord.relative_path` is normalized relative to a `ScanRoot`.

### Provenance/value

- `Provenance`
- `ValueAssertion`
- states `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL`, `USER_CONFIRMED`

### Authority/contributors

- `Agent`
- `AgentName`
- `ExternalIdentifier`
- `Contribution`

### E-books

- `Work`
- `Edition`
- `Series`
- `SeriesMembership`

### Music

- `MusicWork`
- `MusicWorkRelation`
- `CatalogDesignation`
- `Recording`
- `ReleaseGroup`
- `Release`
- `ReleaseRecording`

### Classification/matching evidence

- `ClassificationAssertion`
- `Fingerprint`
- `Relation`
- `Evidence`
- relation/match status enums

### Tool orchestration contracts

- `ToolProviderDescriptor`
- `ToolExecution`
- `ToolResult`
- read-only `ToolCapability` vocabulary

Tool-derived facts reference an exact execution identity and therefore remain attributable to a concrete tool version + adapter version.

## Validation invariants

The initial domain constructors enforce important safety/correctness boundaries:

- timezone-aware datetimes;
- bounded confidence values;
- safe scan-root-relative file paths;
- no self-relations for MusicWork/Relation objects;
- positive disc/track positions;
- explicit WORK/EDITION level for series membership;
- terminal ToolExecution states require a finish timestamp;
- ToolProviders cannot declare write-enabled operation before W10.

## Deferred to the next W1 slice

- SQLite migration mechanism (`W1-007`);
- persistence interfaces/repositories (`W1-008`);
- persistence/migration/constraint tests (`W1-009`);
- final W1 documentation/status closure (`W1-011`).

Concrete ToolProvider process/container execution remains W2; W1 only defines provider-neutral contracts and provenance.
