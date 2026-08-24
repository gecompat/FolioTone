# Semantic Integration Policy

Status: AUTHORITATIVE

## Purpose

Installing the Foundation into an existing repository is a semantic integration, not a text-replacement exercise. The Foundation adds a reusable baseline while the target repository remains authoritative for project facts, domain rules, architecture, project-selected policies, validation, implementation, established identifier history, and compatible Registration Authorities.

Existing project rules do not need to be renamed or rewritten into Foundation terminology merely to integrate the Foundation.

## Discovery invariant

Root `AGENTS.md` is the canonical AI discovery entry point after integration.

- Foundation rules must be reachable from root `AGENTS.md` through `.ai/foundation/FOUNDATION_RULESET.md`.
- Active project-specific authoritative governance must be transitively discoverable from root `AGENTS.md`, either by direct links, an existing project router/index, or an explicitly documented scoped-`AGENTS.md` convention.
- Keep discovery concise. Link to canonical project sources; do not duplicate their rule text into the Foundation block.
- Historical, superseded, examples, generated evidence, and other non-authoritative material do not need to be promoted into the active discovery tree.
- `ORPHANED_AUTHORITY` means an active authoritative project rule exists but is not discoverable through the repository instruction/discovery tree. Resolve it before declaring semantic integration complete.

If the target already has a machine-readable repository map, preserve its schema and content. Add a minimal reference to `.ai/foundation/repo_map.yaml` only when the target map's schema safely supports such an extension; otherwise rely on the root discovery path. Never replace a target repo map with the Foundation map.

## Semantic compatibility classes

Classify meaningful overlaps between Foundation and target governance with one of these classes:

- `EQUIVALENT`: the target rule and Foundation rule have materially equivalent semantics. Keep the target's canonical wording; do not create duplicate governance.
- `PROJECT_STRONGER`: the target intentionally imposes a stricter constraint, such as narrower data handling, additional approvals, more validation, or less autonomous authority. This is compatible and should normally be preserved.
- `PROJECT_SELECTABLE_OVERRIDE`: the target intentionally chooses a different value for a Foundation `DEFAULT` or `PROJECT_SELECTABLE` area. Preserve and document the project choice when needed.
- `COMPLEMENTARY`: both rules apply to different aspects and can coexist without duplication.
- `DUPLICATE_GOVERNANCE`: the same active rule is independently maintained in multiple places. Choose a canonical project source and reduce the others to discovery/reference where appropriate.
- `FOUNDATION_REQUIRED_CONFLICT`: the target would weaken or contradict a Foundation `REQUIRED` minimum in a way that materially reduces the protected safety, privacy, integrity, evidence, authorization, identity, or registration property. Resolve before completion.
- `TARGET_INTERNAL_CONFLICT`: target-project rules already contradict each other independently of the Foundation. Report it as a target issue; do not mislabel it as a Foundation conflict.
- `ORPHANED_AUTHORITY`: active project governance is not discoverable from the instruction tree. Add discovery without copying the rule.
- `ADAPTER_GOVERNANCE_MISPLACED`: a tool adapter contains substantive governance instead of discovery-only instructions. Preserve the rule by moving or referencing it from an appropriate canonical project source before thinning the adapter.

## Stricter project rules

Foundation `REQUIRED` rules define a minimum protected behavior, not a maximum level of restriction. A project may intentionally be stricter. For example, a project may require synthetic-only test data, additional implementation approval, narrower deployment environments, or more validation than the Foundation baseline.

A stricter project rule is not a conflict merely because it permits fewer actions. It becomes a conflict only when the combined rules are logically incompatible or the target weakens a protected Foundation minimum.

## Persistent identifier interoperability

Read `PERSISTENT_IDENTITY_POLICY.md` when the target uses durable planning, decision, requirement, risk, test, release, incident, operational, or other cross-referenced identifiers.

Existing identifier history is target-owned governance and traceability. Integration must distinguish three cases:

