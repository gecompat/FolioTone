# Implementation Plan

This file defines the planned development sequence. `PROJECT_STATUS.md` states where the project currently is.

Under ADR-0016, the initial product surface remains CLI-only. W3 and the following early vertical slices do not add a web API, desktop interface or dashboard layer. The CLI stays a thin adapter to application/core contracts.

## W0 — Project Foundation

Scope:

- repository/package structure;
- Docker baseline with persistent `/data` and read-only media mounts;
- architecture and ADRs;
- AI/contributor handover rules;
- test/quality-tool bootstrap;
- project status and backlog;
- orchestration-first ToolProvider architecture and external-tool registry.

Acceptance:

- repository contains no real media/runtime/private data;
- package imports and bootstrap CLI work;
- CI/quality checks are defined;
- tool orchestration and safety boundaries are documented;
- another agent can identify W1 and its acceptance criteria without prior chat context.

## W1 — Core + Persistence

Implement core models/contracts and SQLite persistence **before** media analyzers, ToolProvider adapters or external knowledge-provider adapters.

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

Mandatory tool-provenance concepts:

- adapter-neutral ToolProvider/tool identity/capability metadata;
- `ToolExecution`-like execution provenance with tool version, adapter/parser version, operation/profile, timestamps and execution state;
- artifact/result references where structured tool output must remain traceable;
- explicit distinction between a tool's capability and FolioTone authorization to execute that capability.

Exact class/table names remain a W1 design decision; the traceability semantics are mandatory.

Mandatory e-book concepts:

- `Work`, `Edition`;
- `Series`, `SeriesMembership`.

Mandatory music concepts:

- `MusicWork`, `MusicWorkRelation`, `CatalogDesignation`;
- `Recording`, `ReleaseGroup`, `Release`, `ReleaseRecording`.

Mandatory classification/matching concepts:

- multidimensional classification assertions/facets with provenance;
- `Relation`, `Evidence`, match/review status concepts;
- version metadata for normalization/resolution/classification/matching/tool-derived logic.

Persistence requirements:

- migration mechanism from the first real schema onward;
- repository/service boundaries that do not expose SQLite, external tool or external provider internals to domain logic;
- deterministic tests using temporary databases;
- timestamps stored consistently (prefer UTC at persistence boundaries);
- provider/tool cache/runtime state remains outside Git and does not require absolute private paths in exported domain data.

Acceptance:

- models capture the distinctions documented in `DOMAIN_MODEL.md` and ADR-0006 through ADR-0010;
- source observations can coexist with tool-derived/normalized/external/canonical values without overwrite;
- schema represents book and music identity levels without Calibre/beets/SongKong/Picard/MusicBrainz/OpenLibrary-specific coupling;
- ToolProvider-derived Evidence can be traced to a versioned execution;
- migrations and round-trip persistence tests pass;
- no media mutation capability exists.

## W2 — Incremental File Index + Filename/Path Context + Tool Runtime

Implement scan roots/runs, discovery, observations, incremental comparison, streamed hashing, and state transitions.

Also introduce:

- provenance-preserving filename/path parsing that emits `FieldCandidate` values without setting canonical metadata;
- a generic ToolProvider runtime for safe bounded execution before W3/W4 specialist adapters are implemented.

Tool runtime responsibilities:

- tool discovery/capability/version detection;
- subprocess/container-job execution with explicit inputs;
- timeout/cancellation/error handling;
- stdout/stderr/structured result/artifact capture;
- isolated writable work directories;
- read-only media mount policy;
- selective re-analysis based on input + tool/adapter/config versions.

Acceptance includes tests for:

- new/unchanged/modified files;
- move/rename candidates;
- unavailable scan root vs. true absence;
- interrupted/resumed scans;
- large-file hashing with bounded memory;
- no unnecessary full re-hash for unchanged files;
- representative filename/path parsing conventions;
- parser version/provenance retained for derived candidates;
- missing tool, non-zero exit, timeout and malformed result behavior;
- no external-tool source mutation through the standard runtime.

## W3 — E-Book Analysis / Orchestration

Do **not** start by writing EPUB/PDF/MOBI parsers from scratch.

First evaluate maintained specialist capabilities, especially calibre CLI, plus targeted format validators/tools where appropriate. Document reuse/rejection decisions with current maintenance/licensing/security information.

Implemented sequence and decisions through `W3-006`:

1. calibre `ebook-meta` as a fixed read-only metadata extraction vertical slice;
2. fixed calibre `ebook-convert` EPUB text plus a FolioTone-owned fingerprint;
3. fixed Poppler PDF metadata/page/text analysis;
4. reuse the same calibre contracts for an explicit MOBI/AZW/AZW3 extension;
5. retain raw OPF 2/3 observations and project versioned, grouped candidates
   for identifiers, contributors/roles/sort names, language, publisher,
   publication date, series and other fields with exact execution/observation
   links;
6. defer read-oriented `calibredb` integration until W8 provides a concrete
   Library-Reconciliation contract.

Separate raw tool/analyzer observations, normalized/derived assertions and canonical domain entities.

Planned evidence includes:

- file SHA-256;
- format/content fingerprint;
- normalized text fingerprint where text is available;
- metadata/tool disagreement;
- later cover/image perceptual fingerprint;
- later structural validation and content-diff/quality evidence.

OCR is out of the first implementation. Scanned PDFs without text should be represented explicitly rather than silently OCRed.

