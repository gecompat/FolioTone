"""SQLite-backed operations optimized for incremental scan batches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import Engine, bindparam, exists, insert, select, update
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
from foliotone.persistence.codecs import codec_for


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """Persisted observations/events generated from one discovery batch."""

    observations: tuple[FileObservation, ...]
    events: tuple[FileScanEvent, ...]


class SQLiteIndexStore:
    """Index-specific queries and batched writes over the W1 SQLite persistence layer."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_root(self, root: ScanRoot) -> None:
        repository(self._engine, ScanRoot).save(root)

    def get_or_create_root(self, name: str, media_type: MediaType) -> ScanRoot:
        """Resolve one stable logical root by name or create it once."""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("scan root name must not be empty")

        codec = codec_for(ScanRoot)
        with self._engine.connect() as connection:
            row = connection.execute(
                select(schema.scan_roots).where(schema.scan_roots.c.name == normalized_name)
            ).mappings().one_or_none()
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
            row = connection.execute(
                select(schema.scan_runs)
                .where(schema.scan_runs.c.scan_root_id == str(root.id))
                .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                .limit(1)
            ).mappings().one_or_none()
        if row is None:
            return None
        return codec.decode(row)

    def latest_interrupted_run(self, root: ScanRoot) -> ScanRun | None:
        """Resolve the latest interrupted scan for this root, if any."""
        codec = codec_for(ScanRun)
        with self._engine.connect() as connection:
            row = connection.execute(
                select(schema.scan_runs)
                .where(
                    schema.scan_runs.c.scan_root_id == str(root.id),
                    schema.scan_runs.c.status == ScanRunStatus.INTERRUPTED.value,
                )
                .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                .limit(1)
            ).mappings().one_or_none()
        if row is None:
            return None
        return codec.decode(row)

    def start_scan(
        self,
        root: ScanRoot,
        started_at: datetime,
        *,
        resume_from: ScanRun | None = None,
    ) -> ScanRun:
        self.save_root(root)
        if resume_from is not None:
            persisted = repository(self._engine, ScanRun).get(resume_from.id)
            if persisted is None:
                raise ValueError(f"resume ScanRun {resume_from.id} does not exist")
            self._validate_resume_source(root, persisted)
            resume_from = persisted
        run = ScanRun(
            id=EntityId.new(),
            scan_root_id=root.id,
            started_at=started_at,
            status=ScanRunStatus.RUNNING,
            resumed_from_run_id=None if resume_from is None else resume_from.id,
        )
        repository(self._engine, ScanRun).save(run)
        return run

    @staticmethod
    def _validate_resume_source(root: ScanRoot, run: ScanRun) -> None:
        if run.scan_root_id != root.id:
            raise ValueError("resume ScanRun belongs to a different ScanRoot")
        if run.status is not ScanRunStatus.INTERRUPTED:
            raise ValueError("only an INTERRUPTED ScanRun can be resumed")

    def finish_scan(
        self,
        run: ScanRun,
        status: ScanRunStatus,
        completed_at: datetime,
    ) -> ScanRun:
        if status is ScanRunStatus.RUNNING:
            raise ValueError("finish_scan requires a terminal ScanRunStatus")
        finished = replace(run, status=status, completed_at=completed_at)
        repository(self._engine, ScanRun).save(finished)
        return finished

    def process_batch(
        self,
        root: ScanRoot,
        run: ScanRun,
        discovered: tuple[DiscoveredFile, ...],
        observed_at: datetime,
    ) -> BatchOutcome:
        """Compare and persist a bounded batch in one transaction."""
        if not discovered:
            return BatchOutcome((), ())

        paths = [item.relative_path for item in discovered]
        if len(paths) != len(set(paths)):
            raise ValueError("one scan batch must not contain duplicate relative paths")

        with self._engine.begin() as connection:
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
                    scan_run_id=run.id,
                    relative_path=item.relative_path,
                    size_bytes=item.size_bytes,
                    modified_at=item.modified_at,
                    observed_at=observed_at,
                )
                event = FileScanEvent(
                    id=EntityId.new(),
                    file_id=record.id,
                    scan_run_id=run.id,
                    change_state=state,
                    recorded_at=observed_at,
                    previous_relative_path=None if current is None else current.relative_path,
                    current_relative_path=record.relative_path,
                )
                observations.append(observation)
                events.append(event)

            _insert_many(connection, new_records)
            _update_many(connection, existing_records)
            _insert_many(connection, observations)
            _insert_many(connection, events)

        return BatchOutcome(tuple(observations), tuple(events))

    def mark_missing(
        self,
        root: ScanRoot,
        run: ScanRun,
        recorded_at: datetime,
        deletion_policy: DeletionConfirmationPolicy | None = None,
    ) -> tuple[FileScanEvent, ...]:
        """Record successful absence and optionally confirm sufficiently persistent deletion."""
        observation_exists = exists(
            select(schema.file_observations.c.id).where(
                schema.file_observations.c.file_id == schema.file_records.c.id,
                schema.file_observations.c.scan_run_id == str(run.id),
            )
        )

        with self._engine.begin() as connection:
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
                    scan_run_id=run.id,
                    change_state=change_state,
                    recorded_at=recorded_at,
                    previous_relative_path=current.relative_path,
                )
                _insert(connection, event)
                events.append(event)
            return tuple(events)

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
        current.size_bytes != discovered.size_bytes
        or current.modified_at != discovered.modified_at
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
        .values(
            {
                column.name: bindparam(column.name)
                for column in table.c
                if column.name != "id"
            }
        )
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

