# AGENTS.md — FolioTone working contract

This file is the primary, vendor-neutral continuation contract for AI coding
agents and human contributors. Repository state must be sufficient to continue
the project without access to previous chat history. Tool-specific instruction
files are discovery adapters only and may not redefine this contract.

## 0. Binding documentation governance

Before creating or substantially revising documentation prose, read and follow:

- `docs/quality/DOCUMENTATION_STYLE.md`;
- `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`;
- `docs/reference/GLOSSARY.md` for canonical domain terminology.

The canonical explanatory project documentation is generally German. Established technical terms, public literals, code identifiers, CLI commands, provider/tool IDs, schema names and other technical contracts remain in their canonical form when translation would reduce precision.

A technical change does not authorize an unrelated editorial rewrite. Documentation changes stay scoped to the subject being changed unless the user explicitly requests a broader review.

The bilingual license notice at the beginning of the root `README.md` is protected content. Before every root README edit, read the current block from the target branch. Preserve its wording, headings, lists, links, separators, emphasis, punctuation and blank lines exactly unless the user explicitly asks to change the license block itself.

`LICENSE.md` is a legal special case: according to its own terms, the English version is the legally binding master version.

## 1. Read before changing anything

Read these files in order:

1. `docs/planning/PROJECT_STATUS.md`
2. `docs/planning/HANDOVER.md`
3. `docs/planning/IMPLEMENTATION_PLAN.md`
4. `docs/planning/BACKLOG.md`
5. `docs/planning/AI_WORKFLOW.md` before starting or handing over a wave
6. `docs/planning/MODEL_ROUTING_POLICY.md` before selecting a model or delegating work
7. `docs/quality/TEST_POLICY.md` before selecting local or CI checks
8. `docs/quality/COST_EFFICIENT_DEVELOPMENT.md` before planning tests, CI or agent work
9. `docs/planning/AI_TOOL_ADAPTERS.md` when tool-specific discovery or configuration is touched
10. `docs/quality/DOCUMENTATION_STYLE.md` when documentation prose is touched
11. `docs/quality/LANGUAGE_AND_TERMINOLOGY.md` when documentation prose or terminology is touched
12. `docs/reference/GLOSSARY.md` when domain terminology is touched
13. `docs/architecture/OVERVIEW.md`
14. `docs/architecture/DOMAIN_MODEL.md`
15. `docs/architecture/AUTHORITY_ENRICHMENT_AND_CLASSIFICATION.md`
16. `docs/reference/EXTERNAL_TOOLS.md` when work touches media analysis/tool orchestration
17. `docs/reference/EXTERNAL_DATA_SOURCES.md` when work touches external knowledge/providers
18. relevant files under `docs/architecture/` and `docs/decisions/`

If repository code and documentation disagree, treat the discrepancy as a defect. Determine the actual state, then update code and documentation together.

## 2. Authoritative project constraints

- Language: Python.
- Primary runtime: Docker/Linux.
- Persistence: host-persistent data mounted at `/data`; SQLite initially.
- Media roots: read-only mounts under `/media` for normal operations. The
  narrowly authorized ADR-0056 interim quarantine is the only W10 exception.
- Current product mode: analysis only, except for the narrowly authorized
  ADR-0056 W10 interim quarantine.
- Current product surface: CLI only; no web API, desktop UI or dashboard is in the active scope.
- **Orchestration first:** before implementing substantial specialist media functionality, evaluate maintained tools with stable documented automation interfaces.
- External specialist tools are replaceable `ToolProvider` integrations; their schemas/commands do not define the core model.
- External tool results are provenance-preserving observations/evidence, never unquestioned canonical truth.
- Calibre: external adapter/tool source, never the internal domain model or primary database.
- E-book and music processing: separate analyzers/orchestrators over shared core/index/tooling infrastructure.
- Filename/path parsing produces candidates with provenance; it does not set canonical metadata directly.
- Authority/Entity Resolution is a separate stage before duplicate Matching.
- Raw/observed values are never destroyed by normalization or external enrichment.
- Provenance/value states must preserve `OBSERVED`, `DERIVED`, `EXTERNAL`, `CANONICAL` and `USER_CONFIRMED` distinctions.
- Contributors are modeled as Agent identities plus typed roles/credits rather than plain author/artist/composer strings.
- MusicWork, Recording, ReleaseGroup and Release are distinct identity levels.
- Classification is multidimensional and provenance-preserving, not a single flat genre field.
- External knowledge providers are behind adapters; network use is explicit, cached and privacy-bounded.
- Matching: candidate generation first, then scoring; never global all-vs-all comparison.
- Resolution/matching decisions preserve evidence, score/confidence, rule/resolver/matcher/provider/tool versions, and review state.
- Consolidation execution: W9 remains non-executable. ADR-0056 permits only
  the narrowly authorized W10 interim quarantine described there; all other
  consolidation execution remains prohibited until its own accepted decision.

