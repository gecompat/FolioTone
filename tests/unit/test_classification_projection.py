from __future__ import annotations

from datetime import UTC, datetime

import pytest

from foliotone.classification import (
    BOOK_CLASSIFICATION_ASSERTION_NAMESPACE,
    BOOK_CLASSIFICATION_ASSERTION_PROFILE,
    BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE,
    BOOK_CLASSIFICATION_PROJECTION_PROFILE,
    BookClassificationAssertion,
    BookClassificationAssertionLineage,
    BookClassificationProjection,
    BookClassificationProjectionAssertionLink,
    BookClassificationProjectionFacet,
    BookClassificationProjectionValue,
    ClassificationDimension,
    ClassificationFacetStatus,
    ClassificationPriorityTier,
    ClassificationProjectionConflictCode,
    ClassificationProjectionLinkRole,
    ClassificationProjectionStatus,
    ClassificationSourceKind,
    ClassificationSourceReferenceKind,
    classification_assertion_id,
    classification_assertion_key,
    classification_projection_id,
    classification_projection_input_fingerprint,
    reduce_book_classification_assertions,
)
from foliotone.core import EntityId, EntityKind

_AT = datetime(2026, 8, 20, tzinfo=UTC)
_REFERENCE_A = "a" * 64
_REFERENCE_B = "b" * 64


def test_classification_package_exports_canonical_assertion_api() -> None:
    assert BOOK_CLASSIFICATION_ASSERTION_PROFILE == "book-classification-assertion/v1"
    assert BOOK_CLASSIFICATION_CANONICAL_JSON_PROFILE == "book-classification-canonical-json/v1"
    assert str(BOOK_CLASSIFICATION_ASSERTION_NAMESPACE) == "d3636547-6437-5d62-bf35-37a004008630"
    assert BookClassificationAssertion.__name__ == "BookClassificationAssertion"
    assert BookClassificationAssertionLineage.__name__ == "BookClassificationAssertionLineage"
    assert ClassificationSourceKind.LOCAL_DERIVED == "LOCAL_DERIVED"
    assert ClassificationSourceReferenceKind.LOCAL_RULE_RUN == "LOCAL_RULE_RUN"
    assert ClassificationPriorityTier.USER_CONFIRMED == "USER_CONFIRMED"
    assert callable(classification_assertion_key)
    assert callable(classification_assertion_id)


def _assertion(
    target_id: EntityId,
    dimension: ClassificationDimension,
    value: str,
    taxonomy: str = "local",
    reference: str = _REFERENCE_A,
    source_kind: ClassificationSourceKind = ClassificationSourceKind.LOCAL_DERIVED,
    confidence: float = 0.2,
) -> BookClassificationAssertion:
    return BookClassificationAssertion.create(
        target_kind=EntityKind.WORK,
        target_id=target_id,
        dimension=dimension,
        value=value,
        taxonomy=taxonomy,
        confidence=confidence,
        source_name="synthetic",
        source_version="v1",
        source_kind=source_kind,
        source_reference=reference,
        observed_at=_AT,
        created_at=_AT,
    )


def test_reducer_projects_the_exact_seven_facets_and_is_order_independent() -> None:
    target_id = EntityId.parse("11111111-1111-1111-1111-111111111111")
    assertions = (
        _assertion(target_id, ClassificationDimension.DOMAIN, "Fiction"),
        _assertion(target_id, ClassificationDimension.GENRE, "Fantasy", reference=_REFERENCE_B),
        _assertion(target_id, ClassificationDimension.SUBGENRE, "Epic fantasy", reference="c" * 64),
        _assertion(target_id, ClassificationDimension.TOPIC, "Dragons", reference="d" * 64),
        _assertion(target_id, ClassificationDimension.AUDIENCE, "Adult", reference="e" * 64),
        _assertion(target_id, ClassificationDimension.LANGUAGE, "EN", reference="f" * 64),
        _assertion(target_id, ClassificationDimension.FORM, "Novel", reference="1" * 64),
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=reversed(assertions)
    )

    assert projection.status is ClassificationProjectionStatus.PROJECTED
    assert projection.projection_profile_version == BOOK_CLASSIFICATION_PROJECTION_PROFILE
    assert tuple(facet.dimension for facet in projection.facets) == tuple(ClassificationDimension)
    assert all(facet.status is ClassificationFacetStatus.PROJECTED for facet in projection.facets)
    assert projection.input_fingerprint == classification_projection_input_fingerprint(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=assertions
    )
    assert projection == reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=assertions
    )


