from __future__ import annotations

import copy
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import foliotone.archive.container_sandbox as container_sandbox_module
from foliotone.archive.container_sandbox import (
    ARCHIVE_CONTAINER_ENVIRONMENT,
    ArchiveContainerRequest,
    ArchiveContainerRunStatus,
    ArchiveLinuxContainerRunner,
    ArchiveRuntimePreflightInputs,
    ArchiveVolumeSource,
    StagedArchiveSandbox,
    verify_container_projection,
)
from foliotone.archive.process_runner import (
    ArchiveProcessRunner,
    ArchiveProcessStatus,
)
from foliotone.archive.sevenzip import (
    ARCHIVE_IMAGE_REFERENCE,
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    ArchiveRuntimeDiagnosticCode,
    ArchiveSevenZipRuntimeAvailability,
    build_7zzs_extraction_command,
    build_7zzs_information_command,
    build_7zzs_listing_command,
)

IMAGE_REFERENCE = (
    f"{ARCHIVE_IMAGE_REFERENCE}@"
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)
CONTAINER_ID = "a" * 64
SYNTHETIC_ROOT = (Path.cwd() / "synthetic-archive-container").resolve()


class _FakeProcess:
    def __init__(
        self,
        stdout: tuple[bytes, ...] = (),
        stderr: tuple[bytes, ...] = (),
        *,
        exit_code: int | None = 0,
    ) -> None:
        self._stdout = list(stdout)
        self._stderr = list(stderr)
        self.exit_code = exit_code
        self.killed = False
        self.closed = False

    def read_stdout(self, _size: int) -> bytes:
        return self._stdout.pop(0) if self._stdout else b""

    def read_stderr(self, _size: int) -> bytes:
        return self._stderr.pop(0) if self._stderr else b""

    def wait(self, _timeout_seconds: float) -> int | None:
        return -9 if self.killed else self.exit_code

    def kill_tree(self) -> None:
        self.killed = True

    def close(self) -> None:
        self.closed = True


class _FakeLauncher:
    def __init__(self, process: _FakeProcess, events: list[str] | None = None) -> None:
        self.process = process
        self.events = events
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str]]] = []

    def start(self, argv: tuple[str, ...], environment: Mapping[str, str]) -> _FakeProcess:
        self.calls.append((argv, dict(environment)))
        if self.events is not None:
            self.events.append("process-start")
        return self.process


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def test_process_stream_failure_precedes_simultaneous_zero_exit_and_quiesces() -> None:
    process = _FakeProcess((b"private-member",), exit_code=0)
    launcher = _FakeLauncher(process)
    calls: list[bytes] = []
    result = ArchiveProcessRunner(launcher).run(
        ("/usr/bin/fixed", "arg"),
        environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=1,
        max_stdout_bytes=1024,
        max_stderr_bytes=0,
        stdout_consumer=lambda chunk: calls.append(chunk) is None and False,
        stderr_consumer=lambda _chunk: True,
    )
    assert result.status is ArchiveProcessStatus.CONSUMER_REJECTED
    assert calls == [b"private-member"]
    assert process.closed is True
    calls_before_return = len(calls)
    assert len(calls) == calls_before_return
    assert "private-member" not in repr(result)


@pytest.mark.parametrize(
    ("stdout", "limit", "expected"),
    [
        ((b"12345",), 4, ArchiveProcessStatus.LIMIT_EXCEEDED),
        ((), 4, ArchiveProcessStatus.TIMED_OUT),
    ],
)
def test_process_limits_or_timeout_kill_the_process_tree(
    stdout: tuple[bytes, ...], limit: int, expected: ArchiveProcessStatus
) -> None:
    process = _FakeProcess(
        stdout,
        exit_code=0 if expected is ArchiveProcessStatus.LIMIT_EXCEEDED else None,
    )
    runner = ArchiveProcessRunner(
        _FakeLauncher(process),
        monotonic=_Clock() if expected is ArchiveProcessStatus.TIMED_OUT else (lambda: 0.0),
    )
    result = runner.run(
        ("/usr/bin/fixed",),
        environment={},
        timeout_seconds=0.5,
        max_stdout_bytes=limit,
        max_stderr_bytes=0,
        stdout_consumer=lambda _chunk: True,
        stderr_consumer=lambda _chunk: True,
    )
    assert result.status is expected
    assert process.killed is True
    assert process.closed is True


