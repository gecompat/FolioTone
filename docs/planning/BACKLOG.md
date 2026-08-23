# Backlog

Statuses: `DONE`, `NEXT`, `READY`, `PLANNED`, `BLOCKED`, `DECISION`.

`NEXT` bezeichnet genau den nächsten regulären Produkt-Slice, sofern eine
solche Wave ausdrücklich freigegeben ist. `READY`
bezeichnet einen unabhängig startbaren Vertrag mit erfüllten Voraussetzungen.
`PLANNED` ist später eingeordnet. `BLOCKED` nennt eine noch nicht erfüllte
Voraussetzung. `DECISION` bezeichnet ein offenes Architektur- oder
Produktgate und keine Implementierungsfreigabe.

## Kanonische Ausführungsfront

| Horizont | Aufgabe | Begründung |
|---|---|---|
| NOW | `S-W10-RN01` | ADR-0066 hat den ersten Writer auf einen byte-identischen Same-Parent-`FILE_RENAME` begrenzt. Als kleinster nutzbarer Slice folgt zuerst die noch fehlende nicht mutierende Proposal-/Preview-/Review-/Plan-Oberfläche. |
| OPERATIONAL READY | `OPS-001` | Der vollständige private Collection-Abschluss prüft den Betrieb, ist aber kein Entwicklungs- oder CI-Gate. |
| NEXT WAVES | `S-W10-RN01` -> `S-W10-RN02` -> `S-W10-RN03` -> `S-W10-RN04` | Proposal/Review/Plan, danach Authority/Persistenz, Linux-No-Replace-Backend/Recovery und zuletzt Bedien-/Scan-/Reconciliation-Kette; jede Wave bleibt für sich operation-spezifisch begrenzt. |
| LATER | W4 sowie die Music-Anteile aus W5 bis W7 | Music bleibt die nächste vollständige Mediendomäne nach ausdrücklicher Aktivierung; weitere Medien erhalten eigene Einstiegspunkte. |
| DECISION | `FG-W10-SIDECAR-WRITE`, `FG-W10-EXTERNAL-LIBRARY-WRITE`, `FG-W10-REORGANIZE`, `FG-W10-ARCHIVE-REWRITE`, W10-003, W10-004 | ADR-0063 und ADR-0066 entscheiden nur den EPUB-Titelwriter beziehungsweise Same-Parent-Rename. Alle benachbarten Operationen behalten ihr eigenes technisches Gate. |
| BLOCKED | `FG-A-SECRET`, `FG-A3-MEMBER-BYTE` | Secretkanal und Archive-Member-Byte-Identity sind von der E-Book-Write-Freigabe nicht betroffen. |

Andere Planungsdokumente erläutern diese Aufgaben, setzen aber keine eigene
Ausführungsreihenfolge oder konkurrierende Statusachse.

## W0 — Foundation

| ID | Status | Item |
|---|---|---|
| W0-001 | DONE | Define repository/package structure and component boundaries. |
| W0-002 | DONE | Record accepted architecture decisions for Python, persistence, analysis-first, Calibre adapter, explainable matching. |
| W0-003 | DONE | Add Docker/Compose baseline with persistent `/data` and read-only media mounts. |
| W0-004 | DONE | Add AI/contributor handover contract and authoritative project status. |
| W0-005 | DONE | Add Python packaging, quality-tool configuration, and bootstrap CLI/tests. |
| W0-006 | DONE | Verify Install/Ruff/Mypy/Pytest plus Docker build and `foliotone status` bootstrap in GitHub Actions. |
| W0-007 | DONE | Adopt the requested custom Community & Attribution License based on `SQL_Server_Analyze`; add protected bilingual root README notice. |
| W0-008 | DONE | Extend architecture with Authority/Entity Resolution, provenance, external enrichment, MusicWork/ReleaseGroup, multidimensional classification, source registry, and W10 safety gate. |
| W0-009 | DONE | Install the GitHub Actions workflow at `.github/workflows/ci.yml`. |
| W0-010 | DONE | Adopt orchestration-first ToolProvider architecture; add ADR-0010, external-tool registry, tooling package boundary, safety and AI handover rules. |
| W0-011 | DONE | Adopt binding documentation/language/terminology governance, canonical glossary, protected-license regression check, task-oriented docs index and Copilot instructions. |
| W0-012 | DONE | Adopt vendor-neutral Wave orchestration, `LOCAL`/`ECONOMICAL`/`BALANCED`/`FRONTIER` routing, a local-first test policy and thin discovery adapters for Copilot, Junie, Codex and Databricks Genie Code. |

## W1 — Core + Persistence

| ID | Status | Item |
|---|---|---|
| W1-001 | DONE | Design concrete entity/value-object boundaries and opaque UUID internal ID strategy; preserve knowledge-provider and ToolProvider independence. |
| W1-002 | DONE | Implement FileRecord, ScanRoot, ScanRun, FileObservation, presence/observation states. |
| W1-003 | DONE | Implement Agent, AgentName, AgentType, ExternalIdentifier, Contribution, and provenance/value assertion states. |
| W1-004 | DONE | Implement Work, Edition, Series, SeriesMembership. |
| W1-005 | DONE | Implement MusicWork, MusicWorkRelation, CatalogDesignation, Recording, ReleaseGroup, Release, ReleaseRecording. |
| W1-006 | DONE | Implement ClassificationAssertion, Fingerprint, Relation, Evidence, match/review status and version metadata. |
| W1-007 | DONE | Select SQLAlchemy Core + Alembic and implement SQLite migrations; record ADR-0012. |
| W1-008 | DONE | Implement provider-independent Repository contracts, explicit codecs and SQLite repositories without leaking SQLAlchemy into domain logic. |
| W1-009 | DONE | Add empty-db migration, idempotent head upgrade, full W1 graph round-trip, update, foreign-key, uniqueness and deterministic-listing tests. |
| W1-010 | DONE | Implement adapter-neutral ToolProviderDescriptor, ToolExecution, and ToolResult provenance contracts with stale-version inputs. |
| W1-011 | DONE | Document persistence architecture, synchronize status/backlog/README/Handover, and close W1 after full CI + Docker migration verification. |

## W2 — Incremental Index + Filename/Path Context + Tool Runtime

