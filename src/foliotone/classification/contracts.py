"""Structured, privacy-safe multidimensional book classification contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from foliotone.core import ClassificationAssertion, EntityId, EntityKind, Provenance
from foliotone.core._validation import require_confidence, require_non_empty

DEFAULT_CLASSIFICATION_SOURCE: Final = "synthetic-classifier/v1"


class ClassificationDimension(StrEnum):
    DOMAIN = "domain"
    GENRE = "genre"
    SUBGENRE = "subgenre"
    TOPIC = "topic"
    AUDIENCE = "audience"
    LANGUAGE = "language"
    FORM = "form"


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
    return " ".join(normalized.split()).strip().casefold()
