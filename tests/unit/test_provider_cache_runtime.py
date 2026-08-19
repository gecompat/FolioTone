"""Focused ADR-0035 cache-policy tests without provider mapping."""

from __future__ import annotations

import http.client
import socket
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256

import pytest

from foliotone.enrichment import (
    ProviderCacheRuntime,
    ProviderCacheRuntimeEntry,
    ProviderCacheRuntimeResult,
    ProviderCacheRuntimeWrite,
    ProviderCacheTransportResult,
)
from foliotone.enrichment.contracts import ProviderAccessMode, ProviderCachePolicy
from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCachePayloadKind,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
)

_NOW = datetime(2026, 8, 19, 10, tzinfo=UTC)
_KEY = "a" * 64


@dataclass
class _Transport:
    result: ProviderCacheTransportResult
    calls: int = 0

    def fetch(self) -> ProviderCacheTransportResult:
        self.calls += 1
        return self.result


@dataclass
class _SentinelTransport:
    calls: int = 0

    def fetch(self) -> ProviderCacheTransportResult:
        self.calls += 1
        urllib.request.urlopen("https://example.invalid")
        raise AssertionError("offline transport path should not be executed")


@dataclass
class _Cache:
    entry: ProviderCacheRuntimeEntry | None
    lose_write: bool = False
    reads: int = 0
    writes: int = 0

    def get(self, source_cache_key: str) -> ProviderCacheRuntimeEntry | None:
        assert source_cache_key == _KEY
        self.reads += 1
        return self.entry

    def compare_and_replace(
        self,
        source_cache_key: str,
        *,
        slots: ProviderCacheSlots,
        payload: object | None,
        expected_generation: int,
    ) -> ProviderCacheRuntimeWrite:
        assert source_cache_key == _KEY
        assert expected_generation == (self.entry.generation if self.entry else 0)
        self.writes += 1
        if self.lose_write:
            assert self.entry is not None
            return ProviderCacheRuntimeWrite(False, self.entry)
        self.entry = ProviderCacheRuntimeEntry(expected_generation + 1, slots, payload)
        return ProviderCacheRuntimeWrite(True, self.entry)


def _content(
    status: ProviderCacheResultStatus = ProviderCacheResultStatus.SUCCESS,
    *,
    fresh_until: datetime = _NOW + timedelta(minutes=5),
    expires_at: datetime = _NOW + timedelta(minutes=10),
) -> ProviderCacheContentSlot:
    payload = b"source"
    if status is ProviderCacheResultStatus.NOT_FOUND:
        return ProviderCacheContentSlot(
            content_status=status,
            content_fetched_at=_NOW - timedelta(minutes=3),
            content_fresh_until_at=fresh_until,
            content_expires_at=expires_at,
        )
    return ProviderCacheContentSlot(
        content_status=status,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_fetched_at=_NOW - timedelta(minutes=3),
        content_fresh_until_at=fresh_until,
        content_expires_at=expires_at,
    )


def _failure(
    status: ProviderCacheResultStatus = ProviderCacheResultStatus.TEMPORARY_FAILURE,
    *,
    retry_after: datetime | None = None,
) -> ProviderCacheFailureSlot:
    return ProviderCacheFailureSlot(
        failure_status=status,
        failure_at=_NOW,
        failure_retry_after_at=retry_after,
        failure_expires_at=_NOW + timedelta(minutes=10),
    )


def _transport(
    status: ProviderCacheResultStatus,
    *,
    payload: object | None = None,
) -> _Transport:
    if status in {ProviderCacheResultStatus.SUCCESS, ProviderCacheResultStatus.NOT_FOUND}:
        slots = ProviderCacheSlots(content_slot=_content(status))
        if status is ProviderCacheResultStatus.SUCCESS and payload is None:
            payload = "opaque-source"
    else:
        slots = ProviderCacheSlots(failure_slot=_failure(status))
    return _Transport(ProviderCacheTransportResult(status, slots, payload))


def _offline_network_block(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked_network(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("offline test network sentinel")

    monkeypatch.setattr(socket, "create_connection", _blocked_network)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _blocked_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", _blocked_network)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked_network)


def _runtime(
    policy: ProviderCachePolicy, access: ProviderAccessMode = ProviderAccessMode.ONLINE_STRUCTURED
) -> ProviderCacheRuntime:
    return ProviderCacheRuntime(access_mode=access, cache_policy=policy)


def test_no_cache_fetches_once_without_cache_read_or_write() -> None:
    cache = _Cache(ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), "old"))
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    result = _runtime(ProviderCachePolicy.NO_CACHE).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.SUCCESS
    assert result.payload == "opaque-source"
    assert transport.calls == 1
    assert cache.reads == 0
    assert cache.writes == 0


def test_offline_no_cache_returns_no_provider_result_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offline_network_block(monkeypatch)
    transport = _SentinelTransport()

    result = _runtime(ProviderCachePolicy.NO_CACHE, ProviderAccessMode.OFFLINE).resolve(
        source_cache_key=_KEY, now=_NOW, cache=None, transport=transport
    )

    assert result.source_status is None
    assert result.slots is None
    assert transport.calls == 0


