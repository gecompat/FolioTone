"""Internal coordinator for the first book-only fixity baseline slice."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from foliotone.core import EntityId
from foliotone.fixity import (
    EBOOK_FIXITY_BASELINE_TTL,
    EbookFixityBaselineEntry,
    EbookFixityBaselineManifest,
    EbookFixityBaselineSourceEntry,
    EbookFixityHashError,
    EbookFixityRootReader,
)
from foliotone.persistence.fixity import (
    DEFAULT_EBOOK_FIXITY_LEASE_DURATION,
    EbookFixityBaselineStoreError,
    SQLiteEbookFixityBaselineProjection,
    SQLiteEbookFixityBaselineStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease

MAX_EBOOK_FIXITY_HASH_WORKERS = 2
MAX_EBOOK_FIXITY_HEARTBEAT_SECONDS = 5.0
Clock = Callable[[], datetime]


class EbookFixityBaselineBuildError(RuntimeError):
    """A manifest was not produced; no private locator or hash is exposed."""


class _FixityLeaseKeeper:
    def __init__(
        self,
        store: SQLiteEbookFixityBaselineStore,
        lease: OwnedScanRootWriteLease,
        *,
        clock: Clock,
        lease_duration: timedelta,
    ) -> None:
        self._store = store
        self._lease = lease
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval = min(
            MAX_EBOOK_FIXITY_HEARTBEAT_SECONDS,
            lease_duration.total_seconds() / 3,
        )
        self._stop = Event()
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="foliotone-fixity-baseline-heartbeat",
            daemon=True,
        )
        self._error: Exception | None = None

    def __enter__(self) -> _FixityLeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def cancelled(self) -> bool:
        return self._error is not None

    def check(self) -> None:
        if self._error is not None:
            raise EbookFixityBaselineStoreError("fixity baseline heartbeat failed") from self._error

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._store.heartbeat(
                    self._lease,
                    heartbeat_at=self._clock(),
                    lease_duration=self._lease_duration,
                )
            except Exception as error:
                self._error = error
                return


class EbookFixityBaselineBuilder:
    """Build one bounded manifest without an Application, CLI, HTTP, or W10 surface."""

    def __init__(
        self,
        projection: SQLiteEbookFixityBaselineProjection,
        store: SQLiteEbookFixityBaselineStore,
        *,
        clock: Clock | None = None,
        lease_duration: timedelta = DEFAULT_EBOOK_FIXITY_LEASE_DURATION,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("fixity lease_duration must be positive")
        self._projection = projection
        self._store = store
        self._clock = clock or _utc_now
        self._lease_duration = lease_duration

    def build(
        self,
        source_root: Path,
        *,
        worker_count: int = 1,
    ) -> EbookFixityBaselineManifest:
        """Stream the latest complete EBOOK scan into an immutable ready manifest."""

        if not 1 <= worker_count <= MAX_EBOOK_FIXITY_HASH_WORKERS:
            raise ValueError("worker_count must be between 1 and 2")
        if not isinstance(source_root, Path) or not source_root.is_absolute():
            raise EbookFixityBaselineBuildError("fixity source root is unavailable")

        manifest_id = EntityId.new()
        started_at = self._clock()
        lease: OwnedScanRootWriteLease | None = None
        build_started = False
        ready_committed = False
        failure_code = "BUILD_FAILED"
        try:
            scan_root_id = self._projection.enabled_ebook_root_id()
            lease = self._store.acquire_lease(
                scan_root_id,
                manifest_id,
                acquired_at=started_at,
                lease_duration=self._lease_duration,
            )
            keeper = _FixityLeaseKeeper(
                self._store,
                lease,
                clock=self._clock,
                lease_duration=self._lease_duration,
            )
            with keeper:
                with self._projection.open_latest(scan_root_id) as source:
                    keeper.check()
                    self._store.start_build(
                        manifest_id,
                        source.source_scan_run_id,
                        started_at=started_at,
                        lease=lease,
                    )
                    build_started = True
                    ordinal = 0
                    with EbookFixityRootReader(source_root) as reader:
                        for source_batch in source.iter_batches():
                            keeper.check()
                            entries = self._hash_batch(
                                reader,
                                source_batch,
                                first_ordinal=ordinal,
                                worker_count=worker_count,
                                cancelled=keeper.cancelled,
                            )
                            ordinal += len(entries)
                            keeper.check()
                            self._store.append_entries(
                                manifest_id,
                                entries,
                                lease=lease,
                                committed_at=self._clock(),
                            )
                    keeper.check()
                keeper.check()
            prepared_at = self._clock()
            manifest = self._store.finalize_manifest(
                manifest_id,
                prepared_at=prepared_at,
                expires_at=prepared_at + EBOOK_FIXITY_BASELINE_TTL,
                lease=lease,
            )
            ready_committed = True
            return manifest
        except EbookFixityHashError as error:
            failure_code = error.code.value
            raise EbookFixityBaselineBuildError("fixity baseline source hashing failed") from error
        except EbookFixityBaselineStoreError as error:
            failure_code = "STORE_OR_LEASE_FAILED"
            raise EbookFixityBaselineBuildError(
                "fixity baseline projection or persistence failed"
            ) from error
        except (OSError, ValueError) as error:
            failure_code = "SOURCE_OR_CONTRACT_FAILED"
            raise EbookFixityBaselineBuildError("fixity baseline build failed") from error
        finally:
            if lease is not None:
                if build_started and not ready_committed:
                    try:
                        status = self._store.read_status(manifest_id)
                        if status is not None and status.status.value == "BUILDING":
                            self._store.fail_build(
                                manifest_id,
                                failure_code,
                                failed_at=self._clock(),
                                lease=lease,
                            )
                    except Exception:
                        pass
                try:
                    self._store.release(lease, released_at=self._clock())
                except Exception:
                    pass

    @staticmethod
    def _hash_batch(
        reader: EbookFixityRootReader,
        sources: tuple[EbookFixityBaselineSourceEntry, ...],
        *,
        first_ordinal: int,
        worker_count: int,
        cancelled: Callable[[], bool],
    ) -> tuple[EbookFixityBaselineEntry, ...]:
        def hash_one(source: EbookFixityBaselineSourceEntry) -> str:
            return reader.hash(source, cancelled=cancelled)

        if worker_count == 1 or len(sources) <= 1:
            hashes = tuple(hash_one(source) for source in sources)
        else:
            with ThreadPoolExecutor(
                max_workers=min(worker_count, len(sources)),
                thread_name_prefix="foliotone-fixity-baseline",
            ) as executor:
                hashes = tuple(executor.map(hash_one, sources))
        return tuple(
            EbookFixityBaselineEntry(
                ordinal=first_ordinal + offset,
                file_id=source.file_id,
                observation_id=source.observation_id,
                expected_size_bytes=source.expected_size_bytes,
                relative_locator=source.relative_locator,
                expected_sha256=digest,
            )
            for offset, (source, digest) in enumerate(zip(sources, hashes, strict=True))
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "MAX_EBOOK_FIXITY_HASH_WORKERS",
    "EbookFixityBaselineBuildError",
    "EbookFixityBaselineBuilder",
]
