# Dependency and External Service Policy

Status: AUTHORITATIVE

Adopt a dependency, tool, model, or service when its benefit justifies maintenance, security, licensing, cost, privacy, reproducibility, network, and lock-in impact. Review depth must be proportional to risk.

Risk classes:

- `ROUTINE`: established low-risk dependency/tool with ordinary permissions, no material data transfer, and a clear compatible license. Automated/package metadata checks plus normal validation are usually sufficient.
- `MATERIAL`: runtime dependency, externally hosted service, redistribution, meaningful data transfer, significant cost, or notable lock-in. Document the relevant license/terms, security/privacy, maintenance, reproducibility, cost, and exit implications.
- `CRITICAL`: privileged/security-sensitive component, sensitive data sharing, unclear/incompatible rights, high cost, major vendor commitment, or difficult recovery. Perform explicit due diligence and record the decision/evidence.

Review existing project capability and local/platform options before adding something new, but avoid needless reinvention. This is a review order, not a ban on a better maintained external solution.

Pin or lock versions when appropriate; avoid uncontrolled `latest` for critical workflows. Prefer project-local or isolated installation when practical. Make material network use and data transfer explicit, minimize data, define timeout/cancellation/failure behavior, and prevent partial inconsistent mutation.
