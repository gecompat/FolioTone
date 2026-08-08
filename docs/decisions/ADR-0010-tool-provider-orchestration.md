# ADR-0010: Orchestrate proven external tools before reimplementing equivalent functionality

- Status: Accepted
- Date: 2026-08-08

## Context

FolioTone needs capabilities that mature tools already provide: e-book metadata extraction and library access, audio probing, acoustic fingerprints, music metadata matching, duplicate/missing-track analysis, and format-specific validation.

Reimplementing every mature capability would increase development cost, maintenance burden and defect risk while adding little product-specific value.

FolioTone's differentiating value is the controlled combination of heterogeneous evidence: indexing, provenance, entity resolution, cross-tool reconciliation, explainable matching, review, library health analysis and safe consolidation planning.

## Decision

FolioTone adopts an **orchestration-first** strategy.

Before implementing a substantial media-specific capability, evaluate whether a maintained external tool already provides a suitable, automatable and legally usable implementation. Prefer integration when the external tool has a stable documented CLI, API, structured output, service interface or container execution model.

External executable/service integrations are represented through a `ToolProvider` boundary. Tool-specific schemas, commands and configuration do not leak into core domain logic.

Initial high-value ToolProvider candidates include:

- calibre CLI and calibre Content Server / `calibredb`;
- FFmpeg / `ffprobe`;
- Chromaprint / `fpcalc`;
- beets;
- SongKong;
- MusicBrainz Picard as an optional specialist/validator;
- a local MusicBrainz mirror as a later infrastructure option.

## Evidence contract

An external tool does not become the source of truth merely because it returned a result.

Material tool executions should be able to retain:

- tool/provider identity;
- tool version;
- adapter version;
- operation/profile name;
- relevant configuration/profile digest or version where practical;
- execution timestamp and status/exit code;
- input reference using FolioTone identities/relative paths rather than unnecessary private host context;
- produced observations, candidates, reports or artifact references;
- parser/import version used to interpret tool output;
- explanation/provenance linking downstream Evidence to the ToolExecution.

The same real-world claim may be supported or contradicted by several tools/providers. FolioTone owns the reconciliation and final decision model.

## Safety

Through W9, ToolProviders are analysis-only with respect to source media.

- Prefer read-only mounts.
- Prefer report, status, scan, probe and preview modes.
- Do not invoke tool commands that delete, move, rename or retag source media.
- A tool with write capabilities is not automatically safe because FolioTone itself is read-only.
- Write-capable external-tool operations remain blocked with all other source-media mutation until W10 and a future accepted ADR.

Examples of capabilities that are explicitly not authorized during W0-W9 include duplicate deletion, automatic file moves/renames and metadata writes from beets, SongKong, calibre, Picard or other tools.

## Integration rules

- Prefer documented interfaces over reverse-engineered GUI/web endpoints.
- Prefer machine-readable output such as JSON where available.
- Pin or record tool versions for reproducibility.
- Treat external Docker images as dependencies, not as FolioTone-owned code.
- Do not redistribute third-party binaries/images inside FolioTone unless their current license explicitly permits the intended distribution model.
- Re-check current maintenance status, licensing, automation interface and security implications before implementing each adapter.
- Tool absence or failure should degrade the relevant capability, not corrupt FolioTone state.
- Avoid making one optional commercial tool mandatory when an open or local baseline can provide the essential pipeline.

## Consequences

- W1 must support provenance for external tool executions/results without embedding individual tool schemas.
- W3/W4 become primarily analyzer-orchestration waves: first reuse suitable tool capabilities, then implement FolioTone-native logic only for gaps or differentiated analysis.
- Tool adapters become replaceable components.
- FolioTone can combine calibre, beets, SongKong, Picard, FFmpeg, Chromaprint and future tools without delegating canonical identity/matching decisions to any one of them.
- The project should maintain an external tool registry with integration mode, intended capabilities, safety constraints and official references.
