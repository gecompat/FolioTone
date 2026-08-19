"""SQLite-backed persistence for provider cache entries."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from foliotone.enrichment.provider_cache_contracts import (
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCacheLimits,
    ProviderCachePayloadKind,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    provider_source_cache_key,
)
from foliotone.enrichment.provider_cache_runtime import (
    ProviderCachePort,
    ProviderCacheRuntimeEntry,
    ProviderCacheRuntimeWrite,
)
from foliotone.persistence import w3_schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db

ProviderCacheClock = Callable[[], datetime]

PROVIDER_CACHE_CONTENT_DOMAIN: Final = "foliotone:provider-cache-content/v1"
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_TECHNICAL_ID_RE = re.compile(r"[a-z0-9._-]+")
_TECHNICAL_VERSION_SEGMENT_RE = re.compile(r"[a-z0-9._-]+")
_MAX_KEY_COMPONENT_LENGTH: Final = 128


class ProviderCacheStoreError(RuntimeError):
    """Base class for provider cache persistence errors."""


class ProviderCacheStoreConflictError(ProviderCacheStoreError):
    """Raised when a concurrent writer already advanced the generation."""

    def __init__(self, current: ProviderCacheStoreEntry | None) -> None:
        super().__init__("provider-cache generation mismatch")
        self.current = current


class ProviderCacheStoreCapacityError(ProviderCacheStoreError):
    """Raised when a write would exceed configured storage capacity."""

    def __init__(self) -> None:
        super().__init__("CACHE_CAPACITY_EXCEEDED")


@dataclass(frozen=True, slots=True)
class ProviderCacheStoreCandidate:
    """A candidate payload for one cache write."""

    source_cache_key: str
    provider_id: str
    provider_adapter_version: str
    query_fingerprint: str
    provider_source_version: str
    slots: ProviderCacheSlots

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_cache_key",
            _require_cache_key(self.source_cache_key, "source_cache_key"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _require_technical_id(self.provider_id, "provider_id"),
        )
        object.__setattr__(
            self,
            "provider_adapter_version",
            _require_technical_version(
                self.provider_adapter_version,
                "provider_adapter_version",
            ),
        )
        object.__setattr__(
            self,
            "query_fingerprint",
            _require_query_fingerprint(self.query_fingerprint, "query_fingerprint"),
        )
        object.__setattr__(
            self,
            "provider_source_version",
            _require_technical_version(
                self.provider_source_version,
                "provider_source_version",
            ),
        )
        if type(self.slots) is not ProviderCacheSlots:
            raise ValueError("slots must be a ProviderCacheSlots")
        expected_source_cache_key = provider_source_cache_key(
            provider_id=self.provider_id,
            provider_adapter_version=self.provider_adapter_version,
            query_fingerprint=self.query_fingerprint,
            provider_source_version=self.provider_source_version,
        )
        if self.source_cache_key != expected_source_cache_key:
            raise ValueError("source_cache_key must match canonical provider_source_cache_key")


@dataclass(frozen=True, slots=True)
class ProviderCacheStoreEntry(ProviderCacheStoreCandidate):
    """Persisted cache snapshot with content hash and fencing generation."""

    generation: int
    content_hash: str

    def __post_init__(self) -> None:
        ProviderCacheStoreCandidate.__post_init__(self)
        generation = _require_non_negative_int(self.generation, "generation")
        if generation <= 0:
            raise ValueError("generation must be a positive integer")
        object.__setattr__(self, "generation", generation)
        object.__setattr__(
            self,
            "content_hash",
            _require_content_hash(self.content_hash, "content_hash"),
        )


class ProviderCacheStorePort(ProviderCachePort):
    """Adapt `SQLiteProviderCacheStore` to the public runtime cache port."""

    def __init__(
        self,
        store: SQLiteProviderCacheStore,
        *,
        provider_id: str,
        provider_adapter_version: str,
        provider_source_version: str,
        query_fingerprint: str,
    ) -> None:
        if not isinstance(store, SQLiteProviderCacheStore):
            raise ValueError("store must be a SQLiteProviderCacheStore")
        self._store = store
        self._provider_id = provider_id
        self._provider_adapter_version = provider_adapter_version
        self._provider_source_version = provider_source_version
        self._query_fingerprint = query_fingerprint
        self._source_cache_key = provider_source_cache_key(
            provider_id=provider_id,
            provider_adapter_version=provider_adapter_version,
            query_fingerprint=query_fingerprint,
            provider_source_version=provider_source_version,
        )

    def get(self, source_cache_key: str) -> ProviderCacheRuntimeEntry | None:
        _validate_source_cache_key(source_cache_key, self._source_cache_key)
        entry = self._store.get(source_cache_key)
        if entry is None:
            return None
        return _entry_to_runtime_entry(entry)

    def compare_and_replace(
        self,
        source_cache_key: str,
        *,
        slots: ProviderCacheSlots,
        payload: object | None,
        expected_generation: int,
    ) -> ProviderCacheRuntimeWrite:
        _validate_source_cache_key(source_cache_key, self._source_cache_key)
        _validate_payload_slots(payload, slots)
        candidate = ProviderCacheStoreCandidate(
            source_cache_key=source_cache_key,
            provider_id=self._provider_id,
            provider_adapter_version=self._provider_adapter_version,
            query_fingerprint=self._query_fingerprint,
            provider_source_version=self._provider_source_version,
            slots=slots,
        )
        expected_generation = _require_non_negative_int(
            expected_generation,
            "expected_generation",
        )
        try:
            written = self._store.compare_and_replace(candidate, expected_generation)
            return ProviderCacheRuntimeWrite(
                True,
                _entry_to_runtime_entry(written, payload),
            )
        except ProviderCacheStoreConflictError as error:
            current = error.current
            if current is None:
                current = self._store.get(self._source_cache_key)
            if current is None:
                raise error
            return ProviderCacheRuntimeWrite(False, _entry_to_runtime_entry(current))


class SQLiteProviderCacheStore:
    """Atomic cache store with bounded retention pruning and CAS write contract."""

    def __init__(
        self,
        engine: Engine,
        limits: ProviderCacheLimits,
        *,
        clock: ProviderCacheClock | None = None,
    ) -> None:
        self._engine = engine
        if type(limits) is not ProviderCacheLimits:
            raise ValueError("limits must be a ProviderCacheLimits")
        self._limits = limits
        self._clock = clock

    def get(self, source_cache_key: str) -> ProviderCacheStoreEntry | None:
        """Load one cache entry by its source key."""

        source_cache_key = _require_cache_key(source_cache_key, "source_cache_key")
        table = w3_schema.provider_cache_entries
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(table).where(table.c.source_cache_key == source_cache_key)
                )
                .mappings()
                .one_or_none()
            )
        return (
            None if row is None else _row_to_entry(row, self._limits.max_entry_payload_bytes)
        )

    def compare_and_replace(
        self,
        entry: ProviderCacheStoreCandidate,
        expected_generation: int,
    ) -> ProviderCacheStoreEntry:
        """Write or replace `entry` via a CAS and bounded-rollback transaction."""

        if type(entry) is not ProviderCacheStoreCandidate:
            raise ValueError("entry must be a ProviderCacheStoreCandidate")
        limits = self._limits
        expected_generation = _require_non_negative_int(
            expected_generation,
            "expected_generation",
        )
        now = _require_utc(_default_now(self._clock), "clock")
        staged_payload = _slot_payload_bytes(entry.slots)
        if staged_payload > limits.max_entry_payload_bytes:
            raise ProviderCacheStoreCapacityError()

        staged_generation = expected_generation + 1
        staged_hash = provider_cache_content_hash(entry)
        staged = ProviderCacheStoreEntry(
            source_cache_key=entry.source_cache_key,
            provider_id=entry.provider_id,
            provider_adapter_version=entry.provider_adapter_version,
            query_fingerprint=entry.query_fingerprint,
            provider_source_version=entry.provider_source_version,
            slots=entry.slots,
            generation=staged_generation,
            content_hash=staged_hash,
        )
        table = w3_schema.provider_cache_entries

        with self._engine.begin() as connection:
            self._acquire_writer_lock(connection, staged.source_cache_key)
            self._prune_expired(
                connection,
                now=now,
                limit=limits.expired_prune_batch_size,
                except_source_cache_key=entry.source_cache_key,
            )
            current = self._get(connection, staged.source_cache_key)
            if current is None:
                if expected_generation != 0:
                    raise ProviderCacheStoreConflictError(None)
                projected_count = self._entry_count(connection) + 1
                projected_payload_bytes = self._payload_total(connection) + staged_payload
            else:
                if current.generation != expected_generation:
                    raise ProviderCacheStoreConflictError(current)
                current_payload = _slot_payload_bytes(current.slots)
                projected_count = self._entry_count(connection)
                projected_payload_bytes = (
                    self._payload_total(connection)
                    - current_payload
                    + staged_payload
                )

            if projected_count > limits.max_entries_total:
                raise ProviderCacheStoreCapacityError()
            if projected_payload_bytes > limits.max_payload_bytes_total:
                raise ProviderCacheStoreCapacityError()

            row = _entry_to_row(staged)
            if current is None:
                try:
                    connection.execute(insert(table).values(**row))
                except IntegrityError as error:
                    if _key_already_exists(connection, staged.source_cache_key):
                        latest = self._get(connection, staged.source_cache_key)
                        raise ProviderCacheStoreConflictError(latest) from error
                    raise
            else:
                result = connection.execute(
                    update(table)
                    .where(
                        table.c.source_cache_key == staged.source_cache_key,
                        table.c.generation == expected_generation,
                    )
                    .values(**row)
                )
                if result.rowcount != 1:
                    latest = self._get(connection, staged.source_cache_key)
                    raise ProviderCacheStoreConflictError(latest)

        return staged

    def _prune_expired(
        self,
        connection: Connection,
        now: datetime,
        limit: int,
        except_source_cache_key: str,
    ) -> None:
        table = w3_schema.provider_cache_entries
        keys = (
            connection.execute(
                select(table.c.source_cache_key)
                .where(
                    table.c.retention_until_at <= datetime_to_db(now),
                    table.c.source_cache_key != except_source_cache_key,
                )
                .order_by(
                    table.c.retention_until_at,
                    table.c.source_cache_key,
                )
                .limit(limit)
            )
            .scalars()
            .all()
        )
        if not keys:
            return
        connection.execute(delete(table).where(table.c.source_cache_key.in_(keys)))

    def _get(self, connection: Connection, source_cache_key: str) -> ProviderCacheStoreEntry | None:
        row = (
            connection.execute(
                select(w3_schema.provider_cache_entries).where(
                    w3_schema.provider_cache_entries.c.source_cache_key == source_cache_key
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _row_to_entry(
            row, self._limits.max_entry_payload_bytes
        )

    @staticmethod
    def _entry_count(connection: Connection) -> int:
        table = w3_schema.provider_cache_entries
        count = connection.execute(select(func.count()).select_from(table)).scalar_one()
        return int(count)

    @staticmethod
    def _payload_total(connection: Connection) -> int:
        table = w3_schema.provider_cache_entries
        total = connection.execute(
            select(func.coalesce(func.sum(func.length(table.c.payload_bytes)), 0))
        ).scalar_one()
        return int(0 if total is None else total)

    @staticmethod
    def _acquire_writer_lock(connection: Connection, source_cache_key: str) -> None:
        connection.execute(
            update(w3_schema.provider_cache_entries)
            .where(w3_schema.provider_cache_entries.c.source_cache_key == source_cache_key)
            .values(generation=w3_schema.provider_cache_entries.c.generation)
        )


def canonical_provider_cache_content_payload(
    candidate: ProviderCacheStoreCandidate,
) -> dict[str, object]:
    """Build the canonical payload used by `provider_cache_content_hash`."""

    if not isinstance(candidate, ProviderCacheStoreCandidate):
        raise ValueError("candidate must be a ProviderCacheStoreCandidate")
    content_slot = candidate.slots.content_slot
    failure_slot = candidate.slots.failure_slot
    content = _serialize_content_slot(content_slot)
    failure = _serialize_failure_slot(failure_slot)
    return {
        "domain": PROVIDER_CACHE_CONTENT_DOMAIN,
        "provider_adapter_version": candidate.provider_adapter_version,
        "provider_id": candidate.provider_id,
        "provider_source_version": candidate.provider_source_version,
        "query_fingerprint": candidate.query_fingerprint,
        "content_status": content["content_status"],
        "content_fetched_at": content["content_fetched_at"],
        "content_fresh_until_at": content["content_fresh_until_at"],
        "content_expires_at": content["content_expires_at"],
        "content_http_status": content["content_http_status"],
        "payload_kind": content["payload_kind"],
        "payload_codec": content["payload_codec"],
        "payload_bytes_length": content["payload_bytes_length"],
        "payload_bytes_sha256": content["payload_bytes_sha256"],
        "failure_status": failure["failure_status"],
        "failure_http_status": failure["failure_http_status"],
        "failure_at": failure["failure_at"],
        "failure_retry_after_at": failure["failure_retry_after_at"],
        "failure_expires_at": failure["failure_expires_at"],
    }


def canonical_provider_cache_content_bytes(
    candidate: ProviderCacheStoreCandidate,
) -> bytes:
    """Serialize canonical JSON payload bytes."""

    return json.dumps(
        canonical_provider_cache_content_payload(candidate),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def provider_cache_content_hash(candidate: ProviderCacheStoreCandidate) -> str:
    """Compute canonical payload SHA-256 for one cache candidate."""

    return hashlib.sha256(canonical_provider_cache_content_bytes(candidate)).hexdigest()


def _validate_source_cache_key(
    source_cache_key: str,
    expected_source_cache_key: str,
) -> None:
    source_cache_key = _require_cache_key(source_cache_key, "source_cache_key")
    if source_cache_key != expected_source_cache_key:
        raise ValueError("source_cache_key must match configured provider components")


def _validate_payload_slots(payload: object | None, slots: ProviderCacheSlots) -> None:
    content_slot = slots.content_slot
    if payload is None:
        if (
            content_slot is not None
            and content_slot.payload_kind is not ProviderCachePayloadKind.NONE
        ):
            raise ValueError("payload required for non-NONE content")
        return
    if type(payload) is not bytes:
        raise ValueError("payload must be bytes")
    if content_slot is None:
        raise ValueError("payload requires a content slot")
    if content_slot.payload_kind is ProviderCachePayloadKind.NONE:
        raise ValueError("payload not allowed for NONE payload kind")
    if content_slot.payload_bytes is None:
        raise ValueError("content slot payload bytes required for non-NONE payload kind")
    if content_slot.payload_bytes_sha256 != hashlib.sha256(payload).hexdigest():
        raise ValueError("payload does not match content slot hash")
    if content_slot.payload_bytes != payload:
        raise ValueError("payload must match persisted content bytes")


def _entry_to_runtime_entry(
    entry: ProviderCacheStoreEntry,
    payload: object | None = None,
) -> ProviderCacheRuntimeEntry:
    runtime_payload = payload
    content_slot = entry.slots.content_slot
    if content_slot is None:
        if runtime_payload is not None:
            raise ValueError("payload must be none when content slot is absent")
        return ProviderCacheRuntimeEntry(entry.generation, entry.slots, None)

    if runtime_payload is None:
        if content_slot.payload_kind is not ProviderCachePayloadKind.NONE:
            payload_bytes = content_slot.payload_bytes
            if payload_bytes is None:
                raise ValueError("payload bytes missing for non-NONE content slot")
            runtime_payload = payload_bytes
        else:
            runtime_payload = None

    if content_slot.payload_kind is ProviderCachePayloadKind.NONE and runtime_payload is not None:
        raise ValueError("payload must be none for NONE payload kind")
    if content_slot.payload_kind is not ProviderCachePayloadKind.NONE:
        if type(runtime_payload) is not bytes:
            raise ValueError("runtime entry payload must be bytes")
        if content_slot.payload_bytes != runtime_payload:
            raise ValueError("payload bytes mismatch")

    return ProviderCacheRuntimeEntry(entry.generation, entry.slots, runtime_payload)


def _row_to_entry(
    row: RowMapping,
    max_entry_payload_bytes: int,
) -> ProviderCacheStoreEntry:
    entry = ProviderCacheStoreEntry(
        source_cache_key=_require_cache_key(str(row["source_cache_key"]), "source_cache_key"),
        provider_id=_require_stripped(row["provider_id"], "provider_id"),
        provider_adapter_version=_require_stripped(
            row["provider_adapter_version"],
            "provider_adapter_version",
        ),
        query_fingerprint=_require_query_fingerprint(
            row["query_fingerprint"],
            "query_fingerprint",
        ),
        provider_source_version=_require_stripped(
            row["provider_source_version"],
            "provider_source_version",
        ),
        slots=ProviderCacheSlots(
            content_slot=_row_to_content_slot(row),
            failure_slot=_row_to_failure_slot(row),
        ),
        generation=_require_non_negative_int(row["generation"], "generation"),
        content_hash=_require_content_hash(row["content_hash"], "content_hash"),
    )
    if provider_cache_content_hash(entry) != entry.content_hash:
        raise ValueError("content hash mismatch")
    content_slot = entry.slots.content_slot
    if content_slot is not None and content_slot.payload_bytes is not None:
        if len(content_slot.payload_bytes) > max_entry_payload_bytes:
            raise ValueError("cached payload exceeds max_entry_payload_bytes")
    return entry


def _serialize_content_slot(slot: ProviderCacheContentSlot | None) -> dict[str, object]:
    if slot is None:
        return {
            "content_status": None,
            "content_fetched_at": None,
            "content_fresh_until_at": None,
            "content_expires_at": None,
            "content_http_status": None,
            "payload_kind": ProviderCachePayloadKind.NONE.value,
            "payload_codec": None,
            "payload_bytes_length": None,
            "payload_bytes_sha256": None,
        }
    if slot.content_status is None:
        raise ValueError("content_status must be present for non-empty content slot")
    return {
        "content_status": slot.content_status.value,
        "content_fetched_at": _serialize_timestamp(slot.content_fetched_at),
        "content_fresh_until_at": _serialize_timestamp(slot.content_fresh_until_at),
        "content_expires_at": _serialize_timestamp(slot.content_expires_at),
        "content_http_status": slot.content_http_status,
        "payload_kind": slot.payload_kind.value,
        "payload_codec": slot.payload_codec,
        "payload_bytes_length": None if slot.payload_bytes is None else len(slot.payload_bytes),
        "payload_bytes_sha256": slot.payload_bytes_sha256,
    }


def _serialize_failure_slot(slot: ProviderCacheFailureSlot | None) -> dict[str, object]:
    if slot is None:
        return {
            "failure_status": None,
            "failure_http_status": None,
            "failure_at": None,
            "failure_retry_after_at": None,
            "failure_expires_at": None,
        }
    if slot.failure_status is None:
        raise ValueError("failure_status must be present for non-empty failure slot")
    return {
        "failure_status": slot.failure_status.value,
        "failure_http_status": slot.failure_http_status,
        "failure_at": _serialize_timestamp(slot.failure_at),
        "failure_retry_after_at": (
            None
            if slot.failure_retry_after_at is None
            else _serialize_timestamp(slot.failure_retry_after_at)
        ),
        "failure_expires_at": _serialize_timestamp(slot.failure_expires_at),
    }


def _row_to_content_slot(row: RowMapping) -> ProviderCacheContentSlot | None:
    if row["content_status"] is None:
        return None
    return ProviderCacheContentSlot(
        content_status=ProviderCacheResultStatus(str(row["content_status"])),
        payload_kind=ProviderCachePayloadKind(str(row["payload_kind"])),
        payload_codec=None if row["payload_codec"] is None else str(row["payload_codec"]),
        payload_bytes=None if row["payload_bytes"] is None else bytes(row["payload_bytes"]),
        payload_bytes_sha256=None
        if row["payload_bytes_sha256"] is None
        else str(row["payload_bytes_sha256"]),
        content_http_status=(
            None if row["content_http_status"] is None else int(row["content_http_status"])
        ),
        content_fetched_at=_required_datetime(row["content_fetched_at"], "content_fetched_at"),
        content_fresh_until_at=_required_datetime(
            row["content_fresh_until_at"],
            "content_fresh_until_at",
        ),
        content_expires_at=_required_datetime(row["content_expires_at"], "content_expires_at"),
    )


def _row_to_failure_slot(row: RowMapping) -> ProviderCacheFailureSlot | None:
    if row["failure_status"] is None:
        return None
    return ProviderCacheFailureSlot(
        failure_status=ProviderCacheResultStatus(str(row["failure_status"])),
        failure_http_status=(
            None if row["failure_http_status"] is None else int(row["failure_http_status"])
        ),
        failure_at=_required_datetime(row["failure_at"], "failure_at"),
        failure_retry_after_at=_optional_datetime(
            row["failure_retry_after_at"],
            "failure_retry_after_at",
        ),
        failure_expires_at=_required_datetime(row["failure_expires_at"], "failure_expires_at"),
    )


def _entry_to_row(entry: ProviderCacheStoreEntry) -> dict[str, object]:
    row: dict[str, object] = {
        "source_cache_key": entry.source_cache_key,
        "provider_id": entry.provider_id,
        "provider_adapter_version": entry.provider_adapter_version,
        "provider_source_version": entry.provider_source_version,
        "query_fingerprint": entry.query_fingerprint,
        "generation": entry.generation,
        "content_hash": entry.content_hash,
    }
    content_slot = entry.slots.content_slot
    failure_slot = entry.slots.failure_slot

    if content_slot is None:
        row.update(
            {
                "content_status": None,
                "payload_kind": ProviderCachePayloadKind.NONE.value,
                "payload_codec": None,
                "payload_bytes": None,
                "payload_bytes_sha256": None,
                "content_http_status": None,
                "content_fetched_at": None,
                "content_fresh_until_at": None,
                "content_expires_at": None,
            }
        )
    else:
        if content_slot.content_status is None:
            raise ValueError("content_status must be present for non-empty content slot")
        row.update(
            {
                "content_status": content_slot.content_status.value,
                "payload_kind": content_slot.payload_kind.value,
                "payload_codec": content_slot.payload_codec,
                "payload_bytes": content_slot.payload_bytes,
                "payload_bytes_sha256": content_slot.payload_bytes_sha256,
                "content_http_status": content_slot.content_http_status,
                "content_fetched_at": datetime_to_db(content_slot.content_fetched_at),
                "content_fresh_until_at": datetime_to_db(content_slot.content_fresh_until_at),
                "content_expires_at": datetime_to_db(content_slot.content_expires_at),
            }
        )

    if failure_slot is None:
        row.update(
            {
                "failure_status": None,
                "failure_http_status": None,
                "failure_at": None,
                "failure_retry_after_at": None,
                "failure_expires_at": None,
            }
        )
    else:
        if failure_slot.failure_status is None:
            raise ValueError("failure_status must be present for non-empty failure slot")
        row.update(
            {
                "failure_status": failure_slot.failure_status.value,
                "failure_http_status": failure_slot.failure_http_status,
                "failure_at": datetime_to_db(failure_slot.failure_at),
                "failure_retry_after_at": (
                    None
                    if failure_slot.failure_retry_after_at is None
                    else datetime_to_db(failure_slot.failure_retry_after_at)
                ),
                "failure_expires_at": datetime_to_db(failure_slot.failure_expires_at),
            }
        )
    return row


def _serialize_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _require_utc(value, "timestamp").strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _required_datetime(value: object, field_name: str) -> datetime:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if type(value) is str:
        return _require_utc(required_datetime_from_db(value), field_name)
    raise ValueError(f"{field_name} must be ISO-8601 UTC string")


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if type(value) is str:
        return _require_utc(required_datetime_from_db(value), field_name)
    raise ValueError(f"{field_name} must be ISO-8601 UTC string")


def _slot_payload_bytes(slots: ProviderCacheSlots) -> int:
    if slots.content_slot is None:
        return 0
    if slots.content_slot.payload_bytes is None:
        return 0
    return len(slots.content_slot.payload_bytes)


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _require_stripped(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = _normalize_text(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(normalized) > _MAX_KEY_COMPONENT_LENGTH:
        raise ValueError(f"{field_name} must not exceed {_MAX_KEY_COMPONENT_LENGTH} characters")
    return normalized


def _require_cache_key(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    normalized = _normalize_text(value)
    if _HEX64_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return normalized


def _require_query_fingerprint(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    normalized = _normalize_text(value)
    if _HEX64_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return normalized


def _require_content_hash(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    normalized = _normalize_text(value)
    if _HEX64_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return normalized


def _require_technical_id(value: object, field_name: str) -> str:
    normalized = _require_stripped(value, field_name)
    if "\\" in normalized or ":" in normalized:
        raise ValueError(f"{field_name} must be lowercase technical identifier")
    if any(ch.isspace() for ch in normalized):
        raise ValueError(f"{field_name} must be lowercase technical identifier")
    if _TECHNICAL_ID_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase technical identifier")
    return normalized


def _require_technical_version(value: object, field_name: str) -> str:
    normalized = _require_stripped(value, field_name)
    if "\\" in normalized or ":" in normalized:
        raise ValueError(f"{field_name} must be a version token")
    if any(ch.isspace() for ch in normalized):
        raise ValueError(f"{field_name} must be a version token")
    if normalized.startswith("/") or normalized.endswith("/"):
        raise ValueError(f"{field_name} must be a version token")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field_name} must be a version token")
    for part in parts:
        if _TECHNICAL_VERSION_SEGMENT_RE.fullmatch(part) is None:
            raise ValueError(f"{field_name} must be a version token")
    return normalized


def _require_non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _require_utc(value: datetime, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise ValueError(f"{field_name} must be UTC")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)


def _default_now(clock: ProviderCacheClock | None) -> datetime:
    return datetime.now(UTC) if clock is None else clock()


def _key_already_exists(connection: Connection, source_cache_key: str) -> bool:
    return (
        connection.execute(
            select(w3_schema.provider_cache_entries.c.source_cache_key).where(
                w3_schema.provider_cache_entries.c.source_cache_key == source_cache_key
            )
        ).scalar_one_or_none()
        is not None
    )


__all__ = [
    "ProviderCacheClock",
    "ProviderCacheStoreCandidate",
    "ProviderCacheStorePort",
    "ProviderCacheStoreCapacityError",
    "ProviderCacheStoreConflictError",
    "ProviderCacheStoreEntry",
    "ProviderCacheStoreError",
    "SQLiteProviderCacheStore",
    "canonical_provider_cache_content_bytes",
    "canonical_provider_cache_content_payload",
    "provider_cache_content_hash",
]
