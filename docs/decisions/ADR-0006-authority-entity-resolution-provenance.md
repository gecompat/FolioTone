# ADR-0006: Authority resolution and provenance are separate from duplicate matching

- Status: Accepted
- Date: 2026-08-08

## Context

Names and titles in real media collections are inconsistent. Examples include reversed person names, initials, aliases, pseudonyms, transliterations, alternate artist credits, incomplete embedded metadata and filename-derived guesses.

Treating text normalization as identity would create false merges. At the same time, duplicate matching benefits significantly from resolved identities and stable external identifiers.

## Decision

FolioTone introduces a separate Authority / Entity Resolution layer before duplicate matching.

Core consequences of this decision:

- contributors are modeled as `Agent` entities rather than independent author/artist strings;
- `AgentName` retains canonical, sort, alias, pseudonym, credited-as and transliteration forms;
- roles are modeled as relationships/contributions;
- external IDs are namespaced and retained as evidence;
- raw observations are never overwritten by normalization or enrichment;
- values/assertions distinguish `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL` and `USER_CONFIRMED` states;
- filename/path parsing emits candidates with provenance rather than directly setting canonical metadata;
- entity-resolution rules and canonical-selection logic are versioned derived logic.

## Consequences

- The W1 domain model must include Agent/alias/provenance concepts before database schema implementation.
- Matching can use resolved entities without losing contradictory source evidence.
- Human review can teach local aliases and reject bad authority candidates without modifying original files.
- Equal normalized names never constitute sufficient proof that two Agents are identical.
- Re-analysis can selectively invalidate derived identity results when normalization or mapping rules change.
