# Implementation Plan

This file defines the planned development sequence. `PROJECT_STATUS.md` states where the project currently is.

The book-only delivery refinement in `EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md`
packages existing W, E and EA work into executable EB pull-request waves. Its
EB labels do not replace this W0-W10 program sequence or the canonical backlog
IDs.

`EBOOK_WRITE_PIPELINE_PLAN.md` verbindet diese Implementierungsfolge mit der
vollständigen späteren Schreibstrecke von Scan und Review über nicht
ausführbare Metadatenkorrektur-/Konsolidierungspläne bis zu getrennten
W10-Gates, Verifikation, Recovery sowie REST-/UI-Grenzen. ADR-0061 autorisiert
die kontrollierte Entwicklung dieser E-Book-Writer mit synthetischen
Fixtures, aber keine pauschale reale Mutation. Das Dokument erzeugt keine
konkurrierende Statusachse.

ADR-0016 bleibt für die anfängliche CLI-only Implementierung historisch und
fachlich gültig. ADR-0067 entscheidet inzwischen die stufenweise lokale
Einzelbenutzer-Produktoberfläche. Für den aktuellen E-Book-Scope verwenden
CLI, REST, Browser und Worker dieselben Application-Verträge; spätere
Produktoberflächen bleiben an ihre jeweilige Wave gebunden.

[`EBOOK_CONTINUATION_PLAN.md`](EBOOK_CONTINUATION_PLAN.md) setzt die
Lieferfolge nach `S-FUT11-04` fort. `DEC-0001` aktiviert `WI-0003`
(`FUT-009`) für read-only Fixity Monitoring. Baseline, Verifikation und
append-only Einzelentscheidungen sowie die gemeinsame Produktoberfläche sind
umgesetzt. `DEC-0001` bindet die
Verifikation an den neuesten abgeschlossenen Scan-Snapshot und an die
generische Review-Core-Paarung `FIXITY_EXPECTATION`/`FIXITY_RESULT` mit exakt
einem immutable Ergebnis je Review. Als nächste Front qualifiziert
`GATE-0001` den vorgeschlagenen
`DEC-0002`-Vertrag für eine deterministische EPUB-3-zu-EPUB-3-Ableitung.
`WI-0004` (`FUT-008`) bleibt bis zu einem positiven Gate blockiert. Diese
registrierten Artefakte ersetzen weder historische IDs noch die permanente
W9-Non-Execution-Grenze.

## Aktuelle Lieferfolge nach dem E-Book-Endgame

Die kanonische Reihenfolge und der operative Status stehen ausschließlich in
`BACKLOG.md`. ADR-0058 akzeptiert drei aufeinander aufbauende reguläre
read-only Produkt-Waves:

1. `CS-01` liefert `collection-state/v1`, `collection-state-build` und
   `collection-state-report` über genau einen abgeschlossenen `ScanRun`;
2. `CS-02` ergänzt `collection-state-diff/v1`,
   `collection-query/v1`, `collection-state-diff` und `collection-search`;
3. `CS-03` ergänzt danach `library-health/v1` und
   `library-health-report` ohne Gesamtscore oder Mutation Authority.

`CS-01` ist umgesetzt. Die Projektion ist immutable und rebuildbar, bindet
ihre Evidence an einen abgeschlossenen book-only `ScanRun` und wird durch die
additive Migration `0023` insert-only persistiert. Der Builder liest nur
persistierte Evidence; der Report verwendet eine echte SQLite-Read-only-
Verbindung. Beide Pfade öffnen weder Source Media noch starten sie Tools oder
Provider.

`CS-02` ist ebenfalls umgesetzt. ADR-0059 konkretisiert sieben feste
Diff-Kategorien und den begrenzten `collection-query/v1`-AST. Migration `0024`
persistiert opaque IDs, Statuswerte, Finding-Codes und ausgewählte
Metadaten-Candidates snapshotgebunden und insert-only; nur die ausgewählten
Metadatenwerte werden lokal über FTS5 gesucht. Diff und Suche verwenden echte
SQLite-Read-only-Verbindungen. JSON bleibt metadatenwertfrei, während
`--private-details` ausschließlich interaktive Textausgabe öffnet.

