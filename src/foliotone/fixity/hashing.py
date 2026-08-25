"""Descriptor-relative, bounded full hashing for fixity baselines."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import NoReturn

from foliotone.fixity.contracts import EbookFixityBaselineSourceEntry

DEFAULT_FIXITY_HASH_CHUNK_BYTES = 4 * 1024 * 1024
_REPARSE_POINT = 0x0400


class EbookFixityHashErrorCode(StrEnum):
    """Fixed, private-data-free hashing failure codes."""

    SECURE_OPEN_UNAVAILABLE = "SECURE_OPEN_UNAVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    CANCELLED = "CANCELLED"


class EbookFixityHashError(RuntimeError):
    """One source could not be hashed without weakening the baseline."""

    def __init__(self, code: EbookFixityHashErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class EbookFixityRootReader:
    """Hold one no-follow root descriptor for a bounded hashing invocation."""

    def __init__(self, source_root: Path) -> None:
        self._source_root = source_root
        self._root_fd = -1
        self._root_identity: tuple[int, int, int, int, int, int] | None = None

    def __enter__(self) -> EbookFixityRootReader:
        _require_secure_open_support()
        if not isinstance(self._source_root, Path) or not self._source_root.is_absolute():
            _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
        try:
            named = os.stat(self._source_root, follow_symlinks=False)
            if not _safe_directory(named):
                _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
            self._root_fd = os.open(
                self._source_root,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            opened = os.fstat(self._root_fd)
            if not _safe_directory(opened) or _named_identity(named) != _named_identity(opened):
                _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
            self._root_identity = _stable_identity(opened)
        except EbookFixityHashError:
            self.close()
            raise
        except OSError:
            self.close()
            _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    def close(self) -> None:
        if self._root_fd >= 0:
            try:
                os.close(self._root_fd)
            except OSError:
                pass
            self._root_fd = -1

    def hash(
        self,
        source: EbookFixityBaselineSourceEntry,
        *,
        chunk_bytes: int = DEFAULT_FIXITY_HASH_CHUNK_BYTES,
        cancelled: Callable[[], bool] | None = None,
        on_bytes_read: Callable[[int], None] | None = None,
    ) -> str:
        """Hash one unchanged regular file through descriptor-relative traversal."""

        if self._root_fd < 0 or self._root_identity is None:
            raise RuntimeError("fixity root reader is not open")
        if not isinstance(source, EbookFixityBaselineSourceEntry):
            raise TypeError("source must be an EbookFixityBaselineSourceEntry")
        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise ValueError("chunk_bytes must be positive")
        self._require_root_unchanged()
        parts = tuple(PurePosixPath(source.relative_locator).parts)
        directory_fds = [os.dup(self._root_fd)]
        directory_identities = [self._root_identity]
        file_fd = -1
        try:
            for component in parts[:-1]:
                next_fd, identity = _open_directory_at(directory_fds[-1], component)
                directory_fds.append(next_fd)
                directory_identities.append(identity)
            parent_fd = directory_fds[-1]
            file_fd, before = _open_source_at(parent_fd, parts[-1], source)
            digest = hashlib.sha256()
            total = 0
            while True:
                if cancelled is not None and cancelled():
                    _fail(EbookFixityHashErrorCode.CANCELLED)
                block = os.read(file_fd, chunk_bytes)
                if not block:
                    break
                total += len(block)
                if total > source.expected_size_bytes:
                    _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)
                digest.update(block)
                if on_bytes_read is not None:
                    on_bytes_read(len(block))
            after = os.fstat(file_fd)
            named_after = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if (
                total != source.expected_size_bytes
                or _stable_identity(before) != _stable_identity(after)
                or _stable_identity(after) != _stable_identity(named_after)
            ):
                _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)
            _require_directory_chain_unchanged(
                parts[:-1],
                directory_fds,
                directory_identities,
            )
            self._require_root_unchanged()
            return digest.hexdigest()
        except EbookFixityHashError:
            raise
        except OSError:
            _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass
            for descriptor in reversed(directory_fds):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _require_root_unchanged(self) -> None:
        try:
            current = os.fstat(self._root_fd)
        except OSError:
            _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
        if self._root_identity != _stable_identity(current) or not _safe_directory(current):
            _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)


def _open_directory_at(
    parent_fd: int, component: str
) -> tuple[int, tuple[int, int, int, int, int, int]]:
    try:
        named = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        if not _safe_directory(named):
            _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)
        descriptor = os.open(
            component,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if not _safe_directory(opened) or _named_identity(named) != _named_identity(opened):
            os.close(descriptor)
            _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)
        return descriptor, _stable_identity(opened)
    except EbookFixityHashError:
        raise
    except OSError:
        _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)


def _require_directory_chain_unchanged(
    components: tuple[str, ...],
    directory_fds: list[int],
    directory_identities: list[tuple[int, int, int, int, int, int]],
) -> None:
    """Re-resolve every held parent from the root after the file hash."""

    try:
        for offset, component in enumerate(components):
            named = os.stat(
                component,
                dir_fd=directory_fds[offset],
                follow_symlinks=False,
            )
            opened = os.fstat(directory_fds[offset + 1])
            expected = directory_identities[offset + 1]
            if (
                not _safe_directory(named)
                or not _safe_directory(opened)
                or _stable_identity(named) != expected
                or _stable_identity(opened) != expected
            ):
                _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)
    except EbookFixityHashError:
        raise
    except OSError:
        _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)


def _open_source_at(
    parent_fd: int,
    name: str,
    source: EbookFixityBaselineSourceEntry,
) -> tuple[int, os.stat_result]:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require_expected_source(named, source)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_BINARY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        try:
            _require_expected_source(opened, source)
            if _named_identity(named) != _named_identity(opened):
                _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor, opened
    except EbookFixityHashError:
        raise
    except OSError:
        _fail(EbookFixityHashErrorCode.SOURCE_UNAVAILABLE)


def _require_expected_source(
    details: os.stat_result,
    source: EbookFixityBaselineSourceEntry,
) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or _is_reparse(details)
        or details.st_size != source.expected_size_bytes
        or datetime.fromtimestamp(details.st_mtime, tz=UTC) != source.expected_modified_at
    ):
        _fail(EbookFixityHashErrorCode.SOURCE_CHANGED)


def _require_secure_open_support() -> None:
    if (
        int(getattr(os, "O_NOFOLLOW", 0)) == 0
        or int(getattr(os, "O_DIRECTORY", 0)) == 0
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        _fail(EbookFixityHashErrorCode.SECURE_OPEN_UNAVAILABLE)


def _safe_directory(details: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(details.st_mode)
        and not stat.S_ISLNK(details.st_mode)
        and not _is_reparse(details)
    )


def _named_identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _stable_identity(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", _REPARSE_POINT)
    return bool(attributes & flag)


def _fail(code: EbookFixityHashErrorCode) -> NoReturn:
    raise EbookFixityHashError(code) from None


__all__ = [
    "DEFAULT_FIXITY_HASH_CHUNK_BYTES",
    "EbookFixityHashError",
    "EbookFixityHashErrorCode",
    "EbookFixityRootReader",
]
