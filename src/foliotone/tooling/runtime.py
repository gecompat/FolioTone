"""Bounded local/container process execution for read-only ToolProviders."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

from sqlalchemy import Engine

from foliotone.core import EntityId, ToolCapability, ToolExecutionStatus
from foliotone.persistence import repository
from foliotone.tooling.artifacts import ToolArtifact
from foliotone.tooling.contracts import ToolExecution, ToolProviderDescriptor
from foliotone.tooling.structured import (
    DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES,
    JsonValue,
    StructuredOutputError,
    parse_json_output,
)

Clock = Callable[[], datetime]
VersionPolicy = Callable[[str], str | None]
MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024 * 1024
MAX_VERSION_OUTPUT_BYTES = 64 * 1024
type LocalProbeCacheKey = tuple[
    str,
    tuple[str, ...],
    str,
    str,
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str], ...],
    int,
]


@dataclass(frozen=True, slots=True)
class WorkspaceOutput:
    """Bounded file an adapter expects a tool to create in its private workspace."""

    artifact_type: str
    relative_path: str
    required: bool = True
    max_bytes: int = DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES

    def __post_init__(self) -> None:
        artifact_type = self.artifact_type.strip()
        if not artifact_type:
            raise ValueError("artifact_type must not be empty")
        if artifact_type in {"STDOUT", "STDERR"}:
            raise ValueError("workspace artifact_type must not be STDOUT or STDERR")
        object.__setattr__(self, "artifact_type", artifact_type)
        object.__setattr__(
            self,
            "relative_path",
            _validate_workspace_relative_path(self.relative_path),
        )
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")


@dataclass(frozen=True, slots=True)
class LocalCommand:
    """Read-only local CLI invocation supplied by a concrete adapter."""

    executable: str
    args: tuple[str, ...]
    capability: ToolCapability
    version_args: tuple[str, ...] = ("--version",)
    timeout_seconds: float = 60.0
    environment: Mapping[str, str] | None = None
    workspace_environment: Mapping[str, str] | None = None
    outputs: tuple[WorkspaceOutput, ...] = ()
    version_policy: VersionPolicy | None = None
    accepted_exit_codes: frozenset[int] = frozenset({0})
    max_stdout_bytes: int = 64 * 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("executable must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(
            self,
            "max_stdout_bytes",
            _validate_process_output_limit(self.max_stdout_bytes),
        )
        object.__setattr__(
            self,
            "max_stderr_bytes",
            _validate_process_output_limit(self.max_stderr_bytes),
        )
        if self.workspace_environment:
            for variable, relative_path in self.workspace_environment.items():
                if not variable.strip():
                    raise ValueError("workspace environment variable must not be empty")
                _validate_workspace_relative_path(relative_path)
        artifact_types = [output.artifact_type for output in self.outputs]
        if len(artifact_types) != len(set(artifact_types)):
            raise ValueError("workspace output artifact types must be unique")
        object.__setattr__(
            self,
            "accepted_exit_codes",
            _validate_accepted_exit_codes(self.accepted_exit_codes),
        )


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
    outputs: tuple[WorkspaceOutput, ...] = ()
    accepted_exit_codes: frozenset[int] = frozenset({0})
    max_stdout_bytes: int = 64 * 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise ValueError("image must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(
            self,
            "max_stdout_bytes",
            _validate_process_output_limit(self.max_stdout_bytes),
        )
        object.__setattr__(
            self,
            "max_stderr_bytes",
            _validate_process_output_limit(self.max_stderr_bytes),
        )
        artifact_types = [output.artifact_type for output in self.outputs]
        if len(artifact_types) != len(set(artifact_types)):
            raise ValueError("workspace output artifact types must be unique")
        object.__setattr__(
            self,
            "accepted_exit_codes",
            _validate_accepted_exit_codes(self.accepted_exit_codes),
        )


@dataclass(frozen=True, slots=True)
class ToolRunOutcome:
    """Terminal ToolExecution plus persisted runtime artifacts and bounded previews."""

    execution: ToolExecution
    artifacts: tuple[ToolArtifact, ...]
    stdout_preview: str
    stderr_preview: str


@dataclass(frozen=True, slots=True)
class LocalToolProbe:
    """Non-persisted local executable/version preflight for exact reuse planning."""

    executable: str | None
    tool_version: str
    error_summary: str | None = None

    def __post_init__(self) -> None:
        tool_version = self.tool_version.strip()
        if not tool_version:
            raise ValueError("tool_version must not be empty")
        object.__setattr__(self, "tool_version", tool_version)
        if self.executable is None and self.error_summary is None:
            raise ValueError("unavailable local tool probe requires an error summary")
        if self.error_summary is not None:
            error_summary = self.error_summary.strip()
            if not error_summary:
                raise ValueError("error_summary must not be empty")
            object.__setattr__(self, "error_summary", error_summary)

    @property
    def usable(self) -> bool:
        """Return whether the probed executable may safely analyze source media."""
        return self.executable is not None and self.error_summary is None


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
        cache_local_probes: bool = False,
    ) -> None:
        if preview_bytes <= 0:
            raise ValueError("preview_bytes must be positive")
        self._execution_repo = repository(engine, ToolExecution)
        self._artifact_repo = repository(engine, ToolArtifact)
        self._artifact_root = artifact_root
        self._work_root = work_root or artifact_root / "work"
        self._preview_bytes = preview_bytes
        self._clock = clock or _utc_now
        self._cache_local_probes = cache_local_probes
        self._local_probe_cache: dict[
            LocalProbeCacheKey,
            Future[LocalToolProbe],
        ] = {}
        self._local_probe_lock = threading.Lock()
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._work_root.mkdir(parents=True, exist_ok=True)

    def probe_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
    ) -> LocalToolProbe:
        """Discover an accepted local tool version without persisting an analysis run."""
        self._validate_descriptor_command(descriptor, command.capability)
        return self._probe_local(command)

    def verify_artifact(self, artifact: ToolArtifact, *, max_bytes: int) -> None:
        """Stream-verify one persisted artifact without loading it into memory."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if artifact.size_bytes > max_bytes:
            raise StructuredOutputError("tool artifact exceeds the configured size limit")
        artifact_path = self._resolved_artifact_path(artifact)
        digest = hashlib.sha256()
        size = 0
        try:
            with artifact_path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise StructuredOutputError(
                            "tool artifact exceeds the configured size limit"
                        )
                    digest.update(chunk)
        except (OSError, RuntimeError) as error:
            raise StructuredOutputError("tool artifact is unavailable") from error
        if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
            raise StructuredOutputError("tool artifact failed its integrity check")

    def read_json_stdout(
        self,
        outcome: ToolRunOutcome,
        *,
        max_bytes: int = DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES,
    ) -> JsonValue:
        """Load one execution's persisted stdout artifact as bounded strict JSON."""
        stdout_artifacts = tuple(
            artifact for artifact in outcome.artifacts if artifact.artifact_type == "STDOUT"
        )
        if len(stdout_artifacts) != 1:
            raise StructuredOutputError(
                "structured stdout requires exactly one persisted STDOUT artifact"
            )
        return self.read_json_artifact(stdout_artifacts[0], max_bytes=max_bytes)

    def read_json_artifact(
        self,
        artifact: ToolArtifact,
        *,
        max_bytes: int = DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES,
    ) -> JsonValue:
        """Load and integrity-check a persisted ToolArtifact as bounded strict JSON."""
        data = self.read_artifact_bytes(artifact, max_bytes=max_bytes)
        return parse_json_output(data, max_bytes=max_bytes)

    def read_artifact_bytes(
        self,
        artifact: ToolArtifact,
        *,
        max_bytes: int = DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES,
    ) -> bytes:
        """Load one persisted artifact with path, size, and digest verification."""
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if artifact.size_bytes > max_bytes:
            raise StructuredOutputError("tool artifact exceeds the configured size limit")

        artifact_path = self._resolved_artifact_path(artifact)
        try:
            with artifact_path.open("rb") as stream:
                data = stream.read(max_bytes + 1)
        except OSError as error:
            raise StructuredOutputError("tool artifact is unavailable") from error
        if len(data) != artifact.size_bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise StructuredOutputError("tool artifact failed its integrity check")
        return data

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
        probe = self._probe_local(command)
        if not probe.usable:
            return self._failed_without_process(
                descriptor,
                command.capability,
                input_identity,
                config_identity,
                probe.tool_version,
                probe.error_summary or "local tool preflight failed",
            )
        assert probe.executable is not None

        environment = os.environ.copy()
        if command.environment:
            environment.update(command.environment)

        return self._execute_process(
            descriptor,
            command.capability,
            input_identity,
            config_identity,
            probe.tool_version,
            (probe.executable, *command.args),
            command.timeout_seconds,
            environment,
            workspace_environment=command.workspace_environment,
            outputs=command.outputs,
            accepted_exit_codes=command.accepted_exit_codes,
            max_stdout_bytes=command.max_stdout_bytes,
            max_stderr_bytes=command.max_stderr_bytes,
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
        try:
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
                outputs=command.outputs,
                accepted_exit_codes=command.accepted_exit_codes,
                max_stdout_bytes=command.max_stdout_bytes,
                max_stderr_bytes=command.max_stderr_bytes,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _validate_request(
        self,
        descriptor: ToolProviderDescriptor,
        capability: ToolCapability,
        input_identity: str,
    ) -> None:
        self._validate_descriptor_command(descriptor, capability)
        if _looks_like_absolute_path(input_identity):
            raise ValueError("input_identity must not persist an absolute local path")
        if not input_identity.strip():
            raise ValueError("input_identity must not be empty")

    @staticmethod
    def _validate_descriptor_command(
        descriptor: ToolProviderDescriptor,
        capability: ToolCapability,
    ) -> None:
        if not descriptor.default_read_only:
            raise ValueError("write-capable ToolProvider is not allowed before W10")
        if capability not in descriptor.capabilities:
            raise ValueError(f"provider does not declare capability {capability.value}")

    def _probe_local(self, command: LocalCommand) -> LocalToolProbe:
        if not self._cache_local_probes:
            return self._probe_local_uncached(command)
        key = _local_probe_cache_key(command)
        with self._local_probe_lock:
            future = self._local_probe_cache.get(key)
            owner = future is None
            if future is None:
                future = Future()
                self._local_probe_cache[key] = future
        if owner:
            try:
                future.set_result(self._probe_local_uncached(command))
            except BaseException as error:
                future.set_exception(error)
                with self._local_probe_lock:
                    if self._local_probe_cache.get(key) is future:
                        self._local_probe_cache.pop(key)
                raise
        return future.result()

    def _probe_local_uncached(self, command: LocalCommand) -> LocalToolProbe:
        executable = shutil.which(command.executable)
        if executable is None:
            return LocalToolProbe(
                executable=None,
                tool_version="unavailable",
                error_summary=f"executable not found: {command.executable}",
            )

        environment = os.environ.copy()
        if command.environment:
            environment.update(command.environment)
        if command.workspace_environment:
            version_workspace = Path(
                tempfile.mkdtemp(prefix="version-", dir=self._work_root)
            ).resolve()
            try:
                version_environment = _apply_workspace_environment(
                    environment,
                    command.workspace_environment,
                    version_workspace,
                )
                version = _detect_version(
                    executable,
                    command.version_args,
                    environment=version_environment,
                )
            finally:
                shutil.rmtree(version_workspace, ignore_errors=True)
        else:
            version = _detect_version(
                executable,
                command.version_args,
                environment=environment,
            )
        if version is None:
            return LocalToolProbe(
                executable=executable,
                tool_version="unknown",
                error_summary=f"could not determine tool version: {command.executable}",
            )
        if command.version_policy is not None:
            policy_error = command.version_policy(version)
            if policy_error is not None:
                return LocalToolProbe(
                    executable=executable,
                    tool_version=version,
                    error_summary=policy_error,
                )
        return LocalToolProbe(executable=executable, tool_version=version)

    def _resolved_artifact_path(self, artifact: ToolArtifact) -> Path:
        artifact_root = self._artifact_root.resolve()
        artifact_path = artifact_root / artifact.relative_path
        try:
            if artifact_path.is_symlink():
                raise StructuredOutputError("symbolic-link tool artifacts are not accepted")
            resolved = artifact_path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise StructuredOutputError("tool artifact is unavailable") from error
        if not resolved.is_relative_to(artifact_root) or not resolved.is_file():
            raise StructuredOutputError("tool artifact escapes the artifact root")
        return resolved

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
        workspace_environment: Mapping[str, str] | None = None,
        outputs: tuple[WorkspaceOutput, ...] = (),
        accepted_exit_codes: frozenset[int] = frozenset({0}),
        max_stdout_bytes: int = 64 * 1024 * 1024,
        max_stderr_bytes: int = 1024 * 1024,
    ) -> ToolRunOutcome:
        execution_id = execution_id or EntityId.new()
        created_workspace = workspace is None
        if workspace is None:
            workspace = Path(tempfile.mkdtemp(prefix=f"{execution_id}-", dir=self._work_root))
        workspace = workspace.resolve()
        process_environment = _apply_workspace_environment(
            environment,
            workspace_environment,
            workspace,
        )

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
        captured_outputs: tuple[tuple[str, Path], ...] = ()
        try:
            try:
                with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                    process = subprocess.Popen(
                        argv,
                        cwd=workspace,
                        env=process_environment,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                    )
                    assert process.stdout is not None
                    assert process.stderr is not None
                    capture_failures: list[str] = []
                    capture_lock = threading.Lock()

                    def capture_stream(
                        stream: BinaryIO,
                        target: BinaryIO,
                        limit: int,
                        label: str,
                    ) -> None:
                        written = 0
                        try:
                            while chunk := os.read(stream.fileno(), 64 * 1024):
                                remaining = limit - written
                                if len(chunk) > remaining:
                                    if remaining > 0:
                                        target.write(chunk[:remaining])
                                    with capture_lock:
                                        capture_failures.append(
                                            f"{label} exceeded its configured size limit"
                                        )
                                    try:
                                        process.kill()
                                    except OSError:
                                        pass
                                    return
                                target.write(chunk)
                                written += len(chunk)
                        except (OSError, ValueError):
                            with capture_lock:
                                capture_failures.append(f"{label} capture failed")
                            try:
                                process.kill()
                            except OSError:
                                pass

                    readers = (
                        threading.Thread(
                            target=capture_stream,
                            args=(process.stdout, stdout, max_stdout_bytes, "stdout"),
                        ),
                        threading.Thread(
                            target=capture_stream,
                            args=(process.stderr, stderr, max_stderr_bytes, "stderr"),
                        ),
                    )
                    for reader in readers:
                        reader.start()
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
                        for reader in readers:
                            reader.join()
                        stdout.flush()
                        stderr.flush()
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
                                if exit_code in accepted_exit_codes
                                else ToolExecutionStatus.FAILED
                            ),
                            exit_code=exit_code,
                            error_summary=(
                                None
                                if exit_code in accepted_exit_codes
                                else f"exit code {exit_code}"
                            ),
                        )
                    finally:
                        for reader in readers:
                            reader.join()
                    if capture_failures:
                        terminal = replace(
                            running,
                            finished_at=self._clock(),
                            status=ToolExecutionStatus.FAILED,
                            error_summary=sorted(set(capture_failures))[0],
                        )
            except OSError as exc:
                terminal = replace(
                    running,
                    finished_at=self._clock(),
                    status=ToolExecutionStatus.FAILED,
                    error_summary=f"process error: {exc}",
                )

            captured_outputs, output_error = self._capture_workspace_outputs(
                execution_id,
                workspace,
                outputs,
            )
            if output_error is not None and terminal.status is ToolExecutionStatus.SUCCEEDED:
                terminal = replace(
                    terminal,
                    status=ToolExecutionStatus.FAILED,
                    error_summary=output_error,
                )
        finally:
            if created_workspace:
                shutil.rmtree(workspace, ignore_errors=True)

        self._execution_repo.save(terminal)
        artifacts = self._persist_artifacts(
            execution_id,
            stdout_path,
            stderr_path,
            captured_outputs,
        )
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
        extra_paths: tuple[tuple[str, Path], ...] = (),
    ) -> tuple[ToolArtifact, ...]:
        artifacts: list[ToolArtifact] = []
        paths = (("STDOUT", stdout_path), ("STDERR", stderr_path), *extra_paths)
        for artifact_type, path in paths:
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

    def _capture_workspace_outputs(
        self,
        execution_id: EntityId,
        workspace: Path,
        outputs: tuple[WorkspaceOutput, ...],
    ) -> tuple[tuple[tuple[str, Path], ...], str | None]:
        captured: list[tuple[str, Path]] = []
        output_dir = self._artifact_root / str(execution_id) / "outputs"
        workspace_root = workspace.resolve()
        for index, output in enumerate(outputs):
            source = workspace_root / output.relative_path
            try:
                resolved_source = source.resolve(strict=True)
                safe = (
                    resolved_source.is_relative_to(workspace_root)
                    and not source.is_symlink()
                    and resolved_source.is_file()
                )
            except (OSError, RuntimeError):
                safe = False
                resolved_source = source
            if not safe:
                if output.required:
                    return tuple(captured), (
                        f"required workspace output unavailable: {output.relative_path}"
                    )
                continue

            suffix = Path(output.relative_path).suffix[:16]
            target = output_dir / f"{index:03d}{suffix}"
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                with (
                    resolved_source.open("rb") as source_stream,
                    target.open("wb") as target_stream,
                ):
                    copied = 0
                    while chunk := source_stream.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > output.max_bytes:
                            raise ValueError("workspace output exceeds its configured size limit")
                        target_stream.write(chunk)
            except (OSError, ValueError):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                if output.required:
                    return tuple(captured), (
                        f"required workspace output invalid: {output.relative_path}"
                    )
                continue
            captured.append((output.artifact_type, target))
        return tuple(captured), None

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