- no established durable convention: the Foundation default profile applies unless the project selects another compatible profile;
- established convention: default to `PRESERVE` and continue using it unless an explicit project decision selects prospective adoption;
- explicit migration decision: use `MIGRATE_EXPLICIT` with durable old-to-new mappings and validation.

Do not treat a more semantically descriptive Foundation reference as justification to rename historical IDs. If the Foundation default is materially better for new work, recommend `ADOPT_FORWARD`: preserve historical IDs and use the selected new profile prospectively from a documented adoption point.

A missing user/project decision is not permission to migrate. `unknown -> PRESERVE`.

Identifier syntax and current hierarchy are separate concerns. Existing forms such as `W3-017`, `S-FUT11-04`, Jira-style project keys, or project-specific decision IDs may remain valid even when their encoded phase or parent becomes historical. Add explicit metadata/relations instead of rewriting identity merely to make the string reflect current structure.

## Registration Authority interoperability

Read `ARTIFACT_REGISTRATION_POLICY.md` when the target allocates or creates final human references.

An existing issue tracker, database allocator, local registry, project application, PowerShell module, Python tool, or other allocator is project governance when it is the established Registration Authority. Preserve it when compatible.

Integration rules:

- do not install Foundation reference clients merely because the registration policy is transferred;
- do not replace an existing allocator with Python, PowerShell, or a Foundation registry for terminology consistency;
- humans and AI systems must resolve to the same authority for the same identifier scope;
- a project may select a different implementation language without creating a Foundation conflict;
- if multiple existing allocators overlap the same final-reference scope, classify whether the target already has a `TARGET_INTERNAL_CONFLICT`; do not hide it by choosing one silently;
- if the target adopts the Foundation sequential reference profile but lacks a safe allocator, establish the Registration Authority before publishing final sequence references;
- `DIRECT` and `DEFERRED` are semantic allocation modes, not requirements to use the Foundation reference clients.

A richer central issue tracker or service may be preferable to the Foundation local reference registry for multi-user/network-concurrent repositories. That is a compatible project-specific choice.

## Adapter migration

When an existing adapter contains substantive project rules:

1. identify the unique governance content before editing the adapter;
2. preserve that content in an existing canonical project-governance source, or create a project-owned canonical source when the task authorizes it;
3. update project discovery so the relocated rule remains reachable;
4. only then reduce the adapter to a thin discovery bridge;
5. if safe rehoming cannot be determined, keep the existing rule and report `ADAPTER_GOVERNANCE_MISPLACED` rather than deleting it.

## Existing policy interoperability

More detailed target policies remain valid. The Foundation provides stable cross-project semantics, not a requirement to discard richer project policy.

- Existing validation status vocabularies may extend the Foundation's reserved meanings as defined by `VALIDATION_POLICY.md`.
- Existing model/cost policies may remain more detailed and map semantically to the Foundation routing tiers as defined by `MODEL_ROUTING_POLICY.md`.
- Existing privacy scanners may be stricter; legally required Foundation provenance must be handled with the narrow exception described by `DATA_PRIVACY_AND_CONFIDENTIALITY.md`, not by weakening the scanner globally.
- Existing identifier conventions remain valid when they preserve stable meaning and no-reuse. Foundation-default human references and UUIDs are defaults, not retroactive renaming requirements.
- Existing Registration Authorities remain valid when they preserve uniqueness, no-reuse, mapping durability, and safe concurrency for their declared scope.

## Completion

Semantic integration is complete only when:

- selected Foundation core material and any explicitly selected optional capabilities are installed or intentionally merged;
- active project governance remains intact and discoverable;
- meaningful overlaps have a compatible classification or a resolved conflict;
- unique adapter governance has not been lost;
- project-specific validation/model/privacy/license/identifier/registration contracts remain preserved;
- any selected identifier adoption mode is explicit and historical references remain resolvable;
- the Registration Authority is discoverable when final project references are created or allocated;
- optional Foundation reference clients have not displaced a compatible project allocator without an explicit project decision;
- `FOUNDATION_INTEGRITY` validation is separated from target `PROJECT_SEMANTIC` and `RUNTIME_EMPIRICAL` validation.