def test_reducer_coalesces_equal_values_and_retains_every_assertion_link() -> None:
    target_id = EntityId.parse("22222222-2222-2222-2222-222222222222")
    first = _assertion(target_id, ClassificationDimension.GENRE, "Fantasy", reference=_REFERENCE_A)
    second = _assertion(
        target_id, ClassificationDimension.GENRE, " fantasy ", reference=_REFERENCE_B
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=(second, first)
    )
    genre = next(
        facet for facet in projection.facets if facet.dimension is ClassificationDimension.GENRE
    )

    assert genre.values[0].taxonomy == "local"
    assert genre.values[0].normalized_value == "fantasy"
    assert len(genre.values) == 1
    assert {link.assertion_key for link in projection.assertion_links} == {
        first.lineage.assertion_key,
        second.lineage.assertion_key,
    }
    assert {link.role for link in projection.assertion_links} == {
        ClassificationProjectionLinkRole.SELECTED
    }


@pytest.mark.parametrize(
    ("dimension", "limit"),
    [
        (ClassificationDimension.GENRE, 8),
        (ClassificationDimension.SUBGENRE, 16),
        (ClassificationDimension.TOPIC, 32),
        (ClassificationDimension.AUDIENCE, 8),
        (ClassificationDimension.LANGUAGE, 8),
        (ClassificationDimension.FORM, 8),
    ],
)
def test_reducer_accepts_each_exact_set_value_limit(
    dimension: ClassificationDimension, limit: int
) -> None:
    target_id = EntityId.new()
    assertions = tuple(
        _assertion(target_id, dimension, f"value {index}", reference=f"{index:064x}")
        for index in range(limit)
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=assertions
    )

    facet = next(facet for facet in projection.facets if facet.dimension is dimension)
    assert len(facet.values) == limit


def test_reducer_keeps_user_confirmed_value_and_marks_lower_tier_considered() -> None:
    target_id = EntityId.new()
    automated = _assertion(target_id, ClassificationDimension.DOMAIN, "fiction")
    confirmed = _assertion(
        target_id,
        ClassificationDimension.DOMAIN,
        "nonfiction",
        source_kind=ClassificationSourceKind.USER_CONFIRMED,
        reference="33333333-3333-3333-3333-333333333333",
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=(automated, confirmed)
    )

    domain = next(
        facet for facet in projection.facets if facet.dimension is ClassificationDimension.DOMAIN
    )
    assert domain.values[0].normalized_value == "nonfiction"
    roles = {link.assertion_key: link.role for link in projection.assertion_links}
    assert roles[confirmed.lineage.assertion_key] is ClassificationProjectionLinkRole.SELECTED
    assert roles[automated.lineage.assertion_key] is ClassificationProjectionLinkRole.CONSIDERED


def test_reducer_retains_automated_domain_conflict_for_review() -> None:
    target_id = EntityId.new()
    first = _assertion(
        target_id, ClassificationDimension.DOMAIN, "fiction", confidence=0.01
    )
    second = _assertion(
        target_id,
        ClassificationDimension.DOMAIN,
        "nonfiction",
        reference=_REFERENCE_B,
        confidence=1.0,
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=(first, second)
    )

    domain = next(
        facet for facet in projection.facets if facet.dimension is ClassificationDimension.DOMAIN
    )
    assert projection.status is ClassificationProjectionStatus.REVIEW_REQUIRED
    assert domain.status is ClassificationFacetStatus.CONFLICT
    assert domain.conflict_code is ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES
    assert not domain.values
    assert {
        (link.assertion_key, link.role, link.conflict_code) for link in projection.assertion_links
    } == {
        (
            first.lineage.assertion_key,
            ClassificationProjectionLinkRole.CONFLICTING,
            ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES,
        ),
        (
            second.lineage.assertion_key,
            ClassificationProjectionLinkRole.CONFLICTING,
            ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES,
        ),
    }