def test_process_that_does_not_exit_after_kill_is_failed() -> None:
    process = _FakeProcess(exit_code=None)
    process.wait = lambda _timeout_seconds: None  # type: ignore[method-assign]
    result = ArchiveProcessRunner(
        _FakeLauncher(process), monotonic=_Clock()
    ).run(
        ("/usr/bin/fixed",),
        environment={},
        timeout_seconds=0.5,
        max_stdout_bytes=0,
        max_stderr_bytes=0,
        stdout_consumer=lambda _chunk: True,
        stderr_consumer=lambda _chunk: True,
    )
    assert result.status is ArchiveProcessStatus.FAILED
    assert process.killed is True
    assert process.closed is True


class _FakeFilesystem:
    supports_linux_sandbox = True

    def __init__(self, events: list[str], *, cleanup_ok: bool = True) -> None:
        self.events = events
        self.cleanup_ok = cleanup_ok
        self.stage_calls = 0
        temp = SYNTHETIC_ROOT / "tmp" / "container-test"
        root = temp / (".archive-" + "b" * 32)
        self.sandbox = StagedArchiveSandbox(temp, root, root / "input", root / "output")

    def stage(
        self,
        _temp_root: Path,
        _volumes: tuple[ArchiveVolumeSource, ...],
        _scan_roots: tuple[Path, ...],
    ) -> StagedArchiveSandbox:
        self.stage_calls += 1
        self.events.append("stage")
        return self.sandbox

    def verify_before_start(self, _sandbox: StagedArchiveSandbox) -> bool:
        self.events.append("verify-before")
        return True

    def verify_after_run(self, _sandbox: StagedArchiveSandbox) -> bool:
        self.events.append("verify-after")
        return True

    def cleanup(self, _sandbox: StagedArchiveSandbox) -> bool:
        self.events.append("cleanup")
        return self.cleanup_ok


class _FakeDocker:
    executable = "C:\\Program Files\\Docker\\docker.exe"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.created_argv: tuple[str, ...] | None = None
        self.removed = False
        self.kill_calls = 0

    def create_container(self, argv: tuple[str, ...]) -> str | None:
        self.events.append("create")
        self.created_argv = argv
        return CONTAINER_ID

    def inspect_container(self, _container_id: str) -> Mapping[str, Any] | None:
        self.events.append("inspect")
        assert self.created_argv is not None
        mounts = [
            value
            for index, value in enumerate(self.created_argv)
            if self.created_argv[index - 1] == "--mount"
        ]
        input_source = mounts[0].split(",source=", 1)[1].split(",target=", 1)[0]
        output_source = mounts[1].split(",source=", 1)[1].split(",target=", 1)[0]
        image_index = self.created_argv.index(IMAGE_REFERENCE)
        return {
            "Id": CONTAINER_ID,
            "Name": f"/{self.created_argv[self.created_argv.index('--name') + 1]}",
            "Platform": "linux",
            "Config": {
                "Image": IMAGE_REFERENCE,
                "User": "65532:65532",
                "Entrypoint": ["/usr/local/bin/7zzs"],
                "WorkingDir": "/workspace",
                "Env": list(ARCHIVE_CONTAINER_ENVIRONMENT),
                "Labels": {
                    "org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"
                },
                "Volumes": None,
                "Cmd": list(self.created_argv[image_index + 1 :]),
            },
            "HostConfig": {
                "Privileged": False,
                "ReadonlyRootfs": True,
                "NetworkMode": "none",
                "LogConfig": {"Type": "none", "Config": {}},
                "CapAdd": None,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true", "seccomp=builtin"],
                "Devices": [],
                "DeviceRequests": [],
                "DeviceCgroupRules": [],
                "PidsLimit": 16,
                "Memory": 1_073_741_824,
                "MemorySwap": 1_073_741_824,
                "NanoCpus": 1_000_000_000,
                "Binds": None,
                "Tmpfs": None,
                "VolumesFrom": None,
                "Links": None,
                "PortBindings": {},
                "PublishAllPorts": False,
                "AutoRemove": False,
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": input_source,
                    "Destination": "/workspace/input",
                    "RW": False,
                    "Propagation": "rprivate",
                },
                {
                    "Type": "bind",
                    "Source": output_source,
                    "Destination": "/workspace/output",
                    "RW": True,
                    "Propagation": "rprivate",
                },
            ],
        }

    def start_argv(self, container_id: str) -> tuple[str, ...]:
        return (self.executable, "start", "--attach", container_id)

    def kill_container(self, _container_id: str) -> bool:
        self.kill_calls += 1
        self.events.append("kill")
        return True

    def remove_container(self, _container_id: str) -> bool:
        self.events.append("remove")
        self.removed = True
        return True

    def container_exists(self, _container_id: str) -> bool | None:
        self.events.append("absence")
        return not self.removed