| ID | Status | Item |
|---|---|---|
| W2-001 | DONE | Implement persistent logical scan roots, stable name resolution and scan-run lifecycle using the W1 persistence layer. |
| W2-002 | DONE | Implement streaming filesystem discovery and relative-path observations without a collection-wide in-memory path list. |
| W2-003 | DONE | Implement incremental NEW/UNCHANGED/MODIFIED/MISSING/REAPPEARED behavior; unavailable roots must not create false MISSING evidence. |
| W2-004 | DONE | Implement opt-in DELETED confirmation requiring consecutive successful MISSING scans plus minimum elapsed absence; failed/interrupted scans do not advance confirmation. |
| W2-005 | DONE | Implement staged quick fingerprint and streamed SHA-256 strategy against FileObservation identity. |
| W2-006 | DONE | Implement conservative FileRelocationCandidate detection for NEW + first-time MISSING pairs in the same scan using unambiguous versioned fingerprint blocks without merging FileRecord identity. |
| W2-007 | DONE | Implement auditable resume lineage: only a persisted INTERRUPTED run of the same ScanRoot may be resumed; resume creates a new ScanRun and reuses already persisted incremental work without re-hashing unchanged files. |
| W2-008 | DONE | Versioned `FilenameParser` and `PathContextAnalyzer` emit provenance-preserving `FieldCandidate` values; full local Quality Gates passed as part of W2 closure. |
| W2-009 | DONE | Add configurable, versioned regex parsing profiles/fixtures for author-title, series/volume, track/disc, year and language conventions; full local Quality Gates passed. |
| W2-010 | DONE | Implement generic ToolProvider runtime with version detection, bounded local/container execution, timeout/cancellation, stdout/stderr artifacts, privacy-safe input identity, isolated work areas and read-only input policy. |
| W2-011 | DONE | Add bounded strict-JSON Artifact loading plus conservative selective re-analysis decisions; cover malformed structured output and tool/adapter/input/config version changes while preserving auditable executions. |
| W2-012 | DONE | Verify the documented local Windows/Docker smoke test with synthetic data: persistent `/data`, read-only media mounts, NEW/UNCHANGED/MODIFIED/MISSING/REAPPEARED behavior and unavailable-root protection. |
| W2-013 | DONE | Make `foliotone scan` operationally observable with path-free interactive progress, clean `KeyboardInterrupt` handling, persisted `INTERRUPTED` runs, cooperatively cancelled hash workers, bounded automatic hash-worker selection and fail-closed repair of the exact empty interrupted-0016 migration shape. |

## W3 — E-book Analysis / Tool Orchestration

