# ADR-0001: Python as implementation language

- Status: Accepted
- Date: 2026-08-08

## Context

FolioTone needs filesystem processing, structured metadata extraction, content/audio analysis integrations, a CLI, SQLite persistence, and a strong ecosystem for e-book and audio tooling on Linux.

## Decision

Use Python as the primary implementation language. The initial supported baseline is Python 3.12 or newer.

## Consequences

- Python owns orchestration and domain logic.
- Native/CLI tools may later be integrated behind adapters when they are clearly better suited to a format or fingerprinting task.
- Third-party library choices remain wave-specific and must be validated for maintenance status, license, correctness, and streaming behavior before adoption.