def _local_probe_cache_key(command: LocalCommand) -> LocalProbeCacheKey:
    return (
        command.executable,
        command.version_args,
        os.environ.get("PATH", ""),
        os.environ.get("PATHEXT", ""),
        tuple(sorted((command.environment or {}).items())),
        tuple(sorted((command.workspace_environment or {}).items())),
        id(command.version_policy),
    )


def _detect_version(
    executable: str,
    args: tuple[str, ...],
    *,
    environment: Mapping[str, str],
) -> str | None:
    try:
        process = subprocess.Popen(
            (executable, *args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=dict(environment),
        )
    except OSError:
        return None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    rejected = threading.Event()

    def capture(stream: BinaryIO, target: bytearray) -> None:
        try:
            while chunk := os.read(stream.fileno(), 64 * 1024):
                if len(target) + len(chunk) > MAX_VERSION_OUTPUT_BYTES:
                    rejected.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
                target.extend(chunk)
        except (OSError, ValueError):
            rejected.set()
            try:
                process.kill()
            except OSError:
                pass

    readers = (
        threading.Thread(target=capture, args=(process.stdout, stdout)),
        threading.Thread(target=capture, args=(process.stderr, stderr)),
    )
    for reader in readers:
        reader.start()
    return_code: int | None = None
    try:
        return_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        rejected.set()
    finally:
        for reader in readers:
            reader.join()
    if rejected.is_set() or return_code != 0:
        return None
    text = bytes(stdout or stderr).decode(errors="replace").strip()
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


def _validate_process_output_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("process output limit must be an integer")
    if not 1 <= value <= MAX_PROCESS_OUTPUT_BYTES:
        raise ValueError("process output limit is outside the supported range")
    return value


def _validate_accepted_exit_codes(codes: frozenset[int]) -> frozenset[int]:
    normalized = frozenset(codes)
    if not normalized:
        raise ValueError("accepted_exit_codes must not be empty")
    if any(isinstance(code, bool) or not isinstance(code, int) or code < 0 for code in normalized):
        raise ValueError("accepted_exit_codes must contain non-negative integers")
    return normalized


def _apply_workspace_environment(
    environment: Mapping[str, str],
    workspace_environment: Mapping[str, str] | None,
    workspace: Path,
) -> dict[str, str]:
    process_environment = dict(environment)
    if workspace_environment is None:
        return process_environment
    for variable, relative_path in workspace_environment.items():
        normalized = _validate_workspace_relative_path(relative_path)
        directory = (workspace / normalized).resolve()
        if not directory.is_relative_to(workspace):
            raise ValueError("workspace environment directory escapes the workspace")
        directory.mkdir(parents=True, exist_ok=True)
        process_environment[variable] = str(directory)
    return process_environment


def _validate_workspace_relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if (
        not normalized
        or posix_path.is_absolute()
        or PureWindowsPath(normalized).is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise ValueError("workspace path must be a safe relative path")
    return posix_path.as_posix()


def _utc_now() -> datetime:
    return datetime.now(UTC)
