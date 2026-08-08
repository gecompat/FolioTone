# ADR-0011: Opaque UUID identifiers and immutable provider-independent core models

- Status: Accepted
- Date: 2026-08-08

## Context

FolioTone must reconcile observations from files, specialist tools, Calibre, authority services and future providers without allowing any one external schema to define internal identity. The same real-world entity can have multiple external identifiers and conflicting metadata.

The initial implementation also needs deterministic persistence boundaries and safe re-analysis when external tools or normalization rules change.

## Decision

Use opaque UUID-backed `EntityId` values for all FolioTone-owned entities.

External identifiers remain separate namespaced domain records and never become internal primary keys.

The W1 core model is implemented as frozen, slotted Python dataclasses with validation at construction boundaries. Core entities do not import SQLite, Calibre, MusicBrainz, calibre CLI, beets, SongKong, Picard, FFmpeg or other concrete provider/tool schemas.

Additional decisions:

- durable file paths in the domain are scan-root-relative and normalized to POSIX separators;
- datetimes crossing domain/persistence boundaries must be timezone-aware;
- confidence values use the inclusive range `0.0..1.0`;
- observed/derived/external/canonical/user-confirmed values remain separate assertions with provenance;
- tool-derived results reference an explicit `ToolExecution` containing tool and adapter versions;
- ToolProvider descriptors are read-only by construction during W0-W9.

## Consequences

- external IDs can be corrected or replaced without changing FolioTone identity;
- the database can store UUIDs as canonical lowercase text initially without coupling domain logic to SQLite;
- source paths can move between hosts without rewriting internal identities merely because an absolute mount path changed;
- stale derived results can later be detected from tool/adapter/rule versions;
- persistence and concrete adapters can evolve independently from the domain layer;
- write-capable ToolProvider behavior requires a future W10 architecture decision rather than a configuration toggle.
