"""Resumable bounded orchestration for one persisted e-book collection snapshot."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

from foliotone.core import (
    MAX_EBOOK_COLLECTION_WORKERS,
    EbookCollectionItemStatus,
    EbookCollectionRun,
    EntityId,
    FileObservation,
)
from foliotone.persistence import (
    EbookCollectionCounts,
    EbookCollectionExecutionSummary,
    EbookCollectionFindingSummary,
    EbookCollectionWorkItem,
    OwnedScanRootWriteLease,
    SQLiteEbookCollectionStore,
    scan_root_write_scope,
)
from foliotone.workflows.ebook import (
    EBOOK_ANALYSIS_PROFILE,
    EbookAnalysisError,
    EbookAnalysisOutcome,
    EbookAnalysisStatus,
    EbookAnalysisStepDisposition,
)

EBOOK_COLLECTION_PROFILE = "ebook-collection-analysis/v1"
EBOOK_COLLECTION_LEASE_DURATION = timedelta(minutes=30)
EBOOK_COLLECTION_CLAIM_FACTOR = 2
MAX_EBOOK_COLLECTION_HEARTBEAT_SECONDS = 60.0

type Clock = Callable[[], datetime]
type EbookCollectionAnalysis = Callable[[FileObservation, bool], EbookAnalysisOutcome]


class EbookCollectionError(RuntimeError):
    """A collection invocation could not maintain its persistent safety contract."""

    def __init__(self, message: str, *, run_id: EntityId | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


class EbookCollectionInterrupted(EbookCollectionError):
    """A user interruption released the lease and left a resumable run."""


@dataclass(frozen=True, slots=True)
class EbookCollectionOutcome:
    """Path-free summary of one new or resumed collection invocation."""

    run: EbookCollectionRun
    counts: EbookCollectionCounts
    processed_this_invocation: int
    profile: str = EBOOK_COLLECTION_PROFILE

    def __post_init__(self) -> None:
        if self.processed_this_invocation < 0:
            raise ValueError("processed_this_invocation must not be negative")
        if self.processed_this_invocation > self.counts.terminal:
            raise ValueError("invocation cannot process more than all terminal items")
        if not self.profile.strip():
            raise ValueError("collection outcome profile must not be empty")


@dataclass(frozen=True, slots=True)
class _ItemSummary:
    status: EbookCollectionItemStatus
    quality_status: str | None
    reused_step_count: int = 0
    executed_step_count: int = 0
    executions: tuple[EbookCollectionExecutionSummary, ...] = ()
    findings: tuple[EbookCollectionFindingSummary, ...] = ()
    error_code: str | None = None


class _CollectionLeaseKeeper:
    """Renew collection and root ownership during long-running analysis."""

    def __init__(
        self,
        store: SQLiteEbookCollectionStore,
        run_id: EntityId,
        lease_token: str,
        *,
        clock: Clock,
        lease_duration: timedelta,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._lease_token = lease_token
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval = min(
            MAX_EBOOK_COLLECTION_HEARTBEAT_SECONDS,
            lease_duration.total_seconds() / 3,
        )
        self._stop = Event()
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="foliotone-ebook-collection-heartbeat",
            daemon=True,
        )
        self._error: Exception | None = None

    def __enter__(self) -> _CollectionLeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def check(self) -> None:
        if self._error is not None:
            raise EbookCollectionError("collection heartbeat failed") from self._error

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval):
            now = self._clock()
            try:
                self._store.heartbeat(
                    self._run_id,
                    self._lease_token,
                    now,
                    now + self._lease_duration,
                )
            except Exception as error:
                self._error = error
                return


class EbookCollectionService:
    """Analyze a stable scan plan in bounded waves with persistent resume state."""

    def __init__(
        self,
        store: SQLiteEbookCollectionStore,
        analyze: EbookCollectionAnalysis,
        *,
        clock: Clock | None = None,
        lease_duration: timedelta = EBOOK_COLLECTION_LEASE_DURATION,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._store = store
        self._analyze = analyze
        self._clock = clock or _utc_now
        self._lease_duration = lease_duration

    def start(
        self,
        scan_root_id: EntityId,
        *,
        fresh: bool = False,
        worker_count: int = 1,
        max_items: int | None = None,
        plan_limit: int | None = None,
        plan_per_format: int | None = None,
    ) -> EbookCollectionOutcome:
        """Create a plan from the latest completed scan and execute a bounded slice."""
        _validate_invocation_limits(worker_count, max_items)
        now = self._clock()
        lease_token = str(EntityId.new())
        created = self._store.create_run(
            scan_root_id,
            profile=EBOOK_COLLECTION_PROFILE,
            analysis_profile=EBOOK_ANALYSIS_PROFILE,
            fresh=fresh,
            worker_count=worker_count,
            started_at=now,
            lease_token=lease_token,
            lease_expires_at=now + self._lease_duration,
            plan_limit=plan_limit,
            plan_per_format=plan_per_format,
        )
        return self._execute(created.run, lease_token, max_items=max_items)

    def resume(
        self,
        run_id: EntityId,
        *,
        max_items: int | None = None,
    ) -> EbookCollectionOutcome:
        """Acquire an interrupted or stale run and continue its unchanged plan."""
        if max_items is not None and max_items <= 0:
            raise ValueError("max_items must be positive when provided")
        now = self._clock()
        lease_token = str(EntityId.new())
        run = self._store.acquire_resume(
            run_id,
            lease_token=lease_token,
            now=now,
            lease_expires_at=now + self._lease_duration,
        )
        return self._execute(run, lease_token, max_items=max_items)

    def _execute(
        self,
        run: EbookCollectionRun,
        lease_token: str,
        *,
        max_items: int | None,
    ) -> EbookCollectionOutcome:
        processed = 0
        write_lease = self._store.owned_write_lease(run.id, lease_token)
        keeper = _CollectionLeaseKeeper(
            self._store,
            run.id,
            lease_token,
            clock=self._clock,
            lease_duration=self._lease_duration,
        )
        try:
            with keeper:
                with ThreadPoolExecutor(
                    max_workers=run.worker_count,
                    thread_name_prefix="foliotone-ebook",
                ) as executor:
                    while max_items is None or processed < max_items:
                        keeper.check()
                        remaining = (
                            run.worker_count * EBOOK_COLLECTION_CLAIM_FACTOR
                            if max_items is None
                            else min(
                                run.worker_count * EBOOK_COLLECTION_CLAIM_FACTOR,
                                max_items - processed,
                            )
                        )
                        now = self._clock()
                        self._store.heartbeat(
                            run.id,
                            lease_token,
                            now,
                            now + self._lease_duration,
                        )
                        work_items = self._store.claim_pending(
                            run.id,
                            lease_token,
                            limit=remaining,
                            started_at=now,
                        )
                        if not work_items:
                            break

                        futures = {
                            executor.submit(
                                self._analyze_item,
                                run,
                                work_item,
                                write_lease,
                            ): work_item
                            for work_item in work_items
                        }
                        for future in as_completed(futures):
                            keeper.check()
                            work_item = futures[future]
                            summary = future.result()
                            keeper.check()
                            self._store.complete_item(
                                work_item.item,
                                lease_token,
                                status=summary.status,
                                completed_at=self._clock(),
                                quality_status=summary.quality_status,
                                reused_step_count=summary.reused_step_count,
                                executed_step_count=summary.executed_step_count,
                                executions=summary.executions,
                                findings=summary.findings,
                                error_code=summary.error_code,
                            )
                            processed += 1
                keeper.check()

            finished = self._store.finish_invocation(
                run.id,
                lease_token,
                finished_at=self._clock(),
            )
            return EbookCollectionOutcome(
                run=finished,
                counts=self._store.counts(run.id),
                processed_this_invocation=processed,
            )
        except KeyboardInterrupt as error:
            self._release_failed_invocation(run.id, lease_token)
            raise EbookCollectionInterrupted(
                "collection analysis was interrupted",
                run_id=run.id,
            ) from error
        except Exception as error:
            self._release_failed_invocation(run.id, lease_token)
            raise EbookCollectionError(
                "collection analysis invocation failed",
                run_id=run.id,
            ) from error

    def _analyze_item(
        self,
        run: EbookCollectionRun,
        work_item: EbookCollectionWorkItem,
        write_lease: OwnedScanRootWriteLease,
    ) -> _ItemSummary:
        try:
            with scan_root_write_scope(write_lease, self._clock):
                outcome = self._analyze(work_item.observation, run.fresh)
        except EbookAnalysisError:
            return _ItemSummary(
                status=EbookCollectionItemStatus.ERROR,
                quality_status=None,
                error_code="ANALYSIS_REQUEST_REJECTED",
            )
        except Exception:
            return _ItemSummary(
                status=EbookCollectionItemStatus.ERROR,
                quality_status=None,
                error_code="UNEXPECTED_ANALYSIS_ERROR",
            )

        if (
            outcome.observation_id != work_item.observation.id
            or outcome.format_name != work_item.item.format_name
            or outcome.profile != run.analysis_profile
        ):
            return _ItemSummary(
                status=EbookCollectionItemStatus.ERROR,
                quality_status=None,
                error_code="ANALYSIS_CONTRACT_MISMATCH",
            )

        status = {
            EbookAnalysisStatus.SUCCEEDED: EbookCollectionItemStatus.SUCCEEDED,
            EbookAnalysisStatus.PARTIAL_FAILURE: (
                EbookCollectionItemStatus.PARTIAL_FAILURE
            ),
            EbookAnalysisStatus.FAILED: EbookCollectionItemStatus.FAILED,
        }[outcome.status]
        return _ItemSummary(
            status=status,
            quality_status=outcome.quality.status.value,
            reused_step_count=sum(
                step.disposition is EbookAnalysisStepDisposition.REUSED
                for step in outcome.steps
            ),
            executed_step_count=sum(
                step.disposition is EbookAnalysisStepDisposition.EXECUTED
                for step in outcome.steps
            ),
            executions=tuple(
                EbookCollectionExecutionSummary(
                    step_name=step.name,
                    disposition=step.disposition.value,
                    execution_id=execution.id,
                )
                for step in outcome.steps
                for execution in step.executions
            ),
            findings=tuple(
                EbookCollectionFindingSummary(
                    code=finding.code,
                    dimension=finding.dimension.value,
                    severity=finding.severity.value,
                    source_execution_ids=finding.source_execution_ids,
                )
                for finding in outcome.quality.findings
            ),
        )

    def _release_failed_invocation(self, run_id: EntityId, lease_token: str) -> None:
        try:
            self._store.fail_invocation(
                run_id,
                lease_token,
                failed_at=self._clock(),
            )
        except Exception:
            # The original failure is more useful; an expired/lost lease is already safe.
            pass


def _validate_invocation_limits(worker_count: int, max_items: int | None) -> None:
    if not 1 <= worker_count <= MAX_EBOOK_COLLECTION_WORKERS:
        raise ValueError("worker_count is outside the supported range")
    if max_items is not None and max_items <= 0:
        raise ValueError("max_items must be positive when provided")


def _utc_now() -> datetime:
    return datetime.now(UTC)