`CS-03` ist ebenfalls umgesetzt. ADR-0060 legt sieben unabhängige
Health-Dimensionen, feste Finding-Codes, Coverage und Status ohne
dimensionsübergreifenden Score fest. Migration `0025` speichert die
content-addressed Projektion, ihre Dimensionen, Findings und höchstens 64
opaque Samples je Finding insert-only. `collection-state-build` erzeugt oder
verifiziert `CollectionState`, Query-Index und Health in derselben
Transaktion. `library-health-report` liest die Projektion tatsächlich
SQLite-read-only und kann sie reproduzierbar mit einem älteren Snapshot
desselben `ScanRoot` vergleichen.

Maschinenlesbare Vertragsreports bleiben pfadfrei. Lokale interaktive
Metadatenwerte benötigen ausdrücklich `--private-details`; absolute Pfade
bleiben ausgeschlossen. Nach Abschluss der drei Waves wurde keine andere
Medienlinie automatisch gestartet. Die inzwischen ausdrücklich aktivierte
E-Book-Fortsetzung beginnt mit `WI-0003`; Music W4 bleibt die nächste geplante
vollständige Mediendomäne und benötigt weiterhin eine eigene Aktivierung.

ADR-0061 aktiviert `W9-006` als nächsten regulären E-Book-Slice. ADR-0062
definiert dafür zuerst einen separaten, reviewbaren
`MetadataCorrectionCandidate` und danach den dauerhaft nicht ausführbaren
`MetadataCorrectionPlan`. `S-W9-006A` hat die reinen Verträge, Reducer,
Serialisierung, Golden Values und den Non-Execution-Gate geliefert.
`S-W9-006B` hat Persistenz und Review-Integration geliefert; `S-W9-006C` hat
den echten SQLite-Read-only-Report samt CLI ergänzt und `W9-006`
abgeschlossen. ADR-0063 schließt danach `FG-W10-METADATA-WRITE` für genau
EPUB 3, `SOURCE_METADATA` und einen einzelnen `title`-`REPLACE`.
`S-W10-MW01` implementiert die reinen Preflight-, lexikalischen Zwei-Spannen-
Patch- und Byte-/Semantik-Diff-Verträge. `S-W10-MW02` ergänzt privates
Streaming-Staging und feste unabhängige Metadaten-, EPUBCheck-, Text-, Cover-
und Preserved-Field-Validatoren. `S-W10-MW03` ergänzt content-addressed
Preparation/Authorization, einmaligen Run, insert-only Eventjournal, private
Capability-Auflösung, Root-Lease/Fencing und read-only Status. `S-W10-MW04`
implementiert das feste Linux-x86_64-glibc-`renameat2`-Backend, immutable
Backend-Binding, den gefenceten Ein-Datei-Executor und idempotente Exact-State-
Recovery mit synthetischen Filesystemen. `S-W10-MW05` schließt den Writer mit
festen Authorize-/Execute-/Recover-/Status-Kommandos, zweiter Bestätigung über
`stdin`, unmittelbarer Verifikation, explizitem Lease-Handoff, neuem Scan,
`CollectionState` und immutable Reconciliation ab.

