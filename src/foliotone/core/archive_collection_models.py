"""Closed state for restartable read-only archive collection runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from foliotone.archive.signatures import ArchiveSignatureObservationV2
from foliotone.core._validation import require_aware_datetime
from foliotone.core.ids import EntityId

ARCHIVE_COLLECTION_PROFILE = "archive-collection-orchestration/v1"
ARCHIVE_COLLECTION_PLAN_PROFILE = "archive-collection-plan/v1"
MAX_ARCHIVE_COLLECTION_WORKERS = 2
MAX_ARCHIVE_COLLECTION_ATTEMPTS = 65_535
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_STAGING = re.compile(r"archive(?:\.[A-Za-z0-9]{1,24})?\Z")


class ArchiveCollectionRunStatus(StrEnum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"


class ArchiveCollectionItemStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"


class ArchiveCollectionDisposition(StrEnum):
    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class ArchiveCollectionPlanFindingCounts:
    hash_evidence_missing: int = 0
    missing_volume: int = 0
    unsupported_volume: int = 0
    ambiguous_volume: int = 0
    name_collision: int = 0
    orphan_volume: int = 0

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.values
        ):
            raise ValueError("archive plan finding counts must be non-negative integers")

    @property
    def values(self) -> tuple[int, ...]:
        return (
            self.hash_evidence_missing,
            self.missing_volume,
            self.unsupported_volume,
            self.ambiguous_volume,
            self.name_collision,
            self.orphan_volume,
        )

    @property
    def total(self) -> int:
        return sum(self.values)


@dataclass(frozen=True, slots=True)
class ArchiveCollectionRun:
    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    worker_count: int
    started_at: datetime
    status: ArchiveCollectionRunStatus
    fence_epoch: int
    plan_limit: int | None = None
    planned_count: int = 0
    plan_findings: ArchiveCollectionPlanFindingCounts = field(
        default_factory=ArchiveCollectionPlanFindingCounts
    )
    plan_content_hash: str | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_token: str | None = field(default=None, repr=False)
    lease_expires_at: datetime | None = None
    profile: str = ARCHIVE_COLLECTION_PROFILE
    plan_profile: str = ARCHIVE_COLLECTION_PLAN_PROFILE

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, EntityId)
            for value in (self.id, self.scan_root_id, self.source_scan_run_id)
        ):
            raise ValueError("archive collection run IDs are invalid")
        if self.profile != ARCHIVE_COLLECTION_PROFILE:
            raise ValueError("archive collection profile is unsupported")
        if self.plan_profile != ARCHIVE_COLLECTION_PLAN_PROFILE:
            raise ValueError("archive collection plan profile is unsupported")
        if not isinstance(self.status, ArchiveCollectionRunStatus):
            raise ValueError("archive collection run status is invalid")
        if (
            isinstance(self.worker_count, bool)
            or not isinstance(self.worker_count, int)
            or not 1 <= self.worker_count <= MAX_ARCHIVE_COLLECTION_WORKERS
        ):
            raise ValueError("archive collection worker count is invalid")
        if self.plan_limit is not None and (
            isinstance(self.plan_limit, bool)
            or not isinstance(self.plan_limit, int)
            or self.plan_limit < 1
        ):
            raise ValueError("archive collection plan limit is invalid")
        if (
            isinstance(self.planned_count, bool)
            or not isinstance(self.planned_count, int)
            or self.planned_count < 0
            or self.plan_limit is not None
            and self.planned_count > self.plan_limit
        ):
            raise ValueError("archive collection planned count is invalid")
        if not isinstance(self.plan_findings, ArchiveCollectionPlanFindingCounts):
            raise ValueError("archive collection plan findings are invalid")
        if (
            isinstance(self.fence_epoch, bool)
            or not isinstance(self.fence_epoch, int)
            or self.fence_epoch < 1
        ):
            raise ValueError("archive collection fence epoch is invalid")
        require_aware_datetime(self.started_at, "started_at")
        if self.plan_content_hash is not None and (
            not isinstance(self.plan_content_hash, str)
            or _SHA256.fullmatch(self.plan_content_hash) is None
        ):
            raise ValueError("archive collection plan hash is invalid")
        if self.status is ArchiveCollectionRunStatus.PLANNING:
            if self.plan_content_hash is not None:
                raise ValueError("planning run cannot expose a sealed plan hash")
        elif self.status is not ArchiveCollectionRunStatus.FAILED:
            if self.plan_content_hash is None:
                raise ValueError("non-planning run requires a sealed plan hash")
        terminal = self.status in {
            ArchiveCollectionRunStatus.FAILED,
            ArchiveCollectionRunStatus.COMPLETED,
            ArchiveCollectionRunStatus.COMPLETED_WITH_FAILURES,
        }
        if terminal != (self.completed_at is not None):
            raise ValueError("archive collection terminal timestamp is inconsistent")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("archive collection completion precedes its start")
        lease_values = (self.heartbeat_at, self.lease_token, self.lease_expires_at)
        if any(value is None for value in lease_values) and not all(
            value is None for value in lease_values
        ):
            raise ValueError("archive collection lease fields must be set together")
        if self.lease_token is not None:
            if not isinstance(self.lease_token, str) or not self.lease_token:
                raise ValueError("archive collection lease token is invalid")
            if self.status not in {
                ArchiveCollectionRunStatus.PLANNING,
                ArchiveCollectionRunStatus.RUNNING,
            }:
                raise ValueError("only active archive collection runs may hold a lease")
            assert self.heartbeat_at is not None and self.lease_expires_at is not None
            require_aware_datetime(self.heartbeat_at, "heartbeat_at")
            require_aware_datetime(self.lease_expires_at, "lease_expires_at")
            if not self.started_at <= self.heartbeat_at < self.lease_expires_at:
                raise ValueError("archive collection lease timestamps are invalid")
        elif self.status is ArchiveCollectionRunStatus.RUNNING:
            raise ValueError("running archive collection requires a lease")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionItem:
    id: EntityId
    run_id: EntityId
    primary_file_observation_id: EntityId
    plan_ordinal: int
    signature: ArchiveSignatureObservationV2 = field(repr=False)
    status: ArchiveCollectionItemStatus = ArchiveCollectionItemStatus.PENDING
    attempt_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    archive_observation_id: EntityId | None = None
    disposition: ArchiveCollectionDisposition | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, EntityId)
            for value in (self.id, self.run_id, self.primary_file_observation_id)
        ):
            raise ValueError("archive collection item IDs are invalid")
        if not isinstance(self.signature, ArchiveSignatureObservationV2):
            raise ValueError("archive collection item signature is invalid")
        if not isinstance(self.status, ArchiveCollectionItemStatus):
            raise ValueError("archive collection item status is invalid")
        if (
            isinstance(self.plan_ordinal, bool)
            or not isinstance(self.plan_ordinal, int)
            or self.plan_ordinal < 0
        ):
            raise ValueError("archive collection plan ordinal is invalid")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or not 0 <= self.attempt_count <= MAX_ARCHIVE_COLLECTION_ATTEMPTS
        ):
            raise ValueError("archive collection attempt count is invalid")
        if self.archive_observation_id is not None and not isinstance(
            self.archive_observation_id, EntityId
        ):
            raise ValueError("archive collection observation ID is invalid")
        if self.disposition is not None and not isinstance(
            self.disposition, ArchiveCollectionDisposition
        ):
            raise ValueError("archive collection disposition is invalid")
        if self.started_at is not None:
            require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.started_at is None or self.completed_at < self.started_at:
                raise ValueError("archive collection item timestamps are invalid")
        terminal = self.status in {
            ArchiveCollectionItemStatus.SUCCEEDED,
            ArchiveCollectionItemStatus.FAILED,
            ArchiveCollectionItemStatus.ERROR,
        }
        if terminal != (self.completed_at is not None):
            raise ValueError("archive collection item completion is inconsistent")
        if self.status is ArchiveCollectionItemStatus.PENDING:
            if self.started_at is not None:
                raise ValueError("pending archive collection item cannot be started")
        elif self.attempt_count < 1 or self.started_at is None:
            raise ValueError("started archive collection item requires an attempt")
        if self.status is ArchiveCollectionItemStatus.SUCCEEDED:
            if (
                self.archive_observation_id is None
                or self.disposition is None
                or self.error_code is not None
            ):
                raise ValueError("successful archive collection item is inconsistent")
        elif self.status is ArchiveCollectionItemStatus.FAILED:
            if (
                self.archive_observation_id is None
                or self.disposition is not ArchiveCollectionDisposition.EXECUTED
                or not _valid_error_code(self.error_code)
            ):
                raise ValueError("failed archive collection item is inconsistent")
        elif self.status is ArchiveCollectionItemStatus.ERROR:
            if (
                self.archive_observation_id is not None
                or self.disposition is not None
                or not _valid_error_code(self.error_code)
            ):
                raise ValueError("errored archive collection item is inconsistent")
        elif any(
            value is not None
            for value in (self.archive_observation_id, self.disposition, self.error_code)
        ):
            raise ValueError("unfinished archive collection item has terminal material")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionItemSource:
    run_id: EntityId
    item_id: EntityId
    source_ordinal: int
    file_observation_id: EntityId
    full_sha256: str
    size_bytes: int
    staging_name: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, EntityId)
            for value in (self.run_id, self.item_id, self.file_observation_id)
        ):
            raise ValueError("archive collection source IDs are invalid")
        if (
            isinstance(self.source_ordinal, bool)
            or not isinstance(self.source_ordinal, int)
            or not 0 <= self.source_ordinal <= 255
        ):
            raise ValueError("archive collection source ordinal is invalid")
        if not isinstance(self.full_sha256, str) or _SHA256.fullmatch(self.full_sha256) is None:
            raise ValueError("archive collection source hash is invalid")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("archive collection source size is invalid")
        if not isinstance(self.staging_name, str) or _STAGING.fullmatch(self.staging_name) is None:
            raise ValueError("archive collection staging role is invalid")


def _valid_error_code(value: str | None) -> bool:
    return isinstance(value, str) and _ERROR_CODE.fullmatch(value) is not None
