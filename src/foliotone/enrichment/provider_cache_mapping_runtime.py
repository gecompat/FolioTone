"""Mapping-oriented adapter for cached provider source snapshots."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheFreshness,
    ProviderCachePayloadKind,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    provider_cache_freshness,
    provider_mapping_input_key,
    provider_source_cache_key,
)
from foliotone.enrichment.provider_cache_runtime import (
    ProviderCachePort,
    ProviderCacheRuntime,
    ProviderCacheRuntimeResult,
    ProviderCacheTransport,
)


class ProviderCacheMappingMapper(Protocol):
    """Pure function contract for source payload re-mapping."""

    def __call__(self, source_payload: object) -> object: ...


@dataclass(frozen=True, slots=True)
class ProviderCacheMappedRuntimeResult:
    """Provider runtime outcome plus optional mapped payload and key provenance."""

    source_status: ProviderCacheResultStatus | None
    slots: ProviderCacheSlots | None
    source_payload: object | None = field(repr=False)
    mapped_payload: object | None = field(repr=False)
    mapping_input_key: str | None

    def __post_init__(self) -> None:
        if (
            self.source_status is not None
            and type(self.source_status) is not ProviderCacheResultStatus
        ):
            raise ValueError("source_status must be ProviderCacheResultStatus or None")
        if self.source_status is None and self.source_payload is not None:
            raise ValueError("source_payload requires a source_status")
        if (
            self.source_status
            in {
                ProviderCacheResultStatus.RATE_LIMITED,
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                ProviderCacheResultStatus.PERMANENT_FAILURE,
                ProviderCacheResultStatus.INVALID_RESPONSE,
            }
            and self.source_payload is not None
        ):
            raise ValueError("technical source_status must not carry source_payload")
        if (
            self.source_status is ProviderCacheResultStatus.SUCCESS
            and self.source_payload is None
        ):
            raise ValueError("SUCCESS requires source_payload")
        if (
            self.mapping_input_key is not None
            and self.source_status
            not in {
                ProviderCacheResultStatus.SUCCESS,
                ProviderCacheResultStatus.NOT_FOUND,
            }
        ):
            raise ValueError(
                "mapping_input_key may only be set for SUCCESS/NOT_FOUND results"
            )
        if (
            self.mapping_input_key is not None
            and type(self.mapping_input_key) is not str
        ):
            raise ValueError("mapping_input_key must be str")
        if (
            self.mapping_input_key is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.mapping_input_key) is None
        ):
            raise ValueError(
                "mapping_input_key must be a lowercase SHA-256 hexadecimal digest"
            )
        if self.mapping_input_key is not None and self.source_payload is None:
            raise ValueError("mapping_input_key requires source_payload")
        if self.mapping_input_key is None and self.mapped_payload is not None:
            raise ValueError(
                "mapping_input_key must be present when mapped_payload is set"
            )


class ProviderCacheMappingRuntime:
    """Apply mapping with source-key reuse and separate mapping versioning."""

    def __init__(self, *, runtime: ProviderCacheRuntime) -> None:
        self._runtime = runtime

    def resolve(
        self,
        *,
        source_cache_key: str,
        now: datetime,
        cache: ProviderCachePort | None,
        transport: ProviderCacheTransport,
        provider_id: str,
        provider_adapter_version: str,
        provider_source_version: str,
        query_fingerprint: str,
        mapping_profile_version: str,
        mapper: Callable[[object], object] | ProviderCacheMappingMapper,
    ) -> ProviderCacheMappedRuntimeResult:
        canonical_source_cache_key = provider_source_cache_key(
            provider_id=provider_id,
            provider_adapter_version=provider_adapter_version,
            query_fingerprint=query_fingerprint,
            provider_source_version=provider_source_version,
        )
        if source_cache_key != canonical_source_cache_key:
            raise ValueError("source_cache_key must match configured provider input")

        source_result = self._runtime.resolve(
            source_cache_key=source_cache_key,
            now=now,
            cache=cache,
            transport=transport,
        )
        mapped_payload = _mapped_payload_if_applicable(
            result=source_result,
            now=now,
            mapper=mapper,
            provider_id=provider_id,
            provider_adapter_version=provider_adapter_version,
            provider_source_version=provider_source_version,
            query_fingerprint=query_fingerprint,
            mapping_profile_version=mapping_profile_version,
        )

        return ProviderCacheMappedRuntimeResult(
            source_status=source_result.source_status,
            slots=source_result.slots,
            source_payload=source_result.payload,
            mapped_payload=mapped_payload.payload,
            mapping_input_key=mapped_payload.mapping_input_key,
        )


@dataclass(frozen=True, slots=True)
class _MappedPayload:
    payload: object | None = field(repr=False)
    mapping_input_key: str | None


def _mapped_payload_if_applicable(
    *,
    result: ProviderCacheRuntimeResult,
    now: datetime,
    mapper: Callable[[object], object] | ProviderCacheMappingMapper,
    provider_id: str,
    provider_adapter_version: str,
    provider_source_version: str,
    query_fingerprint: str,
    mapping_profile_version: str,
) -> _MappedPayload:
    if (
        result.source_status not in
        {ProviderCacheResultStatus.SUCCESS, ProviderCacheResultStatus.NOT_FOUND}
    ):
        return _MappedPayload(None, None)
    if result.payload is None or result.slots is None:
        return _MappedPayload(None, None)
    if result.slots.content_slot is None:
        return _MappedPayload(None, None)
    if result.slots.content_slot.payload_kind is ProviderCachePayloadKind.NONE:
        return _MappedPayload(None, None)
    if (
        provider_cache_freshness(result.slots, _require_utc(now, "now"))
        is not ProviderCacheFreshness.FRESH
    ):
        return _MappedPayload(None, None)
    mapping_input_key = provider_mapping_input_key(
        provider_id=provider_id,
        provider_adapter_version=provider_adapter_version,
        query_fingerprint=query_fingerprint,
        provider_source_version=provider_source_version,
        mapping_profile_version=mapping_profile_version,
    )
    return _MappedPayload(mapper(result.payload), mapping_input_key)


def _require_utc(now: datetime, field_name: str) -> datetime:
    if type(now) is not datetime:
        raise ValueError(f"{field_name} must be UTC")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"{field_name} must be UTC")
    if now.utcoffset() != UTC.utcoffset(now):
        raise ValueError(f"{field_name} must be UTC")
    return now.astimezone(UTC)


__all__ = [
    "ProviderCacheMappingMapper",
    "ProviderCacheMappingRuntime",
    "ProviderCacheMappedRuntimeResult",
]
