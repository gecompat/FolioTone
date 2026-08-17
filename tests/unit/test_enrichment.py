import pytest

from foliotone.enrichment import (
    BookKnowledgeQuery,
    KnowledgeProviderMode,
    ProviderAccessMode,
    ProviderCachePolicy,
    SyntheticBookKnowledgeProvider,
    provider_policy_from_legacy,
)
from foliotone.enrichment.contracts import validate_provider_policy


def test_provider_access_mode_literals_are_exact() -> None:
    assert {name: mode.value for name, mode in ProviderAccessMode.__members__.items()} == {
        "OFFLINE": "offline",
        "LOCAL_DATASETS": "local_datasets",
        "ONLINE_STRUCTURED": "online_structured",
        "ONLINE_WEB_RESEARCH": "online_web_research",
    }


def test_provider_cache_policy_literals_are_exact() -> None:
    assert {name: policy.value for name, policy in ProviderCachePolicy.__members__.items()} == {
        "USE_IF_FRESH": "use_if_fresh",
        "REFRESH_IF_STALE": "refresh_if_stale",
        "FORCE_REFRESH": "force_refresh",
        "NO_CACHE": "no_cache",
    }


@pytest.mark.parametrize(
    ("access_mode", "cache_policy"),
    [
        (access_mode, cache_policy)
        for access_mode in ProviderAccessMode
        for cache_policy in ProviderCachePolicy
        if not (
            access_mode is ProviderAccessMode.OFFLINE
            and cache_policy
            in {
                ProviderCachePolicy.REFRESH_IF_STALE,
                ProviderCachePolicy.FORCE_REFRESH,
            }
        )
    ],
)
def test_provider_policy_accepts_every_valid_combination(
    access_mode: ProviderAccessMode,
    cache_policy: ProviderCachePolicy,
) -> None:
    assert validate_provider_policy(access_mode, cache_policy) is None


@pytest.mark.parametrize(
    "cache_policy",
    [ProviderCachePolicy.REFRESH_IF_STALE, ProviderCachePolicy.FORCE_REFRESH],
)
def test_provider_policy_rejects_offline_source_refresh(
    cache_policy: ProviderCachePolicy,
) -> None:
    with pytest.raises(ValueError, match="offline access cannot request a source refresh"):
        validate_provider_policy(ProviderAccessMode.OFFLINE, cache_policy)


@pytest.mark.parametrize(
    ("access_mode", "cache_policy", "message"),
    [
        ("offline", ProviderCachePolicy.NO_CACHE, "access_mode must be a ProviderAccessMode"),
        (ProviderAccessMode.OFFLINE, "no_cache", "cache_policy must be a ProviderCachePolicy"),
    ],
)
def test_provider_policy_rejects_non_enum_inputs(
    access_mode: object,
    cache_policy: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_provider_policy(access_mode, cache_policy)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("legacy_mode", "expected_access_mode", "expected_cache_policy"),
    [
        (
            KnowledgeProviderMode.OFFLINE,
            ProviderAccessMode.OFFLINE,
            ProviderCachePolicy.NO_CACHE,
        ),
        (
            KnowledgeProviderMode.ONLINE,
            ProviderAccessMode.ONLINE_STRUCTURED,
            ProviderCachePolicy.NO_CACHE,
        ),
        (
            KnowledgeProviderMode.CACHE,
            ProviderAccessMode.OFFLINE,
            ProviderCachePolicy.USE_IF_FRESH,
        ),
    ],
)
def test_legacy_provider_mode_maps_to_exact_policy(
    legacy_mode: KnowledgeProviderMode,
    expected_access_mode: ProviderAccessMode,
    expected_cache_policy: ProviderCachePolicy,
) -> None:
    assert provider_policy_from_legacy(legacy_mode) == (
        expected_access_mode,
        expected_cache_policy,
    )


def test_legacy_provider_policy_mapping_rejects_non_enum_input() -> None:
    with pytest.raises(ValueError, match="mode must be a KnowledgeProviderMode"):
        provider_policy_from_legacy("offline")  # type: ignore[arg-type]


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
