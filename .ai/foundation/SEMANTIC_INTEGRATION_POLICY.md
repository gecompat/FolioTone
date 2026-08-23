# Semantic Integration Policy

Status: AUTHORITATIVE

## Purpose

Installing the Foundation into an existing repository is a semantic integration, not a text-replacement exercise. The Foundation adds a reusable baseline while the target repository remains authoritative for project facts, domain rules, architecture, project-selected policies, validation, and implementation.

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
- `FOUNDATION_REQUIRED_CONFLICT`: the target would weaken or contradict a Foundation `REQUIRED` minimum in a way that materially reduces the protected safety, privacy, integrity, evidence, or authorization property. Resolve before completion.
- `TARGET_INTERNAL_CONFLICT`: target-project rules already contradict each other independently of the Foundation. Report it as a target issue; do not mislabel it as a Foundation conflict.
- `ORPHANED_AUTHORITY`: active project governance is not discoverable from the instruction tree. Add discovery without copying the rule.
- `ADAPTER_GOVERNANCE_MISPLACED`: a tool adapter contains substantive governance instead of discovery-only instructions. Preserve the rule by moving or referencing it from an appropriate canonical project source before thinning the adapter.

## Stricter project rules

Foundation `REQUIRED` rules define a minimum protected behavior, not a maximum level of restriction. A project may intentionally be stricter. For example, a project may require synthetic-only test data, additional implementation approval, narrower deployment environments, or more validation than the Foundation baseline.

A stricter project rule is not a conflict merely because it permits fewer actions. It becomes a conflict only when the combined rules are logically incompatible or the target weakens a protected Foundation minimum.

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

## Completion

Semantic integration is complete only when:

- selected Foundation rules/provenance are installed or intentionally merged;
- active project governance remains intact and discoverable;
- meaningful overlaps have a compatible classification or a resolved conflict;
- unique adapter governance has not been lost;
- project-specific validation/model/privacy/license contracts remain preserved;
- `FOUNDATION_INTEGRITY` validation is separated from target `PROJECT_SEMANTIC` and `RUNTIME_EMPIRICAL` validation.
