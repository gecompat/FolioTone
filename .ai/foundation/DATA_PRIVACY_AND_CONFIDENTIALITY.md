# Data Privacy and Confidentiality

Status: AUTHORITATIVE — REQUIRED

Privacy decisions are based on classification, destination, and handling authority. Information being real is not by itself a stop condition.

## Data classes

- `PUBLIC_OR_REPOSITORY_INTENDED`: public facts, public organization/product/project names, public URLs, and information intentionally approved for the repository/audience.
- `SYNTHETIC_OR_REDISTRIBUTABLE`: generated, public-domain, or explicitly redistributable material.
- `INTERNAL_OR_CONFIDENTIAL`: non-public business, customer, organization, environment, architecture, operational, or proprietary information.
- `PERSONAL_OR_SENSITIVE`: personal or sensitive information requiring explicit lawful/project handling authority.
- `SECRET_OR_CREDENTIAL`: passwords, tokens, API keys, private keys, private certificates, credential-bearing connection strings, or equivalent authentication material.
- `UNKNOWN`: classification or permitted destination cannot yet be established.

## Handling

`PUBLIC_OR_REPOSITORY_INTENDED` and `SYNTHETIC_OR_REDISTRIBUTABLE` may be used normally within scope. `INTERNAL_OR_CONFIDENTIAL` and `PERSONAL_OR_SENSITIVE` may be processed only within the project's authorized handling boundary and must not be transferred to a broader audience or external service without authority. `SECRET_OR_CREDENTIAL` never enters version control, examples, issues, PRs, documentation, or ordinary logs.

Stop before mutation or transfer only when classification/handling authority is unresolved (`UNKNOWN`), the planned destination crosses the permitted boundary, or an explicit stricter project/platform rule requires a gate. A public company name, repository name, documentation URL, or other real public fact is not a privacy gate by itself.

A target project may deliberately use a stricter privacy profile, including synthetic-only repository data, narrower allowlists, or additional approval requirements. Such a stricter rule is compatible with the Foundation and should be preserved.

## Required Foundation provenance in stricter projects

The legally required Foundation attribution notice may contain real public attribution information that a target privacy scanner would otherwise reject. Do not alter, abbreviate, or neutralize the required notice to satisfy a generic scanner.

When a stricter target scanner needs an exception, prefer the narrowest possible path-scoped exception for `.ai/foundation/AI_REPOSITORY_FOUNDATION_NOTICE.md` (or its deliberately equivalent validated notice location). Do not broaden a global personal-name or real-data allowlist merely to permit Foundation provenance.

Use data minimization. Real diagnostic data may be inspected when authorized but does not automatically become repository evidence. Review/redact it before broader transfer when required. Automated scanning supports classification but cannot replace semantic review.

If a secret may have been exposed, stop further distribution and rotate/revoke it as appropriate before treating repository cleanup as sufficient remediation.