## 3. Privacy and repository hygiene

Never commit:

- real personal media files or extracted content from a real collection;
- real private filesystem paths, usernames, hostnames, secrets, credentials, tokens, or `.env` files;
- runtime databases, authority/provider caches, external-tool reports from a private collection, logs, fingerprints, or scan results from a private collection;
- proprietary or private metadata copied from user systems.

Tests must use synthetic, generated, public-domain, or explicitly redistributable fixtures. Keep fixtures minimal.

Public repository/project/provider/tool identifiers and public official documentation URLs are acceptable when required to document this repository.

Before adding an external knowledge provider adapter, re-check current official provider documentation for access rules, licensing/attribution, rate limits, cache/redistribution conditions and authentication requirements. Do not rely on old chat context or memory for mutable provider terms.

Before adding a ToolProvider adapter, re-check the current official tool documentation for maintenance state, license, automation interface, output formats, version behavior, container/image source where relevant, and read/write/security implications.

Outgoing provider requests must not contain absolute local paths. Send only the minimum structured lookup fields necessary.

## 4. Development workflow

Work in the currently active wave unless a blocking dependency requires
another documented task. Wave definition, isolation, review, Git completion
and handover follow `docs/planning/AI_WORKFLOW.md`.

Select the vendor-neutral tier `LOCAL`, `ECONOMICAL`, `BALANCED` or `FRONTIER`
for each individual step according to `docs/planning/MODEL_ROUTING_POLICY.md`.
Concrete model names, prices and reasoning controls are runtime adapter
details. A wave-specific plan may impose a stricter tier or stop condition,
but it may not weaken the repository-wide risk classification.

For each coherent change:

1. identify the backlog item(s) being implemented;
2. confirm the relevant ADRs and safety/privacy invariants;
3. for specialist media functionality, check `EXTERNAL_TOOLS.md` and evaluate reuse before native implementation;
4. implement the smallest complete vertical slice;
5. add or update tests for behavior owned by FolioTone;
6. run targeted tests first, then the repository quality checks;
7. update `BACKLOG.md` and `PROJECT_STATUS.md` in the same change;
8. update architecture/ADR/provider/tool documentation if behavior or a decision changed;
9. leave the repository in a state where the next task is explicit.

Testauswahl und vollständige Gates folgen `docs/quality/TEST_POLICY.md`.
Lokale Logauswertung und Agentenkoordination folgen zusätzlich
`docs/quality/COST_EFFICIENT_DEVELOPMENT.md`. Vollständige Logs werden lokal
aggregiert; nur neue Fehlersignaturen und entscheidungsrelevante Ausschnitte
gelangen in den Modellkontext. Pro konsistenter Welle wird genau ein
vollständiger PR-CI-Gate ausgeführt.

Do not silently invent architecture decisions. If a material choice is needed, add an ADR with status `Proposed` or `Accepted` as appropriate.

Do not implement W5 knowledge-provider adapters before the W1 provider-independent provenance and entity contracts exist.

Do not implement media-specific functionality in W3/W4 without first documenting why existing candidate tools are reused or rejected for that capability.

## 5. Definition of done

A backlog item is done only when:

- implementation matches the documented contract;
- tests cover the new behavior and important failure modes;
- die nach `docs/quality/TEST_POLICY.md` erforderlichen lokalen Checks sind
  erfolgreich, und der vollständige PR-CI-Gate ist für den exakten stabilen
  Head grün, sofern keine dokumentierte umgebungsspezifische Ausnahme gilt;
- public interfaces and data migrations are documented;
- project status/backlog are synchronized with reality;
- no private/runtime data has entered Git;
- no safety/privacy invariant is weakened implicitly;
- derived data has enough version/provenance information to explain when it becomes stale;
- provider/tool-specific behavior remains behind adapters/contracts where applicable;
- ToolProvider-derived evidence records enough tool/adapter/parser version context to be reproducible or selectively invalidated;
- external write-capable tool operations remain inaccessible through W9;
- changed documentation follows `docs/quality/DOCUMENTATION_STYLE.md` and `docs/quality/LANGUAGE_AND_TERMINOLOGY.md`;
- the protected root README license block remains byte-for-byte equivalent to the task-start target-branch version unless the user explicitly requested its modification.

## 6. Git discipline

- Prefer small coherent commits tied to backlog items/waves.
- Use a feature branch and pull request for every `main` change; do not push
  directly to `main`.
- Do not force-push shared branches unless explicitly authorized.
- Do not mix unrelated refactoring with feature work.
- Keep `main` in a consistent state.
- Do not claim a test passed unless it was actually executed.
- If environment-specific verification is pending, record it explicitly in `PROJECT_STATUS.md`.

## 6.1 Tool adapters

