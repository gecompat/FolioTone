"""Incremental scan orchestration over streaming filesystem discovery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
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
        fingerprint_writer: FingerprintWriter | None = None,
        deletion_policy: DeletionConfirmationPolicy | None = None,
        relocation_detector: RelocationCandidateDetector | None = None,
        clock: Clock | None = None,
    ) -> None:
        if batch_size <= 0 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        if hash_mode is not HashMode.NONE and fingerprint_writer is None:
            raise ValueError("hashing requires a FingerprintWriter")
        self._store = store
        self._batch_size = batch_size
        self._hash_mode = hash_mode
        self._fingerprints = fingerprint_writer
        self._deletion_policy = deletion_policy
        self._relocation_detector = relocation_detector
        self._clock = clock or _utc_now

    def scan(self, root: ScanRoot, binding: ScanRootBinding) -> ScanSummary:
        """Run one incremental scan; absence is classified only after successful discovery."""
        started_at = self._clock()
        run = self._store.start_scan(root, started_at)
        counts: Counter[FileChangeState] = Counter()
        relocation_candidates: tuple[FileRelocationCandidate, ...] = ()

        try:
            iterator = discover_files(binding)
            for batch in _batches(iterator, self._batch_size):
                outcome = self._store.process_batch(root, run, batch, self._clock())
                counts.update(event.change_state for event in outcome.events)
                self._hash_changed(batch, outcome.observations, outcome.events)

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
        )

    def _hash_changed(
        self,
        discovered: tuple[DiscoveredFile, ...],
        observations: tuple[FileObservation, ...],
        events: tuple[FileScanEvent, ...],
    ) -> None:
        if self._hash_mode is HashMode.NONE or self._fingerprints is None:
            return
        if len(observations) != len(discovered) or len(events) != len(discovered):
            raise RuntimeError("index batch outcome is not aligned with discovery batch")
        for item, observation, event in zip(discovered, observations, events, strict=True):
            if event.change_state in _HASH_STATES:
                self._fingerprints.calculate_and_save(
                    observation,
                    item.physical_path,
                    self._hash_mode,
                    self._clock(),
                )


def _batches(iterator: Iterator[DiscoveredFile], size: int) -> Iterator[tuple[DiscoveredFile, ...]]:
    while batch := tuple(islice(iterator, size)):
        yield batch


def _utc_now() -> datetime:
    return datetime.now(UTC)
