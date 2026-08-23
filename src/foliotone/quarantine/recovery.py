"""Exact-state, no-move recovery for the ADR-0056 interim quarantine."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

from foliotone.core import EntityId
from foliotone.persistence.quarantine import (
    QuarantineAuthorizationSourceSnapshot,
    QuarantineExecutionEvent,
    QuarantineExecutionRun,
    SQLiteQuarantineStore,
)
from foliotone.persistence.scan_root_lease import OwnedScanRootWriteLease
from foliotone.quarantine.capabilities import ResolvedQuarantineCapability
from foliotone.quarantine.contracts import (
    QuarantineAuthorizationSnapshot,
    QuarantineRunStatus,
)

_BLOCK_BYTES = 1024 * 1024
_MAX_COMPONENT_BYTES = 255
_REPARSE_POINT = 0x0400
_TARGET_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
_INCOMPLETE = frozenset(
    {
        QuarantineRunStatus.PREPARED,
        QuarantineRunStatus.MOVED,
        QuarantineRunStatus.VERIFIED,
    }
)
_NEXT_RECOVERED = {
    QuarantineRunStatus.PREPARED: QuarantineRunStatus.MOVED,
    QuarantineRunStatus.MOVED: QuarantineRunStatus.VERIFIED,
    QuarantineRunStatus.VERIFIED: QuarantineRunStatus.COMPLETED,
}
_RECOVERY_FINDING = {
    QuarantineRunStatus.MOVED: "RECOVERY_MOVE_OBSERVED",
    QuarantineRunStatus.VERIFIED: "RECOVERY_TARGET_VERIFIED",
    QuarantineRunStatus.COMPLETED: "RECOVERY_COMPLETED",
}


class QuarantineRecoveryPhysicalState(StrEnum):
    SOURCE_EXACT_TARGET_ABSENT = "SOURCE_EXACT_TARGET_ABSENT"
    SOURCE_ABSENT_TARGET_EXACT = "SOURCE_ABSENT_TARGET_EXACT"
    AMBIGUOUS = "AMBIGUOUS"


class _EntryState(StrEnum):
    ABSENT = "ABSENT"
    EXACT = "EXACT"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class InterimQuarantineRecoveryResult:
    run_id: EntityId
    status: QuarantineRunStatus


def recover_interim_quarantine(
    *,
    store: SQLiteQuarantineStore,
    authorization: QuarantineAuthorizationSnapshot,
    run: QuarantineExecutionRun,
    lease: OwnedScanRootWriteLease,
    capability: ResolvedQuarantineCapability,
    source: QuarantineAuthorizationSourceSnapshot,
    clock: Callable[[], datetime],
) -> InterimQuarantineRecoveryResult:
    """Close one persisted run without issuing a second filesystem move."""

    if (
        not isinstance(store, SQLiteQuarantineStore)
        or not isinstance(authorization, QuarantineAuthorizationSnapshot)
        or not isinstance(run, QuarantineExecutionRun)
        or not isinstance(lease, OwnedScanRootWriteLease)
        or not isinstance(capability, ResolvedQuarantineCapability)
        or not isinstance(source, QuarantineAuthorizationSourceSnapshot)
        or run.authorization_id != authorization.id
        or run.id != lease.owner_run_id
        or run.scan_root_id != capability.scan_root_id
        or run.scan_root_id != source.scan_root_id
        or run.candidate_file_id != source.file_id
    ):
        raise ValueError("quarantine recovery binding is invalid")

    for _step in range(4):
        events = store.events_for_run(run.id)
        if not events:
            raise ValueError("quarantine recovery requires a prepared run")
        latest = events[-1].status
        if latest not in _INCOMPLETE:
            return InterimQuarantineRecoveryResult(run.id, latest)

        physical = inspect_interim_quarantine_recovery(
            capability=capability,
            source=source,
            target_token=run.target_token,
        )
        if (
            latest is QuarantineRunStatus.PREPARED
            and physical
            is QuarantineRecoveryPhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            physical = inspect_interim_quarantine_recovery(
                capability=capability,
                source=source,
                target_token=run.target_token,
            )
            if (
                physical
                is QuarantineRecoveryPhysicalState.SOURCE_EXACT_TARGET_ABSENT
            ):
                _append_recovery_event(
                    store,
                    run,
                    lease,
                    QuarantineRunStatus.CANCELLED,
                    clock,
                    finding_code="NO_MUTATION_OBSERVED",
                )
                return InterimQuarantineRecoveryResult(
                    run.id,
                    QuarantineRunStatus.CANCELLED,
                )
        if physical is QuarantineRecoveryPhysicalState.SOURCE_ABSENT_TARGET_EXACT:
            next_status = _NEXT_RECOVERED[latest]
            _append_recovery_event(
                store,
                run,
                lease,
                next_status,
                clock,
                finding_code=_RECOVERY_FINDING[next_status],
            )
            continue

        _append_recovery_event(
            store,
            run,
            lease,
            QuarantineRunStatus.MANUAL_REVIEW,
            clock,
            finding_code="RECOVERY_STATE_AMBIGUOUS",
        )
        return InterimQuarantineRecoveryResult(
            run.id,
            QuarantineRunStatus.MANUAL_REVIEW,
        )
    raise ValueError("quarantine recovery exceeded its bounded event sequence")


def inspect_interim_quarantine_recovery(
    *,
    capability: ResolvedQuarantineCapability,
    source: QuarantineAuthorizationSourceSnapshot,
    target_token: str,
) -> QuarantineRecoveryPhysicalState:
    """Classify only the two exact physical distributions accepted by ADR-0056."""

    if (
        not isinstance(capability, ResolvedQuarantineCapability)
        or not isinstance(source, QuarantineAuthorizationSourceSnapshot)
        or capability.scan_root_id != source.scan_root_id
        or not isinstance(target_token, str)
        or _TARGET_TOKEN.fullmatch(target_token) is None
    ):
        return QuarantineRecoveryPhysicalState.AMBIGUOUS
    try:
        source_root, quarantine_root, device = _recovery_directories(capability)
        source_path = source_root.joinpath(*_relative_parts(source.relative_path))
        target_path = quarantine_root / target_token
        source_state = _entry_state(source_path, source_root, source, device)
        target_state = _entry_state(target_path, quarantine_root, source, device)
    except (OSError, TypeError, ValueError):
        return QuarantineRecoveryPhysicalState.AMBIGUOUS
    if source_state is _EntryState.EXACT and target_state is _EntryState.ABSENT:
        return QuarantineRecoveryPhysicalState.SOURCE_EXACT_TARGET_ABSENT
    if source_state is _EntryState.ABSENT and target_state is _EntryState.EXACT:
        return QuarantineRecoveryPhysicalState.SOURCE_ABSENT_TARGET_EXACT
    return QuarantineRecoveryPhysicalState.AMBIGUOUS


def _recovery_directories(
    capability: ResolvedQuarantineCapability,
) -> tuple[Path, Path, int]:
    source_details = os.lstat(capability.scan_root_directory)
    quarantine_details = os.lstat(capability.quarantine_directory)
    source_root = capability.scan_root_directory.resolve(strict=True)
    quarantine_root = capability.quarantine_directory.resolve(strict=True)
    if (
        not stat.S_ISDIR(source_details.st_mode)
        or not stat.S_ISDIR(quarantine_details.st_mode)
        or stat.S_ISLNK(source_details.st_mode)
        or stat.S_ISLNK(quarantine_details.st_mode)
        or _is_reparse(source_details)
        or _is_reparse(quarantine_details)
        or source_root == quarantine_root
        or source_root.is_relative_to(quarantine_root)
        or quarantine_root.is_relative_to(source_root)
        or source_details.st_dev != quarantine_details.st_dev
    ):
        raise ValueError("quarantine recovery directories are unavailable")
    return source_root, quarantine_root, source_details.st_dev


def _relative_parts(value: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    parts = tuple(path.parts)
    if (
        not value
        or "\x00" in value
        or path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or any(len(os.fsencode(part)) > _MAX_COMPONENT_BYTES for part in parts)
    ):
        raise ValueError("quarantine recovery relative path is unavailable")
    return parts


def _entry_state(
    path: Path,
    parent: Path,
    expected: QuarantineAuthorizationSourceSnapshot,
    expected_device: int,
) -> _EntryState:
    descriptor = -1
    try:
        named = os.lstat(path)
    except FileNotFoundError:
        return _EntryState.ABSENT
    except OSError:
        return _EntryState.OTHER
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(parent) or not _matches_expected(
            named,
            expected,
            expected_device,
        ):
            return _EntryState.OTHER
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_BINARY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        opened = os.fstat(descriptor)
        if _named_identity(named) != _named_identity(opened) or not _matches_expected(
            opened,
            expected,
            expected_device,
        ):
            return _EntryState.OTHER
        before = _stable_identity(opened)
        digest, size = _stream_sha256(descriptor, expected.expected_size_bytes)
        after = os.fstat(descriptor)
        named_after = os.lstat(path)
        if (
            before != _stable_identity(after)
            or _named_identity(after) != _named_identity(named_after)
            or size != expected.expected_size_bytes
            or digest != expected.expected_full_sha256
        ):
            return _EntryState.OTHER
        return _EntryState.EXACT
    except OSError:
        return _EntryState.OTHER
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _matches_expected(
    details: os.stat_result,
    expected: QuarantineAuthorizationSourceSnapshot,
    expected_device: int,
) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_nlink == 1
        and not _is_reparse(details)
        and details.st_dev == expected_device
        and details.st_size == expected.expected_size_bytes
        and datetime.fromtimestamp(details.st_mtime, tz=UTC)
        == expected.expected_modified_at
    )


def _stream_sha256(descriptor: int, expected_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        block = os.read(descriptor, _BLOCK_BYTES)
        if not block:
            return digest.hexdigest(), size
        size += len(block)
        if size > expected_size:
            return "", size
        digest.update(block)


def _named_identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _stable_identity(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_nlink,
        details.st_size,
        details.st_mtime_ns,
    )


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", _REPARSE_POINT)
    return bool(attributes & flag)


def _append_recovery_event(
    store: SQLiteQuarantineStore,
    run: QuarantineExecutionRun,
    lease: OwnedScanRootWriteLease,
    status: QuarantineRunStatus,
    clock: Callable[[], datetime],
    *,
    finding_code: str,
) -> None:
    occurred_at = clock()
    if (
        not isinstance(occurred_at, datetime)
        or occurred_at.tzinfo is None
        or occurred_at.utcoffset() is None
    ):
        raise ValueError("quarantine recovery clock must return an aware time")
    sequence = len(store.events_for_run(run.id)) + 1
    store.append_event(
        QuarantineExecutionEvent(
            run.id,
            sequence,
            status,
            occurred_at.astimezone(UTC),
            lease.fence_epoch,
            finding_code,
        ),
        lease,
    )


__all__ = [
    "InterimQuarantineRecoveryResult",
    "QuarantineRecoveryPhysicalState",
    "inspect_interim_quarantine_recovery",
    "recover_interim_quarantine",
]
