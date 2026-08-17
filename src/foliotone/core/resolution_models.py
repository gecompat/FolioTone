"""Persisted entity-resolution candidates and material evidence links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from foliotone.core._validation import require_aware_datetime, require_confidence, require_non_empty
from foliotone.core.enums import EntityKind
from foliotone.core.ids import EntityId

BOOK_RESOLUTION_ENTITY_KINDS = frozenset(
    {EntityKind.AGENT, EntityKind.WORK, EntityKind.EDITION, EntityKind.SERIES}
)
RESOLUTION_SUBJECT_KINDS = BOOK_RESOLUTION_ENTITY_KINDS | {
    EntityKind.FILE,
    EntityKind.FILE_OBSERVATION,
}


class ResolutionDisposition(StrEnum):
    AUTO_SAFE = "AUTO_SAFE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ResolutionEvidenceKind(StrEnum):
    VALUE_ASSERTION = "VALUE_ASSERTION"
    TOOL_RESULT = "TOOL_RESULT"
    FINGERPRINT = "FINGERPRINT"
    EXTERNAL_IDENTIFIER = "EXTERNAL_IDENTIFIER"
    CLASSIFICATION_ASSERTION = "CLASSIFICATION_ASSERTION"
    REVIEW_DECISION = "REVIEW_DECISION"


class ResolutionEvidenceRole(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    """One versioned, non-canonical candidate for an existing local entity."""

    id: EntityId
    subject_kind: EntityKind
    subject_id: EntityId
    candidate_kind: EntityKind
    candidate_entity_id: EntityId
    resolver_name: str
    resolver_version: str
    decision_compatibility_version: str
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    confidence: float
    disposition: ResolutionDisposition
    created_at: datetime

    def __post_init__(self) -> None:
        if self.subject_kind not in RESOLUTION_SUBJECT_KINDS:
            raise ValueError("subject_kind is not supported by book resolution")
        if self.candidate_kind not in BOOK_RESOLUTION_ENTITY_KINDS:
            raise ValueError("candidate_kind must be a book resolution entity kind")
        if self.subject_kind in BOOK_RESOLUTION_ENTITY_KINDS:
            if self.subject_kind is not self.candidate_kind:
                raise ValueError("entity subjects must preserve their identity level")
            if self.subject_id == self.candidate_entity_id:
                raise ValueError("resolution candidate must not map an entity to itself")
        for field_name in (
            "resolver_name",
            "resolver_version",
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
        require_confidence(self.confidence)
        require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ResolutionEvidenceLink:
    """Ordered provenance link to a concrete persisted evidence record."""

    id: EntityId
    resolution_candidate_id: EntityId
    ordinal: int
    evidence_kind: ResolutionEvidenceKind
    evidence_id: EntityId
    evidence_role: ResolutionEvidenceRole
    asserted_entity_kind: EntityKind
    material_fingerprint: str

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must not be negative")
        if self.asserted_entity_kind not in BOOK_RESOLUTION_ENTITY_KINDS:
            raise ValueError("asserted_entity_kind must be a book resolution entity kind")
        object.__setattr__(
            self,
            "material_fingerprint",
            _require_sha256(self.material_fingerprint, "material_fingerprint"),
        )


def _require_sha256(value: str, field_name: str) -> str:
    digest = require_non_empty(value, field_name).casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    return digest
