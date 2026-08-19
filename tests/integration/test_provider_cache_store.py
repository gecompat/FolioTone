"""Integration tests for provider-cache persistence contract."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, func, select, text, update

from foliotone.enrichment import (
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCacheLimits,
    ProviderCachePayloadKind,
    ProviderCacheResultProjection,
    ProviderCacheResultStatus,
    ProviderCacheSlots,
    project_provider_cache_status_to_slots,
    provider_source_cache_key,
)
from foliotone.persistence import create_sqlite_engine, w3_schema
from foliotone.persistence.provider_cache_store import (
    ProviderCacheStoreCandidate,
    ProviderCacheStoreCapacityError,
    ProviderCacheStoreConflictError,
    SQLiteProviderCacheStore,
    provider_cache_content_hash,
)


def _fingerprint(text_value: str) -> str:
    return sha256(text_value.encode("utf-8")).hexdigest()


def _source_key(query: str) -> str:
    return provider_source_cache_key(
        provider_id="provider",
        provider_adapter_version="v1",
        query_fingerprint=_fingerprint(query),
        provider_source_version="source-v1",
    )


def _slots(
    content_bytes: bytes,
    *,
    content_status: ProviderCacheResultStatus = ProviderCacheResultStatus.SUCCESS,
    with_failure: bool = False,
    fetched: datetime,
) -> ProviderCacheSlots:
    content_slot = ProviderCacheContentSlot(
        content_status=content_status,
        payload_kind=(
            ProviderCachePayloadKind.NONE
            if content_status is not ProviderCacheResultStatus.SUCCESS
            else ProviderCachePayloadKind.RAW_RESPONSE
        ),
        payload_codec=(
            None
            if content_status is not ProviderCacheResultStatus.SUCCESS
            else "json/raw-response"
        ),
        payload_bytes=(
            None if content_status is not ProviderCacheResultStatus.SUCCESS else content_bytes
        ),
        payload_bytes_sha256=(
            None
            if content_status is not ProviderCacheResultStatus.SUCCESS
            else sha256(content_bytes).hexdigest()
        ),
        content_http_status=200,
        content_fetched_at=fetched,
        content_fresh_until_at=fetched + timedelta(minutes=1),
        content_expires_at=fetched + timedelta(minutes=2),
    )
    failure_slot = None
    if with_failure:
        failure_slot = ProviderCacheFailureSlot(
            failure_status=ProviderCacheResultStatus.RATE_LIMITED,
            failure_http_status=429,
            failure_at=fetched,
            failure_retry_after_at=fetched + timedelta(minutes=1),
            failure_expires_at=fetched + timedelta(minutes=3),
        )
    return ProviderCacheSlots(content_slot=content_slot, failure_slot=failure_slot)


def _candidate(
    source_name: str,
    *,
    fetched: datetime,
    content_bytes: bytes = b"payload-bytes",
    with_failure: bool = False,
    content_status: ProviderCacheResultStatus = ProviderCacheResultStatus.SUCCESS,
) -> ProviderCacheStoreCandidate:
    return ProviderCacheStoreCandidate(
        source_cache_key=_source_key(source_name),
        provider_id="provider",
        provider_adapter_version="v1",
        query_fingerprint=_fingerprint(source_name),
        provider_source_version="source-v1",
        slots=_slots(
            content_bytes=content_bytes,
            content_status=content_status,
            with_failure=with_failure,
            fetched=fetched,
        ),
    )


def _projection_candidate(
    source_name: str,
    *,
    status: ProviderCacheResultStatus,
    fetched: datetime,
    content_bytes: bytes = b"payload-bytes",
    preserve_content_slot: ProviderCacheContentSlot | None = None,
) -> ProviderCacheStoreCandidate:
    projection = ProviderCacheResultProjection(
        fetched_at=fetched,
        positive_fresh_ttl=timedelta(minutes=2),
        positive_expires_ttl=timedelta(minutes=5),
        negative_fresh_ttl=timedelta(minutes=1),
        negative_expires_ttl=timedelta(minutes=1),
        technical_failure_expires_ttl=timedelta(minutes=1),
    )
    slots = project_provider_cache_status_to_slots(
        status,
        projection=projection,
        payload_bytes=(
            content_bytes if status is ProviderCacheResultStatus.SUCCESS else None
        ),
        payload_codec=(
            "json/raw-response" if status is ProviderCacheResultStatus.SUCCESS else None
        ),
        payload_bytes_sha256=(
            None
            if status is not ProviderCacheResultStatus.SUCCESS
            else sha256(content_bytes).hexdigest()
        ),
        payload_kind=(
            ProviderCachePayloadKind.RAW_RESPONSE
            if status is ProviderCacheResultStatus.SUCCESS
            else ProviderCachePayloadKind.NONE
        ),
        failure_retry_after_at=(
            fetched + timedelta(seconds=30)
            if status is ProviderCacheResultStatus.RATE_LIMITED
            else None
        ),
        preserve_content_slot=preserve_content_slot,
    )
    return ProviderCacheStoreCandidate(
        source_cache_key=_source_key(source_name),
        provider_id="provider",
        provider_adapter_version="v1",
        query_fingerprint=_fingerprint(source_name),
        provider_source_version="source-v1",
        slots=slots,
    )


def _limits(
    *,
    max_entries_total: int = 16,
    max_payload_bytes_total: int = 16_384,
    max_entry_payload_bytes: int = 8_192,
    expired_prune_batch_size: int = 16,
) -> ProviderCacheLimits:
    return ProviderCacheLimits(
        max_entry_payload_bytes=max_entry_payload_bytes,
        max_entries_total=max_entries_total,
        max_payload_bytes_total=max_payload_bytes_total,
        expired_prune_batch_size=expired_prune_batch_size,
    )


def _make_store(
    head_database: Path,
    *,
    limits: ProviderCacheLimits | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SQLiteProviderCacheStore:
    return SQLiteProviderCacheStore(
        create_sqlite_engine(head_database),
        _limits() if limits is None else limits,
        clock=clock,
    )


def _table_row_count(
    engine: Engine,
) -> int:
    with engine.connect() as connection:
        statement = select(func.count()).select_from(w3_schema.provider_cache_entries)
        return int(connection.execute(statement).scalar_one())


def test_provider_cache_store_hit_and_miss(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
    limits = _limits(max_entries_total=4)
    store = _make_store(head_database, limits=limits, clock=lambda: now)
    candidate = _candidate("hit", fetched=now)
    stored = store.compare_and_replace(candidate, expected_generation=0)
    got = store.get(candidate.source_cache_key)
    assert got == stored
    assert store.get("0" * 64) is None


def test_provider_cache_store_compare_and_replace_replaces_with_monotonic_generation(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 2, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    limits = _limits(max_entries_total=4)
    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: now)
    first = store.compare_and_replace(
        _candidate("replace", fetched=now, content_bytes=b"alpha"),
        expected_generation=0,
    )
    assert first.generation == 1
    second = store.compare_and_replace(
        _candidate("replace", fetched=now + timedelta(minutes=5), content_bytes=b"beta"),
        expected_generation=1,
    )
    assert second.generation == 2
    assert second.content_hash != first.content_hash
    fresh = store.get(second.source_cache_key)
    assert fresh is not None
    assert fresh.generation == 2
    assert fresh.content_hash == provider_cache_content_hash(
        _candidate("replace", fetched=now + timedelta(minutes=5), content_bytes=b"beta")
    )


def test_provider_cache_store_cas_conflict_returns_current_winner(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 5, tzinfo=UTC)
    limits = _limits(max_entries_total=4)
    store = _make_store(head_database, limits=limits, clock=lambda: now)
    installed = store.compare_and_replace(
        _candidate("conflict", fetched=now),
        expected_generation=0,
    )
    with pytest.raises(ProviderCacheStoreConflictError) as exc:
        store.compare_and_replace(
            _candidate("conflict", fetched=now + timedelta(minutes=1)),
            expected_generation=0,
        )
    assert exc.value.current == installed
    assert store.get(installed.source_cache_key) == installed


def test_provider_cache_store_capacity_failure_does_not_mutate(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    now = datetime(2026, 8, 19, 9, 6, tzinfo=UTC)
    limits = _limits(
        max_entries_total=1,
        max_payload_bytes_total=128,
        max_entry_payload_bytes=64,
        expired_prune_batch_size=1,
    )
    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: now)
    kept = store.compare_and_replace(
        _candidate("capacity-keep", fetched=now),
        expected_generation=0,
    )
    with pytest.raises(ProviderCacheStoreCapacityError):
        store.compare_and_replace(
            _candidate("capacity-fail", fetched=now),
            expected_generation=0,
        )
    assert _table_row_count(engine) == 1
    assert store.get(kept.source_cache_key) == kept


def test_provider_cache_store_prunes_expired_entries_in_stable_order(
    head_database: Path,
) -> None:
    setup_now = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
    now = datetime(2026, 8, 19, 9, 10, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    limits = _limits(
        max_entries_total=3,
        max_payload_bytes_total=4_096,
        max_entry_payload_bytes=1_024,
        expired_prune_batch_size=2,
    )
    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: setup_now)
    oldest = setup_now + timedelta(minutes=1)
    middle = setup_now + timedelta(minutes=2)
    newest = setup_now + timedelta(minutes=3)
    candidates = [
        _candidate("prune-oldest", fetched=oldest, content_bytes=b"A"),
        _candidate("prune-middle", fetched=middle, content_bytes=b"B"),
        _candidate("prune-newest", fetched=newest, content_bytes=b"C"),
    ]
    for candidate in candidates:
        store.compare_and_replace(candidate, expected_generation=0)

    ordered = sorted(
        (
            candidate.slots.content_slot.content_expires_at,
            candidate.source_cache_key,
        )
        for candidate in candidates
        if candidate.slots.content_slot is not None
    )
    expected_new_key = _source_key("prune-write")
    expected_pruned = {ordered[0][1], ordered[1][1]}
    expected_remaining = {
        candidate.source_cache_key
        for candidate in candidates
        if candidate.source_cache_key not in expected_pruned
    } | {expected_new_key}

    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: now)
    store.compare_and_replace(
        _candidate("prune-write", fetched=now, content_bytes=b"Z"),
        expected_generation=0,
    )

    with engine.connect() as connection:
        remaining_keys = {
            str(row[0])
            for row in connection.execute(
                select(w3_schema.provider_cache_entries.c.source_cache_key)
            ).all()
        }
    assert remaining_keys == expected_remaining
    # Stable order of pruning is tested via (retention_until, source_cache_key).
    assert expected_pruned == {item[1] for item in ordered[:2]}

    with engine.connect() as connection:
        query_plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT source_cache_key "
                "FROM provider_cache_entries "
                "WHERE retention_until_at <= :retention_until "
                "ORDER BY retention_until_at, source_cache_key "
                "LIMIT :limit"
            ),
            {
                "retention_until": now.isoformat(),
                "limit": limits.expired_prune_batch_size,
            },
        ).all()
    assert any(
        "ix_provider_cache_entries_retention_until_source_cache_key" in str(row[-1])
        for row in query_plan
    )


def test_provider_cache_store_rollback_reverts_prune_and_insert(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 8, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    limits = _limits(
        max_entries_total=1,
        max_payload_bytes_total=1_024,
        max_entry_payload_bytes=512,
        expired_prune_batch_size=1,
    )
    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: now)
    expired = _candidate("rollback-keep", fetched=now - timedelta(days=1), content_bytes=b"old")
    persisted = store.compare_and_replace(expired, expected_generation=0)

    assert _table_row_count(engine) == 1

    def _raise_on_provider_cache_write(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = statement.upper()
        if "INSERT INTO" in normalized and "PROVIDER_CACHE_ENTRIES" in normalized:
            raise RuntimeError("inject")
        compact = "".join(ch for ch in normalized if ch != " ")
        if (
            compact.startswith("UPDATEPROVIDER_CACHE_ENTRIES")
            and "GENERATION=PROVIDER_CACHE_ENTRIES.GENERATION" in compact
        ):
            return
        if (
            "UPDATE" in normalized
            and "PROVIDER_CACHE_ENTRIES" in normalized
            and "SET" in normalized
        ):
            raise RuntimeError("inject")

    event.listen(engine, "before_cursor_execute", _raise_on_provider_cache_write)
    try:
        with pytest.raises(RuntimeError, match="inject"):
            store.compare_and_replace(
                _candidate("rollback-new", fetched=now),
                expected_generation=0,
            )
    finally:
        event.remove(engine, "before_cursor_execute", _raise_on_provider_cache_write)

    assert _table_row_count(engine) == 1
    assert store.get(persisted.source_cache_key) == persisted


def test_provider_cache_store_concurrent_distinct_keys_serialize_for_capacity_contract(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 16, tzinfo=UTC)
    limits = _limits(max_entries_total=1)
    engine_one = create_sqlite_engine(head_database)
    engine_two = create_sqlite_engine(head_database)
    store_one = SQLiteProviderCacheStore(
        engine_one,
        limits,
        clock=lambda: now,
    )
    store_two = SQLiteProviderCacheStore(
        engine_two,
        limits,
        clock=lambda: now,
    )
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _attempt(store: SQLiteProviderCacheStore, source: str) -> None:
        barrier.wait()
        try:
            written = store.compare_and_replace(
                _candidate(source, fetched=now, content_bytes=source.encode("utf-8")),
                expected_generation=0,
            )
            with lock:
                outcomes.append(("ok", written))
        except ProviderCacheStoreCapacityError as exc:
            with lock:
                outcomes.append(("capacity", exc))
        except Exception as exc:  # pragma: no cover - assertion path
            with lock:
                outcomes.append(("other", exc))

    thread_one = threading.Thread(target=_attempt, args=(store_one, "concurrent-alpha"))
    thread_two = threading.Thread(target=_attempt, args=(store_two, "concurrent-beta"))
    thread_one.start()
    thread_two.start()
    thread_one.join(timeout=8)
    thread_two.join(timeout=8)
    assert not thread_one.is_alive()
    assert not thread_two.is_alive()
    assert len(outcomes) == 2
    oks = [outcome for outcome in outcomes if outcome[0] == "ok"]
    failures = [outcome for outcome in outcomes if outcome[0] != "ok"]
    assert len(oks) == 1
    assert len(failures) == 1
    assert isinstance(failures[0][1], ProviderCacheStoreCapacityError)
    assert _table_row_count(engine_one) == 1


def test_provider_cache_store_content_hash_and_payload_digest_roundtrip(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 9, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    store = _make_store(head_database, limits=_limits(), clock=lambda: now)
    candidate = _candidate("roundtrip", fetched=now, content_bytes=b"roundtrip-payload")
    written = store.compare_and_replace(candidate, expected_generation=0)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT payload_bytes_sha256, content_hash, payload_bytes, source_cache_key "
                "FROM provider_cache_entries "
                "WHERE source_cache_key = :source_cache_key"
            ),
            {"source_cache_key": written.source_cache_key},
        ).mappings().one()

    assert row["payload_bytes_sha256"] == sha256(b"roundtrip-payload").hexdigest()
    assert row["content_hash"] == provider_cache_content_hash(candidate)
    assert sha256(row["payload_bytes"]).hexdigest() == row["payload_bytes_sha256"]


def test_provider_cache_store_allows_independent_keys_without_cross_key_locking(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 10, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    limits = _limits(max_entries_total=4)
    store = SQLiteProviderCacheStore(engine, limits, clock=lambda: now)

    first = store.compare_and_replace(
        _candidate("independent-1", fetched=now, content_bytes=b"one"),
        expected_generation=0,
    )
    second = store.compare_and_replace(
        _candidate("independent-2", fetched=now, content_bytes=b"two"),
        expected_generation=0,
    )
    assert second.generation == 1
    assert store.get(first.source_cache_key) == first
    assert store.get(second.source_cache_key) == second
    assert _table_row_count(engine) == 2


def test_provider_cache_store_uses_failure_slot_when_present(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 11, tzinfo=UTC)
    engine = create_sqlite_engine(head_database)
    store = SQLiteProviderCacheStore(
        engine,
        _limits(),
        clock=lambda: now,
    )
    failure = _candidate(
        "failure",
        fetched=now,
        with_failure=True,
        content_status=ProviderCacheResultStatus.NOT_FOUND,
    )
    stored = store.compare_and_replace(failure, expected_generation=0)
    row = store.get(stored.source_cache_key)

    assert row is not None
    assert row.slots.failure_slot is not None
    assert row.slots.failure_slot.failure_status is ProviderCacheResultStatus.RATE_LIMITED


@pytest.mark.parametrize(
    "status",
    [
        ProviderCacheResultStatus.SUCCESS,
        ProviderCacheResultStatus.NOT_FOUND,
        ProviderCacheResultStatus.RATE_LIMITED,
        ProviderCacheResultStatus.TEMPORARY_FAILURE,
        ProviderCacheResultStatus.PERMANENT_FAILURE,
        ProviderCacheResultStatus.INVALID_RESPONSE,
    ],
)
def test_provider_cache_store_result_matrix_roundtrip_by_status(
    head_database: Path,
    status: ProviderCacheResultStatus,
) -> None:
    now = datetime(2026, 8, 19, 9, 20, tzinfo=UTC)
    store = _make_store(head_database, limits=_limits(max_entries_total=8), clock=lambda: now)
    candidate = _projection_candidate(
        status.value,
        status=status,
        fetched=now,
        content_bytes=b"matrix-payload",
    )
    written = store.compare_and_replace(candidate, expected_generation=0)
    got = store.get(written.source_cache_key)
    assert got is not None
    assert got == written

    if status in {ProviderCacheResultStatus.SUCCESS, ProviderCacheResultStatus.NOT_FOUND}:
        assert got.slots.content_slot is not None
        assert got.slots.content_slot.content_status is status
        assert got.slots.failure_slot is None
    else:
        assert got.slots.content_slot is None
        assert got.slots.failure_slot is not None
        assert got.slots.failure_slot.failure_status is status
        if status is ProviderCacheResultStatus.RATE_LIMITED:
            assert got.slots.failure_slot.failure_retry_after_at is not None
        else:
            assert got.slots.failure_slot.failure_retry_after_at is None


def test_provider_cache_store_preserves_existing_success_content_for_failure_projection(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 21, tzinfo=UTC)
    store = _make_store(head_database, limits=_limits(), clock=lambda: now)
    written = store.compare_and_replace(
        _projection_candidate(
            "preserve-success",
            status=ProviderCacheResultStatus.SUCCESS,
            fetched=now,
            content_bytes=b"matrix-success",
        ),
        expected_generation=0,
    )
    source_key = written.source_cache_key
    existing = store.get(source_key)
    assert existing is not None
    existing_content = existing.slots.content_slot
    assert existing_content is not None

    failed = store.compare_and_replace(
        _projection_candidate(
            "preserve-success",
            status=ProviderCacheResultStatus.RATE_LIMITED,
            fetched=now + timedelta(minutes=1),
            preserve_content_slot=existing_content,
        ),
        expected_generation=written.generation,
    )
    got = store.get(source_key)

    assert got is not None
    assert got.generation == failed.generation
    assert got.slots.content_slot == existing_content
    assert got.slots.failure_slot is not None
    assert got.slots.failure_slot.failure_status is ProviderCacheResultStatus.RATE_LIMITED
    assert got.slots.failure_slot.failure_retry_after_at == now + timedelta(
        seconds=30,
        minutes=1,
    )


def test_provider_cache_store_candidate_key_shape_is_canonical_provider_key(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="canonical provider_source_cache_key"):
        ProviderCacheStoreCandidate(
            source_cache_key="0" * 64,
            provider_id="provider",
            provider_adapter_version="v1",
            query_fingerprint=_fingerprint("shape"),
            provider_source_version="source-v1",
            slots=_slots(
                content_bytes=b"payload",
                fetched=now,
            ),
        )


def test_provider_cache_store_get_rejects_over_large_payload_row(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 13, tzinfo=UTC)
    candidate = _candidate("oversized", fetched=now, content_bytes=b"x" * 8)
    writer_limits = _limits(max_entry_payload_bytes=9)
    reader_limits = _limits(max_entry_payload_bytes=4)
    writer = _make_store(head_database, limits=writer_limits, clock=lambda: now)
    reader = _make_store(head_database, limits=reader_limits, clock=lambda: now)

    written = writer.compare_and_replace(candidate, expected_generation=0)
    assert written.source_cache_key == candidate.source_cache_key
    with pytest.raises(ValueError, match="cached payload exceeds max_entry_payload_bytes"):
        reader.get(written.source_cache_key)


def test_provider_cache_store_get_rejects_content_hash_drift_and_remains_payload_safe(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 14, tzinfo=UTC)
    limits = _limits()
    store = _make_store(head_database, limits=limits, clock=lambda: now)
    written = store.compare_and_replace(
        _candidate("drift", fetched=now),
        expected_generation=0,
    )

    with create_sqlite_engine(head_database).begin() as connection:
        connection.execute(
            update(w3_schema.provider_cache_entries)
            .where(
                w3_schema.provider_cache_entries.c.source_cache_key
                == written.source_cache_key
            )
            .values(content_hash="0" * 64)
        )

    with pytest.raises(ValueError, match="content hash mismatch"):
        store.get(written.source_cache_key)


def test_provider_cache_store_conflict_repr_and_current_do_not_leak_payload_bytes(
    head_database: Path,
) -> None:
    now = datetime(2026, 8, 19, 9, 15, tzinfo=UTC)
    store = _make_store(head_database, limits=_limits(), clock=lambda: now)
    installed = store.compare_and_replace(
        _candidate("repr", fetched=now, content_bytes=b"payload-bytes"),
        expected_generation=0,
    )

    with pytest.raises(ProviderCacheStoreConflictError) as exc:
        store.compare_and_replace(
            _candidate("repr", fetched=now),
            expected_generation=0,
        )

    assert "payload_bytes" not in repr(exc.value).lower()
    assert "payload_bytes" not in repr(exc.value.current).lower()
    assert installed == store.get(installed.source_cache_key)
