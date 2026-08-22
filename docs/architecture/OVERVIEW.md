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

Aktive `ScanRun`-Datensätze besitzen eine erneuerbare Lease. Ein expliziter
Recovery-Pfad kann einen nachweislich verwaisten ungeleasten oder abgelaufenen
`RUNNING`-Lauf atomar auf `INTERRUPTED` setzen und über die vorhandene Lineage
fortsetzen; eine aktive Lease blockiert konkurrierende Übernahme. Discovery
bleibt vollständig streaming-basiert, während unveränderte vollständige
Hash-Evidence ohne erneuten Source-Read übernommen wird.

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

Die optionale E-Book-Laufzeit folgt ADR-0057 Docker-first. Ein expliziter
Provisioning-Schritt baut ein gelocktes `linux/amd64`-Image mit calibre,
Poppler, Java und EPUBCheck. Der davon getrennte, nicht mutierende
`ebook-tools-doctor` prüft Versionen und Readiness je Format, ohne Medien oder
Datenbank zu öffnen. Analysebefehle installieren, aktualisieren oder bauen
niemals Werkzeuge. Das Containerprofil bindet Source Media read-only ein und
ändert die vorhandenen Adapter-/Evidence-Verträge nicht.

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
fort, `--plan-limit` begrenzt einen neuen Pilotplan global und das gegenseitig
exklusive `--plan-per-format` deckt jedes vorhandene unterstützte Format
begrenzt und deterministisch ab. Die Batch-Persistenz enthält keine
Source-Pfade, Metadatenwerte oder Inhalte und erzeugt keine `Relation` oder
Identitätsentscheidung. ADR-0021 dokumentiert den Lifecycle und die
Sicherheitsgrenzen.

Der fünfzehnte W3-Slice ergänzt `ebook-collection-report/v1` und den CLI-
Befehl `foliotone ebook-collection-report`. Die Projektion liest einen
persistierten, nicht mehr aktiven Collection-Lauf in einer konsistenten
Datenbanktransaktion und öffnet keine Source-Media-Datei. Sie aggregiert
vollständige Format-, Analyse-, Quality- und Befundzähler und erzeugt eine
begrenzte priorisierte Review-Liste mit exakten verfügbaren
`ToolExecution`-Quellen der Befunde.

Gleiche vollständige `FILE_SHA256`-Werte bilden Exact-Duplicate-Kandidaten;
gleiche versionierte `EBOOK_NORMALIZED_TEXT`-Werte mit unterschiedlichen
vollständigen Datei-Hashes bilden Content-Variant-Kandidaten. Sortierte
SQL-Streams und feste Ausgabegrenzen halten Speicher und Artefaktgröße
begrenzt. Private JSON-/CSV-/Checksum-Artefakte enthalten keine rohen
Fingerprints und werden byte-stabil außerhalb des Source Root gespeichert.
Die Kandidaten erzeugen keine `Relation`, Confidence oder
Identitätsentscheidung. ADR-0022 dokumentiert diesen Vertrag.

Der siebzehnte W3-Slice ergänzt `ebook-duplicate-hash/v1` und den CLI-Befehl
`foliotone ebook-hash-candidates`. Vollständiges SHA-256 wird nur für aktuelle
Mitglieder mehrfach belegter Quick-Fingerprint-Gruppen berechnet, denen dieser
Nachweis noch fehlt. Stabile Keyset-Batches, 1 bis 8 Worker, atomare
Fingerprint-Batches und `--max-items` halten den Lauf begrenzt und durch einen
erneuten Aufruf fortsetzbar. Die Source-Observation wird vor und nach dem Hash
validiert; per-File-Fehler bleiben isoliert und path-frei. ADR-0023 dokumentiert
den Evidence- und Sicherheitsvertrag.

Der achtzehnte W3-Slice ergänzt `ebook-inventory-report/v1` und den CLI-Befehl
`foliotone ebook-inventory-report`. Die Projektion liest ausschließlich den
neuesten abgeschlossenen Scan-Snapshot und öffnet keine Source-Media-Datei. Sie
aggregiert vollständige Format- und Byte-Summen, Vollhash-Abdeckung, mehrfach
belegte Quick-Gruppen, noch offene Vollhash-Evidence sowie exakt bestätigte
Dateiduplikate und deren technisches Speicherpotenzial. Sortierte SQL-Streams
und Gruppen-/Mitgliederlimits halten nur begrenzte private Details im Speicher;
rohe Fingerprints verlassen die Query-Schicht nicht. Deterministische private
JSON-/CSV-/Checksum-Artefakte erzeugen keine Relation, Keep-Präferenz oder
Identitätsentscheidung. ADR-0024 dokumentiert diesen Vertrag.

Die book-only Produktprojektion `collection-state/v1` materialisiert die
bereits persistierte Evidence genau eines abgeschlossenen `ScanRun`. Sie hält
vollständige physische Zähler sowie je Analyse-, Resolution-, Classification-,
Matching-, Review-, Calibre-, Archive-, Consolidation- und Quarantäne-
Komponente explizite Coverage-, Freshness-, Konflikt- und Kürzungszustände.
Itembezogene Digests machen den Zustand deterministisch und erklärbar, ohne
Pfade oder Metadatenwerte im maschinenlesbaren Report offenzulegen.