Acceptance requires ToolExecution provenance and tests showing that tool results do not directly become canonical truth.

## W4 — Music Analysis / Orchestration

Do **not** rebuild a complete tagger/fingerprinter ecosystem.

Evaluate and integrate specialist tools in layers:

### W4A — Technical/audio fingerprint baseline

- `ffprobe` for machine-readable container/stream/codec/duration/sample-rate/channel/bitrate observations and probe failures;
- Chromaprint/`fpcalc` behind `AudioFingerprintProvider` for acoustic fingerprints;
- record tool/algorithm versions for selective invalidation.

### W4B — Library/music metadata specialist evidence

Evaluate:

- beets for MusicBrainz-oriented matching, duplicate and missing/completeness evidence;
- SongKong for optional status/report/preview evidence and classical/music metadata analysis;
- MusicBrainz Picard as an optional independent validator/specialist through documented executable commands.

Commercial/optional tools must remain optional unless a later ADR changes the baseline.

### W4C — FolioTone-native gap logic

Implement native logic only for capabilities not adequately handled by the selected tool chain or where FolioTone needs differentiated semantics/performance.

The analyzer/orchestration layer must not collapse MusicWork, Recording, ReleaseGroup and Release identity levels even if an external tool does.

Acceptance includes cross-tool disagreement fixtures and proof that write-capable external commands are not reachable through W0-W9 paths.

## W5 — Authority, Entity Resolution, Enrichment and Classification

Implement the layer described in `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`.

### W5A — Local normalization and authority resolution

- Unicode/name normalization with versioning;
- canonical/sort/alias/pseudonym/credited-as name handling;
- homonym-safe Agent candidate resolution;
- Work/Edition/MusicWork/Recording/ReleaseGroup/Release candidate resolution;
- confirmed local alias/rejection knowledge;
- explanation/confidence/provenance for every non-trivial resolution;
- consume ToolProvider evidence without trusting any one tool as canonical authority.

### W5B — External knowledge-provider infrastructure

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
- AcoustID.

For large-scale provider data, prefer official local/bulk access where suitable rather than permanent per-file online lookup. A local MusicBrainz mirror is a later scale-dependent option, not an MVP requirement.

### W5C — Classification

- typed multidimensional classification assertions;
- provider/tool/local taxonomy context;
- classical domain vs. period distinction;
- forms/work types/instrumentation where available;
- conflicting provider/tool classifications retained rather than overwritten.

Acceptance emphasizes traceability, offline/cache behavior, privacy and false-identity protection.

## W6 — Matching Engine

Implement:

- duplicate/relation taxonomy;
- candidate generation/blocking;
- feature extraction;
- versioned scoring/rules;
- explainable evidence;
- classification and confidence/review status.

Matching consumes resolved identities and ToolProvider outputs as evidence but must still consider independent file/content/audio evidence.

Never perform global all-vs-all matching across the entire collection.

Acceptance emphasizes false-positive protection, cross-tool disagreement handling and clear distinction between:

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

Implement persisted review queues and decisions for entity resolution, ToolProvider conflicts and duplicate matching:

- accept/reject/defer;
- relation-specific decisions;
- authority candidate confirmation/rejection;
- alias/canonical-name confirmation;
- cross-tool contradiction review;
- decision history and tool/resolver/matcher/evidence context;
- prevention of needless repeated review for unchanged cases.

Review decisions may create durable local authority knowledge without rewriting source observations.

## W8 — Calibre Library Adapter

Build on the W3 calibre ToolProvider and implement read-only library integration:

- locate/read configured Calibre library metadata;
- map records into adapter DTOs/core-compatible observations;
- detect files unknown to Calibre, Calibre records without files, duplicates, metadata inconsistencies and authority conflicts;
- use Calibre as one evidence source, not the canonical FolioTone database;
- never require Calibre for normal FolioTone operation.

## W9 — Consolidation Planning

Create non-executable `ConsolidationPlan` data from confirmed/reviewed relations. Plans may describe KEEP and candidate operations but must be marked non-executable.

Identity and quality are separate inputs: a future quality evaluator may rank which equivalent representation is preferable only after identity is established.

Acceptance:

- plans record evidence and preconditions;
- plans cannot mutate the filesystem;
- changed-since-analysis requirements are represented for future W10;
- no single ToolProvider/provider/AI/web inference can justify a destructive candidate by itself.

## W10 — Controlled Consolidation (future, gated)

Do not implement until a new ADR explicitly accepts write-capable behavior.

Potential operations: copy, move, rename, hardlink/reflink where supported, metadata update, delete, and explicitly authorized external-tool write workflows. All require explicit safety design, revalidation, audit, collision handling, and failure semantics.

## Cross-cutting future extensions

These do not block the first end-to-end pipeline but should remain architecturally possible:

- Library Health dashboard combining integrity, quality, unresolved identities, duplicates and completeness;
- completeness/gap detection for series/albums/classical works;
- cover/image perceptual fingerprints for editions/releases;
- e-book structural/quality/content-diff analysis using mature tools where suitable;
- audio quality/corruption assessment using ffmpeg/ffprobe or specialist tools where suitable;
- fixity/bit-rot monitoring;
- reproducible transformation/normalization recipes with dry-run/replay semantics;
- more external authority/catalog providers;
- local bulk authority indexes and incremental provider dataset refresh;
- rule learning from review history before considering more complex ML;
- generic web research as a separately controlled fallback when structured sources are insufficient.
