"""Structured, privacy-safe multidimensional book classification contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from unicodedata import normalize
from uuid import UUID, uuid5

from foliotone.core import ClassificationAssertion, EntityId, EntityKind, Provenance
from foliotone.core._validation import require_confidence, require_non_empty

DEFAULT_CLASSIFICATION_SOURCE: Final = "synthetic-classifier/v1"
BOOK_CLASSIFICATION_ASSERTION_PROFILE: Final = "book-classification-assertion/v1"
BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE: Final = "book-classification-canonical-json/v1"
BOOK_CLASSIFICATION_ASSERTION_NAMESPACE: Final = UUID("d3636547-6437-5d62-bf35-37a004008630")
_TAXONOMY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ClassificationSourceKind(StrEnum):
    LOCAL_DERIVED = "LOCAL_DERIVED"
    TOOL_PROVIDER = "TOOL_PROVIDER"
    KNOWLEDGE_PROVIDER = "KNOWLEDGE_PROVIDER"
    USER_CONFIRMED = "USER_CONFIRMED"


class ClassificationSourceReferenceKind(StrEnum):
    LOCAL_RULE_RUN = "LOCAL_RULE_RUN"
    TOOL_RESULT = "TOOL_RESULT"
    PROVIDER_MAPPING_OUTPUT = "PROVIDER_MAPPING_OUTPUT"
    REVIEW_DECISION = "REVIEW_DECISION"


class ClassificationPriorityTier(StrEnum):
    AUTOMATED = "AUTOMATED"
    USER_CONFIRMED = "USER_CONFIRMED"


_SOURCE_REFERENCE_RULES: Final = {
    ClassificationSourceKind.LOCAL_DERIVED: (
        ClassificationSourceReferenceKind.LOCAL_RULE_RUN,
        ClassificationPriorityTier.AUTOMATED,
    ),
    ClassificationSourceKind.TOOL_PROVIDER: (
        ClassificationSourceReferenceKind.TOOL_RESULT,
        ClassificationPriorityTier.AUTOMATED,
    ),
    ClassificationSourceKind.KNOWLEDGE_PROVIDER: (
        ClassificationSourceReferenceKind.PROVIDER_MAPPING_OUTPUT,
        ClassificationPriorityTier.AUTOMATED,
    ),
    ClassificationSourceKind.USER_CONFIRMED: (
        ClassificationSourceReferenceKind.REVIEW_DECISION,
        ClassificationPriorityTier.USER_CONFIRMED,
    ),
}


class ClassificationDimension(StrEnum):
    DOMAIN = "domain"
    GENRE = "genre"
    SUBGENRE = "subgenre"
    TOPIC = "topic"
    AUDIENCE = "audience"
    LANGUAGE = "language"
    FORM = "form"


@dataclass(frozen=True, slots=True)
class BookClassificationAssertionLineage:
    """Immutable, source-specific lineage for one profiled book assertion."""

    assertion_key: str
    assertion_profile_version: str
    source_kind: ClassificationSourceKind
    source_reference_kind: ClassificationSourceReferenceKind
    source_reference: str
    priority_tier: ClassificationPriorityTier
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assertion_key",
            _require_sha256(self.assertion_key, "assertion_key"),
        )
        if self.assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE:
            raise ValueError("unsupported assertion profile version")
        reference_kind, priority_tier = _SOURCE_REFERENCE_RULES[self.source_kind]
        if self.source_reference_kind is not reference_kind:
            raise ValueError("source kind and source reference kind do not match")
        if self.priority_tier is not priority_tier:
            raise ValueError("source kind and priority tier do not match")
        object.__setattr__(
            self,
            "source_reference",
            _normalize_source_reference(self.source_reference, self.source_reference_kind),
        )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BookClassificationAssertion:
    """Canonical insert-only book classification assertion and its lineage."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    dimension: ClassificationDimension
    normalized_value: str
    taxonomy: str
    confidence: float | None
    source_name: str
    source_version: str
    observed_at: datetime
    lineage: BookClassificationAssertionLineage

    def __post_init__(self) -> None:
        if self.target_kind not in {EntityKind.WORK, EntityKind.EDITION}:
            raise ValueError("classification assertions require WORK or EDITION target kind")
        object.__setattr__(
            self,
            "normalized_value",
            _normalize_assertion_value(self.normalized_value),
        )
        object.__setattr__(self, "taxonomy", _normalize_taxonomy(self.taxonomy))
        object.__setattr__(
            self,
            "source_name",
            _normalize_source_label(self.source_name, "source_name"),
        )
        object.__setattr__(
            self,
            "source_version",
            _normalize_source_label(self.source_version, "source_version"),
        )
        if isinstance(self.confidence, bool):
            raise ValueError("confidence must be a finite number or None")
        require_confidence(self.confidence, "confidence")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        expected_key = classification_assertion_key(
            target_kind=self.target_kind,
            target_id=self.target_id,
            dimension=self.dimension,
            normalized_value=self.normalized_value,
            taxonomy=self.taxonomy,
            assertion_profile_version=self.lineage.assertion_profile_version,
            source_kind=self.lineage.source_kind,
            source_reference=self.lineage.source_reference,
        )
        if self.lineage.assertion_key != expected_key:
            raise ValueError("lineage assertion_key does not match assertion content")
        expected_id = classification_assertion_id(expected_key)
        if self.id != expected_id:
            raise ValueError("assertion id does not match assertion key")

    @classmethod
    def create(
        cls,
        *,
        target_kind: EntityKind,
        target_id: EntityId,
        dimension: ClassificationDimension,
        value: str,
        taxonomy: str,
        confidence: float | None,
        source_name: str,
        source_version: str,
        source_kind: ClassificationSourceKind,
        source_reference: str,
        observed_at: datetime,
        created_at: datetime,
    ) -> BookClassificationAssertion:
        """Build the ADR-0037 deterministic assertion identity and lineage."""

        normalized_value = _normalize_assertion_value(value)
        normalized_taxonomy = _normalize_taxonomy(taxonomy)
        reference_kind, priority_tier = _SOURCE_REFERENCE_RULES[source_kind]
        normalized_reference = _normalize_source_reference(source_reference, reference_kind)
        key = classification_assertion_key(
            target_kind=target_kind,
            target_id=target_id,
            dimension=dimension,
            normalized_value=normalized_value,
            taxonomy=normalized_taxonomy,
            assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
            source_kind=source_kind,
            source_reference=normalized_reference,
        )
        return cls(
            id=classification_assertion_id(key),
            target_kind=target_kind,
            target_id=target_id,
            dimension=dimension,
            normalized_value=normalized_value,
            taxonomy=normalized_taxonomy,
            confidence=confidence,
            source_name=source_name,
            source_version=source_version,
            observed_at=observed_at,
            lineage=BookClassificationAssertionLineage(
                assertion_key=key,
                assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
                source_kind=source_kind,
                source_reference_kind=reference_kind,
                source_reference=normalized_reference,
                priority_tier=priority_tier,
                created_at=created_at,
            ),
        )


