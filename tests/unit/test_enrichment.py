from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from foliotone.enrichment import (
    BookKnowledgeQuery,
    KnowledgeProviderMode,
    ProviderAccessMode,
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCacheFreshness,
    ProviderCacheLimits,
    ProviderCachePayloadKind,
    ProviderCachePolicy,
    ProviderCacheResultProjection,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    SyntheticBookKnowledgeProvider,
    project_provider_cache_status_to_slots,
    provider_cache_freshness,
    provider_policy_from_legacy,
)
from foliotone.enrichment.contracts import validate_provider_policy

_CONTENT_AT = datetime(2026, 8, 19, 10, 0, 0, tzinfo=UTC)
_FAIL_AT = datetime(2026, 8, 19, 10, 30, 0, tzinfo=UTC)


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


def test_synthetic_provider_defaults_to_offline_without_cache() -> None:
    provider = SyntheticBookKnowledgeProvider()

    response = provider.fetch(BookKnowledgeQuery(title="Synthetic title"))

    assert provider.descriptor.default_access_mode is ProviderAccessMode.OFFLINE
    assert provider.descriptor.default_cache_policy is ProviderCachePolicy.NO_CACHE
    assert response.access_mode is ProviderAccessMode.OFFLINE
    assert response.cache_policy is ProviderCachePolicy.NO_CACHE
    assert response.as_privacy_dto()["access_mode"] == "offline"
    assert response.as_privacy_dto()["cache_policy"] == "no_cache"


@pytest.mark.parametrize(
    ("legacy_mode", "access_mode", "cache_policy"),
    [
        (
            legacy_mode,
            *provider_policy_from_legacy(legacy_mode),
        )
        for legacy_mode in KnowledgeProviderMode
    ],
)
def test_synthetic_provider_propagates_mapped_legacy_policy(
    legacy_mode: KnowledgeProviderMode,
    access_mode: ProviderAccessMode,
    cache_policy: ProviderCachePolicy,
) -> None:
    provider = SyntheticBookKnowledgeProvider(
        access_mode=access_mode,
        cache_policy=cache_policy,
    )

    response = provider.fetch(BookKnowledgeQuery(title="Synthetic title"))

    assert provider.descriptor.default_access_mode is access_mode
    assert provider.descriptor.default_cache_policy is cache_policy
    assert response.access_mode is access_mode
    assert response.cache_policy is cache_policy
    assert response.as_privacy_dto()["access_mode"] == access_mode.value
    assert response.as_privacy_dto()["cache_policy"] == cache_policy.value