`W10-005` ist abgeschlossen. `S-W10-05A` bis `S-W10-05D` liefern
Capability-Auflösung, Authorize, zweite Bestätigung, One-use-Fencing, Execute
und eine feste synthetisch abgenommene Recovery-Matrix. Recovery nimmt nur
eine opaque Run-ID, führt selbst keinen Move aus und ergänzt ausschließlich
fehlende append-only Ereignisse für eine exakt gebundene Source-/Ziel-
Verteilung. Kein Paket öffnet einen weiteren Mutationstyp oder behauptet
atomare No-Replace-Semantik. ADR-0065 teilt den nächsten getrennten book-only
Slice `W9-007` in reine Verträge, Persistenz/Review und read-only Ausgabe.
`S-W9-007A` liefert die content-addressed Candidate-/Plan-DTOs, Builder,
Reducer, Golden Values und den statischen Non-Execution-Gate. `S-W9-007B`
liefert Review-Paarung, Migration `0030` und insert-only Persistenz.
`S-W9-007C` liefert getrennt die echte SQLite-read-only Ausgabe. `W9-007` ist
damit vollständig und bleibt nicht ausführbar. ADR-0066 schließt die danach
ausgeführte docs-only Wave `FG-W10-RENAME` ausschließlich für byte-identischen
Same-Parent-`FILE_RENAME`; `FILE_REORGANIZE` bleibt hinter
`FG-W10-REORGANIZE`. `S-W10-RN01` liefert die nicht mutierende Proposal-/
Review-/Plan-Oberfläche; `S-W10-RN02` die weiterhin nicht ausführende
Authority, Capability, Probe, Fencing, insert-only Persistenz und read-only
Status. `S-W10-RN03` ergänzt das feste interne Linux-No-Replace-Backend,
unmittelbare Verifikation und Exact-State-Recovery. `S-W10-RN04` schließt die
vier festen CLI-Kommandos, zweite Bestätigung, Scan-Handoff,
`CollectionState` und immutable Reconciliation ab. ADR-0067 entscheidet die
Produktoberfläche; weitere Writer behalten jeweils ihr eigenes technisches
Gate und benötigen zusätzlich einen operation-spezifischen UI-Slice.

## Lokale Produktoberfläche nach FUT-011

Die nächste reguläre Produktfolge besteht aus genau vier kleinen Waves:

1. `S-FUT11-01` ergänzt adapterneutrale `ApplicationCommand`-,
   `ApplicationQuery`-, Context- und Error-Verträge, eine Composition Root
   sowie die Media-Line-Registry. Tool-/Format-Readiness und `Library Health`
   bilden den ersten doppelten CLI-/Application-Nachweis. Es entstehen noch
   keine HTTP-, Auth-, Worker- oder Migrationsabhängigkeiten.
2. `S-FUT11-02` implementiert `local-single-operator/v1` mit lokalem
   One-time-Bootstrap, Username/Argon2id-Passwort, Session-, CSRF-, Reauth-,
   Grant- und Audit-Vertrag, loopback-only `/api/v1`, gepinntem OpenAPI-3.1-
   Schema sowie dauerhaften `ApplicationJob`-Events und Worker-Leases. API,
   read-only Analyseworker und netzloser Operator-Worker bleiben getrennte
   Prozessrollen; noch ist keine W10-Capability registriert.
3. `S-FUT11-03` liefert die deutschsprachige responsive read-only E-Book-UI
   für Scan/Status, Readiness, `CollectionState`, Suche, `Library Health`,
   Analyse/Quality, Duplicate-/Varianten-Evidence, Review und nicht
   ausführbare Pläne. Private relative Locator benötigen Reauthentisierung,
   zeitbegrenzten `PRIVATE_READ`-Grant und getrennte `no-store`-Endpunkte.
4. `S-FUT11-04` adaptiert ausschließlich den bestehenden ADR-0066-Same-
   Parent-Rename. Passwort-Reauthentisierung und exakte aktionsspezifische
   Bestätigung ergänzen, ersetzen aber weder One-use-W10-Authorization noch
   Capability, Fencing, Recovery, Folgescan und Reconciliation. Nur der
   Operator-Worker erhält den operation-spezifischen Source-Mount.

Nur `EBOOK` ist aktiv. `MUSIC` und `IMAGE` besitzen getrennte als nicht
aktiviert erkennbare Einstiege, aber keine vorgetäuschten Domainendpunkte. Ein
Remote-/Mehrbenutzerprofil, MCP, Titelwriter-/Quarantäne-Controls und alle
weiteren Writer bleiben außerhalb dieser vier Waves.

Der decision-complete Datei-, Schnittstellen-, Privacy-, Worker-, Test- und
Git-Vertrag für die beiden noch offenen Waves steht in
[`FUT11_NEXT_WAVES.md`](FUT11_NEXT_WAVES.md). ADR-0069 ergänzt für
`S-FUT11-04` die operation-spezifische Jobübergabe: Die Raw Confirmation wird
im API-Prozess exakt geprüft und verworfen; nur der gebundene Digest gelangt
in die Persistenz. Diese Bindung ersetzt keine W10-Authorization, Capability,
Revalidierung, Fencing, Verifikation oder Recovery.

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
- missing tool, non-accepted exit code, timeout and malformed result behavior;
- explicit provider-owned accepted-exit-code semantics with zero-only as the
  runtime default;
