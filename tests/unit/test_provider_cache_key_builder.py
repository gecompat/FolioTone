import hashlib
import json
import unicodedata

import pytest

import foliotone.enrichment as public_enrichment
from foliotone.enrichment import (
    provider_mapping_input_key,
    provider_mapping_input_key_bytes,
    provider_source_cache_key,
    provider_source_cache_key_bytes,
)
from foliotone.enrichment.contracts import (
    BOOK_KNOWLEDGE_QUERY_FINGERPRINT_DOMAIN,
    BookKnowledgeQuery,
)

_QUERY_FINGERPRINT_TEXT = (
    b"{\"authors\":[\"jane doe\",\"john doe\"],"
    b"\"domain\":\"foliotone:book-knowledge-query/v2\","
    b"\"identifiers\":[[\"isbn\",\"9783161484100\"],[\"lccn\",\"lccn001\"]],"
    b"\"title\":\"the great tale\"}"
)
_QUERY_FINGERPRINT_HASH = "2442c1289554731aebde2df4978a05fbd565d9446fdd4f2348744ed88c0d73b8"
assert _QUERY_FINGERPRINT_HASH == hashlib.sha256(_QUERY_FINGERPRINT_TEXT).hexdigest()

_SOURCE_CACHE_KEY_BYTES = (
    b"{\"domain\":\"foliotone:provider-source-cache-key/v1\","
    b"\"provider_adapter_version\":\"knowledge-provider/v1\","
    b"\"provider_id\":\"synthetic-book-knowledge\","
    b"\"provider_source_version\":\"knowledge-provider/v1\","
    b"\"query_fingerprint\":\"2442c1289554731aebde2df4978a05fbd565d9446fdd4f2348744ed88c0d73b8\"}"
)
_SOURCE_CACHE_KEY_HASH = (
    "60c291a663091a64a2af7e6a7cf4ff82b1038116f56df0e2e4ef1e44e9b42722"
)
_MAPPING_INPUT_KEY_BYTES = (
    b"{\"domain\":\"foliotone:provider-mapping-input-key/v1\","
    b"\"mapping_profile_version\":\"mapping-profile-v1\","
    b"\"provider_adapter_version\":\"knowledge-provider/v1\","
    b"\"provider_id\":\"synthetic-book-knowledge\","
    b"\"provider_source_version\":\"knowledge-provider/v1\","
    b"\"query_fingerprint\":\"2442c1289554731aebde2df4978a05fbd565d9446fdd4f2348744ed88c0d73b8\"}"
)
_MAPPING_INPUT_KEY_HASH = (
    "2a3ff8b8ce073c86faaa537de65ad20f3f77c1841b680ad139faaad959d1fd41"
)


def test_public_api_keeps_public_key_builders_minimal() -> None:
    exported_names = public_enrichment.__dict__.keys()
    assert "provider_source_cache_key_bytes" in exported_names
    assert "provider_source_cache_key" in exported_names
    assert "provider_mapping_input_key_bytes" in exported_names
    assert "provider_mapping_input_key" in exported_names
    assert "provider_source_cache_key_payload" not in exported_names
    assert "provider_mapping_input_key_payload" not in exported_names
    assert "build_provider_source_cache_key" not in exported_names
    assert "build_provider_mapping_input_key" not in exported_names
    assert "compute_provider_source_cache_key" not in exported_names
    assert "compute_provider_mapping_input_key" not in exported_names
    assert isinstance(
        provider_source_cache_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        ),
        bytes,
    )
    assert isinstance(
        provider_source_cache_key(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        ),
        str,
    )


def test_book_knowledge_query_keeps_legacy_visible_shape() -> None:
    query = BookKnowledgeQuery(
        title="  The Great Tale  ",
        authors=("john DOE", "  Jane Doe ", "john Doe"),
        identifiers=(("ISBN", "978-3-16-148410-0"), ("LCCN", "LCCN 001")),
    )

    assert query.title == "The Great Tale"
    assert query.authors == ("john doe", "jane doe", "john doe")
    assert query.identifiers == (("isbn", "9783161484100"), ("lccn", "lccn001"))