@pytest.mark.parametrize(
    "cache_policy",
    [ProviderCachePolicy.REFRESH_IF_STALE, ProviderCachePolicy.FORCE_REFRESH],
)
def test_synthetic_provider_rejects_offline_source_refresh(
    cache_policy: ProviderCachePolicy,
) -> None:
    with pytest.raises(ValueError, match="offline access cannot request a source refresh"):
        SyntheticBookKnowledgeProvider(
            access_mode=ProviderAccessMode.OFFLINE,
            cache_policy=cache_policy,
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
    assert response.access_mode is ProviderAccessMode.OFFLINE
    assert response.cache_policy is ProviderCachePolicy.NO_CACHE

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
    assert "mode" not in dto
    assert dto["access_mode"] == "offline"
    assert dto["cache_policy"] == "no_cache"
    assert dto["result_count"] == 1


def test_provider_cache_result_status_literals_are_exact() -> None:
    assert {
        name: value.value for name, value in ProviderCacheResultStatus.__members__.items()
    } == {
        "SUCCESS": "success",
        "NOT_FOUND": "not_found",
        "RATE_LIMITED": "rate_limited",
        "TEMPORARY_FAILURE": "temporary_failure",
        "PERMANENT_FAILURE": "permanent_failure",
        "INVALID_RESPONSE": "invalid_response",
    }


def test_provider_cache_payload_kind_literals_are_exact() -> None:
    assert {
        name: value.value for name, value in ProviderCachePayloadKind.__members__.items()
    } == {
        "NONE": "none",
        "RAW_RESPONSE": "raw_response",
        "NORMALIZED_SOURCE_DTO": "normalized_source_dto",
    }


def test_provider_cache_freshness_literals_are_exact() -> None:
    assert {
        name: value.value for name, value in ProviderCacheFreshness.__members__.items()
    } == {
        "FRESH": "fresh",
        "STALE": "stale",
        "EXPIRED": "expired",
    }


def _build_content_slot(
    status: ProviderCacheResultStatus,
) -> ProviderCacheContentSlot:
    if status is ProviderCacheResultStatus.SUCCESS:
        payload = b"payload"
        return ProviderCacheContentSlot(
            content_status=status,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=sha256(payload).hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT + timedelta(minutes=5),
            content_expires_at=_CONTENT_AT + timedelta(minutes=10),
        )

    if status is ProviderCacheResultStatus.NOT_FOUND:
        return ProviderCacheContentSlot(
            content_status=status,
            payload_kind=ProviderCachePayloadKind.NONE,
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT + timedelta(minutes=5),
            content_expires_at=_CONTENT_AT + timedelta(minutes=10),
        )

    raise ValueError("unsupported status for content slot helper")


def _projection(
    *,
    fetched_at: datetime,
    positive_fresh_ttl: timedelta = timedelta(minutes=2),
    negative_fresh_ttl: timedelta = timedelta(minutes=2),
) -> ProviderCacheResultProjection:
    return ProviderCacheResultProjection(
        fetched_at=fetched_at,
        positive_fresh_ttl=positive_fresh_ttl,
        positive_expires_ttl=timedelta(minutes=5),
        negative_fresh_ttl=negative_fresh_ttl,
        negative_expires_ttl=timedelta(minutes=2),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )


@pytest.mark.parametrize(
    ("status", "now", "expected"),
    [
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT - timedelta(minutes=1),
            ProviderCacheFreshness.FRESH,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=5) - timedelta(microseconds=1),
            ProviderCacheFreshness.FRESH,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=5),
            ProviderCacheFreshness.STALE,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=6),
            ProviderCacheFreshness.STALE,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=10) - timedelta(microseconds=1),
            ProviderCacheFreshness.STALE,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=10),
            ProviderCacheFreshness.EXPIRED,
        ),
        (
            ProviderCacheResultStatus.SUCCESS,
            _CONTENT_AT + timedelta(minutes=10, seconds=1),
            ProviderCacheFreshness.EXPIRED,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT - timedelta(minutes=1),
            ProviderCacheFreshness.FRESH,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT + timedelta(minutes=5) - timedelta(microseconds=1),
            ProviderCacheFreshness.FRESH,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT + timedelta(minutes=5),
            ProviderCacheFreshness.STALE,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT + timedelta(minutes=10) - timedelta(microseconds=1),
            ProviderCacheFreshness.STALE,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT + timedelta(minutes=10),
            ProviderCacheFreshness.EXPIRED,
        ),
        (
            ProviderCacheResultStatus.NOT_FOUND,
            _CONTENT_AT + timedelta(minutes=10, seconds=1),
            ProviderCacheFreshness.EXPIRED,
        ),
    ],
)
def test_provider_cache_freshness_boundaries_by_status(
    status: ProviderCacheResultStatus,
    now: datetime,
    expected: ProviderCacheFreshness,
) -> None:
    slot = _build_content_slot(status)
    assert provider_cache_freshness(slot, now) is expected
    assert provider_cache_freshness(ProviderCacheSlots(content_slot=slot), now) is expected


@pytest.mark.parametrize("now", [True, 1.0, "not-a-datetime"])
def test_provider_cache_freshness_rejects_invalid_now_type(now: object) -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        provider_cache_freshness(
            _build_content_slot(ProviderCacheResultStatus.SUCCESS),
            now,  # type: ignore[arg-type]
        )


def test_provider_cache_freshness_accepts_utc_aliases() -> None:
    try:
        zone_info_utc = ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        pytest.skip("ZoneInfo('UTC') unavailable in this environment")

    slot = _build_content_slot(ProviderCacheResultStatus.SUCCESS)
    assert (
        provider_cache_freshness(slot, datetime(2026, 8, 19, 10, 2, tzinfo=UTC))
        is ProviderCacheFreshness.FRESH
    )
    assert (
        provider_cache_freshness(
            slot, datetime(2026, 8, 19, 10, 2, tzinfo=zone_info_utc)
        )
        is ProviderCacheFreshness.FRESH
    )


def test_provider_cache_freshness_rejects_nonzero_offset_now() -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        provider_cache_freshness(
            _build_content_slot(ProviderCacheResultStatus.SUCCESS),
            datetime(2026, 8, 19, 10, 2, tzinfo=timezone(timedelta(hours=1))),
        )


@pytest.mark.parametrize(
    "slots",
    [
        None,
        ProviderCacheSlots(
            failure_slot=ProviderCacheFailureSlot(
                failure_status=ProviderCacheResultStatus.RATE_LIMITED,
                failure_at=_FAIL_AT,
                failure_retry_after_at=_FAIL_AT,
                failure_expires_at=_FAIL_AT,
            )
        ),
    ],
)
def test_provider_cache_freshness_handles_empty_or_missing_content_slot(
    slots: ProviderCacheSlots | None,
) -> None:
    assert provider_cache_freshness(slots, _CONTENT_AT) is None


