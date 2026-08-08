"""SQLite-backed operations optimized for incremental scan batches."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import Engine, exists, insert, select, update
from sqlalchemy.engine import Connection

from foliotone.core import (
    EntityId,
    FileChangeState,
    FileObservation,
    FileRecord,
    FileScanEvent,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
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

    def start_scan(self, root: ScanRoot, started_at: datetime) -> ScanRun:
        self.save_root(root)
        run = ScanRun(
            id=EntityId.new(),
            scan_root_id=root.id,
            started_at=started_at,
            status=ScanRunStatus.RUNNING,
        )
        repository(self._engine, ScanRun).save(run)
        return run

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
            for item in discovered:
                current = existing.get(item.relative_path)
                record, state = _reconcile_file(root, current, item, observed_at)
                _upsert(connection, record)

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
                _insert(connection, observation)
                _insert(connection, event)
                observations.append(observation)
                events.append(event)

        return BatchOutcome(tuple(observations), tuple(events))

    def mark_missing(
        self,
        root: ScanRoot,
        run: ScanRun,
        recorded_at: datetime,
    ) -> tuple[FileScanEvent, ...]:
        """Mark known files not observed in a successful scan as MISSING."""
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
                if current.presence_state is not PresenceState.MISSING:
                    _upsert(connection, replace(current, presence_state=PresenceState.MISSING))
                event = FileScanEvent(
                    id=EntityId.new(),
                    file_id=current.id,
                    scan_run_id=run.id,
                    change_state=FileChangeState.MISSING,
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
        ),
        state,
    )


def _insert(connection: Connection, value: object) -> None:
    codec = codec_for(type(value))
    connection.execute(insert(codec.table).values(**dict(codec.encode(value))))


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
