# Architecture Overview

## Purpose

FolioTone is designed to analyze large e-book and music collections by **orchestrating mature specialist tools and external knowledge sources**, then reconciling their outputs through a common provenance/evidence model.

It identifies real-world entities, enriches uncertain metadata, classifies content, detects duplicate/related media, supports human review, measures library health, and later produces controlled consolidation plans.

The architecture separates physical files, raw observations, tool executions, normalized/derived metadata, authority identities, canonical domain entities, external assertions, matching evidence, review decisions, and future filesystem actions.

## Architectural principle: orchestration first

Before implementing substantial media-specific functionality, evaluate whether a maintained external tool already provides a suitable implementation through a documented CLI, API, service or container interface.

FolioTone should not reproduce calibre, FFmpeg, Chromaprint, beets, SongKong or Picard merely to obtain capabilities they already provide well. It should instead normalize their outputs into a durable common model and combine independent evidence.

Tool-specific commands and schemas terminate at adapter boundaries. FolioTone remains responsible for provenance, reconciliation, canonical decisions, cross-tool matching, review and safety.

See `docs/decisions/ADR-0010-tool-provider-orchestration.md` and `docs/reference/EXTERNAL_TOOLS.md`.

## Current product surface

Under ADR-0016, FolioTone initially exposes only a CLI. The CLI remains a thin adapter and does not own domain logic. A web API, desktop interface or dashboard is outside the active W3 scope. Any later product surface must reuse the application/core contracts and requires an explicit scope or architecture decision.

## Components

### Core

Owns domain concepts and interfaces that must not depend on specific file formats, Calibre, beets, SongKong, Picard, FFmpeg, external provider schemas, Docker, CLI frameworks, or a concrete database implementation.

### Persistence

Initially implements SQLite-backed storage for core/index/tooling/authority/enrichment/matching/review state. Callers should depend on persistence contracts rather than SQLite details.

### Index

Discovers files, records observations, detects incremental changes, and calculates generic hashes/fingerprints that are appropriate to own natively. It does not decide that two works or recordings are equivalent.

### Filename / Path Context

Parses filenames and directory context into provenance-preserving field candidates. It may infer likely author/artist/title/series/track/year/language tokens but does not set canonical values directly.

### Tool Orchestration

Runs external specialist tools behind adapter-neutral `ToolProvider` contracts.

Responsibilities include:

- tool discovery/capability and version detection;
- safe bounded CLI/container/service invocation;
- timeout/cancellation/error handling;
- structured stdout/report/artifact import;
- bounded, strictly validated JSON loading from persisted `ToolArtifact` files;
- bounded declared workspace-output capture with path, size and SHA-256 validation before ephemeral work is removed;
- adapter-owned version policies that can reject unsafe tool versions before Source Media is opened;
- provider-specific accepted-exit-code allowlists with zero-only default and
  preservation of the observed code;
- recording tool/adapter/parser versions and execution status;
- conservative re-analysis decisions based on a prior successful `ToolExecution` and exact provider, capability, input, tool, adapter and configuration identity;
- mapping tool-specific output into FolioTone observations/evidence;
- ensuring source-media read-only safety through W9.

Tool execution is not domain truth. Multiple tools can support or contradict the same claim.

### E-Book Analysis

Coordinates e-book-specific observations and fingerprints. Mature calibre CLI capabilities should be evaluated first for metadata/library/format operations. FolioTone-native parsers are added only when external tools do not satisfy the required semantics, reproducibility, performance or licensing constraints.

The first W3 vertical slice invokes only
`ebook-meta FILE --to-opf metadata.opf`. It records the exact tool/adapter/config
identity, rejects calibre versions below 9.10.0 or unrecognized versions before
analysis, isolates calibre configuration, persists a bounded OPF artifact and
maps selected raw fields to `ToolResult` records attached to the concrete
`FileObservation`. The CLI does not expose calibre setter options, and no result
becomes canonical metadata automatically. `calibredb` remains deferred until a
read-only Library-Reconciliation contract is needed.

The second W3 vertical slice invokes only a fixed `ebook-convert FILE
content.txt` command with plain UTF-8 output, Unix newlines and disabled line
wrapping. A bounded private text artifact preserves the raw extraction;
FolioTone applies versioned Unicode `NFKC` plus whitespace normalization and
stores an `EBOOK_NORMALIZED_TEXT` SHA-256 against the exact `FileObservation`
and `ToolExecution`. Empty normalized output is represented as `NO_TEXT` and
does not create a fingerprint. Extracted text is not emitted through the CLI or
promoted to canonical metadata.