def test_provider_cache_freshness_rejects_invalid_input_slot_type() -> None:
    with pytest.raises(
        ValueError,
        match="slots must be a ProviderCacheSlots or a ProviderCacheContentSlot",
    ):
        provider_cache_freshness(object(), _CONTENT_AT)  # type: ignore[arg-type]


def test_provider_cache_freshness_does_not_mutate_input_slot() -> None:
    slot = _build_content_slot(ProviderCacheResultStatus.SUCCESS)
    expected_slot = (
        slot.content_status,
        slot.payload_kind,
        slot.payload_bytes,
        slot.payload_bytes_sha256,
        slot.content_http_status,
        slot.content_fetched_at,
        slot.content_fresh_until_at,
        slot.content_expires_at,
        slot.payload_codec,
        sha256(slot.payload_bytes or b"").hexdigest(),
    )

    freshness = provider_cache_freshness(slot, _CONTENT_AT)
    assert freshness is ProviderCacheFreshness.FRESH
    assert (
        slot.content_status,
        slot.payload_kind,
        slot.payload_bytes,
        slot.payload_bytes_sha256,
        slot.content_http_status,
        slot.content_fetched_at,
        slot.content_fresh_until_at,
        slot.content_expires_at,
        slot.payload_codec,
    ) == expected_slot[:-1]


def test_provider_cache_limits_require_positive_values() -> None:
    assert ProviderCacheLimits(
        max_entry_payload_bytes=1024,
        max_entries_total=1000,
        max_payload_bytes_total=1024 * 1024,
        expired_prune_batch_size=256,
    )

    with pytest.raises(ValueError, match="must be positive"):
        ProviderCacheLimits(
            max_entry_payload_bytes=0,
            max_entries_total=1000,
            max_payload_bytes_total=1024 * 1024,
            expired_prune_batch_size=256,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_entry_payload_bytes", True),
        ("max_entry_payload_bytes", 1.5),
        ("max_entry_payload_bytes", "1024"),
        ("max_entries_total", False),
        ("max_entries_total", 4.0),
        ("max_payload_bytes_total", 12 + 0.0),
        ("expired_prune_batch_size", "128"),
    ],
)
def test_provider_cache_limits_reject_non_int_values(field: str, value: object) -> None:
    kwargs = {
        "max_entry_payload_bytes": 1024,
        "max_entries_total": 1000,
        "max_payload_bytes_total": 1024 * 1024,
        "expired_prune_batch_size": 256,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match="must be an int"):
        ProviderCacheLimits(**kwargs)


def test_provider_cache_limits_reject_entry_payload_exceeding_total() -> None:
    with pytest.raises(ValueError, match="must be <= max_payload_bytes_total"):
        ProviderCacheLimits(
            max_entry_payload_bytes=2048,
            max_entries_total=1000,
            max_payload_bytes_total=1024,
            expired_prune_batch_size=256,
        )


