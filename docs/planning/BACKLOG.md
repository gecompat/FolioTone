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
| W0-006 | DONE | Verify Install/Ruff/Mypy/Pytest plus Docker build and `foliotone status` bootstrap in GitHub Actions run `31279709278`. |
| W0-007 | DECISION | Select a project license before encouraging third-party reuse/distribution. |
| W0-008 | DONE | Extend architecture with Authority/Entity Resolution, provenance, external enrichment, MusicWork/ReleaseGroup, multidimensional classification, source registry, and W10 safety gate. |
| W0-009 | DONE | Install the GitHub Actions workflow at `.github/workflows/ci.yml`. |
| W0-010 | DONE | Adopt orchestration-first ToolProvider architecture; add ADR-0010, external-tool registry, tooling package boundary, safety and AI handover rules. |

## W1 — Core + Persistence

| ID | Status | Item |
|---|---|---|
| W1-001 | DONE | Design concrete entity/value-object boundaries and opaque UUID internal ID strategy; preserve knowledge-provider and ToolProvider independence. |
| W1-002 | DONE | Implement FileRecord, ScanRoot, ScanRun, FileObservation, presence/observation states. |
| W1-003 | DONE | Implement Agent, AgentName, AgentType, ExternalIdentifier, Contribution, and provenance/value assertion states. |
| W1-004 | DONE | Implement Work, Edition, Series, SeriesMembership. |
| W1-005 | DONE | Implement MusicWork, MusicWorkRelation, CatalogDesignation, Recording, ReleaseGroup, Release, ReleaseRecording. |
| W1-006 | DONE | Implement ClassificationAssertion, Fingerprint, Relation, Evidence, match/review status and version metadata. |
| W1-007 | NEXT | Choose and implement SQLite migration mechanism; document choice in an ADR. |
| W1-008 | READY | Implement persistence contracts and SQLite repositories without leaking SQLite/provider/tool schemas into domain logic. |
| W1-009 | READY | Add round-trip, migration, constraint, provenance, relationship, and failure-mode tests. |
| W1-010 | DONE | Implement adapter-neutral ToolProviderDescriptor, ToolExecution, and ToolResult provenance contracts with stale-version inputs. |
| W1-011 | READY | Update schema/domain documentation and project status from actual persistence implementation; close W1. |

## W2 — Incremental Index + Filename/Path Context + Tool Runtime

| ID | Status | Item |
|---|---|---|
| W2-001 | PLANNED | Implement configured scan roots and scan-run lifecycle. |
| W2-002 | PLANNED | Implement filesystem discovery and relative-path observations. |
| W2-003 | PLANNED | Implement incremental NEW/UNCHANGED/MODIFIED/MISSING behavior. |
| W2-004 | PLANNED | Design robust DELETED confirmation policy. |
| W2-005 | PLANNED | Implement streamed SHA-256 and quick fingerprint strategy. |
| W2-006 | PLANNED | Implement move/rename candidate detection. |
| W2-007 | PLANNED | Add interruption/resume and unavailable-root tests. |
| W2-008 | PLANNED | Implement versioned FilenameParser and PathContextAnalyzer that emit provenance-preserving FieldCandidate values. |
| W2-009 | PLANNED | Add configurable parsing rules/fixtures for author-title, series/volume, track/disc, year and language conventions. |
| W2-010 | PLANNED | Implement generic ToolProvider runtime: discovery/version detection, bounded CLI/container execution, timeout/cancellation, stdout/stderr/artifact capture, safe work directories and read-only media policy. |
| W2-011 | PLANNED | Add ToolProvider runtime tests for missing tool, version change, timeout, non-zero exit, malformed output, read-only safety and selective re-analysis. |

## W3 — E-book Analysis / Tool Orchestration

| ID | Status | Item |
|---|---|---|
| W3-001 | PLANNED | Evaluate current calibre CLI plus specialist EPUB/PDF tools before selecting FolioTone-native parser libraries; document reuse/rejection decisions and licenses. |
| W3-002 | PLANNED | Implement first read-only calibre ToolProvider vertical slice for metadata extraction (`ebook-meta`) and, where useful, read-only library queries through `calibredb`. |
| W3-003 | PLANNED | Implement EPUB content/text extraction and normalized text fingerprint only for capabilities not adequately supplied by the selected tool chain. |
| W3-004 | PLANNED | Implement PDF metadata/page/text analysis using the best tool/library combination; explicitly represent no-text PDFs. |
| W3-005 | PLANNED | Support MOBI/AZW/AZW3 observations through calibre or another maintained tool before writing format-specific code. |
| W3-006 | PLANNED | Extract ISBN, contributors, language, publisher, series and other fields as observations/candidates with ToolExecution/provenance links. |
| W3-007 | PLANNED | Add synthetic/public fixtures covering identical file, changed metadata, same edition, different edition/translation and tool disagreement. |
| W3-008 | PLANNED | Evaluate calibre/other structural validation and book-diff capabilities as reusable evidence for future quality/content comparison. |
| W3-009 | PLANNED | Evaluate cover-image extraction/perceptual fingerprint as optional future evidence; do not block initial analyzer. |

## W4 — Music Analysis / Tool Orchestration

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

## W9 — Consolidation Planning

| ID | Status | Item |
|---|---|---|
| W9-001 | PLANNED | Implement non-executable consolidation plans and preconditions. |
| W9-002 | PLANNED | Keep duplicate identity separate from quality ranking/keep preference. |
| W9-003 | PLANNED | Represent changed-since-analysis checks needed by future execution. |

## W10 — Controlled Consolidation

| ID | Status | Item |
|---|---|---|
| W10-001 | BLOCKED | Write-capable FolioTone or external-tool consolidation; blocked until explicit accepted ADR authorizes it. |

## Cross-cutting future candidates

| ID | Status | Item |
|---|---|---|
| FUT-001 | PLANNED | Cover/image perceptual fingerprints as supporting evidence for book editions/music releases. |
| FUT-002 | PLANNED | E-book structural/quality assessment, separate from identity; reuse EPUB validation tools where suitable. |
| FUT-003 | PLANNED | Audio quality/corruption assessment, separate from identity; reuse ffmpeg/ffprobe or specialist tools where suitable. |
| FUT-004 | PLANNED | Research further authority/catalog providers (e.g. VIAF, ISNI, national libraries, Cover Art Archive, Discogs) only after current access/license review. |
| FUT-005 | PLANNED | Learn deterministic local alias/parsing/ranking rules from review history before considering more complex ML. |
| FUT-006 | PLANNED | Library Health dashboard combining integrity, metadata quality, unresolved entities, duplicates, completeness gaps and storage-saving estimates. |
| FUT-007 | PLANNED | Completeness/gap detection for book series, album tracks/releases and classical multi-part works, reusing external specialist evidence where possible. |
| FUT-008 | PLANNED | Reproducible transformation/normalization recipes with versioning, dry-run and replay semantics. |
| FUT-009 | PLANNED | Integrity/fixity monitoring for unexpected file changes/bit rot independent of duplicate detection. |
