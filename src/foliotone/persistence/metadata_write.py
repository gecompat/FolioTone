"""Fenced insert-only persistence for ADR-0063 metadata-write operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from foliotone.core import EntityId
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.metadata_write.authorization import (
    MAX_METADATA_WRITE_EVENTS,
    MetadataWriteAuthorizationSnapshot,
    MetadataWriteExecutionEvent,
    MetadataWriteExecutionRun,
    MetadataWriteRunStatus,
)
from foliotone.persistence._mapping import datetime_from_db, datetime_to_db
from foliotone.persistence.metadata_correction import (
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
)
from foliotone.persistence.metadata_write_schema import (
    metadata_write_authorizations,
    metadata_write_events,
    metadata_write_runs,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)


class MetadataWriteStoreError(RuntimeError):
    """A path-free authorization, lineage, fence, or journal invariant failed."""


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusEventSnapshot:
    """Only event material safe for a standard status projection."""

    sequence_no: int
    status: MetadataWriteRunStatus
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MetadataWriteStatusSnapshot:
    """Bounded path-, hash-, value-, capability-, and fence-free status material."""

    run_id: EntityId
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    writer_profile: str
    run_profile: str
    authorization_profile: str
    created_at: datetime
    authorized_at: datetime
    expires_at: datetime
    events: tuple[MetadataWriteStatusEventSnapshot, ...]


_FAIL_BEFORE_EXCHANGE = frozenset(
    {
        MetadataWriteRunStatus.STALE,
        MetadataWriteRunStatus.TOOL_UNAVAILABLE,
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
        MetadataWriteRunStatus.CANCELLED,
    }
)
_NEXT: dict[MetadataWriteRunStatus, frozenset[MetadataWriteRunStatus]] = {
    MetadataWriteRunStatus.CREATED: frozenset(
        {MetadataWriteRunStatus.PREPARED, *_FAIL_BEFORE_EXCHANGE}
    ),
    MetadataWriteRunStatus.PREPARED: frozenset(
        {MetadataWriteRunStatus.EXCHANGED, *_FAIL_BEFORE_EXCHANGE}
    ),
    MetadataWriteRunStatus.EXCHANGED: frozenset(
        {
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
        }
    ),
    MetadataWriteRunStatus.ORIGINAL_PRESERVED: frozenset(
        {
            MetadataWriteRunStatus.VERIFIED,
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            MetadataWriteRunStatus.FENCED_OUT,
        }
    ),
    MetadataWriteRunStatus.VALIDATION_FAILED: frozenset(
        {
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    MetadataWriteRunStatus.FENCED_OUT: frozenset(
        {
            MetadataWriteRunStatus.RECOVERED,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
        }
    ),
    MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED: frozenset(
        {MetadataWriteRunStatus.RECOVERED}
    ),
}
_RECOVERABLE_FAILURES = frozenset(
    {
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.FENCED_OUT,
    }
)
_RECOVERY_OUTCOMES = frozenset(
    {
        MetadataWriteRunStatus.RECOVERED,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
    }
)


class SQLiteMetadataWriteStore:
    """Persist one-use authorizations and gapless fence-bound execution journals."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_authorization(
        self,
        value: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
        *,
        persisted_at: datetime,
    ) -> MetadataWriteAuthorizationSnapshot:
        """Persist a new authorization only while its preparation fence is owned."""

        if not isinstance(value, MetadataWriteAuthorizationSnapshot):
            raise MetadataWriteStoreError("metadata write authorization is invalid")
        row = _authorization_row(value)
        try:
            with self._engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(metadata_write_authorizations).where(
                            metadata_write_authorizations.c.id == str(value.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != row:
                        raise MetadataWriteStoreError(
                            "metadata write authorization retry differs"
                        )
                    return _authorization_from_row(existing)
                self._require_preparation_lease(value, lease, persisted_at)
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    persisted_at,
                )
                self._require_plan(connection, value, plan)
                connection.execute(insert(metadata_write_authorizations).values(**row))
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, MetadataCorrectionStoreError, ScanRootWriteLeaseError) as error:
            raise MetadataWriteStoreError(
                "metadata write authorization could not be persisted"
            ) from error
        return value

    def create_run(
        self,
        value: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
        lease: OwnedScanRootWriteLease,
    ) -> MetadataWriteExecutionRun:
        """Consume one authorization once and append CREATED in the same fence."""

        self._require_run_material(value, authorization, lease)
        run_row = _run_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.created_at,
                )
                existing_by_authorization = (
                    connection.execute(
                        select(metadata_write_runs).where(
                            metadata_write_runs.c.authorization_id
                            == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_by_authorization is not None:
                    if dict(existing_by_authorization) != run_row:
                        raise MetadataWriteStoreError(
                            "metadata write authorization was already consumed"
                        )
                    self._require_created_event(connection, value)
                    return _run_from_row(existing_by_authorization)
                persisted_authorization = (
                    connection.execute(
                        select(metadata_write_authorizations).where(
                            metadata_write_authorizations.c.id == str(authorization.id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    persisted_authorization is None
                    or dict(persisted_authorization) != _authorization_row(authorization)
                    or not authorization.authorized_at
                    <= value.created_at
                    < authorization.expires_at
                ):
                    raise MetadataWriteStoreError(
                        "metadata write authorization is unavailable"
                    )
                self._require_plan(connection, authorization, plan)
                connection.execute(insert(metadata_write_runs).values(**run_row))
                connection.execute(
                    insert(metadata_write_events).values(
                        run_id=str(value.id),
                        sequence_no=1,
                        status=MetadataWriteRunStatus.CREATED.value,
                        occurred_at=datetime_to_db(value.created_at),
                        fence_epoch=lease.fence_epoch,
                        finding_code=None,
                        confirmation_digest=None,
                    )
                )
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, MetadataCorrectionStoreError, ScanRootWriteLeaseError) as error:
            raise MetadataWriteStoreError("metadata write run could not be created") from error
        return value

    def append_event(
        self,
        value: MetadataWriteExecutionEvent,
        lease: OwnedScanRootWriteLease,
    ) -> MetadataWriteExecutionEvent:
        """Append exactly one valid next phase under the run's current fence."""

        if not isinstance(value, MetadataWriteExecutionEvent):
            raise MetadataWriteStoreError("metadata write event is invalid")
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            or lease.owner_run_id != value.run_id
            or lease.fence_epoch != value.fence_epoch
            or value.occurred_at < lease.acquired_at
            or value.occurred_at >= lease.lease_expires_at
        ):
            raise MetadataWriteStoreError("metadata write event requires its run lease")
        event_row = _event_row(value)
        try:
            with self._engine.begin() as connection:
                SQLiteScanRootWriteLeaseStore(self._engine).fence(
                    connection,
                    lease,
                    value.occurred_at,
                )
                run = (
                    connection.execute(
                        select(metadata_write_runs).where(
                            metadata_write_runs.c.id == str(value.run_id)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if run is None or str(run["scan_root_id"]) != str(lease.scan_root_id):
                    raise MetadataWriteStoreError("metadata write run is unavailable")
                existing = (
                    connection.execute(
                        select(metadata_write_events).where(
                            metadata_write_events.c.run_id == str(value.run_id),
                            metadata_write_events.c.sequence_no == value.sequence_no,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if dict(existing) != event_row:
                        raise MetadataWriteStoreError("metadata write event retry differs")
                    return _event_from_row(existing)
                previous = (
                    connection.execute(
                        select(metadata_write_events)
                        .where(metadata_write_events.c.run_id == str(value.run_id))
                        .order_by(metadata_write_events.c.sequence_no.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous is None:
                    raise MetadataWriteStoreError("metadata write CREATED event is missing")
                previous_status = MetadataWriteRunStatus(str(previous["status"]))
                previous_at = _required_datetime(previous["occurred_at"])
                exchange_recorded = False
                if (
                    previous_status in _RECOVERABLE_FAILURES
                    and value.status in _RECOVERY_OUTCOMES
                ):
                    exchange_recorded = (
                        connection.execute(
                            select(metadata_write_events.c.run_id)
                            .where(
                                metadata_write_events.c.run_id == str(value.run_id),
                                metadata_write_events.c.status
                                == MetadataWriteRunStatus.EXCHANGED.value,
                            )
                            .limit(1)
                        ).first()
                        is not None
                    )
                if (
                    value.sequence_no != int(previous["sequence_no"]) + 1
                    or not _transition_allowed(
                        previous_status,
                        value.status,
                        exchange_recorded=exchange_recorded,
                    )
                    or value.occurred_at < previous_at
                ):
                    raise MetadataWriteStoreError(
                        "metadata write event transition is invalid"
                    )
                connection.execute(insert(metadata_write_events).values(**event_row))
        except MetadataWriteStoreError:
            raise
        except (IntegrityError, ScanRootWriteLeaseError, ValueError) as error:
            raise MetadataWriteStoreError("metadata write event could not be appended") from error
        return value

    def get_authorization(
        self,
        authorization_id: EntityId,
    ) -> MetadataWriteAuthorizationSnapshot | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_authorizations).where(
                        metadata_write_authorizations.c.id == str(authorization_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _authorization_from_row(row)

    def get_run(self, run_id: EntityId) -> MetadataWriteExecutionRun | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(metadata_write_runs).where(
                        metadata_write_runs.c.id == str(run_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _run_from_row(row)

    def events_for_run(
        self,
        run_id: EntityId,
    ) -> tuple[MetadataWriteExecutionEvent, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(metadata_write_events)
                .where(metadata_write_events.c.run_id == str(run_id))
                .order_by(metadata_write_events.c.sequence_no)
            ).mappings()
            return tuple(_event_from_row(row) for row in rows)

    def read_status_snapshot(
        self,
        run_id: EntityId,
    ) -> MetadataWriteStatusSnapshot | None:
        """Read only the fixed public subset; private material is not selected."""

        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    select(
                        metadata_write_runs.c.id,
                        metadata_write_runs.c.authorization_id,
                        metadata_write_runs.c.plan_id,
                        metadata_write_runs.c.scan_root_id,
                        metadata_write_runs.c.writer_profile,
                        metadata_write_runs.c.profile.label("run_profile"),
                        metadata_write_runs.c.created_at,
                        metadata_write_authorizations.c.profile.label(
                            "authorization_profile"
                        ),
                        metadata_write_authorizations.c.authorized_at,
                        metadata_write_authorizations.c.expires_at,
                    )
                    .join(
                        metadata_write_authorizations,
                        metadata_write_runs.c.authorization_id
                        == metadata_write_authorizations.c.id,
                    )
                    .where(metadata_write_runs.c.id == str(run_id))
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            events = tuple(
                MetadataWriteStatusEventSnapshot(
                    int(row["sequence_no"]),
                    MetadataWriteRunStatus(str(row["status"])),
                    _required_datetime(row["occurred_at"]),
                )
                for row in connection.execute(
                    select(
                        metadata_write_events.c.sequence_no,
                        metadata_write_events.c.status,
                        metadata_write_events.c.occurred_at,
                    )
                    .where(metadata_write_events.c.run_id == str(run_id))
                    .order_by(metadata_write_events.c.sequence_no)
                    .limit(MAX_METADATA_WRITE_EVENTS + 1)
                ).mappings()
            )
        created_at = _required_datetime(run["created_at"])
        if (
            not events
            or len(events) > MAX_METADATA_WRITE_EVENTS
            or tuple(event.sequence_no for event in events)
            != tuple(range(1, len(events) + 1))
            or events[0].status is not MetadataWriteRunStatus.CREATED
            or events[0].occurred_at != created_at
            or not _status_events_are_valid(events)
        ):
            raise MetadataWriteStoreError("metadata write status journal is invalid")
        return MetadataWriteStatusSnapshot(
            run_id=EntityId.parse(str(run["id"])),
            authorization_id=EntityId.parse(str(run["authorization_id"])),
            plan_id=EntityId.parse(str(run["plan_id"])),
            scan_root_id=EntityId.parse(str(run["scan_root_id"])),
            writer_profile=str(run["writer_profile"]),
            run_profile=str(run["run_profile"]),
            authorization_profile=str(run["authorization_profile"]),
            created_at=created_at,
            authorized_at=_required_datetime(run["authorized_at"]),
            expires_at=_required_datetime(run["expires_at"]),
            events=events,
        )

    def _require_preparation_lease(
        self,
        value: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
        persisted_at: datetime,
    ) -> None:
        if (
            not isinstance(persisted_at, datetime)
            or persisted_at.tzinfo is None
            or persisted_at.utcoffset() is None
        ):
            raise MetadataWriteStoreError(
                "metadata write authorization timestamp is invalid"
            )
        if (
            not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION
            or lease.owner_run_id != value.preparation_owner_id
            or lease.scan_root_id != value.scan_root_id
            or lease.fence_epoch != value.preparation_fence_epoch
            or lease.acquired_at > value.authorized_at
            or persisted_at < value.prepared_at
            or persisted_at >= value.expires_at
        ):
            raise MetadataWriteStoreError(
                "metadata write authorization requires its preparation lease"
            )

    def _require_plan(
        self,
        connection: Any,
        value: MetadataWriteAuthorizationSnapshot,
        plan: MetadataCorrectionPlan,
    ) -> None:
        candidate = plan.candidate
        if (
            value.plan_id != plan.id
            or value.plan_content_hash != plan.content_hash
            or value.scan_root_id != candidate.scan_root_id
            or value.file_id != candidate.file_id
            or value.observation_id != candidate.observation_id
            or value.source_sha256 != candidate.expected_full_sha256
            or value.source_size_bytes != candidate.expected_size_bytes
        ):
            raise MetadataWriteStoreError("metadata write plan binding differs")
        SQLiteMetadataCorrectionStore(
            self._engine
        ).require_current_approved_plan_in_transaction(connection, plan)

    @staticmethod
    def _require_run_material(
        value: MetadataWriteExecutionRun,
        authorization: MetadataWriteAuthorizationSnapshot,
        lease: OwnedScanRootWriteLease,
    ) -> None:
        if (
            not isinstance(value, MetadataWriteExecutionRun)
            or not isinstance(authorization, MetadataWriteAuthorizationSnapshot)
            or value.authorization_id != authorization.id
            or value.authorization_content_hash != authorization.content_hash
            or value.plan_id != authorization.plan_id
            or value.scan_root_id != authorization.scan_root_id
            or value.file_id != authorization.file_id
            or value.metadata_write_capability_id
            != authorization.metadata_write_capability_id
            or not isinstance(lease, OwnedScanRootWriteLease)
            or lease.owner_kind is not ScanRootWriteOwnerKind.METADATA_WRITE_RUN
            or lease.owner_run_id != value.id
            or lease.scan_root_id != value.scan_root_id
            or lease.fence_epoch != value.initial_fence_epoch
            or lease.acquired_at > value.created_at
            or lease.lease_expires_at <= value.created_at
        ):
            raise MetadataWriteStoreError("metadata write run binding differs")

    @staticmethod
    def _require_created_event(connection: Any, value: MetadataWriteExecutionRun) -> None:
        event = (
            connection.execute(
                select(metadata_write_events).where(
                    metadata_write_events.c.run_id == str(value.id),
                    metadata_write_events.c.sequence_no == 1,
                )
            )
            .mappings()
            .one_or_none()
        )
        expected = {
            "run_id": str(value.id),
            "sequence_no": 1,
            "status": MetadataWriteRunStatus.CREATED.value,
            "occurred_at": datetime_to_db(value.created_at),
            "fence_epoch": value.initial_fence_epoch,
            "finding_code": None,
            "confirmation_digest": None,
        }
        if event is None or dict(event) != expected:
            raise MetadataWriteStoreError("metadata write CREATED event differs")


def _authorization_row(value: MetadataWriteAuthorizationSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "preparation_id": str(value.preparation_id),
        "preparation_content_hash": value.preparation_content_hash,
        "preparation_owner_id": str(value.preparation_owner_id),
        "preparation_fence_epoch": value.preparation_fence_epoch,
        "plan_id": str(value.plan_id),
        "plan_content_hash": value.plan_content_hash,
        "scan_root_id": str(value.scan_root_id),
        "file_id": str(value.file_id),
        "observation_id": str(value.observation_id),
        "source_sha256": value.source_sha256,
        "source_size_bytes": value.source_size_bytes,
        "expected_output_sha256": value.expected_output_sha256,
        "expected_output_size_bytes": value.expected_output_size_bytes,
        "metadata_write_capability_id": str(value.metadata_write_capability_id),
        "dcterms_modified": value.dcterms_modified,
        "authorized_at": datetime_to_db(value.authorized_at),
        "prepared_at": datetime_to_db(value.prepared_at),
        "expires_at": datetime_to_db(value.expires_at),
        "metadata_tool_version": value.metadata_tool_version,
        "epubcheck_tool_version": value.epubcheck_tool_version,
        "text_tool_version": value.text_tool_version,
        "cover_tool_version": value.cover_tool_version,
        "validator_set_fingerprint": value.validator_set_fingerprint,
        "writer_profile": value.writer_profile,
        "patcher_version": value.patcher_version,
        "staging_profile": value.staging_profile,
        "validation_profile": value.validation_profile,
        "validator_set": value.validator_set,
        "content_hash": value.content_hash,
    }


def _authorization_from_row(row: RowMapping) -> MetadataWriteAuthorizationSnapshot:
    return MetadataWriteAuthorizationSnapshot(
        id=EntityId.parse(str(row["id"])),
        preparation_id=EntityId.parse(str(row["preparation_id"])),
        preparation_content_hash=str(row["preparation_content_hash"]),
        preparation_owner_id=EntityId.parse(str(row["preparation_owner_id"])),
        preparation_fence_epoch=int(row["preparation_fence_epoch"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        plan_content_hash=str(row["plan_content_hash"]),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        source_sha256=str(row["source_sha256"]),
        source_size_bytes=int(row["source_size_bytes"]),
        expected_output_sha256=str(row["expected_output_sha256"]),
        expected_output_size_bytes=int(row["expected_output_size_bytes"]),
        metadata_write_capability_id=EntityId.parse(
            str(row["metadata_write_capability_id"])
        ),
        dcterms_modified=str(row["dcterms_modified"]),
        authorized_at=_required_datetime(row["authorized_at"]),
        prepared_at=_required_datetime(row["prepared_at"]),
        expires_at=_required_datetime(row["expires_at"]),
        metadata_tool_version=str(row["metadata_tool_version"]),
        epubcheck_tool_version=str(row["epubcheck_tool_version"]),
        text_tool_version=str(row["text_tool_version"]),
        cover_tool_version=str(row["cover_tool_version"]),
        validator_set_fingerprint=str(row["validator_set_fingerprint"]),
        writer_profile=str(row["writer_profile"]),
        patcher_version=str(row["patcher_version"]),
        staging_profile=str(row["staging_profile"]),
        validation_profile=str(row["validation_profile"]),
        validator_set=str(row["validator_set"]),
        content_hash=str(row["content_hash"]),
        profile=str(row["profile"]),
    )


def _run_row(value: MetadataWriteExecutionRun) -> dict[str, object]:
    return {
        "id": str(value.id),
        "profile": value.profile,
        "authorization_id": str(value.authorization_id),
        "authorization_content_hash": value.authorization_content_hash,
        "plan_id": str(value.plan_id),
        "scan_root_id": str(value.scan_root_id),
        "file_id": str(value.file_id),
        "metadata_write_capability_id": str(value.metadata_write_capability_id),
        "initial_fence_epoch": value.initial_fence_epoch,
        "created_at": datetime_to_db(value.created_at),
        "writer_profile": value.writer_profile,
    }


def _run_from_row(row: RowMapping) -> MetadataWriteExecutionRun:
    return MetadataWriteExecutionRun(
        id=EntityId.parse(str(row["id"])),
        authorization_id=EntityId.parse(str(row["authorization_id"])),
        authorization_content_hash=str(row["authorization_content_hash"]),
        plan_id=EntityId.parse(str(row["plan_id"])),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        file_id=EntityId.parse(str(row["file_id"])),
        metadata_write_capability_id=EntityId.parse(
            str(row["metadata_write_capability_id"])
        ),
        initial_fence_epoch=int(row["initial_fence_epoch"]),
        created_at=_required_datetime(row["created_at"]),
        writer_profile=str(row["writer_profile"]),
        profile=str(row["profile"]),
    )


def _event_row(value: MetadataWriteExecutionEvent) -> dict[str, object]:
    return {
        "run_id": str(value.run_id),
        "sequence_no": value.sequence_no,
        "status": value.status.value,
        "occurred_at": datetime_to_db(value.occurred_at),
        "fence_epoch": value.fence_epoch,
        "finding_code": value.finding_code,
        "confirmation_digest": value.confirmation_digest,
    }


def _event_from_row(row: RowMapping) -> MetadataWriteExecutionEvent:
    return MetadataWriteExecutionEvent(
        run_id=EntityId.parse(str(row["run_id"])),
        sequence_no=int(row["sequence_no"]),
        status=MetadataWriteRunStatus(str(row["status"])),
        occurred_at=_required_datetime(row["occurred_at"]),
        fence_epoch=int(row["fence_epoch"]),
        finding_code=(None if row["finding_code"] is None else str(row["finding_code"])),
        confirmation_digest=(
            None
            if row["confirmation_digest"] is None
            else str(row["confirmation_digest"])
        ),
    )


def _transition_allowed(
    previous: MetadataWriteRunStatus,
    current: MetadataWriteRunStatus,
    *,
    exchange_recorded: bool,
) -> bool:
    if current not in _NEXT.get(previous, frozenset()):
        return False
    return not (
        previous in _RECOVERABLE_FAILURES
        and current in _RECOVERY_OUTCOMES
        and not exchange_recorded
    )


def _status_events_are_valid(
    events: tuple[MetadataWriteStatusEventSnapshot, ...],
) -> bool:
    exchange_recorded = events[0].status is MetadataWriteRunStatus.EXCHANGED
    for previous, current in zip(events, events[1:], strict=False):
        if (
            not _transition_allowed(
                previous.status,
                current.status,
                exchange_recorded=exchange_recorded,
            )
            or current.occurred_at < previous.occurred_at
        ):
            return False
        exchange_recorded = (
            exchange_recorded or current.status is MetadataWriteRunStatus.EXCHANGED
        )
    return True


def _required_datetime(value: object) -> datetime:
    decoded = datetime_from_db(str(value))
    if decoded is None or decoded.tzinfo is None or decoded.utcoffset() is None:
        raise MetadataWriteStoreError("metadata write timestamp is missing")
    return decoded.astimezone(UTC)


__all__ = [
    "MetadataWriteStatusEventSnapshot",
    "MetadataWriteStatusSnapshot",
    "MetadataWriteStoreError",
    "SQLiteMetadataWriteStore",
]
