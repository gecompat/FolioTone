# Security and Safe Operations

Status: AUTHORITATIVE — REQUIRED

Use the authorization envelope from the current task, project rules, environment, permissions, scope, and budgets. Normal, expected operations inside that envelope do not require repeated confirmation merely because they mutate state.

Classify actions as:

- `READ_ONLY`;
- `NORMAL_OPERATION`;
- `HIGH_IMPACT_OPERATION`;
- `DESTRUCTIVE_OR_IRREVERSIBLE`.

Before a material operation, confirm the target and effects to the degree proportionate to its risk. `HIGH_IMPACT_OPERATION` may proceed when the current task or project policy clearly authorizes the relevant production, publication, permission, financial, messaging, release, or other material effect.

For `DESTRUCTIVE_OR_IRREVERSIBLE`, require exact target authority, assess recovery where possible, and re-resolve the target immediately before execution. Do not ask for another confirmation when the current task already explicitly and unambiguously authorizes that exact action and circumstances have not materially changed.

Request additional authority only when an action exceeds scope/environment/budget, targets an unexpected resource, has a material effect not reasonably implied by the task, or lacks exact authority for a destructive/irreversible effect.

Use dry-run/preview for high-risk operations when useful and available, not as mandatory bureaucracy for ordinary work. Failures must be bounded by timeouts/cancellation where applicable and must not leave silent partial state. Do not weaken privacy, secret handling, or integrity as a project override.
