from datetime import UTC, datetime

import pytest

from foliotone.authority import (
    ResolutionReuseRoute,
    resolution_candidate_set_fingerprint,
    resolution_evidence_fingerprint,
    route_reusable_decision,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    ResolutionCandidate,
    ResolutionDisposition,
    ResolutionEvidenceKind,
    ResolutionEvidenceLink,
    ResolutionEvidenceRole,
    ReviewActorKind,
    ReviewDecision,
    ReviewDecisionValue,
)

NOW = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _link(
    *,
    ordinal: int,
    material: str,
    role: ResolutionEvidenceRole = ResolutionEvidenceRole.SUPPORTS,
    evidence_id: EntityId | None = None,
) -> ResolutionEvidenceLink:
    return ResolutionEvidenceLink(
        id=EntityId.new(),
        resolution_candidate_id=EntityId.new(),
        ordinal=ordinal,
        evidence_kind=ResolutionEvidenceKind.VALUE_ASSERTION,
        evidence_id=evidence_id or EntityId.new(),
        evidence_role=role,
        asserted_entity_kind=EntityKind.AGENT,
        material_fingerprint=material,
    )


def test_material_evidence_fingerprint_ignores_order_and_row_ids() -> None:
    first = _link(ordinal=0, material=DIGEST_A)
    second = _link(ordinal=1, material=DIGEST_B)
    replacement_first = _link(ordinal=9, material=DIGEST_A)
    replacement_second = _link(ordinal=8, material=DIGEST_B)

    assert resolution_evidence_fingerprint((first, second)) == resolution_evidence_fingerprint(
        (replacement_second, replacement_first)
    )
    contradicted = _link(
        ordinal=0,
        material=DIGEST_A,
        role=ResolutionEvidenceRole.CONTRADICTS,
    )
    assert resolution_evidence_fingerprint(
        (contradicted, second)
    ) != resolution_evidence_fingerprint((first, second))


def test_candidate_set_fingerprint_changes_for_competing_identity() -> None:
    first = EntityId.new()
    second = EntityId.new()
    singleton = resolution_candidate_set_fingerprint(((EntityKind.AGENT, first),))
    reordered = resolution_candidate_set_fingerprint(
        ((EntityKind.AGENT, second), (EntityKind.AGENT, first))
    )
    assert singleton != reordered
    assert reordered == resolution_candidate_set_fingerprint(
        ((EntityKind.AGENT, first), (EntityKind.AGENT, second))
    )


def test_first_seen_or_deferred_case_is_never_auto_safe() -> None:
    assert route_reusable_decision(None) is ResolutionReuseRoute.REVIEW_REQUIRED
    deferred = ReviewDecision(
        id=EntityId.new(),
        review_item_id=EntityId.new(),
        sequence_no=1,
        decision=ReviewDecisionValue.DEFER,
        decision_reason="NEEDS_MORE_EVIDENCE",
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        decision_compatibility_version="authority-decision/v1",
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW,
    )
    assert route_reusable_decision(deferred) is ResolutionReuseRoute.REVIEW_REQUIRED


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (ReviewDecisionValue.ACCEPT, ResolutionReuseRoute.AUTO_SAFE),
        (ReviewDecisionValue.REJECT, ResolutionReuseRoute.SUPPRESS_REJECTED),
    ],
)
def test_accept_and_reject_have_distinct_reuse_routes(
    decision: ReviewDecisionValue,
    expected: ResolutionReuseRoute,
) -> None:
    persisted = ReviewDecision(
        id=EntityId.new(),
        review_item_id=EntityId.new(),
        sequence_no=1,
        decision=decision,
        decision_reason="REVIEWED_LOCAL_EVIDENCE",
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        decision_compatibility_version="authority-decision/v1",
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW,
    )
    assert route_reusable_decision(persisted) is expected


def test_identity_levels_and_privacy_are_enforced() -> None:
    with pytest.raises(ValueError, match="identity level"):
        ResolutionCandidate(
            id=EntityId.new(),
            subject_kind=EntityKind.WORK,
            subject_id=EntityId.new(),
            candidate_kind=EntityKind.EDITION,
            candidate_entity_id=EntityId.new(),
            resolver_name="offline-book-resolution",
            resolver_version="1",
            decision_compatibility_version="1",
            evidence_fingerprint=DIGEST_A,
            candidate_set_fingerprint=DIGEST_B,
            confidence=0.5,
            disposition=ResolutionDisposition.REVIEW_REQUIRED,
            created_at=NOW,
        )
    decision = ReviewDecision(
        id=EntityId.new(),
        review_item_id=EntityId.new(),
        sequence_no=1,
        decision=ReviewDecisionValue.REJECT,
        decision_reason="HOMONYM_CONFLICT",
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        decision_compatibility_version="1",
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW,
    )
    assert "HOMONYM_CONFLICT" not in repr(decision)
    with pytest.raises(ValueError, match="reason code"):
        ReviewDecision(
            id=EntityId.new(),
            review_item_id=EntityId.new(),
            sequence_no=1,
            decision=ReviewDecisionValue.REJECT,
            decision_reason="C:/private/book.epub",
            evidence_fingerprint=DIGEST_A,
            candidate_set_fingerprint=DIGEST_B,
            decision_compatibility_version="1",
            actor_kind=ReviewActorKind.USER,
            decided_at=NOW,
        )
