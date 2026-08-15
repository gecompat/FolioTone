"""Bounded SQLite state transitions for resumable e-book collection runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, Select, func, insert, or_, select, update

from foliotone.core import (
    EBOOK_COLLECTION_FORMATS,
    EbookCollectionItem,
    EbookCollectionItemStatus,
    EbookCollectionRun,
    EbookCollectionRunStatus,
    EntityId,
    FileObservation,
    MediaType,
    PresenceState,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import schema, w3_schema
from foliotone.persistence.codecs import Codec, codec_for

EBOOK_COLLECTION_PLAN_BATCH_SIZE = 500
_COLLECTION_FINDING_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_COLLECTION_FINDING_DIMENSIONS = frozenset(
    {"METADATA", "TEXT", "COVER", "STRUCTURE", "FORMAT_RISK"}
)
_COLLECTION_FINDING_SEVERITIES = frozenset({"INFO", "WARNING", "ERROR"})
_COLLECTION_STEP_DISPOSITIONS = frozenset({"EXECUTED", "REUSED"})


class EbookCollectionStoreError(RuntimeError):
    """A collection run cannot make a safe persistent state transition."""


@dataclass(frozen=True, slots=True)
class CreatedEbookCollectionRun:
    run: EbookCollectionRun
    planned_count: int


@dataclass(frozen=True, slots=True)
class EbookCollectionWorkItem:
    item: EbookCollectionItem
    observation: FileObservation


@dataclass(frozen=True, slots=True)
class EbookCollectionExecutionSummary:
    """One exact ToolExecution used by a completed collection item."""

    step_name: str
    disposition: str
    execution_id: EntityId

    def __post_init__(self) -> None:
        step_name = self.step_name.strip()
        if not step_name or len(step_name) > 64:
            raise ValueError("collection step name must be bounded and non-empty")
        object.__setattr__(self, "step_name", step_name)
        if self.disposition not in _COLLECTION_STEP_DISPOSITIONS:
            raise ValueError("collection step disposition is unsupported")


@dataclass(frozen=True, slots=True)
class EbookCollectionFindingSummary:
    """Bounded deterministic quality finding persisted for reporting."""

    code: str
    dimension: str
    severity: str
    source_execution_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if _COLLECTION_FINDING_CODE.fullmatch(self.code) is None:
            raise ValueError("collection finding code is invalid")
        if self.dimension not in _COLLECTION_FINDING_DIMENSIONS:
            raise ValueError("collection finding dimension is unsupported")
        if self.severity not in _COLLECTION_FINDING_SEVERITIES:
            raise ValueError("collection finding severity is unsupported")
        if len(self.source_execution_ids) != len(set(self.source_execution_ids)):
            raise ValueError("collection finding execution references must be unique")


@dataclass(frozen=True, slots=True)
class EbookCollectionCounts:
    planned: int
    pending: int
    running: int
    succeeded: int
    partial_failure: int
    failed: int
    error: int
    reused_steps: int
    executed_steps: int
    findings: int

    def __post_init__(self) -> None:
        values = (
            self.planned,
            self.pending,
            self.running,
            self.succeeded,
            self.partial_failure,
            self.failed,
            self.error,
            self.reused_steps,
            self.executed_steps,
            self.findings,
        )
        if any(value < 0 for value in values):
            raise ValueError("collection counts must not be negative")
        if self.planned != self.pending + self.running + self.terminal:
            raise ValueError("planned collection count must equal all item states")

    @property
    def terminal(self) -> int:
        return self.succeeded + self.partial_failure + self.failed + self.error


class SQLiteEbookCollectionStore:
    """Persist one stable scan snapshot without collection-wide Python lists."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._run_codec = codec_for(EbookCollectionRun)
        self._item_codec = codec_for(EbookCollectionItem)
        self._observation_codec = codec_for(FileObservation)
        self._scan_codec = codec_for(ScanRun)

    def create_run(
        self,
        scan_root_id: EntityId,
        *,
        profile: str,
        analysis_profile: str,
        fresh: bool,
        worker_count: int,
        started_at: datetime,
        lease_token: str,
        lease_expires_at: datetime,
        plan_limit: int | None = None,
        plan_per_format: int | None = None,
    ) -> CreatedEbookCollectionRun:
        if plan_limit is not None and plan_per_format is not None:
            raise ValueError("plan_limit and plan_per_format are mutually exclusive")
        if plan_limit is not None and plan_limit <= 0:
            raise ValueError("plan_limit must be positive when provided")
        if plan_per_format is not None and plan_per_format <= 0:
            raise ValueError("plan_per_format must be positive when provided")
        with self._engine.begin() as connection:
            source_scan = self._latest_scan(connection, scan_root_id)
            if source_scan is None:
                raise EbookCollectionStoreError("ScanRoot has no persisted ScanRun")
            if source_scan.status is not ScanRunStatus.COMPLETED:
                raise EbookCollectionStoreError(
                    "latest ScanRun must be COMPLETED before collection analysis"
                )
            run = EbookCollectionRun(
                id=EntityId.new(),
                scan_root_id=scan_root_id,
                source_scan_run_id=source_scan.id,
                profile=profile,
                analysis_profile=analysis_profile,
                fresh=fresh,
                worker_count=worker_count,
                started_at=started_at,
                status=EbookCollectionRunStatus.RUNNING,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
            )
            connection.execute(insert(w3_schema.ebook_collection_runs).values(
                **self._run_codec.encode(run)
            ))
            planned_count = self._insert_plan(
                connection,
                run,
                plan_limit=plan_limit,
                plan_per_format=plan_per_format,
            )
        return CreatedEbookCollectionRun(run=run, planned_count=planned_count)

    def acquire_resume(
        self,
        run_id: EntityId,
        *,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> EbookCollectionRun:
        if lease_expires_at <= now:
            raise ValueError("resume lease must expire after now")
        with self._engine.begin() as connection:
            run = self._get_run(connection, run_id)
            if run is None:
                raise EbookCollectionStoreError("collection run does not exist")
            if run.status in {
                EbookCollectionRunStatus.COMPLETED,
                EbookCollectionRunStatus.COMPLETED_WITH_FAILURES,
            }:
                raise EbookCollectionStoreError("terminal collection run cannot resume")
            if (
                run.lease_token is not None
                and run.lease_expires_at is not None
                and run.lease_expires_at > now
            ):
                raise EbookCollectionStoreError("collection run already has an active lease")
            connection.execute(
                update(w3_schema.ebook_collection_items)
                .where(
                    w3_schema.ebook_collection_items.c.run_id == str(run.id),
                    w3_schema.ebook_collection_items.c.status
                    == EbookCollectionItemStatus.RUNNING.value,
                )
                .values(
                    status=EbookCollectionItemStatus.PENDING.value,
                    started_at=None,
                    completed_at=None,
                    quality_status=None,
                    reused_step_count=0,
                    executed_step_count=0,
                    finding_count=0,
                    error_code=None,
                )
            )
            resumed = replace(
                run,
                status=EbookCollectionRunStatus.RUNNING,
                completed_at=None,
                lease_token=lease_token,
                lease_expires_at=lease_expires_at,
            )
            self._update_record(connection, self._run_codec, resumed)
            return resumed

    def get_run(self, run_id: EntityId) -> EbookCollectionRun | None:
        with self._engine.connect() as connection:
            return self._get_run(connection, run_id)

    def latest_interrupted_run(
        self,
        scan_root_id: EntityId,
    ) -> EbookCollectionRun | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(w3_schema.ebook_collection_runs)
                .where(
                    w3_schema.ebook_collection_runs.c.scan_root_id == str(scan_root_id),
                    w3_schema.ebook_collection_runs.c.status
                    == EbookCollectionRunStatus.INTERRUPTED.value,
                )
                .order_by(
                    w3_schema.ebook_collection_runs.c.started_at.desc(),
                    w3_schema.ebook_collection_runs.c.id.desc(),
                )
                .limit(1)
            ).mappings().one_or_none()
        if row is None:
            return None
        return self._run_codec.decode(row)

    def heartbeat(
        self,
        run_id: EntityId,
        lease_token: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> None:
        if lease_expires_at <= now:
            raise ValueError("heartbeat lease must expire after now")
        with self._engine.begin() as connection:
            run = self._require_lease(connection, run_id, lease_token, now)
            self._update_record(
                connection,
                self._run_codec,
                replace(run, lease_expires_at=lease_expires_at),
            )

    def claim_pending(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        limit: int,
        started_at: datetime,
    ) -> tuple[EbookCollectionWorkItem, ...]:
        if limit <= 0:
            raise ValueError("claim limit must be positive")
        with self._engine.begin() as connection:
            self._require_lease(connection, run_id, lease_token, started_at)
            rows = connection.execute(
                select(w3_schema.ebook_collection_items)
                .where(
                    w3_schema.ebook_collection_items.c.run_id == str(run_id),
                    w3_schema.ebook_collection_items.c.status
                    == EbookCollectionItemStatus.PENDING.value,
                )
                .order_by(w3_schema.ebook_collection_items.c.ordinal)
                .limit(limit)
            ).mappings().all()
            claimed = tuple(
                replace(
                    self._item_codec.decode(row),
                    status=EbookCollectionItemStatus.RUNNING,
                    attempt_count=int(row["attempt_count"]) + 1,
                    started_at=started_at,
                )
                for row in rows
            )
            for item in claimed:
                self._update_record(connection, self._item_codec, item)
            observations = self._load_observations(
                connection,
                tuple(item.observation_id for item in claimed),
            )
            if len(observations) != len(claimed):
                raise EbookCollectionStoreError(
                    "planned FileObservation is no longer available"
                )
            return tuple(
                EbookCollectionWorkItem(
                    item=item,
                    observation=observations[item.observation_id],
                )
                for item in claimed
            )

    def complete_item(
        self,
        item: EbookCollectionItem,
        lease_token: str,
        *,
        status: EbookCollectionItemStatus,
        completed_at: datetime,
        quality_status: str | None,
        reused_step_count: int = 0,
        executed_step_count: int = 0,
        executions: tuple[EbookCollectionExecutionSummary, ...] = (),
        findings: tuple[EbookCollectionFindingSummary, ...] = (),
        error_code: str | None = None,
    ) -> EbookCollectionItem:
        if status in {EbookCollectionItemStatus.PENDING, EbookCollectionItemStatus.RUNNING}:
            raise ValueError("completed item requires a terminal status")
        execution_ids = tuple(summary.execution_id for summary in executions)
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("collection item execution references must be unique")
        finding_codes = tuple(summary.code for summary in findings)
        if len(finding_codes) != len(set(finding_codes)):
            raise ValueError("collection item finding codes must be unique")
        if quality_status is None and findings:
            raise ValueError("collection item without quality cannot persist findings")
        execution_id_set = set(execution_ids)
        if any(
            execution_id not in execution_id_set
            for finding in findings
            for execution_id in finding.source_execution_ids
        ):
            raise ValueError("collection finding references an unavailable execution")
        with self._engine.begin() as connection:
            self._require_lease(connection, item.run_id, lease_token, completed_at)
            current = self._get_item(connection, item.id)
            if current is None or current.status is not EbookCollectionItemStatus.RUNNING:
                raise EbookCollectionStoreError("collection item is not currently claimed")
            completed = replace(
                current,
                status=status,
                completed_at=completed_at,
                quality_status=quality_status,
                reused_step_count=reused_step_count,
                executed_step_count=executed_step_count,
                finding_count=len(findings),
                error_code=error_code,
            )
            self._update_record(connection, self._item_codec, completed)
            if executions:
                connection.execute(
                    insert(w3_schema.ebook_collection_item_executions),
                    [
                        {
                            "id": str(EntityId.new()),
                            "item_id": str(completed.id),
                            "ordinal": ordinal,
                            "step_name": summary.step_name,
                            "disposition": summary.disposition,
                            "execution_id": str(summary.execution_id),
                        }
                        for ordinal, summary in enumerate(executions)
                    ],
                )
            if findings:
                finding_rows: list[dict[str, object]] = []
                finding_execution_rows: list[dict[str, object]] = []
                for ordinal, summary in enumerate(findings):
                    finding_id = EntityId.new()
                    finding_rows.append(
                        {
                            "id": str(finding_id),
                            "item_id": str(completed.id),
                            "ordinal": ordinal,
                            "code": summary.code,
                            "dimension": summary.dimension,
                            "severity": summary.severity,
                        }
                    )
                    finding_execution_rows.extend(
                        {
                            "id": str(EntityId.new()),
                            "finding_id": str(finding_id),
                            "ordinal": execution_ordinal,
                            "execution_id": str(execution_id),
                        }
                        for execution_ordinal, execution_id in enumerate(
                            summary.source_execution_ids
                        )
                    )
                connection.execute(
                    insert(w3_schema.ebook_collection_findings),
                    finding_rows,
                )
                if finding_execution_rows:
                    connection.execute(
                        insert(w3_schema.ebook_collection_finding_executions),
                        finding_execution_rows,
                    )
            return completed

    def finish_invocation(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        finished_at: datetime,
    ) -> EbookCollectionRun:
        with self._engine.begin() as connection:
            run = self._require_lease(connection, run_id, lease_token, finished_at)
            counts = self._counts(connection, run_id)
            if counts.pending or counts.running:
                status = EbookCollectionRunStatus.INTERRUPTED
                completed_at = None
            elif counts.partial_failure or counts.failed or counts.error:
                status = EbookCollectionRunStatus.COMPLETED_WITH_FAILURES
                completed_at = finished_at
            else:
                status = EbookCollectionRunStatus.COMPLETED
                completed_at = finished_at
            finished = replace(
                run,
                status=status,
                completed_at=completed_at,
                lease_token=None,
                lease_expires_at=None,
            )
            self._update_record(connection, self._run_codec, finished)
            return finished

    def fail_invocation(
        self,
        run_id: EntityId,
        lease_token: str,
        *,
        failed_at: datetime,
    ) -> EbookCollectionRun:
        with self._engine.begin() as connection:
            run = self._require_lease(connection, run_id, lease_token, failed_at)
            failed = replace(
                run,
                status=EbookCollectionRunStatus.INTERRUPTED,
                lease_token=None,
                lease_expires_at=None,
            )
            self._update_record(connection, self._run_codec, failed)
            return failed

    def counts(self, run_id: EntityId) -> EbookCollectionCounts:
        with self._engine.connect() as connection:
            if self._get_run(connection, run_id) is None:
                raise EbookCollectionStoreError("collection run does not exist")
            return self._counts(connection, run_id)

    def _latest_scan(
        self,
        connection: Connection,
        scan_root_id: EntityId,
    ) -> ScanRun | None:
        row = connection.execute(
            select(schema.scan_runs)
            .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
            .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
            .limit(1)
        ).mappings().one_or_none()
        return None if row is None else self._scan_codec.decode(row)

    def _insert_plan(
        self,
        connection: Connection,
        run: EbookCollectionRun,
        *,
        plan_limit: int | None,
        plan_per_format: int | None,
    ) -> int:
        planned = 0
        base_statement = (
            select(schema.file_observations)
            .join(
                schema.file_records,
                schema.file_records.c.id == schema.file_observations.c.file_id,
            )
            .where(
                schema.file_observations.c.scan_run_id == str(run.source_scan_run_id),
                schema.file_records.c.scan_root_id == str(run.scan_root_id),
                schema.file_records.c.media_type == MediaType.EBOOK.value,
                schema.file_records.c.presence_state == PresenceState.PRESENT.value,
                schema.file_records.c.relative_path
                == schema.file_observations.c.relative_path,
                schema.file_records.c.size_bytes == schema.file_observations.c.size_bytes,
                schema.file_records.c.modified_at
                == schema.file_observations.c.modified_at,
            )
        )
        statements: tuple[Select[Any], ...]
        if plan_per_format is None:
            statement = (
                base_statement.where(
                    or_(
                        *(
                            func.lower(schema.file_records.c.relative_path).like(
                                f"%.{format_name.lower()}"
                            )
                            for format_name in sorted(EBOOK_COLLECTION_FORMATS)
                        )
                    )
                )
                .order_by(
                    schema.file_records.c.relative_path,
                    schema.file_records.c.id,
                )
            )
            if plan_limit is not None:
                statement = statement.limit(plan_limit)
            statements = (statement,)
        else:
            statements = tuple(
                base_statement.where(
                    func.lower(schema.file_records.c.relative_path).like(
                        f"%.{format_name.lower()}"
                    )
                )
                .order_by(
                    schema.file_records.c.relative_path,
                    schema.file_records.c.id,
                )
                .limit(plan_per_format)
                for format_name in sorted(EBOOK_COLLECTION_FORMATS)
            )

        for statement in statements:
            result = connection.execution_options(stream_results=True).execute(statement)
            mappings = result.mappings()
            while rows := mappings.fetchmany(EBOOK_COLLECTION_PLAN_BATCH_SIZE):
                items: list[Mapping[str, object]] = []
                for row in rows:
                    observation = self._observation_codec.decode(row)
                    format_name = observation.relative_path.rsplit(".", 1)[-1].upper()
                    item = EbookCollectionItem(
                        id=EntityId.new(),
                        run_id=run.id,
                        observation_id=observation.id,
                        ordinal=planned,
                        format_name=format_name,
                        status=EbookCollectionItemStatus.PENDING,
                    )
                    items.append(self._item_codec.encode(item))
                    planned += 1
                connection.execute(insert(w3_schema.ebook_collection_items), items)
        return planned

    def _require_lease(
        self,
        connection: Connection,
        run_id: EntityId,
        lease_token: str,
        now: datetime,
    ) -> EbookCollectionRun:
        run = self._get_run(connection, run_id)
        if (
            run is None
            or run.status is not EbookCollectionRunStatus.RUNNING
            or run.lease_token != lease_token
            or run.lease_expires_at is None
            or run.lease_expires_at <= now
        ):
            raise EbookCollectionStoreError("collection run lease is unavailable or expired")
        return run

    def _get_run(
        self,
        connection: Connection,
        run_id: EntityId,
    ) -> EbookCollectionRun | None:
        row = connection.execute(
            select(w3_schema.ebook_collection_runs).where(
                w3_schema.ebook_collection_runs.c.id == str(run_id)
            )
        ).mappings().one_or_none()
        return None if row is None else self._run_codec.decode(row)

    def _get_item(
        self,
        connection: Connection,
        item_id: EntityId,
    ) -> EbookCollectionItem | None:
        row = connection.execute(
            select(w3_schema.ebook_collection_items).where(
                w3_schema.ebook_collection_items.c.id == str(item_id)
            )
        ).mappings().one_or_none()
        return None if row is None else self._item_codec.decode(row)

    def _load_observations(
        self,
        connection: Connection,
        observation_ids: tuple[EntityId, ...],
    ) -> dict[EntityId, FileObservation]:
        if not observation_ids:
            return {}
        rows = connection.execute(
            select(schema.file_observations).where(
                schema.file_observations.c.id.in_(tuple(map(str, observation_ids)))
            )
        ).mappings().all()
        values = (self._observation_codec.decode(row) for row in rows)
        return {value.id: value for value in values}

    def _counts(
        self,
        connection: Connection,
        run_id: EntityId,
    ) -> EbookCollectionCounts:
        rows = connection.execute(
            select(
                w3_schema.ebook_collection_items.c.status,
                func.count().label("count"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.reused_step_count), 0
                ).label("reused_steps"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.executed_step_count), 0
                ).label("executed_steps"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.finding_count), 0
                ).label("findings"),
            )
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
            .group_by(w3_schema.ebook_collection_items.c.status)
        ).mappings().all()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return EbookCollectionCounts(
            planned=sum(counts.values()),
            pending=counts.get(EbookCollectionItemStatus.PENDING.value, 0),
            running=counts.get(EbookCollectionItemStatus.RUNNING.value, 0),
            succeeded=counts.get(EbookCollectionItemStatus.SUCCEEDED.value, 0),
            partial_failure=counts.get(
                EbookCollectionItemStatus.PARTIAL_FAILURE.value, 0
            ),
            failed=counts.get(EbookCollectionItemStatus.FAILED.value, 0),
            error=counts.get(EbookCollectionItemStatus.ERROR.value, 0),
            reused_steps=sum(int(row["reused_steps"]) for row in rows),
            executed_steps=sum(int(row["executed_steps"]) for row in rows),
            findings=sum(int(row["findings"]) for row in rows),
        )

    @staticmethod
    def _update_record[T](
        connection: Connection,
        codec: Codec[T],
        value: T,
    ) -> None:
        row = dict(codec.encode(value))
        entity_id = row.pop("id")
        connection.execute(
            update(codec.table).where(codec.table.c.id == entity_id).values(**row)
        )
