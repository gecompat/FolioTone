"""Incremental scan orchestration over streaming filesystem discovery."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import islice
from threading import Event, Lock, Thread
from time import monotonic

from sqlalchemy.exc import OperationalError

from foliotone.core import (
    EntityId,
    FileChangeState,
    FileObservation,
    FileRelocationCandidate,
    FileScanEvent,
    Fingerprint,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index.deletion import DeletionConfirmationPolicy
from foliotone.index.discovery import DiscoveredFile, ScanRootBinding, discover_files
from foliotone.index.hashing import FingerprintWriter, HashMode
from foliotone.index.relocation import RelocationCandidateDetector
from foliotone.index.store import (
    DEFAULT_SCAN_LEASE_DURATION,
    OwnedScanRun,
    ScanLeaseError,
    SQLiteIndexStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease

Clock = Callable[[], datetime]
MAX_SCAN_HASH_WORKERS = 8
MAX_SCAN_HEARTBEAT_SECONDS = 60.0
SCAN_HEARTBEAT_LOCK_RETRY_DELAYS_SECONDS = (0.25, 0.5, 1.0, 2.0)
HASH_PROGRESS_REPORT_INTERVAL_SECONDS = 2.0
DISCOVERY_PROGRESS_REPORT_INTERVAL_SECONDS = 2.0
_HASH_STATES = frozenset(
    {
        FileChangeState.NEW,
        FileChangeState.MODIFIED,
        FileChangeState.REAPPEARED,
    }
)


class ScanProgressPhase(StrEnum):
    """Path-free phases exposed to a console progress renderer."""

    DISCOVERING = "DISCOVERING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """Bounded path-free cumulative progress for one scan invocation."""

    phase: ScanProgressPhase
    processed_files: int
    processed_bytes: int
    hash_failures: int

    def __post_init__(self) -> None:
        if min(self.processed_files, self.processed_bytes, self.hash_failures) < 0:
            raise ValueError("scan progress counts must not be negative")


@dataclass(frozen=True, slots=True)
class HashProgress:
    """Path-free live progress for the currently hashing discovery batch."""

    batch_files: int
    completed_files: int
    bytes_read: int
    current_bytes_per_second: float
    average_bytes_per_second: float

    def __post_init__(self) -> None:
        if self.batch_files <= 0:
            raise ValueError("batch_files must be positive")
        if not 0 <= self.completed_files <= self.batch_files:
            raise ValueError("completed_files must be within the current batch")
        if self.bytes_read < 0:
            raise ValueError("bytes_read must not be negative")
        if min(self.current_bytes_per_second, self.average_bytes_per_second) < 0:
            raise ValueError("hash throughput must not be negative")


@dataclass(frozen=True, slots=True)
class DiscoveryProgress:
    """Path-free live progress while the filesystem is being enumerated."""

    discovered_files: int
    discovered_bytes: int
    current_bytes_per_second: float
    average_bytes_per_second: float

    def __post_init__(self) -> None:
        if min(self.discovered_files, self.discovered_bytes) < 0:
            raise ValueError("discovery progress counts must not be negative")
        if min(self.current_bytes_per_second, self.average_bytes_per_second) < 0:
            raise ValueError("discovery throughput must not be negative")


@dataclass(frozen=True, slots=True)
class ReconciliationProgress:
    """Path-free indication that one discovered batch is being compared to the index."""

    processed_files: int
    processed_bytes: int
    batch_files: int
    batch_bytes: int
    reconciled_files: int
    reconciled_bytes: int

    def __post_init__(self) -> None:
        if min(
            self.processed_files,
            self.processed_bytes,
            self.batch_files,
            self.batch_bytes,
            self.reconciled_files,
            self.reconciled_bytes,
        ) < 0:
            raise ValueError("reconciliation progress counts must not be negative")
        if self.batch_files <= 0:
            raise ValueError("batch_files must be positive")
        if self.reconciled_files > self.batch_files:
            raise ValueError("reconciled_files must not exceed batch_files")
        if self.reconciled_bytes > self.batch_bytes:
            raise ValueError("reconciled_bytes must not exceed batch_bytes")


ProgressReporter = Callable[
    [ScanProgress | HashProgress | DiscoveryProgress | ReconciliationProgress], None
]


class _DiscoveryMeter:
    """Accumulate discovered files without retaining their paths."""

    def __init__(self) -> None:
        self._files = 0
        self._bytes = 0

    def add_file(self, discovered: DiscoveredFile) -> None:
        self._files += 1
        self._bytes += discovered.size_bytes

    def snapshot(self) -> tuple[int, int]:
        return self._files, self._bytes


class _DiscoveryProgressReporter:
    """Rate-limit live discovery progress on the discovery thread."""

    def __init__(
        self,
        meter: _DiscoveryMeter,
        report: ProgressReporter,
        *,
        clock: Callable[[], float] = monotonic,
        interval_seconds: float = DISCOVERY_PROGRESS_REPORT_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._meter = meter
        self._report = report
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._started_at = clock()
        self._last_reported_at = self._started_at
        self._last_reported_bytes = 0

    def start(self) -> None:
        self.report_now()

    def record_file(self, discovered: DiscoveredFile) -> None:
        self._meter.add_file(discovered)
        if self._clock() - self._last_reported_at >= self._interval_seconds:
            self.report_now()

    def report_now(self) -> None:
        now = self._clock()
        discovered_files, discovered_bytes = self._meter.snapshot()
        current_elapsed = max(now - self._last_reported_at, 0.001)
        average_elapsed = max(now - self._started_at, 0.001)
        self._report(
            DiscoveryProgress(
                discovered_files=discovered_files,
                discovered_bytes=discovered_bytes,
                current_bytes_per_second=(discovered_bytes - self._last_reported_bytes)
                / current_elapsed,
                average_bytes_per_second=discovered_bytes / average_elapsed,
            )
        )
        self._last_reported_at = now
        self._last_reported_bytes = discovered_bytes


class _ReconciliationMeter:
    """Share completed work within one atomic index-reconciliation batch."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._reconciled_files = 0
        self._reconciled_bytes = 0

    def set_progress(self, reconciled_files: int, reconciled_bytes: int) -> None:
        with self._lock:
            self._reconciled_files = reconciled_files
            self._reconciled_bytes = reconciled_bytes

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self._reconciled_files, self._reconciled_bytes


