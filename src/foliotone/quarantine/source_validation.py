"""Read-only physical revalidation for ADR-0056 quarantine authorization."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import NoReturn

from foliotone.persistence.quarantine import QuarantineAuthorizationSourceSnapshot
from foliotone.quarantine.capabilities import ResolvedQuarantineCapability

_BLOCK_BYTES = 1024 * 1024
_MAX_COMPONENT_BYTES = 255
_REPARSE_POINT = 0x0400


class QuarantineSourceValidationErrorCode(StrEnum):
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    STALE = "STALE"


class QuarantineSourceValidationError(RuntimeError):
    """A fixed path- and hash-free source-validation failure."""

    def __init__(self, code: QuarantineSourceValidationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class InterimQuarantineSourceVerifier:
    """Stream-verify one current regular source without mutation authority."""

    def verify(
        self,
        *,
        capability: ResolvedQuarantineCapability,
        source: QuarantineAuthorizationSourceSnapshot,
    ) -> None:
        if (
            not isinstance(capability, ResolvedQuarantineCapability)
            or not isinstance(source, QuarantineAuthorizationSourceSnapshot)
            or capability.scan_root_id != source.scan_root_id
        ):
            _fail(QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE)
        root, root_details = _capability_directories(capability)
        parts = _relative_parts(source.relative_path)
        candidate = root.joinpath(*parts)
        descriptor = -1
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                _fail(QuarantineSourceValidationErrorCode.STALE)
            named = os.lstat(candidate)
            _require_expected_file(named, source)
            descriptor = os.open(
                candidate,
                os.O_RDONLY
                | int(getattr(os, "O_BINARY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            opened = os.fstat(descriptor)
            if (
                _named_identity(named) != _named_identity(opened)
                or opened.st_dev != root_details.st_dev
            ):
                _fail(QuarantineSourceValidationErrorCode.STALE)
            _require_expected_file(opened, source)
            before = _stable_identity(opened)
            digest, size = _stream_sha256(descriptor, source.expected_size_bytes)
            after = os.fstat(descriptor)
            named_after = os.lstat(candidate)
            if (
                before != _stable_identity(after)
                or _named_identity(after) != _named_identity(named_after)
                or size != source.expected_size_bytes
                or digest != source.expected_full_sha256
            ):
                _fail(QuarantineSourceValidationErrorCode.STALE)
        except QuarantineSourceValidationError:
            raise
        except OSError:
            _fail(QuarantineSourceValidationErrorCode.STALE)
        finally:
            if descriptor >= 0:
                _close_quietly(descriptor)


def _capability_directories(
    capability: ResolvedQuarantineCapability,
) -> tuple[Path, os.stat_result]:
    if (
        not isinstance(capability.scan_root_directory, Path)
        or not isinstance(capability.quarantine_directory, Path)
        or not capability.scan_root_directory.is_absolute()
        or not capability.quarantine_directory.is_absolute()
    ):
        _fail(QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE)
    try:
        root_details = os.lstat(capability.scan_root_directory)
        quarantine_details = os.lstat(capability.quarantine_directory)
        root = capability.scan_root_directory.resolve(strict=True)
        quarantine = capability.quarantine_directory.resolve(strict=True)
    except OSError:
        _fail(QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE)
    if (
        not stat.S_ISDIR(root_details.st_mode)
        or not stat.S_ISDIR(quarantine_details.st_mode)
        or stat.S_ISLNK(root_details.st_mode)
        or stat.S_ISLNK(quarantine_details.st_mode)
        or _is_reparse(root_details)
        or _is_reparse(quarantine_details)
        or root == quarantine
        or root.is_relative_to(quarantine)
        or quarantine.is_relative_to(root)
        or root_details.st_dev != quarantine_details.st_dev
    ):
        _fail(QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE)
    return root, root_details


def _relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(QuarantineSourceValidationErrorCode.STALE)
    try:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        parts = tuple(path.parts)
        oversized = any(len(os.fsencode(part)) > _MAX_COMPONENT_BYTES for part in parts)
    except (OSError, UnicodeError, ValueError):
        _fail(QuarantineSourceValidationErrorCode.STALE)
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or oversized
    ):
        _fail(QuarantineSourceValidationErrorCode.STALE)
    return parts


def _require_expected_file(
    details: os.stat_result,
    source: QuarantineAuthorizationSourceSnapshot,
) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or _is_reparse(details)
        or details.st_size != source.expected_size_bytes
        or datetime.fromtimestamp(details.st_mtime, tz=UTC) != source.expected_modified_at
    ):
        _fail(QuarantineSourceValidationErrorCode.STALE)


def _stream_sha256(descriptor: int, expected_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        block = os.read(descriptor, _BLOCK_BYTES)
        if not block:
            return digest.hexdigest(), size
        size += len(block)
        if size > expected_size:
            _fail(QuarantineSourceValidationErrorCode.STALE)
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


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _fail(code: QuarantineSourceValidationErrorCode) -> NoReturn:
    raise QuarantineSourceValidationError(code) from None


__all__ = [
    "InterimQuarantineSourceVerifier",
    "QuarantineSourceValidationError",
    "QuarantineSourceValidationErrorCode",
]
