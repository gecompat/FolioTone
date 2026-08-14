import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.core import ToolCapability, ToolExecutionStatus
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.tooling import StructuredOutputError, ToolArtifact, ToolProviderDescriptor
from foliotone.tooling.runtime import (
    ContainerCommand,
    LocalCommand,
    ReadOnlyMount,
    ToolRuntime,
    WorkspaceOutput,
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
    assert (tmp_path / "artifacts" / outcome.artifacts[0].relative_path).read_bytes() == (
        b"hello from tool\r\n" if sys.platform == "win32" else b"hello from tool\n"
    )


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
    assert {artifact.id: artifact for artifact in stored} == {
        artifact.id: artifact for artifact in outcome.artifacts
    }


def test_structured_stdout_is_loaded_from_the_integrity_checked_artifact(tmp_path: Path) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "import json; print(json.dumps({'duration': 12.5, 'streams': [1]}))"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:json",
    )

    assert tool_runtime.read_json_stdout(outcome) == {"duration": 12.5, "streams": [1]}


def test_malformed_structured_stdout_preserves_the_auditable_execution(
    tmp_path: Path,
) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "print('{malformed-json')"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:malformed-json",
    )

    with pytest.raises(StructuredOutputError, match="valid UTF-8 JSON"):
        tool_runtime.read_json_stdout(outcome)

    assert outcome.execution.status is ToolExecutionStatus.SUCCEEDED
    assert {artifact.artifact_type for artifact in outcome.artifacts} == {"STDOUT", "STDERR"}


def test_structured_stdout_rejects_size_limit_and_artifact_integrity_changes(
    tmp_path: Path,
) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "print('{\"ok\": true}')"),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:guarded-json",
    )

    with pytest.raises(StructuredOutputError, match="size limit"):
        tool_runtime.read_json_stdout(outcome, max_bytes=1)

    stdout = next(artifact for artifact in outcome.artifacts if artifact.artifact_type == "STDOUT")
    artifact_path = tmp_path / "artifacts" / stdout.relative_path
    artifact_path.write_bytes(b"x" * stdout.size_bytes)
    with pytest.raises(StructuredOutputError, match="integrity check"):
        tool_runtime.read_json_stdout(outcome)


def test_missing_structured_stdout_is_reported_without_inventing_an_artifact(
    tmp_path: Path,
) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable="foliotone-definitely-missing-structured-tool",
            args=(),
            capability=ToolCapability.STATUS_REPORT,
        ),
        input_identity="synthetic:missing-structured-tool",
    )

    with pytest.raises(StructuredOutputError, match="exactly one"):
        tool_runtime.read_json_stdout(outcome)

    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert outcome.artifacts == ()


def test_required_workspace_output_is_bounded_persisted_and_work_is_removed(
    tmp_path: Path,
) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=(
                "-c",
                "from pathlib import Path; Path('metadata.opf').write_bytes(b'<package/>')",
            ),
            capability=ToolCapability.STATUS_REPORT,
            outputs=(WorkspaceOutput("TEST_OPF", "metadata.opf", max_bytes=1024),),
        ),
        input_identity="synthetic:workspace-output",
    )

    assert outcome.execution.status is ToolExecutionStatus.SUCCEEDED
    output = next(
        artifact for artifact in outcome.artifacts if artifact.artifact_type == "TEST_OPF"
    )
    assert tool_runtime.read_artifact_bytes(output, max_bytes=1024) == b"<package/>"
    assert list((tmp_path / "work").iterdir()) == []


def test_missing_required_workspace_output_fails_an_otherwise_successful_process(
    tmp_path: Path,
) -> None:
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", "print('no declared output')"),
            capability=ToolCapability.STATUS_REPORT,
            outputs=(WorkspaceOutput("TEST_OPF", "metadata.opf"),),
        ),
        input_identity="synthetic:missing-workspace-output",
    )

    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert outcome.execution.exit_code == 0
    assert outcome.execution.error_summary is not None
    assert "required workspace output" in outcome.execution.error_summary
    assert {artifact.artifact_type for artifact in outcome.artifacts} == {"STDOUT", "STDERR"}


def test_oversized_workspace_output_is_not_persisted(tmp_path: Path) -> None:
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=(
                "-c",
                "from pathlib import Path; Path('metadata.opf').write_bytes(b'x' * 9)",
            ),
            capability=ToolCapability.STATUS_REPORT,
            outputs=(WorkspaceOutput("TEST_OPF", "metadata.opf", max_bytes=8),),
        ),
        input_identity="synthetic:oversized-workspace-output",
    )

    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert "TEST_OPF" not in {artifact.artifact_type for artifact in outcome.artifacts}


def test_workspace_environment_is_private_and_removed_after_execution(tmp_path: Path) -> None:
    tool_runtime = runtime(tmp_path)
    outcome = tool_runtime.execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=(
                "-c",
                "import os; from pathlib import Path; "
                "p=Path(os.environ['TEST_CONFIG']); "
                "Path('result.txt').write_text(str(p.is_dir() and p.parent == Path.cwd()))",
            ),
            capability=ToolCapability.STATUS_REPORT,
            workspace_environment={"TEST_CONFIG": "private-config"},
            outputs=(WorkspaceOutput("TEST_RESULT", "result.txt"),),
        ),
        input_identity="synthetic:workspace-environment",
    )

    result = next(
        artifact for artifact in outcome.artifacts if artifact.artifact_type == "TEST_RESULT"
    )
    assert tool_runtime.read_artifact_bytes(result) == b"True"
    assert list((tmp_path / "work").iterdir()) == []


def test_version_policy_blocks_the_target_command_before_it_runs(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    outcome = runtime(tmp_path).execute_local(
        descriptor(),
        LocalCommand(
            executable=sys.executable,
            args=("-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"),
            capability=ToolCapability.STATUS_REPORT,
            version_policy=lambda _version: "blocked by test version policy",
        ),
        input_identity="synthetic:blocked-version",
    )

    assert outcome.execution.status is ToolExecutionStatus.FAILED
    assert outcome.execution.error_summary == "blocked by test version policy"
    assert outcome.artifacts == ()
    assert not marker.exists()
    assert list((tmp_path / "work").iterdir()) == []


@pytest.mark.parametrize("relative_path", ("../escape", "C:/absolute", "/absolute"))
def test_workspace_output_rejects_unsafe_paths(relative_path: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        WorkspaceOutput("TEST", relative_path)
