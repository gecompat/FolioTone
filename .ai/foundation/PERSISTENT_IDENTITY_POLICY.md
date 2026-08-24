# Persistent Identity and Reference Policy

Status: AUTHORITATIVE

## Purpose

This policy defines a project-independent identity model for durable planning, governance, engineering, quality, operational, research, and knowledge artifacts. It separates persistent identity from human-readable references, mutable classification, location, hierarchy, revision, and external-tool identifiers.

The goal is long-lived traceability across repository renames, refactoring, planning changes, multiple AI systems, branches, forks, repository splits/merges, issue-tracker migration, and offline or concurrent work.

The Foundation does not require an existing repository to rename historical identifiers merely to adopt this policy.

## Rule classes

This policy contains three classes of behavior:

- `REQUIRED`: identity invariants that protect traceability and may not be silently weakened.
- `DEFAULT`: the Foundation profile for new projects or projects that explicitly adopt it.
- `PROJECT_SELECTABLE`: choices that a project may make explicitly, including retaining an established identifier system.

Existing project terminology does not need to be rewritten to these labels.

## Core model

Treat these concepts as distinct:

1. **Persistent machine identity** — an opaque identity intended to remain stable for the lifetime of the logical artifact.
2. **Human reference** — a concise project-local reference used in discussion, Markdown, commits, pull requests, plans, and UI.
3. **Aliases and external references** — historical names or identifiers assigned by other systems.
4. **Relations and classification** — hierarchy, dependencies, type, status, owner, phase, wave, milestone, domain, and other mutable structure.
5. **Revision identity** — identity of a particular immutable version, snapshot, content instance, or evidence record.
6. **Locator** — current repository path, URL, issue-tracker location, database row locator, or other resolvable address.

A single string may be convenient for presentation, but these concepts must not be treated as equivalent when doing so would make identity unstable.

## Required invariants

### Stable identity and no reuse

- Once an identifier has been published as the identity or stable reference of an artifact, do not silently reassign it to a different artifact.
- Retired, rejected, superseded, deleted, or archived identifiers remain reserved.
- Renaming a title, moving a file, changing status, changing owner, changing phase, or changing hierarchy must not require changing the canonical identity of the same logical artifact.
- Do not silently reinterpret an existing prefix or identifier so that historical references acquire a different meaning.

### Existing-project preservation

When integrating the Foundation into an existing repository:

- detect established planning, decision, requirement, risk, test, incident, release, and operational identifier conventions before introducing a new convention;
- preserve existing identifiers and their historical references;
- do not bulk-rename or invalidate them merely for Foundation consistency;
- do not infer that an existing hierarchical identifier may be rewritten because its current hierarchy has changed;
- if no explicit adoption decision is available, use `PRESERVE`.

A Foundation upgrade must not create an identifier migration as a side effect.

### Identity is not mutable classification

Status, priority, owner, date, phase, wave, milestone, team, repository path, current parent, and current tool/provider are metadata, not canonical identity.

A project-specific human reference may historically contain such information. When it does, preserve the reference but do not require future renaming to keep the encoded information current.

### Explicit relations

Parent/child, dependency, implementation, verification, blocking, supersession, derivation, and related-artifact semantics should be represented as explicit relations rather than being inferred only from identifier syntax.

A human reference such as `S-FUT11-04` may remain useful, but consumers must not assume that parsing `FUT11` is the only authoritative way to determine the current parent.

### Logical artifact versus revision

A mutable logical artifact and one immutable revision of that artifact are different identity domains.

- Keep the logical artifact identity stable while its content evolves.
- Use Git commits, content digests, immutable snapshot IDs, or equivalent revision identifiers for particular versions when needed.
- Do not use a content hash as the primary identity of a mutable task, requirement, decision, risk, capability, or similar logical artifact unless the project intentionally models every content change as a new logical artifact.

### External systems are not canonical identity by default

GitHub issue numbers, Jira keys, Azure DevOps IDs, filesystem paths, URLs, database row numbers, and similar identifiers are external references or locators unless the project explicitly makes them its authoritative persistent identity system.

If a project migrates tools, preserve mappings from historical external references.

### Identifiers are not authorization

Knowledge or possession of an identifier never grants permission to read, mutate, execute, approve, or delete the identified artifact. Identity and authorization are separate controls.

## Foundation default profile

