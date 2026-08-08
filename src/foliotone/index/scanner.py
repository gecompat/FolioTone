"""Incremental scan orchestration over streaming filesystem discovery."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice

from foliotone.core import FileChangeState, ScanRoot, ScanRun, ScanRunStatus
from foliotone.index.discovery import DiscoveredFile, ScanRootBinding, discover_files
from foliotone.index.store import SQLiteIndexStore

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Counts produced by one completed incremental scan."""

    run: ScanRun
    counts: dict[FileChangeState, int]

    @property
    def observed_files(self) -> int:
        return sum(
            count
            for state, count in self.counts.items()
            if state is not FileChangeState.MISSING
        )


class IncrementalScanner:
    """Discovers files in bounded batches and persists auditable state changes."""

    def __init__(
        self,
        store: SQLiteIndexStore,
        *,
        batch_size: int = 256,
        clock: Clock | None = None,
    ) -> None:
        if batch_size <= 0 or batch_size > 500:
            raise ValueError("batch_size must be between 1 and 500")
        self._store = store
        self._batch_size = batch_size
        self._clock = clock or _utc_now

    def scan(self, root: ScanRoot, binding: ScanRootBinding) -> ScanSummary:
        """Run one incremental scan; missing is marked only after successful discovery."""
        started_at = self._clock()
        run = self._store.start_scan(root, started_at)
        counts: Counter[FileChangeState] = Counter()

        try:
            iterator = discover_files(binding)
            for batch in _batches(iterator, self._batch_size):
                outcome = self._store.process_batch(root, run, batch, self._clock())
                counts.update(event.change_state for event in outcome.events)

            missing = self._store.mark_missing(root, run, self._clock())
            counts.update(event.change_state for event in missing)
            run = self._store.finish_scan(run, ScanRunStatus.COMPLETED, self._clock())
        except KeyboardInterrupt:
            self._store.finish_scan(run, ScanRunStatus.INTERRUPTED, self._clock())
            raise
        except Exception:
            self._store.finish_scan(run, ScanRunStatus.FAILED, self._clock())
            raise

        return ScanSummary(run=run, counts=dict(counts))


def _batches(iterator: Iterator[DiscoveredFile], size: int) -> Iterator[tuple[DiscoveredFile, ...]]:
    while batch := tuple(islice(iterator, size)):
        yield batch


def _utc_now() -> datetime:
    return datetime.now(UTC)
