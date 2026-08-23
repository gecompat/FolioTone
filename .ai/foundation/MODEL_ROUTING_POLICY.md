# Model and Resource Routing Policy

Status: AUTHORITATIVE

Choose per work step, not per project. Safety, privacy, authorization, correctness, and validation outrank cost.

- `LOCAL`: deterministic local processing; no generative model required.
- `ECONOMICAL`: bounded, low-risk, clearly specified, cheaply verifiable work.
- `BALANCED`: integrates multiple contracts, files, layers, or competing sources; diagnosis is not obvious.
- `FRONTIER`: an unresolved, critical or hard-to-verify decision involving architecture, security, privacy, authorization, data loss, persistence boundaries, or another high-impact conclusion.

Routine work involving an already-defined security, privacy, authorization, or architecture contract does not become `FRONTIER` merely because that domain is involved. Tier selection is based on unresolved risk, complexity, criticality, and verifiability—not human review effort. A stronger model does not replace required human review or approval.

Human review effort is an execution-efficiency factor only after the required capability tier has been established. It may motivate better automation, clearer evidence, or a better model within the same tier; it must not by itself escalate the tier or remove a required review.

## Existing project routing policies

A target repository may already have a more detailed model, provider, quota, cost, or tool-selection policy. Preserve it when it is compatible. Do not replace a mature project policy merely to introduce Foundation tier names.

When Foundation tiers overlap an existing project taxonomy, maintain an explicit semantic mapping where needed:

- each project category used for AI/model selection should map to the closest Foundation capability tier or state that no direct mapping is needed;
- concrete model names, providers, current prices, quotas, and product-specific features remain runtime/project facts, not Foundation contracts;
- a target policy may split one Foundation tier into several project-specific categories;
- a target policy must not use human review effort alone to justify a higher Foundation capability tier;
- after a difficult decision, reassess and downgrade subsequent mechanical or deterministic work even when the project uses different local tier names.

The Foundation tiers provide a portable semantic abstraction. The target project's detailed routing remains authoritative for concrete runtime selection when compatible with these semantics.

Minimize context: use relevant diffs, deduplicated error signatures, compact confirmed facts, and repository maps where available. Do not load entire repositories, chats, logs, or research collections by default. Do not repeat an identical failed attempt without new evidence.
