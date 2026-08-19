"""Synthetic integration matrix for the bounded Open Library provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

import foliotone.adapters.openlibrary.provider as provider_module
from foliotone.adapters.openlibrary import (
    AuthorSourceRecord,
    EditionSourceRecord,
    OpenLibraryBookProvider,
    OpenLibraryProviderResult,
    OpenLibraryResolvedAuthorQuery,
    OpenLibrarySourceEnvelope,
    OpenLibraryTransportResult,
    SearchSourceRecord,
    WorkSourceRecord,
    decode_openlibrary_source_dto,
    decode_openlibrary_source_dtos,
)
from foliotone.adapters.openlibrary.mapping import (
    PROVIDER_ADAPTER_VERSION,
    PROVIDER_ID,
    PROVIDER_SOURCE_VERSION,
)
from foliotone.core import EntityId
from foliotone.enrichment import (
    BookKnowledgeQuery,
    ProviderAccessMode,
    ProviderCacheContentSlot,
    ProviderCachePayloadKind,
    ProviderCachePolicy,
    ProviderCacheResultStatus,
    ProviderCacheRuntimeEntry,
    ProviderCacheRuntimeWrite,
    ProviderCacheSlots,
    provider_source_cache_key,
)

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)
WORK_QUERY = BookKnowledgeQuery("Synthetic", identifiers=(("openlibrary.work", "OL77W"),))
WORK_BINDINGS = {"openlibrary.work:OL77W": "target-work-77"}
WORK_BODY = b'{"key":"/works/OL77W","title":"Synthetic","bio":"RAW-ONLY-MARKER"}'


class FakeTransport:
    def __init__(self, *responses: OpenLibraryTransportResult) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def fetch(self, request: object) -> OpenLibraryTransportResult:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("transport request budget exceeded")
        return self.responses.pop(0)


class FailTransport:
    calls = 0

    def fetch(self, request: object) -> OpenLibraryTransportResult:
        self.calls += 1
        raise AssertionError("offline/fresh cache path reached transport")


class FakeCache:
    def __init__(self) -> None:
        self.entries: dict[str, ProviderCacheRuntimeEntry] = {}
        self.reads: list[str] = []
        self.writes: list[tuple[str, ProviderCacheSlots, object | None]] = []

    def get(self, source_cache_key: str) -> ProviderCacheRuntimeEntry | None:
        self.reads.append(source_cache_key)
        return self.entries.get(source_cache_key)

    def compare_and_replace(
        self,
        source_cache_key: str,
        *,
        slots: ProviderCacheSlots,
        payload: object | None,
        expected_generation: int,
    ) -> ProviderCacheRuntimeWrite:
        old = self.entries.get(source_cache_key)
        assert expected_generation == (old.generation if old is not None else 0)
        entry = ProviderCacheRuntimeEntry(expected_generation + 1, slots, payload)
        self.entries[source_cache_key] = entry
        self.writes.append((source_cache_key, slots, payload))
        return ProviderCacheRuntimeWrite(True, entry)


def success(body: bytes = WORK_BODY) -> OpenLibraryTransportResult:
    return OpenLibraryTransportResult(ProviderCacheResultStatus.SUCCESS, http_status=200, body=body)


def failure(
    status: ProviderCacheResultStatus, *, retry: datetime | None = None
) -> OpenLibraryTransportResult:
    return OpenLibraryTransportResult(
        status,
        http_status=429 if status is ProviderCacheResultStatus.RATE_LIMITED else 503,
        retry_after_at=retry,
    )


def make_provider(
    transport: object,
    *,
    cache: FakeCache | None = None,
    access: ProviderAccessMode = ProviderAccessMode.ONLINE_STRUCTURED,
    policy: ProviderCachePolicy = ProviderCachePolicy.REFRESH_IF_STALE,
) -> OpenLibraryBookProvider:
    return OpenLibraryBookProvider(
        access_mode=access,
        cache_policy=policy,
        transport=transport,  # type: ignore[arg-type]
        cache=cache,
    )


def fetch_work(provider: OpenLibraryBookProvider, *, at: datetime = NOW):
    return provider.fetch(WORK_QUERY, observed_at=at, target_bindings=WORK_BINDINGS)


def test_success_stores_only_canonical_normalized_v2_and_exact_positive_ttls() -> None:
    cache = FakeCache()
    transport = FakeTransport(success())

    result = fetch_work(make_provider(transport, cache=cache))

    assert result.status is ProviderCacheResultStatus.SUCCESS
    assert result.mapping is not None and len(result.mapping.identifiers) == 1
    assert len(transport.requests) == 1 and len(cache.writes) == 1
    _, slots, payload = cache.writes[0]
    content = slots.content_slot
    assert content is not None
    assert content.payload_kind is ProviderCachePayloadKind.NORMALIZED_SOURCE_DTO
    assert content.payload_codec == "json/openlibrary-source-dto-v2"
    assert content.content_fresh_until_at == NOW + timedelta(days=30)
    assert content.content_expires_at == NOW + timedelta(days=180)
    assert type(payload) is bytes and payload == content.payload_bytes
    assert b"RAW-ONLY-MARKER" not in payload
    assert decode_openlibrary_source_dto(payload).endpoint_kind == "WORK"


def test_lossless_canonical_decoder_matrix_covers_every_endpoint_and_multi_record() -> None:
    work_one = WorkSourceRecord("OL1W", "One", "2001", (), (), False)
    work_two = WorkSourceRecord("OL2W", None, None, (), (), False)
    edition = EditionSourceRecord(
        "OL3M",
        (),
        "Edition",
        None,
        None,
        (),
        (),
        (),
        ("9780306406157",),
        (),
        (),
        (),
        False,
    )
    author = AuthorSourceRecord("OL4A", "Person", (), None, None, False)
    search = SearchSourceRecord(work_one, (edition,), False, ("Person",))
    envelopes = (
        OpenLibrarySourceEnvelope("WORK", (work_one, work_two), 1, 0, True),
        OpenLibrarySourceEnvelope("EDITION", (edition,), 1, 0, True),
        OpenLibrarySourceEnvelope("AUTHOR", (author,), 1, 0, True),
        OpenLibrarySourceEnvelope("LEGACY_IDENTIFIER", (edition,), 1, 0, True),
        OpenLibrarySourceEnvelope("SEARCH", (search,), 1, 0, True),
    )
    for envelope in envelopes:
        canonical = json.dumps(
            envelope.as_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        decoded = decode_openlibrary_source_dto(canonical)
        assert decoded == envelope and decoded.as_payload() == envelope.as_payload()


def test_fresh_hit_and_offline_hit_never_reach_transport() -> None:
    cache = FakeCache()
    first = fetch_work(make_provider(FakeTransport(success()), cache=cache))
    sentinel = FailTransport()

    online = fetch_work(
        make_provider(sentinel, cache=cache, policy=ProviderCachePolicy.USE_IF_FRESH)
    )
    offline = fetch_work(
        make_provider(
            sentinel,
            cache=cache,
            access=ProviderAccessMode.OFFLINE,
            policy=ProviderCachePolicy.USE_IF_FRESH,
        )
    )

    assert first.mapping == online.mapping == offline.mapping
    assert sentinel.calls == 0


def test_offline_miss_returns_no_result_without_transport() -> None:
    sentinel = FailTransport()
    result = fetch_work(
        make_provider(
            sentinel,
            cache=FakeCache(),
            access=ProviderAccessMode.OFFLINE,
            policy=ProviderCachePolicy.USE_IF_FRESH,
        )
    )
    assert result.status is None and result.mapping is None and sentinel.calls == 0


@pytest.mark.parametrize(
    ("policy", "expected_calls", "expected_status"),
    (
        (ProviderCachePolicy.USE_IF_FRESH, 0, None),
        (ProviderCachePolicy.REFRESH_IF_STALE, 1, ProviderCacheResultStatus.SUCCESS),
        (ProviderCachePolicy.FORCE_REFRESH, 1, ProviderCacheResultStatus.SUCCESS),
    ),
)
def test_stale_behavior_is_owned_by_cache_policy(
    policy: ProviderCachePolicy,
    expected_calls: int,
    expected_status: ProviderCacheResultStatus | None,
) -> None:
    cache = FakeCache()
    initial = FakeTransport(success())
    result = fetch_work(make_provider(initial, cache=cache))
    assert result.source_cache_key is not None
    entry = cache.entries[result.source_cache_key]
    content = entry.slots.content_slot
    assert content is not None and type(entry.payload) is bytes
    stale = ProviderCacheContentSlot(
        content_status=content.content_status,
        payload_kind=content.payload_kind,
        payload_codec=content.payload_codec,
        payload_bytes=content.payload_bytes,
        payload_bytes_sha256=content.payload_bytes_sha256,
        content_http_status=content.content_http_status,
        content_fetched_at=NOW - timedelta(days=31),
        content_fresh_until_at=NOW,
        content_expires_at=NOW + timedelta(days=1),
    )
    cache.entries[result.source_cache_key] = ProviderCacheRuntimeEntry(
        entry.generation, ProviderCacheSlots(content_slot=stale), entry.payload
    )
    transport: FakeTransport | FailTransport = (
        FakeTransport(success()) if expected_calls else FailTransport()
    )

    refreshed = fetch_work(make_provider(transport, cache=cache, policy=policy))

    calls = len(transport.requests) if isinstance(transport, FakeTransport) else transport.calls
    assert calls == expected_calls and refreshed.status is expected_status


def test_not_found_has_exact_negative_ttls_and_no_payload() -> None:
    cache = FakeCache()
    result = fetch_work(make_provider(FakeTransport(success(b"{}")), cache=cache))
    assert result.status is ProviderCacheResultStatus.NOT_FOUND
    entry = next(iter(cache.entries.values()))
    content = entry.slots.content_slot
    assert content is not None and content.payload_kind is ProviderCachePayloadKind.NONE
    assert content.content_fresh_until_at == NOW + timedelta(hours=6)
    assert content.content_expires_at == NOW + timedelta(hours=24)
    assert entry.payload is None


@pytest.mark.parametrize(
    ("status", "ttl"),
    (
        (ProviderCacheResultStatus.TEMPORARY_FAILURE, timedelta(minutes=5)),
        (ProviderCacheResultStatus.PERMANENT_FAILURE, timedelta(hours=24)),
        (ProviderCacheResultStatus.INVALID_RESPONSE, timedelta(hours=1)),
    ),
)
def test_failure_ttls_are_exact_and_payload_free(
    status: ProviderCacheResultStatus, ttl: timedelta
) -> None:
    cache = FakeCache()
    result = fetch_work(make_provider(FakeTransport(failure(status)), cache=cache))
    assert result.status is status and result.mapping is None
    entry = next(iter(cache.entries.values()))
    failure_slot = entry.slots.failure_slot
    assert failure_slot is not None and failure_slot.failure_expires_at == NOW + ttl
    assert entry.payload is None


def test_rate_limit_expiry_and_retry_are_capped_at_24_hours() -> None:
    cache = FakeCache()
    result = fetch_work(
        make_provider(
            FakeTransport(
                failure(
                    ProviderCacheResultStatus.RATE_LIMITED,
                    retry=NOW + timedelta(days=2),
                )
            ),
            cache=cache,
        )
    )
    assert result.status is ProviderCacheResultStatus.RATE_LIMITED
    failure_slot = next(iter(cache.entries.values())).slots.failure_slot
    assert failure_slot is not None
    assert failure_slot.failure_retry_after_at == NOW + timedelta(hours=24)
    assert failure_slot.failure_expires_at == NOW + timedelta(hours=24)


def test_v1_and_v2_source_keys_are_isolated() -> None:
    cache = FakeCache()
    old_key = provider_source_cache_key(
        PROVIDER_ID,
        "openlibrary-book-adapter/v1",
        WORK_QUERY.fingerprint(),
        "openlibrary-web-api-docs-2026-08-19",
    )
    old_payload = b"v1-normalized-placeholder"
    old_slot = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.NORMALIZED_SOURCE_DTO,
        payload_codec="json/openlibrary-source-dto-v1",
        payload_bytes=old_payload,
        payload_bytes_sha256=sha256(old_payload).hexdigest(),
        content_fetched_at=NOW,
        content_fresh_until_at=NOW + timedelta(days=1),
        content_expires_at=NOW + timedelta(days=2),
    )
    cache.entries[old_key] = ProviderCacheRuntimeEntry(
        1, ProviderCacheSlots(content_slot=old_slot), old_payload
    )

    result = fetch_work(make_provider(FakeTransport(success()), cache=cache))

    expected = provider_source_cache_key(
        PROVIDER_ID,
        PROVIDER_ADAPTER_VERSION,
        WORK_QUERY.fingerprint(),
        PROVIDER_SOURCE_VERSION,
    )
    assert result.source_cache_key == expected != old_key
    assert set(cache.entries) == {old_key, expected}


def test_mapping_reanalysis_reuses_same_v2_source_without_fetch_and_changes_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    first = fetch_work(make_provider(FakeTransport(success()), cache=cache))
    sentinel = FailTransport()
    monkeypatch.setattr(provider_module, "MAPPING_PROFILE_VERSION", "openlibrary-book-mapping/v3")

    second = fetch_work(
        make_provider(sentinel, cache=cache, policy=ProviderCachePolicy.USE_IF_FRESH)
    )

    assert second.source_cache_key == first.source_cache_key
    assert second.mapping_input_key != first.mapping_input_key
    assert second.mapping == first.mapping and sentinel.calls == 0


def test_search_fetches_page_two_only_after_parsed_weak_page_one_and_combines_records() -> None:
    page_one = json.dumps({"numFound": 11, "start": 0, "docs": [{"key": "/works/OL1W"}]}).encode()
    page_two = json.dumps(
        {
            "num_found": 11,
            "start": 10,
            "docs": [
                {
                    "key": "/works/OL2W",
                    "editions": {"docs": [{"key": "/books/OL2M"}]},
                }
            ],
        }
    ).encode()
    transport = FakeTransport(success(page_one), success(page_two))
    cache = FakeCache()
    query = BookKnowledgeQuery("Synthetic", authors=("Resolved",))
    provider = make_provider(transport, cache=cache)

    result = provider.fetch(
        query,
        observed_at=NOW,
        target_bindings={
            "openlibrary.work:OL1W": "target-w1",
            "openlibrary.work:OL2W": "target-w2",
            "openlibrary.edition:OL2M": "target-m2",
        },
        resolved_author=OpenLibraryResolvedAuthorQuery(
            "Synthetic",
            "Resolved",
            EntityId.parse("00000000-0000-0000-0000-000000000001"),
        ),
    )

    assert result.status is ProviderCacheResultStatus.SUCCESS
    assert len(transport.requests) == 2
    assert [dict(request.query)["offset"] for request in transport.requests] == ["0", "10"]  # type: ignore[attr-defined]
    envelope = decode_openlibrary_source_dto(next(iter(cache.entries.values())).payload)
    assert envelope.endpoint_kind == "SEARCH" and len(envelope.records) == 2


def test_strong_search_page_one_stops_without_page_two_or_author() -> None:
    body = json.dumps(
        {
            "numFound": 11,
            "start": 0,
            "docs": [
                {
                    "key": "/works/OL3W",
                    "editions": {"docs": [{"key": "/books/OL3M"}]},
                }
            ],
        }
    ).encode()
    transport = FakeTransport(success(body))
    query = BookKnowledgeQuery("Synthetic", authors=("Resolved",))
    result = make_provider(transport, policy=ProviderCachePolicy.NO_CACHE).fetch(
        query,
        observed_at=NOW,
        target_bindings={
            "openlibrary.work:OL3W": "target-w3",
            "openlibrary.edition:OL3M": "target-m3",
        },
        resolved_author=OpenLibraryResolvedAuthorQuery(
            "Synthetic",
            "Resolved",
            EntityId.parse("00000000-0000-0000-0000-000000000002"),
        ),
    )
    assert result.status is ProviderCacheResultStatus.SUCCESS
    assert len(transport.requests) == 1


def test_direct_route_may_fetch_exactly_one_referenced_author_as_request_two() -> None:
    work = b'{"key":"/works/OL77W","authors":[{"author":{"key":"/authors/OL9A"}}]}'
    author = b'{"key":"/authors/OL9A","name":"Synthetic Person"}'
    transport = FakeTransport(success(work), success(author))
    cache = FakeCache()

    result = make_provider(transport, cache=cache).fetch(
        WORK_QUERY,
        observed_at=NOW,
        target_bindings={
            **WORK_BINDINGS,
            "openlibrary.author:OL9A": "target-agent-9",
        },
        referenced_author_olid="OL9A",
    )

    assert result.mapping is not None and len(transport.requests) == 2
    assert transport.requests[1].path == "/authors/OL9A.json"  # type: ignore[attr-defined]
    envelopes = tuple(
        decode_openlibrary_source_dto(entry.payload) for entry in cache.entries.values()
    )
    assert tuple(item.endpoint_kind for item in envelopes) == ("WORK", "AUTHOR")
    assert len(result.source_cache_keys) == len(result.mapping_input_keys) == 2
    assert all(b"Synthetic Person" not in repr(item).encode() for item in envelopes)


@pytest.mark.parametrize(("planned", "unresolved"), ((101, 0), (1, 1001)))
def test_bulk_thresholds_stop_before_query_or_transport(planned: int, unresolved: int) -> None:
    transport = FailTransport()
    result = make_provider(transport, policy=ProviderCachePolicy.NO_CACHE).fetch(
        WORK_QUERY,
        observed_at=NOW,
        target_bindings=WORK_BINDINGS,
        planned_lookup_count=planned,
        unresolved_record_count=unresolved,
    )
    assert result.bulk_dataset_required is True and transport.calls == 0


def test_decoder_rejects_noncanonical_v1_unknown_fields_and_wrong_types_path_safely() -> None:
    cache = FakeCache()
    result = fetch_work(make_provider(FakeTransport(success()), cache=cache))
    payload = next(iter(cache.entries.values())).payload
    assert type(payload) is bytes
    bad_values = (
        payload.replace(b"openlibrary-source-record/v2", b"openlibrary-source-record/v1"),
        payload.replace(b'"records":', b'"unknown":"C:\\\\private","records":'),
        payload.replace(b'"result_count":1', b'"result_count":true'),
        b" " + payload,
    )
    for bad in bad_values:
        with pytest.raises(ValueError) as raised:
            decode_openlibrary_source_dtos(bad)
        assert "private" not in str(raised.value)
    assert "Synthetic" not in repr(result) and "target-work-77" not in repr(result)


def test_target_bindings_are_explicit_and_path_safe_before_mapped_output() -> None:
    provider = make_provider(FakeTransport(success()), policy=ProviderCachePolicy.NO_CACHE)
    with pytest.raises(TypeError, match="target_bindings"):
        provider.fetch(WORK_QUERY, observed_at=NOW, target_bindings=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError) as raised:
        provider.fetch(
            WORK_QUERY,
            observed_at=NOW,
            target_bindings={"openlibrary.work:OL77W": "C:\\private\\book"},
        )
    assert "book" not in str(raised.value)


def test_provider_rejects_ambiguous_cache_configuration() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        OpenLibraryBookProvider(
            access_mode=ProviderAccessMode.ONLINE_STRUCTURED,
            cache_policy=ProviderCachePolicy.USE_IF_FRESH,
            transport=FakeTransport(success()),
            cache=FakeCache(),
            cache_factory=lambda _: FakeCache(),
        )


def test_provider_result_rejects_inconsistent_public_key_shape() -> None:
    digest = "a" * 64
    with pytest.raises(ValueError, match="first source_cache_keys"):
        OpenLibraryProviderResult(
            ProviderCacheResultStatus.SUCCESS,
            digest,
            None,
            None,
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        OpenLibraryProviderResult(
            ProviderCacheResultStatus.SUCCESS,
            "private-path",
            None,
            None,
            source_cache_keys=("private-path",),
        )