- no external-tool source mutation through the standard runtime.

## W3 — E-Book Analysis / Orchestration

Do **not** start by writing EPUB/PDF/MOBI parsers from scratch.

First evaluate maintained specialist capabilities, especially calibre CLI, plus targeted format validators/tools where appropriate. Document reuse/rejection decisions with current maintenance/licensing/security information.

Implemented sequence and decisions through the active `W3-017`:

1. calibre `ebook-meta` as a fixed read-only metadata extraction vertical slice;
2. fixed calibre `ebook-convert` EPUB text plus a FolioTone-owned fingerprint;
3. fixed Poppler PDF metadata/page/text analysis;
4. reuse the same calibre contracts for an explicit MOBI/AZW/AZW3 extension;
5. retain raw OPF 2/3 observations and project versioned, grouped candidates
   for identifiers, contributors/roles/sort names, language, publisher,
   publication date, series and other fields with exact execution/observation
   links;
6. defer read-oriented `calibredb` integration until W8 provides a concrete
   Library-Reconciliation contract;
7. add a versioned synthetic comparison corpus with raw-file hashes,
   normalized-text fingerprints, bibliographic ground truth and
   provenance-scoped disagreement for exact copies, metadata changes, format
   variants of one `Edition`, and translations of one `Work`.
8. add fixed EPUBCheck 5.3.0 JSON validation for EPUB with bounded
   conformance/severity/diagnostic-code Evidence and provider-specific accepted
   exit codes; defer calibre's GUI-only diff and qpdf until a machine-readable
   comparison or additional PDF-structure gap exists.
9. add optional embedded-cover Evidence for EPUB/MOBI/AZW/AZW3 through a fixed
   `calibre-debug -e` helper that stages source privately, disables rendered
   EPUB fallback covers and distinguishes `NO_EMBEDDED_COVER`; use bounded
   Pillow decoding and a FolioTone-owned, versioned 64-bit horizontal dHash.
10. add `ebook-analysis-workflow/v1` and the unified CLI command
    `foliotone ebook-analyze`: route EPUB through metadata, text, cover and
    structural validation; route MOBI/AZW/AZW3 through metadata, text and
    cover; route PDF through both Poppler executions. Continue independent
    steps after expected adapter/tool failures, emit only bounded summary
    facts and return explicit aggregate failure semantics.
11. advance the unified command to `ebook-analysis-workflow/v2`: probe the
    currently configured local tool version without persisting a ToolExecution;
    reuse only the latest exact successful provider/tool/adapter/input/config
    identity after bounded integrity verification of every required private
    artifact and deterministic reconstruction of its persisted results and
    fingerprints. Re-run missing, failed, stale, damaged or inconsistent steps,
    expose `REUSED`/`EXECUTED`, and let `--fresh` bypass reuse completely. Keep
    the existing two-execution Poppler PDF adapter atomic at workflow-step level.
12. advance the unified result contract to `ebook-analysis-workflow/v3` and
    project its bounded facts through `ebook-quality/v1`. Evaluate metadata,
    readable text, cover presence, EPUB structure and format-specific risk as
    separate dimensions with stable finding codes and exact available
    ToolExecution provenance. Keep `INCOMPLETE` evidence separate from media
    findings, omit a scalar score and retain the technical CLI exit semantics.
13. add the read-only `ebook-comparison/v1` projection and `ebook-compare` CLI
    over persisted full-file, normalized-text, metadata-candidate, EPUB-
    structure and embedded-cover Evidence. Keep dimension state separate from
    coverage, retain exact Evidence and ToolExecution provenance, suppress raw
    values and paths, and produce no Relation, confidence or identity verdict.
14. extend the synthetic comparison ground truth to
    `foliotone-ebook-comparison-fixture/v2` with EPUB/MOBI/AZW/AZW3/PDF,
    sparse and malformed Evidence, and calibrated cover distances. Replace
    collection-wide Evidence loading with bounded target queries, explicit
    record limits and the measured SQLite indexes from Alembic
    `0006_ebook_evidence_lookup_indexes` without changing the comparison
    profile or producing an identity decision.
