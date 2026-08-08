# ADR-0002: Docker/Linux runtime with host-persistent state

- Status: Accepted
- Date: 2026-08-08

## Context

The analysis environment should be reproducible while index/results survive container recreation.

## Decision

Docker/Linux is the primary runtime. Application state is stored under `/data` and mounted from persistent host storage. SQLite is the initial persistence engine, but persistence access must remain behind an application boundary.

Media roots are mounted separately under `/media` and are read-only in the standard container configuration.

## Consequences

- Rebuilding/replacing the container does not discard the index or review state.
- The SQLite database and runtime cache are never committed to Git.
- Paths inside persisted data should prefer scan-root-relative representation where possible so host mount locations can change.
- A later PostgreSQL option remains possible without changing domain concepts.
