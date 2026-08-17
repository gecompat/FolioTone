"""Pure fingerprints and conservative reuse policy for persisted resolution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from enum import StrEnum

from foliotone.core import (
    EntityId,
    EntityKind,
    ResolutionEvidenceLink,
    ReviewDecision,
    ReviewDecisionValue,
)

EVIDENCE_FINGERPRINT_PROFILE = "resolution-evidence/v1"
CANDIDATE_SET_FINGERPRINT_PROFILE = "resolution-candidate-set/v1"


class ResolutionReuseRoute(StrEnum):
    AUTO_SAFE = "AUTO_SAFE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUPPRESS_REJECTED = "SUPPRESS_REJECTED"


def resolution_evidence_fingerprint(
    evidence: Iterable[ResolutionEvidenceLink],
) -> str:
    """Hash material evidence semantics independent of row IDs and ordering."""

    descriptors = sorted(
        {
            (
                link.evidence_kind.value,
                link.evidence_role.value,
                link.asserted_entity_kind.value,
                link.material_fingerprint,
            )
            for link in evidence
            if link.evidence_kind.value != "REVIEW_DECISION"
        }
    )
    if not descriptors:
        raise ValueError("resolution evidence must contain material evidence")
    return _fingerprint(EVIDENCE_FINGERPRINT_PROFILE, descriptors)


def resolution_candidate_set_fingerprint(
    candidates: Iterable[tuple[EntityKind, EntityId]],
) -> str:
    """Hash the complete competing candidate set for optimistic review reuse."""

    descriptors = sorted({(kind.value, str(entity_id)) for kind, entity_id in candidates})
    if not descriptors:
        raise ValueError("candidate set must not be empty")
    return _fingerprint(CANDIDATE_SET_FINGERPRINT_PROFILE, descriptors)


def route_reusable_decision(
    decision: ReviewDecision | None,
) -> ResolutionReuseRoute:
    """Never auto-link a first-seen case; only reuse an exact prior decision."""

    if decision is None or decision.decision is ReviewDecisionValue.DEFER:
        return ResolutionReuseRoute.REVIEW_REQUIRED
    if decision.decision is ReviewDecisionValue.ACCEPT:
        return ResolutionReuseRoute.AUTO_SAFE
    return ResolutionReuseRoute.SUPPRESS_REJECTED


def _fingerprint(profile: str, descriptors: Sequence[tuple[str, ...]]) -> str:
    payload = json.dumps(
        {"profile": profile, "records": descriptors},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