The third W3 vertical slice accepts only an unchanged PDF observation and runs
fixed `pdfinfo` and `pdftotext` commands as separate `ToolExecution` records.
Bounded, allowlisted `pdfinfo` output supplies technical metadata and page
count; a private bounded `POPPLER_TEXT` artifact supplies the input to the same
FolioTone-owned normalized-text fingerprint used for EPUB. Successful empty
extraction is explicit `NO_TEXT`; tool failures are not converted into that
state. The slice exposes no OCR, password, arbitrary-option or write path.

The fourth W3 vertical slice reuses the existing calibre adapters instead of
adding native Kindle-format parsers. `ebook-meta` remains format-neutral, while
`ebook-text` now accepts an exact EPUB/MOBI/AZW/AZW3 allowlist through adapter
version `ebook-convert-text/2`. The conversion command, private artifact,
normalization and fingerprint contracts are unchanged. DRM removal or bypass
is outside FolioTone; protected, damaged or otherwise failed conversions remain
failed executions and never become successful `NO_TEXT` observations. KFX,
AZW1, AZW4 and other formats remain outside this text contract.

The fifth W3 vertical slice keeps provider-shaped `calibre_metadata` results
and adds provider-neutral `ebook_metadata_candidate` results under the
versioned `ebook-metadata-candidate/v1` profile. The projection understands
OPF 2 attributes and OPF 3 refinements. Stable field paths group identifier
namespace/value pairs, contributor names/source elements/MARC roles/sort names,
and series names/positions. Direct fields include title, language, publisher,
publication date, subjects, description, rights, type, title sort and calibre
rating where present. Every candidate targets the same `FileObservation` and
references the exact `ToolExecution`; no `Agent`, `Work`, `Edition`, `Series`
or canonical value is created by this extraction step. Unknown role
vocabularies remain source evidence instead of being guessed.

The sixth W3 vertical slice adds the versioned, entirely synthetic
`foliotone-ebook-comparison-fixture/v1` corpus. It records reproducible raw-file
and normalized-text hashes, bibliographic ground truth, metadata differences
and provenance-scoped tool disagreement for exact copies, metadata-only
changes, format variants of one `Edition`, and translations of one `Work`.
The corpus labels expected identity levels for later W6 calibration; it does
not implement candidate blocking, scoring, confidence thresholds, review or
canonical metadata selection.

Der additive W3-014-Korpus
`foliotone-ebook-comparison-fixture/v2` ergänzt alle aktuell unterstützten
Formate EPUB, MOBI, AZW, AZW3 und PDF sowie `SPARSE`- und `MALFORMED`-
Evidence. Cover-dHash-Distanzen von 0, 1, 8, 32 und 64 bleiben technische
Kalibrierungswerte ohne Ähnlichkeits- oder Identitätsschwelle. Der zugehörige
synthetische Skalierungstest trennt zwei angeforderte Beobachtungen von 10.000
fremden Records je Evidence-Tabelle und prüft den indexgestützten,
collection-unabhängigen Leseweg.

The seventh W3 vertical slice runs EPUBCheck 5.3.0 against an unchanged EPUB
observation with a fixed headless Java/JAR command. A bounded private JSON
artifact is validated before FolioTone projects only conformance, severity
counts and diagnostic-code counts. EPUBCheck exit code `1` is an accepted
completed validation with conformance errors, not a process failure; the
negative verdict remains separate `ToolResult` Evidence. Message text, report
paths and publication fields are not projected or printed. calibre's GUI-only
diff interface and qpdf remain deferred until a machine-readable comparison or
additional PDF-structure gap exists.

The eighth W3 vertical slice adds optional embedded-cover Evidence for an exact
EPUB/MOBI/AZW/AZW3 observation. A fixed `calibre-debug -e` helper stages the
source inside the private workspace before invoking calibre and disables
rendered EPUB fallback covers. A bounded JSON contract distinguishes
`COVER_EXTRACTED` from `NO_EMBEDDED_COVER` and carries the staged Source
SHA-256 for a post-run equality check. The optional raster remains a bounded
private artifact. FolioTone uses bounded Pillow decoding and owns the
versioned 64-bit horizontal `EBOOK_COVER_DHASH`; visual similarity is
supporting Evidence and never an identity decision.