def test_book_knowledge_query_fingerprint_bytes_and_domain() -> None:
    query = BookKnowledgeQuery(
        title="The Great Tale",
        authors=("john doe", "jane doe", "john doe"),
        identifiers=(("lccn", "LCCN 001"), ("isbn", "9783161484100")),
    )

    assert query.normalized_title == "the great tale"
    assert query.fingerprint() == _QUERY_FINGERPRINT_HASH
    assert _QUERY_FINGERPRINT_TEXT == json.dumps(
        {
            "authors": ["jane doe", "john doe"],
            "domain": BOOK_KNOWLEDGE_QUERY_FINGERPRINT_DOMAIN,
            "identifiers": [["isbn", "9783161484100"], ["lccn", "lccn001"]],
            "title": "the great tale",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_book_knowledge_query_fingerprint_uses_sorted_sets() -> None:
    left = BookKnowledgeQuery(
        title="The Great Tale",
        authors=("john doe", "jane doe", "jane doe", "john doe"),
        identifiers=(
            ("lccn", "LCCN 001"),
            ("isbn", "9783161484100"),
            ("isbn", "978-3-16-148410-0"),
            ("isbn", "9783161484100"),
        ),
    )
    right = BookKnowledgeQuery(
        title="The Great Tale",
        authors=("jane doe", "john doe", "john doe"),
        identifiers=(("isbn", "9783161484100"), ("lccn", "lccn001"), ("isbn", "9783161484100")),
    )

    assert left.fingerprint() == right.fingerprint()


def test_book_knowledge_query_fingerprint_v2_avoids_legacy_delimiter_collision() -> None:
    left = BookKnowledgeQuery(title="a|b", authors=(), identifiers=())
    right = BookKnowledgeQuery(title="a", authors=("b|",), identifiers=())
    assert left.fingerprint() != right.fingerprint()


def test_book_knowledge_query_normalizes_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Café")
    composed = unicodedata.normalize("NFC", decomposed)
    left = BookKnowledgeQuery(
        title=decomposed,
        authors=("Jöhn Doe",),
        identifiers=(("isbn", "9783161484100"),),
    )
    right = BookKnowledgeQuery(
        title=composed,
        authors=("Jöhn Doe",),
        identifiers=(("isbn", "9783161484100"),),
    )
    assert left.fingerprint() == right.fingerprint()


def test_provider_source_cache_key_is_exact() -> None:
    assert (
        provider_source_cache_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        )
        == _SOURCE_CACHE_KEY_BYTES
    )
    assert (
        provider_source_cache_key(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        )
        == _SOURCE_CACHE_KEY_HASH
    )


def test_provider_mapping_input_key_is_exact() -> None:
    assert (
        provider_mapping_input_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
            mapping_profile_version="mapping-profile-v1",
        )
        == _MAPPING_INPUT_KEY_BYTES
    )
    assert (
        provider_mapping_input_key(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
            mapping_profile_version="mapping-profile-v1",
        )
        == _MAPPING_INPUT_KEY_HASH
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "other-book-provider"),
        ("provider_adapter_version", "knowledge-provider/v2"),
        ("provider_source_version", "knowledge-provider/v2"),
        ("query_fingerprint", "3" * 64),
    ],
)
def test_key_materiality_fields_affect_expected_cache_hashes(
    field: str, value: str
) -> None:
    base = {
        "provider_id": "synthetic-book-knowledge",
        "provider_adapter_version": "knowledge-provider/v1",
        "query_fingerprint": _QUERY_FINGERPRINT_HASH,
        "provider_source_version": "knowledge-provider/v1",
        "mapping_profile_version": "mapping-profile-v1",
    }
    variant = dict(base)
    variant[field] = value

    source_kwargs = dict(base)
    source_kwargs.pop("mapping_profile_version")
    source_variant = dict(variant)
    source_variant.pop("mapping_profile_version")

    assert provider_source_cache_key(**source_kwargs) != provider_source_cache_key(
        **source_variant
    )
    assert provider_mapping_input_key(**base) != provider_mapping_input_key(**variant)


def test_mapping_profile_only_influences_mapping_key_hash() -> None:
    base = {
        "provider_id": "synthetic-book-knowledge",
        "provider_adapter_version": "knowledge-provider/v1",
        "query_fingerprint": _QUERY_FINGERPRINT_HASH,
        "provider_source_version": "knowledge-provider/v1",
        "mapping_profile_version": "mapping-profile-v1",
    }
    changed_profile = dict(base)
    changed_profile["mapping_profile_version"] = "mapping-profile-v2"

    source_kwargs = dict(base)
    source_kwargs.pop("mapping_profile_version")
    changed_source_kwargs = dict(changed_profile)
    changed_source_kwargs.pop("mapping_profile_version")
    assert provider_source_cache_key(**source_kwargs) == provider_source_cache_key(
        **changed_source_kwargs
    )
    assert provider_mapping_input_key(**base) != provider_mapping_input_key(
        **changed_profile
    )


def test_provider_cache_key_bytes_fields_differ_between_source_and_mapping() -> None:
    assert b"\"mapping_profile_version\"" in _MAPPING_INPUT_KEY_BYTES
    assert b"\"mapping_profile_version\"" not in _SOURCE_CACHE_KEY_BYTES


