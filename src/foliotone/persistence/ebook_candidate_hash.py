"""Fenced SQLite lifecycle and batch commits for candidate hashing."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, Table, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from foliotone.core import (
    EbookCandidateHashPhase,
    EbookCandidateHashRun,
    EbookCandidateHashRunStatus,
    EntityId,
    Fingerprint,
)
from foliotone.persistence import schema, w3_schema
from foliotone.persistence._mapping import (
    datetime_to_db,
    required_datetime_from_db,
    required_id_from_db,
)
from foliotone.persistence.codecs import codec_for
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)


class EbookCandidateHashLeaseError(RuntimeError):
    """A candidate-hash run is concurrently owned or has lost its lease."""


class SQLiteEbookCandidateHashRunStore:
    """Persist path-free progress and fence every candidate-hash write."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._fingerprint_codec = codec_for(Fingerprint)
        self._write_leases = SQLiteScanRootWriteLeaseStore(engine)

    def acquire(
        self,
        scan_root_id: EntityId,
        source_scan_run_id: EntityId,
        profile: str,
        *,
        lease_token: str,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> EbookCandidateHashRun:
        """Interrupt an expired owner and atomically acquire a new root-wide run."""

        if lease_expires_at <= started_at:
            raise ValueError("candidate hash lease must expire after acquisition")
        table = w3_schema.ebook_candidate_hash_runs
        run = EbookCandidateHashRun(
            id=EntityId.new(),
            scan_root_id=scan_root_id,
            source_scan_run_id=source_scan_run_id,
            profile=profile,
            status=EbookCandidateHashRunStatus.RUNNING,
            phase=EbookCandidateHashPhase.SELECTING,
            started_at=started_at,
            heartbeat_at=started_at,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
        )
        try:
            with self._engine.begin() as connection:
                current = self._write_leases.current_in_transaction(
                    connection,
                    scan_root_id,
                )
                if current is None:
                    self._write_leases.acquire_in_transaction(
                        connection,
                        scan_root_id,
                        ScanRootWriteOwnerKind.EBOOK_CANDIDATE_HASH_RUN,
                        run.id,
                        lease_token=lease_token,
                        acquired_at=started_at,
                        lease_expires_at=lease_expires_at,
                    )
                else:
                    self._recover_candidate_owner(
                        connection,
                        current,
                        run,
                        started_at=started_at,
                        lease_expires_at=lease_expires_at,
                    )
                latest_scan = connection.execute(
                    select(schema.scan_runs.c.id, schema.scan_runs.c.status)
                    .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
                    .order_by(
                        schema.scan_runs.c.started_at.desc(),
                        schema.scan_runs.c.id.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                if (
                    latest_scan is None
                    or latest_scan.id != str(source_scan_run_id)
                    or latest_scan.status != "COMPLETED"
                ):
                    raise EbookCandidateHashLeaseError(
                        "candidate-hash source ScanRun is no longer current"
                    )
                connection.execute(insert(table).values(**_run_to_row(run)))
        except (IntegrityError, ScanRootWriteLeaseError) as error:
            raise EbookCandidateHashLeaseError(
                "another write workflow owns this ScanRoot"
            ) from error
        return run

    def heartbeat(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> None:
        """Renew one owned active run without changing its progress phase."""

        if lease_expires_at <= heartbeat_at:
            raise ValueError("heartbeat lease must expire after heartbeat")
        table = w3_schema.ebook_candidate_hash_runs
        heartbeat = _required_datetime_to_db(heartbeat_at)
        with self._engine.begin() as connection:
            root_lease = self._require_root_owner(
                connection,
                run_id,
                lease_token,
            )
            self._write_leases.heartbeat_in_transaction(
                connection,
                root_lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
            result = connection.execute(
                update(table)
                .where(*_owned_active_conditions(table, run_id, lease_token, heartbeat))
                .values(
                    heartbeat_at=heartbeat,
                    lease_expires_at=_required_datetime_to_db(lease_expires_at),
                )
            )
        _require_owned(result.rowcount)

    def record_selection(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
        candidate_groups: int,
        candidate_observations: int,
        already_hashed: int,
        remaining_count: int,
    ) -> None:
        """Publish the immutable candidate snapshot totals and enter hashing."""

        counts = (
            candidate_groups,
            candidate_observations,
            already_hashed,
            remaining_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("candidate selection counts must not be negative")
        if candidate_groups > candidate_observations:
            raise ValueError("candidate groups exceed candidate observations")
        if already_hashed > candidate_observations:
            raise ValueError("already_hashed exceeds candidate observations")
        if remaining_count != candidate_observations - already_hashed:
            raise ValueError("remaining_count is inconsistent with selection")
        table = w3_schema.ebook_candidate_hash_runs
        heartbeat = _required_datetime_to_db(heartbeat_at)
        with self._engine.begin() as connection:
            root_lease = self._require_root_owner(
                connection,
                run_id,
                lease_token,
            )
            self._write_leases.heartbeat_in_transaction(
                connection,
                root_lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
            result = connection.execute(
                update(table)
                .where(*_owned_active_conditions(table, run_id, lease_token, heartbeat))
                .values(
                    phase=EbookCandidateHashPhase.HASHING.value,
                    heartbeat_at=heartbeat,
                    lease_expires_at=_required_datetime_to_db(lease_expires_at),
                    candidate_groups=candidate_groups,
                    candidate_observations=candidate_observations,
                    already_hashed=already_hashed,
                    remaining_count=remaining_count,
                )
            )
        _require_owned(result.rowcount)

    def commit_batch(
        self,
        run_id: EntityId,
        lease_token: str,
        fingerprints: tuple[Fingerprint, ...],
        *,
        committed_at: datetime,
        lease_expires_at: datetime,
        processed_delta: int,
        failure_delta: int,
    ) -> None:
        """Fence progress and fingerprint inserts in the same transaction."""

        if processed_delta <= 0:
            raise ValueError("processed_delta must be positive")
        if not 0 <= failure_delta <= processed_delta:
            raise ValueError("failure_delta is outside the processed batch")
        hashed_delta = len(fingerprints)
        if hashed_delta + failure_delta != processed_delta:
            raise ValueError("batch outcomes do not match processed_delta")
        table = w3_schema.ebook_candidate_hash_runs
        committed = _required_datetime_to_db(committed_at)
        rows = [
            dict(self._fingerprint_codec.encode(fingerprint))
            for fingerprint in fingerprints
        ]
        with self._engine.begin() as connection:
            root_lease = self._require_root_owner(
                connection,
                run_id,
                lease_token,
            )
            self._write_leases.heartbeat_in_transaction(
                connection,
                root_lease,
                heartbeat_at=committed_at,
                lease_expires_at=lease_expires_at,
            )
            result = connection.execute(
                update(table)
                .where(*_owned_active_conditions(table, run_id, lease_token, committed))
                .values(
                    heartbeat_at=committed,
                    lease_expires_at=_required_datetime_to_db(lease_expires_at),
                    processed_count=table.c.processed_count + processed_delta,
                    hashed_count=table.c.hashed_count + hashed_delta,
                    failure_count=table.c.failure_count + failure_delta,
                    remaining_count=table.c.remaining_count - hashed_delta,
                )
            )
            _require_owned(result.rowcount)
            if rows:
                connection.execute(insert(self._fingerprint_codec.table), rows)

    def finish(
        self,
        run_id: EntityId,
        lease_token: str,
        status: EbookCandidateHashRunStatus,
        *,
        finished_at: datetime,
    ) -> None:
        """Publish one owned terminal outcome and release its lease."""

        if status not in {
            EbookCandidateHashRunStatus.INTERRUPTED,
            EbookCandidateHashRunStatus.COMPLETED,
            EbookCandidateHashRunStatus.COMPLETED_WITH_FAILURES,
        }:
            raise ValueError("finish requires a supported terminal status")
        table = w3_schema.ebook_candidate_hash_runs
        finished = _required_datetime_to_db(finished_at)
        with self._engine.begin() as connection:
            root_lease = self._require_root_owner(
                connection,
                run_id,
                lease_token,
            )
            self._write_leases.fence(connection, root_lease, finished_at)
            result = connection.execute(
                update(table)
                .where(*_owned_active_conditions(table, run_id, lease_token, finished))
                .values(
                    status=status.value,
                    phase=EbookCandidateHashPhase.FINALIZING.value,
                    heartbeat_at=finished,
                    finished_at=finished,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            _require_owned(result.rowcount)
            self._write_leases.release_in_transaction(
                connection,
                root_lease,
                released_at=finished_at,
            )

    def abandon_owned(
        self,
        run_id: EntityId,
        lease_token: str,
        status: EbookCandidateHashRunStatus,
        *,
        finished_at: datetime,
    ) -> None:
        """Best-effort terminal release that cannot overwrite a stale takeover."""

        if status not in {
            EbookCandidateHashRunStatus.INTERRUPTED,
            EbookCandidateHashRunStatus.FAILED,
        }:
            raise ValueError("abandon requires INTERRUPTED or FAILED")
        table = w3_schema.ebook_candidate_hash_runs
        finished = _required_datetime_to_db(finished_at)
        with self._engine.begin() as connection:
            try:
                root_lease = self._require_root_owner(
                    connection,
                    run_id,
                    lease_token,
                )
                self._write_leases.fence(connection, root_lease, finished_at)
            except (EbookCandidateHashLeaseError, ScanRootWriteLeaseError):
                return
            result = connection.execute(
                update(table)
                .where(
                    *_owned_active_conditions(
                        table,
                        run_id,
                        lease_token,
                        finished,
                    )
                )
                .values(
                    status=status.value,
                    phase=EbookCandidateHashPhase.FINALIZING.value,
                    heartbeat_at=finished,
                    finished_at=finished,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            if result.rowcount == 1:
                self._write_leases.release_in_transaction(
                    connection,
                    root_lease,
                    released_at=finished_at,
                )

    def _recover_candidate_owner(
        self,
        connection: Connection,
        current: OwnedScanRootWriteLease,
        replacement: EbookCandidateHashRun,
        *,
        started_at: datetime,
        lease_expires_at: datetime,
    ) -> None:
        if (
            current.owner_kind
            is not ScanRootWriteOwnerKind.EBOOK_CANDIDATE_HASH_RUN
            or current.lease_expires_at > started_at
        ):
            raise EbookCandidateHashLeaseError(
                "another write workflow owns this ScanRoot"
            )
        table = w3_schema.ebook_candidate_hash_runs
        started = _required_datetime_to_db(started_at)
        result = connection.execute(
            update(table)
            .where(
                table.c.id == str(current.owner_run_id),
                table.c.scan_root_id == str(current.scan_root_id),
                table.c.status == EbookCandidateHashRunStatus.RUNNING.value,
                table.c.lease_token == current.lease_token,
                table.c.lease_expires_at <= started,
            )
            .values(
                status=EbookCandidateHashRunStatus.INTERRUPTED.value,
                phase=EbookCandidateHashPhase.FINALIZING.value,
                heartbeat_at=started,
                finished_at=started,
                lease_token=None,
                lease_expires_at=None,
            )
        )
        _require_owned(result.rowcount)
        self._write_leases.takeover_expired_in_transaction(
            connection,
            current,
            replacement.id,
            lease_token=replacement.lease_token or "",
            acquired_at=started_at,
            lease_expires_at=lease_expires_at,
        )

    def _require_root_owner(
        self,
        connection: Connection,
        run_id: EntityId,
        lease_token: str,
    ) -> OwnedScanRootWriteLease:
        root_id = connection.execute(
            select(w3_schema.ebook_candidate_hash_runs.c.scan_root_id).where(
                w3_schema.ebook_candidate_hash_runs.c.id == str(run_id)
            )
        ).scalar_one_or_none()
        if root_id is None:
            raise EbookCandidateHashLeaseError("candidate-hash run does not exist")
        current = self._write_leases.current_in_transaction(
            connection,
            EntityId.parse(str(root_id)),
        )
        if (
            current is None
            or current.owner_kind
            is not ScanRootWriteOwnerKind.EBOOK_CANDIDATE_HASH_RUN
            or current.owner_run_id != run_id
            or current.lease_token != lease_token
        ):
            raise EbookCandidateHashLeaseError(
                "candidate-hash root ownership is unavailable"
            )
        return current

    def latest(self, scan_root_id: EntityId) -> EbookCandidateHashRun | None:
        """Load the latest durable path-free candidate-hash run for one root."""

        table = w3_schema.ebook_candidate_hash_runs
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(table)
                    .where(table.c.scan_root_id == str(scan_root_id))
                    .order_by(table.c.started_at.desc(), table.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _run_from_row(row)


def _owned_active_conditions(
    table: Table,
    run_id: EntityId,
    lease_token: str,
    now: str,
) -> tuple[ColumnElement[bool], ...]:
    return (
        table.c.id == str(run_id),
        table.c.status == EbookCandidateHashRunStatus.RUNNING.value,
        table.c.lease_token == lease_token,
        table.c.lease_expires_at > now,
    )


def _require_owned(rowcount: int | None) -> None:
    if rowcount != 1:
        raise EbookCandidateHashLeaseError(
            "candidate-hash lease is unavailable or expired"
        )


def _required_datetime_to_db(value: datetime) -> str:
    encoded = datetime_to_db(value)
    if encoded is None:
        raise AssertionError("non-null candidate hash datetime encoded as None")
    return encoded


def _run_to_row(run: EbookCandidateHashRun) -> dict[str, object]:
    return {
        "id": str(run.id),
        "scan_root_id": str(run.scan_root_id),
        "source_scan_run_id": str(run.source_scan_run_id),
        "profile": run.profile,
        "status": run.status.value,
        "phase": run.phase.value,
        "started_at": _required_datetime_to_db(run.started_at),
        "heartbeat_at": _required_datetime_to_db(run.heartbeat_at),
        "finished_at": datetime_to_db(run.finished_at),
        "lease_token": run.lease_token,
        "lease_expires_at": datetime_to_db(run.lease_expires_at),
        "candidate_groups": run.candidate_groups,
        "candidate_observations": run.candidate_observations,
        "already_hashed": run.already_hashed,
        "processed_count": run.processed_count,
        "hashed_count": run.hashed_count,
        "failure_count": run.failure_count,
        "remaining_count": run.remaining_count,
    }


def _run_from_row(row: RowMapping) -> EbookCandidateHashRun:
    return EbookCandidateHashRun(
        id=required_id_from_db(str(row["id"])),
        scan_root_id=required_id_from_db(str(row["scan_root_id"])),
        source_scan_run_id=required_id_from_db(str(row["source_scan_run_id"])),
        profile=str(row["profile"]),
        status=EbookCandidateHashRunStatus(str(row["status"])),
        phase=EbookCandidateHashPhase(str(row["phase"])),
        started_at=required_datetime_from_db(str(row["started_at"])),
        heartbeat_at=required_datetime_from_db(str(row["heartbeat_at"])),
        finished_at=(
            None
            if row["finished_at"] is None
            else required_datetime_from_db(str(row["finished_at"]))
        ),
        lease_token=(
            None if row["lease_token"] is None else str(row["lease_token"])
        ),
        lease_expires_at=(
            None
            if row["lease_expires_at"] is None
            else required_datetime_from_db(str(row["lease_expires_at"]))
        ),
        candidate_groups=_optional_int(row["candidate_groups"]),
        candidate_observations=_optional_int(row["candidate_observations"]),
        already_hashed=_optional_int(row["already_hashed"]),
        processed_count=int(row["processed_count"]),
        hashed_count=int(row["hashed_count"]),
        failure_count=int(row["failure_count"]),
        remaining_count=_optional_int(row["remaining_count"]),
    )


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))
