# AGENTS.md — FolioTone working contract

This file is the primary continuation contract for AI coding agents and human contributors. Repository state must be sufficient to continue the project without access to previous chat history.

## 1. Read before changing anything

Read these files in order:

1. `docs/planning/PROJECT_STATUS.md`
2. `docs/planning/HANDOVER.md`
3. `docs/planning/IMPLEMENTATION_PLAN.md`
4. `docs/planning/BACKLOG.md`
5. `docs/architecture/OVERVIEW.md`
6. `docs/architecture/DOMAIN_MODEL.md`
7. `docs/architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`
8. `docs/reference/EXTERNAL_DATA_SOURCES.md` when work touches external knowledge/providers
9. relevant files under `docs/architecture/` and `docs/decisions/`

If repository code and documentation disagree, treat the discrepancy as a defect. Determine the actual state, then update code and documentation together.

## 2. Authoritative project constraints

- Language: Python.
- Primary runtime: Docker/Linux.
- Persistence: host-persistent data mounted at `/data`; SQLite initially.
- Media roots: read-only mounts under `/media`.
- Current product mode: analysis only.
- Calibre: external adapter, never the internal domain model or primary database.
- E-book and music processing: separate analyzers over shared core/index infrastructure.
- Filename/path parsing produces candidates with provenance; it does not set canonical metadata directly.
- Authority/Entity Resolution is a separate stage before duplicate Matching.
- Raw/observed values are never destroyed by normalization or external enrichment.
- Provenance/value states must preserve `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL` and `USER_CONFIRMED` distinctions.
- Contributors are modeled as Agent identities plus typed roles/credits rather than plain author/artist/composer strings.
- MusicWork, Recording, ReleaseGroup and Release are distinct identity levels.
- Classification is multidimensional and provenance-preserving, not a single flat genre field.
- External providers are behind adapters; network use is explicit, cached and privacy-bounded.
- Matching: candidate generation first, then scoring; never global all-vs-all comparison.
- Resolution/matching decisions: preserve evidence, score/confidence, rule/resolver/matcher/provider versions, and review state.
- Consolidation execution: prohibited until W10 is explicitly activated by a later architecture decision.

## 3. Privacy and repository hygiene

Never commit:

- real personal media files or extracted content from a real collection;
- real private filesystem paths, usernames, hostnames, secrets, credentials, tokens, or `.env` files;
- runtime databases, authority/provider caches, imported private datasets, logs, fingerprints, or scan results from a private collection;
- proprietary or private metadata copied from user systems.

Tests must use synthetic, generated, public-domain, or explicitly redistributable fixtures. Keep fixtures minimal.

Public repository/project/provider identifiers and public official documentation URLs are acceptable when required to document this repository.

Before adding an external provider adapter, re-check current official provider documentation for access rules, licensing/attribution, rate limits, cache/redistribution conditions and authentication requirements. Do not rely on old chat context or memory for mutable provider terms.

Outgoing provider requests must not contain absolute local paths. Send only the minimum structured lookup fields necessary.

## 4. Development workflow

Work in the currently active wave unless a blocking dependency requires another documented task.

For each coherent change:

1. identify the backlog item(s) being implemented;
2. confirm the relevant ADRs and safety/privacy invariants;
3. implement the smallest complete vertical slice;
4. add or update tests for behavior owned by FolioTone;
5. run targeted tests first, then the repository quality checks;
6. update `BACKLOG.md` and `PROJECT_STATUS.md` in the same change;
7. update architecture/ADR/provider documentation if behavior or a decision changed;
8. leave the repository in a state where the next task is explicit.

Do not silently invent architecture decisions. If a material choice is needed, add an ADR with status `Proposed` or `Accepted` as appropriate.

Do not implement W5 provider adapters before the W1 provider-independent provenance and entity contracts exist.

## 5. Definition of done

A backlog item is done only when:

- implementation matches the documented contract;
- tests cover the new behavior and important failure modes;
- `ruff check .`, `mypy src/foliotone`, and `pytest` pass, unless a documented environment-specific exception exists;
- public interfaces and data migrations are documented;
- project status/backlog are synchronized with reality;
- no private/runtime data has entered Git;
- no safety/privacy invariant is weakened implicitly;
- derived data has enough version/provenance information to explain when it becomes stale;
- provider-specific behavior remains behind adapters/contracts where applicable.

