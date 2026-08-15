"""Persistent state for resumable read-only e-book collection analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.enums import EbookCollectionItemStatus, EbookCollectionRunStatus
from foliotone.core.ids import EntityId

EBOOK_COLLECTION_FORMATS = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PDF"})
MAX_EBOOK_COLLECTION_WORKERS = 8
_TERMINAL_RUN_STATUSES = frozenset(
    {
        EbookCollectionRunStatus.COMPLETED,
        EbookCollectionRunStatus.COMPLETED_WITH_FAILURES,
    }
)
_TERMINAL_ITEM_STATUSES = frozenset(
    {
        EbookCollectionItemStatus.SUCCEEDED,
        EbookCollectionItemStatus.PARTIAL_FAILURE,
        EbookCollectionItemStatus.FAILED,
        EbookCollectionItemStatus.ERROR,
    }
)


@dataclass(frozen=True, slots=True)
class EbookCollectionRun:
    """One stable collection snapshot and its resumable analysis lifecycle."""

    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    profile: str
    analysis_profile: str
    fresh: bool
    worker_count: int
    started_at: datetime
    status: EbookCollectionRunStatus
    completed_at: datetime | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", require_non_empty(self.profile, "profile"))
        object.__setattr__(
            self,
            "analysis_profile",
            require_non_empty(self.analysis_profile, "analysis_profile"),
        )
        if not 1 <= self.worker_count <= MAX_EBOOK_COLLECTION_WORKERS:
            raise ValueError("worker_count is outside the supported range")
        require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not be before started_at")
        if (self.status in _TERMINAL_RUN_STATUSES) != (self.completed_at is not None):
            raise ValueError("only terminal collection runs require completed_at")
        if (self.lease_token is None) != (self.lease_expires_at is None):
            raise ValueError("collection run lease fields must be set together")
        if self.status is EbookCollectionRunStatus.RUNNING and self.lease_token is None:
            raise ValueError("running collection run requires a lease")
        if self.lease_token is not None:
            object.__setattr__(
                self,
                "lease_token",
                require_non_empty(self.lease_token, "lease_token"),
            )
            assert self.lease_expires_at is not None
            require_aware_datetime(self.lease_expires_at, "lease_expires_at")
            if self.status is not EbookCollectionRunStatus.RUNNING:
                raise ValueError("only a running collection run may hold a lease")
            if self.lease_expires_at <= self.started_at:
                raise ValueError("collection run lease must expire after started_at")


@dataclass(frozen=True, slots=True)
class EbookCollectionItem:
    """One planned observation and its bounded terminal batch summary."""

    id: EntityId
    run_id: EntityId
    observation_id: EntityId
    ordinal: int
    format_name: str
    status: EbookCollectionItemStatus
    attempt_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    quality_status: str | None = None
    reused_step_count: int = 0
    executed_step_count: int = 0
    finding_count: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("collection item ordinal must not be negative")
        format_name = require_non_empty(self.format_name, "format_name").upper()
        if format_name not in EBOOK_COLLECTION_FORMATS:
            raise ValueError("collection item format is unsupported")
        object.__setattr__(self, "format_name", format_name)
        if self.attempt_count < 0:
            raise ValueError("attempt_count must not be negative")
        if self.started_at is not None:
            require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.started_at is None or self.completed_at < self.started_at:
                raise ValueError("completed item requires an ordered start timestamp")
        terminal = self.status in _TERMINAL_ITEM_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError("only terminal collection items require completed_at")
        if self.status is EbookCollectionItemStatus.PENDING:
            if self.started_at is not None:
                raise ValueError("pending collection item cannot have a current start")
        elif self.attempt_count < 1 or self.started_at is None:
            raise ValueError("started collection item requires an attempt and timestamp")
        for count, name in (
            (self.reused_step_count, "reused_step_count"),
            (self.executed_step_count, "executed_step_count"),
            (self.finding_count, "finding_count"),
        ):
            if count < 0:
                raise ValueError(f"{name} must not be negative")
        if not terminal and (
            self.reused_step_count or self.executed_step_count or self.finding_count
        ):
            raise ValueError("unfinished collection item cannot carry result counts")
        if terminal and self.status is not EbookCollectionItemStatus.ERROR:
            if self.quality_status is None:
                raise ValueError("analyzed collection item requires quality_status")
            object.__setattr__(
                self,
                "quality_status",
                require_non_empty(self.quality_status, "quality_status"),
            )
            if len(self.quality_status) > 64:
                raise ValueError("quality_status exceeds the configured size limit")
        elif self.quality_status is not None:
            raise ValueError("non-analyzed collection item cannot claim quality_status")
        if self.status is EbookCollectionItemStatus.ERROR:
            if self.error_code is None:
                raise ValueError("errored collection item requires error_code")
            object.__setattr__(
                self,
                "error_code",
                require_non_empty(self.error_code, "error_code"),
            )
            if len(self.error_code) > 64:
                raise ValueError("error_code exceeds the configured size limit")
        elif self.error_code is not None:
            raise ValueError("only errored collection items may carry error_code")
