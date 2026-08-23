"""Fixed Linux backend for the bounded same-parent e-book rename.

The adapter owns the syscall numbers and flags.  Its public surface accepts
only already bound authority objects plus persistence-derived relative
locators; it never accepts arbitrary syscall flags, commands, or fallback
strategies.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import stat
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final, NoReturn
from uuid import uuid4

from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.ebook_rename.authority import (
    EbookRenameAuthorizationSnapshot,
    EbookRenameBackendBinding,
    EbookRenameCapabilityProbeSnapshot,
    EbookRenameExecutionRun,
    EbookRenamePhysicalPreparationEvidence,
    EbookRenamePreparationSnapshot,
    build_ebook_rename_capability_probe,
    build_ebook_rename_physical_evidence,
    ebook_rename_dependencies_fingerprint,
    ebook_rename_locator_digest,
)
from foliotone.ebook_rename.capabilities import ResolvedEbookRenameCapability
from foliotone.ebook_rename.target import EBOOK_RENAME_PROCESSOR_PROFILE

EBOOK_RENAME_XATTR_FINGERPRINT_PROFILE: Final = "ebook-file-xattrs/v1"

_SYS_RENAMEAT2_X86_64: Final = 316
_SYS_OPENAT2_X86_64: Final = 437
_RENAME_NOREPLACE: Final = 1
_RESOLVE_NO_XDEV: Final = 0x01
_RESOLVE_NO_MAGICLINKS: Final = 0x02
_RESOLVE_NO_SYMLINKS: Final = 0x04
_RESOLVE_BENEATH: Final = 0x08
_PARENT_RESOLVE_FLAGS: Final = (
    _RESOLVE_BENEATH
    | _RESOLVE_NO_SYMLINKS
    | _RESOLVE_NO_MAGICLINKS
    | _RESOLVE_NO_XDEV
)
_ST_RDONLY: Final = 1
_MAX_COMPONENT_BYTES: Final = 255
_MAX_LOCATOR_BYTES: Final = 1024
_MAX_XATTR_COUNT: Final = 32
_MAX_XATTR_NAME_BYTES: Final = 255
_MAX_XATTR_VALUE_BYTES: Final = 64 * 1024
_MAX_XATTR_TOTAL_BYTES: Final = 128 * 1024
_CHUNK_BYTES: Final = 1024 * 1024
_FILESYSTEM_IDENTITY_DOMAIN: Final = b"foliotone:ebook-rename-filesystem/v1\x00"
_XATTR_DOMAIN: Final = b"foliotone:ebook-file-xattrs/v1\x00"
_CONFIRMATION_DOMAIN: Final = b"foliotone:ebook-rename-physical-state/v1\x00"
_PROBE_DATA: Final = b"foliotone-ebook-rename-probe/v1\n"
_FILESYSTEM_TYPES: Final = {
    0xEF53: "ext4",
    0x9123683E: "btrfs",
    0x58465342: "xfs",
    0x01021994: "tmpfs",
}


class LinuxEbookRenameBackendErrorCode(StrEnum):
    """Fixed path-free failures returned by the Linux adapter."""

    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    SOURCE_STALE = "SOURCE_STALE"
    TARGET_COLLISION = "TARGET_COLLISION"
    STATE_AMBIGUOUS = "STATE_AMBIGUOUS"
    IO_FAILED = "IO_FAILED"


class LinuxEbookRenameBackendError(RuntimeError):
    """One bounded adapter failure without private filesystem material."""

    def __init__(
        self,
        code: LinuxEbookRenameBackendErrorCode,
        *,
        mutation_may_have_occurred: bool = False,
    ) -> None:
        self.code = code
        self.mutation_may_have_occurred = mutation_may_have_occurred
        super().__init__(code.value)


class LinuxEbookRenamePhysicalState(StrEnum):
    """The only exact physical distributions understood by recovery."""

    SOURCE_EXACT_TARGET_ABSENT = "SOURCE_EXACT_TARGET_ABSENT"
    SOURCE_ABSENT_TARGET_EXACT = "SOURCE_ABSENT_TARGET_EXACT"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class LinuxEbookRenamePhysicalSnapshot:
    """Path-free proof of a classified physical distribution."""

    state: LinuxEbookRenamePhysicalState
    confirmation_digest: str = field(repr=False)
    backend_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state, LinuxEbookRenamePhysicalState)
            or self.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or not _is_sha256(self.confirmation_digest)
        ):
            raise ValueError("e-book rename physical snapshot is invalid")


@dataclass(frozen=True, slots=True)
class _EntryView:
    role: str
    device: int = 0
    inode: int = 0


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


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


class _SyscallFailure(Exception):
    def __init__(self, error_number: int) -> None:
        self.error_number = error_number
        super().__init__(str(error_number))


class LinuxEbookRenameSession(AbstractContextManager["LinuxEbookRenameSession"]):
    """One held parent-FD session for a single immutable execution run."""

    def __init__(
        self,
        *,
        parent_fd: int,
        source_name: str,
        target_name: str,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        preparation: EbookRenamePreparationSnapshot,
        run: EbookRenameExecutionRun,
    ) -> None:
        self._parent_fd = parent_fd
        self._source_name = source_name
        self._target_name = target_name
        self._capability = capability
        self._probe = probe
        self._preparation = preparation
        self._run = run
        self._held_source_fd = -1
        self._forward_attempted = False
        self._reverse_attempted = False
        self._closed = False

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_quietly(self._held_source_fd)
        self._held_source_fd = -1
        _close_quietly(self._parent_fd)

    def classify(self) -> LinuxEbookRenamePhysicalSnapshot:
        """Hash and classify both bound names without following links."""

        self._require_open()
        self._revalidate_environment()
        source = _entry_view(self._parent_fd, self._source_name, self._preparation)
        target = _entry_view(self._parent_fd, self._target_name, self._preparation)
        state = (
            LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
            if source.role == "EXACT" and target.role == "MISSING"
            else LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
            if source.role == "MISSING" and target.role == "EXACT"
            else LinuxEbookRenamePhysicalState.AMBIGUOUS
        )
        return self._snapshot(state)

    def revalidate_forward_preconditions(self) -> LinuxEbookRenamePhysicalSnapshot:
        """Bind the exact source FD and prove target absence just before rename."""

        self._require_open()
        self._revalidate_environment()
        _close_quietly(self._held_source_fd)
        self._held_source_fd = -1
        try:
            descriptor, view = _open_exact_entry(
                self._parent_fd,
                self._source_name,
                self._preparation,
            )
        except (FileNotFoundError, OSError, _SyscallFailure):
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        target = _entry_view(self._parent_fd, self._target_name, self._preparation)
        if view.role != "EXACT" or target.role != "MISSING":
            _close_quietly(descriptor)
            if target.role != "MISSING":
                _fail(LinuxEbookRenameBackendErrorCode.TARGET_COLLISION)
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        try:
            os.fsync(descriptor)
        except OSError:
            _close_quietly(descriptor)
            _fail(LinuxEbookRenameBackendErrorCode.IO_FAILED)
        named = _named_stat(self._parent_fd, self._source_name)
        opened = os.fstat(descriptor)
        if named is None or (named.st_dev, named.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            _close_quietly(descriptor)
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        self._held_source_fd = descriptor
        return self._snapshot(
            LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        )

    def rename_forward(self) -> None:
        """Perform exactly one no-replace source-to-target rename and parent fsync."""

        self._require_open()
        self._revalidate_environment()
        if self._held_source_fd < 0 or self._forward_attempted:
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        self._forward_attempted = True
        self._rename(self._source_name, self._target_name)

    def verify_forward(self) -> LinuxEbookRenamePhysicalSnapshot:
        """Prove the moved name still denotes the held, byte-exact source inode."""

        self._require_open()
        self._revalidate_environment()
        if self._held_source_fd < 0 or not self._forward_attempted:
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)
        snapshot = self.classify()
        target = _named_stat(self._parent_fd, self._target_name)
        held = os.fstat(self._held_source_fd)
        if (
            snapshot.state
            is not LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
            or target is None
            or (target.st_dev, target.st_ino) != (held.st_dev, held.st_ino)
        ):
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)
        return snapshot

    def rename_reverse(self) -> None:
        """Perform the one permitted pre-success reverse no-replace rename."""

        self._require_open()
        if self._reverse_attempted:
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)
        if (
            self.classify().state
            is not LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
        ):
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)
        self._reverse_attempted = True
        self._rename(self._target_name, self._source_name)

    def verify_recovery(self) -> LinuxEbookRenamePhysicalSnapshot:
        """Prove exact original placement after a reverse or reconstructed recovery."""

        self._require_open()
        snapshot = self.classify()
        if (
            snapshot.state
            is not LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        ):
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)
        return snapshot

    def _rename(self, old_name: str, new_name: str) -> None:
        try:
            _renameat2_noreplace(self._parent_fd, old_name, new_name)
        except _SyscallFailure as error:
            if error.error_number == errno.EEXIST:
                _fail(LinuxEbookRenameBackendErrorCode.TARGET_COLLISION)
            unavailable = {
                errno.EXDEV,
                errno.EINVAL,
                errno.ENOSYS,
                errno.EROFS,
                getattr(errno, "EOPNOTSUPP", errno.EINVAL),
            }
            if error.error_number in unavailable:
                _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
            raise LinuxEbookRenameBackendError(
                LinuxEbookRenameBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            ) from None
        try:
            os.fsync(self._parent_fd)
        except OSError:
            raise LinuxEbookRenameBackendError(
                LinuxEbookRenameBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            ) from None

    def _snapshot(
        self,
        state: LinuxEbookRenamePhysicalState,
    ) -> LinuxEbookRenamePhysicalSnapshot:
        return LinuxEbookRenamePhysicalSnapshot(
            state=state,
            confirmation_digest=_confirmation_digest(
                self._run,
                self._preparation,
                state,
            ),
        )

    def _revalidate_environment(self) -> None:
        filesystem_type, identity = _filesystem_identity(
            self._parent_fd,
            self._capability,
        )
        if (
            filesystem_type != self._probe.filesystem_type
            or identity != self._probe.filesystem_identity_fingerprint
            or platform.release() != self._probe.kernel_release
        ):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)

    def _require_open(self) -> None:
        if self._closed:
            _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)


class LinuxEbookRenameBackend:
    """Probe and open sessions for the one ADR-0066 Linux profile."""

    def probe(
        self,
        capability: ResolvedEbookRenameCapability,
        *,
        probed_at: datetime,
    ) -> EbookRenameCapabilityProbeSnapshot:
        """Exercise fixed syscalls using only random exclusive private fixtures."""

        _require_platform()
        if not isinstance(capability, ResolvedEbookRenameCapability):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        _require_disjoint_capability_directories(capability)
        root_fd = _open_absolute_directory(capability.scan_root_directory)
        probe_fd = -1
        try:
            probe_fd = _open_absolute_directory(capability.probe_directory)
            _require_private_probe_directory(probe_fd)
            filesystem_type, identity = _require_supported_same_filesystem(
                root_fd,
                probe_fd,
                capability,
            )
            opened = _openat2_directory(root_fd, ".")
            _close_quietly(opened)
            _probe_noreplace(probe_fd)
            _fsync_directory(root_fd)
            return build_ebook_rename_capability_probe(
                capability,
                filesystem_type=filesystem_type,
                filesystem_identity_fingerprint=identity,
                kernel_release=platform.release(),
                probed_at=probed_at,
                openat2_supported=True,
                renameat2_noreplace_supported=True,
                directory_fsync_supported=True,
                root_probe_same_filesystem=True,
            )
        except LinuxEbookRenameBackendError:
            raise
        except (OSError, TypeError, ValueError):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        finally:
            _close_quietly(probe_fd)
            _close_quietly(root_fd)

    def open_session(
        self,
        *,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        preparation: EbookRenamePreparationSnapshot,
        authorization: EbookRenameAuthorizationSnapshot,
        binding: EbookRenameBackendBinding,
        run: EbookRenameExecutionRun,
        source_relative_locator: str,
        target_relative_locator: str,
    ) -> LinuxEbookRenameSession:
        """Open one same-parent session after all immutable binders agree."""

        _require_platform()
        _require_disjoint_capability_directories(capability)
        _require_bindings(
            capability,
            probe,
            preparation,
            authorization,
            binding,
            run,
            source_relative_locator,
            target_relative_locator,
        )
        parent_parts, source_name, target_name = _bound_locators(
            source_relative_locator,
            target_relative_locator,
            preparation.source_format_label,
        )
        root_fd = _open_absolute_directory(capability.scan_root_directory)
        probe_fd = -1
        parent_fd = -1
        try:
            probe_fd = _open_absolute_directory(capability.probe_directory)
            _require_private_probe_directory(probe_fd)
            filesystem_type, identity = _require_supported_same_filesystem(
                root_fd,
                probe_fd,
                capability,
            )
            if (
                filesystem_type != probe.filesystem_type
                or identity != probe.filesystem_identity_fingerprint
                or platform.release() != probe.kernel_release
            ):
                _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
            relative_parent = "/".join(parent_parts) if parent_parts else "."
            parent_fd = _openat2_directory(root_fd, relative_parent)
            if os.fstat(parent_fd).st_dev != os.fstat(root_fd).st_dev:
                _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
            _fsync_directory(parent_fd)
            session = LinuxEbookRenameSession(
                parent_fd=parent_fd,
                source_name=source_name,
                target_name=target_name,
                capability=capability,
                probe=probe,
                preparation=preparation,
                run=run,
            )
            parent_fd = -1
            return session
        except LinuxEbookRenameBackendError:
            raise
        except (OSError, TypeError, ValueError):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        finally:
            _close_quietly(parent_fd)
            _close_quietly(probe_fd)
            _close_quietly(root_fd)

    def capture_preparation_evidence(
        self,
        *,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        plan: EbookOperationRecipePlan,
        target_historically_absent: bool,
        captured_at: datetime,
    ) -> EbookRenamePhysicalPreparationEvidence:
        """Read one exact source and absent target without accepting raw locators."""

        _require_platform()
        if (
            not isinstance(capability, ResolvedEbookRenameCapability)
            or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
            or not isinstance(plan, EbookOperationRecipePlan)
            or type(target_historically_absent) is not bool
        ):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        try:
            ebook_rename_dependencies_fingerprint(plan)
            source = plan.candidate.sources[0]
            target = plan.candidate.target
        except (IndexError, TypeError, ValueError, RuntimeError):
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        _require_capability_probe(capability, probe, source.scan_root_id)
        _require_disjoint_capability_directories(capability)
        parent_parts, source_name, target_name = _bound_locators(
            source.relative_locator,
            target.relative_locator,
            source.format_label,
        )
        root_fd = _open_absolute_directory(capability.scan_root_directory)
        probe_fd = -1
        parent_fd = -1
        try:
            probe_fd = _open_absolute_directory(capability.probe_directory)
            _require_private_probe_directory(probe_fd)
            filesystem_type, identity = _require_supported_same_filesystem(
                root_fd,
                probe_fd,
                capability,
            )
            if (
                filesystem_type != probe.filesystem_type
                or identity != probe.filesystem_identity_fingerprint
                or platform.release() != probe.kernel_release
            ):
                _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
            relative_parent = "/".join(parent_parts) if parent_parts else "."
            parent_fd = _openat2_directory(root_fd, relative_parent)
            details, digest, xattrs = _read_preparation_source(
                parent_fd,
                source_name,
                expected_size=source.expected_size_bytes,
                expected_sha256=source.expected_full_sha256,
                expected_modified_at=source.expected_modified_at,
            )
            if _named_stat(parent_fd, target_name) is not None:
                _fail(LinuxEbookRenameBackendErrorCode.TARGET_COLLISION)
            return build_ebook_rename_physical_evidence(
                plan,
                source_device=details.st_dev,
                source_inode=details.st_ino,
                source_mode=details.st_mode,
                source_uid=details.st_uid,
                source_gid=details.st_gid,
                source_link_count=details.st_nlink,
                source_size_bytes=details.st_size,
                source_mtime_ns=details.st_mtime_ns,
                source_modified_at=source.expected_modified_at,
                source_full_sha256=digest,
                source_xattr_fingerprint=xattrs,
                target_physically_absent=True,
                target_historically_absent=target_historically_absent,
                captured_at=captured_at,
            )
        except LinuxEbookRenameBackendError:
            raise
        except (OSError, TypeError, ValueError):
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        finally:
            _close_quietly(parent_fd)
            _close_quietly(probe_fd)
            _close_quietly(root_fd)


def ebook_rename_xattr_fingerprint(descriptor: int) -> str:
    """Return the bounded, ordered v1 digest of one already-open file's xattrs."""

    listxattr = getattr(os, "listxattr", None)
    getxattr = getattr(os, "getxattr", None)
    if not callable(listxattr) or not callable(getxattr):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        names = listxattr(descriptor)
    except (OSError, TypeError):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    if not isinstance(names, list) or len(names) > _MAX_XATTR_COUNT:
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    encoded: list[tuple[bytes, bytes]] = []
    total = 0
    try:
        for name in names:
            if not isinstance(name, str):
                _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
            name_bytes = os.fsencode(name)
            if not name_bytes or len(name_bytes) > _MAX_XATTR_NAME_BYTES:
                _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
            value = getxattr(descriptor, name)
            if not isinstance(value, bytes) or len(value) > _MAX_XATTR_VALUE_BYTES:
                _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
            total += len(name_bytes) + len(value)
            if total > _MAX_XATTR_TOTAL_BYTES:
                _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
            encoded.append((name_bytes, value))
    except LinuxEbookRenameBackendError:
        raise
    except (OSError, TypeError, UnicodeError):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    digest = hashlib.sha256(_XATTR_DOMAIN)
    for name_bytes, value in sorted(encoded):
        digest.update(len(name_bytes).to_bytes(4, "big"))
        digest.update(name_bytes)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _require_capability_probe(
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    scan_root_id: object,
) -> None:
    if (
        capability.scan_root_id != scan_root_id
        or capability.ebook_rename_capability_id
        != probe.ebook_rename_capability_id
        or capability.scan_root_id != probe.scan_root_id
        or capability.configuration_fingerprint
        != probe.capability_configuration_fingerprint
        or capability.writer_profile != EBOOK_RENAME_PROCESSOR_PROFILE
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _require_bindings(
    capability: ResolvedEbookRenameCapability,
    probe: EbookRenameCapabilityProbeSnapshot,
    preparation: EbookRenamePreparationSnapshot,
    authorization: EbookRenameAuthorizationSnapshot,
    binding: EbookRenameBackendBinding,
    run: EbookRenameExecutionRun,
    source_locator: str,
    target_locator: str,
) -> None:
    if (
        not isinstance(capability, ResolvedEbookRenameCapability)
        or not isinstance(probe, EbookRenameCapabilityProbeSnapshot)
        or not isinstance(preparation, EbookRenamePreparationSnapshot)
        or not isinstance(authorization, EbookRenameAuthorizationSnapshot)
        or not isinstance(binding, EbookRenameBackendBinding)
        or not isinstance(run, EbookRenameExecutionRun)
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        source_digest = ebook_rename_locator_digest(
            preparation.scan_root_id,
            source_locator,
            target=False,
        )
        target_digest = ebook_rename_locator_digest(
            preparation.scan_root_id,
            target_locator,
            target=True,
        )
    except (TypeError, ValueError):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    if (
        capability.writer_profile != EBOOK_RENAME_PROCESSOR_PROFILE
        or capability.ebook_rename_capability_id
        != preparation.ebook_rename_capability_id
        or capability.scan_root_id != preparation.scan_root_id
        or capability.configuration_fingerprint
        != preparation.capability_configuration_fingerprint
        or probe.id != preparation.probe_id
        or probe.content_hash != preparation.probe_content_hash
        or probe.ebook_rename_capability_id
        != capability.ebook_rename_capability_id
        or probe.scan_root_id != capability.scan_root_id
        or probe.capability_configuration_fingerprint
        != capability.configuration_fingerprint
        or authorization.preparation_id != preparation.id
        or authorization.preparation_content_hash != preparation.content_hash
        or authorization.plan_id != preparation.plan_id
        or authorization.content_hash != run.authorization_content_hash
        or run.authorization_id != authorization.id
        or run.plan_id != preparation.plan_id
        or run.scan_root_id != preparation.scan_root_id
        or run.source_file_id != preparation.source_file_id
        or run.ebook_rename_capability_id
        != capability.ebook_rename_capability_id
        or run.probe_id != probe.id
        or binding.run_id != run.id
        or binding.ebook_rename_capability_id
        != capability.ebook_rename_capability_id
        or binding.capability_configuration_fingerprint
        != capability.configuration_fingerprint
        or binding.probe_id != probe.id
        or binding.probe_content_hash != probe.content_hash
        or binding.backend_profile != EBOOK_RENAME_PROCESSOR_PROFILE
        or preparation.source_locator_digest != source_digest
        or preparation.target_locator_digest != target_digest
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _bound_locators(
    source_locator: str,
    target_locator: str,
    format_label: str,
) -> tuple[tuple[str, ...], str, str]:
    source_parts = _locator_parts(source_locator)
    target_parts = _locator_parts(target_locator)
    source_path = PurePosixPath(source_locator)
    target_path = PurePosixPath(target_locator)
    if (
        source_parts[:-1] != target_parts[:-1]
        or source_parts[-1] == target_parts[-1]
        or source_path.suffix != target_path.suffix
        or source_path.suffix.removeprefix(".").upper() != format_label
    ):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    return source_parts[:-1], source_parts[-1], target_parts[-1]


def _locator_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    try:
        encoded = value.encode("utf-8")
        path = PurePosixPath(value)
        parts = tuple(path.parts)
        oversized = any(len(part.encode("utf-8")) > _MAX_COMPONENT_BYTES for part in parts)
    except (UnicodeError, ValueError):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    if (
        len(encoded) > _MAX_LOCATOR_BYTES
        or path.is_absolute()
        or path.as_posix() != value
        or not parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or oversized
    ):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    return parts


def _require_platform() -> None:
    required_flags = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        getattr(os, "O_CLOEXEC", 0),
    )
    if (
        sys.platform != "linux"
        or platform.machine().lower() not in {"x86_64", "amd64"}
        or any(not isinstance(value, int) or value == 0 for value in required_flags)
        or not callable(getattr(os, "geteuid", None))
        or not callable(getattr(os, "listxattr", None))
        or not callable(getattr(os, "getxattr", None))
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    try:
        confstr = os.confstr
        glibc = confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, OSError, TypeError, ValueError):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    if not isinstance(glibc, str) or not glibc.startswith("glibc "):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    _libc()


def _require_disjoint_capability_directories(
    capability: ResolvedEbookRenameCapability,
) -> None:
    if not isinstance(capability, ResolvedEbookRenameCapability):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    root = capability.scan_root_directory
    probe = capability.probe_directory
    if root == probe or root in probe.parents or probe in root.parents:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_NOFOLLOW", 0))
        | int(getattr(os, "O_CLOEXEC", 0))
    )


def _read_flags() -> int:
    return os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0)) | int(
        getattr(os, "O_CLOEXEC", 0)
    )


