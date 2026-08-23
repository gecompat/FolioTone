# Third-Party and Licensing Policy

Status: AUTHORITATIVE — REQUIRED

The target project's license is independent of the Foundation project's license. Installing Foundation rules must never overwrite or silently select the target repository's root license.

## Foundation rule attribution

Transferred AI Repository Foundation material originates from an MIT-licensed source. The installation manifest therefore requires `.ai/foundation/AI_REPOSITORY_FOUNDATION_NOTICE.md` alongside the copied rules. That file preserves the complete Foundation copyright and MIT permission notice and applies only to the transferred Foundation material.

Do not replace, amend, or reinterpret the target project's root `LICENSE` merely to satisfy Foundation attribution. If a project also maintains a consolidated third-party notice, it may reference or additionally reproduce the Foundation notice, but the installed Foundation notice must retain the complete MIT notice unless an equivalent legally compliant mechanism is deliberately established and validated.

## Other third-party material

Review third-party material proportionally to risk. Public visibility, zero price, or an "open" label is not proof of permission.

- `ROUTINE`: standard dependency/material with clear compatible rights and no unusual redistribution or patent/privacy/security implications. Use reliable package/source metadata and normal automated checks where available.
- `MATERIAL`: redistribution, copied documentation/samples/data, runtime service, model, container, or dependency with meaningful legal/security/privacy/cost implications. Record current primary license/terms, required notices/attribution, relevant restrictions, source/version, and material operational implications.
- `CRITICAL`: missing/unclear/contradictory rights, incompatible copyleft/patent terms, privileged components, sensitive data transfer, or major commercial/vendor commitment. Do not incorporate or distribute until resolved.

Generated content is not automatically free of third-party rights. Preserve legally required notices without changing the target project's own license declaration.