| ID | Status | Item |
|---|---|---|
| W3-001 | DONE | Evaluate calibre 9.13.0, EPUBCheck 5.3.0, Poppler 26.07.0 and qpdf 12.4.0 before native parsers; document roles, deferrals, licenses and the calibre 9.10.0 security floor. |
| W3-002 | DONE | Implement the first read-only calibre ToolProvider vertical slice: fixed `ebook-meta FILE --to-opf` command shape, pre-input version policy, isolated config, bounded OPF artifact, raw `ToolResult` persistence and CLI; defer `calibredb` until a Library-Reconciliation contract exists. |
| W3-003 | DONE | Reuse a fixed read-only calibre `ebook-convert` EPUB-to-TXT command; persist a bounded private artifact, explicit text status and versioned FolioTone `EBOOK_NORMALIZED_TEXT` SHA-256. |
| W3-004 | DONE | Implement fixed Poppler 26.07.0 `pdfinfo`/`pdftotext` PDF analysis with separate provenance, bounded metadata/text artifacts, page count, shared normalized-text fingerprint and explicit `NO_TEXT`; defer qpdf until structural evidence has a concrete gap. |
| W3-005 | DONE | Reuse the existing fixed calibre metadata and text paths for an explicit EPUB/MOBI/AZW/AZW3 allowlist; keep DRM, damaged-input and tool failures distinct from successful `NO_TEXT`, without format-specific parsers. |
| W3-006 | DONE | Extract ISBN, contributors, language, publisher, series and other fields as observations/candidates with ToolExecution/provenance links. |
| W3-007 | DONE | Add a versioned synthetic comparison corpus covering identical file, changed metadata, same Edition, different Edition/translation and provenance-preserving tool disagreement without implementing matching. |
| W3-008 | DONE | Implement fixed read-only EPUBCheck 5.3.0 JSON validation with bounded conformance/severity/diagnostic Evidence and provider-accepted exit-code semantics; retain the private raw report and defer calibre's GUI-only book diff plus qpdf until a machine-readable comparison/structural gap exists. |
| W3-009 | DONE | Implement optional embedded-cover Evidence for EPUB/MOBI/AZW/AZW3: fixed `calibre-debug -e` helper with private source staging and rendered-cover suppression, explicit `NO_EMBEDDED_COVER`, bounded private raster artifact, Pillow-backed image guards and a versioned FolioTone `EBOOK_COVER_DHASH`; do not treat visual similarity as identity proof. |
| W3-010 | DONE | Implement unified CLI-only `ebook-analyze` orchestration: route EPUB to metadata/text/cover/EPUBCheck, MOBI/AZW/AZW3 to metadata/text/cover and PDF to Poppler; keep fresh ToolExecutions, bounded summaries, independent step continuation and explicit `SUCCEEDED`/`PARTIAL_FAILURE`/`FAILED` aggregate semantics. |
| W3-011 | DONE | Add `ebook-analysis-workflow/v2` conservative step planning for `ebook-analyze`: preflight current tool versions without persisting a run; reuse only the latest exact successful provider/tool/adapter/input/config identity after bounded private artifact verification and deterministic evidence reconstruction; retry missing/failed/stale/inconsistent steps, report `REUSED` versus `EXECUTED`, and provide `--fresh`. The existing two-execution Poppler PDF adapter remains one atomic workflow step. |
| W3-012 | DONE | Add `ebook-analysis-workflow/v3` plus the separate deterministic `ebook-quality/v1` projection. Report `METADATA`, `TEXT`, `COVER`, `STRUCTURE` and `FORMAT_RISK` as explicit dimensions with stable finding codes and exact available ToolExecution provenance. Keep technical `INCOMPLETE` distinct from `REVIEW`/`ACTION_REQUIRED`, use no scalar score, do not change technical CLI exit semantics and do not infer identity. |
| W3-013 | DONE | Add read-only `ebook-comparison/v1`, `EbookComparisonService` and CLI `ebook-compare` over persisted `FILE_SHA256`, normalized text, provider-neutral metadata candidates, EPUB structure and embedded-cover Evidence. Keep state separate from coverage, invalidate older Evidence after a newer failed provider execution, expose only bounded keys/counts/provenance, ignore volatile `identifier.calibre`, and write no Relation, confidence or identity verdict. |
| W3-014 | DONE | Expand the fully synthetic e-book corpus with malformed, sparse, multi-format and visual-distance cases; replace collection-wide pair-comparison reads with bounded target queries and measured SQLite indexes without using private media. |
| W3-015 | DONE | Add resumable collection-batch orchestration over persisted current EPUB/MOBI/AZW/AZW3/PDF observations. Reuse exact Evidence, continue after per-file failures, bound concurrency and preserve read-only source handling. |
| W3-016 | DONE | Add deterministic CLI collection reports with aggregate format/analysis/quality/finding counts plus prioritized incomplete, action-required, duplicate and variant review sets. Keep private paths and metadata in local runtime artifacts and out of Git. |
| W3-017 | DONE | Harden incremental scan/hash persistence from real read-only scale evidence; add recoverable `ScanRun` leases for externally orphaned `RUNNING` attempts, format-balanced pilot planning, resumable full-SHA enrichment limited to Quick duplicate candidates, a current-scan-first materialized candidate snapshot with a measured lookup index, root-wide fenced candidate-hash runs with durable path-free heartbeat/status, a deterministic scan-wide inventory/hash/duplicate report, true SQLite-read-only JSON status, a path-free postscan completion verifier, the E5 synthetic performance/restart contract and the completed E4 shared `ScanRoot` write lease with monotonic fencing across scan, candidate hash and E-book analysis writers. The controlled book-only continuation through W9 is detailed in [`W3_017_EBOOK_ROADMAP.md`](W3_017_EBOOK_ROADMAP.md). |
| W3-018 | DONE | ADR-0038 evaluates and selects signature-first ZIP/RAR/7z/TAR/CBR/CBZ discovery plus 7-Zip 26.02 for fixed read-only shapes. S-EBA-01, S-EBA-02 and S-EBA-06 implement synthetic fixtures, observer/volume grouping and pure safety policy without a real adapter. |
| W3-019 | DONE | ADR-0055 und S-EBAR-07A schließen Archive-/Volume-/Sidecar-Inventar, Missing-Volume-Findings sowie pfadfreie Listing-/Integrity-/Encryption-Berichte ab. Die Sidecar-Evidence bleibt bounded und enthält weder Basename, Pfad, Inhalt noch Secret. Freie 7-Zip-Prosa und grobe Exitcodes sind weiterhin keine Authority für `CORRUPT`, `UNSUPPORTED_METHOD` oder Passwortursachen. |
| W3-020 | DONE | S-EBA-04 und S-EBA-05 implementieren bounded lokale Secret Candidates und opaque `SecretHandle`-Metadaten. Die reale Passwortprüfung bleibt bis FG-A-SECRET blockiert; kein Klartext, Brute Force oder Online-Fallback ist zulässig. |
| W3-021 | BLOCKED | FG-A-RUNTIME bis EBAR-05 sowie S-EBAR-05A, S-EBAR-06A und das neutrale S-EBAR-04Q sind abgeschlossen. ADR-0046 und ADR-0047 entscheiden Storage Family und Formatlock; ADR-0048 den privaten Extraction-Lifecycle; ADR-0049 die dateisystemneutrale Workspace-Capability. ADR-0050 schließt FG-A-WORKSPACE-BACKEND negativ: Die Adapter-Allowlist bleibt leer; S-EBAR-04A und EBAR-06 bleiben `TOOL_UNAVAILABLE`. ADR-0051 sowie S-EBAR-W01 bis S-EBAR-W04 schließen die getrennte read-only Wrapperstrecke ab. Sie autorisieren weder Extraction noch Persistenz. FolioTone erhält keine Mount-/Device-/Root-Authority; kein Dateisystem und FIEMAP werden Kernvoraussetzung. W10 und Source-Mutation bleiben blockiert. |
| W3-022 | DONE | ADR-0052 und S-EBAR-07 schließen die immutable Archive-Persistenz mit Migration `0019_archive_evidence`, fünf dedizierten insert-only Tabellen, exakter Source-/Execution-/Wrapper-Lineage, konservativem Erfolgs-Reuse und ScanRoot-Fencing ab. Extraction, Secrets und Source-Mutation bleiben ausgeschlossen; CBR/CBZ/EPUB bleiben von entbehrlicher Verpackung getrennt. |
| W3-023 | DONE | ADR-0053 schließt FG-A-COLLECTION-ORCHESTRATION mit getrennten Archive-Run-/Item-/Source-Snapshots, stabilem Multi-Volume-Plan, eigener `ARCHIVE_COLLECTION_RUN`-Lease, Heartbeat, stale Resume, bounded Ausführung und path-freiem read-only Status ab. |
| W3-024 | DONE | S-EBAR-08A bis 08D und EBAR-09 schließen Models, Migration `0020`, Store/Fencing, restartbare Planpartition, bounded Ausführung sowie den strikt read-only und path-freien Archive-Collection-Status ab. Extraction, Secrets, Mutation und allgemeiner E-Book-Collection-Status bleiben getrennt; EB-A3 benötigt ein eigenes Frontier-Gate. |
| W3-025 | DONE | ADR-0054 schließt FG-A3-MATCHING und trennt belegbare generische Archive-Source-Dependencies von weiterhin unbekannter Member-Byte-Identity. S-EBA3-01 bis S-EBA3-03 implementieren reinen Vertrag, bounded Query/Store-Revalidierung und nicht ausführbare Planintegration. `KNOWN_NONE`, Member-/File-Matching, EA9/EA10-Abschluss und jede W10-Operation bleiben gesperrt. |
| W3-026 | DONE | ADR-0057 ergänzt die explizite Docker-first-Bereitstellung der E-Book-Spezialwerkzeuge: gelocktes Linux/amd64-Image, Windows-/WSL2-Provisioning ohne Hostinstallation, pfadfreier `ebook-tools-doctor` und Readiness je EPUB/MOBI/AZW/AZW3/PDF. Analysebefehle installieren oder aktualisieren nichts; ein fertiges Drittanbieter-Image wird nicht veröffentlicht. |

## W4 — Music Analysis / Tool Orchestration

These items remain planned but are deliberately deferred while the user-directed
e-book completion track and the book-only slices of W5 through W8 are active.

