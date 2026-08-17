"""Bounded full-hash enrichment for quick duplicate candidates."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Engine,
    Index,
    MetaData,
    String,
    Table,
    Text,
    and_,
    case,
    func,
    insert,
    or_,
    select,
)

from foliotone.analyzers.ebook.observations import (
    ObservedFileError,
    resolve_observed_file,
)
from foliotone.core import (
    EbookCandidateHashRunStatus,
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index.hashing import (
    FULL_FILE_PROFILE,
    QUICK_FILE_PROFILE,
    FingerprintWriter,
)
from foliotone.persistence import (
    EbookCandidateHashLeaseError,
    SQLiteEbookCandidateHashRunStore,
    schema,
)
from foliotone.persistence.codecs import codec_for

DUPLICATE_HASH_PROFILE = "ebook-duplicate-hash/v1"
MAX_DUPLICATE_HASH_WORKERS = 8
MAX_DUPLICATE_HASH_BATCH_SIZE = 500
DEFAULT_DUPLICATE_HASH_LEASE_DURATION = timedelta(minutes=30)
MAX_DUPLICATE_HASH_HEARTBEAT_SECONDS = 60.0

type Clock = Callable[[], datetime]
type ProgressReporter = Callable[[str], None]

_CANDIDATE_SNAPSHOT_TABLE = "_foliotone_duplicate_hash_candidates"


class DuplicateHashCandidateError(RuntimeError):
    """A duplicate-candidate hash invocation cannot satisfy its safety contract."""


@dataclass(frozen=True, slots=True)
class DuplicateHashCandidateSummary:
    """Path-free outcome for one resumable candidate enrichment invocation."""

    run_id: EntityId
    scan_run_id: EntityId
    candidate_groups: int
    candidate_observations: int
    already_hashed: int
    hashed_this_invocation: int
    hash_failures: int
    remaining: int
    profile: str = DUPLICATE_HASH_PROFILE

    def __post_init__(self) -> None:
        counts = (
            self.candidate_groups,
            self.candidate_observations,
            self.already_hashed,
            self.hashed_this_invocation,
            self.hash_failures,
            self.remaining,
        )
        if any(value < 0 for value in counts):
            raise ValueError("duplicate hash counts must not be negative")
        if self.already_hashed > self.candidate_observations:
            raise ValueError("already-hashed count exceeds candidate observations")
        if not self.profile.strip():
            raise ValueError("duplicate hash profile must not be empty")


@dataclass(frozen=True, slots=True)
class _HashCandidate:
    quick_value: str
    observation: FileObservation

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.quick_value, str(self.observation.id)


class _CandidateHashLeaseKeeper:
    """Renew a candidate-hash lease while one file or SQL step is long-running."""

    def __init__(
        self,
        store: SQLiteEbookCandidateHashRunStore,
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
            MAX_DUPLICATE_HASH_HEARTBEAT_SECONDS,
            lease_duration.total_seconds() / 3,
        )
        self._stop = Event()
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="foliotone-candidate-hash-heartbeat",
            daemon=True,
        )
        self._error: Exception | None = None

    def __enter__(self) -> _CandidateHashLeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self._stop.set()
        self._thread.join()

    def check(self) -> None:
        """Surface a failed background renewal before the next fenced write."""

        if self._error is not None:
            raise EbookCandidateHashLeaseError(
                "candidate-hash heartbeat failed"
            ) from self._error

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval):
            heartbeat_at = self._clock()
            try:
                self._store.heartbeat(
                    self._run_id,
                    self._lease_token,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=heartbeat_at + self._lease_duration,
                )
            except Exception as error:
                self._error = error
                return


class DuplicateHashCandidateService:
    """Confirm only quick-fingerprint collisions with a full SHA-256."""

    def __init__(
        self,
        engine: Engine,
        *,
        fingerprint_writer: FingerprintWriter | None = None,
        clock: Clock | None = None,
        run_store: SQLiteEbookCandidateHashRunStore | None = None,
        lease_duration: timedelta = DEFAULT_DUPLICATE_HASH_LEASE_DURATION,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("candidate hash lease_duration must be positive")
        self._engine = engine
        self._fingerprints = fingerprint_writer or FingerprintWriter(engine)
        self._clock = clock or _utc_now
        self._runs = run_store or SQLiteEbookCandidateHashRunStore(engine)
        self._lease_duration = lease_duration
        self._observation_codec = codec_for(FileObservation)
        self._scan_codec = codec_for(ScanRun)

    def enrich(
        self,
        root: ScanRoot,
        source_root: Path,
        *,
        worker_count: int = 1,
        batch_size: int = 64,
        max_items: int | None = None,
        progress: ProgressReporter | None = None,
    ) -> DuplicateHashCandidateSummary:
        """Hash pending quick-collision members in bounded restartable batches."""

        if root.media_type is not MediaType.EBOOK or not root.enabled:
            raise DuplicateHashCandidateError(
                "ScanRoot must be an enabled EBOOK root"
            )
        if not 1 <= worker_count <= MAX_DUPLICATE_HASH_WORKERS:
            raise ValueError(
                "worker_count must be between 1 and "
                f"{MAX_DUPLICATE_HASH_WORKERS}"
            )
        if not 1 <= batch_size <= MAX_DUPLICATE_HASH_BATCH_SIZE:
            raise ValueError(
                "batch_size must be between 1 and "
                f"{MAX_DUPLICATE_HASH_BATCH_SIZE}"
            )
        if max_items is not None and max_items <= 0:
            raise ValueError("max_items must be positive when provided")
        try:
            resolved_root = source_root.resolve(strict=True)
        except OSError as error:
            raise DuplicateHashCandidateError("source root is unavailable") from error
        if not resolved_root.is_dir():
            raise DuplicateHashCandidateError("source root is not a directory")

        scan = self._latest_scan(root)
        started_at = self._clock()
        lease_token = str(EntityId.new())
        try:
            run = self._runs.acquire(
                root.id,
                scan.id,
                DUPLICATE_HASH_PROFILE,
                lease_token=lease_token,
                started_at=started_at,
                lease_expires_at=started_at + self._lease_duration,
            )
        except EbookCandidateHashLeaseError as error:
            raise DuplicateHashCandidateError(str(error)) from error

        keeper = _CandidateHashLeaseKeeper(
            self._runs,
            run.id,
            lease_token,
            clock=self._clock,
            lease_duration=self._lease_duration,
        )
        try:
            with keeper:
                summary = self._enrich_owned(
                    run.id,
                    lease_token,
                    keeper,
                    root,
                    scan,
                    resolved_root,
                    worker_count=worker_count,
                    batch_size=batch_size,
                    max_items=max_items,
                    progress=progress,
                )
                keeper.check()
                if summary.hash_failures:
                    status = EbookCandidateHashRunStatus.COMPLETED_WITH_FAILURES
                elif summary.remaining:
                    status = EbookCandidateHashRunStatus.INTERRUPTED
                else:
                    status = EbookCandidateHashRunStatus.COMPLETED
                self._runs.finish(
                    run.id,
                    lease_token,
                    status,
                    finished_at=self._clock(),
                )
                return summary
        except KeyboardInterrupt:
            self._runs.abandon_owned(
                run.id,
                lease_token,
                EbookCandidateHashRunStatus.INTERRUPTED,
                finished_at=self._clock(),
            )
            raise
        except EbookCandidateHashLeaseError as error:
            self._runs.abandon_owned(
                run.id,
                lease_token,
                EbookCandidateHashRunStatus.FAILED,
                finished_at=self._clock(),
            )
            raise DuplicateHashCandidateError(
                "candidate-hash lease is unavailable or expired"
            ) from error
        except Exception:
            self._runs.abandon_owned(
                run.id,
                lease_token,
                EbookCandidateHashRunStatus.FAILED,
                finished_at=self._clock(),
            )
            raise

    def _enrich_owned(
        self,
        run_id: EntityId,
        lease_token: str,
        keeper: _CandidateHashLeaseKeeper,
        root: ScanRoot,
        scan: ScanRun,
        resolved_root: Path,
        *,
        worker_count: int,
        batch_size: int,
        max_items: int | None,
        progress: ProgressReporter | None,
    ) -> DuplicateHashCandidateSummary:
        """Execute one invocation whose writes are fenced by an owned run lease."""

        self._report(progress, "candidate selection started")
        processed = 0
        hashed = 0
        failures = 0
        cursor: tuple[str, str] | None = None
        snapshot = self._candidate_snapshot_table()

        with self._engine.connect() as snapshot_connection:
            try:
                self._prepare_candidate_snapshot(
                    snapshot_connection,
                    snapshot,
                    root,
                    scan,
                )
                groups, observations, already_hashed = self._snapshot_stats(
                    snapshot_connection,
                    snapshot,
                )
                snapshot_connection.rollback()
                pending = observations - already_hashed
                heartbeat_at = self._clock()
                keeper.check()
                self._runs.record_selection(
                    run_id,
                    lease_token,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=heartbeat_at + self._lease_duration,
                    candidate_groups=groups,
                    candidate_observations=observations,
                    already_hashed=already_hashed,
                    remaining_count=pending,
                )
                self._report(
                    progress,
                    "candidate selection completed: "
                    f"groups={groups}, observations={observations}, pending={pending}",
                )

                while max_items is None or processed < max_items:
                    keeper.check()
                    limit = batch_size
                    if max_items is not None:
                        limit = min(limit, max_items - processed)
                    candidates = self._next_candidates(
                        snapshot_connection,
                        snapshot,
                        after=cursor,
                        limit=limit,
                    )
                    snapshot_connection.rollback()
                    if not candidates:
                        break
                    succeeded, failed = self._hash_batch(
                        resolved_root,
                        candidates,
                        worker_count=worker_count,
                        created_at=self._clock(),
                    )
                    keeper.check()
                    committed_at = self._clock()
                    self._runs.commit_batch(
                        run_id,
                        lease_token,
                        succeeded,
                        committed_at=committed_at,
                        lease_expires_at=committed_at + self._lease_duration,
                        processed_delta=len(candidates),
                        failure_delta=failed,
                    )
                    hashed += len(succeeded)
                    failures += failed
                    processed += len(candidates)
                    cursor = candidates[-1].sort_key
                    self._report(
                        progress,
                        "full hashing: "
                        f"processed={processed}/{pending}, hashed={hashed}, "
                        f"failures={failures}, remaining={pending - hashed}",
                    )
            finally:
                snapshot_connection.rollback()
                self._drop_candidate_snapshot(snapshot_connection)
                snapshot_connection.commit()

        remaining = pending - hashed
        return DuplicateHashCandidateSummary(
            run_id=run_id,
            scan_run_id=scan.id,
            candidate_groups=groups,
            candidate_observations=observations,
            already_hashed=already_hashed,
            hashed_this_invocation=hashed,
            hash_failures=failures,
            remaining=remaining,
        )

    def _latest_scan(self, root: ScanRoot) -> ScanRun:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(schema.scan_runs)
                .where(schema.scan_runs.c.scan_root_id == str(root.id))
                .order_by(
                    schema.scan_runs.c.started_at.desc(),
                    schema.scan_runs.c.id.desc(),
                )
                .limit(1)
            ).mappings().one_or_none()
        if row is None:
            raise DuplicateHashCandidateError("ScanRoot has no persisted ScanRun")
        scan = self._scan_codec.decode(row)
        if scan.status is not ScanRunStatus.COMPLETED:
            raise DuplicateHashCandidateError(
                "latest ScanRun must be COMPLETED before candidate hashing"
            )
        return scan

    @staticmethod
    def _report(progress: ProgressReporter | None, message: str) -> None:
        if progress is not None:
            progress(message)

    @staticmethod
    def _candidate_snapshot_table() -> Table:
        metadata = MetaData()
        snapshot = Table(
            _CANDIDATE_SNAPSHOT_TABLE,
            metadata,
            Column("observation_id", String(36), primary_key=True),
            Column("quick_value", Text, nullable=False),
            Column("full_hashed", Boolean, nullable=False),
            prefixes=["TEMPORARY"],
        )
        Index(
            "_ix_foliotone_duplicate_hash_candidates_pending",
            snapshot.c.full_hashed,
            snapshot.c.quick_value,
            snapshot.c.observation_id,
        )
        Index(
            "_ix_foliotone_duplicate_hash_candidates_group",
            snapshot.c.quick_value,
            snapshot.c.observation_id,
        )
        return snapshot

    def _prepare_candidate_snapshot(
        self,
        connection: Connection,
        snapshot: Table,
        root: ScanRoot,
        scan: ScanRun,
    ) -> None:
        self._drop_candidate_snapshot(connection)
        snapshot.create(connection)
        current, groups, full_hash_targets = self._candidate_tables(root, scan)
        rows = (
            select(
                current.c.observation_id,
                current.c.quick_value,
                case(
                    (full_hash_targets.c.observation_id.is_not(None), True),
                    else_=False,
                ).label("full_hashed"),
            )
            .select_from(
                current.join(
                    groups,
                    groups.c.quick_value == current.c.quick_value,
                ).outerjoin(
                    full_hash_targets,
                    full_hash_targets.c.observation_id == current.c.observation_id,
                )
            )
        )
        connection.execute(
            insert(snapshot).from_select(
                [
                    snapshot.c.observation_id,
                    snapshot.c.quick_value,
                    snapshot.c.full_hashed,
                ],
                rows,
            )
        )
        connection.commit()

    @staticmethod
    def _snapshot_stats(
        connection: Connection,
        snapshot: Table,
    ) -> tuple[int, int, int]:
        groups, observations, already_hashed = connection.execute(
            select(
                func.count(func.distinct(snapshot.c.quick_value)),
                func.count(),
                func.coalesce(
                    func.sum(
                        case(
                            (snapshot.c.full_hashed.is_(True), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).select_from(snapshot)
        ).one()
        return int(groups), int(observations), int(already_hashed)

    def _next_candidates(
        self,
        connection: Connection,
        snapshot: Table,
        *,
        after: tuple[str, str] | None,
        limit: int,
    ) -> tuple[_HashCandidate, ...]:
        observation = schema.file_observations
        statement = (
            select(observation, snapshot.c.quick_value)
            .join(snapshot, snapshot.c.observation_id == observation.c.id)
            .where(snapshot.c.full_hashed.is_(False))
            .order_by(snapshot.c.quick_value, observation.c.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                or_(
                    snapshot.c.quick_value > after[0],
                    and_(
                        snapshot.c.quick_value == after[0],
                        observation.c.id > after[1],
                    ),
                )
            )
        rows = connection.execute(statement).mappings().all()
        return tuple(
            _HashCandidate(
                quick_value=str(row["quick_value"]),
                observation=self._observation_codec.decode(row),
            )
            for row in rows
        )

    def _candidate_tables(
        self,
        root: ScanRoot,
        scan: ScanRun,
    ) -> tuple[Any, Any, Any]:
        fingerprint = schema.fingerprints
        observation = schema.file_observations
        record = schema.file_records
        current = (
            select(
                observation.c.id.label("observation_id"),
                func.min(fingerprint.c.value).label("quick_value"),
            )
            .select_from(
                observation.join(record, record.c.id == observation.c.file_id).join(
                    fingerprint,
                    and_(
                        fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        fingerprint.c.kind == QUICK_FILE_PROFILE[0],
                        fingerprint.c.algorithm == QUICK_FILE_PROFILE[1],
                        fingerprint.c.algorithm_version == QUICK_FILE_PROFILE[2],
                        fingerprint.c.target_id == observation.c.id,
                    ),
                )
            )
            .where(
                observation.c.scan_run_id == str(scan.id),
                record.c.scan_root_id == str(root.id),
                record.c.media_type == MediaType.EBOOK.value,
                record.c.presence_state == PresenceState.PRESENT.value,
                record.c.relative_path == observation.c.relative_path,
                record.c.size_bytes == observation.c.size_bytes,
                record.c.modified_at == observation.c.modified_at,
            )
            .group_by(observation.c.id)
            .having(func.count(func.distinct(fingerprint.c.value)) == 1)
            .cte("current_quick_observations")
        )
        groups = (
            select(
                current.c.quick_value,
                func.count().label("member_count"),
            )
            .group_by(current.c.quick_value)
            .having(func.count() > 1)
            .cte("quick_duplicate_groups")
        )
        full_hash_targets = (
            select(fingerprint.c.target_id.label("observation_id"))
            .where(
                fingerprint.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                fingerprint.c.kind == FULL_FILE_PROFILE[0],
                fingerprint.c.algorithm == FULL_FILE_PROFILE[1],
                fingerprint.c.algorithm_version == FULL_FILE_PROFILE[2],
            )
            .group_by(fingerprint.c.target_id)
            .cte("full_hash_targets")
        )
        return current, groups, full_hash_targets

    @staticmethod
    def _drop_candidate_snapshot(connection: Connection) -> None:
        connection.exec_driver_sql(
            f"DROP TABLE IF EXISTS temp.{_CANDIDATE_SNAPSHOT_TABLE}"
        )

    def _hash_batch(
        self,
        source_root: Path,
        candidates: tuple[_HashCandidate, ...],
        *,
        worker_count: int,
        created_at: datetime,
    ) -> tuple[tuple[Fingerprint, ...], int]:
        def calculate(candidate: _HashCandidate) -> Fingerprint | None:
            try:
                physical_path = resolve_observed_file(
                    source_root,
                    candidate.observation,
                )
                fingerprint = self._fingerprints.calculate_full(
                    candidate.observation,
                    physical_path,
                    created_at,
                )
                resolve_observed_file(source_root, candidate.observation)
            except (ObservedFileError, OSError):
                return None
            return fingerprint

        if worker_count == 1 or len(candidates) <= 1:
            outcomes = tuple(calculate(candidate) for candidate in candidates)
        else:
            with ThreadPoolExecutor(
                max_workers=min(worker_count, len(candidates)),
                thread_name_prefix="foliotone-duplicate-hash",
            ) as executor:
                outcomes = tuple(executor.map(calculate, candidates))
        succeeded = tuple(outcome for outcome in outcomes if outcome is not None)
        return succeeded, len(outcomes) - len(succeeded)


def _utc_now() -> datetime:
    return datetime.now(UTC)