def test_offline_use_if_fresh_fresh_success_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offline_network_block(monkeypatch)
    cache = _Cache(
        ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), "cached")
    )
    transport = _SentinelTransport()

    result = _runtime(
        ProviderCachePolicy.USE_IF_FRESH, ProviderAccessMode.OFFLINE
    ).resolve(source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport)

    assert result.source_status is ProviderCacheResultStatus.SUCCESS
    assert result.payload == "cached"
    assert transport.calls == 0


def test_offline_use_if_fresh_fresh_not_found_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offline_network_block(monkeypatch)
    cache = _Cache(
        ProviderCacheRuntimeEntry(
            1,
            ProviderCacheSlots(content_slot=_content(ProviderCacheResultStatus.NOT_FOUND)),
            None,
        )
    )
    transport = _SentinelTransport()

    result = _runtime(
        ProviderCachePolicy.USE_IF_FRESH, ProviderAccessMode.OFFLINE
    ).resolve(source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport)

    assert result.source_status is ProviderCacheResultStatus.NOT_FOUND
    assert transport.calls == 0


def test_offline_use_if_fresh_miss_does_not_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    _offline_network_block(monkeypatch)
    transport = _SentinelTransport()

    result = _runtime(
        ProviderCachePolicy.USE_IF_FRESH, ProviderAccessMode.OFFLINE
    ).resolve(source_cache_key=_KEY, now=_NOW, cache=_Cache(None), transport=transport)

    assert result.source_status is None
    assert result.slots is None
    assert transport.calls == 0


def test_use_if_fresh_hits_success_without_fetch() -> None:
    cache = _Cache(
        ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), "cached")
    )
    transport = _transport(ProviderCacheResultStatus.NOT_FOUND)

    result = _runtime(ProviderCachePolicy.USE_IF_FRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.SUCCESS
    assert result.payload == "cached"
    assert transport.calls == 0


def test_use_if_fresh_distinguishes_fresh_not_found_without_fetch() -> None:
    cache = _Cache(
        ProviderCacheRuntimeEntry(
            1,
            ProviderCacheSlots(content_slot=_content(ProviderCacheResultStatus.NOT_FOUND)),
            None,
        )
    )
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    result = _runtime(ProviderCachePolicy.USE_IF_FRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.NOT_FOUND
    assert transport.calls == 0


def test_use_if_fresh_miss_and_stale_do_not_fetch() -> None:
    stale = _content(fresh_until=_NOW, expires_at=_NOW + timedelta(minutes=1))
    cache = _Cache(ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=stale), "old"))
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    result = _runtime(ProviderCachePolicy.USE_IF_FRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is None
    assert result.payload is None
    assert transport.calls == 0


def test_use_if_fresh_miss_and_expired_do_not_fetch() -> None:
    expired = _content(
        fresh_until=_NOW - timedelta(minutes=2),
        expires_at=_NOW - timedelta(minutes=1),
    )
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    miss = _runtime(ProviderCachePolicy.USE_IF_FRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=_Cache(None), transport=transport
    )
    expired_result = _runtime(ProviderCachePolicy.USE_IF_FRESH).resolve(
        source_cache_key=_KEY,
        now=_NOW,
        cache=_Cache(ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=expired), "old")),
        transport=transport,
    )

    assert miss.source_status is None
    assert expired_result.source_status is None
    assert transport.calls == 0


def test_refresh_if_stale_uses_fresh_hit_then_refreshes_stale_once() -> None:
    cache = _Cache(
        ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), "cached")
    )
    transport = _transport(ProviderCacheResultStatus.SUCCESS)
    runtime = _runtime(ProviderCachePolicy.REFRESH_IF_STALE)

    hit = runtime.resolve(source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport)
    cache.entry = ProviderCacheRuntimeEntry(
        1,
        ProviderCacheSlots(
            content_slot=_content(fresh_until=_NOW, expires_at=_NOW + timedelta(minutes=1))
        ),
        "stale",
    )
    refreshed = runtime.resolve(source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport)

    assert hit.payload == "cached"
    assert refreshed.source_status is ProviderCacheResultStatus.SUCCESS
    assert transport.calls == 1
    assert cache.writes == 1


def test_force_refresh_fetches_once_even_for_fresh_cache() -> None:
    cache = _Cache(
        ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), "cached")
    )
    transport = _transport(ProviderCacheResultStatus.NOT_FOUND)

    result = _runtime(ProviderCachePolicy.FORCE_REFRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.NOT_FOUND
    assert transport.calls == 1
    assert cache.writes == 1


def test_refresh_if_stale_fetches_once_for_miss_and_expired() -> None:
    expired = _content(
        fresh_until=_NOW - timedelta(minutes=2),
        expires_at=_NOW - timedelta(minutes=1),
    )
    transport = _transport(ProviderCacheResultStatus.SUCCESS)
    runtime = _runtime(ProviderCachePolicy.REFRESH_IF_STALE)

    runtime.resolve(source_cache_key=_KEY, now=_NOW, cache=_Cache(None), transport=transport)
    runtime.resolve(
        source_cache_key=_KEY,
        now=_NOW,
        cache=_Cache(ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=expired), "old")),
        transport=transport,
    )

    assert transport.calls == 2