The default profile applies to new repositories with no established identifier convention and to existing repositories that explicitly select `ADOPT_FORWARD` or `MIGRATE_EXPLICIT` for the relevant artifact scope.

### Persistent machine UID

Use an RFC 9562 UUID as the opaque machine identity and represent it, when a text/URI form is useful, as a UUID URN:

```text
urn:uuid:<uuid>
```

Foundation default: UUIDv7.

Compatible project choices include UUIDv4 when creation-time disclosure, compatibility, or implementation simplicity makes it preferable. Consumers must treat all UUID values as opaque; ordering or timestamp information must not become domain semantics.

A UUID may be minted without a central project-wide sequence allocator, which makes it suitable for branches, offline work, concurrent humans, and multiple AI agents.

### Human reference

Use a flat, typed, project-local reference:

```text
<PREFIX>-<SEQUENCE>
```

Examples:

```text
CAP-0011
REQ-0042
WI-0473
DEC-0067
GATE-0032
RISK-0014
EXP-0008
OPS-0021
INC-0104
REL-0012
TEST-0087
```

The human reference is stable after publication but is not the deepest technical identity. The sequence:

- is an allocation token, not priority or execution order;
- may contain gaps;
- does not encode current parent, phase, owner, status, date, or repository location;
- may be assigned at integration/merge time when concurrent work makes immediate sequence allocation unsafe.

A newly created artifact may temporarily have only its machine UID until the project-local human reference is allocated.

### Default prefix registry

The Foundation default registry intentionally uses broad, comparatively stable kinds:

| Prefix | Meaning |
|---|---|
| `CAP` | Capability or durable outcome |
| `REQ` | Requirement or durable constraint |
| `WI` | Work item; subtype such as feature, task, bug, spike, or story is metadata |
| `DEC` | Durable decision record; a project may use `ADR` or another established equivalent |
| `GATE` | Decision, safety, readiness, or release gate |
| `RISK` | Risk record |
| `EXP` | Experiment or spike with an evidence-producing question |
| `OPS` | Operational work or operational control |
| `INC` | Incident record |
| `REL` | Release record |
| `TEST` | Durable test contract/case when it needs independent identity |

Projects may define additional prefixes. Once a prefix meaning has been published, do not reuse that prefix for a materially different kind.

Prefer a smaller set of stable kinds plus metadata over many volatile subtype prefixes.

## Recommended artifact representation

The Foundation does not require one serialization format. A structured representation may contain:

```yaml
artifact_uid: urn:uuid:0190f5f6-7f4d-7b7e-8b3e-5e1ef5b5c2c1
human_ref: WI-0473
kind: work_item
title: Add local browser interface
status: planned
aliases:
  - S-FUT11-04
external_refs:
  - system: github
    value: owner/repository#312
relations:
  - type: parent
    target: CAP-0011
  - type: governed_by
    target: DEC-0067
revision:
  git_commit: <commit-sha>
```

The example is illustrative, not a required target schema.

## Relation model

Useful project-defined relations include:

- `parent`
- `depends_on`
- `implements`
- `verifies`
- `blocks`
- `governed_by`
- `supersedes`
- `derived_from`
- `related_to`

Projects may extend the vocabulary. Relation semantics must be documented when they affect dependency ordering, validation, authorization, or lifecycle decisions.

Prefer resolving a relation to the persistent machine identity when available. Human references and aliases remain valid lookup keys.

## Aliases and historical references

Aliases preserve identity continuity across historical naming schemes.

- An alias points to exactly one logical artifact within its declared scope.
- Do not delete an old stable reference merely because a preferred human reference was added later.
- If two merged projects contain the same local human reference, keep both identities and disambiguate by project/namespace or assign a new preferred local reference while preserving the original as a scoped alias.
- Alias mappings are durable history, not temporary migration scratch data.

## Project identity

Repository location is not project identity. When cross-repository exchange, federation, long-lived export/import, repository splitting/merging, or independent project lineage matters, mint and persist a `project_uid` using the same opaque persistent-identity principles.

A repository URL, organization name, repository name, or filesystem path is a locator and may change without changing the project identity.

For small projects that never exchange or federate identity, a project UID is recommended but not required by the Foundation minimum floor.

## Fork, template, split, and merge semantics

### Fork

A normal development fork initially represents the same project/artifact lineage. Preserve existing project/artifact UIDs; divergent commits are different revisions, not automatically different logical identities.