15. add `ebook-collection-analysis/v1` and CLI
    `foliotone ebook-collection-analyze`. Bind one immutable plan to the latest
    completed EBOOK `ScanRun`, stream eligible current EPUB/MOBI/AZW/AZW3/PDF
    observations into bounded persisted batches, claim work under a lease with
    1 to 8 workers, continue after per-file failures and resume without
    replanning or repeating completed items. Reuse exact Evidence through
    `ebook-analysis-workflow/v3`, keep batch summaries path-free and preserve
    read-only Source Media.
16. add `ebook-collection-report/v1` and CLI
    `foliotone ebook-collection-report`. Read one persisted non-running
    Collection snapshot without reopening Source Media, aggregate complete
    format/analysis/quality/finding counts, retain exact finding-to-execution
    provenance and emit bounded prioritized review items. Produce separate
    exact-file and same-normalized-text/different-file candidate groups as
    deterministic private JSON/CSV/checksum artifacts. Expose truncation,
    suppress raw fingerprints, and produce no Relation, confidence or
    identity verdict.
17. harden the real read-only collection path: project complete latest hash
    Evidence for unchanged observations without reopening Source Media, use
    bounded hash workers plus set-oriented index and atomic fingerprint
    batches, and isolate per-file hash I/O failures for selective retry. Add
    mutually exclusive `--plan-per-format` for heterogeneous pilots and
    `ebook-duplicate-hash/v1` / `ebook-hash-candidates` to compute full
    SHA-256 only for current repeated Quick-fingerprint groups that still lack
    exact file Evidence. Protect active `ScanRun` attempts with renewable
    leases and permit only explicit atomic recovery of unleased or expired
    `RUNNING` attempts. Keep all workflows resumable, path-free and
    non-mutating.

The detailed book-only continuation, including the controlled runtime cutover,
synthetic development gates, root-wide write coordination and the sequence
through non-executable W9 planning, is defined in
[`W3_017_EBOOK_ROADMAP.md`](W3_017_EBOOK_ROADMAP.md). Music W4 remains outside
that roadmap and stays deferred under the current user-directed E-book focus.
18. add `ebook-inventory-report/v1` and CLI
    `foliotone ebook-inventory-report`. Read only the newest completed scan
    snapshot without reopening Source Media; aggregate complete format/byte
    totals, full-hash coverage, repeated Quick groups, pending candidate hashes
    and confirmed exact-file duplicate totals. Stream sorted duplicate details,
    retain only bounded prioritized groups/members, suppress raw fingerprints
    and emit deterministic private JSON/CSV/checksum artifacts without a
    Relation, keep preference or identity verdict.

The subsequent archive-aware e-book and end-to-end deduplication track is
defined in
[`EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md`](EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md).
It first adds signature-based archive/volume/sidecar inventory, bounded
read-only listing and integrity Evidence, local secret-handle-based password
candidates and sandboxed private test extraction. Archive members then enter
the normal Entity Resolution, Matching and Review sequence without pretending
to be physical source files. W9 may produce only a non-executable,
content-addressed deduplication plan. Quarantine, purge and empty-directory
cleanup remain blocked W10 work until a future accepted ADR and separate
execution approval exist.

Current execution priority is intentionally e-book-first. Music W4 remains in
the architecture and backlog but is deferred until the e-book completion track
and the book-only portions of authority resolution, matching, review and
Calibre-library reconciliation have reached a mature end-to-end state.

Separate raw tool/analyzer observations, normalized/derived assertions and canonical domain entities.

Planned evidence includes:

- file SHA-256;
- format/content fingerprint;
- normalized text fingerprint where text is available;
- metadata/tool disagreement;
- optional embedded-cover facts and versioned perceptual fingerprint;
- EPUB structural validation Evidence;
- versioned multi-dimensional E-Book quality findings;
- provider-neutral content comparison and collection-level reports.

OCR is out of the first implementation. Scanned PDFs without text should be represented explicitly rather than silently OCRed.