class _Availability:
    def __init__(
        self,
        events: list[str],
        *,
        available: bool = True,
        image_reference: str = IMAGE_REFERENCE,
    ) -> None:
        self.events = events
        self.available = available
        self.image_reference = image_reference
        self.kwargs: dict[str, object] = {}

    def __call__(self, lock_path: Path, **kwargs: object) -> ArchiveSevenZipRuntimeAvailability:
        self.events.append("availability")
        self.kwargs = {"lock_path": lock_path, **kwargs}
        if self.available:
            return ArchiveSevenZipRuntimeAvailability(
                ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
                True,
                "AVAILABLE",
                self.image_reference,
            )
        return ArchiveSevenZipRuntimeAvailability(
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
            False,
            "TOOL_UNAVAILABLE",
            diagnostic_code=ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING,
        )


def _preflight() -> ArchiveRuntimePreflightInputs:
    root = SYNTHETIC_ROOT / "packaging" / "archive" / "7zip-26.02"
    private = SYNTHETIC_ROOT / "tmp" / "archive-runtime-state"
    return ArchiveRuntimePreflightInputs(
        root / "archive-image.lock.json",
        root / "archive-runtime-release.json",
        root / "archive-runtime-revocations.json",
        root / "archive-runtime-evidence",
        private / "state",
        private,
        SYNTHETIC_ROOT / "cache" / "archive-runtime.oci.tar",
    )


def _request() -> ArchiveContainerRequest:
    volume = ArchiveVolumeSource(
        SYNTHETIC_ROOT / "artifacts" / "synthetic-scan" / "archive.fixture",
        9,
        "1" * 64,
        "archive",
    )
    return ArchiveContainerRequest(
        (volume,),
        build_7zzs_information_command(),
        (SYNTHETIC_ROOT / "artifacts" / "synthetic-scan",),
    )


def _runner(
    monkeypatch: pytest.MonkeyPatch,
    process: _FakeProcess,
    *,
    cleanup_ok: bool = True,
    available: bool = True,
    image_reference: str = IMAGE_REFERENCE,
    monotonic: _Clock | None = None,
) -> tuple[
    ArchiveLinuxContainerRunner,
    _FakeFilesystem,
    _FakeDocker,
    _Availability,
    list[str],
]:
    events: list[str] = []
    filesystem = _FakeFilesystem(events, cleanup_ok=cleanup_ok)
    docker = _FakeDocker(events)
    availability = _Availability(
        events, available=available, image_reference=image_reference
    )
    monkeypatch.setattr(
        container_sandbox_module,
        "archive_7zip_runtime_availability",
        availability,
    )
    process_runner = ArchiveProcessRunner(
        _FakeLauncher(process, events),
        monotonic=monotonic or (lambda: 0.0),
    )
    runner = ArchiveLinuxContainerRunner(
        temp_root=filesystem.sandbox.temp_root,
        runtime_preflight=_preflight(),
        filesystem=filesystem,
        docker=docker,
        process_runner=process_runner,
    )
    return runner, filesystem, docker, availability, events


def test_request_rejects_extraction_until_ebar06_live_workspace_contract() -> None:
    volume = _request().volumes[0]
    with pytest.raises(ValueError):
        ArchiveContainerRequest(
            (volume,),
            build_7zzs_extraction_command(),
            (SYNTHETIC_ROOT / "artifacts" / "synthetic-scan",),
        )


def test_unavailable_authority_stops_before_staging_and_receives_every_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, filesystem, _docker, availability, events = _runner(
        monkeypatch, _FakeProcess(), available=False
    )
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TOOL_UNAVAILABLE
    assert filesystem.stage_calls == 0
    assert events == ["availability"]
    assert availability.kwargs["private_state_parent"] == _preflight().private_state_parent
    assert availability.kwargs["local_state_root"] == _preflight().local_state_root
    assert availability.kwargs["oci_layout_path"] == _preflight().oci_layout_path
    assert availability.kwargs["scan_roots"] == _request().scan_roots


def test_non_linux_platform_stops_before_authority_or_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, filesystem, _docker, availability, events = _runner(
        monkeypatch, _FakeProcess()
    )
    filesystem.supports_linux_sandbox = False
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TOOL_UNAVAILABLE
    assert filesystem.stage_calls == 0
    assert availability.kwargs == {}
    assert events == []