def test_reducer_marks_conflicting_confirmed_domains_as_confirmed_contradiction() -> None:
    target_id = EntityId.new()
    fiction = _assertion(
        target_id,
        ClassificationDimension.DOMAIN,
        "fiction",
        source_kind=ClassificationSourceKind.USER_CONFIRMED,
        reference="11111111-1111-1111-1111-111111111111",
    )
    nonfiction = _assertion(
        target_id,
        ClassificationDimension.DOMAIN,
        "nonfiction",
        source_kind=ClassificationSourceKind.USER_CONFIRMED,
        reference="22222222-2222-2222-2222-222222222222",
    )
    lower_tier = _assertion(
        target_id,
        ClassificationDimension.DOMAIN,
        "fiction",
        reference=_REFERENCE_A,
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK,
        target_id=target_id,
        assertions=(fiction, nonfiction, lower_tier),
    )

    domain = next(
        facet for facet in projection.facets if facet.dimension is ClassificationDimension.DOMAIN
    )
    assert domain.conflict_code is ClassificationProjectionConflictCode.CONFIRMED_CONTRADICTION
    roles = {
        link.assertion_key: (link.role, link.conflict_code)
        for link in projection.assertion_links
    }
    assert roles[fiction.lineage.assertion_key] == (
        ClassificationProjectionLinkRole.CONFLICTING,
        ClassificationProjectionConflictCode.CONFIRMED_CONTRADICTION,
    )
    assert roles[nonfiction.lineage.assertion_key] == (
        ClassificationProjectionLinkRole.CONFLICTING,
        ClassificationProjectionConflictCode.CONFIRMED_CONTRADICTION,
    )
    assert roles[lower_tier.lineage.assertion_key] == (
        ClassificationProjectionLinkRole.CONSIDERED,
        None,
    )


def test_reducer_retains_all_inputs_when_set_cardinality_overflows() -> None:
    target_id = EntityId.new()
    assertions = tuple(
        _assertion(
            target_id,
            ClassificationDimension.GENRE,
            f"genre {index}",
            reference=f"{index:064x}",
        )
        for index in range(9)
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=assertions
    )

    genre = next(
        facet for facet in projection.facets if facet.dimension is ClassificationDimension.GENRE
    )
    assert projection.status is ClassificationProjectionStatus.REVIEW_REQUIRED
    assert genre.status is ClassificationFacetStatus.CONFLICT
    assert genre.conflict_code is ClassificationProjectionConflictCode.CARDINALITY_EXCEEDED
    assert not genre.values
    assert {link.assertion_key for link in projection.assertion_links} == {
        item.lineage.assertion_key for item in assertions
    }
    assert all(
        link.role is ClassificationProjectionLinkRole.CONFLICTING
        and link.conflict_code is ClassificationProjectionConflictCode.CARDINALITY_EXCEEDED
        for link in projection.assertion_links
    )


def test_reducer_does_not_invent_cross_dimension_conflicts() -> None:
    target_id = EntityId.new()
    assertions = (
        _assertion(target_id, ClassificationDimension.DOMAIN, "fiction"),
        _assertion(
            target_id,
            ClassificationDimension.TOPIC,
            "computer science",
            reference=_REFERENCE_B,
        ),
        _assertion(
            target_id,
            ClassificationDimension.FORM,
            "technical reference",
            reference="c" * 64,
        ),
    )

    projection = reduce_book_classification_assertions(
        target_kind=EntityKind.WORK, target_id=target_id, assertions=assertions
    )

    assert projection.status is ClassificationProjectionStatus.PROJECTED
    assert all(
        facet.status is not ClassificationFacetStatus.CONFLICT for facet in projection.facets
    )


