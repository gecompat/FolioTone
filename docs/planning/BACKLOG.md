# Backlog

Statuses: `DONE`, `NEXT`, `READY`, `PLANNED`, `BLOCKED`, `DECISION`.

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
| W3-017 | IN PROGRESS | Harden incremental scan/hash persistence from real read-only scale evidence; add recoverable `ScanRun` leases for externally orphaned `RUNNING` attempts, format-balanced pilot planning, resumable full-SHA enrichment limited to Quick duplicate candidates, a current-scan-first materialized candidate snapshot with a measured lookup index, root-wide fenced candidate-hash runs with durable path-free heartbeat/status, a deterministic scan-wide inventory/hash/duplicate report, true SQLite-read-only JSON status and a path-free postscan completion verifier; complete the private collection analysis/report without changing source media or committing private paths, counts, or runtime data. The controlled cutover and book-only continuation through W9 are detailed in [`W3_017_EBOOK_ROADMAP.md`](W3_017_EBOOK_ROADMAP.md). |
| W3-018 | PLANNED | Evaluate signature-first ZIP/RAR/7z/TAR/CBR/CBZ discovery and maintained read-only listing/integrity tools; decide publication-container, multipart, license, version and sandbox contracts before implementing an adapter. |
| W3-019 | PLANNED | Persist bounded incremental archive, volume and sidecar inventory Evidence without extraction; report encryption, missing volumes, corruption and unsupported methods path-free. |
| W3-020 | PLANNED | Implement bounded local archive-password candidates from explicit Secret Handles, container comments, adjacent NFO/TXT/DIZ/INFO/URL/HTML/SFV/README hints and configured local lists; persist no plaintext password and perform no brute force. |
| W3-021 | PLANNED | Implement read-only bounded archive listing/integrity plus private sandboxed test extraction with traversal, symlink, decompression-bomb, nesting, member-count, size and timeout guards; never delete the source archive. |
| W3-022 | PLANNED | Persist versioned archive-member Evidence and reuse it only for unchanged archive/tool/adapter/config/secret identities; keep CBR/CBZ/EPUB publication containers distinct from disposable packaging. |

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
| W5A-001 | PLANNED | Implement versioned Unicode/name normalization without destructive overwrite. |
| W5A-002 | PLANNED | Resolve Agent candidates using aliases, pseudonyms, sort names, credited-as forms, transliterations and local confirmed knowledge. |
| W5A-003 | PLANNED | Implement homonym protection; equal normalized names must not auto-merge Agents. |
| W5A-004 | PLANNED | Implement Work/Edition/Series and MusicWork/Recording/ReleaseGroup/Release resolution candidates with explanations/confidence. |
| W5A-005 | PLANNED | Persist confirmed/rejected local authority mappings separately from source observations. |

### W5B — External enrichment infrastructure/providers

| ID | Status | Item |
|---|---|---|
| W5B-001 | PLANNED | Implement provider interface and explicit OFFLINE/LOCAL_DATASETS/ONLINE_STRUCTURED/ONLINE_WEB_RESEARCH modes. |
| W5B-002 | PLANNED | Implement persistent provider cache/import/version state under `/data`; no provider cache in Git. |
| W5B-003 | PLANNED | Implement privacy-minimized query DTOs; never send absolute paths. |
| W5B-004 | PLANNED | Review and select first book/authority providers from Open Library, GND/DNB and Wikidata; record current access/license constraints before coding adapters. |
| W5B-005 | PLANNED | Review and select first music knowledge providers from MusicBrainz and AcoustID; Chromaprint/fpcalc remains a local ToolProvider concern. |
| W5B-006 | PLANNED | Evaluate/import official bulk/local datasets where they are more appropriate than per-file API lookup. |
| W5B-007 | PLANNED | Implement at least one structured book/authority adapter and one structured music adapter as initial vertical slices. |
| W5B-008 | PLANNED | Add offline/provider-failure/cache-hit/cache-refresh tests. |
| W5B-009 | PLANNED | Define generic web research fallback interface; keep it separately enabled and candidate-only. |
| W5B-010 | PLANNED | Evaluate a local MusicBrainz mirror/container deployment only if scale/rate/latency justifies its operational cost. |
| W5B-011 | PLANNED | Resolve the user-supplied `Newzcrabber` name to a concrete maintained service and evaluate it plus suitable alternatives as explicit opt-in archive-password candidate providers; require a documented interface, current terms/license/privacy review, path-free queries, local cache and Secret Handles, otherwise record a non-integration decision. |

### W5C — Classification

| ID | Status | Item |
|---|---|---|
| W5C-001 | PLANNED | Implement typed multidimensional classification assertions with source/taxonomy provenance. |
| W5C-002 | PLANNED | Support e-book domain/genre/subgenre/topic/audience/language/form facets. |
| W5C-003 | PLANNED | Support music domain/style plus classical period/form/instrumentation facets. |
| W5C-004 | PLANNED | Preserve conflicting provider/tool classifications and derive canonical/local projections separately. |

