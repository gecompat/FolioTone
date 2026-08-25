"""SQLite projection and append-only store for fixity baseline v1."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Engine, and_, func, insert, or_, select, text
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from foliotone.core import EntityId, MediaType, PresenceState, ScanRunStatus
from foliotone.fixity.confirmation import verify_fixity_baseline_confirmation
from foliotone.fixity.contracts import (
    EBOOK_FIXITY_BASELINE_PROFILE,
    EBOOK_FIXITY_BASELINE_SERIALIZER,
    EbookFixityBaselineActivation,
    EbookFixityBaselineBuildEventKind,
    EbookFixityBaselineBuildStatus,
    EbookFixityBaselineEntriesHasher,
    EbookFixityBaselineEntry,
    EbookFixityBaselineManifest,
    EbookFixityBaselineSourceEntry,
    EbookFixityBaselineStatusSnapshot,
)
from foliotone.persistence import fixity_schema, schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

DEFAULT_EBOOK_FIXITY_BATCH_SIZE = 64
MAX_EBOOK_FIXITY_BATCH_SIZE = 256
DEFAULT_EBOOK_FIXITY_LEASE_DURATION = timedelta(seconds=30)
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class EbookFixityBaselineStoreError(RuntimeError):
    """A baseline could not be projected or persisted safely."""


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineSource:
    """One stable read-only projection session for the latest valid scan."""

    scan_root_id: EntityId
    source_scan_run_id: EntityId
    expected_item_count: int
    _connection: Connection = field(repr=False, compare=False)
    _batch_size: int = field(repr=False, compare=False)

    def iter_batches(self) -> Iterator[tuple[EbookFixityBaselineSourceEntry, ...]]:
        """Yield current observations in bounded, deterministic keyset pages."""

        after_file_id: str | None = None
        after_observation_id: str | None = None
        seen = 0
        previous_file_id: str | None = None
        while True:
            query = (
                select(
                    schema.file_records.c.id.label("file_id"),
                    schema.file_observations.c.id.label("observation_id"),
                    schema.file_observations.c.relative_path,
                    schema.file_observations.c.size_bytes,
                    schema.file_observations.c.modified_at,
                )
                .select_from(
                    schema.file_observations.join(
                        schema.file_records,
                        schema.file_observations.c.file_id == schema.file_records.c.id,
                    )
                )
                .where(
                    schema.file_observations.c.scan_run_id == str(self.source_scan_run_id),
                    schema.file_records.c.scan_root_id == str(self.scan_root_id),
                    schema.file_records.c.media_type == MediaType.EBOOK.value,
                    schema.file_records.c.presence_state == PresenceState.PRESENT.value,
                    schema.file_records.c.relative_path == schema.file_observations.c.relative_path,
                    schema.file_records.c.size_bytes == schema.file_observations.c.size_bytes,
                    schema.file_records.c.modified_at == schema.file_observations.c.modified_at,
                )
                .order_by(schema.file_records.c.id, schema.file_observations.c.id)
                .limit(self._batch_size)
            )
            if after_file_id is not None and after_observation_id is not None:
                query = query.where(
                    or_(
                        schema.file_records.c.id > after_file_id,
                        and_(
                            schema.file_records.c.id == after_file_id,
                            schema.file_observations.c.id > after_observation_id,
                        ),
                    )
                )
            rows = self._connection.execute(query).mappings().all()
            if not rows:
                break
            entries: list[EbookFixityBaselineSourceEntry] = []
            for row in rows:
                file_id = str(row["file_id"])
                if file_id == previous_file_id:
                    raise EbookFixityBaselineStoreError(
                        "latest ScanRun has duplicate observations for one file"
                    )
                previous_file_id = file_id
                entries.append(
                    EbookFixityBaselineSourceEntry(
                        file_id=EntityId.parse(file_id),
                        observation_id=EntityId.parse(str(row["observation_id"])),
                        relative_locator=str(row["relative_path"]),
                        expected_size_bytes=int(row["size_bytes"]),
                        expected_modified_at=required_datetime_from_db(str(row["modified_at"])),
                    )
                )
            seen += len(entries)
            after_file_id = str(rows[-1]["file_id"])
            after_observation_id = str(rows[-1]["observation_id"])
            yield tuple(entries)
        if seen != self.expected_item_count:
            raise EbookFixityBaselineStoreError(
                "latest ScanRun does not cover every current EBOOK file"
            )


class SQLiteEbookFixityBaselineProjection:
    """Project baseline sources only through a true query-only SQLite engine."""

    def __init__(
        self,
        read_only_engine: Engine,
        *,
        batch_size: int = DEFAULT_EBOOK_FIXITY_BATCH_SIZE,
    ) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_EBOOK_FIXITY_BATCH_SIZE:
            raise ValueError("fixity batch_size must be between 1 and 256")
        self._engine = read_only_engine
        self._batch_size = batch_size

    def enabled_ebook_root_id(self) -> EntityId:
        """Return the sole enabled EBOOK root without exposing its configured name."""

        try:
            with self._engine.connect() as connection:
                self._require_query_only(connection)
                rows = (
                    connection.execute(
                        select(schema.scan_roots.c.id)
                        .where(
                            schema.scan_roots.c.media_type == MediaType.EBOOK.value,
                            schema.scan_roots.c.enabled.is_(True),
                        )
                        .order_by(schema.scan_roots.c.id)
                        .limit(2)
                    )
                    .scalars()
                    .all()
                )
        except EbookFixityBaselineStoreError:
            raise
        except Exception as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline read-only projection failed"
            ) from error
        if len(rows) != 1:
            raise EbookFixityBaselineStoreError("exactly one enabled EBOOK ScanRoot is required")
        return EntityId.parse(str(rows[0]))

    @contextmanager
    def open_latest(self, scan_root_id: EntityId) -> Iterator[EbookFixityBaselineSource]:
        """Hold one consistent query-only snapshot of the newest ScanRun overall."""

        try:
            with self._engine.connect() as connection:
                self._require_query_only(connection)
                root = (
                    connection.execute(
                        select(
                            schema.scan_roots.c.id,
                            schema.scan_roots.c.media_type,
                            schema.scan_roots.c.enabled,
                        ).where(schema.scan_roots.c.id == str(scan_root_id))
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    root is None
                    or str(root["media_type"]) != MediaType.EBOOK.value
                    or not bool(root["enabled"])
                ):
                    raise EbookFixityBaselineStoreError("enabled EBOOK ScanRoot is unavailable")
                latest = (
                    connection.execute(
                        select(
                            schema.scan_runs.c.id,
                            schema.scan_runs.c.status,
                            schema.scan_runs.c.completed_at,
                        )
                        .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
                        .order_by(
                            schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc()
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    latest is None
                    or str(latest["status"]) != ScanRunStatus.COMPLETED.value
                    or latest["completed_at"] is None
                ):
                    raise EbookFixityBaselineStoreError("newest ScanRun is not completed")
                current_count = int(
                    connection.execute(
                        select(func.count())
                        .select_from(schema.file_records)
                        .where(
                            schema.file_records.c.scan_root_id == str(scan_root_id),
                            schema.file_records.c.media_type == MediaType.EBOOK.value,
                            schema.file_records.c.presence_state == PresenceState.PRESENT.value,
                        )
                    ).scalar_one()
                )
                yield EbookFixityBaselineSource(
                    scan_root_id=scan_root_id,
                    source_scan_run_id=EntityId.parse(str(latest["id"])),
                    expected_item_count=current_count,
                    _connection=connection,
                    _batch_size=self._batch_size,
                )
                connection.rollback()
        except EbookFixityBaselineStoreError:
            raise
        except Exception as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline read-only projection failed"
            ) from error

    @staticmethod
    def _require_query_only(connection: Connection) -> None:
        if int(connection.execute(text("PRAGMA query_only")).scalar_one()) != 1:
            raise EbookFixityBaselineStoreError(
                "fixity baseline projection requires SQLite query_only"
            )


class SQLiteEbookFixityBaselineStore:
    """Persist baseline builds, manifests, and activations append-only."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def acquire_lease(
        self,
        scan_root_id: EntityId,
        owner_id: EntityId,
        *,
        acquired_at: datetime,
        lease_duration: timedelta = DEFAULT_EBOOK_FIXITY_LEASE_DURATION,
    ) -> OwnedScanRootWriteLease:
        """Acquire or recover only an expired prior fixity-baseline owner."""

        if lease_duration <= timedelta(0):
            raise ValueError("fixity lease_duration must be positive")
        token = str(EntityId.new())
        expires_at = acquired_at + lease_duration
        try:
            with self._engine.begin() as connection:
                return self._acquire_lease_in_transaction(
                    connection,
                    scan_root_id,
                    owner_id,
                    lease_token=token,
                    acquired_at=acquired_at,
                    lease_expires_at=expires_at,
                )
        except ScanRootWriteLeaseError as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline ScanRoot lease is unavailable"
            ) from error
        raise EbookFixityBaselineStoreError("fixity baseline ScanRoot lease is unavailable")

    def _acquire_lease_in_transaction(
        self,
        connection: Connection,
        scan_root_id: EntityId,
        owner_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        current = self._leases.current_in_transaction(connection, scan_root_id)
        if current is None:
            return self._leases.acquire_in_transaction(
                connection,
                scan_root_id,
                ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE,
                owner_id,
                lease_token=lease_token,
                acquired_at=acquired_at,
                lease_expires_at=lease_expires_at,
            )
        if (
            current.owner_kind is ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE
            and current.lease_expires_at <= acquired_at
        ):
            recovered = self._leases.takeover_expired_in_transaction(
                connection,
                current,
                owner_id,
                lease_token=lease_token,
                acquired_at=acquired_at,
                lease_expires_at=lease_expires_at,
            )
            self._fail_expired_build_in_transaction(
                connection,
                current.owner_run_id,
                failed_at=acquired_at,
            )
            return recovered
        raise EbookFixityBaselineStoreError("fixity baseline ScanRoot lease is unavailable")

    def heartbeat(
        self,
        lease: OwnedScanRootWriteLease,
        *,
        heartbeat_at: datetime,
        lease_duration: timedelta,
    ) -> None:
        try:
            self._leases.heartbeat(
                lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + lease_duration,
            )
        except ScanRootWriteLeaseError as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline ScanRoot lease was lost"
            ) from error

    def release(self, lease: OwnedScanRootWriteLease, *, released_at: datetime) -> None:
        try:
            self._leases.release(lease, released_at=released_at)
        except ScanRootWriteLeaseError as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline ScanRoot lease was lost"
            ) from error

    def start_build(
        self,
        manifest_id: EntityId,
        source_scan_run_id: EntityId,
        *,
        started_at: datetime,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if lease.owner_run_id != manifest_id or (
            lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE
        ):
            raise EbookFixityBaselineStoreError("fixity baseline lease is invalid")
        try:
            with self._engine.begin() as connection:
                self._leases.fence(connection, lease, started_at)
                self._require_no_active_baseline(connection, lease.scan_root_id)
                self._require_latest_completed_scan(
                    connection,
                    lease.scan_root_id,
                    source_scan_run_id,
                )
                connection.execute(
                    insert(fixity_schema.ebook_fixity_baseline_builds),
                    {
                        "manifest_id": str(manifest_id),
                        "profile": EBOOK_FIXITY_BASELINE_PROFILE,
                        "serializer": EBOOK_FIXITY_BASELINE_SERIALIZER,
                        "scan_root_id": str(lease.scan_root_id),
                        "source_scan_run_id": str(source_scan_run_id),
                        "started_at": _datetime_to_db(started_at),
                    },
                )
                connection.execute(
                    insert(fixity_schema.ebook_fixity_baseline_build_events),
                    {
                        "manifest_id": str(manifest_id),
                        "ordinal": 0,
                        "event_kind": EbookFixityBaselineBuildEventKind.STARTED.value,
                        "occurred_at": _datetime_to_db(started_at),
                        "failure_code": None,
                    },
                )
        except EbookFixityBaselineStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline build could not be started"
            ) from error

    def append_entries(
        self,
        manifest_id: EntityId,
        entries: Sequence[EbookFixityBaselineEntry],
        *,
        lease: OwnedScanRootWriteLease,
        committed_at: datetime,
    ) -> None:
        if not entries:
            return
        if len(entries) > MAX_EBOOK_FIXITY_BATCH_SIZE:
            raise ValueError("fixity entry batch exceeds the bounded maximum")
        if (
            lease.owner_run_id != manifest_id
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE
        ):
            raise EbookFixityBaselineStoreError("fixity baseline lease is invalid")
        try:
            with self._engine.begin() as connection:
                self._leases.fence(connection, lease, committed_at)
                build = self._build_row(connection, manifest_id)
                if str(build["scan_root_id"]) != str(lease.scan_root_id):
                    raise EbookFixityBaselineStoreError(
                        "fixity baseline build does not match its lease"
                    )
                self._require_entries_match_source(connection, build, entries)
                next_ordinal = int(
                    connection.execute(
                        select(
                            func.coalesce(
                                func.max(fixity_schema.ebook_fixity_baseline_entries.c.ordinal) + 1,
                                0,
                            )
                        ).where(
                            fixity_schema.ebook_fixity_baseline_entries.c.manifest_id
                            == str(manifest_id)
                        )
                    ).scalar_one()
                )
                if tuple(entry.ordinal for entry in entries) != tuple(
                    range(next_ordinal, next_ordinal + len(entries))
                ):
                    raise EbookFixityBaselineStoreError(
                        "fixity baseline entry batch is not contiguous"
                    )
                connection.execute(
                    insert(fixity_schema.ebook_fixity_baseline_entries),
                    [self._entry_row(manifest_id, entry) for entry in entries],
                )
        except EbookFixityBaselineStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline entry batch could not be persisted"
            ) from error

    def fail_build(
        self,
        manifest_id: EntityId,
        failure_code: str,
        *,
        failed_at: datetime,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if not _FAILURE_CODE.fullmatch(failure_code):
            raise ValueError("fixity failure_code is invalid")
        if (
            lease.owner_run_id != manifest_id
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE
        ):
            raise EbookFixityBaselineStoreError("fixity baseline lease is invalid")
        try:
            with self._engine.begin() as connection:
                self._leases.fence(connection, lease, failed_at)
                terminal = connection.execute(
                    select(fixity_schema.ebook_fixity_baseline_build_events.c.event_kind).where(
                        fixity_schema.ebook_fixity_baseline_build_events.c.manifest_id
                        == str(manifest_id),
                        fixity_schema.ebook_fixity_baseline_build_events.c.ordinal == 1,
                    )
                ).scalar_one_or_none()
                if terminal is None:
                    connection.execute(
                        insert(fixity_schema.ebook_fixity_baseline_build_events),
                        {
                            "manifest_id": str(manifest_id),
                            "ordinal": 1,
                            "event_kind": EbookFixityBaselineBuildEventKind.FAILED.value,
                            "occurred_at": _datetime_to_db(failed_at),
                            "failure_code": failure_code,
                        },
                    )
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline failure could not be recorded"
            ) from error

    def finalize_manifest(
        self,
        manifest_id: EntityId,
        *,
        prepared_at: datetime,
        expires_at: datetime,
        lease: OwnedScanRootWriteLease,
    ) -> EbookFixityBaselineManifest:
        if (
            lease.owner_run_id != manifest_id
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_FIXITY_BASELINE
        ):
            raise EbookFixityBaselineStoreError("fixity baseline lease is invalid")
        try:
            with self._engine.begin() as connection:
                self._leases.fence(connection, lease, prepared_at)
                build = self._build_row(connection, manifest_id)
                self._require_latest_completed_scan(
                    connection,
                    EntityId.parse(str(build["scan_root_id"])),
                    EntityId.parse(str(build["source_scan_run_id"])),
                )
                self._require_complete_entry_set(connection, build, manifest_id)
                hasher = EbookFixityBaselineEntriesHasher()
                total_size = 0
                rows = connection.execute(
                    select(fixity_schema.ebook_fixity_baseline_entries)
                    .where(
                        fixity_schema.ebook_fixity_baseline_entries.c.manifest_id
                        == str(manifest_id)
                    )
                    .order_by(fixity_schema.ebook_fixity_baseline_entries.c.ordinal)
                ).mappings()
                for row in rows:
                    entry = self._decode_entry(row)
                    hasher.update(entry)
                    total_size += entry.expected_size_bytes
                manifest = EbookFixityBaselineManifest(
                    manifest_id=manifest_id,
                    scan_root_id=EntityId.parse(str(build["scan_root_id"])),
                    source_scan_run_id=EntityId.parse(str(build["source_scan_run_id"])),
                    prepared_at=prepared_at,
                    expires_at=expires_at,
                    item_count=hasher.count,
                    total_size_bytes=total_size,
                    entries_digest=hasher.hexdigest(),
                )
                connection.execute(
                    insert(fixity_schema.ebook_fixity_baseline_manifests),
                    {
                        "manifest_id": str(manifest_id),
                        "prepared_at": _datetime_to_db(prepared_at),
                        "expires_at": _datetime_to_db(expires_at),
                        "item_count": manifest.item_count,
                        "total_size_bytes": manifest.total_size_bytes,
                        "entries_digest": manifest.entries_digest,
                        "content_digest": manifest.content_digest,
                    },
                )
                connection.execute(
                    insert(fixity_schema.ebook_fixity_baseline_build_events),
                    {
                        "manifest_id": str(manifest_id),
                        "ordinal": 1,
                        "event_kind": EbookFixityBaselineBuildEventKind.MANIFEST_READY.value,
                        "occurred_at": _datetime_to_db(prepared_at),
                        "failure_code": None,
                    },
                )
                return manifest
        except EbookFixityBaselineStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise EbookFixityBaselineStoreError(
                "fixity baseline manifest could not be finalized"
            ) from error

    def get_manifest(self, manifest_id: EntityId) -> EbookFixityBaselineManifest | None:
        with self._engine.connect() as connection:
            return self._read_manifest(connection, manifest_id)

    def list_private_entries(
        self, manifest_id: EntityId, *, after_ordinal: int | None = None, limit: int = 50
    ) -> tuple[tuple[EbookFixityBaselineEntry, ...], int | None]:
        """Return one bounded private manifest page."""
        if not 1 <= limit <= 100 or (after_ordinal is not None and after_ordinal < 0):
            raise ValueError("fixity entry page is invalid")
        table = fixity_schema.ebook_fixity_baseline_entries
        statement = select(table).where(table.c.manifest_id == str(manifest_id)).order_by(
            table.c.ordinal
        ).limit(limit + 1)
        if after_ordinal is not None:
            statement = statement.where(table.c.ordinal > after_ordinal)
        with self._engine.connect() as connection:
            exists = connection.execute(
                select(fixity_schema.ebook_fixity_baseline_manifests.c.manifest_id).where(
                    fixity_schema.ebook_fixity_baseline_manifests.c.manifest_id
                    == str(manifest_id)
                )
            ).scalar_one_or_none()
            if exists is None:
                raise ValueError("fixity baseline manifest is unavailable")
            rows = connection.execute(statement).mappings().all()
        entries = tuple(self._decode_entry(row) for row in rows[:limit])
        return entries, (None if len(rows) <= limit or not entries else entries[-1].ordinal)

    def read_status(self, manifest_id: EntityId) -> EbookFixityBaselineStatusSnapshot | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        fixity_schema.ebook_fixity_baseline_builds,
                        fixity_schema.ebook_fixity_baseline_manifests.c.prepared_at,
                        fixity_schema.ebook_fixity_baseline_manifests.c.expires_at,
                        fixity_schema.ebook_fixity_baseline_manifests.c.item_count,
                        fixity_schema.ebook_fixity_baseline_manifests.c.total_size_bytes,
                        fixity_schema.ebook_fixity_baseline_activations.c.activated_at,
                    )
                    .outerjoin(
                        fixity_schema.ebook_fixity_baseline_manifests,
                        fixity_schema.ebook_fixity_baseline_manifests.c.manifest_id
                        == fixity_schema.ebook_fixity_baseline_builds.c.manifest_id,
                    )
                    .outerjoin(
                        fixity_schema.ebook_fixity_baseline_activations,
                        fixity_schema.ebook_fixity_baseline_activations.c.manifest_id
                        == fixity_schema.ebook_fixity_baseline_builds.c.manifest_id,
                    )
                    .where(
                        fixity_schema.ebook_fixity_baseline_builds.c.manifest_id == str(manifest_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            event_kind = connection.execute(
                select(fixity_schema.ebook_fixity_baseline_build_events.c.event_kind)
                .where(
                    fixity_schema.ebook_fixity_baseline_build_events.c.manifest_id
                    == str(manifest_id)
                )
                .order_by(fixity_schema.ebook_fixity_baseline_build_events.c.ordinal.desc())
                .limit(1)
            ).scalar_one_or_none()
        if row is None:
            return None
        if event_kind is None:
            raise EbookFixityBaselineStoreError("fixity baseline build has no lifecycle event")
        event = EbookFixityBaselineBuildEventKind(str(event_kind))
        if row["activated_at"] is not None:
            status = EbookFixityBaselineBuildStatus.ACTIVE
        elif event is EbookFixityBaselineBuildEventKind.MANIFEST_READY:
            status = EbookFixityBaselineBuildStatus.READY
        elif event is EbookFixityBaselineBuildEventKind.FAILED:
            status = EbookFixityBaselineBuildStatus.FAILED
        else:
            status = EbookFixityBaselineBuildStatus.BUILDING
        return EbookFixityBaselineStatusSnapshot(
            manifest_id=manifest_id,
            scan_root_id=EntityId.parse(str(row["scan_root_id"])),
            source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])),
            status=status,
            started_at=required_datetime_from_db(str(row["started_at"])),
            prepared_at=_optional_datetime(row["prepared_at"]),
            expires_at=_optional_datetime(row["expires_at"]),
            item_count=None if row["item_count"] is None else int(row["item_count"]),
            total_size_bytes=(
                None if row["total_size_bytes"] is None else int(row["total_size_bytes"])
            ),
            activated_at=_optional_datetime(row["activated_at"]),
        )

    def activate(
        self,
        manifest_id: EntityId,
        confirmation: str,
        *,
        activated_at: datetime,
        lease_duration: timedelta = DEFAULT_EBOOK_FIXITY_LEASE_DURATION,
    ) -> EbookFixityBaselineActivation:
        # Preserve the direct store's established validation error contract.
        # The connection-scoped path verifies again inside its transaction.
        verify_fixity_baseline_confirmation(manifest_id, confirmation)
        try:
            with self._engine.begin() as connection:
                return self.activate_in_transaction(
                    connection,
                    manifest_id,
                    confirmation,
                    activated_at=activated_at,
                    lease_duration=lease_duration,
                )
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise EbookFixityBaselineStoreError("fixity baseline could not be activated") from error

    def activate_in_transaction(
        self,
        connection: Connection,
        manifest_id: EntityId,
        confirmation: str,
        *,
        activated_at: datetime,
        lease_duration: timedelta = DEFAULT_EBOOK_FIXITY_LEASE_DURATION,
    ) -> EbookFixityBaselineActivation:
        """Validate and activate within a caller-owned crash-atomic transaction."""

        confirmation_digest = verify_fixity_baseline_confirmation(manifest_id, confirmation)
        current = self._read_manifest(connection, manifest_id)
        if current is None:
            raise EbookFixityBaselineStoreError("fixity baseline manifest is unavailable")
        if not current.prepared_at <= activated_at < current.expires_at:
            raise EbookFixityBaselineStoreError(
                "fixity baseline manifest activation window expired"
            )
        activation_id = EntityId.new()
        lease = self._acquire_lease_in_transaction(
            connection,
            current.scan_root_id,
            activation_id,
            lease_token=str(EntityId.new()),
            acquired_at=activated_at,
            lease_expires_at=activated_at + lease_duration,
        )
        self._leases.fence(connection, lease, activated_at)
        self._require_latest_completed_scan(
            connection,
            current.scan_root_id,
            current.source_scan_run_id,
        )
        self._require_no_active_baseline(connection, current.scan_root_id)
        activation = EbookFixityBaselineActivation(
            activation_id=activation_id,
            manifest_id=manifest_id,
            scan_root_id=current.scan_root_id,
            activated_at=activated_at,
            manifest_content_digest=current.content_digest,
            confirmation_digest=confirmation_digest,
        )
        connection.execute(
            insert(fixity_schema.ebook_fixity_baseline_activations),
            {
                "activation_id": str(activation.activation_id),
                "manifest_id": str(activation.manifest_id),
                "scan_root_id": str(activation.scan_root_id),
                "profile": EBOOK_FIXITY_BASELINE_PROFILE,
                "activated_at": _datetime_to_db(activation.activated_at),
                "manifest_content_digest": activation.manifest_content_digest,
                "confirmation_digest": activation.confirmation_digest,
                "activation_digest": activation.activation_digest,
            },
        )
        self._leases.release_in_transaction(connection, lease, released_at=activated_at)
        return activation

    def _release_best_effort(
        self,
        lease: OwnedScanRootWriteLease,
        *,
        released_at: datetime,
    ) -> None:
        try:
            self.release(lease, released_at=released_at)
        except EbookFixityBaselineStoreError:
            pass

    @staticmethod
    def _entry_row(manifest_id: EntityId, entry: EbookFixityBaselineEntry) -> dict[str, object]:
        return {
            "manifest_id": str(manifest_id),
            "ordinal": entry.ordinal,
            "file_id": str(entry.file_id),
            "observation_id": str(entry.observation_id),
            "expected_size_bytes": entry.expected_size_bytes,
            "relative_locator": entry.relative_locator,
            "hash_algorithm": "sha256",
            "hash_algorithm_version": "1",
            "expected_sha256": entry.expected_sha256,
            "entry_digest": entry.entry_digest,
        }

    @staticmethod
    def _decode_entry(row: RowMapping) -> EbookFixityBaselineEntry:
        return EbookFixityBaselineEntry(
            ordinal=int(row["ordinal"]),
            file_id=EntityId.parse(str(row["file_id"])),
            observation_id=EntityId.parse(str(row["observation_id"])),
            expected_size_bytes=int(row["expected_size_bytes"]),
            relative_locator=str(row["relative_locator"]),
            expected_sha256=str(row["expected_sha256"]),
            entry_digest=str(row["entry_digest"]),
        )

    @staticmethod
    def _build_row(connection: Connection, manifest_id: EntityId) -> RowMapping:
        row = (
            connection.execute(
                select(fixity_schema.ebook_fixity_baseline_builds).where(
                    fixity_schema.ebook_fixity_baseline_builds.c.manifest_id == str(manifest_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EbookFixityBaselineStoreError("fixity baseline build is unavailable")
        return row

    @staticmethod
    def _require_entries_match_source(
        connection: Connection,
        build: RowMapping,
        entries: Sequence[EbookFixityBaselineEntry],
    ) -> None:
        observation_ids = tuple(str(entry.observation_id) for entry in entries)
        rows = (
            connection.execute(
                select(
                    schema.file_observations.c.id.label("observation_id"),
                    schema.file_observations.c.file_id,
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.relative_path.label("observation_path"),
                    schema.file_observations.c.size_bytes.label("observation_size"),
                    schema.file_observations.c.modified_at.label("observation_modified"),
                    schema.file_records.c.scan_root_id,
                    schema.file_records.c.relative_path.label("record_path"),
                    schema.file_records.c.size_bytes.label("record_size"),
                    schema.file_records.c.modified_at.label("record_modified"),
                    schema.file_records.c.media_type,
                    schema.file_records.c.presence_state,
                )
                .select_from(
                    schema.file_observations.join(
                        schema.file_records,
                        schema.file_observations.c.file_id == schema.file_records.c.id,
                    )
                )
                .where(schema.file_observations.c.id.in_(observation_ids))
            )
            .mappings()
            .all()
        )
        by_observation = {str(row["observation_id"]): row for row in rows}
        if len(by_observation) != len(entries):
            raise EbookFixityBaselineStoreError(
                "fixity baseline entry source observation is unavailable"
            )
        for entry in entries:
            row = by_observation.get(str(entry.observation_id))
            if row is None or (
                str(row["file_id"]) != str(entry.file_id)
                or str(row["scan_run_id"]) != str(build["source_scan_run_id"])
                or str(row["scan_root_id"]) != str(build["scan_root_id"])
                or str(row["media_type"]) != MediaType.EBOOK.value
                or str(row["presence_state"]) != PresenceState.PRESENT.value
                or str(row["observation_path"]) != entry.relative_locator
                or str(row["record_path"]) != entry.relative_locator
                or int(row["observation_size"]) != entry.expected_size_bytes
                or int(row["record_size"]) != entry.expected_size_bytes
                or str(row["observation_modified"]) != str(row["record_modified"])
            ):
                raise EbookFixityBaselineStoreError(
                    "fixity baseline entry is not bound to the latest source scan"
                )

    @staticmethod
    def _require_complete_entry_set(
        connection: Connection,
        build: RowMapping,
        manifest_id: EntityId,
    ) -> None:
        root_id = str(build["scan_root_id"])
        scan_run_id = str(build["source_scan_run_id"])
        entries = fixity_schema.ebook_fixity_baseline_entries
        records = schema.file_records
        observations = schema.file_observations
        current_filter = (
            records.c.scan_root_id == root_id,
            records.c.media_type == MediaType.EBOOK.value,
            records.c.presence_state == PresenceState.PRESENT.value,
        )
        source_filter = (
            observations.c.scan_run_id == scan_run_id,
            observations.c.relative_path == records.c.relative_path,
            observations.c.size_bytes == records.c.size_bytes,
            observations.c.modified_at == records.c.modified_at,
        )
        expected_count = int(
            connection.execute(
                select(func.count()).select_from(records).where(*current_filter)
            ).scalar_one()
        )
        source_count = int(
            connection.execute(
                select(func.count())
                .select_from(observations.join(records, observations.c.file_id == records.c.id))
                .where(*current_filter, *source_filter)
            ).scalar_one()
        )
        bound_entry_count = int(
            connection.execute(
                select(func.count())
                .select_from(
                    entries.join(
                        observations,
                        entries.c.observation_id == observations.c.id,
                    ).join(records, entries.c.file_id == records.c.id)
                )
                .where(
                    entries.c.manifest_id == str(manifest_id),
                    entries.c.file_id == observations.c.file_id,
                    entries.c.relative_locator == observations.c.relative_path,
                    entries.c.relative_locator == records.c.relative_path,
                    entries.c.expected_size_bytes == observations.c.size_bytes,
                    entries.c.expected_size_bytes == records.c.size_bytes,
                    *current_filter,
                    *source_filter,
                )
            ).scalar_one()
        )
        if expected_count != source_count or expected_count != bound_entry_count:
            raise EbookFixityBaselineStoreError(
                "fixity baseline does not cover the complete current source scan"
            )

    @staticmethod
    def _fail_expired_build_in_transaction(
        connection: Connection,
        expired_owner_id: EntityId,
        *,
        failed_at: datetime,
    ) -> None:
        manifest_id = str(expired_owner_id)
        build_exists = connection.execute(
            select(fixity_schema.ebook_fixity_baseline_builds.c.manifest_id)
            .where(fixity_schema.ebook_fixity_baseline_builds.c.manifest_id == manifest_id)
            .limit(1)
        ).first()
        terminal_exists = connection.execute(
            select(fixity_schema.ebook_fixity_baseline_build_events.c.manifest_id)
            .where(
                fixity_schema.ebook_fixity_baseline_build_events.c.manifest_id == manifest_id,
                fixity_schema.ebook_fixity_baseline_build_events.c.ordinal == 1,
            )
            .limit(1)
        ).first()
        if build_exists is not None and terminal_exists is None:
            connection.execute(
                insert(fixity_schema.ebook_fixity_baseline_build_events),
                {
                    "manifest_id": manifest_id,
                    "ordinal": 1,
                    "event_kind": EbookFixityBaselineBuildEventKind.FAILED.value,
                    "occurred_at": _datetime_to_db(failed_at),
                    "failure_code": "LEASE_EXPIRED",
                },
            )

    def _read_manifest(
        self, connection: Connection, manifest_id: EntityId
    ) -> EbookFixityBaselineManifest | None:
        row = (
            connection.execute(
                select(
                    fixity_schema.ebook_fixity_baseline_builds,
                    fixity_schema.ebook_fixity_baseline_manifests,
                )
                .join(
                    fixity_schema.ebook_fixity_baseline_manifests,
                    fixity_schema.ebook_fixity_baseline_manifests.c.manifest_id
                    == fixity_schema.ebook_fixity_baseline_builds.c.manifest_id,
                )
                .where(fixity_schema.ebook_fixity_baseline_builds.c.manifest_id == str(manifest_id))
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return EbookFixityBaselineManifest(
            manifest_id=manifest_id,
            scan_root_id=EntityId.parse(str(row["scan_root_id"])),
            source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])),
            prepared_at=required_datetime_from_db(str(row["prepared_at"])),
            expires_at=required_datetime_from_db(str(row["expires_at"])),
            item_count=int(row["item_count"]),
            total_size_bytes=int(row["total_size_bytes"]),
            entries_digest=str(row["entries_digest"]),
            content_digest=str(row["content_digest"]),
        )

    @staticmethod
    def _require_no_active_baseline(connection: Connection, scan_root_id: EntityId) -> None:
        if (
            connection.execute(
                select(fixity_schema.ebook_fixity_baseline_activations.c.activation_id)
                .where(
                    fixity_schema.ebook_fixity_baseline_activations.c.profile
                    == EBOOK_FIXITY_BASELINE_PROFILE,
                    fixity_schema.ebook_fixity_baseline_activations.c.scan_root_id
                    == str(scan_root_id),
                )
                .limit(1)
            ).first()
            is not None
        ):
            raise EbookFixityBaselineStoreError(
                "an active fixity baseline already exists for this ScanRoot"
            )

    @staticmethod
    def _require_latest_completed_scan(
        connection: Connection,
        scan_root_id: EntityId,
        expected_scan_run_id: EntityId,
    ) -> None:
        roots = (
            connection.execute(
                select(schema.scan_roots.c.id).where(
                    schema.scan_roots.c.media_type == MediaType.EBOOK.value,
                    schema.scan_roots.c.enabled.is_(True),
                )
            )
            .scalars()
            .all()
        )
        latest = (
            connection.execute(
                select(
                    schema.scan_runs.c.id,
                    schema.scan_runs.c.status,
                    schema.scan_runs.c.completed_at,
                )
                .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
                .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            len(roots) != 1
            or str(roots[0]) != str(scan_root_id)
            or latest is None
            or str(latest["id"]) != str(expected_scan_run_id)
            or str(latest["status"]) != ScanRunStatus.COMPLETED.value
            or latest["completed_at"] is None
        ):
            raise EbookFixityBaselineStoreError("fixity baseline source scan is no longer current")


def _datetime_to_db(value: datetime) -> str:
    encoded = datetime_to_db(value)
    if encoded is None:
        raise ValueError("fixity datetime is required")
    return encoded


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else required_datetime_from_db(str(value))


__all__ = [
    "DEFAULT_EBOOK_FIXITY_BATCH_SIZE",
    "DEFAULT_EBOOK_FIXITY_LEASE_DURATION",
    "EbookFixityBaselineSource",
    "EbookFixityBaselineStoreError",
    "SQLiteEbookFixityBaselineProjection",
    "SQLiteEbookFixityBaselineStore",
]
