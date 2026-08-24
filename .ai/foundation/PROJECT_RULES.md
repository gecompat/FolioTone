# Project Rules

Status: AUTHORITATIVE

## Rule classes

- `REQUIRED`: a minimum safety, privacy, integrity, evidence, authorization, identity, or registration floor that may not be silently weakened. A target project may be stricter.
- `DEFAULT`: applies unless an intentional compatible project override is documented.
- `PROJECT_SELECTABLE`: chosen by the target project.

Existing target rules do not need to adopt these labels. During integration, classify their semantics under `SEMANTIC_INTEGRATION_POLICY.md` instead of rewriting project governance merely for terminology consistency.

## Required

- Classify information by handling requirements; being real is not by itself a stop condition.
- Stop only when classification/handling authority is unresolved or a planned transfer crosses the permitted boundary.
- Never version secrets or private local runtime state.
- Preserve truthful project status and validation evidence.
- A concrete task authorizes ordinary, expected, proportionate operations inside its authorization envelope; do not create redundant confirmation gates.
- Require exact authority for destructive or irreversible work when it is not already explicit in the current task and target.
- Stop on unclear or incompatible third-party rights when incorporation or distribution would create material risk.
- Tool adapters perform discovery/import only and must not define parallel governance. Preserve and rehome unique existing adapter governance before thinning an adapter.
- Preserve active project-specific governance and make it discoverable from the root repository instruction tree.
- Preserve published durable identifiers and historical references; never silently reuse, rename, or reinterpret them for a different artifact.
- Keep canonical identity independent of mutable status, owner, hierarchy, phase, location, or tool assignment; existing references that historically encode such values remain valid and need not be renamed.
- Treat identifiers as references, never as authorization credentials.
- For each overlapping final human-reference scope, use one project-defined Registration Authority. Humans and AI systems use the same authority; neither may independently guess or allocate the next final sequence.
- Use `DIRECT` allocation only through serialized or equivalently unique authority behavior. When concurrent/offline creation cannot safely allocate a final sequence, use `DEFERRED` or the project's equivalent safe mechanism.

A project rule that is deliberately stricter than a Foundation minimum is compatible unless it creates a real logical conflict. Extra approvals, narrower data use, additional validation, or reduced autonomous authority are not Foundation conflicts by themselves.

## Defaults

- Use `branch_and_pr` for AI-assisted Git changes unless the project selects another workflow.
- Prefer local, deterministic, impact-based work and validation.
- Keep changes small, coherent, and free of unrelated cleanup.
- Use synthetic or explicitly redistributable data for examples and tests when real data is not necessary.
- Public primary sources and other project-authorized real information may be used normally within their permitted handling boundary.
- Document durable material decisions with stable IDs.
- For a project without an established durable identifier convention, use the layered identity default in `PERSISTENT_IDENTITY_POLICY.md`: opaque persistent machine UID, flat typed project-local human reference, explicit aliases/relations, and separate revision identity.
- For a new project using sequential human references, establish a Registration Authority before publishing those references; the Foundation reference registry profile is a default option, not a required storage technology.
- Do not automatically upgrade Foundation rules, replace a project allocator, install optional reference clients, or overwrite local changes.

## Project-selectable

- target-project license and contribution policy;
- merge strategy and Git workflow;
- AI commit attribution;
- adapters and optional capabilities;
- decision-authority matrix and approval thresholds;
- allowed data classifications and destinations;
- language, platform, concrete validation commands, release process, environments, and budgets;
- richer project-specific validation statuses and model-routing taxonomy, provided Foundation reserved meanings remain intact or are mapped explicitly;
- identifier adoption mode for an existing repository: `PRESERVE`, `ADOPT_FORWARD`, or explicitly planned `MIGRATE_EXPLICIT`;
- compatible project-specific identifier prefixes, human-reference syntax, UUID profile, relation vocabulary, and storage representation, provided the required identity invariants remain intact;
- Registration Authority implementation: issue tracker, database/service, project script/module, Foundation reference registry, GUI/IDE, or another compatible mechanism;
- client implementation language. Python is not required; PowerShell is a first-class supported Foundation reference client and other languages are compatible when they implement the same contract.