def test_available_but_unapproved_digest_cannot_bypass_fixed_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unapproved = (
        f"{ARCHIVE_IMAGE_REFERENCE}@"
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    runner, filesystem, _docker, _availability, events = _runner(
        monkeypatch,
        _FakeProcess(),
        image_reference=unapproved,
    )
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TOOL_UNAVAILABLE
    assert filesystem.stage_calls == 0
    assert events == ["availability"]
    assert "availability_verifier" not in inspect.signature(
        ArchiveLinuxContainerRunner
    ).parameters


def test_success_uses_exact_docker_contract_and_decides_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess((b"bounded",), exit_code=0)
    runner, _filesystem, docker, _availability, events = _runner(monkeypatch, process)
    consumed: list[bytes] = []
    result = runner.run(
        _request(),
        stdout_consumer=lambda chunk: consumed.append(chunk) is None,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.COMPLETED
    assert consumed == [b"bounded"]
    assert docker.created_argv is not None
    argv = docker.created_argv
    assert argv[:5] == (
        docker.executable,
        "create",
        "--name",
        argv[3],
        "--pull=never",
    )
    assert "--pull" not in argv
    assert argv[argv.index("--platform") + 1] == "linux/amd64"
    assert argv.count("--log-driver=none") == 1
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert argv.count("--mount") == 2
    assert "--device" not in argv and "--privileged" not in argv
    assert argv[-1:] == ("i",)
    assert "/usr/local/bin/7zzs" not in argv[argv.index(IMAGE_REFERENCE) + 1 :]
    assert events.index("availability") < events.index("stage")
    assert events.index("remove") < events.index("verify-after") < events.index("cleanup")
    assert process.closed is True


@pytest.mark.parametrize(
    ("section", "key", "unsafe_value"),
    [
        ("root", "Platform", "windows"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "LogConfig", {"Type": "json-file", "Config": {}}),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "SecurityOpt", ["no-new-privileges=true"]),
        ("HostConfig", "Devices", [{"PathOnHost": "/dev/null"}]),
        ("HostConfig", "DeviceRequests", [{"Count": -1}]),
        ("HostConfig", "DeviceCgroupRules", ["c *:* rwm"]),
        ("HostConfig", "PidsLimit", 17),
        ("HostConfig", "Memory", 2_147_483_648),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "NanoCpus", 2_000_000_000),
    ],
)
def test_post_create_projection_rejects_security_mutation(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
    unsafe_value: object,
) -> None:
    runner, filesystem, docker, _availability, _events = _runner(
        monkeypatch, _FakeProcess(exit_code=0)
    )
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.COMPLETED
    inspection = copy.deepcopy(docker.inspect_container(CONTAINER_ID))
    assert inspection is not None
    target = inspection if section == "root" else inspection[section]
    target[key] = unsafe_value
    assert not verify_container_projection(
        inspection,
        container_id=CONTAINER_ID,
        container_name=docker.created_argv[docker.created_argv.index("--name") + 1],
        image_reference=IMAGE_REFERENCE,
        command=_request().command,
        input_root=filesystem.sandbox.input_root,
        output_root=filesystem.sandbox.output_root,
    )


def test_timeout_kills_and_removes_container_before_workspace_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(exit_code=None)
    events: list[str]
    runner, _filesystem, docker, _availability, events = _runner(
        monkeypatch, process, monotonic=_Clock()
    )
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TIMED_OUT
    assert docker.kill_calls == 1
    assert events.index("kill") < events.index("remove") < events.index("cleanup")


def test_ambiguous_create_failure_is_removed_by_opaque_name_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _filesystem, docker, _availability, events = _runner(
        monkeypatch, _FakeProcess()
    )

    def ambiguous_create(argv: tuple[str, ...]) -> None:
        docker.created_argv = argv
        events.append("create")
        return None

    docker.create_container = ambiguous_create  # type: ignore[method-assign]
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TOOL_UNAVAILABLE
    assert events.index("create") < events.index("remove") < events.index("absence")
    assert events.index("absence") < events.index("cleanup")


def test_cleanup_failure_overrides_an_otherwise_successful_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _filesystem, _docker, _availability, events = _runner(
        monkeypatch, _FakeProcess(exit_code=0), cleanup_ok=False
    )
    result = runner.run(
        _request(),
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    assert result.status is ArchiveContainerRunStatus.TOOL_FAILED
    assert events[-1] == "cleanup"


def test_result_and_request_repr_do_not_expose_source_or_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    runner, _filesystem, _docker, _availability, _events = _runner(
        monkeypatch, _FakeProcess(exit_code=0)
    )
    result = runner.run(
        request,
        stdout_consumer=lambda _chunk: True,
        stderr_classifier=lambda _chunk: True,
    )
    rendered = repr(request) + repr(_preflight()) + repr(result)
    assert "synthetic-scan" not in rendered
    assert "archive-runtime-state" not in rendered
    assert "archive-runtime.oci" not in rendered
    assert "bounded" not in rendered


def test_listing_shape_remains_accepted_without_free_argv() -> None:
    base = _request()
    request = ArchiveContainerRequest(base.volumes, build_7zzs_listing_command(), base.scan_roots)
    assert request.command == build_7zzs_listing_command()
