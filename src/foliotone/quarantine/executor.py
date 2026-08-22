"""Interim, deliberately bounded filesystem executor for one quarantine run.

This adapter intentionally uses only ``os.rename`` after a target-absence
check.  It never copies or deletes.  The absence check is not an atomic
no-replace primitive on every supported platform; the remaining race is
documented and must be replaced by the later FG-W10-MOVE-BACKEND hardening.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from foliotone.core import EntityId
from foliotone.persistence.quarantine import (
    QuarantineExecutionEvent,
    QuarantineExecutionRun,
    SQLiteQuarantineStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease
from foliotone.quarantine.contracts import (
    QuarantineAuthorizationSnapshot,
    QuarantineRunStatus,
)


class InterimQuarantineError(RuntimeError):
    """The bounded interim executor refused to mutate a candidate file."""


@dataclass(frozen=True, slots=True)
class InterimQuarantinePaths:
    """Private runtime paths; these values must never enter persistence or reports."""

    candidate_path: Path = field(repr=False)
    scan_root_directory: Path = field(repr=False)
    quarantine_directory: Path = field(repr=False)


@dataclass(frozen=True, slots=True)
class InterimQuarantineExecutionResult:
    """Opaque outcome suitable for callers which must not expose private paths."""

    run_id: EntityId
    status: QuarantineRunStatus


def execute_interim_quarantine(
    *,
    store: SQLiteQuarantineStore,
    authorization: QuarantineAuthorizationSnapshot,
    run: QuarantineExecutionRun,
    lease: OwnedScanRootWriteLease,
    paths: InterimQuarantinePaths,
    occurred_at: datetime,
) -> InterimQuarantineExecutionResult:
    """Persist and execute one same-filesystem ``os.rename`` quarantine move.

    The caller supplies an already-authorized, single-candidate run and its
    root lease.  The function records ``PREPARED`` before touching the source,
    then records every observed state.  It does not attempt rollback on any
    post-move failure.
    """

    if run.authorization_id != authorization.id:
        raise InterimQuarantineError("run authorization does not match")
    if run.scan_root_id != authorization.scan_root_id:
        raise InterimQuarantineError("run ScanRoot does not match authorization")
    if occurred_at < authorization.authorized_at or occurred_at >= authorization.expires_at:
        raise InterimQuarantineError("quarantine authorization is not currently valid")

    _require_target_token(run.target_token)
    store.create_prepared_run(run, lease, occurred_at)
    candidate = paths.candidate_path
    target = paths.quarantine_directory / run.target_token
    try:
        _validate_before_move(
            candidate,
            paths.scan_root_directory,
            paths.quarantine_directory,
            target,
            authorization,
        )
    except InterimQuarantineError as error:
        _append_terminal(store, run, lease, QuarantineRunStatus.VALIDATION_FAILED, occurred_at)
        raise error

    try:
        os.rename(candidate, target)
    except OSError as error:
        _append_terminal(store, run, lease, QuarantineRunStatus.VALIDATION_FAILED, occurred_at)
        raise InterimQuarantineError("interim filesystem rename failed") from error
    _append(store, run, lease, QuarantineRunStatus.MOVED, occurred_at)

    try:
        _validate_after_move(candidate, target, authorization)
    except InterimQuarantineError as error:
        _append_terminal(store, run, lease, QuarantineRunStatus.MANUAL_REVIEW, occurred_at)
        raise error
    _append(store, run, lease, QuarantineRunStatus.VERIFIED, occurred_at)
    _append(store, run, lease, QuarantineRunStatus.COMPLETED, occurred_at)
    return InterimQuarantineExecutionResult(run.id, QuarantineRunStatus.COMPLETED)


def _validate_before_move(
    candidate: Path,
    scan_root_directory: Path,
    quarantine_directory: Path,
    target: Path,
    authorization: QuarantineAuthorizationSnapshot,
) -> None:
    root = _directory_stat(scan_root_directory, "ScanRoot")
    source_stat = _regular_file_stat(candidate, "candidate")
    directory_stat = _directory_stat(quarantine_directory)
    root_path = scan_root_directory.resolve(strict=True)
    quarantine_path = quarantine_directory.resolve(strict=True)
    candidate_path = candidate.resolve(strict=True)
    if not candidate_path.is_relative_to(root_path):
        raise InterimQuarantineError("candidate is outside the configured ScanRoot")
    if quarantine_path.is_relative_to(root_path) or root_path.is_relative_to(quarantine_path):
        raise InterimQuarantineError("quarantine directory overlaps the configured ScanRoot")
    if root.st_dev != source_stat.st_dev:
        raise InterimQuarantineError("candidate does not use the configured ScanRoot filesystem")
    if source_stat.st_dev != directory_stat.st_dev:
        raise InterimQuarantineError("cross-filesystem quarantine move is unavailable")
    if os.path.lexists(target):
        raise InterimQuarantineError("quarantine target already exists")
    if _sha256(candidate) != authorization.candidate_full_sha256:
        raise InterimQuarantineError("candidate content no longer matches authorization")


def _validate_after_move(
    candidate: Path,
    target: Path,
    authorization: QuarantineAuthorizationSnapshot,
) -> None:
    if os.path.lexists(candidate):
        raise InterimQuarantineError("candidate remains present after quarantine rename")
    _regular_file_stat(target, "quarantine target")
    if _sha256(target) != authorization.candidate_full_sha256:
        raise InterimQuarantineError("quarantine target content does not match authorization")


def _regular_file_stat(path: Path, label: str) -> os.stat_result:
    try:
        values = os.lstat(path)
    except OSError as error:
        raise InterimQuarantineError(f"{label} is unavailable") from error
    if not stat.S_ISREG(values.st_mode):
        raise InterimQuarantineError(f"{label} is not a regular non-symlink file")
    return values


def _directory_stat(path: Path, label: str = "quarantine directory") -> os.stat_result:
    try:
        values = os.lstat(path)
    except OSError as error:
        raise InterimQuarantineError(f"{label} is unavailable") from error
    if not stat.S_ISDIR(values.st_mode):
        raise InterimQuarantineError(f"{label} is not a directory")
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise InterimQuarantineError("candidate content cannot be read") from error
    return digest.hexdigest()


def _require_target_token(value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise InterimQuarantineError("quarantine target token is invalid")


def _append(
    store: SQLiteQuarantineStore,
    run: QuarantineExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: QuarantineRunStatus,
    occurred_at: datetime,
) -> None:
    sequence = len(store.events_for_run(run.id)) + 1
    store.append_event(
        QuarantineExecutionEvent(run.id, sequence, status, occurred_at, lease.fence_epoch),
        lease,
    )


def _append_terminal(
    store: SQLiteQuarantineStore,
    run: QuarantineExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: QuarantineRunStatus,
    occurred_at: datetime,
) -> None:
    _append(store, run, lease, status, occurred_at)