class _ReconciliationProgressKeeper:
    """Publish live progress while the store reconciles one atomic batch."""

    def __init__(
        self,
        meter: _ReconciliationMeter,
        *,
        processed_files: int,
        processed_bytes: int,
        batch_files: int,
        batch_bytes: int,
        report: ProgressReporter,
        interval_seconds: float = HASH_PROGRESS_REPORT_INTERVAL_SECONDS,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._meter = meter
        self._processed_files = processed_files
        self._processed_bytes = processed_bytes
        self._batch_files = batch_files
        self._batch_bytes = batch_bytes
        self._report = report
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._thread = Thread(
            target=self._report_until_stopped,
            name="foliotone-reconciliation-progress",
            daemon=True,
        )

    def __enter__(self) -> _ReconciliationProgressKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def _report_until_stopped(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._report_once()

    def _report_once(self) -> None:
        reconciled_files, reconciled_bytes = self._meter.snapshot()
        self._report(
            ReconciliationProgress(
                processed_files=self._processed_files,
                processed_bytes=self._processed_bytes,
                batch_files=self._batch_files,
                batch_bytes=self._batch_bytes,
                reconciled_files=reconciled_files,
                reconciled_bytes=reconciled_bytes,
            )
        )


class _HashReadMeter:
    """Accumulate worker read counts without exposing paths or fingerprint values."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._bytes_read = 0
        self._completed_files = 0

    def add_bytes(self, byte_count: int) -> None:
        if byte_count <= 0:
            return
        with self._lock:
            self._bytes_read += byte_count

    def complete_file(self) -> None:
        with self._lock:
            self._completed_files += 1

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self._bytes_read, self._completed_files


class _HashProgressKeeper:
    """Publish a bounded live read-rate snapshot while one hash batch runs."""

    def __init__(
        self,
        meter: _HashReadMeter,
        batch_files: int,
        report: ProgressReporter,
        *,
        clock: Callable[[], float] = monotonic,
        interval_seconds: float = HASH_PROGRESS_REPORT_INTERVAL_SECONDS,
    ) -> None:
        if batch_files <= 0:
            raise ValueError("batch_files must be positive")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._meter = meter
        self._batch_files = batch_files
        self._report = report
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._started_at = clock()
        self._last_reported_at = self._started_at
        self._last_reported_bytes = 0
        self._stop = Event()
        self._thread = Thread(
            target=self._report_until_stopped,
            name="foliotone-hash-progress",
            daemon=True,
        )

    def __enter__(self) -> _HashProgressKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def _report_until_stopped(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._report_once()

    def _report_once(self) -> None:
        now = self._clock()
        bytes_read, completed_files = self._meter.snapshot()
        current_elapsed = max(now - self._last_reported_at, 0.001)
        average_elapsed = max(now - self._started_at, 0.001)
        self._report(
            HashProgress(
                batch_files=self._batch_files,
                completed_files=completed_files,
                bytes_read=bytes_read,
                current_bytes_per_second=(bytes_read - self._last_reported_bytes) / current_elapsed,
                average_bytes_per_second=bytes_read / average_elapsed,
            )
        )
        self._last_reported_at = now
        self._last_reported_bytes = bytes_read


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Counts and conservative relocation candidates from one completed scan."""

    run: ScanRun
    counts: dict[FileChangeState, int]
    relocation_candidates: tuple[FileRelocationCandidate, ...] = ()
    hash_failures: int = 0

    def __post_init__(self) -> None:
        if self.hash_failures < 0:
            raise ValueError("hash_failures must not be negative")

    @property
    def observed_files(self) -> int:
        return sum(
            count
            for state, count in self.counts.items()
            if state not in {FileChangeState.MISSING, FileChangeState.DELETED}
        )


class _ScanLeaseKeeper:
    """Renew scan and root ownership while discovery or hashing blocks."""

    def __init__(
        self,
        store: SQLiteIndexStore,
        owned: OwnedScanRun,
        *,
        clock: Clock,
        lease_duration: timedelta,
    ) -> None:
        self._store = store
        self._owned = owned
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval = min(
            MAX_SCAN_HEARTBEAT_SECONDS,
            lease_duration.total_seconds() / 3,
        )
        self._stop = Event()
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="foliotone-scan-heartbeat",
            daemon=True,
        )
        self._error: Exception | None = None

    def __enter__(self) -> _ScanLeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def check(self) -> None:
        if self._error is not None:
            raise ScanLeaseError("scan heartbeat failed") from self._error

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval):
            if not self._renew():
                return

    def _renew(self) -> bool:
        """Renew ownership, tolerating a bounded transient SQLite writer conflict."""

        for delay in (*SCAN_HEARTBEAT_LOCK_RETRY_DELAYS_SECONDS, None):
            heartbeat_at = self._clock()
            try:
                self._owned = self._store.heartbeat_scan(
                    self._owned,
                    heartbeat_at,
                    heartbeat_at + self._lease_duration,
                )
                return True
            except Exception as error:
                if delay is not None and _is_transient_sqlite_lock(error):
                    if self._stop.wait(delay):
                        return False
                    continue
                self._error = error
                return False
        raise AssertionError("heartbeat retry loop must return")


