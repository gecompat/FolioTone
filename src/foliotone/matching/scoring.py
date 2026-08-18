"""Versioned, conservative scoring for bounded e-book relation candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from foliotone.core import EntityId, EntityKind, MatchStatus, RelationType
from foliotone.matching.contracts import validate_relation_endpoints

MATCHER_DECISION_COMPATIBILITY = "ebook-matching-decision/v1"
_SHA256_LENGTH = 64
_MAX_FEATURES = 64
_MAX_EVIDENCE_IDS = 256


class MatcherFeatureState(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class MatcherFeatureEffect(StrEnum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    UNKNOWN = "UNKNOWN"


class MatcherFeatureCode(StrEnum):
    FILE_SHA256_EQUAL = "FILE_SHA256_EQUAL"
    FILE_SHA256_DIFFERENT = "FILE_SHA256_DIFFERENT"
    NORMALIZED_TEXT_EQUAL = "NORMALIZED_TEXT_EQUAL"
    NORMALIZED_TEXT_DIFFERENT = "NORMALIZED_TEXT_DIFFERENT"
    MATERIAL_TEXT_CONTRADICTORY = "MATERIAL_TEXT_CONTRADICTORY"
    EDITION_IDENTIFIER_COMPATIBLE = "EDITION_IDENTIFIER_COMPATIBLE"
    EDITION_IDENTIFIER_CONTRADICTORY = "EDITION_IDENTIFIER_CONTRADICTORY"
    RESOLVED_EDITION_EQUAL = "RESOLVED_EDITION_EQUAL"
    RESOLVED_EDITION_DIFFERENT = "RESOLVED_EDITION_DIFFERENT"
    RESOLVED_WORK_EQUAL = "RESOLVED_WORK_EQUAL"
    RESOLVED_WORK_DIFFERENT = "RESOLVED_WORK_DIFFERENT"
    RESOLVED_AGENT_EQUAL = "RESOLVED_AGENT_EQUAL"
    TITLE_COMPATIBLE = "TITLE_COMPATIBLE"
    TITLE_CONTRADICTORY = "TITLE_CONTRADICTORY"
    LANGUAGE_COMPATIBLE = "LANGUAGE_COMPATIBLE"
    LANGUAGE_CONTRADICTORY = "LANGUAGE_CONTRADICTORY"
    FORMAT_DIFFERENT = "FORMAT_DIFFERENT"


@dataclass(frozen=True, slots=True)
class MatcherFeature:
    code: MatcherFeatureCode
    state: MatcherFeatureState
    material_fingerprint: str
    evidence_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        _require_digest(self.material_fingerprint, "material_fingerprint")
        if len(self.evidence_ids) > _MAX_EVIDENCE_IDS:
            raise ValueError("matcher feature evidence exceeds the bounded limit")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("matcher feature evidence IDs must be unique")
        if self.evidence_ids != tuple(sorted(self.evidence_ids, key=str)):
            raise ValueError("matcher feature evidence IDs must be sorted")


@dataclass(frozen=True, slots=True)
class MatcherFeatureRule:
    code: MatcherFeatureCode
    weight: int
    effect: MatcherFeatureEffect = MatcherFeatureEffect.SUPPORTING
    hard_contradiction: bool = False
    required_for_confirmation: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.weight <= 100:
            raise ValueError("matcher feature weight must be between 1 and 100")
        if self.hard_contradiction and self.effect is not MatcherFeatureEffect.CONTRADICTING:
            raise ValueError("hard contradiction rules must be contradicting")
        if self.required_for_confirmation and self.effect is not MatcherFeatureEffect.SUPPORTING:
            raise ValueError("confirmation rules must be supporting")


@dataclass(frozen=True, slots=True)
class MatcherProfile:
    name: str
    version: str
    relation_type: RelationType
    rules: tuple[MatcherFeatureRule, ...]
    decision_compatibility_version: str = MATCHER_DECISION_COMPATIBILITY

    def __post_init__(self) -> None:
        for value, label in (
            (self.name, "matcher profile name"),
            (self.version, "matcher profile version"),
            (self.decision_compatibility_version, "decision compatibility version"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        codes = tuple(rule.code for rule in self.rules)
        if not codes or len(set(codes)) != len(codes):
            raise ValueError("matcher profile rules must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class MatcherExplanationEntry:
    code: MatcherFeatureCode
    effect: MatcherFeatureEffect
    weight: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class MatcherOutcome:
    relation_type: RelationType
    left_kind: EntityKind
    left_id: EntityId
    right_kind: EntityKind
    right_id: EntityId
    matcher_name: str
    matcher_version: str
    decision_compatibility_version: str
    status: MatchStatus
    confidence: float
    evidence_fingerprint: str
    explanation: tuple[MatcherExplanationEntry, ...]

    def __post_init__(self) -> None:
        validate_relation_endpoints(self.relation_type, self.left_kind, self.right_kind)
        if self.left_id == self.right_id:
            raise ValueError("matcher outcome endpoints must be distinct")
        if (str(self.left_id), self.left_kind.value) > (str(self.right_id), self.right_kind.value):
            raise ValueError("matcher outcome endpoints must use canonical order")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("matcher confidence must be between 0 and 1")
        _require_digest(self.evidence_fingerprint, "evidence_fingerprint")
        if not self.explanation or len(self.explanation) > _MAX_FEATURES:
            raise ValueError("matcher explanation count is outside bounds")


class EbookRelationMatcher:
    """Apply one fixed profile without persisting Relations or review state."""

    def score(
        self,
        relation_type: RelationType,
        left_kind: EntityKind,
        left_id: EntityId,
        right_kind: EntityKind,
        right_id: EntityId,
        features: tuple[MatcherFeature, ...],
    ) -> MatcherOutcome:
        profile = matcher_profile_for(relation_type)
        validate_relation_endpoints(relation_type, left_kind, right_kind)
        if left_id == right_id:
            raise ValueError("matching requires two distinct endpoints")
        _validate_features(profile, features, require_canonical_order=True)
        rules = {rule.code: rule for rule in profile.rules}

        explanation = tuple(
            MatcherExplanationEntry(
                code=feature.code,
                effect=_effect(rules[feature.code], feature.state),
                weight=rules[feature.code].weight,
                evidence_count=len(feature.evidence_ids),
            )
            for feature in features
        )
        contradictions = tuple(
            feature
            for feature in features
            if feature.state is MatcherFeatureState.PRESENT
            and rules[feature.code].effect is MatcherFeatureEffect.CONTRADICTING
            and rules[feature.code].hard_contradiction
        )
        supporting_weight = sum(
            rules[feature.code].weight
            for feature in features
            if feature.state is MatcherFeatureState.PRESENT
            and rules[feature.code].effect is MatcherFeatureEffect.SUPPORTING
        )
        assessed_weight = sum(
            rules[feature.code].weight
            for feature in features
            if feature.state is not MatcherFeatureState.ABSENT
        )
        confidence = 0.0 if assessed_weight == 0 else supporting_weight / assessed_weight
        status = _status(profile, features, contradictions)
        ordered_endpoints = sorted(
            ((left_kind, left_id), (right_kind, right_id)),
            key=lambda item: (str(item[1]), item[0].value),
        )
        return MatcherOutcome(
            relation_type=relation_type,
            left_kind=ordered_endpoints[0][0],
            left_id=ordered_endpoints[0][1],
            right_kind=ordered_endpoints[1][0],
            right_id=ordered_endpoints[1][1],
            matcher_name=profile.name,
            matcher_version=profile.version,
            decision_compatibility_version=profile.decision_compatibility_version,
            status=status,
            confidence=confidence,
            evidence_fingerprint=matcher_evidence_fingerprint(profile, features),
            explanation=explanation,
        )


def matcher_evidence_fingerprint(
    profile: MatcherProfile,
    features: tuple[MatcherFeature, ...],
) -> str:
    """Fingerprint material feature semantics, excluding row IDs and timestamps."""

    _validate_features(profile, features, require_canonical_order=False)
    payload = {
        "domain": "foliotone:ebook-matcher-evidence/v1",
        "profile": profile.name,
        "profile_version": profile.version,
        "decision_compatibility_version": profile.decision_compatibility_version,
        "relation_type": profile.relation_type.value,
        "features": sorted(
            (
                {
                    "code": feature.code.value,
                    "state": feature.state.value,
                    "material_fingerprint": feature.material_fingerprint,
                }
                for feature in features
            ),
            key=lambda item: item["code"],
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def matcher_profile_for(relation_type: RelationType) -> MatcherProfile:
    try:
        return EBOOK_MATCHER_PROFILES[relation_type]
    except KeyError as error:
        raise ValueError("relation_type has no book matcher profile") from error


def _validate_features(
    profile: MatcherProfile,
    features: tuple[MatcherFeature, ...],
    *,
    require_canonical_order: bool,
) -> None:
    if not features or len(features) > _MAX_FEATURES:
        raise ValueError("matcher feature count is outside bounds")
    codes = tuple(feature.code for feature in features)
    if len(set(codes)) != len(codes):
        raise ValueError("matcher features must contain unique codes")
    if require_canonical_order and codes != tuple(sorted(codes, key=lambda item: item.value)):
        raise ValueError("matcher features must use canonical order")
    supported = {rule.code for rule in profile.rules}
    if any(code not in supported for code in codes):
        raise ValueError("matcher feature is unsupported by profile")


def _status(
    profile: MatcherProfile,
    features: tuple[MatcherFeature, ...],
    contradictions: tuple[MatcherFeature, ...],
) -> MatchStatus:
    if contradictions:
        return MatchStatus.REJECTED
    by_code = {feature.code: feature for feature in features}
    required = tuple(rule for rule in profile.rules if rule.required_for_confirmation)
    all_required = bool(required) and all(
        by_code.get(rule.code) is not None
        and by_code[rule.code].state is MatcherFeatureState.PRESENT
        for rule in required
    )
    if profile.relation_type is RelationType.EXACT_DUPLICATE and all_required:
        return MatchStatus.CONFIRMED
    return MatchStatus.REVIEW_REQUIRED


def _effect(
    rule: MatcherFeatureRule,
    state: MatcherFeatureState,
) -> MatcherFeatureEffect:
    return rule.effect if state is MatcherFeatureState.PRESENT else MatcherFeatureEffect.UNKNOWN


def _require_digest(value: str, label: str) -> None:
    if len(value) != _SHA256_LENGTH or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hexadecimal digest")


EBOOK_MATCHER_PROFILES: dict[RelationType, MatcherProfile] = {
    RelationType.EXACT_DUPLICATE: MatcherProfile(
        "ebook-exact-duplicate",
        "1",
        RelationType.EXACT_DUPLICATE,
        (
            MatcherFeatureRule(
                MatcherFeatureCode.FILE_SHA256_EQUAL,
                100,
                required_for_confirmation=True,
            ),
            MatcherFeatureRule(
                MatcherFeatureCode.FILE_SHA256_DIFFERENT,
                100,
                MatcherFeatureEffect.CONTRADICTING,
                hard_contradiction=True,
            ),
        ),
    ),
    RelationType.SAME_EDITION: MatcherProfile(
        "ebook-same-edition",
        "1",
        RelationType.SAME_EDITION,
        (
            MatcherFeatureRule(MatcherFeatureCode.EDITION_IDENTIFIER_COMPATIBLE, 35),
            MatcherFeatureRule(
                MatcherFeatureCode.EDITION_IDENTIFIER_CONTRADICTORY,
                100,
                MatcherFeatureEffect.CONTRADICTING,
                hard_contradiction=True,
            ),
            MatcherFeatureRule(MatcherFeatureCode.RESOLVED_EDITION_EQUAL, 50),
            MatcherFeatureRule(
                MatcherFeatureCode.RESOLVED_EDITION_DIFFERENT,
                100,
                MatcherFeatureEffect.CONTRADICTING,
                hard_contradiction=True,
            ),
            MatcherFeatureRule(MatcherFeatureCode.RESOLVED_WORK_EQUAL, 20),
            MatcherFeatureRule(MatcherFeatureCode.RESOLVED_AGENT_EQUAL, 10),
            MatcherFeatureRule(MatcherFeatureCode.TITLE_COMPATIBLE, 10),
            MatcherFeatureRule(
                MatcherFeatureCode.TITLE_CONTRADICTORY,
                30,
                MatcherFeatureEffect.CONTRADICTING,
            ),
            MatcherFeatureRule(MatcherFeatureCode.LANGUAGE_COMPATIBLE, 10),
            MatcherFeatureRule(
                MatcherFeatureCode.LANGUAGE_CONTRADICTORY,
                30,
                MatcherFeatureEffect.CONTRADICTING,
            ),
            MatcherFeatureRule(MatcherFeatureCode.NORMALIZED_TEXT_EQUAL, 30),
            MatcherFeatureRule(
                MatcherFeatureCode.NORMALIZED_TEXT_DIFFERENT,
                20,
                MatcherFeatureEffect.CONTRADICTING,
            ),
            MatcherFeatureRule(
                MatcherFeatureCode.MATERIAL_TEXT_CONTRADICTORY,
                100,
                MatcherFeatureEffect.CONTRADICTING,
                hard_contradiction=True,
            ),
            MatcherFeatureRule(MatcherFeatureCode.FORMAT_DIFFERENT, 5),
        ),
    ),
    RelationType.SAME_WORK: MatcherProfile(
        "ebook-same-work",
        "1",
        RelationType.SAME_WORK,
        (
            MatcherFeatureRule(MatcherFeatureCode.RESOLVED_WORK_EQUAL, 60),
            MatcherFeatureRule(
                MatcherFeatureCode.RESOLVED_WORK_DIFFERENT,
                100,
                MatcherFeatureEffect.CONTRADICTING,
                hard_contradiction=True,
            ),
            MatcherFeatureRule(MatcherFeatureCode.RESOLVED_AGENT_EQUAL, 20),
            MatcherFeatureRule(MatcherFeatureCode.TITLE_COMPATIBLE, 20),
            MatcherFeatureRule(
                MatcherFeatureCode.TITLE_CONTRADICTORY,
                20,
                MatcherFeatureEffect.CONTRADICTING,
            ),
            MatcherFeatureRule(MatcherFeatureCode.LANGUAGE_COMPATIBLE, 5),
            MatcherFeatureRule(
                MatcherFeatureCode.LANGUAGE_CONTRADICTORY,
                5,
                MatcherFeatureEffect.CONTRADICTING,
            ),
            MatcherFeatureRule(MatcherFeatureCode.NORMALIZED_TEXT_EQUAL, 15),
            MatcherFeatureRule(
                MatcherFeatureCode.NORMALIZED_TEXT_DIFFERENT,
                15,
                MatcherFeatureEffect.CONTRADICTING,
            ),
        ),
    ),
}