### Template or copy as a new independent project

A template-derived independent project mints a new project UID. Project-owned mutable artifacts normally mint new artifact UIDs unless the copied object is intentionally a shared external/normative artifact whose identity is meant to remain common.

### Repository split

Preserve logical artifact UIDs when artifacts move into a new repository. Update locators and repository mappings; do not mint new identities merely because storage boundaries changed.

### Repository merge

Preserve artifact UIDs from all source projects. Resolve project-local human-reference collisions with scoping, aliases, or new preferred references; never collapse two different artifacts solely because their human references match.

## Adoption modes for existing repositories

### `PRESERVE`

Use the established project identifier convention. Foundation integration documents and respects it. No historical ID migration is performed.

This is the default when an existing convention is detected and no explicit decision selects another mode.

### `ADOPT_FORWARD`

Keep all historical identifiers stable. New durable artifacts use the Foundation default profile, or another explicitly selected improved project profile, from a documented adoption point forward.

Historical identifiers remain valid primary references or aliases. Do not retroactively rename them merely for visual consistency.

### `MIGRATE_EXPLICIT`

Perform a controlled migration only after an explicit durable decision. The migration plan must define:

- scope and motivation;
- old-to-new mapping;
- alias retention;
- external references and consumers;
- affected files, links, commits, issues, tests, release notes, APIs, databases, and other repositories;
- collision handling;
- validation and rollback/recovery;
- cutover behavior for concurrent work.

A migration is incomplete if historical references no longer resolve.

## AI integration behavior

When an AI installs or upgrades the Foundation in an existing repository:

1. inventory established identifier forms and their authoritative definitions;
2. determine whether they are stable references, hierarchy/position codes, external-tool keys, or informal labels;
3. preserve them before changing any related governance;
4. assess whether the Foundation default would materially improve stability, distributed allocation, cross-repository portability, or machine resolution;
5. if a choice is needed, present `PRESERVE`, `ADOPT_FORWARD`, and `MIGRATE_EXPLICIT` with a recommendation and trade-off;
6. never select `MIGRATE_EXPLICIT` without explicit authorization;
7. if no choice is available, continue with `PRESERVE`;
8. record the selected mode in project-owned governance when it becomes a durable project decision.

For a new project with no established convention, use the Foundation default unless the project intentionally selects another compatible convention.

## Validation expectations

Foundation validation verifies that this policy and its machine-readable transfer contract are present and internally consistent. It does not prove that an arbitrary target repository has semantically classified every historical identifier correctly.

A target project that adopts structured identity should consider `PROJECT_SEMANTIC` checks for:

- duplicate machine UIDs;
- duplicate active human references in the same scope;
- identifier reuse after retirement;
- conflicting aliases;
- undefined or redefined prefixes;
- broken relation targets;
- invalid migration mappings;
- external-reference collisions where uniqueness is assumed;
- accidental dependence on mutable hierarchy/status encoded in historical references.

Runtime resolution, issue-tracker/API synchronization, database constraints, and migration execution belong to `RUNTIME_EMPIRICAL` validation when applicable.

## Privacy and security considerations

UUIDv7 contains time-ordering information and can reveal approximate creation chronology. A project with a material privacy concern may select UUIDv4 or another documented opaque equivalent.

Do not place secrets, personal data, customer names, hostnames, environment identifiers, or other sensitive values into human-reference prefixes or IDs merely to make them descriptive. Apply the repository's data-classification policy to aliases and external references as well.

Identifiers are not access-control capabilities and must not be relied on as unguessable authorization tokens.

## Standards and design references

This Foundation policy is project governance, not an assertion that the following standards directly standardize project task IDs. It adopts compatible principles from:

- RFC 9562, *Universally Unique IDentifiers (UUIDs)*: https://www.rfc-editor.org/rfc/rfc9562.html
- RFC 8141, *Uniform Resource Names (URNs)*: https://www.rfc-editor.org/rfc/rfc8141.html
- RFC 8720, *Principles for Operation of IANA Registries*: https://www.rfc-editor.org/rfc/rfc8720.html
- ISO 21511, *Work breakdown structures for project and programme management*: https://www.iso.org/standard/69702.html
- SPDX 3.x identifier/namespace model: https://spdx.github.io/spdx-spec/

The WBS concept is useful for planning structure, but WBS position is treated here as classification/relationship rather than canonical identity when the position can change.
