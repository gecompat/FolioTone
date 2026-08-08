# Architecture Overview

## Purpose

FolioTone is designed to analyze large e-book and music collections, identify real-world entities, enrich uncertain metadata from controlled external knowledge sources, classify content, identify relations/duplicate candidates using multiple evidence sources, support human review, and later produce controlled consolidation plans.

The architecture separates physical files, raw observations, normalized/derived metadata, authority identities, canonical domain entities, external assertions, matching evidence, review decisions, and future filesystem actions.

## Components

### Core

Owns domain concepts and interfaces that must not depend on specific file formats, Calibre, external provider schemas, Docker, CLI frameworks, or a concrete database implementation.

### Persistence

Initially implements SQLite-backed storage for core/index/authority/enrichment/matching/review state. Callers should depend on persistence contracts rather than SQLite details.

### Index

Discovers files, records observations, detects incremental changes, and calculates generic hashes/fingerprints. It does not decide that two works or recordings are equivalent.

### Filename / Path Context

Parses filenames and directory context into provenance-preserving field candidates. It may infer likely author/artist/title/series/track/year/language tokens but does not set canonical values directly.

### E-Book Analyzer

Extracts metadata and content features from EPUB, PDF, MOBI/AZW-family formats in staged priority order. Format-specific code stays here.

### Music Analyzer

Extracts tags and technical audio properties, then later audio-stream/acoustic fingerprints. It does not own authority-resolution or matching policy.

### Authority / Entity Resolution

Resolves inconsistent names, aliases, pseudonyms, credited-as forms, external identifiers, works and releases into candidate canonical identities while retaining all source observations.

This component answers identity questions such as whether `Asimov, I.` and `Isaac Asimov` plausibly refer to the same Agent. It does not itself decide that two media files are duplicates.

### Enrichment Providers

Adapters integrate structured external knowledge and optional generic web research. Providers return provenance-preserving assertions/candidates rather than overwriting core entities.

Provider use is mode-controlled (`OFFLINE`, `LOCAL_DATASETS`, `ONLINE_STRUCTURED`, `ONLINE_WEB_RESEARCH`) and cached under `/data`.

### Classification

Stores multidimensional typed facets with provenance instead of a single flat genre field. Provider classifications can coexist until canonical/local classification rules decide what to expose.

### Matching

Generates plausible candidates using blocking/indexes, derives features, scores evidence, classifies relations, and records explanations and version information.

Matching consumes resolved identities as evidence together with hashes, embedded metadata, content/audio fingerprints, release/edition structure and other signals.

### Review

Queues uncertain entity-resolution and matching cases and persists human decisions. A decision should prevent identical cases from being repeatedly presented without a reason such as changed evidence, resolver version or matcher version.

Review can create durable local knowledge such as confirmed aliases or rejected external candidates.

### Consolidation

W9 only plans possible actions. No executable source-media mutation exists before W10 and an explicit architecture decision.

### Adapters

Integrate external systems. Calibre is read-only initially and must not leak its database schema into the core domain model. External authority/music/book providers follow the same adapter boundary.

## Dependency rule

Domain logic is inward-facing. Concrete storage, file formats, CLI, Calibre, external provider APIs and web research adapt to core contracts rather than defining them.

Allowed high-level dependency direction:

```text
cli -> application/core interfaces
index -> core + persistence interfaces
filename/path parsing -> core candidate contracts
analyzers -> core observation contracts
authority/resolution -> core + observations + provider interfaces
enrichment providers -> core provider contracts
classification -> core + resolved/external assertions
matching -> core + analyzer/index/resolution outputs
review -> core + resolution/matching + persistence interfaces
consolidation -> core + reviewed/planned decisions
persistence -> core persistence contracts
```

## Data flow

```text
ScanRoot
  -> ScanRun / FileObservation
  -> File identity + generic fingerprints
  -> filename/path candidates
  -> media analyzer observations
  -> normalized/derived assertions
  -> authority/entity-resolution candidates
  -> optional local/external enrichment
  -> canonical identity candidates + classifications
  -> duplicate/relation candidate generation
  -> scoring + evidence
  -> relation proposal
  -> automatic threshold or review queue
  -> persisted decision/local knowledge
  -> future non-executable ConsolidationPlan
```

## Important identity levels

E-book:

```text
Agent --role--> Work -> Edition -> File
                    \
                     -> SeriesMembership
```

Music:

```text
Agent --role--> MusicWork -> Recording -> ReleaseRecording -> Release -> ReleaseGroup
```

The arrows are conceptual relationships, not ownership constraints; especially in music, many-to-many relationships are expected.

## Scalability assumptions

The collection may contain hundreds of thousands of files and multiple terabytes. Therefore:

- scans must be incremental;
- hashes must be streamed;
- expensive work must be cached/versioned;
- local authority indexes should avoid repeated internet requests;
- bulk provider datasets should be considered when officially supported/recommended for large-scale access;
- candidate generation must reduce pair comparisons before scoring;
- missing storage must not be confused with deletion;
- analysis must be resumable and observable;
- external provider outages must not make ordinary rescans impossible.

## Privacy assumptions

- source media stays read-only through W9;
- runtime databases/caches remain outside Git;
- absolute local paths are not sent to external providers;
- provider requests use the minimum structured information needed;
- generic web research is a separately controlled fallback, not an implicit side effect of scanning.

See `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`, `SAFETY.md` and `docs/reference/EXTERNAL_DATA_SOURCES.md`.
