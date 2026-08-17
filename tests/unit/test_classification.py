from foliotone.classification import (
    BookClassificationFacet,
    BookClassificationQuery,
    BookClassificationSet,
    ClassificationDimension,
    build_classification_assertions,
    make_classification_dto,
)
from foliotone.core import EntityId, EntityKind


def test_query_builds_expected_facets() -> None:
    query = BookClassificationQuery(
        domain="Fiction",
        genre="Fantasy",
        topic="   Dragons   and   magic  ",
        audience=None,
        language="EN",
        form="Ebook",
        confidence=0.84,
    )

    facets = query.facets()

    assert len(facets) == 5
    assert facets[0].dimension == ClassificationDimension.DOMAIN
    assert facets[0].value == "fiction"
    assert facets[2].dimension == ClassificationDimension.TOPIC
    assert facets[2].value == "dragons and magic"
    assert facets[3].dimension == ClassificationDimension.LANGUAGE
    assert facets[3].value == "en"


def test_build_classification_assertions_emits_persistence_records() -> None:
    classification_set = BookClassificationSet(
        target_kind=EntityKind.WORK,
        target_id=EntityId.new(),
        facets=(
            BookClassificationFacet(
                dimension=ClassificationDimension.GENRE,
                value="Sci-Fi",
                taxonomy="lcc",
                confidence=0.9,
            ),
            BookClassificationFacet(
                dimension=ClassificationDimension.AUDIENCE,
                value="adult",
                taxonomy="internal",
                confidence=0.65,
            ),
        ),
        source_name="classifier-unit",
        source_version="unit-test",
    )
    assertions = build_classification_assertions(classification_set)

    assert len(assertions) == 2
    assert {item.dimension for item in assertions} == {"genre", "audience"}
    assert {item.taxonomy for item in assertions} == {"lcc", "internal"}
    assert assertions[0].provenance.source_name == "classifier-unit"


def test_make_classification_dto_is_privacy_safe() -> None:
    dto = make_classification_dto(
        BookClassificationFacet(
            dimension=ClassificationDimension.FORM,
            value="Hardcover",
            taxonomy="local",
        )
    )

    assert dto["dimension"] == "form"
    assert dto["value"] == "hardcover"
    assert "source_version" not in dto
