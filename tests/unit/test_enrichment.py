from foliotone.enrichment import (
    BookKnowledgeQuery,
    SyntheticBookKnowledgeProvider,
)


def test_synthetic_book_provider_matches_title_and_author() -> None:
    provider = SyntheticBookKnowledgeProvider()
    query = BookKnowledgeQuery(
        title="The Great Tale",
        authors=("john doe",),
    )

    response = provider.fetch(query)

    assert response.query_fingerprint == query.fingerprint()
    assert response.results
    assert response.mode.value == "offline"

    first = response.results[0]
    keys = {dto.key for dto in first.dtos}
    assert keys == {"work.title", "agent.name"}


def test_synthetic_book_provider_matches_identifier() -> None:
    provider = SyntheticBookKnowledgeProvider()
    query = BookKnowledgeQuery(
        title="No title match",
        identifiers=(("isbn", "978-3-16-148410-0"),),
    )

    response = provider.fetch(query)

    assert response.results
    assert response.results[0].dtos[0].value == "Project Babel"


def test_privacy_dto_contains_no_absolute_paths() -> None:
    provider = SyntheticBookKnowledgeProvider()
    query = BookKnowledgeQuery(
        title="Project Babel",
        authors=("jane doe",),
    )

    response = provider.fetch(query)
    dto = response.as_privacy_dto()
    rendered = repr(dto).lower()

    assert "c:\\" not in rendered
    assert "provider_id" in dto
    assert dto["result_count"] == 1
