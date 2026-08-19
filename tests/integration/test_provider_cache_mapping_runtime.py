"""Integration tests for provider cache mapping reanalysis and cache-store adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from foliotone.enrichment import (
    ProviderAccessMode,
    ProviderCacheLimits,
    ProviderCacheMappingRuntime,
    ProviderCachePayloadKind,
    ProviderCachePolicy,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    provider_mapping_input_key,
    provider_source_cache_key,
)
from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
)
from foliotone.enrichment.provider_cache_runtime import (
    ProviderCachePort,
    ProviderCacheRuntime,
    ProviderCacheRuntimeEntry,
    ProviderCacheRuntimeWrite,
    ProviderCacheTransportResult,
)
from foliotone.persistence import create_sqlite_engine
from foliotone.persistence.provider_cache_store import (
    ProviderCacheStorePort,
    SQLiteProviderCacheStore,
)

_NOW = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
_FRESH_UNTIL = _NOW + timedelta(minutes=5)
_EXPIRES = _NOW + timedelta(minutes=10)

_PROVIDER_ID = "synthetic-book-knowledge"
_PROVIDER_ADAPTER_VERSION = "knowledge-provider/v1"
_PROVIDER_SOURCE_VERSION = "source-mapping-profile/v1"
_QUERY_FINGERPRINT = sha256(b"seb03a-09-query").hexdigest()


SeedFunction = Callable[[Path], str]


def _source_cache_key() -> str:
    return provider_source_cache_key(
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
    )


def _mapping_input_key(version: str) -> str:
    return provider_mapping_input_key(
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        mapping_profile_version=version,
    )


def _limits() -> ProviderCacheLimits:
    return ProviderCacheLimits(
        max_entry_payload_bytes=128,
        max_entries_total=8,
        max_payload_bytes_total=1024,
        expired_prune_batch_size=8,
    )


def _store_and_port(
    head_database: Path,
) -> tuple[SQLiteProviderCacheStore, ProviderCacheStorePort]:
    store = SQLiteProviderCacheStore(
        create_sqlite_engine(head_database),
        _limits(),
    )
    return store, ProviderCacheStorePort(
        store=store,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
    )


def _success_content_slot(payload: bytes) -> ProviderCacheContentSlot:
    return ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_http_status=200,
        content_fetched_at=_NOW,
        content_fresh_until_at=_FRESH_UNTIL,
        content_expires_at=_EXPIRES,
    )


def _not_found_content_slot() -> ProviderCacheContentSlot:
    return ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.NOT_FOUND,
        payload_kind=ProviderCachePayloadKind.NONE,
        content_fetched_at=_NOW,
        content_fresh_until_at=_FRESH_UNTIL,
        content_expires_at=_EXPIRES,
    )


def _not_found_raw_response_content_slot(payload: bytes) -> ProviderCacheContentSlot:
    return ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.NOT_FOUND,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_http_status=404,
        content_fetched_at=_NOW,
        content_fresh_until_at=_FRESH_UNTIL,
        content_expires_at=_EXPIRES,
    )


def _failure_slot(
    status: ProviderCacheResultStatus = ProviderCacheResultStatus.RATE_LIMITED,
    *,
    active_retry: bool = True,
) -> ProviderCacheFailureSlot:
    return ProviderCacheFailureSlot(
        failure_status=status,
        failure_http_status=429,
        failure_at=_NOW,
        failure_retry_after_at=_NOW + timedelta(minutes=1)
        if active_retry
        else None,
        failure_expires_at=_NOW + timedelta(minutes=5),
    )


def _seed_success_cache(
    head_database: Path,
    payload: bytes = b"cached-payload",
) -> str:
    _, port = _store_and_port(head_database)
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(content_slot=_success_content_slot(payload)),
        payload=payload,
        expected_generation=0,
    )
    return _source_cache_key()


def _seed_expired_cache(
    head_database: Path,
    payload: bytes = b"expired-payload",
) -> str:
    expired_slot = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_http_status=200,
        content_fetched_at=_NOW - timedelta(minutes=20),
        content_fresh_until_at=_NOW - timedelta(minutes=10),
        content_expires_at=_NOW - timedelta(minutes=1),
    )
    _, port = _store_and_port(head_database)
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(content_slot=expired_slot),
        payload=payload,
        expected_generation=0,
    )
    return _source_cache_key()


def _seed_not_found_cache(head_database: Path) -> str:
    _, port = _store_and_port(head_database)
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(content_slot=_not_found_content_slot()),
        payload=None,
        expected_generation=0,
    )
    return _source_cache_key()


def _seed_not_found_raw_response_cache(
    head_database: Path,
    payload: bytes = b"mapped-not-found-payload",
) -> str:
    _, port = _store_and_port(head_database)
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(
            content_slot=_not_found_raw_response_content_slot(payload)
        ),
        payload=payload,
        expected_generation=0,
    )
    return _source_cache_key()


def _seed_technical_failure_cache(
    head_database: Path,
    active_retry: bool = True,
) -> str:
    _, port = _store_and_port(head_database)
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(failure_slot=_failure_slot(active_retry=active_retry)),
        payload=None,
        expected_generation=0,
    )
    return _source_cache_key()


def _transport(
    payload: bytes = b"fallback-payload",
    status: ProviderCacheResultStatus = ProviderCacheResultStatus.SUCCESS,
) -> _Transport:
    if status is ProviderCacheResultStatus.NOT_FOUND:
        slot = _not_found_raw_response_content_slot(payload)
        return _Transport(
            ProviderCacheTransportResult(
                source_status=status,
                slots=ProviderCacheSlots(content_slot=slot),
                payload=payload,
            ),
        )
    if status in {
        ProviderCacheResultStatus.SUCCESS,
        ProviderCacheResultStatus.TEMPORARY_FAILURE,
        ProviderCacheResultStatus.RATE_LIMITED,
        ProviderCacheResultStatus.PERMANENT_FAILURE,
        ProviderCacheResultStatus.INVALID_RESPONSE,
    }:
        if status is ProviderCacheResultStatus.SUCCESS:
            slots = ProviderCacheSlots(content_slot=_success_content_slot(payload))
            return _Transport(
                ProviderCacheTransportResult(
                    source_status=status,
                    slots=slots,
                    payload=payload,
                ),
            )
        if status in {
            ProviderCacheResultStatus.RATE_LIMITED,
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
            ProviderCacheResultStatus.PERMANENT_FAILURE,
            ProviderCacheResultStatus.INVALID_RESPONSE,
        }:
            slots = ProviderCacheSlots(
                failure_slot=_failure_slot(status, active_retry=False)
            )
            return _Transport(
                ProviderCacheTransportResult(
                    source_status=status,
                    slots=slots,
                    payload=None,
                ),
            )
        raise ValueError("unsupported status for transport helper")

    raise ValueError("unsupported status for transport helper")


def _runtime_for(policy: ProviderCachePolicy) -> ProviderCacheRuntime:
    return ProviderCacheRuntime(
        access_mode=ProviderAccessMode.ONLINE_STRUCTURED,
        cache_policy=policy,
    )


def _runtime() -> ProviderCacheRuntime:
    return _runtime_for(ProviderCachePolicy.USE_IF_FRESH)


class _Transport:
    def __init__(self, result: ProviderCacheTransportResult) -> None:
        self.calls = 0
        self._result = result

    def fetch(self) -> ProviderCacheTransportResult:
        self.calls += 1
        return self._result


class _Mapper:
    def __init__(self, expected_source_payload: bytes) -> None:
        self.calls = 0
        self._payload = expected_source_payload

    def __call__(self, payload: object) -> str:
        self.calls += 1
        assert payload == self._payload
        return f"mapped:{self._payload.decode('utf-8')}"


class _SpyPort(ProviderCachePort):
    def __init__(self, delegate: ProviderCachePort) -> None:
        self._delegate = delegate
        self.reads = 0
        self.writes = 0

    def get(self, source_cache_key: str) -> ProviderCacheRuntimeEntry | None:
        self.reads += 1
        return self._delegate.get(source_cache_key)

    def compare_and_replace(
        self,
        source_cache_key: str,
        *,
        slots: ProviderCacheSlots,
        payload: object | None,
        expected_generation: int,
    ) -> ProviderCacheRuntimeWrite:
        self.writes += 1
        return self._delegate.compare_and_replace(
            source_cache_key,
            slots=slots,
            payload=payload,
            expected_generation=expected_generation,
        )


def test_mapping_runtime_remaps_per_profile_without_cache_or_fetch(
    head_database: Path,
) -> None:
    _seed_success_cache(head_database)
    _, delegate = _store_and_port(head_database)
    spy = _SpyPort(delegate)
    mapper_payload = b"cached-payload"
    mapper = _Mapper(mapper_payload)
    runtime = ProviderCacheMappingRuntime(runtime=_runtime())
    transport_v1 = _transport(mapper_payload)
    transport_v2 = _transport(mapper_payload)

    first = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=spy,
        transport=transport_v1,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )
    second = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=spy,
        transport=transport_v2,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v2",
        mapper=mapper,
    )

    assert first.source_status is ProviderCacheResultStatus.SUCCESS
    assert first.source_payload == mapper_payload
    assert first.mapped_payload == "mapped:cached-payload"
    assert first.mapping_input_key == _mapping_input_key("mapping-profile-v1")
    assert second.mapping_input_key == _mapping_input_key("mapping-profile-v2")
    assert first.mapped_payload == second.mapped_payload
    assert spy.reads == 2
    assert spy.writes == 0
    assert mapper.calls == 2
    assert transport_v1.calls == 0
    assert transport_v2.calls == 0


def test_mapping_runtime_no_same_version_memoization_and_no_transport_in_miss_hit_cycle(
    head_database: Path,
) -> None:
    _seed_success_cache(head_database)
    _, delegate = _store_and_port(head_database)
    spy = _SpyPort(delegate)
    mapper = _Mapper(b"cached-payload")
    runtime = ProviderCacheMappingRuntime(runtime=_runtime())
    transport_first = _transport()
    transport_second = _transport()
    first = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=spy,
        transport=transport_first,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )
    second = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=spy,
        transport=transport_second,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert first.mapping_input_key == second.mapping_input_key == _mapping_input_key(
        "mapping-profile-v1"
    )
    assert first.mapped_payload == second.mapped_payload
    assert mapper.calls == 2
    assert spy.reads == 2
    assert spy.writes == 0
    assert transport_first.calls == 0
    assert transport_second.calls == 0


def test_mapping_runtime_maps_fresh_not_found_raw_response_payload(
    head_database: Path,
) -> None:
    source_payload = b"mapped-not-found-payload"
    _seed_not_found_raw_response_cache(head_database, payload=source_payload)
    _, port = _store_and_port(head_database)
    transport = _transport()
    mapper = _Mapper(source_payload)
    runtime = ProviderCacheMappingRuntime(runtime=_runtime())
    result = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=port,
        transport=transport,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert result.source_status is ProviderCacheResultStatus.NOT_FOUND
    assert result.source_payload == source_payload
    assert result.mapped_payload == "mapped:mapped-not-found-payload"
    assert result.mapping_input_key == _mapping_input_key("mapping-profile-v1")
    assert transport.calls == 0
    assert mapper.calls == 1


def test_mapping_runtime_does_not_map_not_found_none_payload(
    head_database: Path,
) -> None:
    _seed_not_found_cache(head_database)
    transport = _transport()
    _, port = _store_and_port(head_database)
    mapper = _Mapper(b"no-payload")
    runtime = ProviderCacheMappingRuntime(runtime=_runtime())
    result = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=port,
        transport=transport,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert result.source_status is ProviderCacheResultStatus.NOT_FOUND
    assert result.source_payload is None
    assert result.mapped_payload is None
    assert result.mapping_input_key is None
    assert transport.calls == 0
    assert mapper.calls == 0


def test_mapping_runtime_refresh_if_stale_technical_failure_keeps_content_and_payload(
    head_database: Path,
) -> None:
    _, port = _store_and_port(head_database)
    existing_payload = b"existing-success-payload"
    port.compare_and_replace(
        _source_cache_key(),
        slots=ProviderCacheSlots(content_slot=_success_content_slot(existing_payload)),
        payload=existing_payload,
        expected_generation=0,
    )
    transport = _transport(status=ProviderCacheResultStatus.TEMPORARY_FAILURE)
    mapper = _Mapper(existing_payload)
    runtime = ProviderCacheMappingRuntime(
        runtime=_runtime_for(ProviderCachePolicy.REFRESH_IF_STALE)
    )

    result = runtime.resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW + timedelta(minutes=10),
        cache=port,
        transport=transport,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert result.source_status is ProviderCacheResultStatus.TEMPORARY_FAILURE
    assert result.source_payload is None
    assert result.mapped_payload is None
    assert result.mapping_input_key is None
    assert transport.calls == 1

    read_back = port.get(_source_cache_key())
    assert read_back is not None
    assert read_back.payload == existing_payload
    assert read_back.slots.failure_slot is not None
    assert (
        read_back.slots.failure_slot.failure_status
        is ProviderCacheResultStatus.TEMPORARY_FAILURE
    )
    assert read_back.slots.content_slot is not None
    assert read_back.slots.content_slot.payload_bytes == existing_payload


def test_mapping_runtime_rejects_source_key_mismatch_before_cache_or_mapper(
    head_database: Path,
) -> None:
    _seed_success_cache(head_database)
    _, delegate = _store_and_port(head_database)
    transport = _transport()
    mapper = _Mapper(b"cached-payload")
    spy = _SpyPort(delegate)

    with pytest.raises(ValueError, match="source_cache_key must match configured"):
        ProviderCacheMappingRuntime(runtime=_runtime()).resolve(
            source_cache_key=_source_cache_key(),
            now=_NOW,
            cache=spy,
            transport=transport,
            provider_id=_PROVIDER_ID,
            provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
            provider_source_version="mismatched-source-version",
            query_fingerprint=_QUERY_FINGERPRINT,
            mapping_profile_version="mapping-profile-v1",
            mapper=mapper,
        )

    assert transport.calls == 0
    assert mapper.calls == 0
    assert spy.reads == 0
    assert spy.writes == 0


@pytest.mark.parametrize(
    "provider_id,provider_adapter_version,query_fingerprint,provider_source_version",
    [
        (
            "synthetic\\book-knowledge",
            _PROVIDER_ADAPTER_VERSION,
            _QUERY_FINGERPRINT,
            _PROVIDER_SOURCE_VERSION,
        ),
        (
            "../bad",
            _PROVIDER_ADAPTER_VERSION,
            _QUERY_FINGERPRINT,
            _PROVIDER_SOURCE_VERSION,
        ),
        (
            _PROVIDER_ID,
            _PROVIDER_ADAPTER_VERSION,
            _QUERY_FINGERPRINT + "/ff",
            _PROVIDER_SOURCE_VERSION,
        ),
    ],
)
def test_mapping_runtime_rejects_path_like_source_components_before_cache_or_mapper(
    head_database: Path,
    provider_id: str,
    provider_adapter_version: str,
    query_fingerprint: str,
    provider_source_version: str,
) -> None:
    _seed_success_cache(head_database)
    _, delegate = _store_and_port(head_database)
    transport = _transport()
    mapper = _Mapper(b"cached-payload")
    spy = _SpyPort(delegate)

    with pytest.raises(ValueError):
        ProviderCacheMappingRuntime(runtime=_runtime()).resolve(
            source_cache_key=_source_cache_key(),
            now=_NOW,
            cache=spy,
            transport=transport,
            provider_id=provider_id,
            provider_adapter_version=provider_adapter_version,
            provider_source_version=provider_source_version,
            query_fingerprint=query_fingerprint,
            mapping_profile_version="mapping-profile-v1",
            mapper=mapper,
        )

    assert transport.calls == 0
    assert mapper.calls == 0
    assert spy.reads == 0
    assert spy.writes == 0


@pytest.mark.parametrize(
    "seed, now, expected_status",
    [
        (
            _seed_expired_cache,
            _NOW + timedelta(minutes=15),
            None,
        ),
        (
            _seed_not_found_cache,
            _NOW,
            ProviderCacheResultStatus.NOT_FOUND,
        ),
        (
            lambda head_database: _seed_technical_failure_cache(head_database),
            _NOW + timedelta(minutes=15),
            ProviderCacheResultStatus.RATE_LIMITED,
        ),
    ],
)
def test_mapping_runtime_does_not_map_or_fetch_expired_not_found_or_technical(
    head_database: Path,
    seed: SeedFunction,
    now: datetime,
    expected_status: ProviderCacheResultStatus | None,
) -> None:
    source_cache_key = seed(head_database)
    _, delegate = _store_and_port(head_database)
    transport = _transport()
    mapper = _Mapper(b"cached-payload")
    spy = _SpyPort(delegate)

    result = ProviderCacheMappingRuntime(runtime=_runtime()).resolve(
        source_cache_key=source_cache_key,
        now=now,
        cache=spy,
        transport=transport,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert result.mapped_payload is None
    assert result.mapping_input_key is None
    assert result.source_payload is None
    assert result.source_status is expected_status
    assert transport.calls == 0
    assert mapper.calls == 0


def test_mapping_runtime_miss_keeps_mapping_optional_fields_none(
    head_database: Path,
) -> None:
    _, delegate = _store_and_port(head_database)
    transport = _transport()
    mapper = _Mapper(b"cached-payload")
    spy = _SpyPort(delegate)
    result = ProviderCacheMappingRuntime(runtime=_runtime()).resolve(
        source_cache_key=_source_cache_key(),
        now=_NOW,
        cache=spy,
        transport=transport,
        provider_id=_PROVIDER_ID,
        provider_adapter_version=_PROVIDER_ADAPTER_VERSION,
        provider_source_version=_PROVIDER_SOURCE_VERSION,
        query_fingerprint=_QUERY_FINGERPRINT,
        mapping_profile_version="mapping-profile-v1",
        mapper=mapper,
    )

    assert result.source_status is None
    assert result.source_payload is None
    assert result.mapped_payload is None
    assert result.mapping_input_key is None
    assert transport.calls == 0
    assert mapper.calls == 0
    assert spy.reads == 1
    assert spy.writes == 0


def test_provider_cache_store_port_applies_write_and_returns_cas_loser(
    head_database: Path,
) -> None:
    store, port = _store_and_port(head_database)
    source_key = _source_cache_key()
    first_payload = b"first-payload"

    first = port.compare_and_replace(
        source_key,
        slots=ProviderCacheSlots(content_slot=_success_content_slot(first_payload)),
        payload=first_payload,
        expected_generation=0,
    )
    assert first.applied is True
    assert first.entry.payload == first_payload
    assert first.entry.slots.content_slot is not None
    assert first.entry.slots.content_slot.payload_bytes == first_payload
    assert port.get(source_key) is not None

    read_back = port.get(source_key)
    assert read_back is not None
    assert read_back.payload == first_payload
    assert read_back.payload == first.entry.payload

    second_payload = b"second-payload"
    second = port.compare_and_replace(
        source_key,
        slots=ProviderCacheSlots(content_slot=_success_content_slot(second_payload)),
        payload=second_payload,
        expected_generation=0,
    )
    assert second.applied is False
    assert second.entry.payload == first_payload
    assert second.entry.slots.content_slot is not None
    assert second.entry.slots.content_slot.payload_bytes == first_payload


def test_provider_cache_store_port_validate_source_key_and_payload_fail_closed(
    head_database: Path,
) -> None:
    _, port = _store_and_port(head_database)
    source_key = _source_cache_key()
    port.compare_and_replace(
        source_key,
        slots=ProviderCacheSlots(content_slot=_success_content_slot(b"payload")),
        payload=b"payload",
        expected_generation=0,
    )

    with pytest.raises(ValueError, match="source_cache_key must match configured"):
        port.compare_and_replace(
            "0" * 64,
            slots=ProviderCacheSlots(content_slot=_success_content_slot(b"payload")),
            payload=b"payload",
            expected_generation=1,
        )

    with pytest.raises(ValueError, match="payload required for non-NONE content"):
        port.compare_and_replace(
            source_key,
            slots=ProviderCacheSlots(
                content_slot=ProviderCacheContentSlot(
                    content_status=ProviderCacheResultStatus.SUCCESS,
                    payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
                    payload_codec="json/raw-response",
                    payload_bytes=b"payload",
                    payload_bytes_sha256=sha256(b"payload").hexdigest(),
                    content_http_status=200,
                    content_fetched_at=_NOW,
                    content_fresh_until_at=_FRESH_UNTIL,
                    content_expires_at=_EXPIRES,
                ),
            ),
            payload=None,
            expected_generation=1,
        )
