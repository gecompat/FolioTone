import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.core import ToolCapability, ToolExecutionStatus
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.tooling import ToolArtifact, ToolProviderDescriptor
from foliotone.tooling.runtime import (
    ContainerCommand,
    LocalCommand,
    ReadOnlyMount,
    ToolRuntime,
    build_docker_argv,
)

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)


def descriptor() -> ToolProviderDescriptor:
    return ToolProviderDescriptor(
        provider_id="python-test",
        display_name="Python Test Tool",
        adapter_version="1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )


def runtime(tmp_path: Path) -> ToolRuntime:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    return ToolRuntime(
        engine,
        tmp_path / "artifacts",
        work_root=tmp_path / "work",
        preview_bytes=1024,
        clock=lambda: NOW,
    )


def test_local_tool_success_captures_version_stdout_and_artifacts(tmp_path: Path) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "print('hello from tool')"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:1",
    )

    assert outcome.execution.status is ToolExecutionStatus.SUCCEEDED
    assert outcome.execution.exit_code == 0
    assert outcome.execution.tool_version
    assert outcome.stdout_preview == "hello from tool\n"
    assert {artifact.artifact_type for artifact in outcome.artifacts} == {"STDOUT", "STDERR"}
    for artifact in outcome.artifacts:
        assert not Path(artifact.relative_path).is_absolute()
        assert len(artifact.sha256) == 64


def test_nonzero_exit_is_persisted_as_failed(tmp_path: Path) -> None:
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:2",
    )
    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert outcome.execution.exit_code == 3
    assert "bad" in outcome.stderr_preview


def test_timeout_is_cancelled_without_shell(tmp_path: Path) -> None:
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "import time; time.sleep(5)"),
            capability=ToolCapability.STATUS_REPORT,
            timeout_seconds=0.05,
        ),
        input_identity="synthetic:3",
    )
    assert outcome.execution.status is ToolExecutionStatus.CANCELLED
    assert outcome.execution.error_summary is not None
    assert "timeout" in outcome.execution.error_summary


def test_missing_tool_is_a_failed_auditable_execution(tmp_path: Path) -> None:
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable="foliotone-definitely-missing-executable",
            args=(),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:4",
    )
    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert outcome.execution.tool_version == "unavailable"


def test_absolute_path_is_rejected_as_persisted_input_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        runtime(tmp_path).execute_local(
            descriptor(),
            LocalCommand(
                executable=sys.executable,
                args=("-c", "print('never')"),
                capability=ToolCapability.STATUS_REPORT,
            ),
            input_identity=str(tmp_path / "private-file"),
        )


def test_container_command_builder_hardens_defaults_and_mounts_inputs_read_only(
    tmp_path: Path,
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    workspace = tmp_path / "work"
    workspace.mkdir()
    argv = build_docker_argv(
        "docker",
        ContainerCommand(
            image="example/tool@sha256:synthetic",
            args=("scan", "/input"),
            capability=ToolCapability.STATUS_REPORT,
            mounts=(ReadOnlyMount(source, "/input"),),
        ),
        workspace,
    )
    joined = " ".join(argv)
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--network=none" in argv
    assert f"src={source},dst=/input,readonly" in joined
    assert f"src={workspace},dst=/work" in joined


def test_tool_artifacts_round_trip_through_repository(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    tool_runtime = ToolRuntime(engine, tmp_path / "artifacts", clock=lambda: NOW)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "print('artifact')"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:5",
    )
    stored = repository(engine, ToolArtifact).list_all()
    assert stored == list(outcome.artifacts)