## 6. Git discipline

- Prefer small coherent commits tied to backlog items/waves.
- Do not force-push shared branches unless explicitly authorized.
- Do not mix unrelated refactoring with feature work.
- Keep `main` in a consistent state.
- Do not claim a test passed unless it was actually executed.
- If environment-specific verification is pending, record it explicitly in `PROJECT_STATUS.md`.

## 7. Architecture boundaries

Allowed dependency direction:

```text
cli -> application/core interfaces
index -> core + persistence interfaces
filename/path parsing -> core candidate contracts
analyzers -> core observation contracts
authority/resolution -> core + observations + provider interfaces
enrichment provider adapters -> core provider contracts
classification -> core + resolved/external assertions
matching -> core + analyzer/index/resolution outputs
review -> core + resolution/matching + persistence interfaces
consolidation -> core + reviewed/planned decisions
calibre/external adapters -> core interfaces
persistence -> core persistence contracts
```

Avoid importing CLI, Docker, Calibre, Open Library, MusicBrainz, provider HTTP clients, or concrete database concerns into domain logic.

External provider DTO/schema details must terminate at adapter boundaries.

## 8. Safety invariants

Until W10:

- no delete operation;
- no move/rename operation on source media;
- no metadata write to source media;
- no automatic Calibre modification;
- no write-capable source-media mount required by normal operation.

W9 may create `ConsolidationPlan` records, but they must be non-executable.

Any future write operation must revalidate that the source file has not changed since analysis.

No destructive decision may be based solely on a provider result, web research, AI inference, one metadata field, one similarity score or one unreviewed weak signal.

## 9. External enrichment/privacy invariants

Supported conceptual operating modes:

- `OFFLINE`
- `LOCAL_DATASETS`
- `ONLINE_STRUCTURED`
- `ONLINE_WEB_RESEARCH`

Rules:

- network use must be explicit/configurable;
- ordinary rescans must remain useful without internet access;
- prefer local cache/imported bulk data for repeated/high-volume work when provider rules support it;
- never send absolute paths;
- avoid sending raw filenames when structured candidate fields are sufficient;
- do not transmit collection-wide inventories unless explicitly configured and permitted;
- credentials stay outside Git;
- cache/provider results retain source/version/fetch context;
- generic web/AI results create candidates/evidence, not unquestioned canonical truth.

## 10. Performance invariants

The target collection size is large. Design for bounded memory and incremental work.

- Stream hashes and media reads where practical.
- Avoid loading entire large files into memory without a format-specific reason.
- Do not rescan/re-hash unchanged content unnecessarily.
- Candidate generation must reduce the search space before expensive similarity comparisons.
- Persist enough observations to explain why a file was considered unchanged, modified, missing, or moved.
- Cache expensive parsing/fingerprinting/entity-resolution results with versions.
- Avoid repeated online authority/provider lookups for already-resolved entities.
- Evaluate provider bulk/local datasets where officially supported and operationally appropriate.

## 11. Identity/modeling invariants

- `AgentName` equality is not Agent identity proof.
- Names keep original spelling and source even when canonical/sort forms exist.
- Book `Work` and `Edition` are distinct.
- Music `MusicWork`, `Recording`, `ReleaseGroup`, `Release`, and `File` are distinct.
- Classical work hierarchies must not assume one track boundary equals one work boundary.
- Duplicate identity and quality ranking are separate concerns.
- Classification facets are supporting knowledge and normally not sufficient identity proof by themselves.

## 12. How to hand over

Before ending a substantial work session, make `PROJECT_STATUS.md` answer all of these:

- What is implemented now?
- What was verified, and how?
- What remains unverified?
- What is the next backlog item?
- Are there blockers or unresolved decisions?
- Did any ADR change?
- Did provider access/licensing assumptions change?
- Which resolver/parser/provider/matcher versions make stored derived data stale, if applicable?

A future agent should not need the previous conversation to answer those questions.
