from __future__ import annotations

from dataclasses import replace

import pytest

from foliotone.core import EntityId, EntityKind, MatchStatus, RelationType
from foliotone.matching import (
    MATCHER_DECISION_COMPATIBILITY,
    EbookRelationMatcher,
    MatcherFeature,
    MatcherFeatureCode,
    MatcherFeatureEffect,
    MatcherFeatureState,
    matcher_evidence_fingerprint,
    matcher_profile_for,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _ids() -> tuple[EntityId, EntityId, EntityId]:
    return (
        EntityId.parse("00000000-0000-4000-8000-000000000001"),
        EntityId.parse("00000000-0000-4000-8000-000000000002"),
        EntityId.parse("00000000-0000-4000-8000-000000000003"),
    )


def _feature(
    code: MatcherFeatureCode,
    *,
    state: MatcherFeatureState = MatcherFeatureState.PRESENT,
    digest: str = DIGEST_A,
    evidence_ids: tuple[EntityId, ...] = (),
) -> MatcherFeature:
    return MatcherFeature(code, state, digest, evidence_ids)


def _score(
    relation_type: RelationType,
    kind: EntityKind,
    features: tuple[MatcherFeature, ...],
):
    first, second, _ = _ids()
    return EbookRelationMatcher().score(
        relation_type,
        kind,
        second,
        kind,
        first,
        tuple(sorted(features, key=lambda item: item.code.value)),
    )


def test_exact_full_hash_is_the_only_automatic_confirmation() -> None:
    outcome = _score(
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        (_feature(MatcherFeatureCode.FILE_SHA256_EQUAL),),
    )

    assert outcome.status is MatchStatus.CONFIRMED
    assert outcome.confidence == 1.0
    assert outcome.left_id == _ids()[0]
    assert outcome.right_id == _ids()[1]
    assert outcome.matcher_version == "1"
    assert outcome.decision_compatibility_version == MATCHER_DECISION_COMPATIBILITY
    assert outcome.explanation[0].effect is MatcherFeatureEffect.SUPPORTING


def test_different_full_hash_rejects_exact_duplicate_candidate() -> None:
    outcome = _score(
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        (_feature(MatcherFeatureCode.FILE_SHA256_DIFFERENT),),
    )

    assert outcome.status is MatchStatus.REJECTED
    assert outcome.confidence == 0.0
    assert outcome.explanation[0].effect is MatcherFeatureEffect.CONTRADICTING


@pytest.mark.parametrize(
    ("relation_type", "kind", "features"),
    (
        (
            RelationType.SAME_EDITION,
            EntityKind.EDITION,
            (
                _feature(MatcherFeatureCode.EDITION_IDENTIFIER_COMPATIBLE),
                _feature(MatcherFeatureCode.RESOLVED_EDITION_EQUAL, digest=DIGEST_B),
                _feature(MatcherFeatureCode.NORMALIZED_TEXT_EQUAL),
            ),
        ),
        (
            RelationType.SAME_WORK,
            EntityKind.WORK,
            (
                _feature(MatcherFeatureCode.RESOLVED_WORK_EQUAL),
                _feature(MatcherFeatureCode.RESOLVED_AGENT_EQUAL, digest=DIGEST_B),
                _feature(MatcherFeatureCode.TITLE_COMPATIBLE),
            ),
        ),
    ),
)
def test_first_time_bibliographic_candidates_always_require_review(
    relation_type: RelationType,
    kind: EntityKind,
    features: tuple[MatcherFeature, ...],
) -> None:
    outcome = _score(relation_type, kind, features)

    assert outcome.status is MatchStatus.REVIEW_REQUIRED
    assert outcome.confidence == 1.0


@pytest.mark.parametrize(
    ("relation_type", "kind", "positive", "contradiction"),
    (
        (
            RelationType.SAME_EDITION,
            EntityKind.EDITION,
            MatcherFeatureCode.EDITION_IDENTIFIER_COMPATIBLE,
            MatcherFeatureCode.EDITION_IDENTIFIER_CONTRADICTORY,
        ),
        (
            RelationType.SAME_EDITION,
            EntityKind.EDITION,
            MatcherFeatureCode.RESOLVED_EDITION_EQUAL,
            MatcherFeatureCode.MATERIAL_TEXT_CONTRADICTORY,
        ),
        (
            RelationType.SAME_WORK,
            EntityKind.WORK,
            MatcherFeatureCode.RESOLVED_WORK_EQUAL,
            MatcherFeatureCode.RESOLVED_WORK_DIFFERENT,
        ),
    ),
)
def test_provider_or_tool_agreement_cannot_mask_hard_local_contradiction(
    relation_type: RelationType,
    kind: EntityKind,
    positive: MatcherFeatureCode,
    contradiction: MatcherFeatureCode,
) -> None:
    outcome = _score(
        relation_type,
        kind,
        (
            _feature(positive),
            _feature(contradiction, digest=DIGEST_B),
        ),
    )

    assert outcome.status is MatchStatus.REJECTED
    assert any(
        item.code is contradiction and item.effect is MatcherFeatureEffect.CONTRADICTING
        for item in outcome.explanation
    )


def test_translation_evidence_is_not_a_same_work_contradiction() -> None:
    outcome = _score(
        RelationType.SAME_WORK,
        EntityKind.WORK,
        (
            _feature(MatcherFeatureCode.RESOLVED_WORK_EQUAL),
            _feature(MatcherFeatureCode.LANGUAGE_CONTRADICTORY, digest=DIGEST_B),
            _feature(MatcherFeatureCode.NORMALIZED_TEXT_DIFFERENT),
        ),
    )

    assert outcome.status is MatchStatus.REVIEW_REQUIRED
    assert 0.0 < outcome.confidence < 1.0


def test_different_translation_title_does_not_reject_same_work() -> None:
    outcome = _score(
        RelationType.SAME_WORK,
        EntityKind.WORK,
        (
            _feature(MatcherFeatureCode.RESOLVED_WORK_EQUAL),
            _feature(MatcherFeatureCode.TITLE_CONTRADICTORY, digest=DIGEST_B),
        ),
    )

    assert outcome.status is MatchStatus.REVIEW_REQUIRED


def test_different_normalized_text_hash_alone_is_not_material_contradiction() -> None:
    outcome = _score(
        RelationType.SAME_EDITION,
        EntityKind.EDITION,
        (
            _feature(MatcherFeatureCode.RESOLVED_EDITION_EQUAL),
            _feature(MatcherFeatureCode.NORMALIZED_TEXT_DIFFERENT, digest=DIGEST_B),
        ),
    )

    assert outcome.status is MatchStatus.REVIEW_REQUIRED


def test_material_fingerprint_ignores_row_ids_but_changes_with_semantics() -> None:
    first, second, third = _ids()
    profile = matcher_profile_for(RelationType.SAME_EDITION)
    original = (
        _feature(
            MatcherFeatureCode.RESOLVED_EDITION_EQUAL,
            evidence_ids=(first, second),
        ),
    )
    different_rows = (
        _feature(
            MatcherFeatureCode.RESOLVED_EDITION_EQUAL,
            evidence_ids=(third,),
        ),
    )
    changed_material = (replace(original[0], material_fingerprint=DIGEST_B),)

    assert matcher_evidence_fingerprint(profile, original) == matcher_evidence_fingerprint(
        profile,
        different_rows,
    )
    assert matcher_evidence_fingerprint(
        profile,
        original,
    ) != matcher_evidence_fingerprint(profile, changed_material)

    paired = (
        _feature(MatcherFeatureCode.RESOLVED_EDITION_EQUAL),
        _feature(MatcherFeatureCode.NORMALIZED_TEXT_EQUAL, digest=DIGEST_B),
    )
    assert matcher_evidence_fingerprint(profile, paired) == matcher_evidence_fingerprint(
        profile,
        tuple(reversed(paired)),
    )


def test_path_free_explanation_and_strict_input_bounds() -> None:
    first, second, _ = _ids()
    feature = _feature(
        MatcherFeatureCode.RESOLVED_WORK_EQUAL,
        evidence_ids=(first, second),
    )
    outcome = _score(RelationType.SAME_WORK, EntityKind.WORK, (feature,))

    rendered = repr(outcome)
    assert "C:\\private" not in rendered
    assert "/private/collection" not in rendered
    assert DIGEST_A not in rendered
    with pytest.raises(ValueError, match="canonical order"):
        EbookRelationMatcher().score(
            RelationType.SAME_WORK,
            EntityKind.WORK,
            first,
            EntityKind.WORK,
            second,
            (
                _feature(MatcherFeatureCode.TITLE_COMPATIBLE),
                _feature(MatcherFeatureCode.RESOLVED_WORK_EQUAL),
            ),
        )
    with pytest.raises(ValueError, match="requires"):
        EbookRelationMatcher().score(
            RelationType.SAME_EDITION,
            EntityKind.WORK,
            first,
            EntityKind.WORK,
            second,
            (_feature(MatcherFeatureCode.RESOLVED_EDITION_EQUAL),),
        )
