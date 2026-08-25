"""Internal coordinator for snapshot-bound book-only fixity verification."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from foliotone.core import EntityId
from foliotone.fixity.contracts import EbookFixityBaselineSourceEntry
from foliotone.fixity.hashing import (
    EbookFixityHashError,
    EbookFixityHashErrorCode,
    EbookFixityRootReader,
)
from foliotone.fixity.verification_contracts import (
    EbookFixityVerificationResult,
    EbookFixityVerificationResultRecord,
    EbookFixityVerificationRun,
    EbookFixityVerificationRunStatus,
)
from foliotone.persistence.fixity import SQLiteEbookFixityBaselineProjection
from foliotone.persistence.fixity_verification import (
    DEFAULT_EBOOK_FIXITY_VERIFICATION_LEASE_DURATION,
    EbookFixityVerificationStoreError,
    EbookFixityVerificationWorkItem,
    OwnedEbookFixityVerificationRun,
    SQLiteEbookFixityVerificationStore,
)

MAX_EBOOK_FIXITY_VERIFICATION_HASH_WORKERS = 2
MAX_EBOOK_FIXITY_VERIFICATION_HEARTBEAT_SECONDS = 5.0
DEFAULT_EBOOK_FIXITY_VERIFICATION_BATCH_SIZE = 100
Clock = Callable[[], datetime]


class EbookFixityVerificationError(RuntimeError):
    """A verification did not complete; no private evidence is exposed."""


class _VerificationLeaseKeeper:
    def __init__(
        self,
        store: SQLiteEbookFixityVerificationStore,
        owned: OwnedEbookFixityVerificationRun,
        *,
        clock: Clock,
        lease_duration: timedelta,
    ) -> None:
        self._store = store
        self._owned = owned
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval = min(
            MAX_EBOOK_FIXITY_VERIFICATION_HEARTBEAT_SECONDS,
            lease_duration.total_seconds() / 3,
        )
        self._stop = Event()
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="foliotone-fixity-verification-heartbeat",
            daemon=True,
        )
        self._error: Exception | None = None

    def __enter__(self) -> _VerificationLeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def cancelled(self) -> bool:
        return self._error is not None

    def check(self) -> None:
        if self._error is not None:
            raise EbookFixityVerificationStoreError(
                "fixity verification heartbeat failed"
            ) from self._error

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                heartbeat_at = self._clock()
                self._store.heartbeat(
                    self._owned,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=heartbeat_at + self._lease_duration,
                )
            except Exception as error:
                self._error = error
                return


class EbookFixityVerifier:
    """Verify exactly one bound EBOOK snapshot without a product surface or writes."""

    def __init__(
        self,
        projection: SQLiteEbookFixityBaselineProjection,
        store: SQLiteEbookFixityVerificationStore,
        *,
        clock: Clock | None = None,
        lease_duration: timedelta = DEFAULT_EBOOK_FIXITY_VERIFICATION_LEASE_DURATION,
        batch_size: int = DEFAULT_EBOOK_FIXITY_VERIFICATION_BATCH_SIZE,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("fixity verification lease_duration must be positive")
        if not 1 <= batch_size <= 1_000:
            raise ValueError("fixity verification batch_size must be between 1 and 1000")
        self._projection = projection
        self._store = store
        self._clock = clock or _utc_now
        self._lease_duration = lease_duration
        self._batch_size = batch_size

    def verify(
        self,
        source_root: Path,
        *,
        worker_count: int = 1,
    ) -> EbookFixityVerificationRun:
        """Stream the exact bound workset into one immutable completed run."""

        if not 1 <= worker_count <= MAX_EBOOK_FIXITY_VERIFICATION_HASH_WORKERS:
            raise ValueError("worker_count must be between 1 and 2")
        if not isinstance(source_root, Path) or not source_root.is_absolute():
            raise EbookFixityVerificationError("fixity verification source root is unavailable")

        run_id = EntityId.new()
        started_at = self._clock()
        owned: OwnedEbookFixityVerificationRun | None = None
        completed = False
        failure_code = "VERIFICATION_FAILED"
        try:
            scan_root_id = self._projection.enabled_ebook_root_id()
            owned = self._store.start_run(
                run_id,
                scan_root_id,
                started_at=started_at,
                lease_token=str(EntityId.new()),
                lease_expires_at=started_at + self._lease_duration,
            )
            keeper = _VerificationLeaseKeeper(
                self._store,
                owned,
                clock=self._clock,
                lease_duration=self._lease_duration,
            )
            after_file_id: EntityId | None = None
            with keeper, EbookFixityRootReader(source_root) as reader:
                while True:
                    keeper.check()
                    work = self._store.read_workset_batch(
                        owned,
                        observed_at=self._clock(),
                        after_file_id=after_file_id,
                        batch_size=self._batch_size,
                    )
                    if not work:
                        break
                    results = self._verify_batch(
                        reader,
                        owned.run.run_id,
                        work,
                        worker_count=worker_count,
                        cancelled=keeper.cancelled,
                    )
                    keeper.check()
                    self._store.append_results(
                        owned,
                        results,
                        recorded_at=self._clock(),
                    )
                    after_file_id = work[-1].file_id
                reader.check_root()
                keeper.check()
            result = self._store.complete_run(owned, completed_at=self._clock())
            completed = True
            return result
        except EbookFixityHashError as error:
            failure_code = error.code.value
            raise EbookFixityVerificationError(
                "fixity verification source hashing failed"
            ) from error
        except EbookFixityVerificationStoreError as error:
            failure_code = "STORE_OR_LEASE_FAILED"
            raise EbookFixityVerificationError(
                "fixity verification projection or persistence failed"
            ) from error
        except (OSError, ValueError) as error:
            failure_code = "SOURCE_OR_CONTRACT_FAILED"
            raise EbookFixityVerificationError("fixity verification failed") from error
        finally:
            if owned is not None and not completed:
                try:
                    status = self._store.read_status(owned.run.run_id)
                    if (
                        status is not None
                        and status.status is EbookFixityVerificationRunStatus.RUNNING
                    ):
                        self._store.fail_run(
                            owned,
                            failed_at=self._clock(),
                            failure_code=failure_code,
                        )
                except Exception:
                    # A lost fence cannot be overwritten by its former owner. The next
                    # verification takeover closes the expired run append-only.
                    pass

    @staticmethod
    def _verify_batch(
        reader: EbookFixityRootReader,
        run_id: EntityId,
        work: tuple[EbookFixityVerificationWorkItem, ...],
        *,
        worker_count: int,
        cancelled: Callable[[], bool],
    ) -> tuple[EbookFixityVerificationResultRecord, ...]:
        def verify_one(
            item: EbookFixityVerificationWorkItem,
        ) -> EbookFixityVerificationResultRecord:
            return _verify_one(reader, run_id, item, cancelled=cancelled)

        if worker_count == 1 or len(work) <= 1:
            return tuple(verify_one(item) for item in work)
        with ThreadPoolExecutor(
            max_workers=min(worker_count, len(work)),
            thread_name_prefix="foliotone-fixity-verification",
        ) as executor:
            return tuple(executor.map(verify_one, work))


def _verify_one(
    reader: EbookFixityRootReader,
    run_id: EntityId,
    item: EbookFixityVerificationWorkItem,
    *,
    cancelled: Callable[[], bool],
) -> EbookFixityVerificationResultRecord:
    if item.current_observation_id is None:
        if (
            item.expected_observation_id is None
            or item.expected_size_bytes is None
            or item.expected_sha256 is None
            or item.expected_relative_locator is None
        ):
            raise ValueError("missing work item has no complete expected state")
        return _result_record(
            run_id,
            item,
            EbookFixityVerificationResult.MISSING,
            current_sha256=None,
        )
    if (
        item.current_size_bytes is None
        or item.current_modified_at is None
        or item.current_relative_locator is None
    ):
        raise ValueError("present work item has no complete current state")
    source = EbookFixityBaselineSourceEntry(
        file_id=item.file_id,
        observation_id=item.current_observation_id,
        relative_locator=item.current_relative_locator,
        expected_size_bytes=item.current_size_bytes,
        expected_modified_at=item.current_modified_at,
    )
    try:
        current_sha256 = reader.hash(source, cancelled=cancelled)
    except EbookFixityHashError as error:
        if error.code is EbookFixityHashErrorCode.SOURCE_UNREADABLE:
            return _result_record(
                run_id,
                item,
                EbookFixityVerificationResult.UNREADABLE,
                current_sha256=None,
                failure_code=error.code.value,
            )
        if error.code is EbookFixityHashErrorCode.SOURCE_CHANGED:
            return _result_record(
                run_id,
                item,
                EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN,
                current_sha256=None,
                failure_code=error.code.value,
            )
        raise
    if item.expected_observation_id is None:
        result = EbookFixityVerificationResult.UNBASELINED
    elif (
        item.expected_size_bytes == item.current_size_bytes
        and item.expected_sha256 == current_sha256
    ):
        result = EbookFixityVerificationResult.VERIFIED
    else:
        result = EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE
    return _result_record(run_id, item, result, current_sha256=current_sha256)


def _result_record(
    run_id: EntityId,
    item: EbookFixityVerificationWorkItem,
    result: EbookFixityVerificationResult,
    *,
    current_sha256: str | None,
    failure_code: str | None = None,
) -> EbookFixityVerificationResultRecord:
    return EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=run_id,
        file_id=item.file_id,
        result=result,
        expected_observation_id=item.expected_observation_id,
        expected_size_bytes=item.expected_size_bytes,
        expected_sha256=item.expected_sha256,
        expected_relative_locator=item.expected_relative_locator,
        current_observation_id=item.current_observation_id,
        current_size_bytes=item.current_size_bytes,
        current_sha256=current_sha256,
        current_relative_locator=item.current_relative_locator,
        failure_code=failure_code,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_EBOOK_FIXITY_VERIFICATION_BATCH_SIZE",
    "MAX_EBOOK_FIXITY_VERIFICATION_HASH_WORKERS",
    "EbookFixityVerificationError",
    "EbookFixityVerifier",
]