def classification_assertion_key(
    *,
    target_kind: EntityKind,
    target_id: EntityId,
    dimension: ClassificationDimension,
    normalized_value: str,
    taxonomy: str,
    assertion_profile_version: str,
    source_kind: ClassificationSourceKind,
    source_reference: str,
) -> str:
    """Return the versioned SHA-256 identity required by ADR-0037."""

    payload = {
        "canonical_json_profile": BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE,
        "assertion_profile_version": assertion_profile_version,
        "target_kind": target_kind.value,
        "target_id": str(target_id),
        "dimension": dimension.value,
        "normalized_value": _normalize_assertion_value(normalized_value),
        "taxonomy": _normalize_taxonomy(taxonomy),
        "source_kind": source_kind.value,
        "source_reference": _normalize_source_reference(
            source_reference,
            _SOURCE_REFERENCE_RULES[source_kind][0],
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classification_assertion_id(assertion_key: str) -> EntityId:
    """Derive the immutable UUIDv5 identity from a validated assertion key."""

    return EntityId(
        uuid5(
            BOOK_CLASSIFICATION_ASSERTION_NAMESPACE,
            _require_sha256(assertion_key, "assertion_key"),
        )
    )


@dataclass(frozen=True, slots=True)
class BookClassificationFacet:
    """Single classification assertion payload without entity-level fields."""

    dimension: ClassificationDimension
    value: str
    taxonomy: str
    confidence: float = 0.7

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _normalize_classification_value(self.value))
        object.__setattr__(
            self,
            "taxonomy",
            require_non_empty(self.taxonomy, "taxonomy"),
        )
        require_confidence(self.confidence, "confidence")
        if self.value == "":
            raise ValueError("value must not be empty")


@dataclass(frozen=True, slots=True)
class BookClassificationQuery:
    """Structured query payload for multidimensional assertions."""

    domain: str | None = None
    genre: str | None = None
    subgenre: str | None = None
    topic: str | None = None
    audience: str | None = None
    language: str | None = None
    form: str | None = None
    taxonomy: str = "local"
    confidence: float = 0.7

    def __post_init__(self) -> None:
        require_confidence(self.confidence, "confidence")
        object.__setattr__(self, "taxonomy", require_non_empty(self.taxonomy, "taxonomy"))

    def facets(self) -> tuple[BookClassificationFacet, ...]:
        facets: list[BookClassificationFacet] = []
        for dimension, value in (
            (ClassificationDimension.DOMAIN, self.domain),
            (ClassificationDimension.GENRE, self.genre),
            (ClassificationDimension.SUBGENRE, self.subgenre),
            (ClassificationDimension.TOPIC, self.topic),
            (ClassificationDimension.AUDIENCE, self.audience),
            (ClassificationDimension.LANGUAGE, self.language),
            (ClassificationDimension.FORM, self.form),
        ):
            if value is None:
                continue
            facets.append(
                _facet_for(
                    dimension,
                    value,
                    taxonomy=self.taxonomy,
                    confidence=self.confidence,
                )
            )
        return tuple(facets)


@dataclass(frozen=True, slots=True)
class BookClassificationSet:
    """Bundle of assertions for one target entity."""

    target_kind: EntityKind
    target_id: EntityId
    facets: tuple[BookClassificationFacet, ...]
    source_name: str
    source_version: str = DEFAULT_CLASSIFICATION_SOURCE
    observed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_name",
            require_non_empty(self.source_name, "source_name"),
        )
        if self.source_version is not None:
            object.__setattr__(
                self,
                "source_version",
                require_non_empty(self.source_version, "source_version"),
            )
        if not self.facets:
            raise ValueError("at least one classification facet is required")
        if self.target_kind not in {EntityKind.WORK, EntityKind.EDITION}:
            raise ValueError("classification assertions require WORK or EDITION target kind")

    @property
    def query(self) -> str:
        return f"{self.target_kind.name}:{self.target_id}:{len(self.facets)}"


