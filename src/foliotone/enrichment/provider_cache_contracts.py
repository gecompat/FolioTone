"""Provider cache runtime contracts for ADR-0035.

This module intentionally contains only immutable, serializable core contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from re import fullmatch

from foliotone.core._validation import require_aware_datetime


class ProviderCacheResultStatus(Enum):
    """Result status for a provider cache lookup or fetch."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"
    INVALID_RESPONSE = "invalid_response"


class ProviderCachePayloadKind(Enum):
    """Allowed payload representation for a cached provider content snapshot."""

    NONE = "none"
    RAW_RESPONSE = "raw_response"
    NORMALIZED_SOURCE_DTO = "normalized_source_dto"


class ProviderCacheFreshness(Enum):
    """Freshness state for a persisted content slot."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


_PAYLOAD_CODEC_MAXLEN = 48


def _require_exact_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an int")
    return value


def _require_positive(value: object, field_name: str) -> int:
    value = _require_exact_int(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_non_negative_int(value: object | None, field_name: str) -> int | None:
    if value is None:
        return None
    value = _require_exact_int(value, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be greater than or equal to zero")
    return value


def _require_http_status(value: object | None, field_name: str) -> int | None:
    value = _require_non_negative_int(value, field_name)
    if value is None:
        return None
    if not (100 <= value <= 599):
        raise ValueError(f"{field_name} must be between 100 and 599")
    return value


def _require_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise ValueError(f"{field_name} must be UTC")
    try:
        value = require_aware_datetime(value, field_name)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be UTC") from exc
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)


def _require_sha256(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(
            f"{field_name} must be a lowercase SHA-256 hexadecimal digest"
        )
    if not fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return value


def _require_payload_codec(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    if not (1 <= len(value) <= _PAYLOAD_CODEC_MAXLEN):
        raise ValueError(f"{field_name} must be between 1 and {_PAYLOAD_CODEC_MAXLEN}")
    if fullmatch(r"^[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*$", value) is None:
        raise ValueError(
            f"{field_name} must match family/name technical codec pattern"
        )
    return value


def _require_payload_kind(
    value: object,
    field_name: str,
) -> ProviderCachePayloadKind:
    if type(value) is not ProviderCachePayloadKind:
        raise ValueError(f"{field_name} must be a ProviderCachePayloadKind")
    return value


def _require_result_status(
    value: object | None,
    field_name: str,
) -> ProviderCacheResultStatus | None:
    if value is None:
        return None
    if type(value) is not ProviderCacheResultStatus:
        raise ValueError(f"{field_name} must be a ProviderCacheResultStatus")
    return value


@dataclass(frozen=True, slots=True)
class ProviderCacheLimits:
    """Bounded capacity and retention controls for a provider cache instance."""

    max_entry_payload_bytes: int
    max_entries_total: int
    max_payload_bytes_total: int
    expired_prune_batch_size: int

    def __post_init__(self) -> None:
        max_entry_payload_bytes = _require_positive(
            self.max_entry_payload_bytes,
            "max_entry_payload_bytes",
        )
        max_entries_total = _require_positive(self.max_entries_total, "max_entries_total")
        max_payload_bytes_total = _require_positive(
            self.max_payload_bytes_total,
            "max_payload_bytes_total",
        )
        expired_prune_batch_size = _require_positive(
            self.expired_prune_batch_size,
            "expired_prune_batch_size",
        )
        object.__setattr__(
            self,
            "max_entry_payload_bytes",
            max_entry_payload_bytes,
        )
        object.__setattr__(self, "max_entries_total", max_entries_total)
        object.__setattr__(
            self,
            "max_payload_bytes_total",
            max_payload_bytes_total,
        )
        object.__setattr__(
            self,
            "expired_prune_batch_size",
            expired_prune_batch_size,
        )
        if max_entry_payload_bytes > max_payload_bytes_total:
            raise ValueError(
                "max_entry_payload_bytes must be <= max_payload_bytes_total"
            )


@dataclass(frozen=True, slots=True)
class ProviderCacheContentSlot:
    """Normalized provider content snapshot for one source-cache key."""

    content_status: ProviderCacheResultStatus | None = None
    payload_kind: ProviderCachePayloadKind = ProviderCachePayloadKind.NONE
    payload_codec: str | None = None
    payload_bytes: bytes | None = None
    payload_bytes_sha256: str | None = None
    content_http_status: int | None = None
    content_fetched_at: datetime | None = None
    content_fresh_until_at: datetime | None = None
    content_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        payload_kind = _require_payload_kind(self.payload_kind, "payload_kind")
        content_status = _require_result_status(self.content_status, "content_status")
        object.__setattr__(self, "payload_kind", payload_kind)
        object.__setattr__(self, "content_status", content_status)

        if content_status is None:
            if payload_kind is not ProviderCachePayloadKind.NONE:
                raise ValueError("content_status must exist when payload_kind is set")
            if self.payload_codec is not None:
                raise ValueError("payload_codec must be None for empty content slot")
            if self.payload_bytes is not None:
                raise ValueError("payload_bytes must be None for empty content slot")
            if self.payload_bytes_sha256 is not None:
                raise ValueError("payload_bytes_sha256 must be None for empty content slot")
            if (
                self.content_http_status is not None
                or self.content_fetched_at is not None
                or self.content_fresh_until_at is not None
                or self.content_expires_at is not None
            ):
                raise ValueError("empty content slot must not carry content metadata")
            return

        if content_status not in {
            ProviderCacheResultStatus.SUCCESS,
            ProviderCacheResultStatus.NOT_FOUND,
        }:
            raise ValueError("content_status must be SUCCESS or NOT_FOUND")

        if payload_kind is ProviderCachePayloadKind.NONE:
            if content_status is ProviderCacheResultStatus.SUCCESS:
                raise ValueError("SUCCESS requires a non-NONE payload")
            if self.payload_codec is not None:
                raise ValueError("payload_codec must be None when payload_kind is NONE")
            if self.payload_bytes is not None:
                raise ValueError("payload_bytes must be None when payload_kind is NONE")
            if self.payload_bytes_sha256 is not None:
                raise ValueError(
                    "payload_bytes_sha256 must be None when payload_kind is NONE"
                )
        else:
            payload_codec = _require_payload_codec(self.payload_codec, "payload_codec")
            object.__setattr__(self, "payload_codec", payload_codec)
            if type(self.payload_bytes) is not bytes:
                raise ValueError("payload_bytes must be bytes for non-NONE payloads")
            if not self.payload_bytes:
                raise ValueError("payload_bytes must be non-empty for non-NONE payloads")
            payload_bytes_sha256 = _require_sha256(
                self.payload_bytes_sha256,
                "payload_bytes_sha256",
            )
            if payload_bytes_sha256 != sha256(self.payload_bytes).hexdigest():
                raise ValueError("payload_bytes_sha256 must match payload_bytes")
            object.__setattr__(self, "payload_bytes_sha256", payload_bytes_sha256)

        if self.content_fetched_at is None:
            raise ValueError("content_fetched_at is required for content_status")
        if self.content_fresh_until_at is None:
            raise ValueError("content_fresh_until_at is required for content_status")
        if self.content_expires_at is None:
            raise ValueError("content_expires_at is required for content_status")
        object.__setattr__(
            self,
            "content_fetched_at",
            _require_utc(self.content_fetched_at, "content_fetched_at"),
        )
        object.__setattr__(
            self,
            "content_fresh_until_at",
            _require_utc(self.content_fresh_until_at, "content_fresh_until_at"),
        )
        object.__setattr__(
            self,
            "content_expires_at",
            _require_utc(self.content_expires_at, "content_expires_at"),
        )

        if not (
            self.content_fetched_at
            <= self.content_fresh_until_at
            <= self.content_expires_at
        ):
            raise ValueError("content timeline must be fetched <= fresh_until <= expires")
        if self.content_http_status is not None:
            object.__setattr__(
                self,
                "content_http_status",
                _require_http_status(self.content_http_status, "content_http_status"),
            )

    def __repr__(self) -> str:
        return (
            "ProviderCacheContentSlot("
            f"content_status={self.content_status!r}, "
            f"payload_kind={self.payload_kind!r}, "
            f"payload_codec={self.payload_codec!r}, "
            f"content_http_status={self.content_http_status!r}, "
            f"content_fetched_at={self.content_fetched_at!r}, "
            f"content_fresh_until_at={self.content_fresh_until_at!r}, "
            f"content_expires_at={self.content_expires_at!r})"
        )


@dataclass(frozen=True, slots=True)
class ProviderCacheFailureSlot:
    """Technical failure details for a failed provider fetch."""

    failure_status: ProviderCacheResultStatus | None = None
    failure_http_status: int | None = None
    failure_at: datetime | None = None
    failure_retry_after_at: datetime | None = None
    failure_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        failure_status = _require_result_status(self.failure_status, "failure_status")
        object.__setattr__(self, "failure_status", failure_status)

        if failure_status is None:
            if (
                self.failure_http_status is not None
                or self.failure_at is not None
                or self.failure_retry_after_at is not None
                or self.failure_expires_at is not None
            ):
                raise ValueError("empty failure slot cannot carry failure metadata")
            return

        if failure_status in {
            ProviderCacheResultStatus.SUCCESS,
            ProviderCacheResultStatus.NOT_FOUND,
        }:
            raise ValueError("failure_status cannot be SUCCESS or NOT_FOUND")

        if self.failure_at is None:
            raise ValueError("failure_at is required for failure_status")
        if self.failure_expires_at is None:
            raise ValueError("failure_expires_at is required for failure_status")
        object.__setattr__(
            self, "failure_at", _require_utc(self.failure_at, "failure_at")
        )
        object.__setattr__(
            self,
            "failure_expires_at",
            _require_utc(self.failure_expires_at, "failure_expires_at"),
        )
        if self.failure_at > self.failure_expires_at:
            raise ValueError("failure_at must be before or equal to failure_expires_at")

        if self.failure_retry_after_at is not None:
            object.__setattr__(
                self,
                "failure_retry_after_at",
                _require_utc(
                    self.failure_retry_after_at,
                    "failure_retry_after_at",
                ),
            )
            if failure_status is not ProviderCacheResultStatus.RATE_LIMITED:
                raise ValueError("failure_retry_after_at is only valid for RATE_LIMITED")
            if (
                self.failure_at
                > self.failure_retry_after_at
                or self.failure_retry_after_at > self.failure_expires_at
            ):
                raise ValueError(
                    "failure_retry_after_at must be between failure_at and failure_expires_at"
                )

        if self.failure_http_status is not None:
            object.__setattr__(
                self,
                "failure_http_status",
                _require_http_status(self.failure_http_status, "failure_http_status"),
            )

    def __repr__(self) -> str:
        return (
            "ProviderCacheFailureSlot("
            f"failure_status={self.failure_status!r}, "
            f"failure_http_status={self.failure_http_status!r}, "
            f"failure_at={self.failure_at!r}, "
            f"failure_retry_after_at={self.failure_retry_after_at!r}, "
            f"failure_expires_at={self.failure_expires_at!r})"
        )


@dataclass(frozen=True, slots=True)
class ProviderCacheSlots:
    """Pairing of content and failure slots for one cache entry."""

    content_slot: ProviderCacheContentSlot | None = None
    failure_slot: ProviderCacheFailureSlot | None = None

    def __post_init__(self) -> None:
        if (
            self.content_slot is not None
            and type(self.content_slot) is not ProviderCacheContentSlot
        ):
            raise ValueError("content_slot must be a ProviderCacheContentSlot")
        if (
            self.failure_slot is not None
            and type(self.failure_slot) is not ProviderCacheFailureSlot
        ):
            raise ValueError("failure_slot must be a ProviderCacheFailureSlot")
        if (
            self.content_slot is not None
            and self.content_slot.content_status is None
        ):
            raise ValueError("content_slot must include a content_status")
        if (
            self.failure_slot is not None
            and self.failure_slot.failure_status is None
        ):
            raise ValueError("failure_slot must include a failure_status")

        has_content_status = (
            self.content_slot is not None and self.content_slot.content_status is not None
        )
        has_failure_status = (
            self.failure_slot is not None and self.failure_slot.failure_status is not None
        )
        if not (has_content_status or has_failure_status):
            raise ValueError("at least one slot must be present")