| ID | Status | Item |
|---|---|---|
| W4-001 | PLANNED | Evaluate current ffprobe, Chromaprint/fpcalc, beets, SongKong and Picard interfaces/licensing; define which capabilities are reused vs. FolioTone-native. |
| W4-002 | PLANNED | Implement `ffprobe` ToolProvider for machine-readable technical audio/container observations and probe/integrity failures. |
| W4-003 | PLANNED | Implement Chromaprint/`fpcalc` ToolProvider behind `AudioFingerprintProvider`; persist algorithm/tool version and fingerprint provenance. |
| W4-004 | PLANNED | Implement a read-only beets analysis adapter for useful matching/duplicate/completeness evidence without file/library mutation. |
| W4-005 | PLANNED | Evaluate/implement optional SongKong status/report/preview adapter; keep commercial dependency optional and prohibit mutating commands. |
| W4-006 | PLANNED | Evaluate Picard executable commands as an optional independent validator/specialist, not the primary FolioTone backend. |
| W4-007 | PLANNED | Extract contributor roles and identifiers (MusicBrainz IDs, ISRC/ISWC, barcode, catalog designation) from the selected tool chain as provenance-preserving observations. |
| W4-008 | PLANNED | Implement FolioTone-native audio logic only for gaps that the selected tools cannot satisfy reliably. |
| W4-009 | PLANNED | Add fixtures for same MusicWork/different Recording, same Recording/different Release, remix/remaster/quality variants and cross-tool disagreement. |

## W5 — Authority, Entity Resolution, Enrichment and Classification

### W5A — Local authority and resolution

| ID | Status | Item |
|---|---|---|
| W5A-001 | DONE | Implement versioned Unicode/name normalization without destructive overwrite. |
| W5A-002 | DONE | Generate local Agent candidates using aliases, pseudonyms, sort names and credited-as forms with versioned confidence/provenance. |
| W5A-003 | DONE | Implement homonym protection; equal normalized names must not auto-merge Agents. |
| W5A-004 | DONE | Persist book-only Agent/Work/Edition/Series resolution candidates with explanations, confidence and provenance through EB-02. |
| W5A-005 | DONE | Persist confirmed/rejected local authority mappings as append-only review decisions separately from source observations. |
| W5A-006 | PLANNED | Extend resolution candidates and explanations to MusicWork/Recording/ReleaseGroup/Release without collapsing their identity levels. |

### W5B — External enrichment infrastructure/providers

| ID | Status | Item |
|---|---|---|
| W5B-001 | DONE | Separate provider access modes (`OFFLINE`/`LOCAL_DATASETS`/`ONLINE_STRUCTURED`/`ONLINE_WEB_RESEARCH`) from `ProviderCachePolicy`; retain `KnowledgeProviderMode` only as input to the exact deprecated compatibility mapping. |
| W5B-002 | DONE | Implement persistent provider cache/import/version state under `/data` according to ADR-0035; no provider cache in Git. |
| W5B-003 | DONE | Implement privacy-minimized query DTOs; never send absolute paths. |
| W5B-004 | DONE | FG-03B accepts Open Library as the first bounded real book provider through ADR-0036; fixed endpoint, privacy, rate, cache, license and bulk boundaries are recorded before adapter code. GND/DNB remains the planned second authority source and Wikidata supplementary. |
| W5B-005 | PLANNED | Review and select first music knowledge providers from MusicBrainz and AcoustID; Chromaprint/fpcalc remains a local ToolProvider concern. |
| W5B-006 | PLANNED | Evaluate/import official bulk/local datasets where they are more appropriate than per-file API lookup. |
| W5B-007 | DONE | Implement the accepted Open Library book adapter as S-EB03B-01 through S-EB03B-08 with synthetic fixtures only; the structured music adapter remains planned. |
| W5B-008 | DONE | Add and verify offline/provider-failure/cache-hit/cache-refresh tests for the bounded Open Library provider. |
| W5B-009 | PLANNED | Define generic web research fallback interface; keep it separately enabled and candidate-only. |
| W5B-010 | PLANNED | Evaluate a local MusicBrainz mirror/container deployment only if scale/rate/latency justifies its operational cost. |
| W5B-011 | PLANNED | Resolve the user-supplied `Newzcrabber` name to a concrete maintained service and evaluate it plus suitable alternatives as explicit opt-in archive-password candidate providers; require a documented interface, current terms/license/privacy review, path-free queries, local cache and Secret Handles, otherwise record a non-integration decision. |

### W5C — Classification

| ID | Status | Item |
|---|---|---|
| W5C-001 | DONE | Implement typed multidimensional classification assertions with source/taxonomy provenance. |
| W5C-002 | DONE | Support e-book domain/genre/subgenre/topic/audience/language/form facets. |
| W5C-003 | PLANNED | Support music domain/style plus classical period/form/instrumentation facets. |
| W5C-004 | DONE | Preserve conflicting provider/tool classifications and derive canonical/local projections separately. EB-04 provides immutable profiled assertions, bounded read-only queries, deterministic projections, conflict links and a path-free CLI summary. |

## W6 — Matching

| ID | Status | Item |
|---|---|---|
| W6-001 | DONE | Implement book-only Endpoint-, Identity- and Evidence contracts through EB-05. |
| W6-002 | DONE | Implement bounded read-only book blocking for hashes, identifiers, resolution, Agent/title, text and Series context through EB-05. |
| W6-003 | DONE | Implement versioned book-only profiles and the persisted bounded workflow for `EXACT_DUPLICATE`, `SAME_EDITION` and `SAME_WORK` through EB-06. |
| W6-004 | DONE | Persist book-only Relation-Candidate feature links and project a path-free Explanation through EB-06B/EB-06C. |
| W6-005 | DONE | Calibrate the conservative book-only boundary on the controlled adversarial corpus; bibliographic auto-confirmation remains excluded. |
| W6-006 | DONE | Prevent hard local Contradictions from being outvoted in book-only profiles through EB-06A. |
| W6-007 | PLANNED | Match archive members, physical files and publication containers at separate file/content/Edition levels; an online password result or equal filename is never sufficient identity Evidence. |
| W6-008 | PLANNED | Define MusicWork/Recording/ReleaseGroup/Release Endpoint-, Identity- and Evidence contracts. |
| W6-009 | PLANNED | Add Music-/Audio-Candidate Blocks and relation-specific matcher profiles without reusing book-only thresholds. |
| W6-010 | PLANNED | Persist and calibrate Music Relation Candidates, feature links and Explanations against a dedicated adversarial corpus. |

## W7 — Review