The ninth W3 vertical slice adds `ebook-analysis-workflow/v1` and the unified
CLI command `foliotone ebook-analyze`. It selects only the already implemented
read-only adapters required by the observation format: calibre plus EPUBCheck
for EPUB, calibre for MOBI/AZW/AZW3, and Poppler for PDF. Required adapters are
preflighted before the first step. Expected adapter or ToolExecution failures
remain step-local and do not suppress independent later Evidence; aggregate
`PARTIAL_FAILURE` and `FAILED` states still produce a non-zero CLI exit code.
The workflow prints only a bounded allowlist of counts, statuses and
fingerprints and never combines tool Evidence into canonical truth.

The tenth W3 vertical slice advances the public workflow contract to
`ebook-analysis-workflow/v2`. Each configured adapter first performs only its
fixed version probe. A prior step is reusable only when the latest execution
with the exact provider, tool, adapter, capability, FileObservation input and
configuration identities succeeded. FolioTone then verifies each adapter-
declared private artifact by bounded size and SHA-256 and deterministically
reconstructs the persisted results and fingerprints from that artifact. Any
missing, failed, stale, damaged or inconsistent step is executed again; an
explicit `--fresh` bypasses lookup and probing. The CLI exposes `REUSED` versus
`EXECUTED`, while the reused ToolExecution IDs preserve original provenance.
The combined Poppler PDF adapter remains one atomic workflow step containing
its separate `pdfinfo` and `pdftotext` executions.

The eleventh W3 vertical slice advances the public result contract to
`ebook-analysis-workflow/v3` and adds the separately versioned
`ebook-quality/v1` projection. `EbookQualityAssessment` evaluates the bounded
workflow facts in the stable dimensions `METADATA`, `TEXT`, `COVER`,
`STRUCTURE` and `FORMAT_RISK`. Fixed finding codes retain the exact available
ToolExecution IDs; raw metadata, text, validation messages and local paths do
not enter the assessment. Technical evidence gaps become `INCOMPLETE`, while
media findings become `REVIEW` or `ACTION_REQUIRED`. The aggregate is not a
numeric score, does not change the technical CLI exit code and does not assert
file, `Edition` or `Work` identity. Because the projection uses existing
Evidence, changing its rules requires a new quality-profile version but no
automatic tool rerun.

The twelfth W3 vertical slice adds the read-only `ebook-comparison/v1`
projection and CLI command `foliotone ebook-compare`. It loads two exact
FileObservations and their persisted full-file, normalized-text, metadata-
candidate, EPUB-structure and embedded-cover Evidence without opening Source
Media or invoking another tool. Each dimension reports comparison state and
Evidence coverage independently, retains bounded Evidence and ToolExecution
provenance and emits only safe field or diagnostic keys. Compatible cover
dHash values expose their raw Hamming distance without applying a similarity
threshold. The projection explicitly writes no Relation, confidence, review
decision or identity verdict; those contracts remain later Matching work.

Der dreizehnte W3-Slice ersetzt die collection-weite Vorabladung des
Paarvergleichs durch drei begrenzte, indexgestützte Target-Abfragen. Feste
Record-Grenzen und `LIMIT maximum + 1` verhindern unbeschränkte
Evidence-Historien; eine Überschreitung bricht technisch ab. Alembic
`0006_ebook_evidence_lookup_indexes` stellt die zugehörigen SQLite-Indizes
bereit. Der fachliche Vertrag von `ebook-comparison/v1` bleibt unverändert.

Der vierzehnte W3-Slice ergänzt `ebook-collection-analysis/v1` und den CLI-
Befehl `foliotone ebook-collection-analyze`. Ein neuer Lauf bindet einen
unveränderlichen Plan aktueller EPUB/MOBI/AZW/AZW3/PDF-Beobachtungen an den
neuesten abgeschlossenen EBOOK-`ScanRun`. Die Planung verwendet einen
gestreamten Read und persistiert höchstens 500 Items je Schreibbatch. Eine
Lease verhindert konkurrierendes Resume desselben Laufs; 1 bis 8 Worker
beanspruchen höchstens zwei Workerwellen gleichzeitig.

Jedes Item verwendet den vorhandenen formatbewussten Workflow und dessen
exakte Evidence-Wiederverwendung. Per-File-Fehler bleiben path-freie,
begrenzte Statuswerte und blockieren andere Items nicht. `--max-items`
ermöglicht kontrollierte Teil-Invocations, `--resume-run` setzt denselben Plan
fort, und `--plan-limit` begrenzt einen neuen Pilotplan deterministisch. Die
Batch-Persistenz enthält keine Source-Pfade, Metadatenwerte oder Inhalte und
erzeugt keine `Relation` oder Identitätsentscheidung. ADR-0021 dokumentiert
den Lifecycle und die Sicherheitsgrenzen.