def test_provider_cache_content_slot_requires_content_status_for_payload() -> None:
    payload = b'{"source":"cached"}'
    with pytest.raises(ValueError, match="content_status must exist"):
        ProviderCacheContentSlot(
            content_status=None,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=sha256(payload).hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_rejects_success_without_payload() -> None:
    with pytest.raises(ValueError, match="SUCCESS requires a non-NONE payload"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_allows_not_found_without_payload() -> None:
    entry = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.NOT_FOUND,
        payload_kind=ProviderCachePayloadKind.NONE,
        content_fetched_at=_CONTENT_AT,
        content_fresh_until_at=_CONTENT_AT,
        content_expires_at=_CONTENT_AT,
    )
    assert entry.content_status is ProviderCacheResultStatus.NOT_FOUND
    assert entry.payload_kind is ProviderCachePayloadKind.NONE
    assert entry.payload_bytes is None


def test_provider_cache_content_slot_rejects_not_found_with_payload_for_none_kind() -> None:
    payload = b'{"source":"not_found_payload"}'
    with pytest.raises(ValueError, match="payload_codec must be None when payload_kind is NONE"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.NOT_FOUND,
            payload_kind=ProviderCachePayloadKind.NONE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=sha256(payload).hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_rejects_payload_sha_mismatch() -> None:
    with pytest.raises(ValueError, match="must match payload_bytes"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=b"payload",
            payload_bytes_sha256="0" * 64,
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_rejects_non_aware_datetimes() -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=b"payload",
            payload_bytes_sha256=sha256(b"payload").hexdigest(),
            content_fetched_at=datetime(2026, 8, 19),
            content_fresh_until_at=datetime(2026, 8, 20),
            content_expires_at=datetime(2026, 8, 21),
        )


@pytest.mark.parametrize("timestamp", [True, 1.0, "not-a-datetime"])
def test_provider_cache_content_slot_rejects_non_datetime_timestamps(
    timestamp: object,
) -> None:
    payload = b"payload"
    with pytest.raises(ValueError, match="must be UTC"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=sha256(payload).hexdigest(),
            content_fetched_at=timestamp,  # type: ignore[arg-type]
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_accepts_timezone_alias_and_zoneinfo_utc() -> None:
    try:
        zone_info_utc = ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        pytest.skip("ZoneInfo('UTC') unavailable in this environment")
    payload = b"cache payload"
    with_tz = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_fetched_at=datetime(2026, 8, 19, 10, 0, 0, tzinfo=UTC),
        content_fresh_until_at=datetime(2026, 8, 19, 10, 5, 0, tzinfo=UTC),
        content_expires_at=datetime(2026, 8, 19, 11, 0, 0, tzinfo=UTC),
    )
    assert with_tz.content_fetched_at.tzinfo is UTC

    with_z = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_fetched_at=datetime(2026, 8, 19, 10, 0, 0, tzinfo=zone_info_utc),
        content_fresh_until_at=datetime(2026, 8, 19, 10, 5, 0, tzinfo=zone_info_utc),
        content_expires_at=datetime(2026, 8, 19, 11, 0, 0, tzinfo=zone_info_utc),
    )
    assert with_z.content_fetched_at.tzinfo is UTC


def test_provider_cache_content_slot_rejects_nonzero_offset_timezone() -> None:
    payload = b"cache payload"
    with pytest.raises(ValueError, match="must be UTC"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=sha256(payload).hexdigest(),
            content_fetched_at=datetime(
                2026, 8, 19, 10, 0, 0, tzinfo=timezone(timedelta(hours=1))
            ),
            content_fresh_until_at=datetime(
                2026, 8, 19, 10, 5, 0, tzinfo=timezone(timedelta(hours=1))
            ),
            content_expires_at=datetime(
                2026, 8, 19, 11, 0, 0, tzinfo=timezone(timedelta(hours=1))
            ),
        )


def test_provider_cache_content_slot_rejects_wrong_enum_payload_kind() -> None:
    class ForeignPayloadKind(Enum):
        RAW = "raw_response"

    with pytest.raises(ValueError, match="payload_kind must be a ProviderCachePayloadKind"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ForeignPayloadKind.RAW,  # type: ignore[arg-type]
            payload_codec="json/raw-response",
            payload_bytes=b"payload",
            payload_bytes_sha256=sha256(b"payload").hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


@pytest.mark.parametrize("status", [True, 1.0])
def test_provider_cache_content_slot_rejects_nonenum_content_status(status: object) -> None:
    with pytest.raises(ValueError, match="content_status must be a ProviderCacheResultStatus"):
        ProviderCacheContentSlot(
            content_status=status,  # type: ignore[arg-type]
            payload_kind=ProviderCachePayloadKind.NONE,
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_rejects_bytearray_payload() -> None:
    with pytest.raises(ValueError, match="payload_bytes must be bytes"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=bytearray(b"payload"),
            payload_bytes_sha256=sha256(b"payload").hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


@pytest.mark.parametrize("digest", [True, 1.5, b"0" * 64, bytearray(b"0" * 64)])
def test_provider_cache_content_slot_rejects_invalid_payload_digest_type(digest: object) -> None:
    payload = b"payload"
    with pytest.raises(
        ValueError,
        match="payload_bytes_sha256 must be a lowercase SHA-256 hexadecimal digest",
    ):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=payload,
            payload_bytes_sha256=digest,  # type: ignore[arg-type]
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


@pytest.mark.parametrize(
    "codec",
    [
        r"json\\raw-response",
        "JSON/raw-response",
        "json//raw-response",
        "json:raw-response",
        "json/raw response",
        "/json/raw",
        "json/",
    ],
)
def test_provider_cache_content_slot_rejects_invalid_codec(codec: str) -> None:
    with pytest.raises(ValueError, match="technical codec pattern"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec=codec,
            payload_bytes=b"payload",
            payload_bytes_sha256=sha256(b"payload").hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_rejects_invalid_http_status() -> None:
    with pytest.raises(ValueError, match="must be between 100 and 599"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.NOT_FOUND,
            payload_kind=ProviderCachePayloadKind.NONE,
            content_http_status=99,
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT,
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_content_slot_validates_content_timeline_ordering() -> None:
    with pytest.raises(ValueError, match="must be fetched <= fresh_until <= expires"):
        ProviderCacheContentSlot(
            content_status=ProviderCacheResultStatus.SUCCESS,
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            payload_codec="json/raw-response",
            payload_bytes=b"payload",
            payload_bytes_sha256=sha256(b"payload").hexdigest(),
            content_fetched_at=_CONTENT_AT,
            content_fresh_until_at=_CONTENT_AT.replace(hour=9),
            content_expires_at=_CONTENT_AT,
        )


def test_provider_cache_failure_slot_requires_utc_failures() -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.RATE_LIMITED,
            failure_at=datetime(2026, 8, 19),
            failure_retry_after_at=datetime(2026, 8, 19, 10, 1),
            failure_expires_at=datetime(2026, 8, 19, 10, 2),
        )


@pytest.mark.parametrize("value", [True, 1.0, "not-a-datetime"])
def test_provider_cache_failure_slot_rejects_non_datetime_timestamps(value: object) -> None:
    with pytest.raises(ValueError, match="must be UTC"):
        ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.RATE_LIMITED,
            failure_at=value,  # type: ignore[arg-type]
            failure_expires_at=_FAIL_AT,
        )


@pytest.mark.parametrize(
    "failure_status",
    [ProviderCacheResultStatus.SUCCESS, ProviderCacheResultStatus.NOT_FOUND],
)
def test_provider_cache_failure_slot_rejects_invalid_status_values(
    failure_status: ProviderCacheResultStatus,
) -> None:
    with pytest.raises(ValueError, match="cannot be SUCCESS or NOT_FOUND"):
        ProviderCacheFailureSlot(
            failure_status=failure_status,
            failure_at=_FAIL_AT,
            failure_expires_at=_FAIL_AT,
        )


def test_provider_cache_failure_slot_rejects_non_matching_status_type() -> None:
    class ForeignStatus(Enum):
        TEMP = "temporary_failure"

    with pytest.raises(ValueError, match="failure_status must be a ProviderCacheResultStatus"):
        ProviderCacheFailureSlot(
            failure_status=ForeignStatus.TEMP,  # type: ignore[arg-type]
            failure_at=_FAIL_AT,
            failure_expires_at=_FAIL_AT,
        )


@pytest.mark.parametrize("status", [True, 1.0])
def test_provider_cache_failure_slot_rejects_nonenum_failure_status(status: object) -> None:
    with pytest.raises(ValueError, match="failure_status must be a ProviderCacheResultStatus"):
        ProviderCacheFailureSlot(
            failure_status=status,  # type: ignore[arg-type]
            failure_at=_FAIL_AT,
            failure_expires_at=_FAIL_AT,
        )


def test_provider_cache_failure_slot_rejects_non_http_status_code() -> None:
    with pytest.raises(ValueError, match="must be between 100 and 599"):
        ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.TEMPORARY_FAILURE,
            failure_http_status=600,
            failure_at=_FAIL_AT,
            failure_expires_at=_FAIL_AT,
        )


def test_provider_cache_failure_slot_rejects_retry_after_for_non_rate_limited_status() -> None:
    with pytest.raises(ValueError, match="only valid for RATE_LIMITED"):
        ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.TEMPORARY_FAILURE,
            failure_at=_FAIL_AT,
            failure_retry_after_at=_FAIL_AT,
            failure_expires_at=_FAIL_AT,
        )


def test_provider_cache_failure_slot_rejects_retry_after_ordering() -> None:
    with pytest.raises(ValueError, match="between failure_at and failure_expires_at"):
        ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.RATE_LIMITED,
            failure_at=_FAIL_AT,
            failure_retry_after_at=_FAIL_AT.replace(minute=20),
            failure_expires_at=_FAIL_AT.replace(minute=35),
        )


def test_provider_cache_slots_require_at_least_one_slot() -> None:
    with pytest.raises(ValueError, match="at least one slot must be present"):
        ProviderCacheSlots()
    with pytest.raises(ValueError, match="content_slot must include a content_status"):
        ProviderCacheSlots(content_slot=ProviderCacheContentSlot(), failure_slot=None)
    with pytest.raises(ValueError, match="failure_slot must include a failure_status"):
        ProviderCacheSlots(content_slot=None, failure_slot=ProviderCacheFailureSlot())


def test_provider_cache_slots_reject_foreign_slot_types() -> None:
    with pytest.raises(ValueError, match="content_slot must be a ProviderCacheContentSlot"):
        ProviderCacheSlots(content_slot=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="failure_slot must be a ProviderCacheFailureSlot"):
        ProviderCacheSlots(failure_slot=object())  # type: ignore[arg-type]


def test_provider_cache_slots_allow_content_only_failure_only_or_both() -> None:
    content = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.NOT_FOUND,
        payload_kind=ProviderCachePayloadKind.NONE,
        content_fetched_at=_CONTENT_AT,
        content_fresh_until_at=_CONTENT_AT,
        content_expires_at=_CONTENT_AT,
    )
    failure = ProviderCacheFailureSlot(
        failure_status=ProviderCacheResultStatus.RATE_LIMITED,
        failure_at=_FAIL_AT,
        failure_retry_after_at=_FAIL_AT,
        failure_expires_at=_FAIL_AT,
    )
    assert ProviderCacheSlots(content_slot=content).failure_slot is None
    assert ProviderCacheSlots(failure_slot=failure).content_slot is None
    slots = ProviderCacheSlots(content_slot=content, failure_slot=failure)
    assert slots.content_slot is content
    assert slots.failure_slot is failure


