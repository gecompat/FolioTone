# Validation Policy

Status: AUTHORITATIVE

## Validation scopes

Validation is layered. The Foundation does not replace the target repository's own validation system.

- `FOUNDATION_INTEGRITY`: installation structure, required Foundation rules/provenance, adapters, deterministic Foundation contracts, and detectable drift.
- `PROJECT_SEMANTIC`: project-specific rules, local overrides, architecture, domain behavior, documentation contracts, data/model invariants, and other repository-specific semantics.
- `RUNTIME_EMPIRICAL`: tests, builds, integrations, runtime behavior, operational checks, research/data verification, and manual validation.

The Foundation validator establishes only `FOUNDATION_INTEGRITY` for an installed Foundation ruleset. It may detect that a local override or drift exists, but it cannot prove that the override is semantically correct for the target project. A green Foundation validator therefore does **not** mean that project-specific validation is green.

Existing target-project validators, static contracts, tests, reviews, and manual validation remain authoritative for their respective scopes. Installing or upgrading the Foundation must not delete, disable, weaken, or silently replace them. Select `PROJECT_SEMANTIC` and `RUNTIME_EMPIRICAL` checks impact-by-impact when the affected contract requires them.

## Validation progression

Use the smallest local, reproducible method that reliably tests the affected contract:

1. reproduction or characterization;
2. focused validation;
3. affected regression or consistency checks;
4. structural/static checks;
5. integration or runtime validation;
6. stable completion gate.

Determine affected artifacts and consumers before selecting checks. Prefer existing tools, synthetic/redistributable fixtures where suitable, mocks, and offline checks. CI confirms a stable result; it is not the primary debugging environment.

Validation applies equally to software, data, research, and documentation: tests, schemas, calculations, links, sources, citations, dates/versions, samples, consistency, reproducibility, and review may all be evidence.

## Evidence

Evidence records contain, as relevant:

- method;
- validation scope (`FOUNDATION_INTEGRITY`, `PROJECT_SEMANTIC`, or `RUNTIME_EMPIRICAL`);
- affected contract;
- environment/platform;
- command or procedure;
- result;
- date;
- limitations.

## Status vocabulary

The following Foundation meanings are reserved and must not be weakened or redefined:

- `not executed`: no required procedure was run.
- `pending manual validation`: an executable manual plan exists but has not been completed.
- `validated`: the stated procedure actually ran and met its pass criteria for the stated scope only.

Target repositories may define additional statuses such as `partially validated`, `failed`, `not applicable`, `inconclusive`, or domain-specific equivalents. Such extensions are compatible when their meanings are documented and they do not cause unexecuted, failed, partial, or inapplicable work to be represented as `validated`.

A project may keep an existing richer status vocabulary; it does not need to replace it with only the three Foundation terms. When reporting across repositories, preserve the exact target status and map to a Foundation reserved meaning only when the semantics genuinely match.

When human execution is required, create an exact step-by-step manual validation plan containing: ID, objective, contract/risk, prerequisites, environment, initial state, ordered steps, exact commands/UI actions, expected results, pass/fail criteria, outputs to return, cleanup/recovery, limitations, and residual risk. A plan is not evidence that the test passed.

A test with external effects, cost, production impact, or mutation may run without an additional confirmation when that effect is an ordinary and clearly authorized part of the current task's authorization envelope. Gate only effects that exceed the envelope, have ambiguous targets, introduce material unapproved cost, or are destructive/irreversible without exact authority.
