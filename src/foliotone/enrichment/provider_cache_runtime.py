"""Pure cache-policy orchestration for provider source snapshots.

This module deliberately does not decode payloads, map provider evidence, or
depend on a concrete persistence implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from foliotone.enrichment.contracts import (
    ProviderAccessMode,
    ProviderCachePolicy,
    validate_provider_policy,
)
from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheFreshness,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    provider_cache_freshness,
)


@dataclass(frozen=True, slots=True)
class ProviderCacheRuntimeEntry:
    """One opaque source snapshot supplied by the cache port."""

    generation: int
    slots: ProviderCacheSlots
    payload: object | None = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive int")


@dataclass(frozen=True, slots=True)
class ProviderCacheRuntimeWrite:
    """CAS outcome; a losing writer receives the current winner."""

    applied: bool
    entry: ProviderCacheRuntimeEntry

    def __post_init__(self) -> None:
        if type(self.applied) is not bool:
            raise ValueError("applied must be a bool")


@dataclass(frozen=True, slots=True)
class ProviderCacheTransportResult:
    """Transport result with already formed cache slots and opaque payload."""

    source_status: ProviderCacheResultStatus
    slots: ProviderCacheSlots
    payload: object | None = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.source_status) is not ProviderCacheResultStatus:
            raise ValueError("source_status must be a ProviderCacheResultStatus")
        content = self.slots.content_slot
        failure = self.slots.failure_slot
        if self.source_status is ProviderCacheResultStatus.SUCCESS:
            if content is None or content.content_status is not self.source_status:
                raise ValueError("SUCCESS requires a SUCCESS content slot")
            if failure is not None or self.payload is None:
                raise ValueError("SUCCESS requires payload and no failure slot")
        elif self.source_status is ProviderCacheResultStatus.NOT_FOUND:
            if content is None or content.content_status is not self.source_status:
                raise ValueError("NOT_FOUND requires a NOT_FOUND content slot")
            if failure is not None:
                raise ValueError("NOT_FOUND must not include a failure slot")
        elif (
            content is not None
            or failure is None
            or failure.failure_status is not self.source_status
            or self.payload is not None
        ):
            raise ValueError("technical status requires failure-only slots and no payload")


@dataclass(frozen=True, slots=True)
class ProviderCacheRuntimeResult:
    """Immutable runtime outcome without a provider-specific mapped result."""

    source_status: ProviderCacheResultStatus | None
    slots: ProviderCacheSlots | None
    payload: object | None = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.source_status is not None
            and type(self.source_status) is not ProviderCacheResultStatus
        ):
            raise ValueError("source_status must be a ProviderCacheResultStatus or None")
        if (
            self.source_status
            in {
                ProviderCacheResultStatus.RATE_LIMITED,
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                ProviderCacheResultStatus.PERMANENT_FAILURE,
                ProviderCacheResultStatus.INVALID_RESPONSE,
            }
            and self.payload is not None
        ):
            raise ValueError("technical source_status must not carry payload")


class ProviderCachePort(Protocol):
    """Field-based source-cache port; persistence owns its own DTOs."""

    def get(self, source_cache_key: str) -> ProviderCacheRuntimeEntry | None: ...

    def compare_and_replace(
        self,
        source_cache_key: str,
        *,
        slots: ProviderCacheSlots,
        payload: object | None,
        expected_generation: int,
    ) -> ProviderCacheRuntimeWrite: ...


class ProviderCacheTransport(Protocol):
    """Fetch one allowed source and return reusable source material."""

    def fetch(self) -> ProviderCacheTransportResult: ...


class ProviderCacheRuntime:
    """Evaluate ADR-0035 cache policy without mapping or transport details."""

    def __init__(
        self,
        *,
        access_mode: ProviderAccessMode,
        cache_policy: ProviderCachePolicy,
    ) -> None:
        validate_provider_policy(access_mode, cache_policy)
        self._access_mode = access_mode
        self._cache_policy = cache_policy

    def resolve(
        self,
        *,
        source_cache_key: str,
        now: datetime,
        cache: ProviderCachePort | None,
        transport: ProviderCacheTransport,
    ) -> ProviderCacheRuntimeResult:
        """Return one policy result, executing at most one source fetch."""

        now = _require_utc_now(now)

        if self._cache_policy is ProviderCachePolicy.NO_CACHE:
            if self._access_mode is ProviderAccessMode.OFFLINE:
                return ProviderCacheRuntimeResult(None, None, None)
            return _from_transport(transport.fetch())

        entry = cache.get(source_cache_key) if cache is not None else None
        if self._cache_policy is ProviderCachePolicy.USE_IF_FRESH:
            return _read_only_result(entry, now)

        if self._cache_policy is ProviderCachePolicy.REFRESH_IF_STALE:
            fresh = _fresh_content_result(entry, now)
            if fresh is not None:
                return fresh

        active_retry = _active_retry_result(entry, now)
        if active_retry is not None:
            return active_retry

        # OFFLINE refresh combinations were rejected at construction time.
        fetched = transport.fetch()
        result = _from_transport(fetched)
        if cache is None:
            return result

        slots = _slots_for_write(entry, fetched)
        payload = _payload_for_write(entry, fetched)
        written = cache.compare_and_replace(
            source_cache_key,
            slots=slots,
            payload=payload,
            expected_generation=entry.generation if entry is not None else 0,
        )
        if written.applied:
            return ProviderCacheRuntimeResult(fetched.source_status, slots, fetched.payload)
        return _read_only_result(written.entry, now)


def _from_transport(result: ProviderCacheTransportResult) -> ProviderCacheRuntimeResult:
    return ProviderCacheRuntimeResult(result.source_status, result.slots, result.payload)


def _require_utc_now(now: datetime) -> datetime:
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a UTC datetime")
    if now.utcoffset() != timedelta(0):
        raise ValueError("now must be a UTC datetime")
    return now.astimezone(UTC)


def _fresh_content_result(
    entry: ProviderCacheRuntimeEntry | None,
    now: datetime,
) -> ProviderCacheRuntimeResult | None:
    if entry is None or entry.slots.content_slot is None:
        return None
    if provider_cache_freshness(entry.slots, now) is not ProviderCacheFreshness.FRESH:
        return None
    return ProviderCacheRuntimeResult(
        entry.slots.content_slot.content_status,
        entry.slots,
        entry.payload,
    )


def _active_retry_result(
    entry: ProviderCacheRuntimeEntry | None,
    now: datetime,
) -> ProviderCacheRuntimeResult | None:
    if entry is None or entry.slots.failure_slot is None:
        return None
    failure = entry.slots.failure_slot
    if (
        failure.failure_status is ProviderCacheResultStatus.RATE_LIMITED
        and failure.failure_retry_after_at is not None
        and now < failure.failure_retry_after_at
    ):
        return ProviderCacheRuntimeResult(failure.failure_status, entry.slots, None)
    return None


def _read_only_result(
    entry: ProviderCacheRuntimeEntry | None,
    now: datetime,
) -> ProviderCacheRuntimeResult:
    fresh = _fresh_content_result(entry, now)
    if fresh is not None:
        return fresh
    if entry is not None and entry.slots.failure_slot is not None:
        return ProviderCacheRuntimeResult(
            entry.slots.failure_slot.failure_status,
            entry.slots,
            None,
        )
    return ProviderCacheRuntimeResult(None, entry.slots if entry is not None else None, None)


def _slots_for_write(
    entry: ProviderCacheRuntimeEntry | None,
    fetched: ProviderCacheTransportResult,
) -> ProviderCacheSlots:
    if fetched.slots.failure_slot is None:
        return fetched.slots
    if entry is None or entry.slots.content_slot is None:
        return fetched.slots
    return ProviderCacheSlots(
        content_slot=entry.slots.content_slot,
        failure_slot=fetched.slots.failure_slot,
    )


def _payload_for_write(
    entry: ProviderCacheRuntimeEntry | None,
    fetched: ProviderCacheTransportResult,
) -> object | None:
    if fetched.slots.content_slot is not None:
        return fetched.payload
    if entry is not None and entry.slots.content_slot is not None:
        return entry.payload
    return None