| ID | Status | Item |
|---|---|---|
| W7-001 | DONE | Persist the generic review queue and append-only accept/reject/defer decision history with optimistic snapshot fencing. |
| W7-002 | DONE | Provide CLI-based `ACCEPT`/`REJECT`/`DEFER` and compatible decision reuse for book-only Relation Candidates through EB-06. |
| W7-003 | DONE | Reuse compatible ACCEPT/REJECT authority decisions while keeping DEFER reviewable; material or compatibility changes create a new case. |
| W7-004 | PLANNED | Add bounded Authority-/Alias-Review CLI flows and Music Relation-Candidate review without weakening snapshot fencing. |

## EB-07 — Read-only Calibre Library Reconciliation

| ID | Status | Item |
|---|---|---|
| S-EB07-01 | DONE | Synthetische Calibre-Ausgaben und malformed-output Fixtures für Fälle A bis G. |
| S-EB07-02 | DONE | Feste read-only `calibredb` Command Builder ohne freie Argumentweitergabe. |
| S-EB07-03 | DONE | Bounded Parser für Library Records, Formate und Kategorien. |
| S-EB07-04 | DONE | Read-only ToolProvider-Descriptor mit festen Capability Shapes. |
| S-EB07-05 | DONE | Immutable Snapshot-, Ownership- und Sidecar-DTOs. |
| S-EB07-06 | DONE | Insert-only Persistenz für Snapshot-Lineage und Ownership Evidence. |
| S-EB07-07 | DONE | Reconciliation Mapper für Fälle A bis D. |
| S-EB07-08 | DONE | Reconciliation Mapper für Fälle E bis G als Evidence und Review Candidates. |
| S-EB07-09 | DONE | Read-only CLI `calibre-reconciliation-report` und pfadfreier Report `calibre-reconciliation-report/v1`. |
| S-EB07-10 | DONE | Generische ToolRuntime begrenzt stdout/stderr bereits während der Ausführung; die festen `calibredb`-Shapes binden ihre ADR-0033-Grenzen und brechen bei Überlauf fail-closed ab. |
| S-EB07-11A | DONE | Bounded Capture-Parser für verpflichtendes `last_modified`, Exact-ID-Suche und Kategorie-CSV sowie kanonischer ADR-0033-Inventory-Digest. |
| S-EB07-11B1 | DONE | Bounded OPF-Validierung und exakter Metadatenfingerprint sowie reine, lineage-gebundene Projektion des Capture-Ergebnisses in den atomaren Record-/Format-Snapshotgraphen. |
| S-EB07-11B2A | DONE | Vollständige bounded Read-Sequenz mit global begrenzter Keyset-Pagination, Exact-ID-/OPF-/Kategorie-Läufen, Vorher-/Nachher-Digest und pro Tool-Write gefenceter bestehender EBOOK_ANALYSIS-Lease. |
| S-EB07-11B2B | DONE | Eigener EBOOK_ANALYSIS-Lease-Erwerb und Keeper, Latest-Completed-Scan-Bindung, atomare Persistenz des terminalen Snapshotgraphen und garantierte Lease-Freigabe. |

EB-07 ist damit für die persistierte read-only Reconciliation abgeschlossen.
Die read-only Capture-Orchestrierung gegen eine konfigurierte Calibre-
Bibliothek ist damit vollständig. EB-08, Archiv-Evidence und die W10-Sperre
werden durch diesen Abschluss nicht vorgezogen.

## EB-08 — nicht ausführbarer ConsolidationPlan

ADR-0034 ist vollständig umgesetzt. EB-08 liefert immutable
`ConsolidationPlan`-DTOs, `canonical-json/v1`, reine Preconditions- und
Blocker-Builder, eine reviewpflichtige Keep Preference, Migration `0016`,
insert-only Persistenz, den deterministischen pfadfreien Report
`ebook-consolidation-report` sowie einen statischen Non-Execution-Gate-Test
gegen Filesystem-Mutationen, mutierende Calibre-Command-Shapes und
öffentliche Ausführungssurfaces. Jeder Plan bleibt dauerhaft
`NOT_EXECUTABLE`. ADR-0056 deutet diese W9-Pläne nicht um; ausschließlich ein
neuer, kurzlebiger W10-Authorization-Snapshot darf den separaten
Interim-Quarantäneexecutor öffnen.

| ID | Status | Item |
|---|---|---|
| S-EB08-01 | DONE | Immutable `ConsolidationPlan`-DTOs und feste Status-, Rollen- und Blocker-Literale. |
| S-EB08-02 | DONE | Kanonische `canonical-json/v1`-Serialisierung und SHA-256-`content_hash`. |
| S-EB08-03 | DONE | Reiner Precondition Builder für Candidate-/Keeper-Snapshots. |
| S-EB08-04 | DONE | Hard Blocker für Root-, Review-, Calibre-, Sidecar-, Archive- und Lineage-Grenzen. |
| S-EB08-05 | DONE | Reine, versionierte und reviewpflichtige Keep Preference. |
| S-EB08-06 | DONE | Additive Migration `0016` und insert-only Planpersistenz. |
| S-EB08-07 | DONE | Planner für actionable Identity, Quality Evidence, Keep Preference und Preconditions. |
| S-EB08-08 | DONE | Deterministischer path-free Reporter und read-only CLI. |
| S-EB08-09 | DONE | Statischer Non-Execution-Test und dokumentierter W9-Abschluss. |

## W8 — Calibre Library Adapter

| ID | Status | Item |
|---|---|---|
| W8-001 | DONE | Implement read-only Calibre library integration with provenance-preserving observations through EB-07. |
| W8-002 | DONE | Analyze Calibre/filesystem consistency, duplicates and metadata/authority conflicts without modifying Calibre. |
| W8-003 | DONE | Model read-only ownership and dependency Evidence for Calibre records, formats, `metadata.opf`, covers, archive containers and other sidecars before any Keep preference. |

## W9 — Consolidation Planning