### Music Analysis

Coordinates music-specific observations using suitable specialists such as `ffprobe`, Chromaprint/`fpcalc`, beets, SongKong and optionally Picard. FolioTone keeps the distinction between MusicWork, Recording, ReleaseGroup and Release regardless of a tool's internal model.

### Authority / Entity Resolution

Resolves inconsistent names, aliases, pseudonyms, credited-as forms, external identifiers, works and releases into candidate canonical identities while retaining all source observations.

This component answers identity questions such as whether `Asimov, I.` and `Isaac Asimov` plausibly refer to the same Agent. It does not itself decide that two media files are duplicates.

### Enrichment Providers

Adapters integrate structured external knowledge and optional generic web research. Providers return provenance-preserving assertions/candidates rather than overwriting core entities.

Provider use is mode-controlled (`OFFLINE`, `LOCAL_DATASETS`, `ONLINE_STRUCTURED`, `ONLINE_WEB_RESEARCH`) and cached under `/data`.

### Classification

Stores multidimensional typed facets with provenance instead of a single flat genre field. Provider/tool classifications can coexist until canonical/local classification rules decide what to expose.

### Matching

Generates plausible candidates using blocking/indexes, derives features, scores evidence, classifies relations, and records explanations and version information.

Matching consumes resolved identities and tool/provider observations as evidence together with hashes, embedded metadata, content/audio fingerprints, release/edition structure and other signals.

### Review

Queues uncertain entity-resolution and matching cases and persists human decisions. A decision should prevent identical cases from being repeatedly presented without a reason such as changed evidence, tool/resolver version or matcher version.

Review can create durable local knowledge such as confirmed aliases or rejected external/tool candidates.

### Consolidation

W9 only plans possible actions. No executable source-media mutation exists before W10 and an explicit architecture decision.

### Adapters

Integrate concrete external systems and tools. Calibre, beets, SongKong, Picard, FFmpeg, Chromaprint and external authority/music/book providers must not leak their schemas/commands into the core domain model.

## Dependency rule

Domain logic is inward-facing. Concrete storage, file formats, CLI, external tools, external provider APIs and web research adapt to core contracts rather than defining them.

Allowed high-level dependency direction:

```text
cli -> application/core interfaces
index -> core + persistence interfaces
filename/path parsing -> core candidate contracts
tooling -> core tool/evidence contracts + adapter interfaces
analyzers -> core observation contracts + tooling interfaces
authority/resolution -> core + observations + provider interfaces
external knowledge providers -> core provider contracts
classification -> core + resolved/external/tool assertions
matching -> core + analyzer/index/resolution/tool outputs
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
  -> specialist ToolExecutions / native analyzers
  -> raw tool/analyzer observations
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

## Tool execution provenance

A material tool-derived result must be traceable to the execution that produced it. Persistence must be able to represent at least tool identity/version, adapter/parser version, operation/profile, execution time/status, relevant configuration version/digest where practical, and output/artifact references.

This enables selective re-analysis when a tool or adapter changes and prevents opaque statements such as "SongKong says so" or "calibre returned this" from becoming unreviewable facts.

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
- expensive external tool jobs must be incremental and resumable where possible;
- repeated tool analysis should be skipped when input identity + relevant tool/config versions are unchanged;
- local authority indexes should avoid repeated internet requests;
- bulk provider datasets should be considered when officially supported/recommended for large-scale access;
- candidate generation must reduce pair comparisons before scoring;
- missing storage must not be confused with deletion;
- analysis must be observable;
- external tool/provider outages must not corrupt existing results.

## Safety assumptions

- source media stays read-only through W9;
- runtime databases/caches remain outside Git;
- external tool containers should receive read-only media mounts for analysis whenever possible;
- write/delete/move/rename/retag commands from external tools are prohibited through W9;
- absolute local paths are not sent to online providers;
- provider requests use the minimum structured information needed;
- generic web research is a separately controlled fallback, not an implicit side effect of scanning.

See `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`, `SAFETY.md`, `docs/reference/EXTERNAL_DATA_SOURCES.md` and `docs/reference/EXTERNAL_TOOLS.md`.