## W6 — Matching

| ID | Status | Item |
|---|---|---|
| W6-001 | PLANNED | Finalize relation taxonomy and validation rules across File/Edition/Work/MusicWork/Recording/ReleaseGroup/Release levels. |
| W6-002 | PLANNED | Implement candidate blocking using hashes, identifiers, resolved entities, text/audio fingerprints, durations and contextual/tool-derived keys. |
| W6-003 | PLANNED | Implement versioned feature/scoring pipeline. |
| W6-004 | PLANNED | Persist human-readable evidence/explanations including ToolExecution provenance. |
| W6-005 | PLANNED | Calibrate review thresholds using controlled fixtures; prioritize false-positive protection. |
| W6-006 | PLANNED | Test that agreement among external tools/providers cannot mask contradictory content/edition/recording evidence. |
| W6-007 | PLANNED | Match archive members, physical files and publication containers at separate file/content/Edition levels; an online password result or equal filename is never sufficient identity Evidence. |

## W7 — Review

| ID | Status | Item |
|---|---|---|
| W7-001 | PLANNED | Persist review queue, decisions, defer/reject/accept semantics and history. |
| W7-002 | PLANNED | Review/confirm/reject authority candidates and aliases as well as duplicate relations. |
| W7-003 | PLANNED | Reuse confirmed local knowledge and avoid needless repeated review when evidence/tool/resolver versions are unchanged. |

## W8 — Calibre Library Adapter

| ID | Status | Item |
|---|---|---|
| W8-001 | PLANNED | Build on the earlier calibre ToolProvider and implement read-only Calibre library integration with provenance-preserving observations. |
| W8-002 | PLANNED | Analyze Calibre/filesystem consistency, duplicates and metadata/authority conflicts without modifying Calibre. |
| W8-003 | PLANNED | Model read-only ownership and dependency Evidence for Calibre records, formats, `metadata.opf`, covers, archive containers and other sidecars before any Keep preference. |

## W9 — Consolidation Planning

| ID | Status | Item |
|---|---|---|
| W9-001 | PLANNED | Implement non-executable consolidation plans and preconditions. |
| W9-002 | PLANNED | Keep duplicate identity separate from quality ranking/keep preference. |
| W9-003 | PLANNED | Represent changed-since-analysis checks needed by future execution. |
| W9-004 | PLANNED | Produce a complete non-executable, content-addressed e-book deduplication plan with Keeper, quarantine, verification, rollback, purge, Calibre, sidecar, archive and empty-directory preconditions. |
| W9-005 | PLANNED | Require Review approval for Keep preference and every future mutation candidate; keep exact duplicate identity, quality ranking and physical operation separate. |

## W10 — Controlled Consolidation

| ID | Status | Item |
|---|---|---|
| W10-001 | BLOCKED | Write-capable FolioTone or external-tool consolidation; blocked until explicit accepted ADR authorizes it. |
| W10-002 | BLOCKED | Implement a fenced restartable quarantine-only executor after W10 authorization; revalidate candidate and surviving Keeper with full hashes immediately before each mutation. |
| W10-003 | BLOCKED | Implement verified rollback and separately approved purge after a retention period; never make successful extraction imply archive deletion. |
| W10-004 | BLOCKED | Implement bottom-up empty-directory cleanup as a separate approved operation with fresh enumeration, root/reparse/Calibre/sidecar guards and an auditable reconstruction record. |

## Cross-cutting future candidates

| ID | Status | Item |
|---|---|---|
| FUT-001 | PLANNED | Extend the implemented e-book cover Evidence to music-release artwork and later calibrate cross-item visual-distance use; perceptual hashes remain supporting Evidence only. |
| FUT-002 | PLANNED | E-book structural/quality assessment, separate from identity; reuse EPUB validation tools where suitable. |
| FUT-003 | PLANNED | Audio quality/corruption assessment, separate from identity; reuse ffmpeg/ffprobe or specialist tools where suitable. |
| FUT-004 | PLANNED | Research further authority/catalog providers (e.g. VIAF, ISNI, national libraries, Cover Art Archive, Discogs) only after current access/license review. |
| FUT-005 | PLANNED | Learn deterministic local alias/parsing/ranking rules from review history before considering more complex ML. |
| FUT-006 | PLANNED | Library Health dashboard combining integrity, metadata quality, unresolved entities, duplicates, completeness gaps and storage-saving estimates. |
| FUT-007 | PLANNED | Completeness/gap detection for book series, album tracks/releases and classical multi-part works, reusing external specialist evidence where possible. |
| FUT-008 | PLANNED | Reproducible transformation/normalization recipes with versioning, dry-run and replay semantics. |
| FUT-009 | PLANNED | Integrity/fixity monitoring for unexpected file changes/bit rot independent of duplicate detection. |
