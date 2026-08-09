"""Bounded local/container process execution for read-only ToolProviders."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import Engine

from foliotone.core import EntityId, ToolCapability, ToolExecutionStatus
from foliotone.persistence import repository
from foliotone.tooling.artifacts import ToolArtifact
from foliotone.tooling.contracts import ToolExecution, ToolProviderDescriptor

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class LocalCommand:
    """Read-only local CLI invocation supplied by a concrete adapter."""

    executable: str
    args: tuple[str, ...]
    capability: ToolCapability
    version_args: tuple[str, ...] = ("--version",)
    timeout_seconds: float = 60.0
    environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("executable must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ReadOnlyMount:
    """Host input mounted read-only into a specialist tool container."""

    host_path: Path
    container_path: str

    def __post_init__(self) -> None:
        if not PurePosixPath(self.container_path).is_absolute():
            raise ValueError("container_path must be an absolute POSIX path")


@dataclass(frozen=True, slots=True)
class ContainerCommand:
    """Hardened Docker invocation with read-only source mounts by construction."""

    image: str
    args: tuple[str, ...]
    capability: ToolCapability
    mounts: tuple[ReadOnlyMount, ...] = ()
    timeout_seconds: float = 120.0
    network_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise ValueError("image must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ToolRunOutcome:
    """Terminal ToolExecution plus persisted runtime artifacts and bounded previews."""

    execution: ToolExecution
    artifacts: tuple[ToolArtifact, ...]
    stdout_preview: str
    stderr_preview: str


class ToolRuntime:
    """Execute read-only specialist tools without using a shell."""

    def __init__(
        self,
        engine: Engine,
        artifact_root: Path,
        *,
        work_root: Path | None = None,
        preview_bytes: int = 64 * 1024,
        clock: Clock | None = None,
    ) -> None:
        if preview_bytes <= 0:
            raise ValueError("preview_bytes must be positive")
        self._execution_repo = repository(engine, ToolExecution)
        self._artifact_repo = repository(engine, ToolArtifact)
        self._artifact_root = artifact_root
        self._work_root = work_root or artifact_root / "work"
        self._preview_bytes = preview_bytes
        self._clock = clock or _utc_now
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._work_root.mkdir(parents=True, exist_ok=True)

    def execute_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        """Execute a local CLI after discovering and recording its version."""
        self._validate_request(descriptor, command.capability, input_identity)
        executable = shutil.which(command.executable)
        if executable is None:
            return self._failed_without_process(
                descriptor,
                command.capability,
                input_identity,
                config_identity,
                "unavailable",
                f"executable not found: {command.executable}",
            )

        version = _detect_version(executable, command.version_args)
        if version is None:
            return self._failed_without_process(
                descriptor,
                command.capability,
                input_identity,
                config_identity,
                "unknown",
                f"could not determine tool version: {command.executable}",
            )

        environment = os.environ.copy()
        if command.environment:
            environment.update(command.environment)
        return self._execute_process(
            descriptor,
            command.capability,
            input_identity,
            config_identity,
            version,
            (executable, *command.args),
            command.timeout_seconds,
            environment,
        )

    def execute_container(
        self,
        descriptor: ToolProviderDescriptor,
        command: ContainerCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        """Execute a Dockerized tool with hardened defaults and read-only inputs."""
        self._validate_request(descriptor, command.capability, input_identity)
        docker = shutil.which("docker")
        if docker is None:
            return self._failed_without_process(
                descriptor,
                command.capability,
                input_identity,
                config_identity,
                command.image,
                "docker executable not found",
            )
        execution_id = EntityId.new()
        workspace = self._work_root / str(execution_id)
        workspace.mkdir(parents=True, exist_ok=True)
        argv = build_docker_argv(docker, command, workspace)
        return self._execute_process(
            descriptor,
            command.capability,
            input_identity,
            config_identity,
            command.image,
            argv,
            command.timeout_seconds,
            os.environ.copy(),
            execution_id=execution_id,
            workspace=workspace,
        )

    def _validate_request(
        self,
        descriptor: ToolProviderDescriptor,
        capability: ToolCapability,
        input_identity: str,
    ) -> None:
        if not descriptor.default_read_only:
            raise ValueError("write-capable ToolProvider is not allowed before W10")
        if capability not in descriptor.capabilities:
            raise ValueError(f"provider does not declare capability {capability.value}")
        if _looks_like_absolute_path(input_identity):
            raise ValueError("input_identity must not persist an absolute local path")
        if not input_identity.strip():
            raise ValueError("input_identity must not be empty")

    def _execute_process(
        self,
        descriptor: ToolProviderDescriptor,
        capability: ToolCapability,
        input_identity: str,
        config_identity: str | None,
        tool_version: str,
        argv: tuple[str, ...],
        timeout_seconds: float,
        environment: Mapping[str, str],
        *,
        execution_id: EntityId | None = None,
        workspace: Path | None = None,
    ) -> ToolRunOutcome:
        execution_id = execution_id or EntityId.new()
        created_workspace = workspace is None
        if workspace is None:
            workspace = Path(tempfile.mkdtemp(prefix=f"{execution_id}-", dir=self._work_root))

        artifact_dir = self._artifact_root / str(execution_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact_dir / "stdout.bin"
        stderr_path = artifact_dir / "stderr.bin"

        running = ToolExecution(
            id=execution_id,
            provider_id=descriptor.provider_id,
            tool_version=tool_version,
            adapter_version=descriptor.adapter_version,
            capability=capability,
            input_identity=input_identity,
            config_identity=config_identity,
            started_at=self._clock(),
            status=ToolExecutionStatus.RUNNING,
        )
        self._execution_repo.save(running)

        terminal: ToolExecution
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    env=dict(environment),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                )
                try:
                    exit_code = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    terminal = replace(
                        running,
                        finished_at=self._clock(),
                        status=ToolExecutionStatus.CANCELLED,
                        error_summary=f"timeout after {timeout_seconds:g} seconds",
                    )
                except KeyboardInterrupt:
                    process.kill()
                    process.wait()
                    cancelled = replace(
                        running,
                        finished_at=self._clock(),
                        status=ToolExecutionStatus.CANCELLED,
                        error_summary="cancelled by caller",
                    )
                    self._execution_repo.save(cancelled)
                    self._persist_artifacts(execution_id, stdout_path, stderr_path)
                    raise
                else:
                    terminal = replace(
                        running,
                        finished_at=self._clock(),
                        status=(
                            ToolExecutionStatus.SUCCEEDED
                            if exit_code == 0
                            else ToolExecutionStatus.FAILED
                        ),
                        exit_code=exit_code,
                        error_summary=None if exit_code == 0 else f"exit code {exit_code}",
                    )
        except OSError as exc:
            terminal = replace(
                running,
                finished_at=self._clock(),
                status=ToolExecutionStatus.FAILED,
                error_summary=f"process error: {exc}",
            )
        finally:
            if created_workspace:
                shutil.rmtree(workspace, ignore_errors=True)

        self._execution_repo.save(terminal)
        artifacts = self._persist_artifacts(execution_id, stdout_path, stderr_path)
        return ToolRunOutcome(
            execution=terminal,
            artifacts=artifacts,
            stdout_preview=_read_preview(stdout_path, self._preview_bytes),
            stderr_preview=_read_preview(stderr_path, self._preview_bytes),
        )

    def _persist_artifacts(
        self,
        execution_id: EntityId,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[ToolArtifact, ...]:
        artifacts: list[ToolArtifact] = []
        for artifact_type, path in (("STDOUT", stdout_path), ("STDERR", stderr_path)):
            if not path.exists():
                continue
            relative = path.relative_to(self._artifact_root).as_posix()
            artifact = ToolArtifact(
                id=EntityId.new(),
                execution_id=execution_id,
                artifact_type=artifact_type,
                relative_path=relative,
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
            )
            self._artifact_repo.save(artifact)
            artifacts.append(artifact)
        return tuple(artifacts)

    def _failed_without_process(
        self,
        descriptor: ToolProviderDescriptor,
        capability: ToolCapability,
        input_identity: str,
        config_identity: str | None,
        tool_version: str,
        error_summary: str,
    ) -> ToolRunOutcome:
        now = self._clock()
        execution = ToolExecution(
            id=EntityId.new(),
            provider_id=descriptor.provider_id,
            tool_version=tool_version,
            adapter_version=descriptor.adapter_version,
            capability=capability,
            input_identity=input_identity,
            config_identity=config_identity,
            started_at=now,
            finished_at=now,
            status=ToolExecutionStatus.FAILED,
            error_summary=error_summary,
        )
        self._execution_repo.save(execution)
        return ToolRunOutcome(execution, (), "", "")


def build_docker_argv(
    docker_executable: str,
    command: ContainerCommand,
    workspace: Path,
) -> tuple[str, ...]:
    """Build a hardened docker-run command without executing it."""
    argv = [
        docker_executable,
        "run",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev",
        f"--network={'bridge' if command.network_enabled else 'none'}",
        "--mount",
        f"type=bind,src={workspace},dst=/work",
    ]
    for mount in command.mounts:
        argv.extend(
            (
                "--mount",
                f"type=bind,src={mount.host_path},dst={mount.container_path},readonly",
            )
        )
    argv.append(command.image)
    argv.extend(command.args)
    return tuple(argv)


def _detect_version(executable: str, args: tuple[str, ...]) -> str | None:
    try:
        result = subprocess.run(
            (executable, *args),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or result.stderr).decode(errors="replace").strip()
    return text.splitlines()[0][:256] if text else None


def _read_preview(path: Path, limit: int) -> str:
    """Return a bounded, display-safe text preview without altering its artifact."""
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        preview = stream.read(limit).decode(errors="replace")
    return preview.replace("\r\n", "\n").replace("\r", "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _utc_now() -> datetime:
    return datetime.now(UTC)
