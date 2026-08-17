import pytest

from foliotone.enrichment import (
    BookKnowledgeQuery,
    KnowledgeProviderMode,
    SyntheticBookKnowledgeProvider,
)


@pytest.mark.parametrize(
    ("mode", "expected_name", "expected_value"),
    [
        (KnowledgeProviderMode.OFFLINE, "OFFLINE", "offline"),
        (KnowledgeProviderMode.ONLINE, "ONLINE", "online"),
        (KnowledgeProviderMode.CACHE, "CACHE", "cache"),
    ],
)
def test_legacy_provider_mode_names_and_values_are_stable(
    mode: KnowledgeProviderMode,
    expected_name: str,
    expected_value: str,
) -> None:
    assert mode.name == expected_name
    assert mode.value == expected_value


def test_synthetic_provider_defaults_to_legacy_offline_mode() -> None:
    provider = SyntheticBookKnowledgeProvider()

    response = provider.fetch(BookKnowledgeQuery(title="Synthetic title"))

    assert provider.descriptor.default_mode is KnowledgeProviderMode.OFFLINE
    assert response.descriptor.default_mode is KnowledgeProviderMode.OFFLINE
    assert response.mode is KnowledgeProviderMode.OFFLINE
    assert response.as_privacy_dto()["mode"] == "offline"


@pytest.mark.parametrize(
    ("mode", "expected_value"),
    [
        (KnowledgeProviderMode.OFFLINE, "offline"),
        (KnowledgeProviderMode.ONLINE, "online"),
        (KnowledgeProviderMode.CACHE, "cache"),
    ],
)
def test_synthetic_provider_propagates_legacy_mode_to_response_and_privacy_dto(
    mode: KnowledgeProviderMode,
    expected_value: str,
) -> None:
    provider = SyntheticBookKnowledgeProvider(mode=mode)

    response = provider.fetch(BookKnowledgeQuery(title="Synthetic title"))

    assert provider.descriptor.default_mode is mode
    assert response.descriptor.default_mode is mode
    assert response.mode is mode
    assert response.as_privacy_dto()["mode"] == expected_value


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
