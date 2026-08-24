# Artifact Registration and Allocation Policy

Status: AUTHORITATIVE

## Purpose

This policy defines how humans, AI systems, scripts, services, issue trackers, and other clients create and register durable artifacts without depending on one programming language or vendor. It operationalizes `PERSISTENT_IDENTITY_POLICY.md`.

The registration contract is normative. Python, PowerShell, a GUI, an IDE extension, a REST service, Jira, GitHub Issues, Azure DevOps, Linear, or a project-specific tool may implement the contract. No implementation language is part of the Foundation identity semantics.

## Core rule

A project or identifier scope has one **Registration Authority** for final project-local human-reference allocation.

The Registration Authority is a logical role, not a specific executable. Humans and AI systems MUST use the same authority for the same identifier scope. A client MUST NOT invent the next sequence independently when a Registration Authority exists.

A project may use multiple authorities only for explicitly disjoint namespaces/scopes whose collision rules are documented.

## Rule classes

### REQUIRED

- Persistent artifact UIDs follow the active persistent-identity contract and are never reused.
- Published human references are stable and are never reused for another artifact.
- Humans and AI systems use the same Registration Authority for a given scope.
- The authority, allocation mode, prefix registry, and collision behavior are discoverable from project-owned governance or machine-readable configuration.
- Final human references are allocated by the authority, not guessed by scanning Markdown, filenames, Git history, chat history, or a model's memory.
- Concurrent creation MUST NOT allow two logical artifacts to receive the same final human reference.
- A failed or partially completed allocation may leave a reserved gap; safety and non-reuse take precedence over gap-free numbering.
- Registration never confers authorization to modify, approve, execute, or delete the artifact.

### DEFAULT

For a new project using the Foundation profile:

- machine UID: RFC 9562 UUIDv7 represented as `urn:uuid:<uuid>`;
- final human reference: `<PREFIX>-<SEQUENCE>`;
- final sequence width: at least four digits for display, expanding without truncation;
- authority profile: project-local registry with monotonically increasing registry revision;
- direct allocation: serialized;
- concurrent/offline creation: `DEFERRED` until a serialized registration point.

### PROJECT_SELECTABLE

A project may instead use an existing issue tracker, database sequence, internal service, PowerShell module, Python tool, .NET application, shell tool, or other allocator when it satisfies the required invariants. Existing repositories should preserve a mature compatible authority rather than replacing it merely to match Foundation tooling.

## Registration states

The Foundation distinguishes logical identity from registration state.

### Unregistered durable artifact

An artifact may exist with a permanent machine UID but without a final human reference:

```json
{
  "artifact_uid": "urn:uuid:...",
  "human_ref": null,
  "registration_state": "DRAFT"
}
```

The UID is already final. `DRAFT` does not mean disposable identity.

### Registered artifact

After final allocation:

```json
{
  "artifact_uid": "urn:uuid:...",
  "human_ref": "WI-0048",
  "registration_state": "REGISTERED"
}
```

The published human reference is now reserved permanently for that logical artifact.

## Allocation modes

### `DIRECT`

`DIRECT` allocates the machine UID and final human reference during the same registration operation.

Use `DIRECT` only when the Registration Authority serializes allocation or otherwise provides equivalent atomic uniqueness. Examples include a central database/issue tracker, a single-writer local workflow, or a registry transaction protected by an exclusive lock and revision check.

A client that cannot establish safe serialized allocation MUST NOT emulate `DIRECT` by reading the highest visible number and incrementing it.

### `DEFERRED`

`DEFERRED` creates the durable machine UID immediately while leaving `human_ref` unset. It is the safe default for concurrent branches, offline work, forks, or multiple humans/AI agents when no central allocator is available at creation time.

The final human reference is allocated later by `register` at a serialized integration point. Temporary display labels may be used by a client, but they are not stable references unless the project explicitly publishes them as aliases.

## Language-neutral operations

An implementation may expose different commands or UI, but it maps to these semantic operations:

- `create` — create a durable artifact, using `DIRECT` or `DEFERRED`;
- `register` — allocate the final human reference for an existing UID;
- `resolve` — resolve a stable human reference or alias to the machine UID;
- `add_alias` — add a durable historical/project alias without changing identity;
- `add_relation` — add an explicit relationship without encoding hierarchy in the ID;
- `retire` — mark an artifact inactive while preserving all identifiers;
- `supersede` — link a replacement artifact while retaining both identities;
- `validate` — verify registry and artifact invariants.

Projects may expose richer operations, but these meanings must not be silently redefined when interoperating with Foundation tooling.

## Registration Authority contract

A Registration Authority MUST provide or preserve equivalent semantics for:

1. uniqueness of final human references within its declared scope;
2. stable mapping from each allocated final human reference to exactly one artifact UID;
3. non-reuse of retired or abandoned allocations;
4. explicit prefix-to-kind meaning;
5. deterministic formatting of the final human reference;
6. collision detection;
7. durable history sufficient to resolve published references;
8. concurrency control appropriate to the selected allocation mode;
9. recovery behavior after partial failure.

A project may keep these semantics in an issue tracker or database instead of a JSON file.

