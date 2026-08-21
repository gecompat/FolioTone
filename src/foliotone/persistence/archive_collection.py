"""Fenced SQLite transitions for restartable archive collection plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, and_, func, insert, or_, select, update
from sqlalchemy.engine import Connection, RowMapping

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservationV2,
    ArchiveStorageFamily,
    ArchiveSuffixKind,
)
from foliotone.core import (
    ArchiveCollectionDisposition,
    ArchiveCollectionItem,
    ArchiveCollectionItemSource,
    ArchiveCollectionItemStatus,
    ArchiveCollectionPlanFindingCounts,
    ArchiveCollectionRun,
    ArchiveCollectionRunStatus,
    EntityId,
)
from foliotone.core._validation import require_relative_path
from foliotone.persistence import archive_collection_schema as tables
from foliotone.persistence import archive_schema, schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

ARCHIVE_COLLECTION_PLAN_BATCH_SIZE = 500
_PLAN_HASH_DOMAIN = b"archive-collection-plan/v1\x00"


class ArchiveCollectionStoreError(RuntimeError):
    """An archive collection transition failed without exposing private data."""


@dataclass(frozen=True, slots=True)
class ArchiveCollectionPlanEntry:
    item: ArchiveCollectionItem
    sources: tuple[ArchiveCollectionItemSource, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.item, ArchiveCollectionItem):
            raise ValueError("archive collection plan item is invalid")
        if (
            not isinstance(self.sources, tuple)
            or not 1 <= len(self.sources) <= 256
            or any(not isinstance(source, ArchiveCollectionItemSource) for source in self.sources)
        ):
            raise ValueError("archive collection plan sources are invalid")
        if tuple(source.source_ordinal for source in self.sources) != tuple(
            range(len(self.sources))
        ):
            raise ValueError("archive collection source ordinals are not contiguous")
        if any(
            source.run_id != self.item.run_id or source.item_id != self.item.id
            for source in self.sources
        ):
            raise ValueError("archive collection source lineage is invalid")
        canonical = tuple(source for source in self.sources if source.staging_name == "archive")
        if (
            len(canonical) != 1
            or canonical[0].file_observation_id != self.item.primary_file_observation_id
        ):
            raise ValueError("archive collection plan requires one canonical source")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionWorkItem:
    item: ArchiveCollectionItem
    sources: tuple[ArchiveCollectionItemSource, ...]


@dataclass(frozen=True, slots=True)
class _ArchiveCollectionResolvedSource:
    source: ArchiveCollectionItemSource
    relative_path: str = dataclass_field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, ArchiveCollectionItemSource):
            raise ValueError("archive collection resolved source is invalid")
        object.__setattr__(
            self, "relative_path", require_relative_path(self.relative_path)
        )


@dataclass(frozen=True, slots=True)
class _ArchiveCollectionLiteralCount:
    literal: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.literal, str) or not self.literal:
            raise ValueError("archive collection aggregate literal is invalid")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError("archive collection aggregate count is invalid")


@dataclass(frozen=True, slots=True)
class _ArchiveCollectionReportSnapshot:
    run: ArchiveCollectionRun
    item_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    dispositions: tuple[_ArchiveCollectionLiteralCount, ...]
    listing_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    integrity_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    encryption_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    recognition_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    storage_families: tuple[_ArchiveCollectionLiteralCount, ...]
    error_codes: tuple[_ArchiveCollectionLiteralCount, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run, ArchiveCollectionRun):
            raise ValueError("archive collection report run is invalid")
        for values in (
            self.item_statuses,
            self.dispositions,
            self.listing_statuses,
            self.integrity_statuses,
            self.encryption_statuses,
            self.recognition_statuses,
            self.storage_families,
            self.error_codes,
        ):
            if (
                not isinstance(values, tuple)
                or any(not isinstance(value, _ArchiveCollectionLiteralCount) for value in values)
                or tuple(value.literal for value in values)
                != tuple(sorted(value.literal for value in values))
                or len({value.literal for value in values}) != len(values)
            ):
                raise ValueError("archive collection report aggregates are invalid")


def archive_collection_plan_content_hash(
    run: ArchiveCollectionRun,
    entries: tuple[ArchiveCollectionPlanEntry, ...],
    findings: ArchiveCollectionPlanFindingCounts,
) -> str:
    """Hash the complete immutable, path-free plan projection."""

    if not isinstance(run, ArchiveCollectionRun):
        raise ValueError("archive collection plan run is invalid")
    if not isinstance(findings, ArchiveCollectionPlanFindingCounts):
        raise ValueError("archive collection plan findings are invalid")
    if (
        not isinstance(entries, tuple)
        or any(not isinstance(entry, ArchiveCollectionPlanEntry) for entry in entries)
        or tuple(entry.item.plan_ordinal for entry in entries) != tuple(range(len(entries)))
        or any(entry.item.run_id != run.id for entry in entries)
    ):
        raise ValueError("archive collection plan entries are invalid")
    material = {
        "profile": run.plan_profile,
        "scan_root_id": str(run.scan_root_id),
        "source_scan_run_id": str(run.source_scan_run_id),
        "plan_limit": run.plan_limit,
        "findings": {
            "hash_evidence_missing": findings.hash_evidence_missing,
            "missing_volume": findings.missing_volume,
            "unsupported_volume": findings.unsupported_volume,
            "ambiguous_volume": findings.ambiguous_volume,
            "name_collision": findings.name_collision,
            "orphan_volume": findings.orphan_volume,
        },
        "items": [_plan_item_material(entry) for entry in entries],
    }
    encoded = json.dumps(
        material, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(_PLAN_HASH_DOMAIN + encoded).hexdigest()


class SQLiteArchiveCollectionStore:
    """Own one immutable plan and serialize its fenced item transitions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def create_planning_run(
        self,
        scan_root_id: EntityId,
        *,
        worker_count: int,
        plan_limit: int | None,
        started_at: datetime,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> ArchiveCollectionRun:
        run_id = EntityId.new()
        try:
            with self._engine.begin() as connection:
                source_scan_run_id = _latest_completed_scan(connection, scan_root_id)
                lease = self._leases.acquire_in_transaction(
                    connection,
                    scan_root_id,
                    ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN,
                    run_id,
                    lease_token=lease_token,
                    acquired_at=started_at,
                    lease_expires_at=lease_expires_at,
                )
                run = ArchiveCollectionRun(
                    id=run_id,
                    scan_root_id=scan_root_id,
                    source_scan_run_id=source_scan_run_id,
                    worker_count=worker_count,
                    plan_limit=plan_limit,
                    started_at=started_at,
                    status=ArchiveCollectionRunStatus.PLANNING,
                    fence_epoch=lease.fence_epoch,
                    heartbeat_at=started_at,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                )
                connection.execute(
                    insert(tables.archive_collection_runs).values(**_run_values(run))
                )
            return run
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection run creation failed") from None

    def append_plan_batch(
        self,
        run_id: EntityId,
        lease_token: str,
        entries: tuple[ArchiveCollectionPlanEntry, ...],
        *,
        now: datetime,
    ) -> int:
        if (
            not isinstance(entries, tuple)
            or not 1 <= len(entries) <= ARCHIVE_COLLECTION_PLAN_BATCH_SIZE
        ):
            raise ValueError("archive collection plan batch is invalid")
        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, now)
                if run.status is not ArchiveCollectionRunStatus.PLANNING:
                    raise ArchiveCollectionStoreError("archive collection plan is already sealed")
                count = int(
                    connection.execute(
                        select(func.count())
                        .select_from(tables.archive_collection_items)
                        .where(tables.archive_collection_items.c.run_id == str(run_id))
                    ).scalar_one()
                )
                for entry in entries:
                    if (
                        entry.item.run_id != run_id
                        or entry.item.status is not ArchiveCollectionItemStatus.PENDING
                    ):
                        raise ArchiveCollectionStoreError(
                            "archive collection plan entry is invalid"
                        )
                    ordinal = entry.item.plan_ordinal
                    if ordinal < count:
                        if self._entry(connection, entry.item.id) != entry:
                            raise ArchiveCollectionStoreError(
                                "archive collection plan retry drifted"
                            )
                        continue
                    if ordinal != count:
                        raise ArchiveCollectionStoreError(
                            "archive collection plan ordinal has a gap"
                        )
                    _validate_plan_sources(connection, run, entry)
                    connection.execute(
                        insert(tables.archive_collection_items).values(**_item_values(entry.item))
                    )
                    connection.execute(
                        insert(tables.archive_collection_item_sources),
                        [_source_values(source) for source in entry.sources],
                    )
                    count += 1
                self._leases.fence(connection, lease, now)
                return count
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection plan write failed") from None

    def seal_plan(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        planned_count: int,
        findings: ArchiveCollectionPlanFindingCounts,
        plan_content_hash: str,
        sealed_at: datetime,
    ) -> ArchiveCollectionRun:
        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, sealed_at)
                entries = self._entries_for_run(connection, run_id)
                if len(entries) != planned_count:
                    raise ArchiveCollectionStoreError(
                        "archive collection plan count is incomplete"
                    )
                expected_hash = archive_collection_plan_content_hash(run, entries, findings)
                if expected_hash != plan_content_hash:
                    raise ArchiveCollectionStoreError("archive collection plan hash drifted")
                if run.status is ArchiveCollectionRunStatus.RUNNING:
                    expected = replace(
                        run,
                        planned_count=planned_count,
                        plan_findings=findings,
                        plan_content_hash=plan_content_hash,
                    )
                    if expected != run:
                        raise ArchiveCollectionStoreError("archive collection seal retry drifted")
                    return run
                if run.status is not ArchiveCollectionRunStatus.PLANNING:
                    raise ArchiveCollectionStoreError("archive collection plan cannot be sealed")
                candidate = replace(
                    run,
                    status=ArchiveCollectionRunStatus.RUNNING,
                    planned_count=planned_count,
                    plan_findings=findings,
                    plan_content_hash=plan_content_hash,
                )
                result = connection.execute(
                    update(tables.archive_collection_runs)
                    .where(
                        tables.archive_collection_runs.c.id == str(run_id),
                        tables.archive_collection_runs.c.status
                        == ArchiveCollectionRunStatus.PLANNING.value,
                        tables.archive_collection_runs.c.lease_token == lease_token,
                        tables.archive_collection_runs.c.fence_epoch == lease.fence_epoch,
                    )
                    .values(**_run_values(candidate))
                )
                _one(result.rowcount)
                self._leases.fence(connection, lease, sealed_at)
                return candidate
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection plan seal failed") from None

    def heartbeat(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> ArchiveCollectionRun:
        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, heartbeat_at)
                renewed = self._leases.heartbeat_in_transaction(
                    connection,
                    lease,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=lease_expires_at,
                )
                candidate = replace(
                    run,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=lease_expires_at,
                    fence_epoch=renewed.fence_epoch,
                )
                result = connection.execute(
                    update(tables.archive_collection_runs)
                    .where(
                        tables.archive_collection_runs.c.id == str(run_id),
                        tables.archive_collection_runs.c.lease_token == lease_token,
                        tables.archive_collection_runs.c.fence_epoch == lease.fence_epoch,
                    )
                    .values(**_run_values(candidate))
                )
                _one(result.rowcount)
                return candidate
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection heartbeat failed") from None

    def acquire_resume(
        self,
        run_id: EntityId,
        *,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ArchiveCollectionRun:
        try:
            with self._engine.begin() as connection:
                run = self._get_run(connection, run_id)
                if run is None or run.status in {
                    ArchiveCollectionRunStatus.FAILED,
                    ArchiveCollectionRunStatus.COMPLETED,
                    ArchiveCollectionRunStatus.COMPLETED_WITH_FAILURES,
                }:
                    raise ArchiveCollectionStoreError("archive collection run cannot resume")
                current = self._leases.current_in_transaction(connection, run.scan_root_id)
                if current is None:
                    lease = self._leases.acquire_in_transaction(
                        connection,
                        run.scan_root_id,
                        ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN,
                        run.id,
                        lease_token=lease_token,
                        acquired_at=now,
                        lease_expires_at=lease_expires_at,
                    )
                else:
                    if (
                        current.owner_kind is not ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN
                        or current.owner_run_id != run.id
                    ):
                        raise ArchiveCollectionStoreError("another writer owns this ScanRoot")
                    lease = self._leases.takeover_expired_in_transaction(
                        connection,
                        current,
                        run.id,
                        lease_token=lease_token,
                        acquired_at=now,
                        lease_expires_at=lease_expires_at,
                    )
                if run.plan_content_hash is not None:
                    connection.execute(
                        update(tables.archive_collection_items)
                        .where(
                            tables.archive_collection_items.c.run_id == str(run.id),
                            tables.archive_collection_items.c.status
                            == ArchiveCollectionItemStatus.RUNNING.value,
                        )
                        .values(status=ArchiveCollectionItemStatus.PENDING.value, started_at=None)
                    )
                    status = ArchiveCollectionRunStatus.RUNNING
                else:
                    status = ArchiveCollectionRunStatus.PLANNING
                candidate = replace(
                    run,
                    status=status,
                    fence_epoch=lease.fence_epoch,
                    heartbeat_at=now,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                )
                result = connection.execute(
                    update(tables.archive_collection_runs)
                    .where(tables.archive_collection_runs.c.id == str(run.id))
                    .values(**_run_values(candidate))
                )
                _one(result.rowcount)
                return candidate
        except (ArchiveCollectionStoreError, ValueError, ScanRootWriteLeaseError):
            raise ArchiveCollectionStoreError("archive collection resume failed") from None
        except Exception:
            raise ArchiveCollectionStoreError("archive collection resume failed") from None

    def claim_pending(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        limit: int,
        started_at: datetime,
    ) -> tuple[ArchiveCollectionWorkItem, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
            raise ValueError("archive collection claim limit is invalid")
        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, started_at)
                if run.status is not ArchiveCollectionRunStatus.RUNNING:
                    raise ArchiveCollectionStoreError("archive collection run is not executable")
                if limit > 2 * run.worker_count:
                    raise ArchiveCollectionStoreError(
                        "archive collection claim exceeds the worker bound"
                    )
                ids = (
                    connection.execute(
                        select(tables.archive_collection_items.c.id)
                        .where(
                            tables.archive_collection_items.c.run_id == str(run_id),
                            tables.archive_collection_items.c.status
                            == ArchiveCollectionItemStatus.PENDING.value,
                        )
                        .order_by(tables.archive_collection_items.c.plan_ordinal)
                        .limit(limit)
                    )
                    .scalars()
                    .all()
                )
                claimed: list[ArchiveCollectionWorkItem] = []
                for value in ids:
                    result = connection.execute(
                        update(tables.archive_collection_items)
                        .where(
                            tables.archive_collection_items.c.id == value,
                            tables.archive_collection_items.c.status
                            == ArchiveCollectionItemStatus.PENDING.value,
                            tables.archive_collection_items.c.attempt_count < 65_535,
                        )
                        .values(
                            status=ArchiveCollectionItemStatus.RUNNING.value,
                            attempt_count=tables.archive_collection_items.c.attempt_count + 1,
                            started_at=datetime_to_db(started_at),
                        )
                    )
                    _one(result.rowcount)
                    entry = self._entry(connection, EntityId.parse(str(value)))
                    if entry is None:
                        raise ArchiveCollectionStoreError(
                            "claimed archive collection item is unavailable"
                        )
                    claimed.append(ArchiveCollectionWorkItem(entry.item, entry.sources))
                self._leases.fence(connection, lease, started_at)
                return tuple(claimed)
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection claim failed") from None

    def complete_item(
        self,
        item: ArchiveCollectionItem,
        lease_token: str,
        *,
        status: ArchiveCollectionItemStatus,
        completed_at: datetime,
        archive_observation_id: EntityId | None,
        disposition: ArchiveCollectionDisposition | None,
        error_code: str | None,
    ) -> ArchiveCollectionItem:
        candidate = replace(
            item,
            status=status,
            completed_at=completed_at,
            archive_observation_id=archive_observation_id,
            disposition=disposition,
            error_code=error_code,
        )
        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, item.run_id, lease_token, completed_at)
                if (
                    run.status is not ArchiveCollectionRunStatus.RUNNING
                    or item.status is not ArchiveCollectionItemStatus.RUNNING
                ):
                    raise ArchiveCollectionStoreError("archive collection item is not running")
                current = self._entry(connection, item.id)
                if current is None or current.item != item:
                    raise ArchiveCollectionStoreError(
                        "archive collection item changed before completion"
                    )
                if archive_observation_id is not None:
                    if candidate.disposition is None:
                        raise ArchiveCollectionStoreError(
                            "archive collection disposition is unavailable"
                        )
                    _validate_archive_graph(
                        connection,
                        run,
                        current,
                        archive_observation_id,
                        candidate.disposition,
                    )
                result = connection.execute(
                    update(tables.archive_collection_items)
                    .where(
                        tables.archive_collection_items.c.id == str(item.id),
                        tables.archive_collection_items.c.status
                        == ArchiveCollectionItemStatus.RUNNING.value,
                        tables.archive_collection_items.c.attempt_count == item.attempt_count,
                    )
                    .values(**_item_values(candidate))
                )
                _one(result.rowcount)
                self._leases.fence(connection, lease, completed_at)
                return candidate
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection item completion failed") from None

    def finish_invocation(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        finished_at: datetime,
    ) -> ArchiveCollectionRun:
        """Release ownership and project the resumable or terminal run status."""

        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, finished_at)
                if run.status is ArchiveCollectionRunStatus.PLANNING:
                    status = ArchiveCollectionRunStatus.PLANNING
                    completed_at = None
                elif run.status is ArchiveCollectionRunStatus.RUNNING:
                    counts = {
                        ArchiveCollectionItemStatus(str(status)): int(count)
                        for status, count in connection.execute(
                            select(
                                tables.archive_collection_items.c.status,
                                func.count(),
                            )
                            .where(tables.archive_collection_items.c.run_id == str(run_id))
                            .group_by(tables.archive_collection_items.c.status)
                        ).all()
                    }
                    if counts.get(ArchiveCollectionItemStatus.PENDING, 0) or counts.get(
                        ArchiveCollectionItemStatus.RUNNING, 0
                    ):
                        status = ArchiveCollectionRunStatus.INTERRUPTED
                        completed_at = None
                    elif counts.get(ArchiveCollectionItemStatus.FAILED, 0) or counts.get(
                        ArchiveCollectionItemStatus.ERROR, 0
                    ):
                        status = ArchiveCollectionRunStatus.COMPLETED_WITH_FAILURES
                        completed_at = finished_at
                    else:
                        status = ArchiveCollectionRunStatus.COMPLETED
                        completed_at = finished_at
                else:
                    raise ArchiveCollectionStoreError(
                        "archive collection invocation cannot finish"
                    )
                candidate = replace(
                    run,
                    status=status,
                    completed_at=completed_at,
                    heartbeat_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
                result = connection.execute(
                    update(tables.archive_collection_runs)
                    .where(
                        tables.archive_collection_runs.c.id == str(run_id),
                        tables.archive_collection_runs.c.lease_token == lease_token,
                        tables.archive_collection_runs.c.fence_epoch == lease.fence_epoch,
                    )
                    .values(**_run_values(candidate))
                )
                _one(result.rowcount)
                self._leases.release_in_transaction(
                    connection, lease, released_at=finished_at
                )
                return candidate
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError(
                "archive collection invocation finish failed"
            ) from None

    def fail_planning(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        failed_at: datetime,
    ) -> ArchiveCollectionRun:
        """Terminate only an unsealed plan after a non-resumable conflict."""

        try:
            with self._engine.begin() as connection:
                run, lease = self._owned_run(connection, run_id, lease_token, failed_at)
                if run.status is not ArchiveCollectionRunStatus.PLANNING:
                    raise ArchiveCollectionStoreError(
                        "only an unsealed archive collection plan may fail"
                    )
                candidate = replace(
                    run,
                    status=ArchiveCollectionRunStatus.FAILED,
                    completed_at=failed_at,
                    heartbeat_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
                result = connection.execute(
                    update(tables.archive_collection_runs)
                    .where(
                        tables.archive_collection_runs.c.id == str(run_id),
                        tables.archive_collection_runs.c.lease_token == lease_token,
                        tables.archive_collection_runs.c.fence_epoch == lease.fence_epoch,
                    )
                    .values(**_run_values(candidate))
                )
                _one(result.rowcount)
                self._leases.release_in_transaction(
                    connection, lease, released_at=failed_at
                )
                return candidate
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError("archive collection plan failure failed") from None

    def get_run(self, run_id: EntityId) -> ArchiveCollectionRun | None:
        with self._engine.connect() as connection:
            return self._get_run(connection, run_id)

    def _read_report_snapshot(
        self, run_id: EntityId
    ) -> _ArchiveCollectionReportSnapshot | None:
        """Read one bounded aggregate projection in a single DB transaction."""

        if not isinstance(run_id, EntityId):
            raise ValueError("archive collection report run ID is invalid")
        try:
            with self._engine.connect() as connection, connection.begin():
                run = self._get_run(connection, run_id)
                if run is None:
                    return None
                items = tables.archive_collection_items
                parent = archive_schema.archive_observations
                item_statuses = _literal_counts(
                    connection,
                    select(items.c.status, func.count())
                    .where(items.c.run_id == str(run_id))
                    .group_by(items.c.status)
                    .order_by(items.c.status),
                    bound=5,
                )
                dispositions = _literal_counts(
                    connection,
                    select(items.c.disposition, func.count())
                    .where(
                        items.c.run_id == str(run_id),
                        items.c.disposition.is_not(None),
                    )
                    .group_by(items.c.disposition)
                    .order_by(items.c.disposition),
                    bound=2,
                )
                archive_base = items.join(
                    parent, parent.c.id == items.c.archive_observation_id
                )

                def archive_counts(column: Any) -> tuple[_ArchiveCollectionLiteralCount, ...]:
                    return _literal_counts(
                        connection,
                        select(column, func.count())
                        .select_from(archive_base)
                        .where(items.c.run_id == str(run_id))
                        .group_by(column)
                        .order_by(column),
                        bound=16,
                    )

                listing_statuses = archive_counts(parent.c.listing_status)
                integrity_statuses = archive_counts(parent.c.integrity_status)
                encryption_statuses = archive_counts(parent.c.encryption_status)
                recognition_statuses = archive_counts(parent.c.recognition_status)
                storage_families = archive_counts(parent.c.storage_family)
                error_codes = _literal_counts(
                    connection,
                    select(items.c.error_code, func.count())
                    .where(
                        items.c.run_id == str(run_id),
                        items.c.error_code.is_not(None),
                    )
                    .group_by(items.c.error_code)
                    .order_by(items.c.error_code),
                    bound=64,
                )
                _validate_report_aggregates(
                    connection,
                    run,
                    item_statuses,
                    dispositions,
                    listing_statuses,
                    error_codes,
                )
                return _ArchiveCollectionReportSnapshot(
                    run,
                    item_statuses,
                    dispositions,
                    listing_statuses,
                    integrity_statuses,
                    encryption_statuses,
                    recognition_statuses,
                    storage_families,
                    error_codes,
                )
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError(
                "archive collection report read failed"
            ) from None

    def owned_write_lease(self, run_id: EntityId, lease_token: str) -> OwnedScanRootWriteLease:
        with self._engine.connect() as connection:
            run = self._get_run(connection, run_id)
            if run is None:
                raise ArchiveCollectionStoreError("archive collection run does not exist")
            current = self._leases.current_in_transaction(connection, run.scan_root_id)
        if (
            current is None
            or current.owner_kind is not ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN
            or current.owner_run_id != run_id
            or current.lease_token != lease_token
            or current.fence_epoch != run.fence_epoch
        ):
            raise ArchiveCollectionStoreError("archive collection lease is not owned")
        return current

    def _resolve_work_item_sources(
        self, work_item: ArchiveCollectionWorkItem
    ) -> tuple[_ArchiveCollectionResolvedSource, ...]:
        """Return private locators only after revalidating the sealed DB lineage."""

        if not isinstance(work_item, ArchiveCollectionWorkItem):
            raise ValueError("archive collection work item is invalid")
        try:
            with self._engine.connect() as connection:
                run = self._get_run(connection, work_item.item.run_id)
                current = self._entry(connection, work_item.item.id)
                if (
                    run is None
                    or current is None
                    or current.item != work_item.item
                    or current.sources != work_item.sources
                ):
                    raise ArchiveCollectionStoreError(
                        "archive collection work item lineage is invalid"
                    )
                resolved: list[_ArchiveCollectionResolvedSource] = []
                for source in work_item.sources:
                    row = connection.execute(
                        select(
                            schema.file_observations.c.relative_path,
                            schema.file_observations.c.size_bytes,
                            schema.file_observations.c.scan_run_id,
                            schema.file_records.c.relative_path.label("record_path"),
                            schema.file_records.c.size_bytes.label("record_size"),
                            schema.file_records.c.scan_root_id,
                            schema.file_records.c.presence_state,
                            schema.scan_runs.c.scan_root_id.label("run_root"),
                            schema.scan_runs.c.status,
                        )
                        .select_from(
                            schema.file_observations.join(
                                schema.file_records,
                                schema.file_records.c.id
                                == schema.file_observations.c.file_id,
                            ).join(
                                schema.scan_runs,
                                schema.scan_runs.c.id
                                == schema.file_observations.c.scan_run_id,
                            )
                        )
                        .where(
                            schema.file_observations.c.id
                            == str(source.file_observation_id)
                        )
                    ).mappings().one_or_none()
                    fingerprint = connection.execute(
                        select(schema.fingerprints.c.id)
                        .where(
                            schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                            schema.fingerprints.c.target_id
                            == str(source.file_observation_id),
                            schema.fingerprints.c.kind == "FILE_SHA256",
                            schema.fingerprints.c.algorithm == "sha256",
                            schema.fingerprints.c.algorithm_version == "1",
                            schema.fingerprints.c.value == source.full_sha256,
                        )
                        .limit(1)
                    ).scalar_one_or_none()
                    if (
                        row is None
                        or fingerprint is None
                        or str(row["scan_run_id"]) != str(run.source_scan_run_id)
                        or str(row["scan_root_id"]) != str(run.scan_root_id)
                        or str(row["run_root"]) != str(run.scan_root_id)
                        or row["status"] != "COMPLETED"
                        or row["presence_state"] != "PRESENT"
                        or int(row["size_bytes"]) != source.size_bytes
                        or int(row["record_size"]) != source.size_bytes
                        or row["relative_path"] != row["record_path"]
                    ):
                        raise ArchiveCollectionStoreError(
                            "archive collection source lineage is invalid"
                        )
                    resolved.append(
                        _ArchiveCollectionResolvedSource(
                            source, str(row["relative_path"])
                        )
                    )
            return tuple(resolved)
        except (ArchiveCollectionStoreError, ValueError):
            raise
        except Exception:
            raise ArchiveCollectionStoreError(
                "archive collection source resolution failed"
            ) from None

    def _owned_run(
        self, connection: Connection, run_id: EntityId, lease_token: str, now: datetime
    ) -> tuple[ArchiveCollectionRun, OwnedScanRootWriteLease]:
        run = self._get_run(connection, run_id)
        if run is None or run.lease_token != lease_token:
            raise ArchiveCollectionStoreError("archive collection lease is not owned")
        current = self._leases.current_in_transaction(connection, run.scan_root_id)
        if (
            current is None
            or current.owner_kind is not ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN
            or current.owner_run_id != run.id
            or current.lease_token != lease_token
            or current.fence_epoch != run.fence_epoch
        ):
            raise ArchiveCollectionStoreError("archive collection lease is not owned")
        self._leases.fence(connection, current, now)
        return run, current

    @staticmethod
    def _get_run(connection: Connection, run_id: EntityId) -> ArchiveCollectionRun | None:
        row = (
            connection.execute(
                select(tables.archive_collection_runs).where(
                    tables.archive_collection_runs.c.id == str(run_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _run_from_row(row)

    def _entry(
        self, connection: Connection, item_id: EntityId
    ) -> ArchiveCollectionPlanEntry | None:
        row = (
            connection.execute(
                select(tables.archive_collection_items).where(
                    tables.archive_collection_items.c.id == str(item_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        sources = (
            connection.execute(
                select(tables.archive_collection_item_sources)
                .where(tables.archive_collection_item_sources.c.item_id == str(item_id))
                .order_by(tables.archive_collection_item_sources.c.source_ordinal)
            )
            .mappings()
            .all()
        )
        return ArchiveCollectionPlanEntry(
            _item_from_row(row), tuple(_source_from_row(value) for value in sources)
        )

    def _entries_for_run(
        self, connection: Connection, run_id: EntityId
    ) -> tuple[ArchiveCollectionPlanEntry, ...]:
        item_ids = connection.execute(
            select(tables.archive_collection_items.c.id)
            .where(tables.archive_collection_items.c.run_id == str(run_id))
            .order_by(tables.archive_collection_items.c.plan_ordinal)
        ).scalars()
        entries: list[ArchiveCollectionPlanEntry] = []
        for value in item_ids:
            entry = self._entry(connection, EntityId.parse(str(value)))
            if entry is None:
                raise ArchiveCollectionStoreError(
                    "archive collection plan material is unavailable"
                )
            entries.append(entry)
        return tuple(entries)


def _literal_counts(
    connection: Connection, statement: Any, *, bound: int
) -> tuple[_ArchiveCollectionLiteralCount, ...]:
    rows = connection.execute(statement.limit(bound + 1)).all()
    if len(rows) > bound:
        raise ArchiveCollectionStoreError(
            "archive collection report aggregate exceeds its bound"
        )
    return tuple(
        _ArchiveCollectionLiteralCount(str(literal), int(count))
        for literal, count in rows
    )


def _validate_report_aggregates(
    connection: Connection,
    run: ArchiveCollectionRun,
    item_statuses: tuple[_ArchiveCollectionLiteralCount, ...],
    dispositions: tuple[_ArchiveCollectionLiteralCount, ...],
    listing_statuses: tuple[_ArchiveCollectionLiteralCount, ...],
    error_codes: tuple[_ArchiveCollectionLiteralCount, ...],
) -> None:
    statuses = {value.literal: value.count for value in item_statuses}
    disposition_counts = {value.literal: value.count for value in dispositions}
    if set(statuses) - {value.value for value in ArchiveCollectionItemStatus} or set(
        disposition_counts
    ) - {value.value for value in ArchiveCollectionDisposition}:
        raise ArchiveCollectionStoreError(
            "archive collection report contains an unknown state"
        )
    if sum(statuses.values()) != run.planned_count:
        raise ArchiveCollectionStoreError(
            "archive collection report item count is inconsistent"
        )
    succeeded = statuses.get(ArchiveCollectionItemStatus.SUCCEEDED.value, 0)
    failed = statuses.get(ArchiveCollectionItemStatus.FAILED.value, 0)
    errored = statuses.get(ArchiveCollectionItemStatus.ERROR.value, 0)
    pending = statuses.get(ArchiveCollectionItemStatus.PENDING.value, 0)
    running = statuses.get(ArchiveCollectionItemStatus.RUNNING.value, 0)
    archived = succeeded + failed
    if (
        sum(value.count for value in listing_statuses) != archived
        or sum(disposition_counts.values()) != archived
        or sum(value.count for value in error_codes) != failed + errored
        or disposition_counts.get(ArchiveCollectionDisposition.REUSED.value, 0) > succeeded
    ):
        raise ArchiveCollectionStoreError(
            "archive collection report terminal counts are inconsistent"
        )
    if (
        run.status is ArchiveCollectionRunStatus.COMPLETED
        and (pending or running or failed or errored)
        or run.status is ArchiveCollectionRunStatus.COMPLETED_WITH_FAILURES
        and (pending or running or not (failed or errored))
        or run.status is ArchiveCollectionRunStatus.INTERRUPTED
        and not (pending or running)
    ):
        raise ArchiveCollectionStoreError(
            "archive collection report run status is inconsistent"
        )
    items = tables.archive_collection_items
    parent = archive_schema.archive_observations
    invalid_graphs = int(
        connection.execute(
            select(func.count())
            .select_from(items.outerjoin(parent, parent.c.id == items.c.archive_observation_id))
            .where(
                items.c.run_id == str(run.id),
                items.c.archive_observation_id.is_not(None),
                or_(
                    parent.c.id.is_(None),
                    parent.c.scan_root_id != str(run.scan_root_id),
                    parent.c.source_scan_run_id != str(run.source_scan_run_id),
                    parent.c.signature_profile != items.c.signature_profile,
                    parent.c.compatibility_profile != items.c.compatibility_profile,
                    parent.c.container_class != items.c.container_class,
                    parent.c.suffix_kind != items.c.suffix_kind,
                    parent.c.publication_kind != items.c.publication_kind,
                    parent.c.storage_family != items.c.storage_family,
                    parent.c.outer_compression_kind != items.c.outer_compression_kind,
                    parent.c.recognition_status != items.c.recognition_status,
                    parent.c.inspected_bytes != items.c.inspected_bytes,
                    parent.c.structural_confirmation_required
                    != items.c.structural_confirmation_required,
                    and_(
                        items.c.disposition
                        == ArchiveCollectionDisposition.EXECUTED.value,
                        or_(
                            parent.c.writer_owner_kind
                            != ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN.value,
                            parent.c.writer_owner_run_id != str(run.id),
                            parent.c.writer_fence_epoch != run.fence_epoch,
                        ),
                    ),
                    and_(
                        items.c.disposition
                        == ArchiveCollectionDisposition.REUSED.value,
                        parent.c.writer_owner_kind.not_in(
                            (
                                ScanRootWriteOwnerKind.EBOOK_ANALYSIS.value,
                                ScanRootWriteOwnerKind.EBOOK_COLLECTION_RUN.value,
                                ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN.value,
                            )
                        ),
                    ),
                ),
            )
        ).scalar_one()
    )
    if invalid_graphs:
        raise ArchiveCollectionStoreError(
            "archive collection report graph lineage is inconsistent"
        )
    collection_sources = tables.archive_collection_item_sources
    archive_sources = archive_schema.archive_observation_sources
    terminal_sources = collection_sources.join(
        items, items.c.id == collection_sources.c.item_id
    )
    expected_sources = int(
        connection.execute(
            select(func.count())
            .select_from(terminal_sources)
            .where(
                items.c.run_id == str(run.id),
                items.c.archive_observation_id.is_not(None),
            )
        ).scalar_one()
    )
    actual_sources = int(
        connection.execute(
            select(func.count())
            .select_from(
                items.join(
                    archive_sources,
                    archive_sources.c.archive_observation_id
                    == items.c.archive_observation_id,
                )
            )
            .where(items.c.run_id == str(run.id))
        ).scalar_one()
    )
    matched_sources = int(
        connection.execute(
            select(func.count())
            .select_from(
                terminal_sources.join(
                    archive_sources,
                    and_(
                        archive_sources.c.archive_observation_id
                        == items.c.archive_observation_id,
                        archive_sources.c.source_ordinal
                        == collection_sources.c.source_ordinal,
                        archive_sources.c.file_observation_id
                        == collection_sources.c.file_observation_id,
                        archive_sources.c.source_full_sha256
                        == collection_sources.c.full_sha256,
                        archive_sources.c.source_size_bytes
                        == collection_sources.c.size_bytes,
                        archive_sources.c.staging_name
                        == collection_sources.c.staging_name,
                    ),
                )
            )
            .where(
                items.c.run_id == str(run.id),
                items.c.archive_observation_id.is_not(None),
            )
        ).scalar_one()
    )
    if expected_sources != actual_sources or matched_sources != expected_sources:
        raise ArchiveCollectionStoreError(
            "archive collection report source lineage is inconsistent"
        )


def _latest_completed_scan(connection: Connection, scan_root_id: EntityId) -> EntityId:
    row = connection.execute(
        select(schema.scan_runs.c.id)
        .join(schema.scan_roots, schema.scan_roots.c.id == schema.scan_runs.c.scan_root_id)
        .where(
            schema.scan_runs.c.scan_root_id == str(scan_root_id),
            schema.scan_runs.c.status == "COMPLETED",
            schema.scan_roots.c.enabled.is_(True),
            schema.scan_roots.c.media_type == "EBOOK",
        )
        .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise ArchiveCollectionStoreError("archive collection requires a completed scan")
    return EntityId.parse(str(row))


def _validate_plan_sources(
    connection: Connection,
    run: ArchiveCollectionRun,
    entry: ArchiveCollectionPlanEntry,
) -> None:
    for source in entry.sources:
        row = (
            connection.execute(
                select(
                    schema.file_observations.c.scan_run_id,
                    schema.file_observations.c.size_bytes,
                    schema.file_records.c.scan_root_id,
                    schema.file_records.c.presence_state,
                    schema.file_records.c.size_bytes.label("record_size"),
                    schema.scan_runs.c.status,
                    schema.scan_runs.c.scan_root_id.label("run_root"),
                )
                .join(
                    schema.file_records,
                    schema.file_records.c.id == schema.file_observations.c.file_id,
                )
                .join(
                    schema.scan_runs,
                    schema.scan_runs.c.id == schema.file_observations.c.scan_run_id,
                )
                .where(
                    schema.file_observations.c.id == str(source.file_observation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        fingerprint = connection.execute(
            select(schema.fingerprints.c.id)
            .where(
                schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                schema.fingerprints.c.target_id == str(source.file_observation_id),
                schema.fingerprints.c.kind == "FILE_SHA256",
                schema.fingerprints.c.algorithm == "sha256",
                schema.fingerprints.c.algorithm_version == "1",
                schema.fingerprints.c.value == source.full_sha256,
            )
            .limit(1)
        ).scalar_one_or_none()
        if (
            row is None
            or fingerprint is None
            or str(row["scan_run_id"]) != str(run.source_scan_run_id)
            or str(row["scan_root_id"]) != str(run.scan_root_id)
            or str(row["run_root"]) != str(run.scan_root_id)
            or row["status"] != "COMPLETED"
            or row["presence_state"] != "PRESENT"
            or int(row["size_bytes"]) != source.size_bytes
            or int(row["record_size"]) != source.size_bytes
        ):
            raise ArchiveCollectionStoreError(
                "archive collection plan source lineage is invalid"
            )


def _run_values(run: ArchiveCollectionRun) -> dict[str, object]:
    counts = run.plan_findings
    return {
        "id": str(run.id),
        "scan_root_id": str(run.scan_root_id),
        "source_scan_run_id": str(run.source_scan_run_id),
        "profile": run.profile,
        "plan_profile": run.plan_profile,
        "worker_count": run.worker_count,
        "plan_limit": run.plan_limit,
        "started_at": datetime_to_db(run.started_at),
        "status": run.status.value,
        "fence_epoch": run.fence_epoch,
        "planned_count": run.planned_count,
        "hash_evidence_missing_count": counts.hash_evidence_missing,
        "missing_volume_count": counts.missing_volume,
        "unsupported_volume_count": counts.unsupported_volume,
        "ambiguous_volume_count": counts.ambiguous_volume,
        "name_collision_count": counts.name_collision,
        "orphan_volume_count": counts.orphan_volume,
        "plan_content_hash": run.plan_content_hash,
        "completed_at": datetime_to_db(run.completed_at),
        "heartbeat_at": datetime_to_db(run.heartbeat_at),
        "lease_token": run.lease_token,
        "lease_expires_at": datetime_to_db(run.lease_expires_at),
    }


def _run_from_row(row: RowMapping) -> ArchiveCollectionRun:
    values = dict(row)
    return ArchiveCollectionRun(
        id=EntityId.parse(str(values["id"])),
        scan_root_id=EntityId.parse(str(values["scan_root_id"])),
        source_scan_run_id=EntityId.parse(str(values["source_scan_run_id"])),
        worker_count=int(values["worker_count"]),
        plan_limit=None if values["plan_limit"] is None else int(values["plan_limit"]),
        started_at=required_datetime_from_db(values["started_at"]),
        status=ArchiveCollectionRunStatus(str(values["status"])),
        fence_epoch=int(values["fence_epoch"]),
        planned_count=int(values["planned_count"]),
        plan_findings=ArchiveCollectionPlanFindingCounts(
            int(values["hash_evidence_missing_count"]),
            int(values["missing_volume_count"]),
            int(values["unsupported_volume_count"]),
            int(values["ambiguous_volume_count"]),
            int(values["name_collision_count"]),
            int(values["orphan_volume_count"]),
        ),
        plan_content_hash=values["plan_content_hash"],
        completed_at=None
        if values["completed_at"] is None
        else required_datetime_from_db(values["completed_at"]),
        heartbeat_at=None
        if values["heartbeat_at"] is None
        else required_datetime_from_db(values["heartbeat_at"]),
        lease_token=values["lease_token"],
        lease_expires_at=None
        if values["lease_expires_at"] is None
        else required_datetime_from_db(values["lease_expires_at"]),
        profile=str(values["profile"]),
        plan_profile=str(values["plan_profile"]),
    )


def _item_values(item: ArchiveCollectionItem) -> dict[str, object]:
    signature = item.signature
    return {
        "id": str(item.id),
        "run_id": str(item.run_id),
        "primary_file_observation_id": str(item.primary_file_observation_id),
        "plan_ordinal": item.plan_ordinal,
        "signature_profile": signature.profile,
        "compatibility_profile": signature.compatibility,
        "container_class": signature.container_class.value,
        "suffix_kind": signature.suffix_kind.value,
        "publication_kind": signature.publication_kind.value,
        "storage_family": signature.storage_family.value,
        "outer_compression_kind": signature.outer_compression_kind.value,
        "recognition_status": signature.recognition_status.value,
        "inspected_bytes": signature.inspected_bytes,
        "structural_confirmation_required": signature.structural_confirmation_required,
        "status": item.status.value,
        "attempt_count": item.attempt_count,
        "started_at": datetime_to_db(item.started_at),
        "completed_at": datetime_to_db(item.completed_at),
        "archive_observation_id": None
        if item.archive_observation_id is None
        else str(item.archive_observation_id),
        "disposition": None if item.disposition is None else item.disposition.value,
        "error_code": item.error_code,
    }


def _item_from_row(row: RowMapping) -> ArchiveCollectionItem:
    values = dict(row)
    signature = ArchiveSignatureObservationV2(
        profile=str(values["signature_profile"]),
        compatibility=str(values["compatibility_profile"]),
        container_class=ArchiveContainerClass(str(values["container_class"])),
        suffix_kind=ArchiveSuffixKind(str(values["suffix_kind"])),
        publication_kind=ArchivePublicationKind(str(values["publication_kind"])),
        storage_family=ArchiveStorageFamily(str(values["storage_family"])),
        outer_compression_kind=ArchiveOuterCompressionKind(str(values["outer_compression_kind"])),
        recognition_status=ArchiveRecognitionStatus(str(values["recognition_status"])),
        inspected_bytes=int(values["inspected_bytes"]),
        structural_confirmation_required=bool(values["structural_confirmation_required"]),
    )
    return ArchiveCollectionItem(
        id=EntityId.parse(str(values["id"])),
        run_id=EntityId.parse(str(values["run_id"])),
        primary_file_observation_id=EntityId.parse(str(values["primary_file_observation_id"])),
        plan_ordinal=int(values["plan_ordinal"]),
        signature=signature,
        status=ArchiveCollectionItemStatus(str(values["status"])),
        attempt_count=int(values["attempt_count"]),
        started_at=None
        if values["started_at"] is None
        else required_datetime_from_db(values["started_at"]),
        completed_at=None
        if values["completed_at"] is None
        else required_datetime_from_db(values["completed_at"]),
        archive_observation_id=None
        if values["archive_observation_id"] is None
        else EntityId.parse(str(values["archive_observation_id"])),
        disposition=None
        if values["disposition"] is None
        else ArchiveCollectionDisposition(str(values["disposition"])),
        error_code=values["error_code"],
    )


def _source_values(source: ArchiveCollectionItemSource) -> dict[str, object]:
    return {
        "run_id": str(source.run_id),
        "item_id": str(source.item_id),
        "source_ordinal": source.source_ordinal,
        "file_observation_id": str(source.file_observation_id),
        "full_sha256": source.full_sha256,
        "size_bytes": source.size_bytes,
        "staging_name": source.staging_name,
    }


def _source_from_row(row: RowMapping) -> ArchiveCollectionItemSource:
    values = dict(row)
    return ArchiveCollectionItemSource(
        run_id=EntityId.parse(str(values["run_id"])),
        item_id=EntityId.parse(str(values["item_id"])),
        source_ordinal=int(values["source_ordinal"]),
        file_observation_id=EntityId.parse(str(values["file_observation_id"])),
        full_sha256=str(values["full_sha256"]),
        size_bytes=int(values["size_bytes"]),
        staging_name=str(values["staging_name"]),
    )


def _plan_item_material(entry: ArchiveCollectionPlanEntry) -> dict[str, object]:
    signature = entry.item.signature
    return {
        "plan_ordinal": entry.item.plan_ordinal,
        "primary_file_observation_id": str(entry.item.primary_file_observation_id),
        "signature": {
            "profile": signature.profile,
            "compatibility": signature.compatibility,
            "container_class": signature.container_class.value,
            "suffix_kind": signature.suffix_kind.value,
            "publication_kind": signature.publication_kind.value,
            "storage_family": signature.storage_family.value,
            "outer_compression_kind": signature.outer_compression_kind.value,
            "recognition_status": signature.recognition_status.value,
            "inspected_bytes": signature.inspected_bytes,
            "structural_confirmation_required": signature.structural_confirmation_required,
        },
        "sources": [
            {
                "source_ordinal": source.source_ordinal,
                "file_observation_id": str(source.file_observation_id),
                "full_sha256": source.full_sha256,
                "size_bytes": source.size_bytes,
                "staging_name": source.staging_name,
            }
            for source in entry.sources
        ],
    }


def _validate_archive_graph(
    connection: Connection,
    run: ArchiveCollectionRun,
    entry: ArchiveCollectionPlanEntry,
    observation_id: EntityId,
    disposition: ArchiveCollectionDisposition,
) -> None:
    parent = (
        connection.execute(
            select(archive_schema.archive_observations).where(
                archive_schema.archive_observations.c.id == str(observation_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    sources = (
        connection.execute(
            select(archive_schema.archive_observation_sources)
            .where(
                archive_schema.archive_observation_sources.c.archive_observation_id
                == str(observation_id)
            )
            .order_by(archive_schema.archive_observation_sources.c.source_ordinal)
        )
        .mappings()
        .all()
    )
    expected = tuple(
        (
            str(source.file_observation_id),
            source.full_sha256,
            source.size_bytes,
            source.staging_name,
        )
        for source in entry.sources
    )
    actual = tuple(
        (
            str(row["file_observation_id"]),
            str(row["source_full_sha256"]),
            int(row["source_size_bytes"]),
            str(row["staging_name"]),
        )
        for row in sources
    )
    signature = entry.item.signature
    executed_writer = (
        parent is not None
        and str(parent["writer_owner_kind"])
        == ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN.value
        and str(parent["writer_owner_run_id"]) == str(run.id)
        and int(parent["writer_fence_epoch"]) == run.fence_epoch
    )
    reused_writer = parent is not None and str(parent["writer_owner_kind"]) in {
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS.value,
        ScanRootWriteOwnerKind.EBOOK_COLLECTION_RUN.value,
        ScanRootWriteOwnerKind.ARCHIVE_COLLECTION_RUN.value,
    }
    if (
        parent is None
        or str(parent["scan_root_id"]) != str(run.scan_root_id)
        or str(parent["source_scan_run_id"]) != str(run.source_scan_run_id)
        or disposition is ArchiveCollectionDisposition.EXECUTED
        and not executed_writer
        or disposition is ArchiveCollectionDisposition.REUSED
        and not reused_writer
        or str(parent["signature_profile"]) != signature.profile
        or str(parent["compatibility_profile"]) != signature.compatibility
        or str(parent["container_class"]) != signature.container_class.value
        or str(parent["suffix_kind"]) != signature.suffix_kind.value
        or str(parent["publication_kind"]) != signature.publication_kind.value
        or str(parent["storage_family"]) != signature.storage_family.value
        or str(parent["outer_compression_kind"])
        != signature.outer_compression_kind.value
        or str(parent["recognition_status"]) != signature.recognition_status.value
        or int(parent["inspected_bytes"]) != signature.inspected_bytes
        or bool(parent["structural_confirmation_required"])
        != signature.structural_confirmation_required
        or expected != actual
    ):
        raise ArchiveCollectionStoreError("archive collection evidence lineage is invalid")


def _one(rowcount: int | None) -> None:
    if rowcount != 1:
        raise ArchiveCollectionStoreError("archive collection transition lost ownership")
