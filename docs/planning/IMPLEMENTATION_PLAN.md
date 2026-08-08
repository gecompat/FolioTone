# Implementation Plan

This file defines the planned development sequence. `PROJECT_STATUS.md` states where the project currently is.

## W0 — Project Foundation

Scope:

- repository/package structure;
- Docker baseline with persistent `/data` and read-only media mounts;
- architecture and ADRs;
- AI/contributor handover rules;
- test/quality-tool bootstrap;
- project status and backlog.

Acceptance:

- repository contains no real media/runtime/private data;
- package imports and bootstrap CLI work;
- CI/quality checks are defined;
- another agent can identify W1 and its acceptance criteria without prior chat context.

## W1 — Core + Persistence

Implement core models/contracts and SQLite persistence **before** format analyzers or provider adapters.

Mandatory physical/index concepts:

- `File`, `ScanRoot`, `ScanRun`, `FileObservation`;
- `Fingerprint` and algorithm/version metadata;
- analysis/version state required to detect stale derived data.

Mandatory provenance/authority concepts:

- `Agent`, `AgentName`, `AgentType`;
- `ExternalIdentifier` with namespace/provider;
- typed `Contribution`/credit relationships;
- provenance-preserving value/assertion model capable of distinguishing `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL`, `USER_CONFIRMED`;
- candidate/resolution metadata without embedding provider-specific schemas.

Mandatory e-book concepts:

- `Work`, `Edition`;
- `Series`, `SeriesMembership`.

Mandatory music concepts:

- `MusicWork`, `MusicWorkRelation`, `CatalogDesignation`;
- `Recording`, `ReleaseGroup`, `Release`, `ReleaseRecording`.

Mandatory classification/matching concepts:

- multidimensional classification assertions/facets with provenance;
- `Relation`, `Evidence`, match/review status concepts;
- version metadata for normalization/resolution/classification/matching derived logic.

Persistence requirements:

- migration mechanism from the first real schema onward;
- repository/service boundaries that do not expose SQLite internals to domain logic;
- deterministic tests using temporary databases;
- timestamps stored consistently (prefer UTC at persistence boundaries);
- provider/cache/runtime state remains outside Git and does not require absolute private paths in exported domain data.

Acceptance:

- models capture the distinctions documented in `DOMAIN_MODEL.md` and ADR-0006 through ADR-0009;
- source observations can coexist with normalized/external/canonical values without overwrite;
- schema represents book and music identity levels without Calibre/MusicBrainz/OpenLibrary-specific coupling;
- migrations and round-trip persistence tests pass;
- no media mutation capability exists.

## W2 — Incremental File Index + Filename/Path Context

Implement scan roots/runs, discovery, observations, incremental comparison, streamed hashing, and state transitions.

Also introduce provenance-preserving filename/path parsing that emits `FieldCandidate` values without setting canonical metadata.

Acceptance includes tests for:

- new/unchanged/modified files;
- move/rename candidates;
- unavailable scan root vs. true absence;
- interrupted/resumed scans;
- large-file hashing with bounded memory;
- no unnecessary full re-hash for unchanged files;
- representative filename/path parsing conventions;
- parser version/provenance retained for derived candidates.

## W3 — E-Book Analyzer

Priority:

1. EPUB;
2. PDF;
3. MOBI/AZW/AZW3 as feasible.

Separate raw extracted metadata, normalized/derived assertions and canonical domain entities.

Planned fingerprints:

- file SHA-256;
- format/content fingerprint;
- normalized text fingerprint where text is available;
- later cover/image perceptual fingerprint as optional evidence.

Extract useful identifiers/credits/series information as observations/candidates rather than directly declaring canonical identity.

OCR is out of the first implementation. Scanned PDFs without text should be represented explicitly rather than silently OCRed.

## W4 — Music Analyzer

Extract common tags and technical properties such as codec, duration, sample rate, bit depth/channels/bitrate where available.

Extract observed identifiers including MusicBrainz IDs, ISRC, ISWC, barcode and catalog designations when present.

Model composer/performer/conductor/etc. credits as candidate relationships rather than a single artist field.

Provide an `AudioFingerprintProvider` boundary. Acoustic fingerprint integration may initially be a stub; exact/audio-stream fingerprints can precede it.

The analyzer must not collapse MusicWork, Recording, ReleaseGroup and Release identity levels.

