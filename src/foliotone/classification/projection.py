"""Pure, deterministic projections of profiled book classification evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from foliotone.classification.contracts import (
    BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE,
    BookClassificationAssertion,
    ClassificationDimension,
    ClassificationPriorityTier,
)
from foliotone.core import EntityId, EntityKind

BOOK_CLASSIFICATION_PROJECTION_PROFILE: Final = "book-classification-projection/v1"
BOOK_CLASSIFICATION_PROJECTION_NAMESPACE: Final = UUID("3b130592-d8aa-5f56-9c9f-acde3b159e89")

_DIMENSIONS: Final = tuple(ClassificationDimension)
_SET_VALUE_LIMITS: Final = {
    ClassificationDimension.GENRE: 8,
    ClassificationDimension.SUBGENRE: 16,
    ClassificationDimension.TOPIC: 32,
    ClassificationDimension.AUDIENCE: 8,
    ClassificationDimension.LANGUAGE: 8,
    ClassificationDimension.FORM: 8,
}


class ClassificationProjectionStatus(StrEnum):
    EMPTY = "EMPTY"
    PROJECTED = "PROJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ClassificationFacetStatus(StrEnum):
    EMPTY = "EMPTY"
    PROJECTED = "PROJECTED"
    CONFLICT = "CONFLICT"


class ClassificationProjectionConflictCode(StrEnum):
    MULTIPLE_EXCLUSIVE_VALUES = "MULTIPLE_EXCLUSIVE_VALUES"
    CARDINALITY_EXCEEDED = "CARDINALITY_EXCEEDED"
    CONFIRMED_CONTRADICTION = "CONFIRMED_CONTRADICTION"


class ClassificationProjectionLinkRole(StrEnum):
    SELECTED = "SELECTED"
    CONSIDERED = "CONSIDERED"
    CONFLICTING = "CONFLICTING"


class ClassificationProjectionError(ValueError):
    """The input cannot safely produce a v1 classification projection."""


class ClassificationProjectionConflictError(ClassificationProjectionError):
    """A v1 projection would require review; S-EB04-05 owns that output."""


@dataclass(frozen=True, slots=True)
class BookClassificationProjectionValue:
    """One ordered, normalized value selected for a projected facet."""

    ordinal: int
    taxonomy: str
    normalized_value: str

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a nonnegative integer")
        if not self.taxonomy or not self.normalized_value:
            raise ValueError("projected values must be non-empty")


@dataclass(frozen=True, slots=True)
class BookClassificationProjectionFacet:
    """The immutable local view for one of the exact seven dimensions."""

    dimension: ClassificationDimension
    status: ClassificationFacetStatus
    values: tuple[BookClassificationProjectionValue, ...] = ()
    conflict_code: ClassificationProjectionConflictCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, ClassificationDimension):
            raise ValueError("dimension must be a ClassificationDimension")
        if not isinstance(self.status, ClassificationFacetStatus):
            raise ValueError("status must be a ClassificationFacetStatus")
        if any(not isinstance(value, BookClassificationProjectionValue) for value in self.values):
            raise ValueError("values must contain BookClassificationProjectionValue values")
        if tuple(value.ordinal for value in self.values) != tuple(range(len(self.values))):
            raise ValueError("value ordinals must be contiguous and ordered")
        if tuple((value.taxonomy, value.normalized_value) for value in self.values) != tuple(
            sorted((value.taxonomy, value.normalized_value) for value in self.values)
        ):
            raise ValueError("values must use canonical ordering")
        if self.conflict_code is not None and not isinstance(
            self.conflict_code, ClassificationProjectionConflictCode
        ):
            raise ValueError("conflict_code must be a ClassificationProjectionConflictCode")
        if len({(value.taxonomy, value.normalized_value) for value in self.values}) != len(
            self.values
        ):
            raise ValueError("values must be unique by taxonomy and normalized_value")
        if self.status is ClassificationFacetStatus.EMPTY:
            if self.values or self.conflict_code is not None:
                raise ValueError("empty facets cannot contain values or a conflict code")
        elif self.status is ClassificationFacetStatus.PROJECTED:
            if not self.values or self.conflict_code is not None:
                raise ValueError("projected facets require values and no conflict code")
        elif not self.conflict_code or self.values:
            raise ValueError("conflict facets require a conflict code and no values")


@dataclass(frozen=True, slots=True)
class BookClassificationProjectionAssertionLink:
    """An exact, role-labelled assertion reference retained by a projection."""

    assertion_id: EntityId
    assertion_key: str
    role: ClassificationProjectionLinkRole
    conflict_code: ClassificationProjectionConflictCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assertion_id, EntityId):
            raise ValueError("assertion_id must be an EntityId")
        if len(self.assertion_key) != 64 or any(
            character not in "0123456789abcdef" for character in self.assertion_key
        ):
            raise ValueError("assertion_key must be a lowercase SHA-256")
        if not isinstance(self.role, ClassificationProjectionLinkRole):
            raise ValueError("role must be a ClassificationProjectionLinkRole")
        if self.conflict_code is not None and not isinstance(
            self.conflict_code, ClassificationProjectionConflictCode
        ):
            raise ValueError("conflict_code must be a ClassificationProjectionConflictCode")
        if self.role is ClassificationProjectionLinkRole.CONFLICTING:
            if self.conflict_code is None:
                raise ValueError("conflicting links require a conflict code")
        elif self.conflict_code is not None:
            raise ValueError("selected and considered links cannot carry a conflict code")


@dataclass(frozen=True, slots=True)
class BookClassificationProjection:
    """A deterministic, immutable projection snapshot; never source evidence."""

    id: EntityId
    target_kind: EntityKind
    target_id: EntityId
    assertion_profile_version: str
    projection_profile_version: str
    input_fingerprint: str
    status: ClassificationProjectionStatus
    facets: tuple[BookClassificationProjectionFacet, ...]
    assertion_links: tuple[BookClassificationProjectionAssertionLink, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, EntityId) or not isinstance(self.target_id, EntityId):
            raise ValueError("projection identifiers must be EntityId values")
        if self.target_kind not in {EntityKind.WORK, EntityKind.EDITION}:
            raise ValueError("classification projections require WORK or EDITION target kind")
        if self.assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE:
            raise ValueError("unsupported assertion profile version")
        if self.projection_profile_version != BOOK_CLASSIFICATION_PROJECTION_PROFILE:
            raise ValueError("unsupported projection profile version")
        _require_sha256(self.input_fingerprint, "input_fingerprint")
        if not isinstance(self.status, ClassificationProjectionStatus):
            raise ValueError("status must be a ClassificationProjectionStatus")
        if any(not isinstance(facet, BookClassificationProjectionFacet) for facet in self.facets):
            raise ValueError("facets must contain BookClassificationProjectionFacet values")
        if tuple(facet.dimension for facet in self.facets) != _DIMENSIONS:
            raise ValueError("facets must contain the exact seven canonical dimensions")
        if any(
            not isinstance(link, BookClassificationProjectionAssertionLink)
            for link in self.assertion_links
        ):
            raise ValueError(
                "assertion_links must contain BookClassificationProjectionAssertionLink values"
            )
        if len({link.assertion_key for link in self.assertion_links}) != len(self.assertion_links):
            raise ValueError("assertion links must be unique by assertion_key")
        if tuple(link.assertion_key for link in self.assertion_links) != tuple(
            sorted(link.assertion_key for link in self.assertion_links)
        ):
            raise ValueError("assertion links must use canonical ordering")
        facet_statuses = {facet.status for facet in self.facets}
        if self.status is ClassificationProjectionStatus.EMPTY:
            if facet_statuses != {ClassificationFacetStatus.EMPTY} or self.assertion_links:
                raise ValueError("empty projections require empty facets and no assertion links")
        elif self.status is ClassificationProjectionStatus.PROJECTED:
            if (
                ClassificationFacetStatus.CONFLICT in facet_statuses
                or ClassificationFacetStatus.PROJECTED not in facet_statuses
            ):
                raise ValueError("projected projections require values and no conflict facets")
        elif ClassificationFacetStatus.CONFLICT not in facet_statuses:
            raise ValueError("review-required projections require a conflict facet")
        expected_id = classification_projection_id(
            target_kind=self.target_kind,
            target_id=self.target_id,
            projection_profile_version=self.projection_profile_version,
            input_fingerprint=self.input_fingerprint,
        )
        if self.id != expected_id:
            raise ValueError("projection id does not match projection identity")


def classification_projection_input_fingerprint(
    *,
    target_kind: EntityKind,
    target_id: EntityId,
    assertions: Iterable[BookClassificationAssertion],
) -> str:
    """Hash target and sorted profiled assertion keys with canonical JSON bytes."""

    checked = _checked_assertions(
        target_kind=target_kind, target_id=target_id, assertions=assertions
    )
    material = {
        "canonical_json_profile": BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE,
        "target_kind": target_kind.value,
        "target_id": str(target_id),
        "assertion_profile_version": BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        "assertion_keys": [item.lineage.assertion_key for item in checked],
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def classification_projection_id(
    *,
    target_kind: EntityKind,
    target_id: EntityId,
    projection_profile_version: str,
    input_fingerprint: str,
) -> EntityId:
    """Derive the ADR-0037 UUIDv5 identity for one immutable snapshot."""

    if target_kind not in {EntityKind.WORK, EntityKind.EDITION} or not isinstance(
        target_id, EntityId
    ):
        raise ClassificationProjectionError("projection target must be a book entity")
    if projection_profile_version != BOOK_CLASSIFICATION_PROJECTION_PROFILE:
        raise ClassificationProjectionError("unsupported projection profile version")
    _require_sha256(input_fingerprint, "input_fingerprint")
    material = {
        "target_kind": target_kind.value,
        "target_id": str(target_id),
        "projection_profile_version": projection_profile_version,
        "input_fingerprint": input_fingerprint,
    }
    return EntityId(
        uuid5(BOOK_CLASSIFICATION_PROJECTION_NAMESPACE, _canonical_json(material).decode("utf-8"))
    )


def reduce_book_classification_assertions(
    *,
    target_kind: EntityKind,
    target_id: EntityId,
    assertions: Iterable[BookClassificationAssertion],
) -> BookClassificationProjection:
    """Reduce v1 assertions without I/O, confidence ranking, or mutation."""

    checked = _checked_assertions(
        target_kind=target_kind, target_id=target_id, assertions=assertions
    )
    fingerprint = _input_fingerprint_for_checked(target_kind, target_id, checked)
    facets: list[BookClassificationProjectionFacet] = []
    links: list[BookClassificationProjectionAssertionLink] = []
    for dimension in _DIMENSIONS:
        dimension_assertions = tuple(item for item in checked if item.dimension is dimension)
        facet, dimension_links = _reduce_facet(dimension, dimension_assertions)
        facets.append(facet)
        links.extend(dimension_links)
    status = ClassificationProjectionStatus.EMPTY if not checked else (
        ClassificationProjectionStatus.REVIEW_REQUIRED
        if any(facet.status is ClassificationFacetStatus.CONFLICT for facet in facets)
        else ClassificationProjectionStatus.PROJECTED
    )
    return BookClassificationProjection(
        id=classification_projection_id(
            target_kind=target_kind,
            target_id=target_id,
            projection_profile_version=BOOK_CLASSIFICATION_PROJECTION_PROFILE,
            input_fingerprint=fingerprint,
        ),
        target_kind=target_kind,
        target_id=target_id,
        assertion_profile_version=BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        projection_profile_version=BOOK_CLASSIFICATION_PROJECTION_PROFILE,
        input_fingerprint=fingerprint,
        status=status,
        facets=tuple(facets),
        assertion_links=tuple(sorted(links, key=lambda link: link.assertion_key)),
    )


def _reduce_facet(
    dimension: ClassificationDimension,
    assertions: tuple[BookClassificationAssertion, ...],
) -> tuple[
    BookClassificationProjectionFacet, tuple[BookClassificationProjectionAssertionLink, ...]
]:
    if not assertions:
        return (
            BookClassificationProjectionFacet(
                dimension=dimension, status=ClassificationFacetStatus.EMPTY
            ),
            (),
        )
    highest = max((item.lineage.priority_tier for item in assertions), key=_priority_rank)
    selected = tuple(item for item in assertions if item.lineage.priority_tier is highest)
    considered = tuple(item for item in assertions if item.lineage.priority_tier is not highest)
    distinct_values = tuple(sorted({(item.taxonomy, item.normalized_value) for item in selected}))
    conflict_code = _conflict_code(
        dimension=dimension, highest=highest, distinct_values=distinct_values
    )
    if conflict_code is not None:
        domain_conflict = dimension is ClassificationDimension.DOMAIN
        return (
            BookClassificationProjectionFacet(
                dimension=dimension,
                status=ClassificationFacetStatus.CONFLICT,
                conflict_code=conflict_code,
            ),
            tuple(
                BookClassificationProjectionAssertionLink(
                    assertion_id=item.id,
                    assertion_key=item.lineage.assertion_key,
                    role=(
                        ClassificationProjectionLinkRole.CONFLICTING
                        if not domain_conflict or item.lineage.priority_tier is highest
                        else ClassificationProjectionLinkRole.CONSIDERED
                    ),
                    conflict_code=(
                        conflict_code
                        if not domain_conflict or item.lineage.priority_tier is highest
                        else None
                    ),
                )
                for item in assertions
            ),
        )
    values = tuple(
        BookClassificationProjectionValue(
            ordinal=ordinal, taxonomy=taxonomy, normalized_value=normalized_value
        )
        for ordinal, (taxonomy, normalized_value) in enumerate(distinct_values)
    )
    links = tuple(
        BookClassificationProjectionAssertionLink(
            assertion_id=item.id,
            assertion_key=item.lineage.assertion_key,
            role=(
                ClassificationProjectionLinkRole.SELECTED
                if item.lineage.priority_tier is highest
                else ClassificationProjectionLinkRole.CONSIDERED
            ),
        )
        for item in (*selected, *considered)
    )
    return (
        BookClassificationProjectionFacet(
            dimension=dimension,
            status=ClassificationFacetStatus.PROJECTED,
            values=values,
        ),
        links,
    )


def _conflict_code(
    *,
    dimension: ClassificationDimension,
    highest: ClassificationPriorityTier,
    distinct_values: tuple[tuple[str, str], ...],
) -> ClassificationProjectionConflictCode | None:
    if dimension is ClassificationDimension.DOMAIN and len(distinct_values) > 1:
        return (
            ClassificationProjectionConflictCode.CONFIRMED_CONTRADICTION
            if highest is ClassificationPriorityTier.USER_CONFIRMED
            else ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES
        )
    if (
        dimension is not ClassificationDimension.DOMAIN
        and len(distinct_values) > _SET_VALUE_LIMITS[dimension]
    ):
        return ClassificationProjectionConflictCode.CARDINALITY_EXCEEDED
    return None


def _checked_assertions(
    *,
    target_kind: EntityKind,
    target_id: EntityId,
    assertions: Iterable[BookClassificationAssertion],
) -> tuple[BookClassificationAssertion, ...]:
    if target_kind not in {EntityKind.WORK, EntityKind.EDITION} or not isinstance(
        target_id, EntityId
    ):
        raise ClassificationProjectionError("projection target must be a book entity")
    checked = tuple(assertions)
    if any(not isinstance(item, BookClassificationAssertion) for item in checked):
        raise ClassificationProjectionError("projection inputs must be profiled book assertions")
    if any(item.target_kind is not target_kind or item.target_id != target_id for item in checked):
        raise ClassificationProjectionError("projection inputs must share the requested target")
    if any(
        item.lineage.assertion_profile_version != BOOK_CLASSIFICATION_ASSERTION_PROFILE
        for item in checked
    ):
        raise ClassificationProjectionError("projection inputs must use the v1 assertion profile")
    ordered = tuple(sorted(checked, key=lambda item: item.lineage.assertion_key))
    if len({item.lineage.assertion_key for item in ordered}) != len(ordered):
        raise ClassificationProjectionError("projection inputs must not repeat assertion keys")
    return ordered


def _input_fingerprint_for_checked(
    target_kind: EntityKind,
    target_id: EntityId,
    assertions: tuple[BookClassificationAssertion, ...],
) -> str:
    material = {
        "canonical_json_profile": BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE,
        "target_kind": target_kind.value,
        "target_id": str(target_id),
        "assertion_profile_version": BOOK_CLASSIFICATION_ASSERTION_PROFILE,
        "assertion_keys": [item.lineage.assertion_key for item in assertions],
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def _canonical_json(material: object) -> bytes:
    return json.dumps(material, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _priority_rank(tier: ClassificationPriorityTier) -> int:
    return 1 if tier is ClassificationPriorityTier.USER_CONFIRMED else 0


def _require_sha256(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