def make_classification_dto(facet: BookClassificationFacet) -> dict[str, str | float]:
    """Privacy-safe, serializable DTO for one classification facet."""
    return {
        "dimension": facet.dimension.value,
        "value": facet.value,
        "taxonomy": facet.taxonomy,
        "confidence": facet.confidence,
    }


def build_classification_assertions(
    classification_set: BookClassificationSet,
) -> tuple[ClassificationAssertion, ...]:
    """Convert a structured book classification set into persistence assertions."""
    provenance = Provenance(
        source_kind="classification",
        source_name=classification_set.source_name,
        source_version=classification_set.source_version,
        observed_at=classification_set.observed_at,
    )

    return tuple(
        ClassificationAssertion(
            id=EntityId.new(),
            target_kind=classification_set.target_kind,
            target_id=classification_set.target_id,
            dimension=facet.dimension.value,
            value=facet.value,
            provenance=provenance,
            taxonomy=facet.taxonomy,
            confidence=facet.confidence,
        )
        for facet in classification_set.facets
    )


def _facet_for(
    dimension: ClassificationDimension,
    value: str,
    *,
    taxonomy: str,
    confidence: float,
) -> BookClassificationFacet:
    return BookClassificationFacet(
        dimension=dimension,
        value=value,
        taxonomy=taxonomy,
        confidence=confidence,
    )


def _normalize_classification_value(value: str) -> str:
    normalized = require_non_empty(value, "classification value")
    return normalize("NFC", " ".join(normalized.split()).strip().casefold())


def _normalize_assertion_value(value: str) -> str:
    normalized = _normalize_classification_value(value)
    if not 1 <= len(normalized) <= 512:
        raise ValueError("classification value must contain 1 to 512 codepoints")
    return normalized


def _normalize_taxonomy(value: str) -> str:
    normalized = require_non_empty(value, "taxonomy")
    if _TAXONOMY.fullmatch(normalized) is None:
        raise ValueError("taxonomy must be a lowercase bounded identifier")
    return normalized


def _normalize_source_label(value: str, field_name: str) -> str:
    normalized = require_non_empty(value, field_name)
    if (
        not 1 <= len(normalized) <= 128
        or "/" in normalized
        or "\\" in normalized
        or normalized in {".", ".."}
        or re.match(r"^[A-Za-z]:", normalized) is not None
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError(f"{field_name} must be a bounded path-free label")
    return normalized


def _normalize_source_reference(
    value: str,
    reference_kind: ClassificationSourceReferenceKind,
) -> str:
    normalized = require_non_empty(value, "source_reference")
    if reference_kind in {
        ClassificationSourceReferenceKind.LOCAL_RULE_RUN,
        ClassificationSourceReferenceKind.PROVIDER_MAPPING_OUTPUT,
    }:
        return _require_sha256(normalized, "source_reference")
    try:
        return str(UUID(normalized))
    except ValueError as error:
        raise ValueError("source_reference must be a canonical UUID") from error


def _require_sha256(value: str, field_name: str) -> str:
    normalized = require_non_empty(value, field_name)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return normalized
