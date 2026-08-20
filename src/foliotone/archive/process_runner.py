"""Bounded, raw-output-free process streaming for the archive sandbox.

The runner is intentionally smaller than the generic tooling runtime.  It never
stores output bytes and it never invokes a shell.  Callers receive only fixed
status values and byte counts; parser state stays with the supplied in-memory
consumers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Final, Protocol, cast

_READ_CHUNK_BYTES: Final = 64 * 1024
_PROCESS_STOP_SECONDS: Final = 5.0
_POSIX_KILLPG: Final = vars(os).get("killpg")
_SIGKILL: Final = vars(signal).get("SIGKILL", 9)


class ArchiveProcessStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    CONSUMER_REJECTED = "CONSUMER_REJECTED"


@dataclass(frozen=True, slots=True)
class ProcessExecutionResult:
    """Secret- and path-free terminal information about one process attempt."""

    status: ArchiveProcessStatus
    exit_code: int | None
    stdout_bytes: int
    stderr_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, ArchiveProcessStatus):
            raise ValueError("status must be ArchiveProcessStatus")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("exit_code must be an integer or None")
        for value in (self.stdout_bytes, self.stderr_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("stream byte counts must be non-negative integers")
        if self.status is ArchiveProcessStatus.SUCCEEDED and self.exit_code != 0:
            raise ValueError("successful process result requires exit code zero")


class CancellationProbe(Protocol):
    def is_set(self) -> bool: ...


class RunningProcess(Protocol):
    def read_stdout(self, size: int) -> bytes: ...

    def read_stderr(self, size: int) -> bytes: ...

    def wait(self, timeout_seconds: float) -> int | None: ...

    def kill_tree(self) -> None: ...

    def close(self) -> None: ...


class ProcessLauncher(Protocol):
    def start(self, argv: tuple[str, ...], environment: Mapping[str, str]) -> RunningProcess: ...


ByteConsumer = Callable[[bytes], bool | None]


class ArchiveProcessRunner:
    """Internal primitive used only behind the closed container request API."""

    def __init__(
        self,
        launcher: ProcessLauncher,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._launcher = launcher
        self._monotonic = monotonic

    def run(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str],
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
        stdout_consumer: ByteConsumer,
        stderr_consumer: ByteConsumer,
        cancellation: CancellationProbe | None = None,
    ) -> ProcessExecutionResult:
        command = _validated_argv(argv)
        clean_environment = _validated_environment(environment)
        _require_positive_number(timeout_seconds, "timeout_seconds")
        _require_nonnegative_int(max_stdout_bytes, "max_stdout_bytes")
        _require_nonnegative_int(max_stderr_bytes, "max_stderr_bytes")
        process = self._launcher.start(command, clean_environment)
        counters = {"stdout": 0, "stderr": 0}
        failure: list[ArchiveProcessStatus] = []
        failure_event = threading.Event()
        lock = threading.Lock()

        def consume_stream(
            name: str,
            reader: Callable[[int], bytes],
            limit: int,
            consumer: ByteConsumer,
        ) -> None:
            try:
                while True:
                    if failure_event.is_set():
                        return
                    chunk = reader(_READ_CHUNK_BYTES)
                    if not chunk:
                        return
                    if not isinstance(chunk, bytes):
                        raise TypeError("process streams must yield bytes")
                    with lock:
                        next_count = counters[name] + len(chunk)
                        counters[name] = next_count
                        if next_count > limit:
                            failure.append(ArchiveProcessStatus.LIMIT_EXCEEDED)
                            failure_event.set()
                            return
                    if failure_event.is_set():
                        return
                    if consumer(chunk) is False:
                        with lock:
                            failure.append(ArchiveProcessStatus.CONSUMER_REJECTED)
                            failure_event.set()
                        return
            except Exception:
                with lock:
                    failure.append(ArchiveProcessStatus.CONSUMER_REJECTED)
                    failure_event.set()

        readers = (
            threading.Thread(
                target=consume_stream,
                args=("stdout", process.read_stdout, max_stdout_bytes, stdout_consumer),
                daemon=True,
            ),
            threading.Thread(
                target=consume_stream,
                args=("stderr", process.read_stderr, max_stderr_bytes, stderr_consumer),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()

        deadline = self._monotonic() + timeout_seconds
        status: ArchiveProcessStatus | None = None
        exit_code: int | None = None
        closed = False
        termination_failed = False
        try:
            while exit_code is None:
                if failure_event.is_set():
                    with lock:
                        status = _stream_failure_precedence(failure)
                    termination_failed = not _try_kill_tree(process)
                    break
                if cancellation is not None:
                    try:
                        cancelled = cancellation.is_set()
                    except Exception:
                        status = ArchiveProcessStatus.FAILED
                        termination_failed = not _try_kill_tree(process)
                        break
                    if cancelled:
                        status = ArchiveProcessStatus.CANCELLED
                        termination_failed = not _try_kill_tree(process)
                        break
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    status = ArchiveProcessStatus.TIMED_OUT
                    termination_failed = not _try_kill_tree(process)
                    break
                exit_code = process.wait(min(remaining, 0.05))
            if exit_code is None:
                exit_code = process.wait(_PROCESS_STOP_SECONDS)
                if exit_code is None:
                    _try_kill_tree(process)
                    termination_failed = True
                    status = ArchiveProcessStatus.FAILED
            for reader in readers:
                reader.join(_PROCESS_STOP_SECONDS)
            if any(reader.is_alive() for reader in readers):
                failure_event.set()
                if not _try_kill_tree(process):
                    termination_failed = True
                process.close()
                closed = True
                for reader in readers:
                    reader.join(_PROCESS_STOP_SECONDS)
                termination_failed = True
            with lock:
                if termination_failed:
                    status = ArchiveProcessStatus.FAILED
                elif failure:
                    status = _stream_failure_precedence(failure)
            if status is None:
                status = (
                    ArchiveProcessStatus.SUCCEEDED
                    if exit_code == 0
                    else ArchiveProcessStatus.FAILED
                )
            return ProcessExecutionResult(
                status,
                exit_code,
                counters["stdout"],
                counters["stderr"],
            )
        finally:
            if not closed:
                process.close()


class SubprocessLauncher:
    """No-shell launcher with a new POSIX process group for tree termination."""

    def start(self, argv: tuple[str, ...], environment: Mapping[str, str]) -> RunningProcess:
        process = subprocess.Popen(  # noqa: S603 - argv is closed by the caller contract
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            shell=False,
            close_fds=True,
            start_new_session=os.name == "posix",
        )
        return _SubprocessHandle(process)


class _SubprocessHandle:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("bounded process requires both output pipes")
        self._process = process
        self._stdout = cast(BinaryIO, process.stdout)
        self._stderr = cast(BinaryIO, process.stderr)

    def read_stdout(self, size: int) -> bytes:
        return self._stdout.read(size)

    def read_stderr(self, size: int) -> bytes:
        return self._stderr.read(size)

    def wait(self, timeout_seconds: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return None

    def kill_tree(self) -> None:
        try:
            if os.name == "posix":
                if not callable(_POSIX_KILLPG):
                    raise RuntimeError("process-tree termination unavailable")
                _POSIX_KILLPG(self._process.pid, _SIGKILL)
            elif self._process.poll() is None:
                self._process.kill()
        except ProcessLookupError:
            return

    def close(self) -> None:
        self._stdout.close()
        self._stderr.close()


def discard_process_bytes(_chunk: bytes) -> bool:
    """Explicit consumer for output that must be discarded immediately."""

    return True


def _try_kill_tree(process: RunningProcess) -> bool:
    try:
        process.kill_tree()
        return True
    except Exception:
        return False


def _validated_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise ValueError("argv must be a sequence of fixed arguments")
    command = tuple(argv)
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise ValueError("argv must contain non-empty strings")
    if any("\x00" in value for value in command):
        raise ValueError("argv cannot contain NUL")
    return command


def _validated_environment(environment: Mapping[str, str]) -> dict[str, str]:
    clean = dict(environment)
    if any(
        not isinstance(key, str)
        or not key
        or "=" in key
        or "\x00" in key
        or not isinstance(value, str)
        or "\x00" in value
        for key, value in clean.items()
    ):
        raise ValueError("environment must contain valid strings")
    return clean


def _require_positive_number(value: float, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be positive")


def _require_nonnegative_int(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _stream_failure_precedence(
    failures: Sequence[ArchiveProcessStatus],
) -> ArchiveProcessStatus:
    if ArchiveProcessStatus.LIMIT_EXCEEDED in failures:
        return ArchiveProcessStatus.LIMIT_EXCEEDED
    return ArchiveProcessStatus.CONSUMER_REJECTED