- Codex and Databricks Genie Code consume this root `AGENTS.md` directly.
- GitHub/Visual Studio Copilot uses `.github/copilot-instructions.md` as a
  thin discovery adapter.
- JetBrains Junie uses `.junie/AGENTS.md` as a thin discovery adapter; do not
  introduce the legacy `.junie/guidelines.md` format.
- Databricks Genie Agents/Spaces are analytics agents configured in
  Databricks and are not repository coding-agent adapters.
- Adapter files may add discovery syntax or stricter local runtime limits, but
  they may not duplicate or weaken architecture, test, Safety, Privacy, W10,
  model-tier or Git contracts.

## 7. Architecture boundaries

Allowed dependency direction:

```text
cli -> application/core interfaces
index -> core + persistence interfaces
filename/path parsing -> core candidate contracts
tooling -> core tool/evidence contracts + adapter interfaces
analyzers -> core observation contracts + tooling interfaces
authority/resolution -> core + observations + provider interfaces
external knowledge provider adapters -> core provider contracts
classification -> core + resolved/external/tool assertions
matching -> core + analyzer/index/resolution/tool outputs
review -> core + resolution/matching + persistence interfaces
consolidation -> core + reviewed/planned decisions
calibre/external tool adapters -> core/tooling interfaces
persistence -> core persistence contracts
```

Avoid importing CLI, Docker, Calibre, beets, SongKong, Picard, FFmpeg, Open Library, MusicBrainz HTTP clients, or concrete database concerns into domain logic.

External provider/tool DTO/schema/command details must terminate at adapter boundaries.

## 8. ToolProvider invariants

- Prefer documented CLI/API/service/container interfaces; do not reverse-engineer GUI/web endpoints when a stable interface is absent.
- Prefer machine-readable output such as JSON when available.
- Record tool identity/version and adapter/parser version for material results.
- Treat optional/commercial tools as optional unless an explicit architecture decision changes that.
- Tool absence/failure must not corrupt existing FolioTone state.
- External Docker images are dependencies, not FolioTone-owned code.
- Do not redistribute third-party binaries/images unless the current license permits the intended model.
- Use bounded execution, timeouts/cancellation, clear exit/error handling and isolated writable work areas.

## 9. Safety invariants

Until W10:

- no delete operation;
- no move/rename operation on source media;
- no metadata write to source media;
- no automatic Calibre modification;
- no external-tool delete/move/rename/retag operation;
- no write-capable source-media mount required by normal operation.

Within W10, ADR-0056 permits only its narrowly authorized one-file interim
quarantine. It uses same-filesystem `os.rename`, a non-atomic target-absence
check and full SHA-256 revalidation; it neither promises atomic no-replace nor
authorizes copy/delete, rollback, purge, metadata writes or directory cleanup.
`FG-W10-MOVE-BACKEND` remains the mandatory Frontier hardening for those
filesystem guarantees.

W9 may create `ConsolidationPlan` records, but they must be non-executable.

Any future write operation must revalidate that the source file has not changed since analysis.

No destructive decision may be based solely on a provider result, ToolProvider result, web research, AI inference, one metadata field, one similarity score or one unreviewed weak signal.

## 10. External enrichment/privacy invariants

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

## 11. Performance invariants

The target collection size is large. Design for bounded memory and incremental work.

- Stream hashes and media reads where practical.
- Avoid loading entire large files into memory without a format-specific reason.
- Do not rescan/re-hash unchanged content unnecessarily.
- Do not rerun expensive ToolProvider analysis when relevant input identity + tool/adapter/config versions are unchanged.
- Candidate generation must reduce the search space before expensive similarity comparisons.
- Persist enough observations to explain why a file was considered unchanged, modified, missing, or moved.
- Cache expensive parsing/fingerprinting/entity-resolution results with versions.
- Avoid repeated online authority/provider lookups for already-resolved entities.
- Evaluate provider bulk/local datasets where officially supported and operationally appropriate.

## 12. Identity/modeling invariants

- `AgentName` equality is not Agent identity proof.
- Names keep original spelling and source even when canonical/sort forms exist.
- Book `Work` and `Edition` are distinct.
- Music `MusicWork`, `Recording`, `ReleaseGroup`, `Release`, and `File` are distinct.
- Classical work hierarchies must not assume one track boundary equals one work boundary.
- Duplicate identity and quality ranking are separate concerns.
- Classification facets are supporting knowledge and normally not sufficient identity proof by themselves.

## 13. How to hand over

Before ending a substantial work session, make `PROJECT_STATUS.md` answer all of these:

- What is implemented now?
- What was verified, and how?
- What remains unverified?
- What is the next backlog item?
- Are there blockers or unresolved decisions?
- Did any ADR change?
- Did provider/tool access/licensing assumptions change?
- Which tool/adapter/resolver/parser/provider/matcher versions make stored derived data stale, if applicable?

A future agent should not need the previous conversation to answer those questions.
