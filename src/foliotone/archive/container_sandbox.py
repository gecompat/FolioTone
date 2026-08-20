"""Fail-closed Docker/Linux sandbox for the fixed archive 7-Zip runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, cast

from foliotone.archive.process_runner import (
    ArchiveProcessRunner,
    ArchiveProcessStatus,
    ByteConsumer,
    CancellationProbe,
    ProcessExecutionResult,
)
from foliotone.archive.safety_policy import (
    MAX_CONCURRENT_ARCHIVE_JOBS,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    MAX_VOLUME_COUNT,
)
from foliotone.archive.sevenzip import (
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    archive_7zip_runtime_availability,
    build_7zzs_information_command,
    build_7zzs_integrity_command,
    build_7zzs_listing_command,
)

ARCHIVE_CONTAINER_UID: Final = 65_532
ARCHIVE_CONTAINER_GID: Final = 65_532
ARCHIVE_INPUT_DIRECTORY_MODE: Final = 0o500
ARCHIVE_INPUT_FILE_MODE: Final = 0o400
ARCHIVE_OUTPUT_DIRECTORY_MODE: Final = 0o700
ARCHIVE_CONTAINER_INPUT: Final = "/workspace/input"
ARCHIVE_CONTAINER_OUTPUT: Final = "/workspace/output"
ARCHIVE_CONTAINER_ENVIRONMENT: Final = (
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
)
_CLIENT_ENVIRONMENT: Final = {"PATH": "/usr/bin:/bin"}
_APPROVED_IMAGE_REFERENCE: Final = (
    "ghcr.io/gecompat/foliotone-archive-7zip@"
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)
_CONTAINER_ID_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_NAME_RE: Final = re.compile(r"foliotone-archive-[0-9a-f]{32}\Z")
_STAGING_NAME_RE: Final = re.compile(
    r"archive(?:\.(?:[0-9]{3,6}|r[0-9]{2}|z[0-9]{2}|part[0-9]{1,6}\.rar))?\Z",
    re.IGNORECASE,
)
_OPAQUE_DIRECTORY_RE: Final = re.compile(r"\.archive-[0-9a-f]{32}\Z")
_ALLOWED_COMMANDS: Final = frozenset(
    {
        build_7zzs_information_command(),
        build_7zzs_listing_command(),
        build_7zzs_integrity_command(),
    }
)
_COMMAND_TIMEOUTS: Final = {
    build_7zzs_information_command(): 60.0,
    build_7zzs_listing_command(): 60.0,
    build_7zzs_integrity_command(): 300.0,
}
_ACTIVE_ARCHIVE_JOBS: Final = threading.BoundedSemaphore(MAX_CONCURRENT_ARCHIVE_JOBS)
_O_NOFOLLOW: Final = cast(int, getattr(os, "O_NOFOLLOW", 0))
_O_DIRECTORY: Final = cast(int, getattr(os, "O_DIRECTORY", 0))
_OS_CHOWN: Final = cast(Callable[..., None] | None, getattr(os, "chown", None))
_OS_FCHMOD: Final = cast(Callable[[int, int], None] | None, getattr(os, "fchmod", None))
_OS_LISTXATTR: Final = cast(
    Callable[..., list[str]] | None, getattr(os, "listxattr", None)
)


class ArchiveContainerRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_FAILED = "TOOL_FAILED"
    POLICY_REJECTED = "POLICY_REJECTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ArchiveVolumeSource:
    """Validated source evidence plus a non-private sandbox basename."""

    path: Path = field(repr=False)
    size_bytes: int
    full_sha256: str
    staging_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("source path must be absolute")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("source size must be a non-negative integer")
        if re.fullmatch(r"[0-9a-f]{64}", self.full_sha256) is None:
            raise ValueError("source full_sha256 must be lowercase SHA-256")
        if _STAGING_NAME_RE.fullmatch(self.staging_name) is None:
            raise ValueError("staging_name must use the opaque archive volume grammar")


@dataclass(frozen=True, slots=True)
class ArchiveContainerRequest:
    volumes: tuple[ArchiveVolumeSource, ...]
    command: tuple[str, ...]
    scan_roots: tuple[Path, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.volumes, tuple)
            or not 1 <= len(self.volumes) <= MAX_VOLUME_COUNT
            or any(not isinstance(item, ArchiveVolumeSource) for item in self.volumes)
        ):
            raise ValueError("volumes must contain one bounded validated volume group")
        names = [item.staging_name for item in self.volumes]
        if len(names) != len(set(name.casefold() for name in names)) or names.count("archive") != 1:
            raise ValueError("volume staging names must be unique and include archive")
        if self.command not in _ALLOWED_COMMANDS:
            raise ValueError("command must be one fixed archive 7zzs shape")
        if (
            not isinstance(self.scan_roots, tuple)
            or not self.scan_roots
            or any(not isinstance(root, Path) or not root.is_absolute() for root in self.scan_roots)
        ):
            raise ValueError("scan_roots must contain at least one absolute path")


@dataclass(frozen=True, slots=True)
class ArchiveRuntimePreflightInputs:
    lock_path: Path = field(repr=False)
    release_path: Path = field(repr=False)
    revocations_path: Path = field(repr=False)
    evidence_directory: Path = field(repr=False)
    local_state_root: Path = field(repr=False)
    private_state_parent: Path = field(repr=False)
    oci_layout_path: Path = field(repr=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, Path) or not value.is_absolute()
            for value in (
                self.lock_path,
                self.release_path,
                self.revocations_path,
                self.evidence_directory,
                self.local_state_root,
                self.private_state_parent,
                self.oci_layout_path,
            )
        ):
            raise ValueError("runtime preflight paths must be absolute")


@dataclass(frozen=True, slots=True)
class ArchiveContainerRunResult:
    profile: str
    status: ArchiveContainerRunStatus
    exit_code: int | None = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE:
            raise ValueError("unsupported archive container runner profile")
        if not isinstance(self.status, ArchiveContainerRunStatus):
            raise ValueError("status must be ArchiveContainerRunStatus")
        if self.status is ArchiveContainerRunStatus.COMPLETED and self.exit_code != 0:
            raise ValueError("completed container run requires exit code zero")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("exit_code must be an integer or None")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.stdout_bytes, self.stderr_bytes)
        ):
            raise ValueError("stream byte counts must be non-negative")


@dataclass(frozen=True, slots=True)
class StagedArchiveSandbox:
    temp_root: Path = field(repr=False)
    root: Path = field(repr=False)
    input_root: Path = field(repr=False)
    output_root: Path = field(repr=False)


class SandboxFilesystem(Protocol):
    @property
    def supports_linux_sandbox(self) -> bool: ...

    def stage(
        self,
        temp_root: Path,
        volumes: tuple[ArchiveVolumeSource, ...],
        scan_roots: tuple[Path, ...],
    ) -> StagedArchiveSandbox: ...

    def verify_before_start(self, sandbox: StagedArchiveSandbox) -> bool: ...

    def verify_after_run(self, sandbox: StagedArchiveSandbox) -> bool: ...

    def cleanup(self, sandbox: StagedArchiveSandbox) -> bool: ...


class DockerSandboxBackend(Protocol):
    @property
    def executable(self) -> str: ...

    def create_container(self, argv: tuple[str, ...]) -> str | None: ...

    def inspect_container(self, container_id: str) -> Mapping[str, Any] | None: ...

    def start_argv(self, container_id: str) -> tuple[str, ...]: ...

    def kill_container(self, container_id: str) -> bool: ...

    def remove_container(self, container_id: str) -> bool: ...

    def container_exists(self, container_id: str) -> bool | None: ...


class ArchiveLinuxContainerRunner:
    """Run one fixed archive command after staging and Docker preflight."""

    def __init__(
        self,
        *,
        temp_root: Path,
        runtime_preflight: ArchiveRuntimePreflightInputs,
        filesystem: SandboxFilesystem,
        docker: DockerSandboxBackend,
        process_runner: ArchiveProcessRunner,
    ) -> None:
        if not temp_root.is_absolute():
            raise ValueError("runner paths must be absolute")
        self._temp_root = temp_root
        self._runtime_preflight = runtime_preflight
        self._filesystem = filesystem
        self._docker = docker
        self._process_runner = process_runner
        self._single_job = threading.Lock()

    def run(
        self,
        request: ArchiveContainerRequest,
        *,
        stdout_consumer: ByteConsumer,
        stderr_classifier: ByteConsumer,
        cancellation: CancellationProbe | None = None,
    ) -> ArchiveContainerRunResult:
        if not isinstance(request, ArchiveContainerRequest):
            raise ValueError("request must be ArchiveContainerRequest")
        if not self._filesystem.supports_linux_sandbox:
            return _result(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
        if not self._single_job.acquire(blocking=False):
            return _result(ArchiveContainerRunStatus.POLICY_REJECTED)
        if not _ACTIVE_ARCHIVE_JOBS.acquire(blocking=False):
            self._single_job.release()
            return _result(ArchiveContainerRunStatus.POLICY_REJECTED)
        try:
            return self._run_locked(
                request,
                stdout_consumer=stdout_consumer,
                stderr_classifier=stderr_classifier,
                cancellation=cancellation,
            )
        finally:
            _ACTIVE_ARCHIVE_JOBS.release()
            self._single_job.release()

    def _run_locked(
        self,
        request: ArchiveContainerRequest,
        *,
        stdout_consumer: ByteConsumer,
        stderr_classifier: ByteConsumer,
        cancellation: CancellationProbe | None,
    ) -> ArchiveContainerRunResult:
        inputs = self._runtime_preflight
        try:
            if cancellation is not None and cancellation.is_set():
                return _result(ArchiveContainerRunStatus.CANCELLED)
            availability = archive_7zip_runtime_availability(
                inputs.lock_path,
                release_path=inputs.release_path,
                revocations_path=inputs.revocations_path,
                evidence_directory=inputs.evidence_directory,
                local_state_root=inputs.local_state_root,
                private_state_parent=inputs.private_state_parent,
                scan_roots=request.scan_roots,
                oci_layout_path=inputs.oci_layout_path,
            )
        except Exception:
            return _result(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
        if (
            not availability.available
            or availability.image_reference is None
            or not _is_approved_image_reference(availability.image_reference)
        ):
            return _result(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
        image_reference = availability.image_reference

        sandbox: StagedArchiveSandbox | None = None
        container_id: str | None = None
        create_attempted = False
        process_result: ProcessExecutionResult | None = None
        start_attempted = False
        lifecycle_status = ArchiveContainerRunStatus.TOOL_FAILED
        container_name = f"foliotone-archive-{secrets.token_hex(16)}"
        try:
            try:
                sandbox = self._filesystem.stage(
                    self._temp_root, request.volumes, request.scan_roots
                )
            except _StagingCleanupRequired as error:
                sandbox = error.sandbox
                raise _LifecycleAbort(ArchiveContainerRunStatus.TOOL_FAILED) from None
            if cancellation is not None and cancellation.is_set():
                raise _LifecycleAbort(ArchiveContainerRunStatus.CANCELLED)
            if not self._filesystem.verify_before_start(sandbox):
                raise _LifecycleAbort(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
            create_argv = _build_docker_create_argv(
                self._docker,
                container_name=container_name,
                image_reference=image_reference,
                command=request.command,
                input_root=sandbox.input_root,
                output_root=sandbox.output_root,
            )
            create_attempted = True
            container_id = self._docker.create_container(create_argv)
            if container_id is None:
                raise _LifecycleAbort(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
            inspection = self._docker.inspect_container(container_id)
            if inspection is None or not verify_container_projection(
                inspection,
                container_id=container_id,
                container_name=container_name,
                image_reference=image_reference,
                command=request.command,
                input_root=sandbox.input_root,
                output_root=sandbox.output_root,
            ):
                raise _LifecycleAbort(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
            if not self._filesystem.verify_before_start(sandbox):
                raise _LifecycleAbort(ArchiveContainerRunStatus.TOOL_UNAVAILABLE)
            if cancellation is not None and cancellation.is_set():
                raise _LifecycleAbort(ArchiveContainerRunStatus.CANCELLED)
            start_attempted = True
            process_result = self._process_runner.run(
                self._docker.start_argv(container_id),
                environment=_CLIENT_ENVIRONMENT,
                timeout_seconds=_COMMAND_TIMEOUTS[request.command],
                max_stdout_bytes=MAX_STDOUT_BYTES,
                max_stderr_bytes=MAX_STDERR_BYTES,
                stdout_consumer=stdout_consumer,
                stderr_consumer=stderr_classifier,
                cancellation=cancellation,
            )
            lifecycle_status = _map_process_status(process_result.status)
        except _LifecycleAbort as error:
            lifecycle_status = error.status
        except Exception:
            lifecycle_status = ArchiveContainerRunStatus.TOOL_FAILED
        finally:
            cleanup_ok = True
            container_target = (
                container_id
                if container_id is not None
                else container_name if create_attempted else None
            )
            container_absent = container_target is None
            if container_target is not None:
                needs_kill = (start_attempted and process_result is None) or (
                    process_result is not None
                    and process_result.status
                    in {
                        ArchiveProcessStatus.TIMED_OUT,
                        ArchiveProcessStatus.CANCELLED,
                        ArchiveProcessStatus.LIMIT_EXCEEDED,
                        ArchiveProcessStatus.CONSUMER_REJECTED,
                    }
                )
                if needs_kill and not _bounded_cleanup_call(
                    lambda: self._docker.kill_container(container_target)
                ):
                    cleanup_ok = False
                _bounded_cleanup_call(
                    lambda: self._docker.remove_container(container_target)
                )
                container_absent = _container_absence_proven(
                    self._docker, container_target
                )
                if not container_absent:
                    cleanup_ok = False
            if sandbox is not None:
                if not _bounded_cleanup_call(
                    lambda: self._filesystem.verify_after_run(sandbox)
                ):
                    cleanup_ok = False
                if container_absent:
                    if not _bounded_cleanup_call(lambda: self._filesystem.cleanup(sandbox)):
                        cleanup_ok = False
                else:
                    cleanup_ok = False
            if not cleanup_ok:
                lifecycle_status = ArchiveContainerRunStatus.TOOL_FAILED

        if process_result is None:
            return _result(lifecycle_status)
        return _result(
            lifecycle_status,
            exit_code=process_result.exit_code,
            stdout_bytes=process_result.stdout_bytes,
            stderr_bytes=process_result.stderr_bytes,
        )


def _build_docker_create_argv(
    docker: DockerSandboxBackend,
    *,
    container_name: str,
    image_reference: str,
    command: tuple[str, ...],
    input_root: Path,
    output_root: Path,
) -> tuple[str, ...]:
    """Build the sole Docker create shape accepted by the v1 backend."""

    if (
        command not in _ALLOWED_COMMANDS
        or not _is_approved_image_reference(image_reference)
    ):
        raise ValueError("unapproved image or archive command")
    if _CONTAINER_NAME_RE.fullmatch(container_name) is None:
        raise ValueError("container name must be opaque")
    if any(not path.is_absolute() or "," in os.fspath(path) for path in (input_root, output_root)):
        raise ValueError("mount roots must be absolute and unambiguous")
    executable = docker.executable
    return (
        executable,
        "create",
        "--name",
        container_name,
        "--pull=never",
        "--platform",
        "linux/amd64",
        "--log-driver=none",
        "--user",
        "65532:65532",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--security-opt",
        "seccomp=builtin",
        "--pids-limit",
        "16",
        "--memory",
        "1g",
        "--memory-swap",
        "1g",
        "--cpus",
        "1.0",
        "--env",
        ARCHIVE_CONTAINER_ENVIRONMENT[0],
        "--mount",
        f"type=bind,source={input_root},target={ARCHIVE_CONTAINER_INPUT},readonly,bind-propagation=rprivate",
        "--mount",
        f"type=bind,source={output_root},target={ARCHIVE_CONTAINER_OUTPUT},bind-propagation=rprivate",
        image_reference,
        *command[1:],
    )


def _is_approved_image_reference(image_reference: str) -> bool:
    return image_reference == _APPROVED_IMAGE_REFERENCE


def _bounded_cleanup_call(action: Callable[[], bool]) -> bool:
    try:
        return action() is True
    except Exception:
        return False


def _container_absence_proven(
    docker: DockerSandboxBackend, container_id: str
) -> bool:
    try:
        return docker.container_exists(container_id) is False
    except Exception:
        return False


def verify_container_projection(
    inspection: Mapping[str, Any],
    *,
    container_id: str,
    container_name: str,
    image_reference: str,
    command: tuple[str, ...],
    input_root: Path,
    output_root: Path,
) -> bool:
    """Revalidate every security-relevant property projected by Docker."""

    try:
        if (
            _CONTAINER_ID_RE.fullmatch(container_id) is None
            or _CONTAINER_NAME_RE.fullmatch(container_name) is None
            or inspection.get("Id") != container_id
            or inspection.get("Name") != f"/{container_name}"
        ):
            return False
        config = _mapping(inspection["Config"])
        host = _mapping(inspection["HostConfig"])
        mounts = cast(Sequence[object], inspection["Mounts"])
        if inspection.get("Platform") != "linux":
            return False
        if config.get("Image") != image_reference:
            return False
        if config.get("User") != "65532:65532":
            return False
        if config.get("Entrypoint") != ["/usr/local/bin/7zzs"]:
            return False
        if config.get("WorkingDir") != "/workspace":
            return False
        if config.get("Env") != list(ARCHIVE_CONTAINER_ENVIRONMENT):
            return False
        if config.get("Labels") != {
            "org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"
        }:
            return False
        if config.get("Volumes") not in (None, {}):
            return False
        if config.get("Cmd") != list(command[1:]):
            return False
        if host.get("Privileged") is not False or host.get("ReadonlyRootfs") is not True:
            return False
        if host.get("NetworkMode") != "none":
            return False
        if host.get("LogConfig") != {"Type": "none", "Config": {}}:
            return False
        if host.get("CapAdd") not in (None, []) or host.get("CapDrop") != ["ALL"]:
            return False
        security_options = cast(Sequence[str], host.get("SecurityOpt", []))
        if len(security_options) != 2 or set(security_options) != {
            "no-new-privileges=true",
            "seccomp=builtin",
        }:
            return False
        if (
            host.get("Devices") not in (None, [])
            or host.get("DeviceRequests") not in (None, [])
            or host.get("DeviceCgroupRules") not in (None, [])
        ):
            return False
        if host.get("PidsLimit") != 16:
            return False
        if host.get("Memory") != 1_073_741_824 or host.get("MemorySwap") != 1_073_741_824:
            return False
        if host.get("NanoCpus") != 1_000_000_000:
            return False
        if (
            host.get("Binds") not in (None, [])
            or host.get("Tmpfs") not in (None, {})
            or host.get("VolumesFrom") not in (None, [])
            or host.get("Links") not in (None, [])
            or host.get("PortBindings") not in (None, {})
            or host.get("PublishAllPorts") is not False
            or host.get("AutoRemove") is not False
        ):
            return False
        if not isinstance(mounts, list) or len(mounts) != 2:
            return False
        expected = {
            ARCHIVE_CONTAINER_INPUT: (os.fspath(input_root), False),
            ARCHIVE_CONTAINER_OUTPUT: (os.fspath(output_root), True),
        }
        observed: dict[str, tuple[str, bool]] = {}
        for item in mounts:
            mount = _mapping(item)
            if mount.get("Type") != "bind" or mount.get("Propagation") != "rprivate":
                return False
            destination = mount.get("Destination")
            source = mount.get("Source")
            writable = mount.get("RW")
            if (
                not isinstance(destination, str)
                or not isinstance(source, str)
                or not isinstance(writable, bool)
            ):
                return False
            observed[destination] = (source, writable)
        return observed == expected
    except (KeyError, TypeError, ValueError):
        return False


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("capture limit must be non-negative")
        self._limit = limit
        self._payload = bytearray()

    def consume(self, chunk: bytes) -> bool:
        if len(self._payload) + len(chunk) > self._limit:
            return False
        self._payload.extend(chunk)
        return True

    def payload(self) -> bytes:
        return bytes(self._payload)


def _discard_classified_stderr(_chunk: bytes) -> bool:
    return True


class DockerCliSandboxBackend:
    """Minimal bounded local-Docker control plane; it never pulls an image."""

    def __init__(self, executable: Path, process_runner: ArchiveProcessRunner) -> None:
        if not executable.is_absolute():
            raise ValueError("Docker executable must be absolute")
        self._executable = os.fspath(executable)
        self._process_runner = process_runner

    @property
    def executable(self) -> str:
        return self._executable

    @classmethod
    def discover(
        cls, process_runner: ArchiveProcessRunner
    ) -> DockerCliSandboxBackend | None:
        if sys.platform != "linux":
            return None
        executable = shutil.which("docker", path=_CLIENT_ENVIRONMENT["PATH"])
        return None if executable is None else cls(Path(executable), process_runner)

    def create_container(self, argv: tuple[str, ...]) -> str | None:
        if not argv or argv[0] != self._executable:
            return None
        payload = self._control(argv[1:], max_stdout=4_096)
        if payload is None:
            return None
        try:
            container_id = payload.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError:
            return None
        return container_id if _CONTAINER_ID_RE.fullmatch(container_id) is not None else None

    def inspect_container(self, container_id: str) -> Mapping[str, Any] | None:
        if _CONTAINER_ID_RE.fullmatch(container_id) is None:
            return None
        payload = self._control(("container", "inspect", container_id), max_stdout=262_144)
        if payload is None:
            return None
        try:
            values = json.loads(payload)
            if not isinstance(values, list) or len(values) != 1:
                return None
            return _mapping(values[0])
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def start_argv(self, container_id: str) -> tuple[str, ...]:
        if container_id and _CONTAINER_ID_RE.fullmatch(container_id) is None:
            raise ValueError("invalid opaque container id")
        return (self._executable, "start", "--attach", container_id)

    def kill_container(self, container_id: str) -> bool:
        if not _valid_container_target(container_id):
            return False
        return self._control(("container", "kill", container_id), max_stdout=4_096) is not None

    def remove_container(self, container_id: str) -> bool:
        if not _valid_container_target(container_id):
            return False
        return (
            self._control(("container", "rm", "--force", container_id), max_stdout=4_096)
            is not None
        )

    def container_exists(self, container_id: str) -> bool | None:
        if not _valid_container_target(container_id):
            return None
        inspected = self._control_result(
            ("container", "inspect", "--format", "{{.Id}}", container_id),
            max_stdout=128,
        )
        if inspected.status is ArchiveProcessStatus.SUCCEEDED:
            return True
        daemon = self._control_result(
            ("version", "--format", "{{.Server.Version}}"), max_stdout=256
        )
        if (
            inspected.status is ArchiveProcessStatus.FAILED
            and inspected.exit_code == 1
            and daemon.status is ArchiveProcessStatus.SUCCEEDED
        ):
            return False
        return None

    def _control(self, argv: tuple[str, ...], *, max_stdout: int) -> bytes | None:
        capture = _BoundedCapture(max_stdout)
        result = self._control_result(argv, max_stdout=max_stdout, capture=capture)
        if result.status is not ArchiveProcessStatus.SUCCEEDED:
            return None
        return capture.payload()

    def _control_result(
        self,
        argv: tuple[str, ...],
        *,
        max_stdout: int,
        capture: _BoundedCapture | None = None,
    ) -> ProcessExecutionResult:
        consumer = capture or _BoundedCapture(max_stdout)
        return self._process_runner.run(
            (self._executable, *argv),
            environment=_CLIENT_ENVIRONMENT,
            timeout_seconds=30.0,
            max_stdout_bytes=max_stdout,
            max_stderr_bytes=65_536,
            stdout_consumer=consumer.consume,
            stderr_consumer=_discard_classified_stderr,
        )


class LocalSandboxFilesystem:
    """Linux no-follow staging implementation with explicit ACL closure."""

    @property
    def supports_linux_sandbox(self) -> bool:
        return (
            sys.platform == "linux"
            and _O_NOFOLLOW != 0
            and _O_DIRECTORY != 0
            and _OS_CHOWN is not None
            and _OS_FCHMOD is not None
            and _OS_LISTXATTR is not None
        )

    def stage(
        self,
        temp_root: Path,
        volumes: tuple[ArchiveVolumeSource, ...],
        scan_roots: tuple[Path, ...],
    ) -> StagedArchiveSandbox:
        if not self.supports_linux_sandbox:
            raise _SandboxClosed
        _verify_private_temp_root(temp_root)
        for scan_root in scan_roots:
            _verify_path_chain_no_follow(scan_root, final_directory=True)
            if _paths_overlap(temp_root, scan_root):
                raise _SandboxClosed
        if any(not _path_is_within_scan_root(volume.path, scan_roots) for volume in volumes):
            raise _SandboxClosed
        root = temp_root / f".archive-{secrets.token_hex(16)}"
        input_root = root / "input"
        output_root = root / "output"
        try:
            os.mkdir(root, 0o700)
            os.mkdir(input_root, 0o700)
            os.mkdir(output_root, ARCHIVE_OUTPUT_DIRECTORY_MODE)
            _set_identity(output_root, ARCHIVE_OUTPUT_DIRECTORY_MODE)
            for volume in volumes:
                _copy_and_verify_volume(volume, input_root / volume.staging_name)
            _set_identity(input_root, ARCHIVE_INPUT_DIRECTORY_MODE)
            sandbox = StagedArchiveSandbox(temp_root, root, input_root, output_root)
            if not self.verify_before_start(sandbox):
                raise _SandboxClosed
            return sandbox
        except Exception as error:
            sandbox = StagedArchiveSandbox(temp_root, root, input_root, output_root)
            if not self.cleanup(sandbox):
                raise _StagingCleanupRequired(sandbox) from error
            raise _SandboxClosed from error

    def verify_before_start(self, sandbox: StagedArchiveSandbox) -> bool:
        try:
            _verify_opaque_sandbox(sandbox)
            _verify_owned_directory(
                sandbox.input_root,
                ARCHIVE_INPUT_DIRECTORY_MODE,
                ARCHIVE_CONTAINER_UID,
                ARCHIVE_CONTAINER_GID,
            )
            _verify_owned_directory(
                sandbox.output_root,
                ARCHIVE_OUTPUT_DIRECTORY_MODE,
                ARCHIVE_CONTAINER_UID,
                ARCHIVE_CONTAINER_GID,
            )
            with os.scandir(sandbox.output_root) as output_entries:
                if next(output_entries, None) is not None:
                    return False
            with os.scandir(sandbox.input_root) as entries:
                for entry in entries:
                    if not entry.is_file(follow_symlinks=False):
                        return False
                    _verify_owned_file(
                        Path(entry.path),
                        ARCHIVE_INPUT_FILE_MODE,
                        ARCHIVE_CONTAINER_UID,
                        ARCHIVE_CONTAINER_GID,
                    )
            return True
        except (OSError, _SandboxClosed):
            return False

    def verify_after_run(self, sandbox: StagedArchiveSandbox) -> bool:
        try:
            return self.verify_before_start(sandbox)
        except (OSError, _SandboxClosed):
            return False

    def cleanup(self, sandbox: StagedArchiveSandbox) -> bool:
        try:
            if sandbox.root.parent != sandbox.temp_root:
                return False
            if _OPAQUE_DIRECTORY_RE.fullmatch(sandbox.root.name) is None:
                return False
            if not os.path.lexists(sandbox.root):
                return True
            _remove_tree_no_follow(sandbox.root)
            return not os.path.lexists(sandbox.root)
        except (OSError, _SandboxClosed):
            return False


class _SandboxClosed(Exception):
    def __str__(self) -> str:
        return "archive sandbox preflight rejected"


class _StagingCleanupRequired(Exception):
    def __init__(self, sandbox: StagedArchiveSandbox) -> None:
        self.sandbox = sandbox
        super().__init__("archive staging cleanup required")


class _LifecycleAbort(Exception):
    def __init__(self, status: ArchiveContainerRunStatus) -> None:
        self.status = status
        super().__init__("archive container lifecycle rejected")


def _copy_and_verify_volume(volume: ArchiveVolumeSource, destination: Path) -> None:
    before = _verified_source_stat(volume)
    source_hash = hashlib.sha256()
    source_fd = os.open(volume.path, os.O_RDONLY | _O_NOFOLLOW)
    destination_fd: int | None = None
    copied = 0
    try:
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
            ARCHIVE_INPUT_FILE_MODE,
        )
        opened = os.fstat(source_fd)
        if _stat_identity(opened) != _stat_identity(before):
            raise _SandboxClosed
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            source_hash.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise _SandboxClosed
                view = view[written:]
        os.fsync(destination_fd)
        if _stat_identity(os.fstat(source_fd)) != _stat_identity(before):
            raise _SandboxClosed
    finally:
        os.close(source_fd)
        if destination_fd is not None:
            os.close(destination_fd)
    if copied != volume.size_bytes or source_hash.hexdigest() != volume.full_sha256:
        raise _SandboxClosed
    after = _verified_source_stat(volume)
    if _stat_identity(after) != _stat_identity(before):
        raise _SandboxClosed
    if _sha256_file_no_follow(volume.path) != volume.full_sha256:
        raise _SandboxClosed
    if _sha256_file_no_follow(destination) != volume.full_sha256:
        raise _SandboxClosed
    if not _files_equal_no_follow(volume.path, destination):
        raise _SandboxClosed
    _set_identity(destination, ARCHIVE_INPUT_FILE_MODE)


def _verified_source_stat(volume: ArchiveVolumeSource) -> os.stat_result:
    _verify_path_chain_no_follow(volume.path, final_directory=False)
    value = os.lstat(volume.path)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_size != volume.size_bytes
        or _is_reparse(value)
    ):
        raise _SandboxClosed
    return value


def _sha256_file_no_follow(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _files_equal_no_follow(left: Path, right: Path) -> bool:
    left_fd = os.open(left, os.O_RDONLY | _O_NOFOLLOW)
    right_fd = os.open(right, os.O_RDONLY | _O_NOFOLLOW)
    try:
        while True:
            left_chunk = os.read(left_fd, 1024 * 1024)
            right_chunk = os.read(right_fd, 1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True
    finally:
        os.close(left_fd)
        os.close(right_fd)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _set_identity(path: Path, mode: int) -> None:
    if _OS_CHOWN is None or _OS_LISTXATTR is None:
        raise _SandboxClosed
    _OS_CHOWN(path, ARCHIVE_CONTAINER_UID, ARCHIVE_CONTAINER_GID, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)
    if _OS_LISTXATTR(path, follow_symlinks=False):
        raise _SandboxClosed


def _verify_opaque_sandbox(sandbox: StagedArchiveSandbox) -> None:
    if (
        _OPAQUE_DIRECTORY_RE.fullmatch(sandbox.root.name) is None
        or sandbox.root.parent != sandbox.temp_root
        or sandbox.input_root != sandbox.root / "input"
        or sandbox.output_root != sandbox.root / "output"
    ):
        raise _SandboxClosed
    _verify_private_temp_root(sandbox.temp_root)
    _verify_directory_no_follow(sandbox.root)
    _verify_directory_no_follow(sandbox.input_root)
    _verify_directory_no_follow(sandbox.output_root)


def _verify_directory_no_follow(path: Path) -> None:
    value = os.lstat(path)
    if not stat.S_ISDIR(value.st_mode) or _is_reparse(value):
        raise _SandboxClosed


def _verify_private_temp_root(path: Path) -> None:
    if _OS_LISTXATTR is None:
        raise _SandboxClosed
    value = os.lstat(path)
    geteuid = getattr(os, "geteuid", None)
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o700
        or not callable(geteuid)
        or value.st_uid != geteuid()
        or _is_reparse(value)
        or _OS_LISTXATTR(path, follow_symlinks=False)
        or path.resolve(strict=True) != path
    ):
        raise _SandboxClosed


def _verify_path_chain_no_follow(path: Path, *, final_directory: bool) -> None:
    if not path.is_absolute() or not path.anchor:
        raise _SandboxClosed
    current = Path(path.anchor)
    parts = path.parts[1:]
    if not parts:
        raise _SandboxClosed
    for index, part in enumerate(parts):
        current /= part
        value = os.lstat(current)
        is_final = index == len(parts) - 1
        if stat.S_ISLNK(value.st_mode) or _is_reparse(value):
            raise _SandboxClosed
        if (not is_final or final_directory) and not stat.S_ISDIR(value.st_mode):
            raise _SandboxClosed


def _verify_owned_directory(path: Path, mode: int, uid: int, gid: int) -> None:
    if _OS_LISTXATTR is None:
        raise _SandboxClosed
    value = os.lstat(path)
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_IMODE(value.st_mode) != mode
        or value.st_uid != uid
        or value.st_gid != gid
        or _is_reparse(value)
        or _OS_LISTXATTR(path, follow_symlinks=False)
    ):
        raise _SandboxClosed


def _verify_owned_file(path: Path, mode: int, uid: int, gid: int) -> None:
    if _OS_LISTXATTR is None:
        raise _SandboxClosed
    value = os.lstat(path)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != mode
        or value.st_uid != uid
        or value.st_gid != gid
        or _is_reparse(value)
        or _OS_LISTXATTR(path, follow_symlinks=False)
    ):
        raise _SandboxClosed


def _verify_tree_no_links(root: Path) -> None:
    _verify_directory_no_follow(root)
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                value = entry.stat(follow_symlinks=False)
                if _is_reparse(value) or stat.S_ISLNK(value.st_mode):
                    raise _SandboxClosed
                if stat.S_ISDIR(value.st_mode):
                    pending.append(Path(entry.path))
                elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                    raise _SandboxClosed


def _remove_tree_no_follow(root: Path) -> None:
    value = os.lstat(root)
    if stat.S_ISLNK(value.st_mode) or _is_reparse(value):
        os.unlink(root)
        return
    if not stat.S_ISDIR(value.st_mode):
        os.unlink(root)
        return
    try:
        descriptor = os.open(root, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except OSError:
        value = os.lstat(root)
        if stat.S_ISLNK(value.st_mode) or _is_reparse(value) or not stat.S_ISDIR(
            value.st_mode
        ):
            os.unlink(root)
            return
        raise
    try:
        _empty_directory_fd_no_follow(descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(root)


def _empty_directory_fd_no_follow(directory_fd: int) -> None:
    if _OS_FCHMOD is None:
        raise _SandboxClosed
    _OS_FCHMOD(directory_fd, 0o700)
    with os.scandir(directory_fd) as entries:
        names = [entry.name for entry in entries]
    for name in names:
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(value.st_mode) and not _is_reparse(value):
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
            except OSError:
                value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    stat.S_ISLNK(value.st_mode)
                    or _is_reparse(value)
                    or not stat.S_ISDIR(value.st_mode)
                ):
                    os.unlink(name, dir_fd=directory_fd)
                    continue
                raise
            try:
                _empty_directory_fd_no_follow(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        left_resolved = left.resolve(strict=True)
        right_resolved = right.resolve(strict=True)
    except OSError as error:
        raise _SandboxClosed from error
    return (
        left_resolved == right_resolved
        or left_resolved in right_resolved.parents
        or right_resolved in left_resolved.parents
    )


def _path_is_within_scan_root(path: Path, scan_roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.resolve(strict=True)
        return any(
            resolved == root.resolve(strict=True)
            or resolved.is_relative_to(root.resolve(strict=True))
            for root in scan_roots
        )
    except OSError as error:
        raise _SandboxClosed from error


def _is_reparse(value: os.stat_result) -> bool:
    attributes = getattr(value, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return cast(Mapping[str, Any], value)


def _valid_container_target(value: str) -> bool:
    return (
        _CONTAINER_ID_RE.fullmatch(value) is not None
        or _CONTAINER_NAME_RE.fullmatch(value) is not None
    )


def _map_process_status(status: ArchiveProcessStatus) -> ArchiveContainerRunStatus:
    return {
        ArchiveProcessStatus.SUCCEEDED: ArchiveContainerRunStatus.COMPLETED,
        ArchiveProcessStatus.FAILED: ArchiveContainerRunStatus.TOOL_FAILED,
        ArchiveProcessStatus.TIMED_OUT: ArchiveContainerRunStatus.TIMED_OUT,
        ArchiveProcessStatus.CANCELLED: ArchiveContainerRunStatus.CANCELLED,
        ArchiveProcessStatus.LIMIT_EXCEEDED: ArchiveContainerRunStatus.LIMIT_EXCEEDED,
        ArchiveProcessStatus.CONSUMER_REJECTED: ArchiveContainerRunStatus.POLICY_REJECTED,
    }[status]


def _result(
    status: ArchiveContainerRunStatus,
    *,
    exit_code: int | None = None,
    stdout_bytes: int = 0,
    stderr_bytes: int = 0,
) -> ArchiveContainerRunResult:
    return ArchiveContainerRunResult(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        status,
        exit_code,
        stdout_bytes,
        stderr_bytes,
    )
