# AI Repository Foundation Ruleset

Status: AUTHORITATIVE BASELINE
Ruleset version: 1.4.0

This directory contains reusable governance rules, machine-readable schemas, and the source-license notice required for transferred Foundation material. Optional capability files are installed only when explicitly selected. The ruleset does not describe the Foundation source project and does not define the target project's README, root license, architecture, backlog, status, or release state.

## Rule classes

- `REQUIRED`: minimum protected behavior that may not be silently weakened; a target project may be stricter.
- `DEFAULT`: applies unless an intentional project-specific override exists.
- `PROJECT_SELECTABLE`: selected by the project when relevant.

Existing project rules do not need to be rewritten into these labels. Use semantic integration classes instead.

## Read by scope

- project/baseline rules: `PROJECT_RULES.md`
- semantic integration, compatibility, discovery, and adapter migration: `SEMANTIC_INTEGRATION_POLICY.md`
- persistent artifact identity, human references, aliases, relations, revisions, and legacy-safe adoption: `PERSISTENT_IDENTITY_POLICY.md`
- language-neutral artifact creation, Registration Authority, `DIRECT`/`DEFERRED`, concurrency, and human/AI allocation: `ARTIFACT_REGISTRATION_POLICY.md`
- registration schemas: `schemas/artifact-record.schema.json`, `schemas/artifact-registry.schema.json`, `schemas/artifact-registration-request.schema.json`
- authorization and working behavior: `WORKING_RULES.md`
- model/resource selection and target-policy mapping: `MODEL_ROUTING_POLICY.md`
- validation, status vocabulary, and manual test plans: `VALIDATION_POLICY.md`
- data handling and narrow provenance exceptions: `DATA_PRIVACY_AND_CONFIDENTIALITY.md`
- safe operations: `SECURITY_AND_SAFE_OPERATIONS.md`
- documentation truth: `DOCUMENTATION_POLICY.md`
- third-party/licensing: `THIRD_PARTY_AND_LICENSING.md`
- evidence/sources: `SOURCE_AND_EVIDENCE_POLICY.md`
- dependencies/services: `DEPENDENCY_POLICY.md`
- machine-readable authority, integration, identity, registration, and validation index: `repo_map.yaml`

## Discovery boundary

Foundation rules are discoverable through root `AGENTS.md`. Active target-project governance must also remain transitively discoverable from the root repository instruction tree. Keep project discovery links outside the managed Foundation block and point to canonical project sources rather than copying their rule text.

An active authoritative target rule that is not discoverable is `ORPHANED_AUTHORITY` and is an integration defect even if the Foundation files themselves are present.

## Semantic integration boundary

Foundation integration supplements existing governance. Preserve `PROJECT_STRONGER`, `PROJECT_SELECTABLE_OVERRIDE`, and `COMPLEMENTARY` project behavior. Resolve `FOUNDATION_REQUIRED_CONFLICT`, distinguish `TARGET_INTERNAL_CONFLICT`, and do not remove adapter governance until it has been safely rehomed.

Existing identifier conventions and Registration Authorities are project governance. Preserve them by default when compatible. The Foundation identity default applies automatically only when no established convention exists, or prospectively after an explicit `ADOPT_FORWARD` decision. A historical migration requires `MIGRATE_EXPLICIT`; Foundation installation never performs one implicitly.

## Identity boundary

Persistent identity, human-readable reference, aliases/external references, mutable relations/classification, revision identity, and current locator are distinct concerns. Stable references are never reused for different artifacts. Hierarchy/status/location changes must not force canonical identity changes. Identifiers never grant authorization.

## Registration boundary

Humans and AI systems use the same project-selected Registration Authority for a given identifier scope. Final sequence references are allocated by that authority, not guessed by individual clients. `DIRECT` requires serialized or equivalent uniqueness; `DEFERRED` creates the final machine UID first and allocates the human reference later.

Python is not a required runtime. PowerShell is a first-class supported reference client. The optional `artifact-registration-clients` capability may install both reference clients, but a project-specific compatible allocator takes precedence and does not need to be replaced.

## Validation boundary

Foundation validation supplements rather than replaces the target repository's validation system. The Foundation validator covers `FOUNDATION_INTEGRITY` only. Project-specific semantic correctness remains under `PROJECT_SEMANTIC`; executable/empirical behavior remains under `RUNTIME_EMPIRICAL`. Existing project validators, static contracts, tests, reviews, and manual validation remain authoritative for those scopes when affected.

A local override or drift warning identifies a difference; it is not semantic approval of that difference. A green Foundation validator must never be used as evidence that the entire target project is validated.

## Provenance and license notice

`AI_REPOSITORY_FOUNDATION_NOTICE.md` is not a target-project license. It preserves the MIT notice for the Foundation material copied into this repository. Keep that notice with the installed Foundation rules and any selected Foundation capability files; do not use it to replace or reinterpret the target project's own root license.

Read only the rules relevant to the current task. Repository-specific instructions and facts remain in the target repository; these Foundation files are a reusable baseline, not a replacement for project context.
