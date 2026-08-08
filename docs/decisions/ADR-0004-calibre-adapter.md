# ADR-0004: Calibre is an external read-only adapter

- Status: Accepted
- Date: 2026-08-08

## Context

Calibre is useful for e-book metadata/library state, but FolioTone also analyzes music and should not inherit Calibre-specific assumptions as its core model.

## Decision

Treat Calibre as an external library and metadata source accessed through `adapters/calibre`. The initial adapter is read-only. FolioTone maintains its own domain and persistence model.

## Consequences

- FolioTone can operate without Calibre.
- Calibre schema details do not leak into core entities.
- Future Calibre synchronization, if ever implemented, requires separate write-safety design and explicit authorization.