def test_facet_constructor_enforces_sum_type_and_unique_values() -> None:
    value = BookClassificationProjectionValue(
        ordinal=0, taxonomy="local", normalized_value="fiction"
    )

    with pytest.raises(ValueError, match="empty facets"):
        BookClassificationProjectionFacet(
            dimension=ClassificationDimension.DOMAIN,
            status=ClassificationFacetStatus.EMPTY,
            values=(value,),
        )
    with pytest.raises(ValueError, match="projected facets"):
        BookClassificationProjectionFacet(
            dimension=ClassificationDimension.DOMAIN,
            status=ClassificationFacetStatus.PROJECTED,
        )
    with pytest.raises(ValueError, match="conflict facets"):
        BookClassificationProjectionFacet(
            dimension=ClassificationDimension.DOMAIN,
            status=ClassificationFacetStatus.CONFLICT,
        )
    with pytest.raises(ValueError, match="unique"):
        BookClassificationProjectionFacet(
            dimension=ClassificationDimension.GENRE,
            status=ClassificationFacetStatus.PROJECTED,
            values=(
                value,
                BookClassificationProjectionValue(
                    ordinal=1, taxonomy="local", normalized_value="fiction"
                ),
            ),
        )


def test_assertion_link_constructor_enforces_conflict_sum_type() -> None:
    assertion_id = EntityId.new()

    with pytest.raises(ValueError, match="conflicting links"):
        BookClassificationProjectionAssertionLink(
            assertion_id=assertion_id,
            assertion_key="a" * 64,
            role=ClassificationProjectionLinkRole.CONFLICTING,
        )
    with pytest.raises(ValueError, match="selected and considered"):
        BookClassificationProjectionAssertionLink(
            assertion_id=assertion_id,
            assertion_key="a" * 64,
            role=ClassificationProjectionLinkRole.SELECTED,
            conflict_code=ClassificationProjectionConflictCode.MULTIPLE_EXCLUSIVE_VALUES,
        )


def test_projection_constructor_enforces_status_and_canonical_link_order() -> None:
    target_id = EntityId.new()
    fingerprint = "a" * 64
    projection_id = classification_projection_id(
        target_kind=EntityKind.WORK,
        target_id=target_id,
        projection_profile_version=BOOK_CLASSIFICATION_PROJECTION_PROFILE,
        input_fingerprint=fingerprint,
    )
    empty_facets = tuple(
        BookClassificationProjectionFacet(
            dimension=dimension, status=ClassificationFacetStatus.EMPTY
        )
        for dimension in ClassificationDimension
    )
    unordered_links = (
        BookClassificationProjectionAssertionLink(
            assertion_id=EntityId.new(),
            assertion_key="b" * 64,
            role=ClassificationProjectionLinkRole.CONSIDERED,
        ),
        BookClassificationProjectionAssertionLink(
            assertion_id=EntityId.new(),
            assertion_key="a" * 64,
            role=ClassificationProjectionLinkRole.CONSIDERED,
        ),
    )

    with pytest.raises(ValueError, match="canonical ordering"):
        _projection(
            projection_id=projection_id,
            target_id=target_id,
            fingerprint=fingerprint,
            status=ClassificationProjectionStatus.EMPTY,
            facets=empty_facets,
            links=unordered_links,
        )
    with pytest.raises(ValueError, match="empty projections"):
        _projection(
            projection_id=projection_id,
            target_id=target_id,
            fingerprint=fingerprint,
            status=ClassificationProjectionStatus.EMPTY,
            facets=empty_facets,
            links=tuple(reversed(unordered_links)),
        )
    with pytest.raises(ValueError, match="projected projections"):
        _projection(
            projection_id=projection_id,
            target_id=target_id,
            fingerprint=fingerprint,
            status=ClassificationProjectionStatus.PROJECTED,
            facets=empty_facets,
            links=(),
        )


def _projection(
    *,
    projection_id: EntityId,
    target_id: EntityId,
    fingerprint: str,
    status: ClassificationProjectionStatus,
    facets: tuple[BookClassificationProjectionFacet, ...],
    links: tuple[BookClassificationProjectionAssertionLink, ...],
) -> BookClassificationProjection:
    return BookClassificationProjection(
        id=projection_id,
        target_kind=EntityKind.WORK,
        target_id=target_id,
        assertion_profile_version="book-classification-assertion/v1",
        projection_profile_version=BOOK_CLASSIFICATION_PROJECTION_PROFILE,
        input_fingerprint=fingerprint,
        status=status,
        facets=facets,
        assertion_links=links,
    )