@pytest.mark.parametrize(
    ("value", "field"),
    [
        (12.5, "provider_id"),
        (True, "provider_id"),
        (12.5, "provider_adapter_version"),
        (True, "provider_adapter_version"),
        (12.5, "provider_source_version"),
        (True, "provider_source_version"),
    ],
)
def test_provider_cache_key_builder_rejects_wrong_types_and_digest_shapes(
    value: object, field: str
) -> None:
    kwargs = {
        "provider_id": "synthetic-book-knowledge",
        "provider_adapter_version": "knowledge-provider/v1",
        "query_fingerprint": _QUERY_FINGERPRINT_HASH,
        "provider_source_version": "knowledge-provider/v1",
    }
    mapping_kwargs = kwargs.copy()
    mapping_kwargs["mapping_profile_version"] = "mapping-profile-v1"
    if field == "provider_id":
        kwargs["provider_id"] = value  # type: ignore[assignment]
        mapping_kwargs["provider_id"] = value  # type: ignore[assignment]
        with pytest.raises(ValueError, match="must be a"):
            provider_source_cache_key(**kwargs)
        with pytest.raises(ValueError, match="must be a"):
            provider_mapping_input_key(**mapping_kwargs)
    elif field == "provider_adapter_version":
        kwargs["provider_adapter_version"] = value  # type: ignore[assignment]
        mapping_kwargs["provider_adapter_version"] = value  # type: ignore[assignment]
        with pytest.raises(ValueError, match="must be"):
            provider_source_cache_key(**kwargs)
        with pytest.raises(ValueError, match="must be"):
            provider_mapping_input_key(**mapping_kwargs)
    elif field == "provider_source_version":
        kwargs["provider_source_version"] = value  # type: ignore[assignment]
        mapping_kwargs["provider_source_version"] = value  # type: ignore[assignment]
        with pytest.raises(ValueError, match="must be"):
            provider_source_cache_key(**kwargs)
        with pytest.raises(ValueError, match="must be"):
            provider_mapping_input_key(**mapping_kwargs)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("ABCDEF", "must be a lowercase SHA-256 hexadecimal digest"),
        (1234, "must be a non-empty string"),
        ("A" * 64, "must be a lowercase SHA-256 hexadecimal digest"),
    ],
)
def test_provider_cache_key_builder_rejects_bad_query_fingerprint(
    value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        provider_source_cache_key(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=value,  # type: ignore[arg-type]
            provider_source_version="knowledge-provider/v1",
        )


@pytest.mark.parametrize(
    "value",
    [
        "C:\\\\private",
        "/abs",
        "../",
        "a//b",
        "a/../b",
        "a b",
        "a\tb",
        "a\nb",
        "a:provider",
        r"json\raw",
    ],
)
def test_provider_cache_key_technical_components_reject_path_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        provider_source_cache_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version=value,
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        )
    with pytest.raises(ValueError):
        provider_source_cache_key_bytes(
            provider_id=value,
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
        )
    with pytest.raises(ValueError):
        provider_mapping_input_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version=value,
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
            mapping_profile_version="mapping-profile-v1",
        )
    with pytest.raises(ValueError):
        provider_mapping_input_key_bytes(
            provider_id="synthetic-book-knowledge",
            provider_adapter_version="knowledge-provider/v1",
            query_fingerprint=_QUERY_FINGERPRINT_HASH,
            provider_source_version="knowledge-provider/v1",
            mapping_profile_version=value,
        )


def test_book_knowledge_query_fingerprint_domain_is_v2() -> None:
    assert BOOK_KNOWLEDGE_QUERY_FINGERPRINT_DOMAIN == "foliotone:book-knowledge-query/v2"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "x" * 129),
        ("provider_adapter_version", "x" * 129),
        ("provider_source_version", "x" * 129),
        ("mapping_profile_version", "x" * 129),
    ],
)
def test_provider_cache_key_components_reject_oversized_inputs(
    field: str, value: str
) -> None:
    kwargs = {
        "provider_id": "synthetic-book-knowledge",
        "provider_adapter_version": "knowledge-provider/v1",
        "query_fingerprint": _QUERY_FINGERPRINT_HASH,
        "provider_source_version": "knowledge-provider/v1",
        "mapping_profile_version": "mapping-profile-v1",
    }
    source_kwargs = {
        "provider_id": "synthetic-book-knowledge",
        "provider_adapter_version": "knowledge-provider/v1",
        "query_fingerprint": _QUERY_FINGERPRINT_HASH,
        "provider_source_version": "knowledge-provider/v1",
    }
    mapping_kwargs = dict(kwargs)
    if field == "provider_id":
        source_kwargs["provider_id"] = value
        mapping_kwargs["provider_id"] = value
    elif field == "provider_adapter_version":
        source_kwargs["provider_adapter_version"] = value
        mapping_kwargs["provider_adapter_version"] = value
    elif field == "provider_source_version":
        source_kwargs["provider_source_version"] = value
        mapping_kwargs["provider_source_version"] = value
    else:
        mapping_kwargs["mapping_profile_version"] = value

    if field == "mapping_profile_version":
        with pytest.raises(ValueError, match="must not exceed 128 characters"):
            provider_mapping_input_key(**mapping_kwargs)
        return

    with pytest.raises(ValueError, match="must not exceed 128 characters"):
        provider_source_cache_key(**source_kwargs)
    with pytest.raises(ValueError, match="must not exceed 128 characters"):
        provider_mapping_input_key(**mapping_kwargs)
