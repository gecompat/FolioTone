"""Incremental scan orchestration over streaming filesystem discovery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice

from foliotone.core import (
    FileChangeState,
    FileObservation,
    FileRelocationCandidate,
    FileScanEvent,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index.deletion import DeletionConfirmationPolicy
from foliotone.index.discovery import DiscoveredFile, ScanRootBinding, discover_files
from foliotone.index.hashing import FingerprintWriter, HashMode
from foliotone.index.relocation import RelocationCandidateDetector
from foliotone.index.store import SQLiteIndexStore

Clock = Callable[[], datetime]
MAX_SCAN_HASH_WORKERS = 8
_HASH_STATES = frozenset(
    {
        FileChangeState.NEW,
        FileChangeState.MODIFIED,
        FileChangeState.REAPPEARED,
    }
)


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
        clock: Clock | None = None,
    ) -> None:
        if batch_size <= 0 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        if not 1 <= hash_workers <= MAX_SCAN_HASH_WORKERS:
            raise ValueError(
                f"hash_workers must be between 1 and {MAX_SCAN_HASH_WORKERS}"
            )
        if hash_mode is not HashMode.NONE and fingerprint_writer is None:
            raise ValueError("hashing requires a FingerprintWriter")
        self._store = store
        self._batch_size = batch_size
        self._hash_mode = hash_mode
        self._hash_workers = hash_workers
        self._fingerprints = fingerprint_writer
        self._deletion_policy = deletion_policy
        self._relocation_detector = relocation_detector
        self._clock = clock or _utc_now

    def scan(
        self,
        root: ScanRoot,
        binding: ScanRootBinding,
        *,
        resume_from: ScanRun | None = None,
    ) -> ScanSummary:
        """Run or resume one incremental scan with a distinct auditable ScanRun."""
        started_at = self._clock()
        run = self._store.start_scan(root, started_at, resume_from=resume_from)
        counts: Counter[FileChangeState] = Counter()
        relocation_candidates: tuple[FileRelocationCandidate, ...] = ()
        hash_failures = 0

        try:
            iterator = discover_files(binding)
            for batch in _batches(iterator, self._batch_size):
                outcome = self._store.process_batch(root, run, batch, self._clock())
                counts.update(event.change_state for event in outcome.events)
                hash_failures += self._hash_changed(
                    batch,
                    outcome.observations,
                    outcome.events,
                )

            missing = self._store.mark_missing(
                root,
                run,
                self._clock(),
                deletion_policy=self._deletion_policy,
            )
            counts.update(event.change_state for event in missing)
            if self._relocation_detector is not None:
                relocation_candidates = self._relocation_detector.detect(run, self._clock())
            run = self._store.finish_scan(run, ScanRunStatus.COMPLETED, self._clock())
        except KeyboardInterrupt:
            self._store.finish_scan(run, ScanRunStatus.INTERRUPTED, self._clock())
            raise
        except Exception:
            self._store.finish_scan(run, ScanRunStatus.FAILED, self._clock())
            raise

        return ScanSummary(
            run=run,
            counts=dict(counts),
            relocation_candidates=relocation_candidates,
            hash_failures=hash_failures,
        )

    def _hash_changed(
        self,
        discovered: tuple[DiscoveredFile, ...],
        observations: tuple[FileObservation, ...],
        events: tuple[FileScanEvent, ...],
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
            for item, observation, event in zip(
                discovered, observations, events, strict=True
            )
            if event.change_state in _HASH_STATES
            or (
                event.change_state is FileChangeState.UNCHANGED
                and observation.id not in reused
            )
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
            with ThreadPoolExecutor(
                max_workers=min(self._hash_workers, len(calculate)),
                thread_name_prefix="foliotone-hash",
            ) as executor:
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
        self._fingerprints.save_many(fingerprints)
        return hash_failures


def _batches(iterator: Iterator[DiscoveredFile], size: int) -> Iterator[tuple[DiscoveredFile, ...]]:
    while batch := tuple(islice(iterator, size)):
        yield batch


def _utc_now() -> datetime:
    return datetime.now(UTC)