Der Builder liest in zwei stabilen Keyset-Pässen ausschließlich die lokale
Persistenz und verweigert einen Abschluss, wenn sich die relevante Evidence
zwischen den Pässen ändert. Migration `0023` speichert Snapshots insert-only;
identische Eingaben verwenden denselben content-addressed Snapshot. Der
separate Reportpfad öffnet SQLite tatsächlich read-only. Beide Pfade öffnen
keine Source Media, starten keine Tools oder Provider und besitzen keine
Mutation Authority. ADR-0058 dokumentiert Projektion und Lieferfolge.

`collection-state-diff/v1` vergleicht zwei immutable Snapshots desselben
`ScanRoot` über begrenzte Keyset-Streams. Kategorien beschreiben nur direkt
belegte Zustandsübergänge; ein neuer Observation-Identifier allein wird nicht
als technische Änderung ausgegeben. Der pfadfreie Report zählt den
vollständigen Diff und begrenzt nur seine Detailseite.

`collection-query/v1` kompiliert ausschließlich einen validierten, begrenzten
`AND`-/`OR`-AST auf feste SQLite-Abfragen. Migration `0024` bindet opaque IDs,
Statuswerte, Finding-Codes und ausgewählte nicht kanonische Metadaten-
Candidates insert-only an den exakten `CollectionState`. FTS5 indexiert nur
diese Metadatenwerte, nie Content oder OCR. Maschinenreports bleiben
metadatenwertfrei; private Werte benötigen interaktive Textausgabe mit
`--private-details`. ADR-0059 dokumentiert den ausführbaren Vertrag.

`library-health/v1` reduziert den gebundenen Snapshot anschließend in sieben
unabhängige, content-addressed Dimensionen. Migration `0025` persistiert
Snapshot, Dimensionen, Findings und höchstens 64 nach opaque `File`-ID
sortierte Samples je Finding insert-only. `collection-state-build` erzeugt
oder verifiziert State, Query-Index und Health atomar; eine fehlende oder
inkonsistente Teilprojektion bricht den Build ab. `library-health-report`
öffnet SQLite mit `mode=ro` und `query_only=ON`, gibt keine privaten Werte oder
Evidence-Digests aus und kann zwei kompatible Snapshots ohne
Kausalitätsbehauptung vergleichen. ADR-0060 dokumentiert diesen Vertrag.

Der getrennte `ebook-metadata-correction-report` liest genau einen immutable
`MetadataCorrectionPlan` ebenfalls mit `mode=ro` und `query_only=ON`. Seine
Text- und JSON-Projektionen bleiben pfad- und metadatenwertfrei; sie zeigen
nur die durch ADR-0062 erlaubten IDs, Profile, Status-, Feld-, Operations-,
Count-, Review- und Blockerinformationen. Der Report besitzt keine Mutation
Authority und öffnet keine Source Media.

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

W9 plant mögliche Aktionen ausschließlich nicht ausführbar. ADR-0061 erlaubt
die kontrollierte Entwicklung operation-spezifischer E-Book-Writer; eine reale
W10-Mutation benötigt zusätzlich die eigene akzeptierte technische ADR, die
vollständige Bedien-/Recoverykette und eine konkrete lokale Authorization. Die
enge ADR-0056-Interim-Quarantäne ist derzeit der einzige ausführbare
Mutationstyp.

ADR-0063 entscheidet als ersten weiteren technischen Vertrag ausschließlich
einen EPUB-3-`SOURCE_METADATA`-Writer für genau einen
`title`-`REPLACE`. `S-W10-MW01` implementiert den bounded Preflight, den
lexikalischen Zwei-Spannen-Patch und den memberweisen Diff als reines Bytes-
API. `S-W10-MW02` ergänzt exklusives privates Streaming-Staging sowie feste
nicht persistierende Metadaten-, EPUBCheck-, Text-, Cover- und Preserved-
Field-Validatoren. `S-W10-MW03` ergänzt content-addressed Preparation und
Authorization, einmalige gefencete Runs, append-only Events, private
Capability-Auflösung und einen read-only Status. Linux-`renameat2`-Exchange/
Recovery sowie CLI/Reconciliation bleiben `S-W10-MW04` und `S-W10-MW05`
vorbehalten. Bis zu deren Abschluss entsteht keine neue operative Mutation
Authority.

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

- source media stays read-only through W9; W10 writers remain
  operation-specific and capability-bound;
- runtime databases/caches remain outside Git;
- external tool containers should receive read-only media mounts for analysis whenever possible;
- write/delete/move/rename/retag commands from external tools are prohibited through W9;
- absolute local paths are not sent to online providers;
- provider requests use the minimum structured information needed;
- generic web research is a separately controlled fallback, not an implicit side effect of scanning.

See `AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`, `SAFETY.md`, `docs/reference/EXTERNAL_DATA_SOURCES.md` and `docs/reference/EXTERNAL_TOOLS.md`.