## W5 — Authority, Entity Resolution, Enrichment and Classification

Implement the layer described in `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`.

### W5A — Local normalization and authority resolution

- Unicode/name normalization with versioning;
- canonical/sort/alias/pseudonym/credited-as name handling;
- homonym-safe Agent candidate resolution;
- Work/Edition/MusicWork/Recording/ReleaseGroup/Release candidate resolution;
- confirmed local alias/rejection knowledge;
- explanation/confidence/provenance for every non-trivial resolution.

### W5B — External provider infrastructure

- provider interface/DTO boundary;
- explicit modes: `OFFLINE`, `LOCAL_DATASETS`, `ONLINE_STRUCTURED`, `ONLINE_WEB_RESEARCH`;
- persistent cache/import state under `/data`;
- rate/access/licensing metadata in provider documentation;
- minimum-data privacy rules for outgoing queries;
- failure/offline behavior that does not break ordinary rescans.

Initial provider candidates are documented in `docs/reference/EXTERNAL_DATA_SOURCES.md`. Concrete adapters are selected only after current maintenance/licensing/access review.

High-value candidates:

Books/authority:
- Open Library;
- GND/DNB;
- Wikidata.

Music:
- MusicBrainz;
- AcoustID/Chromaprint.

For large-scale provider data, prefer official local/bulk access where suitable rather than permanent per-file online lookup.

### W5C — Classification

- typed multidimensional classification assertions;
- provider/local taxonomy context;
- classical domain vs. period distinction;
- forms/work types/instrumentation where available;
- conflicting provider classifications retained rather than overwritten.

Acceptance emphasizes traceability, offline/cache behavior, privacy and false-identity protection.

## W6 — Matching Engine

Implement:

- duplicate/relation taxonomy;
- candidate generation/blocking;
- feature extraction;
- versioned scoring/rules;
- explainable evidence;
- classification and confidence/review status.

Matching consumes resolved identities as evidence but must still consider independent file/content/audio evidence.

Never perform global all-vs-all matching across the entire collection.

Acceptance emphasizes false-positive protection and clear distinction between:

E-books:
- exact file/content;
- same Edition;
- same Work/different Edition.

Music:
- same MusicWork/different Recording;
- same Recording;
- same ReleaseGroup;
- same concrete Release;
- transcode/quality/release variants.

## W7 — Review

Implement persisted review queues and decisions for both entity resolution and duplicate matching:

- accept/reject/defer;
- relation-specific decisions;
- authority candidate confirmation/rejection;
- alias/canonical-name confirmation;
- decision history and resolver/matcher/evidence context;
- prevention of needless repeated review for unchanged cases.

Review decisions may create durable local authority knowledge without rewriting source observations.

## W8 — Calibre Adapter

Read-only integration:

- locate/read Calibre library metadata as configured;
- map Calibre records into adapter DTOs/core-compatible observations;
- detect files unknown to Calibre, Calibre records without files, duplicates, metadata inconsistencies and authority conflicts;
- use Calibre as one evidence source, not the canonical database;
- never require Calibre for normal FolioTone operation.

## W9 — Consolidation Planning

Create non-executable `ConsolidationPlan` data from confirmed/reviewed relations. Plans may describe KEEP and candidate operations but must be marked non-executable.

Identity and quality are separate inputs: a future quality evaluator may rank which equivalent representation is preferable only after identity is established.

Acceptance:

- plans record evidence and preconditions;
- plans cannot mutate the filesystem;
- changed-since-analysis requirements are represented for future W10;
- no single provider/AI/web inference can justify a destructive candidate by itself.

## W10 — Controlled Consolidation (future, gated)

Do not implement until a new ADR explicitly accepts write-capable behavior.

Potential operations: copy, move, rename, hardlink/reflink where supported, metadata update, delete. All require explicit safety design, revalidation, audit, collision handling, and failure semantics.

## Cross-cutting future extensions

These do not block the first end-to-end pipeline but should remain architecturally possible:

- cover/image perceptual fingerprints for editions/releases;
- e-book structural/quality assessment;
- audio quality/corruption assessment;
- more external authority/catalog providers;
- local bulk authority indexes and incremental provider dataset refresh;
- rule learning from review history before considering more complex ML;
- generic web research as a separately controlled fallback when structured sources are insufficient.