def test_active_rate_limit_blocks_refresh_fetch_and_is_visible() -> None:
    slots = ProviderCacheSlots(
        failure_slot=_failure(
            ProviderCacheResultStatus.RATE_LIMITED,
            retry_after=_NOW + timedelta(minutes=2),
        )
    )
    cache = _Cache(ProviderCacheRuntimeEntry(1, slots, None))
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    result = _runtime(ProviderCachePolicy.FORCE_REFRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )
    refresh = _runtime(ProviderCachePolicy.REFRESH_IF_STALE).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.RATE_LIMITED
    assert refresh.source_status is ProviderCacheResultStatus.RATE_LIMITED
    assert transport.calls == 0


def test_refresh_technical_failure_keeps_existing_content_in_written_slots() -> None:
    old_content = _content(fresh_until=_NOW, expires_at=_NOW + timedelta(minutes=1))
    cache = _Cache(
        ProviderCacheRuntimeEntry(3, ProviderCacheSlots(content_slot=old_content), "old")
    )
    transport = _transport(ProviderCacheResultStatus.TEMPORARY_FAILURE)

    result = _runtime(ProviderCachePolicy.REFRESH_IF_STALE).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.TEMPORARY_FAILURE
    assert cache.entry is not None
    assert cache.entry.slots.content_slot is old_content
    assert cache.entry.slots.failure_slot is not None
    assert cache.entry.payload == "old"
    assert transport.calls == 1


def test_cas_loser_uses_winner_without_second_fetch() -> None:
    winner = ProviderCacheRuntimeEntry(2, ProviderCacheSlots(content_slot=_content()), "winner")
    cache = _Cache(winner, lose_write=True)
    transport = _transport(ProviderCacheResultStatus.SUCCESS)

    result = _runtime(ProviderCachePolicy.FORCE_REFRESH).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert result.source_status is ProviderCacheResultStatus.SUCCESS
    assert result.payload == "winner"
    assert transport.calls == 1
    assert cache.writes == 1


def test_successful_refresh_replaces_old_failure_slot_and_hides_payloads_from_repr() -> None:
    sentinel = "private-source-token"
    old_slots = ProviderCacheSlots(
        content_slot=_content(fresh_until=_NOW, expires_at=_NOW + timedelta(minutes=1)),
        failure_slot=_failure(),
    )
    cache = _Cache(ProviderCacheRuntimeEntry(1, old_slots, sentinel))
    transport = _transport(ProviderCacheResultStatus.SUCCESS, payload=sentinel)

    result = _runtime(ProviderCachePolicy.REFRESH_IF_STALE).resolve(
        source_cache_key=_KEY, now=_NOW, cache=cache, transport=transport
    )

    assert cache.entry is not None
    assert cache.entry.slots.failure_slot is None
    assert sentinel not in repr(cache.entry)
    assert sentinel not in repr(transport.result)
    assert sentinel not in repr(result)


def test_runtime_dtos_reject_invalid_types_and_payload_leaks() -> None:
    with pytest.raises(ValueError, match="generation"):
        ProviderCacheRuntimeEntry(True, ProviderCacheSlots(content_slot=_content()), None)
    with pytest.raises(ValueError, match="applied"):
        ProviderCacheRuntimeWrite(
            1, ProviderCacheRuntimeEntry(1, ProviderCacheSlots(content_slot=_content()), None)
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="source_status"):
        ProviderCacheRuntimeResult("success", None, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="technical source_status"):
        ProviderCacheRuntimeResult(ProviderCacheResultStatus.TEMPORARY_FAILURE, None, "leak")


def test_transport_result_rejects_invalid_sum_type_and_resolve_rejects_non_utc_now() -> None:
    with pytest.raises(ValueError, match="SUCCESS requires payload"):
        ProviderCacheTransportResult(
            ProviderCacheResultStatus.SUCCESS,
            ProviderCacheSlots(content_slot=_content()),
            None,
        )
    with pytest.raises(ValueError, match="technical status"):
        ProviderCacheTransportResult(
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
            ProviderCacheSlots(failure_slot=_failure()),
            "must-not-leak",
        )
    with pytest.raises(ValueError, match="UTC"):
        _runtime(ProviderCachePolicy.NO_CACHE).resolve(
            source_cache_key=_KEY,
            now=datetime(2026, 8, 19, 10),
            cache=None,
            transport=_transport(ProviderCacheResultStatus.SUCCESS),
        )
    with pytest.raises(ValueError, match="UTC"):
        _runtime(ProviderCachePolicy.NO_CACHE).resolve(
            source_cache_key=_KEY,
            now=datetime(2026, 8, 19, 12, tzinfo=timezone(timedelta(hours=2))),
            cache=None,
            transport=_transport(ProviderCacheResultStatus.SUCCESS),
        )