| ID | Status | Item |
|---|---|---|
| W9-001 | DONE | Implement non-executable consolidation plans and preconditions. |
| W9-002 | DONE | Keep duplicate identity separate from quality ranking/keep preference. |
| W9-003 | DONE | Represent changed-since-analysis checks needed by future execution. |
| W9-004 | DONE | Produce a complete non-executable, content-addressed e-book deduplication plan with Keeper, quarantine, verification, rollback, purge, Calibre, sidecar, archive and empty-directory preconditions. |
| W9-005 | DONE | Require Review approval for Keep preference and every future mutation candidate; keep exact duplicate identity, quality ranking and physical operation separate. |
| W9-006 | DONE | Implemented a non-executable, content-addressed `MetadataCorrectionPlan` that binds observed values, reviewed canonical candidates, one explicit target carrier, dependencies, writer profile, changed-since-analysis preconditions and post-write verification without exposing a writer. |
| FG-W9-006 | DONE | ADR-0062 definiert den separaten immutable `MetadataCorrectionCandidate`, den append-only Reviewvertrag, content-addressed Candidate und Plan, fünf getrennte Zielträger, feste Preconditions, Post-write-Verifikation, Privacy und die permanente `NOT_EXECUTABLE`-Grenze. |
| S-W9-006A | DONE | Immutable Candidate-/Plan-DTOs, bounded Feld-/Ziel-/Dependency-/Review-/Precondition-/Verification-Verträge, reine Reducer, deterministische UUIDv5-/`canonical-json/v1`-Identitäten, Golden Values und ein statischer Non-Execution-Gate sind implementiert. Das Paket importiert weder Persistenz, CLI, Tooling noch Filesystemmodule. |
| S-W9-006B | DONE | Review-Core additiv erweitert; Migration `0026` erhält bestehende Review-Historien und persistiert den normalisierten Candidate-/Plan-Graph insert-only. Der bounded Store prüft Content-Identitäten, den kanonischen Reducer, Source-/Evidence-/Dependency-/Target-/Review-Lineage und idempotente Retries atomar. |
| S-W9-006C | DONE | `ebook-metadata-correction-report` liest genau einen persistierten Plan über `mode=ro` und `query_only=ON`. Text und JSON enthalten nur erlaubte IDs, Profile, Status, Content Hash, Zielträger, Format, Feld-/Operationsnamen, Counts, Reviewstatus und Blockerliterale; Bootstrap und Fehler bleiben pfad- und metadatenwertfrei. |
| W9-007 | DONE | Non-executable, reproducible recipes for rename, reorganization, import/export, transformation and archive/container changes are implemented through pure contracts, insert-only persistence/review and a true SQLite-read-only report; every operation remains behind its own W10 gate. |
| FG-W9-007 | DONE | ADR-0065 definiert Candidate-Review-Plan-Trennung, sechs feste Operationstypen, Source-/Target-/Outputidentität, fünf Dependency-Achsen, Processor-/Collision-/Workspace-/Recovery-/Verification-Verträge, kanonische Identität, Privacy und die permanente `NOT_EXECUTABLE`-Grenze. |
| S-W9-007A | DONE | `foliotone.ebook_operation_recipes` liefert immutable DTOs, reine Builder/Reducer, deterministische UUIDv5-/`canonical-json/v1`-Identitäten, Golden Values und einen statischen Non-Execution-Gate. Das Paket importiert weder Persistence, CLI, Tooling, Adapter noch Filesystem-/Prozessmodule. |
| S-W9-007B | DONE | Review-Core und SQLite-Constraint sind um die feste Recipe-Paarung erweitert. Migration `0030` erhält vorhandene Review-Historie und abhängige Trigger; zehn Tabellen persistieren Candidate-/Plan-Graph insert-only und bounded. Der Store revalidiert Content-Identitäten, kanonischen Reducer sowie Source-/Hash-/Evidence-/Dependency-/Target-/Review-Lineage atomar und idempotent, ohne Source Media zu öffnen. |
| S-W9-007C | DONE | `ebook-operation-recipe-report` liest genau einen persistierten Plan über `mode=ro` und `query_only=ON`, ohne Migration. Text und JSON enthalten ausschließlich opaque Plan-/Candidate-IDs, Profile, Operationstyp, Status, Counts, Reviewstatus und Blockerliterale; Locator, Source-/Target-IDs, Hashes und Materialwerte bleiben ausgeschlossen. |

## W10 — Controlled Consolidation

