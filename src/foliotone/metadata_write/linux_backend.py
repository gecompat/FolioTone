"""Fixed Linux ``renameat2`` backend for the bounded EPUB title writer.

The public surface accepts no flags, syscall numbers, source paths, or target
names.  Runtime directories come from one resolved private capability, the
source locator comes from persistence, and all mutable names are derived from
the immutable run and authorization.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import platform
import stat
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, NoReturn, cast

from foliotone.metadata_write.authorization import (
    MetadataWriteAuthorizationSnapshot,
    MetadataWriteExecutionRun,
)
from foliotone.metadata_write.capabilities import ResolvedMetadataWriteCapability
from foliotone.metadata_write.contracts import (
    LINUX_METADATA_WRITE_BACKEND_PROFILE,
    LINUX_METADATA_WRITE_PROBE_PROFILE,
    MAX_EPUB_ARCHIVE_BYTES,
)

_RENAME_NOREPLACE: Final = 1
_RENAME_EXCHANGE: Final = 2
_ST_RDONLY: Final = 1
_CHUNK_BYTES: Final = 1024 * 1024
_MAX_COMPONENT_BYTES: Final = 255
_PROBE_DIRECTORY: Final = ".foliotone-metadata-write-probe-v1"
_PROBE_A: Final = "exchange-a"
_PROBE_B: Final = "exchange-b"
_PROBE_C: Final = "noreplace-c"
_PROBE_D: Final = "noreplace-d"
_PROBE_A_DATA: Final = b"foliotone-renameat2-probe-a/v1\n"
_PROBE_B_DATA: Final = b"foliotone-renameat2-probe-b/v1\n"
_PROBE_MOVE_DATA: Final = b"foliotone-renameat2-probe-move/v1\n"
_PROBE_NAMES: Final = frozenset({_PROBE_A, _PROBE_B, _PROBE_C, _PROBE_D})
_ALLOWED_FILESYSTEM_TYPES: Final = frozenset(
    {
        0xEF53,  # ext2/ext3/ext4 family
        0x9123683E,  # btrfs
        0x01021994,  # tmpfs
        0x58465342,  # xfs
    }
)


class LinuxMetadataWriteBackendErrorCode(StrEnum):
    """Fixed path- and filename-free failures for the Linux adapter."""

    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    STATE_AMBIGUOUS = "STATE_AMBIGUOUS"
    IO_FAILED = "IO_FAILED"


class LinuxMetadataWriteBackendError(RuntimeError):
    """One bounded backend failure without private runtime material."""

    def __init__(
        self,
        code: LinuxMetadataWriteBackendErrorCode,
        *,
        mutation_may_have_occurred: bool = False,
    ) -> None:
        self.code = code
        self.mutation_may_have_occurred = mutation_may_have_occurred
        super().__init__(code.value)


class LinuxMetadataWritePhysicalState(StrEnum):
    """Recognizable exact hash distributions; paths remain private."""

    SOURCE_ORIGINAL_ONLY = "SOURCE_ORIGINAL_ONLY"
    SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT = "SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT"
    SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT = "SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT"
    SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL = (
        "SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL"
    )
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class LinuxMetadataWritePhysicalSnapshot:
    """Path-free confirmation of one recognized physical state."""

    state: LinuxMetadataWritePhysicalState
    confirmation_digest: str = field(repr=False)
    backend_profile: str = LINUX_METADATA_WRITE_BACKEND_PROFILE
    conformance_profile: str = LINUX_METADATA_WRITE_PROBE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state, LinuxMetadataWritePhysicalState)
            or self.backend_profile != LINUX_METADATA_WRITE_BACKEND_PROFILE
            or self.conformance_profile != LINUX_METADATA_WRITE_PROBE_PROFILE
            or len(self.confirmation_digest) != 64
            or any(value not in "0123456789abcdef" for value in self.confirmation_digest)
        ):
            raise ValueError("metadata write physical snapshot is invalid")


@dataclass(frozen=True, slots=True)
class _EntryView:
    role: str
    device: int = 0
    inode: int = 0
    mode: int = 0
    uid: int = 0
    gid: int = 0


class _LinuxStatFs(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


class _RenameFailure(Exception):
    def __init__(self, error_number: int) -> None:
        self.error_number = error_number
        super().__init__(str(error_number))


class LinuxMetadataWriteSession(AbstractContextManager["LinuxMetadataWriteSession"]):
    """Open directory-FD session for one immutable run and source locator."""

    def __init__(
        self,
        *,
        source_parent_fd: int,
        recovery_fd: int,
        source_name: str,
        authorization: MetadataWriteAuthorizationSnapshot,
        run: MetadataWriteExecutionRun,
        expected_modified_at: datetime,
    ) -> None:
        self._source_parent_fd = source_parent_fd
        self._recovery_fd = recovery_fd
        self._source_name = source_name
        self._authorization = authorization
        self._run = run
        self._expected_modified_at = expected_modified_at.astimezone(UTC)
        self._draft_name = f".foliotone-metadata-write-{run.id}.draft.epub"
        self._recovery_name = (
            f"original-{authorization.source_sha256}-{run.id}.epub"
        )
        if self._source_name == self._draft_name:
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        self._closed = False

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_quietly(self._source_parent_fd)
        _close_quietly(self._recovery_fd)

    def _open_source(self) -> tuple[int, os.stat_result]:
        descriptor = -1
        try:
            descriptor = os.open(
                self._source_name,
                os.O_RDONLY
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=self._source_parent_fd,
            )
            details = os.fstat(descriptor)
            named = os.stat(
                self._source_name,
                dir_fd=self._source_parent_fd,
                follow_symlinks=False,
            )
            parent = os.fstat(self._source_parent_fd)
        except OSError:
            if descriptor >= 0:
                os.close(descriptor)
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        if (
            (details.st_dev, details.st_ino) != (named.st_dev, named.st_ino)
            or details.st_dev != parent.st_dev
        ):
            os.close(descriptor)
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        _verify_source_preconditions(
            descriptor,
            details,
            self._authorization,
            self._expected_modified_at,
        )
        return descriptor, details

    def read_source_bytes(self) -> bytes:
        """Revalidate and read the exact bounded source through ``openat``."""

        descriptor, details = self._open_source()
        try:
            before = _stable_identity(details)
            data, digest = _read_all(descriptor, MAX_EPUB_ARCHIVE_BYTES)
            after = os.fstat(descriptor)
        except OSError:
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        finally:
            os.close(descriptor)
        if (
            before != _stable_identity(after)
            or len(data) != self._authorization.source_size_bytes
            or digest != self._authorization.source_sha256
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        return data

    def prepare_output(self, staged_output: Path) -> LinuxMetadataWritePhysicalSnapshot:
        """Copy one verified private output into an exclusive same-dir draft."""

        current = self.classify()
        if current.state is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT:
            return current
        if current.state is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY:
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)

        source_fd, source_details = self._open_source()
        try:
            _verify_source_preconditions(
                source_fd,
                source_details,
                self._authorization,
                self._expected_modified_at,
            )
            stage_fd = _open_staged_output(staged_output)
            try:
                target_fd = _create_regular(
                    self._source_parent_fd,
                    self._draft_name,
                    stat.S_IMODE(source_details.st_mode),
                )
                try:
                    _copy_exact_output(
                        stage_fd,
                        target_fd,
                        self._authorization.expected_output_sha256,
                        self._authorization.expected_output_size_bytes,
                    )
                    _preserve_owner_and_mode(target_fd, source_details)
                    os.fsync(target_fd)
                finally:
                    os.close(target_fd)
            finally:
                os.close(stage_fd)
        except LinuxMetadataWriteBackendError:
            raise
        except OSError:
            _fail(LinuxMetadataWriteBackendErrorCode.IO_FAILED)
        finally:
            os.close(source_fd)
        _fsync_directory(self._source_parent_fd)
        prepared = self.classify()
        if prepared.state is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT:
            _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
        return prepared

    def revalidate_prepared(self) -> LinuxMetadataWritePhysicalSnapshot:
        """Perform the final full source/draft check before PREPARED is journaled."""

        self.read_source_bytes()
        value = self.classify()
        if value.state is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT:
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        return value

    def exchange(self) -> LinuxMetadataWritePhysicalSnapshot:
        """Atomically exchange the internally derived draft and source names."""

        if (
            self.classify().state
            is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
        try:
            _renameat2(
                self._source_parent_fd,
                self._draft_name,
                self._source_parent_fd,
                self._source_name,
                _RENAME_EXCHANGE,
            )
        except _RenameFailure as error:
            _raise_rename(error, mutation_may_have_occurred=False)
        try:
            _fsync_directory(self._source_parent_fd)
        except LinuxMetadataWriteBackendError:
            raise LinuxMetadataWriteBackendError(
                LinuxMetadataWriteBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            ) from None
        return self.classify()

    def preserve_original(self) -> LinuxMetadataWritePhysicalSnapshot:
        """Move the exact exchanged original to its no-replace recovery name."""

        if (
            self.classify().state
            is not LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)
        try:
            _renameat2(
                self._source_parent_fd,
                self._draft_name,
                self._recovery_fd,
                self._recovery_name,
                _RENAME_NOREPLACE,
            )
        except _RenameFailure as error:
            _raise_rename(error, mutation_may_have_occurred=False)
        try:
            _fsync_directory(self._source_parent_fd)
            _fsync_directory(self._recovery_fd)
        except LinuxMetadataWriteBackendError:
            raise LinuxMetadataWriteBackendError(
                LinuxMetadataWriteBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            ) from None
        return self.classify()

    def restore_original(self) -> LinuxMetadataWritePhysicalSnapshot:
        """Idempotently restore the source only for an exact known hash distribution."""

        current = self.classify()
        if current.state in {
            LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY,
            LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT,
        }:
            return current
        if current.state is LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL:
            try:
                _renameat2(
                    self._recovery_fd,
                    self._recovery_name,
                    self._source_parent_fd,
                    self._draft_name,
                    _RENAME_NOREPLACE,
                )
            except _RenameFailure as error:
                _raise_rename(error, mutation_may_have_occurred=False)
            try:
                _fsync_directory(self._recovery_fd)
                _fsync_directory(self._source_parent_fd)
            except LinuxMetadataWriteBackendError:
                raise LinuxMetadataWriteBackendError(
                    LinuxMetadataWriteBackendErrorCode.IO_FAILED,
                    mutation_may_have_occurred=True,
                ) from None
            current = self.classify()
        if current.state is not LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT:
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)
        try:
            _renameat2(
                self._source_parent_fd,
                self._draft_name,
                self._source_parent_fd,
                self._source_name,
                _RENAME_EXCHANGE,
            )
        except _RenameFailure as error:
            _raise_rename(error, mutation_may_have_occurred=False)
        try:
            _fsync_directory(self._source_parent_fd)
        except LinuxMetadataWriteBackendError:
            raise LinuxMetadataWriteBackendError(
                LinuxMetadataWriteBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            ) from None
        restored = self.classify()
        if restored.state is not LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT:
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)
        return restored

    def classify(self) -> LinuxMetadataWritePhysicalSnapshot:
        """Classify only exact, safe original/output distributions."""

        source = _entry_view(
            self._source_parent_fd,
            self._source_name,
            self._authorization.source_sha256,
            self._authorization.expected_output_sha256,
            self._authorization.source_size_bytes,
            self._authorization.expected_output_size_bytes,
        )
        draft = _entry_view(
            self._source_parent_fd,
            self._draft_name,
            self._authorization.source_sha256,
            self._authorization.expected_output_sha256,
            self._authorization.source_size_bytes,
            self._authorization.expected_output_size_bytes,
        )
        recovery = _entry_view(
            self._recovery_fd,
            self._recovery_name,
            self._authorization.source_sha256,
            self._authorization.expected_output_sha256,
            self._authorization.source_size_bytes,
            self._authorization.expected_output_size_bytes,
        )
        state = LinuxMetadataWritePhysicalState.AMBIGUOUS
        if (source.role, draft.role, recovery.role) == ("ORIGINAL", "MISSING", "MISSING"):
            state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY
        elif (source.role, draft.role, recovery.role) == (
            "ORIGINAL",
            "OUTPUT",
            "MISSING",
        ) and _metadata_matches(source, draft):
            state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        elif (source.role, draft.role, recovery.role) == (
            "OUTPUT",
            "ORIGINAL",
            "MISSING",
        ) and _metadata_matches(source, draft):
            state = LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        elif (source.role, draft.role, recovery.role) == (
            "OUTPUT",
            "MISSING",
            "ORIGINAL",
        ) and _metadata_matches(source, recovery):
            state = (
                LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
            )
        return LinuxMetadataWritePhysicalSnapshot(
            state,
            _confirmation_digest(self._run, self._authorization, state),
        )

    def confirmation_for(
        self,
        state: LinuxMetadataWritePhysicalState,
    ) -> LinuxMetadataWritePhysicalSnapshot:
        """Build a path-free confirmation for one reconstructed exact phase."""

        if state is LinuxMetadataWritePhysicalState.AMBIGUOUS:
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)
        return LinuxMetadataWritePhysicalSnapshot(
            state,
            _confirmation_digest(self._run, self._authorization, state),
        )


class LinuxMetadataWriteBackend:
    """Create one fixed Linux session after capability-level conformance probing."""

    def open_session(
        self,
        *,
        capability: ResolvedMetadataWriteCapability,
        source_relative_path: str,
        authorization: MetadataWriteAuthorizationSnapshot,
        run: MetadataWriteExecutionRun,
        expected_modified_at: datetime,
    ) -> LinuxMetadataWriteSession:
        _require_platform()
        _require_bindings(capability, authorization, run, expected_modified_at)
        _require_disjoint_capability_directories(capability)
        parent_parts, source_name = _source_locator(source_relative_path)
        root_fd = _open_absolute_directory(capability.scan_root_directory)
        recovery_fd = -1
        parent_fd = -1
        try:
            recovery_fd = _open_absolute_directory(capability.recovery_directory)
            _require_private_recovery_directory(recovery_fd)
            parent_fd = _open_descendant_directory(root_fd, parent_parts)
            _require_supported_filesystem(parent_fd, recovery_fd)
            _probe_renameat2(recovery_fd)
            return LinuxMetadataWriteSession(
                source_parent_fd=parent_fd,
                recovery_fd=recovery_fd,
                source_name=source_name,
                authorization=authorization,
                run=run,
                expected_modified_at=expected_modified_at,
            )
        except Exception:
            if parent_fd >= 0:
                _close_quietly(parent_fd)
            if recovery_fd >= 0:
                _close_quietly(recovery_fd)
            raise
        finally:
            _close_quietly(root_fd)


def _require_platform() -> None:
    required = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        getattr(os, "O_CLOEXEC", 0),
    )
    if (
        sys.platform != "linux"
        or platform.machine().lower() not in {"x86_64", "amd64"}
        or any(not isinstance(value, int) or value == 0 for value in required)
        or not callable(getattr(os, "geteuid", None))
        or not callable(getattr(os, "getegid", None))
        or not callable(getattr(os, "listxattr", None))
        or not callable(getattr(os, "fchmod", None))
        or not callable(getattr(os, "fchown", None))
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    _require_glibc()
    _libc()


def _require_glibc() -> None:
    confstr = getattr(os, "confstr", None)
    if not callable(confstr):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        value = confstr("CS_GNU_LIBC_VERSION")
    except (OSError, TypeError, ValueError):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    if not isinstance(value, str) or not value.startswith("glibc "):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _require_bindings(
    capability: ResolvedMetadataWriteCapability,
    authorization: MetadataWriteAuthorizationSnapshot,
    run: MetadataWriteExecutionRun,
    expected_modified_at: datetime,
) -> None:
    if (
        not isinstance(capability, ResolvedMetadataWriteCapability)
        or not isinstance(authorization, MetadataWriteAuthorizationSnapshot)
        or not isinstance(run, MetadataWriteExecutionRun)
        or not isinstance(expected_modified_at, datetime)
        or expected_modified_at.tzinfo is None
        or expected_modified_at.utcoffset() is None
        or run.authorization_id != authorization.id
        or run.authorization_content_hash != authorization.content_hash
        or run.plan_id != authorization.plan_id
        or run.scan_root_id != authorization.scan_root_id
        or run.file_id != authorization.file_id
        or run.metadata_write_capability_id
        != authorization.metadata_write_capability_id
        or capability.scan_root_id != run.scan_root_id
        or capability.metadata_write_capability_id
        != run.metadata_write_capability_id
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _require_disjoint_capability_directories(
    capability: ResolvedMetadataWriteCapability,
) -> None:
    source = capability.scan_root_directory
    recovery = capability.recovery_directory
    if (
        source == recovery
        or source in recovery.parents
        or recovery in source.parents
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _source_locator(value: str) -> tuple[tuple[str, ...], str]:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
    try:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        parts = tuple(path.parts)
        oversized = any(
            len(os.fsencode(part)) > _MAX_COMPONENT_BYTES for part in parts
        )
    except (OSError, UnicodeError, ValueError):
        _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or oversized
        or path.suffix.lower() != ".epub"
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
    return parts[:-1], parts[-1]


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_NOFOLLOW", 0))
        | int(getattr(os, "O_CLOEXEC", 0))
    )


def _open_absolute_directory(path: Path) -> int:
    if not isinstance(path, Path) or not path.is_absolute():
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    descriptor = -1
    try:
        descriptor = os.open("/", _directory_flags())
        for part in path.parts[1:]:
            if part in {"", ".", ".."}:
                _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
            next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        return descriptor
    except LinuxMetadataWriteBackendError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _open_descendant_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    root_device = os.fstat(root_fd).st_dev
    try:
        for part in parts:
            next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            if os.fstat(descriptor).st_dev != root_device:
                _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        return descriptor
    except LinuxMetadataWriteBackendError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)


def _require_private_recovery_directory(descriptor: int) -> None:
    details = os.fstat(descriptor)
    geteuid = getattr(os, "geteuid", None)
    if (
        not callable(geteuid)
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    _require_no_xattrs(
        descriptor,
        LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE,
    )


def _require_supported_filesystem(source_fd: int, recovery_fd: int) -> None:
    source = os.fstat(source_fd)
    recovery = os.fstat(recovery_fd)
    source_fs = _fstatfs(source_fd)
    recovery_fs = _fstatfs(recovery_fd)
    if (
        source.st_dev != recovery.st_dev
        or source_fs.f_type != recovery_fs.f_type
        or source_fs.f_type not in _ALLOWED_FILESYSTEM_TYPES
        or source_fs.f_flags & _ST_RDONLY
        or recovery_fs.f_flags & _ST_RDONLY
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _probe_renameat2(recovery_fd: int) -> None:
    try:
        os.mkdir(_PROBE_DIRECTORY, mode=0o700, dir_fd=recovery_fd)
    except FileExistsError:
        pass
    except (OSError, TypeError):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        probe_fd = os.open(_PROBE_DIRECTORY, _directory_flags(), dir_fd=recovery_fd)
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        details = os.fstat(probe_fd)
        geteuid = getattr(os, "geteuid", None)
        if (
            not callable(geteuid)
            or details.st_uid != geteuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        _require_no_xattrs(
            probe_fd,
            LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE,
        )
        entries = set(os.listdir(probe_fd))
        if not entries <= _PROBE_NAMES:
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        _ensure_probe_exchange_files(probe_fd)
        _ensure_probe_move_file(probe_fd)
        before_a = _read_named_small(probe_fd, _PROBE_A)
        before_b = _read_named_small(probe_fd, _PROBE_B)
        if {before_a, before_b} != {_PROBE_A_DATA, _PROBE_B_DATA}:
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        _renameat2(probe_fd, _PROBE_A, probe_fd, _PROBE_B, _RENAME_EXCHANGE)
        if (
            _read_named_small(probe_fd, _PROBE_A) != before_b
            or _read_named_small(probe_fd, _PROBE_B) != before_a
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        collision_before = (
            _named_identity(probe_fd, _PROBE_A),
            _named_identity(probe_fd, _PROBE_B),
        )
        try:
            _renameat2(probe_fd, _PROBE_A, probe_fd, _PROBE_B, _RENAME_NOREPLACE)
        except _RenameFailure as error:
            if error.error_number != errno.EEXIST:
                raise
        else:
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        if collision_before != (
            _named_identity(probe_fd, _PROBE_A),
            _named_identity(probe_fd, _PROBE_B),
        ):
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        entries = set(os.listdir(probe_fd))
        if _PROBE_C in entries and _PROBE_D not in entries:
            old_name, new_name = _PROBE_C, _PROBE_D
        elif _PROBE_D in entries and _PROBE_C not in entries:
            old_name, new_name = _PROBE_D, _PROBE_C
        else:
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        _renameat2(probe_fd, old_name, probe_fd, new_name, _RENAME_NOREPLACE)
        if _read_named_small(probe_fd, new_name) != _PROBE_MOVE_DATA:
            _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
        _fsync_directory(probe_fd)
        _fsync_directory(recovery_fd)
    except (LinuxMetadataWriteBackendError, _RenameFailure):
        raise LinuxMetadataWriteBackendError(
            LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE
        ) from None
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    finally:
        os.close(probe_fd)


def _ensure_probe_exchange_files(probe_fd: int) -> None:
    entries = set(os.listdir(probe_fd))
    if _PROBE_A not in entries:
        _create_probe_file(probe_fd, _PROBE_A, _PROBE_A_DATA)
    if _PROBE_B not in entries:
        _create_probe_file(probe_fd, _PROBE_B, _PROBE_B_DATA)


def _ensure_probe_move_file(probe_fd: int) -> None:
    entries = set(os.listdir(probe_fd))
    present = entries & {_PROBE_C, _PROBE_D}
    if not present:
        _create_probe_file(probe_fd, _PROBE_C, _PROBE_MOVE_DATA)
    elif len(present) != 1:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    name = next(iter(set(os.listdir(probe_fd)) & {_PROBE_C, _PROBE_D}))
    if _read_named_small(probe_fd, name) != _PROBE_MOVE_DATA:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _create_probe_file(directory_fd: int, name: str, data: bytes) -> None:
    descriptor = _create_regular(directory_fd, name, 0o600)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    finally:
        os.close(descriptor)
    _fsync_directory(directory_fd)


def _read_named_small(directory_fd: int, name: str) -> bytes:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0)) | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=directory_fd,
        )
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
            data = os.read(descriptor, 128)
            if os.read(descriptor, 1):
                _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
            return data
        finally:
            os.close(descriptor)
    except LinuxMetadataWriteBackendError:
        raise
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)


def _named_identity(directory_fd: int, name: str) -> tuple[int, int, int, int]:
    try:
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _verify_source_preconditions(
    descriptor: int,
    details: os.stat_result,
    authorization: MetadataWriteAuthorizationSnapshot,
    expected_modified_at: datetime,
) -> None:
    geteuid = getattr(os, "geteuid", None)
    if (
        not callable(geteuid)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o7000
        or details.st_size != authorization.source_size_bytes
        or datetime.fromtimestamp(details.st_mtime, tz=UTC) != expected_modified_at
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)
    _require_no_xattrs(descriptor, LinuxMetadataWriteBackendErrorCode.SOURCE_STALE)


def _open_staged_output(path: Path) -> int:
    if not isinstance(path, Path) or not path.is_absolute():
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        details = os.fstat(descriptor)
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        os.close(descriptor)
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
    return descriptor


def _create_regular(directory_fd: int, name: str, mode: int) -> int:
    try:
        return os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            mode,
            dir_fd=directory_fd,
        )
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)


def _copy_exact_output(
    source_fd: int,
    target_fd: int,
    expected_hash: str,
    expected_size: int,
) -> None:
    digest = hashlib.sha256()
    total = 0
    try:
        while True:
            block = os.read(source_fd, _CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            if total > MAX_EPUB_ARCHIVE_BYTES or total > expected_size:
                _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
            digest.update(block)
            _write_all(target_fd, block)
    except LinuxMetadataWriteBackendError:
        raise
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
    if total != expected_size or digest.hexdigest() != expected_hash:
        _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)


def _preserve_owner_and_mode(target_fd: int, source: os.stat_result) -> None:
    fchmod = cast(Callable[[int, int], None] | None, getattr(os, "fchmod", None))
    fchown = cast(Callable[[int, int, int], None] | None, getattr(os, "fchown", None))
    if fchmod is None or fchown is None:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        current = os.fstat(target_fd)
        if current.st_gid != source.st_gid:
            fchown(target_fd, -1, source.st_gid)
        fchmod(target_fd, stat.S_IMODE(source.st_mode))
        details = os.fstat(target_fd)
    except (OSError, TypeError):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    if (
        details.st_uid != source.st_uid
        or details.st_gid != source.st_gid
        or stat.S_IMODE(details.st_mode) != stat.S_IMODE(source.st_mode)
    ):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    _require_no_xattrs(target_fd, LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)


def _entry_view(
    directory_fd: int,
    name: str,
    original_hash: str,
    output_hash: str,
    original_size: int,
    output_size: int,
) -> _EntryView:
    try:
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _EntryView("MISSING")
    except OSError:
        return _EntryView("OTHER")
    geteuid = getattr(os, "geteuid", None)
    if (
        not callable(geteuid)
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or named.st_uid != geteuid()
        or stat.S_IMODE(named.st_mode) & 0o7000
    ):
        return _EntryView("OTHER")
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                return _EntryView("OTHER")
            _require_no_xattrs(
                descriptor,
                LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS,
            )
            size, digest = _hash_bounded(descriptor, MAX_EPUB_ARCHIVE_BYTES)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, LinuxMetadataWriteBackendError):
        return _EntryView("OTHER")
    if _stable_identity(opened) != _stable_identity(after):
        return _EntryView("OTHER")
    role = (
        "ORIGINAL"
        if (digest, size) == (original_hash, original_size)
        else "OUTPUT"
        if (digest, size) == (output_hash, output_size)
        else "OTHER"
    )
    return _EntryView(
        role,
        opened.st_dev,
        opened.st_ino,
        stat.S_IMODE(opened.st_mode),
        opened.st_uid,
        opened.st_gid,
    )


def _metadata_matches(left: _EntryView, right: _EntryView) -> bool:
    return (
        left.device == right.device
        and left.mode == right.mode
        and left.uid == right.uid
        and left.gid == right.gid
    )


def _require_no_xattrs(
    descriptor: int,
    code: LinuxMetadataWriteBackendErrorCode,
) -> None:
    listxattr = getattr(os, "listxattr", None)
    if not callable(listxattr):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        values = listxattr(descriptor)
    except (OSError, TypeError):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    if values:
        _fail(code)


def _read_all(descriptor: int, maximum: int) -> tuple[bytes, str]:
    digest = hashlib.sha256()
    output = bytearray()
    while True:
        block = os.read(descriptor, min(_CHUNK_BYTES, maximum + 1 - len(output)))
        if not block:
            break
        output.extend(block)
        if len(output) > maximum:
            _fail(LinuxMetadataWriteBackendErrorCode.OUTPUT_INVALID)
        digest.update(block)
    return bytes(output), digest.hexdigest()


def _hash_bounded(descriptor: int, maximum: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    while True:
        block = os.read(descriptor, _CHUNK_BYTES)
        if not block:
            break
        total += len(block)
        if total > maximum:
            _fail(LinuxMetadataWriteBackendErrorCode.STATE_AMBIGUOUS)
        digest.update(block)
    return total, digest.hexdigest()


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("bounded write failed")
        view = view[written:]


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _stable_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError:
        _fail(LinuxMetadataWriteBackendErrorCode.IO_FAILED)


def _confirmation_digest(
    run: MetadataWriteExecutionRun,
    authorization: MetadataWriteAuthorizationSnapshot,
    state: LinuxMetadataWritePhysicalState,
) -> str:
    payload = "\x00".join(
        (
            "foliotone:metadata-write-physical-state/v1",
            str(run.id),
            authorization.content_hash,
            authorization.source_sha256,
            authorization.expected_output_sha256,
            state.value,
            LINUX_METADATA_WRITE_BACKEND_PROFILE,
            LINUX_METADATA_WRITE_PROBE_PROFILE,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _libc() -> Any:
    try:
        library = ctypes.CDLL(None, use_errno=True)
        renameat2 = library.renameat2
        fstatfs = library.fstatfs
    except (AttributeError, OSError):
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_LinuxStatFs)]
    fstatfs.restype = ctypes.c_int
    return library


def _renameat2(
    old_directory_fd: int,
    old_name: str,
    new_directory_fd: int,
    new_name: str,
    flag: int,
) -> None:
    if flag not in {_RENAME_EXCHANGE, _RENAME_NOREPLACE}:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        encoded_old_name = os.fsencode(old_name)
        encoded_new_name = os.fsencode(new_name)
    except (OSError, UnicodeError, ValueError):
        raise _RenameFailure(errno.EINVAL) from None
    library = _libc()
    ctypes.set_errno(0)
    result = library.renameat2(
        old_directory_fd,
        encoded_old_name,
        new_directory_fd,
        encoded_new_name,
        flag,
    )
    if result != 0:
        raise _RenameFailure(ctypes.get_errno())


def _fstatfs(descriptor: int) -> _LinuxStatFs:
    value = _LinuxStatFs()
    library = _libc()
    ctypes.set_errno(0)
    if library.fstatfs(descriptor, ctypes.byref(value)) != 0:
        _fail(LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE)
    return value


def _raise_rename(
    error: _RenameFailure,
    *,
    mutation_may_have_occurred: bool,
) -> NoReturn:
    unavailable = {
        errno.EACCES,
        errno.EPERM,
        errno.EROFS,
        errno.EXDEV,
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    code = (
        LinuxMetadataWriteBackendErrorCode.TOOL_UNAVAILABLE
        if error.error_number in unavailable
        else LinuxMetadataWriteBackendErrorCode.IO_FAILED
    )
    raise LinuxMetadataWriteBackendError(
        code,
        mutation_may_have_occurred=mutation_may_have_occurred,
    ) from None


def _fail(code: LinuxMetadataWriteBackendErrorCode) -> NoReturn:
    raise LinuxMetadataWriteBackendError(code) from None


__all__ = [
    "LINUX_METADATA_WRITE_BACKEND_PROFILE",
    "LINUX_METADATA_WRITE_PROBE_PROFILE",
    "LinuxMetadataWriteBackend",
    "LinuxMetadataWriteBackendError",
    "LinuxMetadataWriteBackendErrorCode",
    "LinuxMetadataWritePhysicalSnapshot",
    "LinuxMetadataWritePhysicalState",
    "LinuxMetadataWriteSession",
]