def test_provider_cache_slots_reject_empty_content_slot_when_failure_present() -> None:
    failure = ProviderCacheFailureSlot(
        failure_status=ProviderCacheResultStatus.RATE_LIMITED,
        failure_at=_FAIL_AT,
        failure_retry_after_at=_FAIL_AT,
        failure_expires_at=_FAIL_AT,
    )
    with pytest.raises(ValueError, match="content_slot must include a content_status"):
        ProviderCacheSlots(content_slot=ProviderCacheContentSlot(), failure_slot=failure)


def test_provider_cache_slots_reject_empty_failure_slot_when_content_present() -> None:
    content = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.NOT_FOUND,
        payload_kind=ProviderCachePayloadKind.NONE,
        content_fetched_at=_CONTENT_AT,
        content_fresh_until_at=_CONTENT_AT,
        content_expires_at=_CONTENT_AT,
    )
    with pytest.raises(ValueError, match="failure_slot must include a failure_status"):
        ProviderCacheSlots(content_slot=content, failure_slot=ProviderCacheFailureSlot())


def test_provider_cache_slot_repr_is_path_free() -> None:
    payload = b"C:\\tmp\\project\\secret.json"
    slot = ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus.SUCCESS,
        payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
        payload_codec="json/raw-response",
        payload_bytes=payload,
        payload_bytes_sha256=sha256(payload).hexdigest(),
        content_fetched_at=_CONTENT_AT,
        content_fresh_until_at=_CONTENT_AT,
        content_expires_at=_CONTENT_AT,
    )
    assert "C:\\" not in repr(slot)


