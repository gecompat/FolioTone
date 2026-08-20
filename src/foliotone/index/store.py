"""SQLite-backed operations optimized for incremental scan batches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import Engine, bindparam, exists, insert, or_, select, update
from sqlalchemy.engine import Connection

from foliotone.core import (
    EntityId,
    FileChangeState,
    FileObservation,
    FileRecord,
    FileScanEvent,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.index.deletion import DeletionConfirmationPolicy
from foliotone.index.discovery import DiscoveredFile
from foliotone.persistence import repository, schema, w2_schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.codecs import codec_for
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

DEFAULT_SCAN_LEASE_DURATION = timedelta(minutes=30)


class ScanLeaseError(RuntimeError):
    """A scan lease is active, expired, or no longer owned by this invocation."""


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """Persisted observations/events generated from one discovery batch."""

    observations: tuple[FileObservation, ...]
    events: tuple[FileScanEvent, ...]


@dataclass(frozen=True, slots=True)
class OwnedScanRun:
    """A running ScanRun coupled to its root-wide fencing proof."""

    run: ScanRun
    write_lease: OwnedScanRootWriteLease


class SQLiteIndexStore:
    """Index-specific queries and batched writes over the W1 SQLite persistence layer."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._write_leases = SQLiteScanRootWriteLeaseStore(engine)

    def save_root(self, root: ScanRoot) -> None:
        repository(self._engine, ScanRoot).save(root)

    def get_or_create_root(self, name: str, media_type: MediaType) -> ScanRoot:
        """Resolve one stable logical root by name or create it once."""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("scan root name must not be empty")

        codec = codec_for(ScanRoot)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(schema.scan_roots).where(schema.scan_roots.c.name == normalized_name)
                )
                .mappings()
                .one_or_none()
            )
        if row is not None:
            root = codec.decode(row)
            if root.media_type is not media_type:
                raise ValueError(
                    f"scan root {normalized_name!r} already exists with media type "
                    f"{root.media_type.value}"
                )
            return root

        root = ScanRoot(id=EntityId.new(), name=normalized_name, media_type=media_type)
        self.save_root(root)
        return root

    def get_resumable_run(self, root: ScanRoot, run_id: EntityId) -> ScanRun:
        """Resolve a persisted interrupted run that belongs to the requested root."""
        run = repository(self._engine, ScanRun).get(run_id)
        if run is None:
            raise ValueError(f"resume ScanRun {run_id} does not exist")
        self._validate_resume_source(root, run)
        return run

    def latest_run(self, root: ScanRoot) -> ScanRun | None:
        """Resolve the latest persisted scan for this root, if any."""
        codec = codec_for(ScanRun)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(schema.scan_runs)
                    .where(schema.scan_runs.c.scan_root_id == str(root.id))
                    .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return codec.decode(row)

    def latest_interrupted_run(self, root: ScanRoot) -> ScanRun | None:
        """Resolve the latest interrupted scan for this root, if any."""
        codec = codec_for(ScanRun)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(schema.scan_runs)
                    .where(
                        schema.scan_runs.c.scan_root_id == str(root.id),
                        schema.scan_runs.c.status == ScanRunStatus.INTERRUPTED.value,
                    )
                    .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return codec.decode(row)

    def start_scan(
        self,
        root: ScanRoot,
        started_at: datetime,
        *,
        resume_from: ScanRun | None = None,
        lease_token: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> OwnedScanRun:
        self.save_root(root)
        if resume_from is not None:
            persisted = repository(self._engine, ScanRun).get(resume_from.id)
            if persisted is None:
                raise ValueError(f"resume ScanRun {resume_from.id} does not exist")
            self._validate_resume_source(root, persisted)
            resume_from = persisted
        if lease_token is None and lease_expires_at is None:
            lease_token = str(EntityId.new())
            lease_expires_at = started_at + DEFAULT_SCAN_LEASE_DURATION
        if lease_token is None or lease_expires_at is None:
            raise ValueError("scan lease token and expiry must be provided together")
        run_id = EntityId.new()
        run = ScanRun(
            id=run_id,
            scan_root_id=root.id,
            started_at=started_at,
            status=ScanRunStatus.RUNNING,
            resumed_from_run_id=None if resume_from is None else resume_from.id,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
        )
        codec = codec_for(ScanRun)
        try:
            with self._engine.begin() as connection:
                write_lease = self._write_leases.acquire_in_transaction(
                    connection,
                    root.id,
                    ScanRootWriteOwnerKind.SCAN_RUN,
                    run_id,
                    lease_token=lease_token,
                    acquired_at=started_at,
                    lease_expires_at=lease_expires_at,
                )
                connection.execute(insert(schema.scan_runs).values(**codec.encode(run)))
        except ScanRootWriteLeaseError as error:
            raise ScanLeaseError("another write workflow owns this ScanRoot") from error
        return OwnedScanRun(run=run, write_lease=write_lease)

    def recover_latest_stale_run(
        self,
        root: ScanRoot,
        recovered_at: datetime,
    ) -> ScanRun:
        """Atomically turn the latest unleased or expired RUNNING run into INTERRUPTED."""
        encoded_recovered_at = datetime_to_db(recovered_at)
        if encoded_recovered_at is None:
            raise AssertionError("non-null recovery time encoded as None")
        codec = codec_for(ScanRun)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(schema.scan_runs)
                    .where(
                        schema.scan_runs.c.scan_root_id == str(root.id),
                        schema.scan_runs.c.status == ScanRunStatus.RUNNING.value,
                    )
                    .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("no RUNNING ScanRun exists for this ScanRoot")
            run = codec.decode(row)
            if run.lease_expires_at is not None and run.lease_expires_at > recovered_at:
                raise ScanLeaseError("the latest RUNNING ScanRun still has an active lease")

            current_lease = self._write_leases.current_in_transaction(
                connection,
                root.id,
            )
            if (
                current_lease is None
                or current_lease.owner_kind is not ScanRootWriteOwnerKind.SCAN_RUN
                or current_lease.owner_run_id != run.id
                or current_lease.lease_expires_at > recovered_at
            ):
                raise ScanLeaseError("the ScanRoot writer is not recoverable")
            recovery = self._write_leases.takeover_expired_in_transaction(
                connection,
                current_lease,
                run.id,
                lease_token=str(EntityId.new()),
                acquired_at=recovered_at,
                lease_expires_at=recovered_at + DEFAULT_SCAN_LEASE_DURATION,
            )
            recovered = replace(
                run,
                status=ScanRunStatus.INTERRUPTED,
                completed_at=recovered_at,
                lease_token=None,
                lease_expires_at=None,
            )
            encoded = dict(codec.encode(recovered))
            result = connection.execute(
                update(schema.scan_runs)
                .where(
                    schema.scan_runs.c.id == str(run.id),
                    schema.scan_runs.c.status == ScanRunStatus.RUNNING.value,
                    or_(
                        schema.scan_runs.c.lease_expires_at.is_(None),
                        schema.scan_runs.c.lease_expires_at <= encoded_recovered_at,
                    ),
                )
                .values(**encoded)
            )
            if result.rowcount != 1:
                raise ScanLeaseError("the RUNNING ScanRun lease changed during recovery")
            self._write_leases.release_in_transaction(
                connection,
                recovery,
                released_at=recovered_at,
            )
            return recovered

    def heartbeat_scan(
        self,
        owned: OwnedScanRun,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRun:
        """Extend one still-active lease owned by this scan invocation."""
        if lease_expires_at <= heartbeat_at:
            raise ValueError("heartbeat lease must expire after heartbeat_at")
        run = owned.run
        if run.lease_token is None or run.lease_expires_at is None:
            raise ScanLeaseError("the RUNNING ScanRun has no owned lease")
        renewed = replace(run, lease_expires_at=lease_expires_at)
        encoded_heartbeat_at = datetime_to_db(heartbeat_at)
        if encoded_heartbeat_at is None:
            raise AssertionError("non-null heartbeat time encoded as None")
        with self._engine.begin() as connection:
            renewed_write_lease = self._write_leases.heartbeat_in_transaction(
                connection,
                owned.write_lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
            result = connection.execute(
                update(schema.scan_runs)
                .where(
                    schema.scan_runs.c.id == str(run.id),
                    schema.scan_runs.c.status == ScanRunStatus.RUNNING.value,
                    schema.scan_runs.c.lease_token == run.lease_token,
                    schema.scan_runs.c.lease_expires_at > encoded_heartbeat_at,
                )
                .values(lease_expires_at=datetime_to_db(lease_expires_at))
            )
        if result.rowcount != 1:
            raise ScanLeaseError("the RUNNING ScanRun lease is unavailable or expired")
        return OwnedScanRun(run=renewed, write_lease=renewed_write_lease)

    @staticmethod
    def _validate_resume_source(root: ScanRoot, run: ScanRun) -> None:
        if run.scan_root_id != root.id:
            raise ValueError("resume ScanRun belongs to a different ScanRoot")
        if run.status is not ScanRunStatus.INTERRUPTED:
            raise ValueError("only an INTERRUPTED ScanRun can be resumed")

    def finish_scan(
        self,
        owned: OwnedScanRun,
        status: ScanRunStatus,
        completed_at: datetime,
    ) -> OwnedScanRun:
        run = owned.run
        if status is ScanRunStatus.RUNNING:
            raise ValueError("finish_scan requires a terminal ScanRunStatus")
        finished = replace(
            run,
            status=status,
            completed_at=completed_at,
            lease_token=None,
            lease_expires_at=None,
        )
        codec = codec_for(ScanRun)
        encoded = dict(codec.encode(finished))
        lease_condition = (
            schema.scan_runs.c.lease_token.is_(None)
            if run.lease_token is None
            else schema.scan_runs.c.lease_token == run.lease_token
        )
        with self._engine.begin() as connection:
            self._fence_owned_scan(connection, owned, completed_at)
            result = connection.execute(
                update(schema.scan_runs)
                .where(
                    schema.scan_runs.c.id == str(run.id),
                    schema.scan_runs.c.status == ScanRunStatus.RUNNING.value,
                    lease_condition,
                )
                .values(**encoded)
            )
            if result.rowcount == 1:
                self._write_leases.release_in_transaction(
                    connection,
                    owned.write_lease,
                    released_at=completed_at,
                )
        if result.rowcount != 1:
            raise ScanLeaseError("the RUNNING ScanRun is no longer owned by this invocation")
        return OwnedScanRun(run=finished, write_lease=owned.write_lease)

    def process_batch(
        self,
        root: ScanRoot,
        owned: OwnedScanRun,
        discovered: tuple[DiscoveredFile, ...],
        observed_at: datetime,
        *,
        on_item_reconciled: Callable[[int, int], None] | None = None,
    ) -> BatchOutcome:
        """Compare and persist a bounded batch in one transaction."""
        if not discovered:
            return BatchOutcome((), ())

        paths = [item.relative_path for item in discovered]
        if len(paths) != len(set(paths)):
            raise ValueError("one scan batch must not contain duplicate relative paths")

        with self._engine.begin() as connection:
            self._fence_owned_scan(connection, owned, observed_at)
            existing_rows = connection.execute(
                select(schema.file_records).where(
                    schema.file_records.c.scan_root_id == str(root.id),
                    schema.file_records.c.relative_path.in_(paths),
                )
            ).mappings()
            file_codec = codec_for(FileRecord)
            existing = {row["relative_path"]: file_codec.decode(row) for row in existing_rows}

            observations: list[FileObservation] = []
            events: list[FileScanEvent] = []
            new_records: list[FileRecord] = []
            existing_records: list[FileRecord] = []
            reconciled_bytes = 0
            for item in discovered:
                current = existing.get(item.relative_path)
                record, state = _reconcile_file(root, current, item, observed_at)
                if current is None:
                    new_records.append(record)
                else:
                    existing_records.append(record)

                observation = FileObservation(
                    id=EntityId.new(),
                    file_id=record.id,
                    scan_run_id=owned.run.id,
                    relative_path=item.relative_path,
                    size_bytes=item.size_bytes,
                    modified_at=item.modified_at,
                    observed_at=observed_at,
                )
                event = FileScanEvent(
                    id=EntityId.new(),
                    file_id=record.id,
                    scan_run_id=owned.run.id,
                    change_state=state,
                    recorded_at=observed_at,
                    previous_relative_path=None if current is None else current.relative_path,
                    current_relative_path=record.relative_path,
                )
                observations.append(observation)
                events.append(event)
                reconciled_bytes += item.size_bytes
                if on_item_reconciled is not None:
                    on_item_reconciled(len(observations), reconciled_bytes)

            _insert_many(connection, new_records)
            _update_many(connection, existing_records)
            _insert_many(connection, observations)
            _insert_many(connection, events)

        return BatchOutcome(tuple(observations), tuple(events))

    def mark_missing(
        self,
        root: ScanRoot,
        owned: OwnedScanRun,
        recorded_at: datetime,
        deletion_policy: DeletionConfirmationPolicy | None = None,
    ) -> tuple[FileScanEvent, ...]:
        """Record successful absence and optionally confirm sufficiently persistent deletion."""
        observation_exists = exists(
            select(schema.file_observations.c.id).where(
                schema.file_observations.c.file_id == schema.file_records.c.id,
                schema.file_observations.c.scan_run_id == str(owned.run.id),
            )
        )

        with self._engine.begin() as connection:
            self._fence_owned_scan(connection, owned, recorded_at)
            rows = connection.execute(
                select(schema.file_records).where(
                    schema.file_records.c.scan_root_id == str(root.id),
                    schema.file_records.c.presence_state != PresenceState.DELETED.value,
                    ~observation_exists,
                )
            ).mappings()
            codec = codec_for(FileRecord)
            events: list[FileScanEvent] = []
            for row in rows:
                current = codec.decode(row)
                if (
                    current.presence_state is PresenceState.MISSING
                    and current.missing_since_at is not None
                ):
                    missing_since_at = current.missing_since_at
                    consecutive_missing_scans = current.consecutive_missing_scans + 1
                else:
                    missing_since_at = recorded_at
                    consecutive_missing_scans = 1

                confirmed_deleted = deletion_policy is not None and deletion_policy.confirms(
                    consecutive_missing_scans=consecutive_missing_scans,
                    missing_since_at=missing_since_at,
                    evaluated_at=recorded_at,
                )
                presence_state = (
                    PresenceState.DELETED if confirmed_deleted else PresenceState.MISSING
                )
                change_state = (
                    FileChangeState.DELETED if confirmed_deleted else FileChangeState.MISSING
                )
                _upsert(
                    connection,
                    replace(
                        current,
                        presence_state=presence_state,
                        missing_since_at=missing_since_at,
                        consecutive_missing_scans=consecutive_missing_scans,
                    ),
                )
                event = FileScanEvent(
                    id=EntityId.new(),
                    file_id=current.id,
                    scan_run_id=owned.run.id,
                    change_state=change_state,
                    recorded_at=recorded_at,
                    previous_relative_path=current.relative_path,
                )
                _insert(connection, event)
                events.append(event)
            return tuple(events)

    def _fence_owned_scan(
        self,
        connection: Connection,
        owned: OwnedScanRun,
        now: datetime,
    ) -> None:
        try:
            self._write_leases.fence(connection, owned.write_lease, now)
        except ScanRootWriteLeaseError as error:
            raise ScanLeaseError("ScanRoot write ownership is unavailable") from error
        run = owned.run
        encoded_now = datetime_to_db(now)
        if encoded_now is None:
            raise AssertionError("non-null scan fence time encoded as None")
        result = connection.execute(
            update(schema.scan_runs)
            .where(
                schema.scan_runs.c.id == str(run.id),
                schema.scan_runs.c.status == ScanRunStatus.RUNNING.value,
                schema.scan_runs.c.lease_token == run.lease_token,
                schema.scan_runs.c.lease_expires_at > encoded_now,
            )
            .values(lease_expires_at=schema.scan_runs.c.lease_expires_at)
        )
        if result.rowcount != 1:
            raise ScanLeaseError("the RUNNING ScanRun lease is unavailable or expired")

    def list_events(self, run: ScanRun) -> list[FileScanEvent]:
        """Return scan events for one run in deterministic ID order."""
        codec = codec_for(FileScanEvent)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(w2_schema.file_scan_events)
                .where(w2_schema.file_scan_events.c.scan_run_id == str(run.id))
                .order_by(w2_schema.file_scan_events.c.id)
            ).mappings()
            return [codec.decode(row) for row in rows]


def _reconcile_file(
    root: ScanRoot,
    current: FileRecord | None,
    discovered: DiscoveredFile,
    observed_at: datetime,
) -> tuple[FileRecord, FileChangeState]:
    if current is None:
        return (
            FileRecord(
                id=EntityId.new(),
                scan_root_id=root.id,
                relative_path=discovered.relative_path,
                size_bytes=discovered.size_bytes,
                modified_at=discovered.modified_at,
                media_type=root.media_type,
                presence_state=PresenceState.PRESENT,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            ),
            FileChangeState.NEW,
        )

    if current.presence_state is not PresenceState.PRESENT:
        state = FileChangeState.REAPPEARED
    elif (
        current.size_bytes != discovered.size_bytes or current.modified_at != discovered.modified_at
    ):
        state = FileChangeState.MODIFIED
    else:
        state = FileChangeState.UNCHANGED

    return (
        replace(
            current,
            size_bytes=discovered.size_bytes,
            modified_at=discovered.modified_at,
            presence_state=PresenceState.PRESENT,
            last_seen_at=observed_at,
            missing_since_at=None,
            consecutive_missing_scans=0,
        ),
        state,
    )


def _insert(connection: Connection, value: object) -> None:
    codec = codec_for(type(value))
    connection.execute(insert(codec.table).values(**dict(codec.encode(value))))


def _insert_many(connection: Connection, values: Sequence[object]) -> None:
    if not values:
        return
    codec = codec_for(type(values[0]))
    rows = [dict(codec.encode(value)) for value in values]
    connection.execute(insert(codec.table), rows)


def _update_many(connection: Connection, values: Sequence[object]) -> None:
    if not values:
        return
    codec = codec_for(type(values[0]))
    table = codec.table
    rows: list[dict[str, object]] = []
    for value in values:
        row = dict(codec.encode(value))
        entity_id = row.pop("id", None)
        if not isinstance(entity_id, str):
            raise TypeError("persistence codec must encode an 'id' string")
        row["_foliotone_entity_id"] = entity_id
        rows.append(row)
    statement = (
        update(table)
        .where(table.c.id == bindparam("_foliotone_entity_id"))
        .values({column.name: bindparam(column.name) for column in table.c if column.name != "id"})
    )
    connection.execute(statement, rows)


def _upsert(connection: Connection, value: object) -> None:
    codec = codec_for(type(value))
    row = dict(codec.encode(value))
    entity_id = row.get("id")
    if not isinstance(entity_id, str):
        raise TypeError("persistence codec must encode an 'id' string")
    exists_value = connection.execute(
        select(codec.table.c.id).where(codec.table.c.id == entity_id)
    ).scalar_one_or_none()
    if exists_value is None:
        connection.execute(insert(codec.table).values(**row))
    else:
        connection.execute(update(codec.table).where(codec.table.c.id == entity_id).values(**row))