| ID | Status | Item |
|---|---|---|
| W10-001 | DECISION | ADR-0056 bindet Vertrag, Persistenz und Status einer gefenceten Ein-Datei-Quarantäne. W9-Pläne bleiben nicht ausführbar; nur eine neue, kurzlebige W10-Authorization darf den Interim-Executor öffnen. |
| FG-W10-WRITE-DEVELOPMENT | DONE | ADR-0061 hält die ausdrückliche Owner-Freigabe für die kontrollierte Entwicklung der E-Book-Schreibstrecke fest. Synthetische Writer-Tests sind erlaubt; reale Mutation benötigt weiterhin eine eigene technische ADR, Capability, Authorization, Revalidierung, Fencing, Journal und Recovery. |
| W10-002 | DONE | S-W10-01 bis S-W10-04 liefern path-freie Verträge, immutable Authorization-/Run-/Eventpersistenz, einen engen Interim-Executor und `quarantine-status` als echte SQLite-Read-only-Projektion: gleicher vom OS gemeldeter Filesystem-Kontext, Ziel-Abwesenheitsprüfung, `os.rename`, Full-SHA-256-Revalidierung sowie ausschließlich opaque Statusausgabe. Kein Copy+Delete oder Cross-Volume-Fallback. |
| S-DOC-W10-01 | DONE | Pauschale Alttexte zur W10-Sperre sind auf ADR-0056 harmonisiert: Nur die enge S-W10-03-Interim-Quarantäne ist ausführbar; `FG-W10-MOVE-BACKEND` bleibt die verpflichtende, geplante Frontier-Härtung. |
| W10-005 | DONE | Die ADR-0056-Bedienkette besitzt Capability-Auflösung, Authorize, zweite Bestätigung, One-use-Fencing, Execute, read-only Status und eine feste Recovery-Matrix. Sie bleibt bei genau einer regulären Same-Filesystem-Datei und behauptet keine atomare No-Replace-Garantie. |
| S-W10-05A | DONE | Privater, bounded und fail-closed `QuarantineCapabilityResolver`: `FOLIOTONE_QUARANTINE_CAPABILITIES_FILE` löst nur eine opaque Capability-ID zu ScanRoot-ID und privaten absoluten Verzeichnissen auf. Fehlende/unsichere Konfiguration, Schema-/Duplikat-/Pfad-/Reparse-/Berechtigungsfehler ergeben ausschließlich `TOOL_UNAVAILABLE`. Keine CLI, Persistenz, Reports oder Executor-Aufrufe. |
| S-W10-05B | DONE | `quarantine-authorize` bindet opaque Plan-ID, vollständigen Plan-Content-Hash und Capability-ID an einen höchstens 15 Minuten gültigen Snapshot. Der Operator revalidiert aktuelle Plan-/Review-/Dependency-/File-/Observation-Lineage, streamt Keeper und Candidate gegen Größe, Modified-Zeitpunkt und Full-SHA-256 und persistiert nur nach erneuter atomarer Planprüfung. Ausgabe und Fehler bleiben pfad-, dateinamen- und materialhashfrei; es gibt keinen Executor-Aufruf oder Source-Write. |
| S-W10-05C | DONE | `quarantine-execute` prüft erneut alle opaque Binder, akzeptiert exakt eine begrenzte nicht geloggte `stdin`-Bestätigung, verbraucht die Authorization atomar beim bestätigten `PREPARED`-Insert, revalidiert Plan, Source und Capability unter einer `CONSOLIDATION_QUARANTINE_RUN`-Lease und ruft ausschließlich den vorhandenen Interim-Executor auf. |
| S-W10-05D | DONE | `quarantine-recover` nimmt genau eine opaque Run-ID, rekonstruiert ausschließlich bestätigte historische Bindungen, klassifiziert die exakte Source-/Zielverteilung unter einer frischen oder sicher übernommenen Run-Lease und ergänzt nur fehlende Journalereignisse. Recovery führt keinen Move aus; unklare Zustände enden ohne Dateisystemmutation bei `MANUAL_REVIEW`. |
| FG-W10-MOVE-BACKEND | PLANNED | Spätere Frontier-Härtung für einen atomaren No-Replace-Move, no-follow Elternverzeichnisse sowie reproduzierbare Cross-Device-, Race- und Crash-/Recovery-Nachweise. Der Interim-Executor ist bewusst nicht atomar; seine Zielprüfung kann eine konkurrierende Race nicht ausschließen. |
| FG-W10-METADATA-WRITE | DONE | ADR-0063 akzeptiert ausschließlich `ebook-source-metadata-write/epub3-title-replace/v1`: ein EPUB-3-`SOURCE_METADATA`-Plan, ein `title`-`REPLACE`, lexikalischer Zwei-Spannen-Patch, memberweiser Diff, privates Staging und Linux-`renameat2`-Exchange mit Same-Filesystem-Recovery. Andere Formate, Felder und Zielträger bleiben geschlossen. |
| W10-006 | DONE | Der durch ADR-0063 begrenzte EPUB-Titelwriter ist über fünf Subwaves vollständig implementiert. ADR-0064 bindet CLI, zweite Bestätigung, unmittelbare Verifikation, Scan-/Collection-Reconciliation und Recovery-Abschluss; andere Writer bleiben geschlossen. |
| S-W10-MW01 | DONE | `foliotone.metadata_write` revalidiert den exakten reviewten Plan, denselben Full-SHA-256 und gepinnte EPUBCheck-/EPUB-3-Evidence, prüft bounded OCF-/ZIP-/XML-Verträge, ersetzt ausschließlich `dc:title` und `dcterms:modified` und belegt danach genau einen geänderten Package-Document-Member. Das reine Bytes-API besitzt keine Datei-, Persistenz-, Tool-, CLI-, Capability- oder Execute-Fläche. |
| S-W10-MW02 | DONE | `epub3-title-private-staging/v1` kopiert den gebundenen Input ohne Source-Pfad in einen exklusiven privaten Ordner, baut den OCF-Container memberweise streaming-basiert neu auf und belegt den vollständigen Diff. `epub3-title-staged-validation/v1` führt feste nicht persistierende `ebook-meta`-, EPUBCheck-, Text- und Cover-Read-backs gegen Input/Output aus und revalidiert beide Hashes; keine Capability, CLI oder Source-Commit-Fläche. |
| S-W10-MW03 | DONE | `metadata-write-authorization/v1` bindet den content-addressed Prepare-Snapshot, den aktuellen reviewten W9-Plan, Input-/Outputidentität, Writer-/Validatorversionen, Capability-ID und ein höchstens 15 Minuten offenes Zeitfenster. Migration `0027` persistiert Authorization, einmaligen Run und gapless Events insert-only; Preparation und Run verwenden eigene `ScanRootWriteLease`-Owner und jede Persistenz ist fence-gebunden. Der private Capability-Resolver und die read-only Statusprojektion geben keine Pfade, Metadatenwerte, Hashes, Capability-Inhalte, Fences oder Finding-Digests aus. Es existiert weiterhin kein Executor oder CLI-Writepfad. |
| S-W10-MW04 | DONE | `epub-source-replace-linux-renameat2/v1` öffnet Source und Recovery no-follow über feste Directory-FDs, verlangt Linux x86_64 plus glibc, dieselbe erlaubte lokale Filesysteminstanz und einen persistent geprüften `RENAME_EXCHANGE`-/`RENAME_NOREPLACE`-Probevertrag. Migration `0028` bindet Backend und Probe immutable an den Run. Der Executor revalidiert Authorization, Plan/Review/File, Full-SHA-256, Attribute und Root-Fence unmittelbar vor dem Exchange, bewahrt das Original no-replace content-addressed und stoppt bei `ORIGINAL_PRESERVED`; die idempotente Recovery mutiert nur exakte bekannte Hashverteilungen und markiert Uneindeutigkeit manuell. Kein CLI-, Delete-, Copy-, Overwrite- oder Fallbackpfad. |
| S-W10-MW05 | DONE | Feste Authorize-/Execute-/Recover-/Status-CLI, zweite Bestätigung über nicht geloggtes `stdin`, unmittelbare Source-Verifikation, expliziter Lease-Handoff, neuer inkrementeller Vollscan, `CollectionState` und immutable Reconciliation sind implementiert. |
| FG-W10-SIDECAR-WRITE | DECISION | Entscheide Sidecar Create/Update separat mit Ownership, Kollisions-, No-Follow-, Atomizitäts-, Dependency-, Recovery- und Reconciliation-Vertrag. |
| FG-W10-EXTERNAL-LIBRARY-WRITE | DECISION | Entscheide mutierendes Calibre oder andere externe Systeme je Adapter und fester Operation mit eigenem Snapshot, Idempotenz, Konflikt-, Recovery- und Auditvertrag. |
| FG-W10-RENAME | DONE | ADR-0066 akzeptiert ausschließlich byte-identischen `FILE_RENAME` auf einen historisch unbenutzten Basename im selben bestehenden Parent. Private Capability, Linux-`openat2`/`renameat2(RENAME_NOREPLACE)`, Revalidierung, Fencing, Journal, Exact-State-Recovery, Scan und nicht vereinigende `FileRecord`-Reconciliation sind festgelegt; das docs-only Gate selbst öffnet keine Mutation. |
| S-W10-RN01 | NEXT | Ergänze die nicht mutierenden Befehle `ebook-rename-propose`, `ebook-rename-preview --private-details`, `ebook-rename-review` und `ebook-rename-plan` auf dem bestehenden W9-Recipe-/Review-Store. Der Ziel-Basename kommt bounded und ungeloggt über `stdin`; eine opaque Dependency-Scope-ID bindet explizite Coverage, und bloß fehlende Zeilen bleiben `UNKNOWN`. Es gibt keine Capability oder Source-Mutation. |
| S-W10-RN02 | PLANNED | Implementiere reine Preparation-/Authorization-/Run-/Event-Verträge, private Rename-Capability und persistenten Conformance-Probe, additive insert-only Migration `0031_ebook_rename_operations`, `EBOOK_RENAME_PREPARATION`-/`EBOOK_RENAME_RUN`-Leases sowie echten SQLite-read-only Status; kein Executor. |
| S-W10-RN03 | PLANNED | Implementiere das feste Linux-x86_64-glibc-Backend mit `openat2` und genau einem `renameat2(RENAME_NOREPLACE)`, unmittelbarer Inode-/Byte-/Attributverifikation, Parent-`fsync` und der ADR-0066-Exact-State-Recovery; keine CLI und kein Fallback. |
| S-W10-RN04 | PLANNED | Ergänze feste Authorize-/Execute-/Recover-/Status-Kommandos, zweite `stdin`-Bestätigung, Lease-Handoff, neuen Scan, `CollectionState`, Migration `0032_ebook_rename_reconciliation` und den immutable `EbookRenameReconciliationSnapshot`; erst diese Wave macht das enge Profil operativ erreichbar. |
| FG-W10-REORGANIZE | DECISION | Entscheide `FILE_REORGANIZE` separat mit zwei Parent-FDs, Haltbarkeit beider Verzeichniseinträge, vorhandener beziehungsweise neuer Zielverzeichnisstruktur, Dependencies, Recovery und Reconciliation. ADR-0066 autorisiert keinen Parentwechsel. |
| FG-W10-ARCHIVE-REWRITE | DECISION | Entscheide Archive-/Container-Rewrite separat; erfolgreiche Extraction oder Transformation darf keine Source-Löschung implizieren. |
| W10-003 | DECISION | Decide verified rollback and separately approved purge after a retention period; never make successful extraction imply archive deletion. |
| W10-004 | DECISION | Decide bottom-up empty-directory cleanup as a separate approved operation with fresh enumeration, root/reparse/Calibre/sidecar guards and an auditable reconstruction record. |