Acceptance requires ToolExecution provenance and tests showing that tool
results do not directly become canonical truth. The controlled comparison
corpus must keep file, content, `Edition` and `Work` identity levels distinct
without defining W6 scoring or automatic review thresholds prematurely.

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

ADR-0062 teilt `W9-006` in drei begrenzte Pakete. `S-W9-006A` und
`S-W9-006B` und `S-W9-006C` sind umgesetzt: immutable Candidate-/Plan-DTOs, reine Reducer,
kanonische Serialisierung, Review-Literale, Migration `0026`, insert-only
Persistenz, der echte SQLite-Read-only-Report, die CLI-Grenze und der
Non-Execution-Vertrag sind vorhanden.
ADR-0065 teilt `W9-007` in drei begrenzte Pakete. `S-W9-007A` implementiert
immutable, content-addressed Candidate-/Plan-DTOs für sechs feste
Operationsfamilien, reine Builder/Reducer, kanonische Serialisierung und den
Non-Execution-Vertrag. `S-W9-007B` ergänzt den Review-Core, Migration `0030`
und die bounded insert-only Persistenz einschließlich kanonischem Rebuild und
vollständiger lokaler Lineage-Revalidierung. `S-W9-007C` ergänzt den echten
SQLite-Read-only-Report samt privacy-begrenzter CLI und schließt `W9-007` ab.
Ein Ziel-Slot oder Rezept öffnet keinen Writer. Die vollständige Reihenfolge
steht in `EBOOK_WRITE_PIPELINE_PLAN.md`; ADR-0066 hat
`FG-W10-RENAME` inzwischen eng entschieden. `S-W10-RN01` liefert die
nicht mutierende Produktsurface, `S-W10-RN02` die nicht ausführende
Authority-/Persistenzschicht und `S-W10-RN03` Backend, Executor sowie
Exact-State-Recovery. `S-W10-RN04` schließt die Bedien-, Scan- und
Reconciliation-Kette inzwischen ab.

Identity and quality are separate inputs: a future quality evaluator may rank which equivalent representation is preferable only after identity is established.

Acceptance:

- plans record evidence and preconditions;
- plans cannot mutate the filesystem;
- changed-since-analysis requirements are represented for future W10;
- no single ToolProvider/provider/AI/web inference can justify a destructive candidate by itself.

## W10 — Controlled Consolidation (gated)

ADR-0056 akzeptiert reine Quarantäneverträge, insert-only Authorization-/Run-
Persistenz, read-only Status und als begrenzte Interim-Ausnahme einen
Ein-Datei-Quarantäneexecutor. S-W10-01 und S-W10-02 bleiben mutationsfrei;
S-W10-03 darf ausschließlich `os.rename` im selben vom Betriebssystem
gemeldeten Filesystem nach Ziel-Abwesenheitsprüfung und vollständiger
SHA-256-Revalidierung verwenden. Diese Zielprüfung ist nicht atomar.
`FG-W10-MOVE-BACKEND` bleibt deshalb die verpflichtende spätere Härtung für
atomaren No-Replace, no-follow sowie Race-/Crash-Nachweise. Cross-Volume-
Copy+Delete und Überschreiben sind kein Fallback.

Metadaten-, Sidecar-, externe Library-, Rename- und Archive-/Containerwrites
sind durch ADR-0061 zur getrennten Entwicklung freigegeben, bleiben operativ
aber an ihre eigenen technischen und operativen Verträge gebunden. ADR-0063
entscheidet `FG-W10-METADATA-WRITE` ausschließlich für
`ebook-source-metadata-write/epub3-title-replace/v1`. Der Writer patcht nur
`dc:title` und das formatbedingt aktualisierte `dcterms:modified`, verlangt
einen memberweisen Byte-/Semantik-Diff und verwendet für den späteren Linux-
Commit ausschließlich atomaren `renameat2`-Exchange mit
Same-Filesystem-Recovery. ADR-0064 und `S-W10-MW05` ergänzen die feste CLI,
zweite Bestätigung, unmittelbare Verifikation, einen expliziten Lease-Handoff,
neuen Scan, `CollectionState` sowie den atomaren `VERIFIED`-/Reconciliation-
Abschluss. Damit ist genau dieser EPUB-Titelwriter operativ erreichbar.
Sidecar-, externe Library- und Archivewrites bleiben an
`FG-W10-SIDECAR-WRITE`, `FG-W10-EXTERNAL-LIBRARY-WRITE` beziehungsweise
`FG-W10-ARCHIVE-REWRITE` gebunden. Same-Parent-Rename ist nach RN04 als einziges
ADR-0066-Profil operativ; Reorganisation bindet `FG-W10-REORGANIZE`. W10-003
und W10-004 halten Rollback/Purge und Verzeichnisbereinigung weiterhin
getrennt.