## Registry revision and optimistic concurrency

The Foundation reference registry profile contains a monotonically increasing `registry_revision`.

A read-modify-write client SHOULD provide the revision it observed. An authority receiving a stale expected revision MUST reject the mutation rather than silently allocating from stale state.

An exclusive lock alone protects cooperating local clients on one shared filesystem. A revision check additionally detects stale callers and is required when the authority supports detached read/modify/write workflows.

Neither mechanism makes a local JSON file a distributed database. Projects needing multi-host or network-concurrent registration should use an appropriate central authority.

## Prefix allocation

The prefix registry binds broad stable kinds to human-reference prefixes, for example:

```json
{
  "WI": {
    "kind": "work_item",
    "next_sequence": 49,
    "width": 4
  }
}
```

Rules:

- prefix meaning is stable after publication;
- `next_sequence` is allocation state, not priority or execution order;
- gaps are valid;
- sequence width is presentation only and expands when necessary;
- clients must not infer the next sequence from visible artifact files when the authority provides allocation state;
- changing current parent, phase, wave, status, owner, date, or repository does not change the human reference.

## Reference registry profile

The Foundation ships JSON Schemas for an interoperable reference profile:

- `artifact-record.schema.json` — one logical artifact record;
- `artifact-registry.schema.json` — prefix/allocation authority state;
- `artifact-registration-request.schema.json` — language-neutral mutation request envelope.

These schemas define a portable Foundation reference profile. A compatible project authority may use a different internal representation if it preserves equivalent semantics and exposes enough mapping for AI/human continuation.

## Reference clients

The Foundation may ship optional reference clients. They are examples and convenience tooling, not normative runtimes.

The official Python and PowerShell reference clients MUST implement the same contract fixtures and produce semantically equivalent records for the same deterministic inputs.

A target repository may select neither client, one client, or both. A project-specific client takes precedence when it is the documented Registration Authority.

### Python

Python is a convenient portable client for AI-assisted automation and many development environments. It is not required by the Foundation registration contract.

### PowerShell

PowerShell is a first-class reference client for Windows, SQL Server, infrastructure, administration, and human-operated repositories. It is not a translation layer around Python and must remain contract-equivalent independently.

## Existing repositories

During Foundation integration:

1. discover whether the target already has an identifier allocator/issue tracker/registry;
2. preserve it if it satisfies the required identity invariants;
3. document it as the Registration Authority when needed for AI discovery;
4. do not install or activate Foundation reference clients merely because they exist;
5. if the project adopts the Foundation human-reference profile prospectively, choose the authority and allocation mode explicitly;
6. historical references remain governed by `PRESERVE`, `ADOPT_FORWARD`, or `MIGRATE_EXPLICIT` from `PERSISTENT_IDENTITY_POLICY.md`.

Foundation installation MUST NOT silently replace an existing project allocator.

## AI behavior

Before creating a durable project artifact, an AI MUST determine the project's Registration Authority for that scope.

- If an authority exists and is callable, use it.
- If an authority exists but is not callable, do not invent a final sequence; create only what the project permits or report the registration step as pending.
- If the project explicitly uses `DEFERRED`, mint the permanent UID and leave the final human reference unallocated.
- If no authority exists in a new Foundation-default project, the project should establish one before publishing final sequence references.
- Do not assume Python is preferred merely because the actor is an AI.

## Human behavior

A human should be able to create an artifact through the same authority using a client natural to the environment: PowerShell, a CLI, a GUI, an issue form, an IDE action, or another project-selected interface.

The human is not expected to calculate UUID bits, inspect the highest sequence, edit allocator counters manually, or understand concurrency internals for ordinary creation.

## Failure and recovery

Registration favors durable traceability over compact numbering.

- If a human reference is allocated but artifact persistence fails, keep the allocation reserved and recover/reconcile by UID; do not recycle the number.
- If an artifact UID is created in `DEFERRED` mode and later abandoned, keep the UID non-reusable.
- If a registry lock becomes stale, removal is an operational recovery action and must not alter allocation history.
- If two external systems already allocated colliding local references, preserve both machine identities and disambiguate with namespace/alias mapping rather than collapsing them.

## Validation expectations

`FOUNDATION_INTEGRITY` validates that the transferred registration policy and schemas are internally consistent and that selected Foundation reference clients match the declared transfer contract.

`PROJECT_SEMANTIC` should validate, when applicable:

- exactly one authority per overlapping allocation scope;
- documented mapping from kinds to prefixes;
- no duplicate active final human references;
- no reuse of retired references;
- valid aliases and relation targets;
- project-selected client/authority behavior consistent with local governance.

`RUNTIME_EMPIRICAL` should test actual concurrent allocation, issue-tracker/service integration, filesystem locking, database constraints, or recovery behavior where those mechanisms are relied upon.

## Security and privacy

Registration identifiers are not authorization tokens. Registry files and request envelopes must not contain secrets merely because they are machine-readable.

UUIDv7 privacy considerations from `PERSISTENT_IDENTITY_POLICY.md` continue to apply. Projects may select UUIDv4 when creation chronology is sensitive.
