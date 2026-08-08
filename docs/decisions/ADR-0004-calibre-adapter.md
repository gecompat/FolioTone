# ADR-0004: Calibre is an external read-only adapter/tool source

- Status: Accepted
- Date: 2026-08-08

## Context

Calibre is useful for e-book metadata, format tooling and library state, but FolioTone also analyzes music and should not inherit Calibre-specific assumptions as its core model.

ADR-0010 later established an orchestration-first strategy: mature specialist tools should be reused through adapter-neutral ToolProvider boundaries where appropriate.

## Decision

Treat Calibre as an external e-book specialist and library/metadata source accessed through adapter/tool boundaries. The initial integrations are read-only with respect to source media and Calibre library state.

Candidate integration paths include documented calibre CLI tools such as `ebook-meta`, read-oriented `calibredb` operations, and the calibre Content Server where useful.

FolioTone maintains its own domain and persistence model. Calibre observations/results become provenance-preserving evidence and do not automatically become canonical FolioTone values.

## Consequences

- FolioTone can operate without Calibre.
- Calibre schema/command details do not leak into core entities.
- W3 may reuse calibre CLI capabilities before implementing native e-book parsing equivalents.
- W8 builds richer read-only Calibre library consistency analysis on the earlier ToolProvider work.
- Calibre write operations remain prohibited through W9.
- Future Calibre synchronization, if ever implemented, requires separate write-safety design and explicit authorization under the W10 gate.