def test_provider_cache_result_projection_preserves_expected_status_slots() -> None:
    payload = b"projection-payload"
    projection = _projection(fetched_at=_CONTENT_AT, positive_fresh_ttl=timedelta(minutes=3))
    projected = {
        status: project_provider_cache_status_to_slots(
            status,
            projection=projection,
            payload_bytes=(
                payload
                if status is ProviderCacheResultStatus.SUCCESS
                else None
            ),
            payload_codec="json/raw-response"
            if status is ProviderCacheResultStatus.SUCCESS
            else None,
            payload_kind=(
                ProviderCachePayloadKind.RAW_RESPONSE
                if status is ProviderCacheResultStatus.SUCCESS
                else ProviderCachePayloadKind.NONE
            ),
            content_http_status=200 if status is ProviderCacheResultStatus.SUCCESS else None,
            payload_bytes_sha256=(
                sha256(payload).hexdigest() if status is ProviderCacheResultStatus.SUCCESS else None
            ),
        )
        for status in (
            ProviderCacheResultStatus.SUCCESS,
            ProviderCacheResultStatus.NOT_FOUND,
            ProviderCacheResultStatus.RATE_LIMITED,
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
            ProviderCacheResultStatus.PERMANENT_FAILURE,
            ProviderCacheResultStatus.INVALID_RESPONSE,
        )
    }

    assert projected[ProviderCacheResultStatus.SUCCESS].content_slot is not None
    assert (
        projected[ProviderCacheResultStatus.SUCCESS].content_slot.content_status
        is ProviderCacheResultStatus.SUCCESS
    )
    assert projected[ProviderCacheResultStatus.SUCCESS].failure_slot is None

    not_found_slots = projected[ProviderCacheResultStatus.NOT_FOUND]
    assert not_found_slots.content_slot is not None
    assert not_found_slots.content_slot.content_status is ProviderCacheResultStatus.NOT_FOUND
    assert not_found_slots.content_slot.payload_kind is ProviderCachePayloadKind.NONE
    assert not_found_slots.failure_slot is None

    for status in (
        ProviderCacheResultStatus.RATE_LIMITED,
        ProviderCacheResultStatus.TEMPORARY_FAILURE,
        ProviderCacheResultStatus.PERMANENT_FAILURE,
        ProviderCacheResultStatus.INVALID_RESPONSE,
    ):
        failure_slots = projected[status]
        assert failure_slots.content_slot is None
        assert failure_slots.failure_slot is not None
        assert failure_slots.failure_slot.failure_status is status