class IncrementalScanner:
    """Discovers files in bounded batches and persists auditable state changes."""

    def __init__(
        self,
        store: SQLiteIndexStore,
        *,
        batch_size: int = 256,
        hash_mode: HashMode = HashMode.QUICK,
        hash_workers: int = 1,
        fingerprint_writer: FingerprintWriter | None = None,
        deletion_policy: DeletionConfirmationPolicy | None = None,
        relocation_detector: RelocationCandidateDetector | None = None,
        lease_duration: timedelta = DEFAULT_SCAN_LEASE_DURATION,
        clock: Clock | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        if batch_size <= 0 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        if not 1 <= hash_workers <= MAX_SCAN_HASH_WORKERS:
            raise ValueError(f"hash_workers must be between 1 and {MAX_SCAN_HASH_WORKERS}")
        if hash_mode is not HashMode.NONE and fingerprint_writer is None:
            raise ValueError("hashing requires a FingerprintWriter")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._store = store
        self._batch_size = batch_size
        self._hash_mode = hash_mode
        self._hash_workers = hash_workers
        self._fingerprints = fingerprint_writer
        self._deletion_policy = deletion_policy
        self._relocation_detector = relocation_detector
        self._lease_duration = lease_duration
        self._clock = clock or _utc_now
        self._progress = progress
        self._progress_lock = Lock()

    def scan(
        self,
        root: ScanRoot,
        binding: ScanRootBinding,
        *,
        resume_from: ScanRun | None = None,
    ) -> ScanSummary:
        """Run or resume one incremental scan with a distinct auditable ScanRun."""
        if self._fingerprints is not None:
            self._fingerprints.reset_cancellation()
        started_at = self._clock()
        owned = self._store.start_scan(
            root,
            started_at,
            resume_from=resume_from,
            lease_token=str(EntityId.new()),
            lease_expires_at=started_at + self._lease_duration,
        )
        counts: Counter[FileChangeState] = Counter()
        relocation_candidates: tuple[FileRelocationCandidate, ...] = ()
        hash_failures = 0
        processed_files = 0
        processed_bytes = 0
        keeper = _ScanLeaseKeeper(
            self._store,
            owned,
            clock=self._clock,
            lease_duration=self._lease_duration,
        )
        keeper.__enter__()
        keeper_stopped = False

        try:
            discovery_meter = _DiscoveryMeter()
            discovery_progress = (
                _DiscoveryProgressReporter(discovery_meter, self._emit_progress)
                if self._progress is not None
                else None
            )
            if discovery_progress is not None:
                discovery_progress.start()
            iterator = _record_discovery(discover_files(binding), discovery_progress)
            for batch in _batches(iterator, self._batch_size):
                keeper.check()
                owned = self._heartbeat(owned)
                if discovery_progress is not None:
                    discovery_progress.report_now()
                self._emit_progress(
                    ReconciliationProgress(
                        processed_files=processed_files,
                        processed_bytes=processed_bytes,
                        batch_files=len(batch),
                        batch_bytes=sum(item.size_bytes for item in batch),
                        reconciled_files=0,
                        reconciled_bytes=0,
                    )
                )
                reconciliation_meter = (
                    _ReconciliationMeter() if self._progress is not None else None
                )
                reconciliation_keeper = (
                    _ReconciliationProgressKeeper(
                        reconciliation_meter,
                        processed_files=processed_files,
                        processed_bytes=processed_bytes,
                        batch_files=len(batch),
                        batch_bytes=sum(item.size_bytes for item in batch),
                        report=self._emit_progress,
                    )
                    if reconciliation_meter is not None
                    else None
                )
                try:
                    if reconciliation_keeper is not None:
                        reconciliation_keeper.__enter__()
                    outcome = self._store.process_batch(
                        root,
                        owned,
                        batch,
                        self._clock(),
                        on_item_reconciled=(
                            reconciliation_meter.set_progress
                            if reconciliation_meter is not None
                            else None
                        ),
                    )
                finally:
                    if reconciliation_keeper is not None:
                        reconciliation_keeper.__exit__(None, None, None)
                counts.update(event.change_state for event in outcome.events)
                hash_failures += self._hash_changed(
                    batch,
                    outcome.observations,
                    outcome.events,
                    owned.write_lease,
                )
                processed_files += len(batch)
                processed_bytes += sum(item.size_bytes for item in batch)
                self._report_progress(
                    ScanProgressPhase.DISCOVERING,
                    processed_files,
                    processed_bytes,
                    hash_failures,
                )
                keeper.check()
                owned = self._heartbeat(owned)

            self._report_progress(
                ScanProgressPhase.FINALIZING,
                processed_files,
                processed_bytes,
                hash_failures,
            )
            owned = self._heartbeat(owned)
            missing = self._store.mark_missing(
                root,
                owned,
                self._clock(),
                deletion_policy=self._deletion_policy,
            )
            counts.update(event.change_state for event in missing)
            owned = self._heartbeat(owned)
            if self._relocation_detector is not None:
                relocation_candidates = self._relocation_detector.detect(
                    owned.run,
                    self._clock(),
                    write_lease=owned.write_lease,
                )
                owned = self._heartbeat(owned)
            keeper.check()
            keeper.__exit__(None, None, None)
            keeper_stopped = True
            keeper.check()
            owned = self._store.finish_scan(
                owned,
                ScanRunStatus.COMPLETED,
                self._clock(),
            )
            self._report_progress(
                ScanProgressPhase.COMPLETED,
                processed_files,
                processed_bytes,
                hash_failures,
            )
        except KeyboardInterrupt:
            if not keeper_stopped:
                keeper.__exit__(None, None, None)
            self._finish_after_error(owned, ScanRunStatus.INTERRUPTED)
            raise
        except Exception:
            if not keeper_stopped:
                keeper.__exit__(None, None, None)
            self._finish_after_error(owned, ScanRunStatus.FAILED)
            raise
        except BaseException:
            if not keeper_stopped:
                keeper.__exit__(None, None, None)
            self._finish_after_error(owned, ScanRunStatus.INTERRUPTED)
            raise

        return ScanSummary(
            run=owned.run,
            counts=dict(counts),
            relocation_candidates=relocation_candidates,
            hash_failures=hash_failures,
        )

    def _heartbeat(self, owned: OwnedScanRun) -> OwnedScanRun:
        heartbeat_at = self._clock()
        return self._store.heartbeat_scan(
            owned,
            heartbeat_at,
            heartbeat_at + self._lease_duration,
        )

    def _report_progress(
        self,
        phase: ScanProgressPhase,
        processed_files: int,
        processed_bytes: int,
        hash_failures: int,
    ) -> None:
        self._emit_progress(
            ScanProgress(
                phase=phase,
                processed_files=processed_files,
                processed_bytes=processed_bytes,
                hash_failures=hash_failures,
            )
        )

    def _emit_progress(
        self,
        progress: ScanProgress | HashProgress | DiscoveryProgress | ReconciliationProgress,
    ) -> None:
        if self._progress is None:
            return
        with self._progress_lock:
            self._progress(progress)

    def _finish_after_error(
        self,
        owned: OwnedScanRun,
        status: ScanRunStatus,
    ) -> None:
        try:
            self._store.finish_scan(owned, status, self._clock())
        except ScanLeaseError:
            # A concurrent stale-run recovery already owns the durable transition.
            pass

    def _hash_changed(
        self,
        discovered: tuple[DiscoveredFile, ...],
        observations: tuple[FileObservation, ...],
        events: tuple[FileScanEvent, ...],
        write_lease: OwnedScanRootWriteLease,
    ) -> int:
        if self._hash_mode is HashMode.NONE or self._fingerprints is None:
            return 0
        if len(observations) != len(discovered) or len(events) != len(discovered):
            raise RuntimeError("index batch outcome is not aligned with discovery batch")
        batch_time = self._clock()
        unchanged = tuple(
            observation
            for observation, event in zip(observations, events, strict=True)
            if event.change_state is FileChangeState.UNCHANGED
        )
        reused = self._fingerprints.reuse_latest(
            unchanged,
            self._hash_mode,
            batch_time,
        )
        fingerprints = [
            fingerprint
            for observation in unchanged
            for fingerprint in reused.get(observation.id, ())
        ]
        hash_failures = 0
        calculate = tuple(
            (item, observation)
            for item, observation, event in zip(discovered, observations, events, strict=True)
            if event.change_state in _HASH_STATES
            or (event.change_state is FileChangeState.UNCHANGED and observation.id not in reused)
        )
        meter = _HashReadMeter() if self._progress is not None and calculate else None
        progress_keeper = (
            _HashProgressKeeper(
                meter,
                len(calculate),
                self._emit_progress,
                interval_seconds=HASH_PROGRESS_REPORT_INTERVAL_SECONDS,
            )
            if meter is not None
            else None
        )

        def calculate_one(
            item: DiscoveredFile, observation: FileObservation
        ) -> tuple[Fingerprint, ...]:
            try:
                return self._fingerprints.calculate(
                    observation,
                    item.physical_path,
                    self._hash_mode,
                    batch_time,
                )
            finally:
                if meter is not None:
                    meter.complete_file()

        if meter is not None:
            self._fingerprints.set_read_observer(meter.add_bytes)
        try:
            if progress_keeper is not None:
                progress_keeper.__enter__()
            if self._hash_workers == 1 or len(calculate) <= 1:
                for item, observation in calculate:
                    try:
                        calculated = calculate_one(item, observation)
                    except OSError:
                        hash_failures += 1
                    else:
                        fingerprints.extend(calculated)
            else:
                executor = ThreadPoolExecutor(
                    max_workers=min(self._hash_workers, len(calculate)),
                    thread_name_prefix="foliotone-hash",
                )
                futures: tuple[Future[tuple[Fingerprint, ...]], ...] = ()
                cancel_futures = False
                try:
                    futures = tuple(
                        executor.submit(calculate_one, item, observation)
                        for item, observation in calculate
                    )
                    for future in futures:
                        try:
                            calculated = future.result()
                        except OSError:
                            hash_failures += 1
                        else:
                            fingerprints.extend(calculated)
                except KeyboardInterrupt:
                    self._fingerprints.cancel_pending()
                    cancel_futures = True
                    for future in futures:
                        future.cancel()
                    raise
                finally:
                    executor.shutdown(wait=True, cancel_futures=cancel_futures)
        finally:
            if progress_keeper is not None:
                progress_keeper.__exit__(None, None, None)
            if meter is not None:
                self._fingerprints.set_read_observer(None)
        self._fingerprints.save_many(
            fingerprints,
            write_lease=write_lease,
            committed_at=self._clock(),
        )
        return hash_failures


def _batches(iterator: Iterator[DiscoveredFile], size: int) -> Iterator[tuple[DiscoveredFile, ...]]:
    while batch := tuple(islice(iterator, size)):
        yield batch


def _record_discovery(
    iterator: Iterator[DiscoveredFile],
    progress: _DiscoveryProgressReporter | None,
) -> Iterator[DiscoveredFile]:
    for discovered in iterator:
        if progress is not None:
            progress.record_file(discovered)
        yield discovered


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_transient_sqlite_lock(error: Exception) -> bool:
    """Return whether SQLAlchemy wrapped SQLite's retryable writer-lock errors."""

    if not isinstance(error, OperationalError) or not isinstance(
        error.orig, sqlite3.OperationalError
    ):
        return False
    message = str(error.orig).lower()
    return "locked" in message or "busy" in message