def _open_absolute_directory(path: Path) -> int:
    if not isinstance(path, Path) or not path.is_absolute() or not path.anchor:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    descriptor = -1
    try:
        descriptor = os.open("/", _directory_flags())
        for part in path.parts[1:]:
            if part in {"", ".", ".."}:
                _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
            next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            _close_quietly(descriptor)
            descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        return descriptor
    except LinuxEbookRenameBackendError:
        _close_quietly(descriptor)
        raise
    except OSError:
        _close_quietly(descriptor)
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _openat2_directory(root_fd: int, relative_path: str) -> int:
    try:
        return _openat2(root_fd, relative_path, _directory_flags())
    except _SyscallFailure:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _openat2(directory_fd: int, name: str, flags: int) -> int:
    try:
        encoded = os.fsencode(name)
    except (OSError, UnicodeError, ValueError):
        raise _SyscallFailure(errno.EINVAL) from None
    how = _OpenHow(flags=flags, mode=0, resolve=_PARENT_RESOLVE_FLAGS)
    library = _libc()
    ctypes.set_errno(0)
    result = library.syscall(
        ctypes.c_long(_SYS_OPENAT2_X86_64),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(encoded),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        raise _SyscallFailure(ctypes.get_errno())
    return int(result)


def _renameat2_noreplace(directory_fd: int, old_name: str, new_name: str) -> None:
    try:
        encoded_old = os.fsencode(old_name)
        encoded_new = os.fsencode(new_name)
    except (OSError, UnicodeError, ValueError):
        raise _SyscallFailure(errno.EINVAL) from None
    library = _libc()
    ctypes.set_errno(0)
    result = library.syscall(
        ctypes.c_long(_SYS_RENAMEAT2_X86_64),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(encoded_old),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(encoded_new),
        ctypes.c_uint(_RENAME_NOREPLACE),
    )
    if result != 0:
        raise _SyscallFailure(ctypes.get_errno())


def _require_private_probe_directory(descriptor: int) -> None:
    details = os.fstat(descriptor)
    geteuid = getattr(os, "geteuid", None)
    if (
        not callable(geteuid)
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o022
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _require_supported_same_filesystem(
    root_fd: int,
    probe_fd: int,
    capability: ResolvedEbookRenameCapability,
) -> tuple[str, str]:
    root = os.fstat(root_fd)
    probe = os.fstat(probe_fd)
    root_fs = _fstatfs(root_fd)
    probe_fs = _fstatfs(probe_fd)
    filesystem_type, root_identity = _filesystem_identity(root_fd, capability)
    probe_type, probe_identity = _filesystem_identity(probe_fd, capability)
    if (
        root.st_dev != probe.st_dev
        or root_fs.f_type != probe_fs.f_type
        or tuple(root_fs.f_fsid) != tuple(probe_fs.f_fsid)
        or filesystem_type != probe_type
        or root_identity != probe_identity
        or root_fs.f_flags & _ST_RDONLY
        or probe_fs.f_flags & _ST_RDONLY
    ):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    return filesystem_type, root_identity


def _filesystem_identity(
    descriptor: int,
    capability: ResolvedEbookRenameCapability,
) -> tuple[str, str]:
    details = os.fstat(descriptor)
    filesystem = _fstatfs(descriptor)
    if filesystem.f_flags & _ST_RDONLY:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    filesystem_type = _filesystem_type_from_mountinfo(
        details.st_dev,
        int(filesystem.f_type),
    )
    material = {
        "capability_id": str(capability.ebook_rename_capability_id),
        "filesystem_id": [int(filesystem.f_fsid[0]), int(filesystem.f_fsid[1])],
        "filesystem_type": filesystem_type,
        "scan_root_id": str(capability.scan_root_id),
        "st_dev": int(details.st_dev),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("ascii")
    return filesystem_type, hashlib.sha256(_FILESYSTEM_IDENTITY_DOMAIN + encoded).hexdigest()


def _filesystem_type_from_mountinfo(device: int, filesystem_magic: int) -> str:
    expected = _FILESYSTEM_TYPES.get(filesystem_magic)
    if expected is None:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    major = ((device >> 8) & 0xFFF) | ((device >> 32) & ~0xFFF)
    minor = (device & 0xFF) | ((device >> 12) & ~0xFF)
    device_field = f"{major}:{minor}"
    filesystem_types: set[str] = set()
    total_bytes = 0
    line_count = 0
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as source:
            for line in source:
                line_count += 1
                total_bytes += len(line.encode("utf-8"))
                if line_count > 8192 or total_bytes > 2 * 1024 * 1024:
                    _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
                fields = line.rstrip("\n").split(" - ")
                prefix = fields[0].split() if len(fields) == 2 else []
                suffix = fields[1].split() if len(fields) == 2 else []
                if len(prefix) >= 3 and suffix and prefix[2] == device_field:
                    filesystem_types.add(suffix[0])
    except (OSError, UnicodeError):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    if filesystem_types != {expected}:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    return expected


def _probe_noreplace(probe_fd: int) -> None:
    token = uuid4().hex
    source_name = f".foliotone-ebook-rename-{token}-source"
    target_name = f".foliotone-ebook-rename-{token}-target"
    collision_name = f".foliotone-ebook-rename-{token}-collision"
    identities: dict[str, tuple[int, int]] = {}
    failure: Exception | None = None
    try:
        source_fd = _create_probe_file(probe_fd, source_name)
        try:
            source = os.fstat(source_fd)
            identities[source_name] = (source.st_dev, source.st_ino)
            _write_all(source_fd, _PROBE_DATA)
            os.fsync(source_fd)
        finally:
            _close_quietly(source_fd)
        _renameat2_noreplace(probe_fd, source_name, target_name)
        identities[target_name] = identities.pop(source_name)
        _fsync_directory(probe_fd)
        collision_fd = _create_probe_file(probe_fd, collision_name)
        try:
            collision_created = os.fstat(collision_fd)
            identities[collision_name] = (
                collision_created.st_dev,
                collision_created.st_ino,
            )
            os.fsync(collision_fd)
        finally:
            _close_quietly(collision_fd)
        try:
            _renameat2_noreplace(probe_fd, target_name, collision_name)
        except _SyscallFailure as error:
            if error.error_number != errno.EEXIST:
                raise
        else:
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        target = _named_stat(probe_fd, target_name)
        collision = _named_stat(probe_fd, collision_name)
        if (
            target is None
            or collision is None
            or (target.st_dev, target.st_ino) != identities[target_name]
            or (collision.st_dev, collision.st_ino) != identities[collision_name]
            or _read_probe_file(probe_fd, target_name) != _PROBE_DATA
        ):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    except Exception as error:  # Cleanup still uses only bound fixture identities.
        failure = error
    cleanup_ok = True
    for name, identity in tuple(identities.items()):
        details = _named_stat(probe_fd, name)
        if details is None:
            continue
        if (details.st_dev, details.st_ino) != identity:
            cleanup_ok = False
            continue
        try:
            os.unlink(name, dir_fd=probe_fd)
        except OSError:
            cleanup_ok = False
    try:
        _fsync_directory(probe_fd)
    except LinuxEbookRenameBackendError:
        cleanup_ok = False
    if failure is not None or not cleanup_ok:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _create_probe_file(directory_fd: int, name: str) -> int:
    try:
        return os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            0o600,
            dir_fd=directory_fd,
        )
    except OSError:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _read_probe_file(directory_fd: int, name: str) -> bytes:
    descriptor = -1
    try:
        descriptor = _openat2(directory_fd, name, _read_flags())
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        data = os.read(descriptor, len(_PROBE_DATA) + 1)
        if len(data) > len(_PROBE_DATA) or os.read(descriptor, 1):
            _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
        return data
    except LinuxEbookRenameBackendError:
        raise
    except (OSError, _SyscallFailure):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    finally:
        _close_quietly(descriptor)


def _entry_view(
    directory_fd: int,
    name: str,
    preparation: EbookRenamePreparationSnapshot,
) -> _EntryView:
    descriptor = -1
    try:
        descriptor, view = _open_exact_entry(directory_fd, name, preparation)
        return view
    except FileNotFoundError:
        return _EntryView("MISSING")
    except (LinuxEbookRenameBackendError, OSError, _SyscallFailure):
        return _EntryView("OTHER")
    finally:
        _close_quietly(descriptor)


def _read_preparation_source(
    directory_fd: int,
    name: str,
    *,
    expected_size: int,
    expected_sha256: str,
    expected_modified_at: datetime,
) -> tuple[os.stat_result, str, str]:
    named = _named_stat(directory_fd, name)
    if (
        named is None
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or named.st_dev != os.fstat(directory_fd).st_dev
        or named.st_size != expected_size
        or datetime.fromtimestamp(named.st_mtime, tz=UTC) != expected_modified_at
    ):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    descriptor = -1
    try:
        descriptor = _openat2(directory_fd, name, _read_flags())
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        before = _stable_identity(opened)
        size, digest = _hash_file(descriptor, expected_size)
        xattrs = ebook_rename_xattr_fingerprint(descriptor)
        after = os.fstat(descriptor)
        named_after = _named_stat(directory_fd, name)
        if (
            named_after is None
            or before != _stable_identity(after)
            or (named_after.st_dev, named_after.st_ino) != (
                after.st_dev,
                after.st_ino,
            )
            or not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or after.st_size != expected_size
            or size != expected_size
            or digest != expected_sha256
            or datetime.fromtimestamp(after.st_mtime, tz=UTC)
            != expected_modified_at
        ):
            _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
        return after, digest, xattrs
    except LinuxEbookRenameBackendError:
        raise
    except (OSError, _SyscallFailure):
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    finally:
        _close_quietly(descriptor)


def _open_exact_entry(
    directory_fd: int,
    name: str,
    preparation: EbookRenamePreparationSnapshot,
) -> tuple[int, _EntryView]:
    named = _named_stat(directory_fd, name)
    if named is None:
        raise FileNotFoundError
    if not stat.S_ISREG(named.st_mode) or named.st_nlink != 1:
        return -1, _EntryView("OTHER")
    if (
        named.st_dev != preparation.source_device
        or named.st_ino != preparation.source_inode
        or named.st_mode != preparation.source_mode
        or named.st_uid != preparation.source_uid
        or named.st_gid != preparation.source_gid
        or named.st_nlink != preparation.source_link_count
        or named.st_size != preparation.source_size_bytes
        or named.st_mtime_ns != preparation.source_mtime_ns
    ):
        return -1, _EntryView("OTHER")
    descriptor = -1
    try:
        descriptor = _openat2(directory_fd, name, _read_flags())
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            return descriptor, _EntryView("OTHER")
        before = _stable_identity(opened)
        size, digest = _hash_file(descriptor, preparation.source_size_bytes)
        xattrs = ebook_rename_xattr_fingerprint(descriptor)
        after = os.fstat(descriptor)
        exact = (
            before == _stable_identity(after)
            and after.st_dev == preparation.source_device
            and after.st_ino == preparation.source_inode
            and after.st_mode == preparation.source_mode
            and after.st_uid == preparation.source_uid
            and after.st_gid == preparation.source_gid
            and after.st_nlink == preparation.source_link_count == 1
            and size == preparation.source_size_bytes
            and after.st_mtime_ns == preparation.source_mtime_ns
            and digest == preparation.source_full_sha256
            and xattrs == preparation.source_xattr_fingerprint
        )
        return descriptor, _EntryView(
            "EXACT" if exact else "OTHER",
            after.st_dev,
            after.st_ino,
        )
    except Exception:
        _close_quietly(descriptor)
        raise


def _named_stat(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        _fail(LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS)


def _hash_file(descriptor: int, maximum: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            remaining = maximum + 1 - total
            if remaining <= 0:
                break
            block = os.read(descriptor, min(_CHUNK_BYTES, remaining))
            if not block:
                break
            total += len(block)
            digest.update(block)
            if total > maximum:
                break
    except OSError:
        _fail(LinuxEbookRenameBackendErrorCode.SOURCE_STALE)
    return total, digest.hexdigest()


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


def _confirmation_digest(
    run: EbookRenameExecutionRun,
    preparation: EbookRenamePreparationSnapshot,
    state: LinuxEbookRenamePhysicalState,
) -> str:
    payload = "\x00".join(
        (
            str(run.id),
            preparation.content_hash,
            preparation.source_full_sha256,
            state.value,
            EBOOK_RENAME_PROCESSOR_PROFILE,
            EBOOK_RENAME_XATTR_FINGERPRINT_PROFILE,
        )
    ).encode("utf-8")
    return hashlib.sha256(_CONFIRMATION_DOMAIN + payload).hexdigest()


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    try:
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
    except OSError:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _fsync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)


def _fstatfs(descriptor: int) -> _LinuxStatFs:
    value = _LinuxStatFs()
    library = _libc()
    ctypes.set_errno(0)
    if library.fstatfs(ctypes.c_int(descriptor), ctypes.byref(value)) != 0:
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    return value


def _libc() -> Any:
    try:
        library = ctypes.CDLL(None, use_errno=True)
        syscall = library.syscall
        fstatfs = library.fstatfs
    except (AttributeError, OSError):
        _fail(LinuxEbookRenameBackendErrorCode.TOOL_UNAVAILABLE)
    syscall.restype = ctypes.c_long
    fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_LinuxStatFs)]
    fstatfs.restype = ctypes.c_int
    return library


def _close_quietly(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: LinuxEbookRenameBackendErrorCode) -> NoReturn:
    raise LinuxEbookRenameBackendError(code) from None


__all__ = [
    "EBOOK_RENAME_XATTR_FINGERPRINT_PROFILE",
    "LinuxEbookRenameBackend",
    "LinuxEbookRenameBackendError",
    "LinuxEbookRenameBackendErrorCode",
    "LinuxEbookRenamePhysicalSnapshot",
    "LinuxEbookRenamePhysicalState",
    "LinuxEbookRenameSession",
    "ebook_rename_xattr_fingerprint",
]