def test_provider_cache_result_projection_enforces_negative_ttl_inequality() -> None:
    with pytest.raises(
        ValueError,
        match="negative_fresh_ttl must be less than or equal to negative_expires_ttl",
    ):
        ProviderCacheResultProjection(
            fetched_at=_CONTENT_AT,
            positive_fresh_ttl=timedelta(minutes=2),
            positive_expires_ttl=timedelta(minutes=5),
            negative_fresh_ttl=timedelta(minutes=3),
            negative_expires_ttl=timedelta(minutes=2),
            technical_failure_expires_ttl=timedelta(minutes=1),
        )
    with pytest.raises(
        ValueError,
        match="negative_expires_ttl must be shorter than positive_expires_ttl",
    ):
        ProviderCacheResultProjection(
            fetched_at=_CONTENT_AT,
            positive_fresh_ttl=timedelta(minutes=2),
            positive_expires_ttl=timedelta(minutes=2),
            negative_fresh_ttl=timedelta(minutes=1),
            negative_expires_ttl=timedelta(minutes=2),
            technical_failure_expires_ttl=timedelta(minutes=1),
        )


def test_provider_cache_result_projection_not_found_uses_negative_fresh_ttl() -> None:
    projection = ProviderCacheResultProjection(
        fetched_at=_CONTENT_AT,
        positive_fresh_ttl=timedelta(minutes=5),
        positive_expires_ttl=timedelta(minutes=10),
        negative_fresh_ttl=timedelta(minutes=1),
        negative_expires_ttl=timedelta(minutes=4),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )
    slots = project_provider_cache_status_to_slots(
        ProviderCacheResultStatus.NOT_FOUND,
        projection=projection,
        payload_bytes=None,
        payload_codec=None,
        payload_kind=ProviderCachePayloadKind.NONE,
    )
    assert slots.content_slot is not None
    assert slots.content_slot.content_fresh_until_at == _CONTENT_AT + timedelta(minutes=1)
    assert slots.content_slot.content_expires_at == _CONTENT_AT + timedelta(minutes=4)
    assert provider_cache_freshness(slots.content_slot, _CONTENT_AT) is ProviderCacheFreshness.FRESH
    assert provider_cache_freshness(
        slots.content_slot, _CONTENT_AT + timedelta(minutes=1) - timedelta(microseconds=1)
    ) is ProviderCacheFreshness.FRESH
    assert provider_cache_freshness(
        slots.content_slot, _CONTENT_AT + timedelta(minutes=1)
    ) is ProviderCacheFreshness.STALE
    assert provider_cache_freshness(
        slots.content_slot, _CONTENT_AT + timedelta(minutes=4)
    ) is ProviderCacheFreshness.EXPIRED


def test_provider_cache_result_projection_rejects_non_rate_limited_failure_retry_after() -> None:
    projection = ProviderCacheResultProjection(
        fetched_at=_CONTENT_AT,
        positive_fresh_ttl=timedelta(minutes=3),
        positive_expires_ttl=timedelta(minutes=6),
        negative_fresh_ttl=timedelta(minutes=1),
        negative_expires_ttl=timedelta(minutes=2),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )
    with pytest.raises(
        ValueError,
        match="failure_retry_after_at is only valid for RATE_LIMITED",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
            projection=projection,
            payload_bytes=None,
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
            failure_retry_after_at=_CONTENT_AT + timedelta(seconds=10),
        )


def test_provider_cache_result_projection_rejects_invalid_retry_after_retry_window() -> None:
    projection = ProviderCacheResultProjection(
        fetched_at=_CONTENT_AT,
        positive_fresh_ttl=timedelta(minutes=3),
        positive_expires_ttl=timedelta(minutes=6),
        negative_fresh_ttl=timedelta(minutes=1),
        negative_expires_ttl=timedelta(minutes=2),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="must be UTC"):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.RATE_LIMITED,
            projection=projection,
            payload_bytes=None,
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
            failure_retry_after_at=datetime(2026, 8, 19, 10, 1),
        )
    with pytest.raises(ValueError, match="between failure_at and failure_expires_at"):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.RATE_LIMITED,
            projection=projection,
            payload_bytes=None,
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
            failure_retry_after_at=_CONTENT_AT + timedelta(minutes=2),
        )


