"""Generic review items and append-only decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.enums import EntityKind
from foliotone.core.ids import EntityId
from foliotone.core.resolution_models import _require_sha256

_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


class ReviewType(StrEnum):
    AUTHORITY_RESOLUTION = "AUTHORITY_RESOLUTION"
    CLASSIFICATION = "CLASSIFICATION"
    MATCH_RELATION = "MATCH_RELATION"
    KEEP_PREFERENCE = "KEEP_PREFERENCE"
    CONSOLIDATION_CANDIDATE = "CONSOLIDATION_CANDIDATE"
    METADATA_CORRECTION = "METADATA_CORRECTION"
    EBOOK_OPERATION_RECIPE = "EBOOK_OPERATION_RECIPE"
    FIXITY_EXPECTATION = "FIXITY_EXPECTATION"


class ReviewCandidateKind(StrEnum):
    RESOLUTION_CANDIDATE = "RESOLUTION_CANDIDATE"
    CLASSIFICATION_ASSERTION = "CLASSIFICATION_ASSERTION"
    RELATION = "RELATION"
    KEEP_PREFERENCE = "KEEP_PREFERENCE"
    CONSOLIDATION_CANDIDATE = "CONSOLIDATION_CANDIDATE"
    METADATA_CORRECTION_CANDIDATE = "METADATA_CORRECTION_CANDIDATE"
    EBOOK_OPERATION_RECIPE_CANDIDATE = "EBOOK_OPERATION_RECIPE_CANDIDATE"
    FIXITY_RESULT = "FIXITY_RESULT"


class ReviewItemState(StrEnum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    DEFERRED = "DEFERRED"
    STALE = "STALE"


class ReviewDecisionValue(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"


class ReviewActorKind(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    id: EntityId
    review_type: ReviewType
    subject_kind: EntityKind
    subject_id: EntityId
    candidate_kind: ReviewCandidateKind
    candidate_id: EntityId
    producer_name: str
    producer_version: str
    decision_compatibility_version: str
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    state: ReviewItemState
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "producer_name",
            "producer_version",
            "decision_compatibility_version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _require_sha256(self.evidence_fingerprint, "evidence_fingerprint"),
        )
        object.__setattr__(
            self,
            "candidate_set_fingerprint",
            _require_sha256(
                self.candidate_set_fingerprint,
                "candidate_set_fingerprint",
            ),
        )
        if (
            self.review_type is ReviewType.AUTHORITY_RESOLUTION
            and self.candidate_kind is not ReviewCandidateKind.RESOLUTION_CANDIDATE
        ):
            raise ValueError("authority review requires a resolution candidate")
        if (
            self.review_type is ReviewType.MATCH_RELATION
            and self.candidate_kind is not ReviewCandidateKind.RELATION
        ):
            raise ValueError("matching review requires a relation candidate")
        if (
            self.review_type is ReviewType.METADATA_CORRECTION
            and self.candidate_kind is not ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE
        ):
            raise ValueError("metadata correction review requires its candidate kind")
        if (
            self.candidate_kind is ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE
            and self.review_type is not ReviewType.METADATA_CORRECTION
        ):
            raise ValueError("metadata correction candidate requires its review type")
        if (
            self.review_type is ReviewType.EBOOK_OPERATION_RECIPE
            and self.candidate_kind is not ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE
        ):
            raise ValueError("e-book operation recipe review requires its candidate kind")
        if (
            self.candidate_kind is ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE
            and self.review_type is not ReviewType.EBOOK_OPERATION_RECIPE
        ):
            raise ValueError("e-book operation recipe candidate requires its review type")
        if (
            self.review_type is ReviewType.FIXITY_EXPECTATION
            and self.candidate_kind is not ReviewCandidateKind.FIXITY_RESULT
        ):
            raise ValueError("fixity review requires a fixity result")
        if (
            self.candidate_kind is ReviewCandidateKind.FIXITY_RESULT
            and self.review_type is not ReviewType.FIXITY_EXPECTATION
        ):
            raise ValueError("fixity result requires its review type")
        if (
            self.review_type is ReviewType.FIXITY_EXPECTATION
            and self.subject_kind is not EntityKind.FILE
        ):
            raise ValueError("fixity review requires a FILE subject")
        require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    id: EntityId
    review_item_id: EntityId
    sequence_no: int
    decision: ReviewDecisionValue
    decision_reason: str = field(repr=False)
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    decision_compatibility_version: str
    actor_kind: ReviewActorKind
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.sequence_no < 1:
            raise ValueError("sequence_no must be positive")
        reason = require_non_empty(self.decision_reason, "decision_reason")
        if _REASON_CODE.fullmatch(reason) is None:
            raise ValueError("decision_reason must be a bounded reason code")
        object.__setattr__(self, "decision_reason", reason)
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _require_sha256(self.evidence_fingerprint, "evidence_fingerprint"),
        )
        object.__setattr__(
            self,
            "candidate_set_fingerprint",
            _require_sha256(
                self.candidate_set_fingerprint,
                "candidate_set_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "decision_compatibility_version",
            require_non_empty(
                self.decision_compatibility_version,
                "decision_compatibility_version",
            ),
        )
        require_aware_datetime(self.decided_at, "decided_at")
