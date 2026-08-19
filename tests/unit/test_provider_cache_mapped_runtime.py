"""Mapped runtime DTO invariants and repr-safety."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.enrichment import (
    ProviderCacheMappedRuntimeResult,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
)
from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheContentSlot,
    ProviderCachePayloadKind,
)

_NOW = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def _slots() -> ProviderCacheSlots:
    return ProviderCacheSlots(
        content_slot=ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.NOT_FOUND,
            payload_kind=ProviderCachePayloadKind.NONE,
            content_fetched_at=_NOW,
            content_fresh_until_at=_NOW + timedelta(minutes=1),
            content_expires_at=_NOW + timedelta(minutes=2),
        ),
    )


def _result(
    source_status: ProviderCacheResultStatus,
    source_payload: object | None,
    mapped_payload: object | None,
    mapping_input_key: str | None,
) -> ProviderCacheMappedRuntimeResult:
    return ProviderCacheMappedRuntimeResult(
        source_status=source_status,
        slots=_slots(),
        source_payload=source_payload,
        mapped_payload=mapped_payload,
        mapping_input_key=mapping_input_key,
    )


class _Sensitive:
    def __repr__(self) -> str:
        return "private-mapped-secret"


def test_mapped_runtime_result_rejects_non_hex_mapping_input_key() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _result(
            ProviderCacheResultStatus.SUCCESS,
            source_payload=b"source-payload",
            mapped_payload=None,
            mapping_input_key="NOT_HEX",
        )


def test_mapped_runtime_result_requires_source_payload_when_mapping_key_set() -> None:
    with pytest.raises(ValueError, match="mapping_input_key requires source_payload"):
        _result(
            ProviderCacheResultStatus.NOT_FOUND,
            source_payload=None,
            mapped_payload="mapped",
            mapping_input_key="a" * 64,
        )


def test_mapped_runtime_result_rejects_mapped_payload_without_mapping_key() -> None:
    with pytest.raises(ValueError, match="mapping_input_key must be present"):
        _result(
            ProviderCacheResultStatus.SUCCESS,
            source_payload=b"source-payload",
            mapped_payload="mapped",
            mapping_input_key=None,
        )


def test_mapped_runtime_result_rejects_technical_payload() -> None:
    with pytest.raises(ValueError, match="technical source_status"):
        _result(
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
            source_payload=b"forbidden",
            mapped_payload=None,
            mapping_input_key=None,
        )


def test_mapped_runtime_result_hides_private_payloads_from_repr() -> None:
    result = _result(
        ProviderCacheResultStatus.SUCCESS,
        source_payload=_Sensitive(),
        mapped_payload=_Sensitive(),
        mapping_input_key="a" * 64,
    )

    assert "private-mapped-secret" not in repr(result)