## Cross-cutting future candidates

| ID | Status | Item |
|---|---|---|
| FUT-001 | PLANNED | Extend the implemented e-book cover Evidence to music-release artwork and later calibrate cross-item visual-distance use; perceptual hashes remain supporting Evidence only. |
| FUT-002 | PLANNED | E-book structural/quality assessment, separate from identity; reuse EPUB validation tools where suitable. |
| FUT-003 | PLANNED | Audio quality/corruption assessment, separate from identity; reuse ffmpeg/ffprobe or specialist tools where suitable. |
| FUT-004 | PLANNED | Research further authority/catalog providers (e.g. VIAF, ISNI, national libraries, Cover Art Archive, Discogs) only after current access/license review. |
| FUT-005 | PLANNED | Learn deterministic local alias/parsing/ranking rules from review history before considering more complex ML. |
| FUT-006 | DECISION | Die allgemeine `Library Health`-Idee wird für den ersten book-only Slice durch ADR-0058 und `CS-03` konkretisiert; eine medienübergreifende Generalisierung bleibt bis nach Music W4 offen. |
| FUT-007 | PLANNED | Completeness/gap detection for book series, album tracks/releases and classical multi-part works, reusing external specialist evidence where possible. |
| FUT-008 | PLANNED | Reproducible transformation/normalization recipes with versioning, dry-run and replay semantics. |
| FUT-009 | PLANNED | Integrity/fixity monitoring for unexpected file changes/bit rot independent of duplicate detection. |
| FUT-010 | DECISION | Decide ADR-0042 and the staged FG-FED-IDENTITY/BUNDLE/MERGE/CARRIER contracts for portable object lineage and bounded, idempotent exchange between FolioTone systems. The first slice uses only synthetic packages and read-only carrier detection; it must define node clone/restore semantics, privacy, trust, replay/conflict handling and Decision Compatibility without introducing a universal Asset type. Embedded metadata, Sidecar and external-library writes remain separate W10-blocked work. |
| FUT-011 | DECISION | Plane vor API/UI-Code eine eigene Produktoberflächen-ADR: versionierte Application-Commands/-Queries, getrennte Einstiegspunkte für E-Books, Musik, Bilder und spätere Linien, REST-/OpenAPI-Vertrag, Authentisierung/Autorisierung, Pagination, Privacy, Audit sowie strikt getrennte Read- und W10-Write-Capabilities. `EBOOK_WRITE_PIPELINE_PLAN.md` hält die Zielgrenze fest; bis zur ADR bleibt ausschließlich die CLI aktiv. |

## Book-only Produktprojektionen

ADR-0058 bindet die folgende Reihenfolge. Die drei Aufgaben sind read-only und
öffnen weder Music noch Federation oder weitere W10-Operationen.

| ID | Status | Item |
|---|---|---|
| FG-CS-01 | DONE | Accept ADR-0058 for book-only `CollectionState`, deterministic Diff, bounded local metadata query and multidimensional `Library Health` with explicit private-detail opt-in. |
| CS-01 | DONE | Implemented immutable, rebuildable `collection-state/v1`, additive insert-only persistence, `collection-state-build` and true SQLite-read-only `collection-state-report` over exactly one completed `ScanRun`. |
| CS-02 | DONE | Implemented deterministic `collection-state-diff/v1` and bounded `collection-query/v1` with fixed AST allowlist, keyset pagination, snapshot-bound metadata-only FTS index, `collection-state-diff` and `collection-search`. |
| CS-03 | DONE | Implemented immutable `library-health/v1`, additive Migration `0025`, atomare Bindung an `CollectionState` und Query-Index sowie das echte SQLite-read-only `library-health-report`. Sieben unabhängige Dimensionen, vollständige Finding-Counts, begrenzte opaque Samples und reproduzierbarer Baseline-Vergleich verwenden weder Gesamtscore noch Mutation Authority. |

## Operativer Collection-Abschluss

| ID | Status | Item |
|---|---|---|
| OPS-001 | READY | Execute the full private inventory, candidate-hash, collection-analysis and completion-verifier sequence only as a coordinated local operating procedure. Keep Source Media read-only, store all artifacts outside Git and record only abstract pass/degraded/open evidence in project status. |
