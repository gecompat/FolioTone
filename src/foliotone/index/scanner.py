"""Incremental scan orchestration over streaming filesystem discovery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import islice
from threading import Event, Thread

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
ProgressReporter = Callable[["ScanProgress"], None]
MAX_SCAN_HASH_WORKERS = 8
MAX_SCAN_HEARTBEAT_SECONDS = 60.0
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
            heartbeat_at = self._clock()
            try:
                self._owned = self._store.heartbeat_scan(
                    self._owned,
                    heartbeat_at,
                    heartbeat_at + self._lease_duration,
                )
            except Exception as error:
                self._error = error
                return


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
            iterator = discover_files(binding)
            for batch in _batches(iterator, self._batch_size):
                keeper.check()
                owned = self._heartbeat(owned)
                outcome = self._store.process_batch(root, owned, batch, self._clock())
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
        if self._progress is None:
            return
        self._progress(
            ScanProgress(
                phase=phase,
                processed_files=processed_files,
                processed_bytes=processed_bytes,
                hash_failures=hash_failures,
            )
        )

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
        if self._hash_workers == 1 or len(calculate) <= 1:
            for item, observation in calculate:
                try:
                    calculated = self._fingerprints.calculate(
                        observation,
                        item.physical_path,
                        self._hash_mode,
                        batch_time,
                    )
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
                    executor.submit(
                        self._fingerprints.calculate,
                        observation,
                        item.physical_path,
                        self._hash_mode,
                        batch_time,
                    )
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
        self._fingerprints.save_many(
            fingerprints,
            write_lease=write_lease,
            committed_at=self._clock(),
        )
        return hash_failures


def _batches(iterator: Iterator[DiscoveredFile], size: int) -> Iterator[tuple[DiscoveredFile, ...]]:
    while batch := tuple(islice(iterator, size)):
        yield batch


def _utc_now() -> datetime:
    return datetime.now(UTC)