def test_provider_cache_result_projection_keeps_existing_success_content_for_failure() -> None:
    existing_content = _build_content_slot(ProviderCacheResultStatus.SUCCESS)
    projection = ProviderCacheResultProjection(
        fetched_at=_CONTENT_AT,
        positive_fresh_ttl=timedelta(minutes=3),
        positive_expires_ttl=timedelta(minutes=6),
        negative_fresh_ttl=timedelta(minutes=1),
        negative_expires_ttl=timedelta(minutes=2),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )
    slots = project_provider_cache_status_to_slots(
        ProviderCacheResultStatus.RATE_LIMITED,
        projection=projection,
        payload_bytes=None,
        payload_codec=None,
        payload_kind=ProviderCachePayloadKind.NONE,
        failure_retry_after_at=_CONTENT_AT + timedelta(seconds=30),
        preserve_content_slot=existing_content,
    )
    assert slots.content_slot is existing_content
    assert slots.failure_slot is not None
    assert slots.failure_slot.failure_retry_after_at == _CONTENT_AT + timedelta(seconds=30)


def test_provider_cache_result_projection_rejects_cross_path_metadata() -> None:
    projection = _projection(fetched_at=_CONTENT_AT)
    with pytest.raises(
        ValueError,
        match="payload_kind NONE must not include payload fields",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.NOT_FOUND,
            projection=projection,
            payload_bytes=b"must-not-be-discarded",
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
        )
    with pytest.raises(
        ValueError,
        match="failure_http_status is only valid for failure statuses",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.SUCCESS,
            projection=projection,
            payload_bytes=b"payload",
            payload_codec="json/raw-response",
            payload_kind=ProviderCachePayloadKind.RAW_RESPONSE,
            failure_http_status=429,
        )
    with pytest.raises(
        ValueError,
        match="failure_retry_after_at is only valid for failure statuses",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.NOT_FOUND,
            projection=projection,
            payload_bytes=None,
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
            failure_retry_after_at=_CONTENT_AT + timedelta(seconds=10),
        )
    with pytest.raises(
        ValueError,
        match="content_http_status is only valid for content statuses",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.RATE_LIMITED,
            projection=projection,
            payload_bytes=None,
            payload_codec=None,
            payload_kind=ProviderCachePayloadKind.NONE,
            content_http_status=404,
        )


def test_provider_cache_result_projection_rejects_invalid_payload_digest_type() -> None:
    projection = _projection(fetched_at=_CONTENT_AT)
    with pytest.raises(
        ValueError,
        match="payload_bytes_sha256 must be a lowercase SHA-256 hex digest",
    ):
        project_provider_cache_status_to_slots(
            ProviderCacheResultStatus.SUCCESS,
            projection=projection,
            payload_bytes=b"payload",
            payload_codec="json/raw-response",
            payload_bytes_sha256=bytearray(b"0" * 64),
        )


@pytest.mark.parametrize(
    ("instance", "field_name", "new_value"),
    [
        (
            ProviderCacheLimits(
                max_entry_payload_bytes=1024,
                max_entries_total=1000,
                max_payload_bytes_total=1024 * 1024,
                expired_prune_batch_size=256,
            ),
            "max_entry_payload_bytes",
            2048,
        ),
        (
            ProviderCacheContentSlot(
                content_status=ProviderCacheResultStatus.NOT_FOUND,
                payload_kind=ProviderCachePayloadKind.NONE,
                content_fetched_at=_CONTENT_AT,
                content_fresh_until_at=_CONTENT_AT,
                content_expires_at=_CONTENT_AT,
            ),
            "content_status",
            ProviderCacheResultStatus.SUCCESS,
        ),
        (
            ProviderCacheFailureSlot(
                failure_status=ProviderCacheResultStatus.RATE_LIMITED,
                failure_at=_FAIL_AT,
                failure_retry_after_at=_FAIL_AT,
                failure_expires_at=_FAIL_AT,
            ),
            "failure_status",
            ProviderCacheResultStatus.TEMPORARY_FAILURE,
        ),
        (
            ProviderCacheSlots(
                content_slot=ProviderCacheContentSlot(
                    content_status=ProviderCacheResultStatus.NOT_FOUND,
                    payload_kind=ProviderCachePayloadKind.NONE,
                    content_fetched_at=_CONTENT_AT,
                    content_fresh_until_at=_CONTENT_AT,
                    content_expires_at=_CONTENT_AT,
                )
            ),
            "failure_slot",
            ProviderCacheFailureSlot(
                failure_status=ProviderCacheResultStatus.RATE_LIMITED,
                failure_at=_FAIL_AT,
                failure_retry_after_at=_FAIL_AT,
                failure_expires_at=_FAIL_AT,
            ),
        ),
    ],
)
def test_provider_cache_contract_classes_are_frozen_slots_and_path_safe(
    instance: object,
    field_name: str,
    new_value: object,
) -> None:
    assert not hasattr(instance, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(instance, field_name, new_value)
