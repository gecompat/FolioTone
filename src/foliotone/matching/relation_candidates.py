"""Immutable persisted relation-candidate and feature-evidence contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from foliotone.core import EntityId, EntityKind, MatchStatus, RelationType
from foliotone.core._validation import require_aware_datetime, require_confidence
from foliotone.matching.contracts import validate_relation_endpoints
from foliotone.matching.scoring import MatcherFeatureCode, MatcherFeatureState, MatcherOutcome

MAX_RELATION_CANDIDATE_EVIDENCE = 256


class RelationCandidateEvidenceKind(StrEnum):
    FINGERPRINT = "FINGERPRINT"
    VALUE_ASSERTION = "VALUE_ASSERTION"
    EXTERNAL_IDENTIFIER = "EXTERNAL_IDENTIFIER"
    RESOLUTION_CANDIDATE = "RESOLUTION_CANDIDATE"
    TOOL_RESULT = "TOOL_RESULT"
    CLASSIFICATION_ASSERTION = "CLASSIFICATION_ASSERTION"
    REVIEW_DECISION = "REVIEW_DECISION"


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    left_kind: EntityKind
    left_id: EntityId
    right_kind: EntityKind
    right_id: EntityId
    relation_type: RelationType
    matcher_name: str
    matcher_version: str
    decision_compatibility_version: str
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    confidence: float
    status: MatchStatus
    created_at: datetime

    def __post_init__(self) -> None:
        validate_relation_endpoints(self.relation_type, self.left_kind, self.right_kind)
        if self.left_id == self.right_id or str(self.left_id) > str(self.right_id):
            raise ValueError("relation candidate endpoints must use distinct canonical order")
        if self.status not in {
            MatchStatus.CONFIRMED,
            MatchStatus.REVIEW_REQUIRED,
            MatchStatus.REJECTED,
        }:
            raise ValueError("relation candidate status is unsupported")
        if (
            self.status is MatchStatus.CONFIRMED
            and self.relation_type is not RelationType.EXACT_DUPLICATE
        ):
            raise ValueError("only exact duplicates may be automatically confirmed")
        for value, label in (
            (self.matcher_name, "matcher_name"),
            (self.matcher_version, "matcher_version"),
            (self.decision_compatibility_version, "decision_compatibility_version"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        _require_digest(self.evidence_fingerprint, "evidence_fingerprint")
        _require_digest(self.candidate_set_fingerprint, "candidate_set_fingerprint")
        require_confidence(self.confidence)
        require_aware_datetime(self.created_at, "created_at")

    @classmethod
    def from_outcome(
        cls,
        candidate_id: EntityId,
        scan_root_id: EntityId,
        source_scan_run_id: EntityId,
        candidate_set_fingerprint: str,
        outcome: MatcherOutcome,
        created_at: datetime,
    ) -> RelationCandidate:
        return cls(
            candidate_id,
            scan_root_id,
            source_scan_run_id,
            outcome.left_kind,
            outcome.left_id,
            outcome.right_kind,
            outcome.right_id,
            outcome.relation_type,
            outcome.matcher_name,
            outcome.matcher_version,
            outcome.decision_compatibility_version,
            outcome.evidence_fingerprint,
            candidate_set_fingerprint,
            outcome.confidence,
            outcome.status,
            created_at,
        )


@dataclass(frozen=True, slots=True)
class RelationCandidateEvidenceLink:
    id: EntityId
    relation_candidate_id: EntityId
    ordinal: int
    feature_code: MatcherFeatureCode
    feature_state: MatcherFeatureState
    material_fingerprint: str
    evidence_kind: RelationCandidateEvidenceKind | None = None
    evidence_id: EntityId | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("relation candidate evidence ordinal must not be negative")
        _require_digest(self.material_fingerprint, "material_fingerprint")
        if (self.evidence_kind is None) != (self.evidence_id is None):
            raise ValueError("evidence kind and id must both be set or both be absent")


def relation_candidate_set_fingerprint(
    candidates: tuple[tuple[RelationType, EntityKind, EntityId, EntityKind, EntityId], ...],
) -> str:
    if not candidates:
        raise ValueError("relation candidate set must not be empty")
    for relation_type, left_kind, left_id, right_kind, right_id in candidates:
        validate_relation_endpoints(relation_type, left_kind, right_kind)
        if left_id == right_id or str(left_id) > str(right_id):
            raise ValueError("relation candidate set endpoints must use canonical order")
    canonical = sorted(
        {
            (
                relation_type.value,
                left_kind.value,
                str(left_id),
                right_kind.value,
                str(right_id),
            )
            for relation_type, left_kind, left_id, right_kind, right_id in candidates
        }
    )
    encoded = json.dumps(
        {"domain": "foliotone:relation-candidate-set/v1", "candidates": canonical},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hexadecimal digest")