ADR-0066 entscheidet `FG-W10-RENAME` ausschließlich für einen
byte-identischen `FILE_RENAME` im selben vorhandenen Parent. Zulässig sind nur
ein reviewter blockerfreier W9-Plan, fünf durch aktuelle Coverage
`KNOWN_NONE` oder explizit `NOT_APPLICABLE` belegte Dependencies, ein
historisch unbenutzter Target-Slot, eine private einzelne Capability und das
feste Linux-`openat2`-/`renameat2(RENAME_NOREPLACE)`-Profil. Authorization,
Fencing, Journal, unmittelbare Verifikation, Exact-State-Recovery, Folgescan,
`CollectionState` und eine Reconciliation mit getrennten alten/neuen
`FileRecord`-Identitäten sind verpflichtend. `S-W10-RN01` liefert die
nicht mutierende Proposal-/Preview-/Review-/Plan-Oberfläche; `S-W10-RN02`
schließt Authority und Persistenz. `S-W10-RN03` schließt Backend und
Exact-State-Recovery; `S-W10-RN04` schließt die Bedien-/Reconciliation-Kette.
Erst RN04 öffnet den engen operativen Einstieg. `FILE_REORGANIZE` bleibt
separat hinter `FG-W10-REORGANIZE`.

Die Quarantäne besitzt eine vollständige eng begrenzte Bedienkette. Der
private `QuarantineCapabilityResolver`, `quarantine-authorize`, die zweite
Bestätigung über nicht geloggtes `stdin`, `quarantine-execute` und
`quarantine-recover` sind vorhanden. Recovery rekonstruiert die historischen
Run-Binder und klassifiziert ausschließlich die feste exakte physische
Zustandsmatrix; es führt keinen zweiten Move aus. CLI-Argumente enthalten nur
opaque IDs und Content Hashes. `quarantine-status` bleibt die
maschinenlesbare read-only Statusprojektion.

Spätere Operationen wie Rollback, Purge, Metadatenupdate, Calibrewrite und
explizit autorisierte externe Toolwrites benötigen jeweils eine eigene
Sicherheitsentscheidung, Revalidierung, Audit, Collision Handling und feste
Fehlersemantik.

## Cross-cutting future extensions

Diese späteren Erweiterungen blockieren die aktuelle Lieferfolge nicht:

- medienübergreifende Generalisierung der durch `CS-03` zunächst book-only
  implementierten `Library Health`-Projektion;
- Remote-/Mehrbenutzerbetrieb, MCP oder eine native Desktop-UI über die durch
  ADR-0067 akzeptierte lokale REST-/Browser-Oberfläche hinaus. Schreibende
  Endpunkte bleiben von read-only Oberflächen getrennt und benötigen
  weiterhin eigene W10-Gates sowie einen operation-spezifischen UI-Slice;
- completeness/gap detection for series/albums/classical works;
- cover/image perceptual fingerprints for editions/releases;
- e-book structural/quality/content-diff analysis using mature tools where suitable;
- audio quality/corruption assessment using ffmpeg/ffprobe or specialist tools where suitable;
- fixity/bit-rot monitoring;
- reproducible transformation/normalization recipes with dry-run/replay semantics;
- portable node/object lineage plus bounded, idempotent exchange and
  conflict-aware fusion between FolioTone systems, subject to the proposed
  ADR-0042 gates; embedded/source/external-library identifier writes remain
  separate W10-blocked operations;
- more external authority/catalog providers;
- local bulk authority indexes and incremental provider dataset refresh;
- rule learning from review history before considering more complex ML;
- generic web research as a separately controlled fallback when structured sources are insufficient.
