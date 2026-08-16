"""Persistent lifecycle state for selective e-book candidate hashing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.enums import EbookCandidateHashPhase, EbookCandidateHashRunStatus
from foliotone.core.ids import EntityId

_TERMINAL_STATUSES = frozenset(
    {
        EbookCandidateHashRunStatus.INTERRUPTED,
        EbookCandidateHashRunStatus.COMPLETED,
        EbookCandidateHashRunStatus.COMPLETED_WITH_FAILURES,
        EbookCandidateHashRunStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class EbookCandidateHashRun:
    """One fenced, path-free invocation over a completed source scan."""

    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    profile: str
    status: EbookCandidateHashRunStatus
    phase: EbookCandidateHashPhase
    started_at: datetime
    heartbeat_at: datetime
    processed_count: int = 0
    hashed_count: int = 0
    failure_count: int = 0
    finished_at: datetime | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    candidate_groups: int | None = None
    candidate_observations: int | None = None
    already_hashed: int | None = None
    remaining_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", require_non_empty(self.profile, "profile"))
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.heartbeat_at, "heartbeat_at")
        if self.heartbeat_at < self.started_at:
            raise ValueError("candidate hash heartbeat must not precede its start")
        terminal = self.status in _TERMINAL_STATUSES
        if terminal != (self.finished_at is not None):
            raise ValueError("only terminal candidate hash runs require finished_at")
        if self.finished_at is not None:
            require_aware_datetime(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise ValueError("candidate hash finish must not precede its start")
        if (self.lease_token is None) != (self.lease_expires_at is None):
            raise ValueError("candidate hash lease fields must be set together")
        if self.status is EbookCandidateHashRunStatus.RUNNING:
            if self.lease_token is None or self.lease_expires_at is None:
                raise ValueError("running candidate hash run requires a lease")
            object.__setattr__(
                self,
                "lease_token",
                require_non_empty(self.lease_token, "lease_token"),
            )
            require_aware_datetime(self.lease_expires_at, "lease_expires_at")
            if self.lease_expires_at <= self.heartbeat_at:
                raise ValueError("candidate hash lease must outlive its heartbeat")
        elif self.lease_token is not None:
            raise ValueError("terminal candidate hash run must not retain a lease")
        for value, name in (
            (self.processed_count, "processed_count"),
            (self.hashed_count, "hashed_count"),
            (self.failure_count, "failure_count"),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.hashed_count + self.failure_count != self.processed_count:
            raise ValueError("candidate hash processed outcomes are inconsistent")
        optional_counts = (
            self.candidate_groups,
            self.candidate_observations,
            self.already_hashed,
            self.remaining_count,
        )
        if any(value is not None and value < 0 for value in optional_counts):
            raise ValueError("candidate hash selection counts must not be negative")
        if self.phase is EbookCandidateHashPhase.SELECTING:
            if any(value is not None for value in optional_counts):
                raise ValueError("selection counts must remain unknown while selecting")
        elif self.status in {
            EbookCandidateHashRunStatus.RUNNING,
            EbookCandidateHashRunStatus.COMPLETED,
            EbookCandidateHashRunStatus.COMPLETED_WITH_FAILURES,
        } and any(value is None for value in optional_counts):
            raise ValueError("candidate hash selection counts are incomplete")
        if all(value is not None for value in optional_counts):
            assert self.candidate_groups is not None
            assert self.candidate_observations is not None
            assert self.already_hashed is not None
            assert self.remaining_count is not None
            if self.candidate_groups > self.candidate_observations:
                raise ValueError("candidate groups exceed candidate observations")
            if self.already_hashed > self.candidate_observations:
                raise ValueError("already-hashed count exceeds candidate observations")
            initially_pending = self.candidate_observations - self.already_hashed
            if self.processed_count > initially_pending:
                raise ValueError("processed count exceeds initially pending candidates")
            if self.hashed_count > initially_pending:
                raise ValueError("hashed count exceeds initially pending candidates")
            if self.remaining_count != initially_pending - self.hashed_count:
                raise ValueError("remaining candidate count is inconsistent")
