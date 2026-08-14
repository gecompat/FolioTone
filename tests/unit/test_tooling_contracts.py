from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId, EntityKind, ToolCapability, ToolExecutionStatus
from foliotone.tooling import (
    ToolExecution,
    ToolProviderDescriptor,
    ToolResult,
    requires_reanalysis,
)

START = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
FINISH = START + timedelta(seconds=1)


def test_tool_provider_must_be_read_only_before_w10() -> None:
    with pytest.raises(ValueError):
        ToolProviderDescriptor(
            provider_id="unsafe",
            display_name="Unsafe Writer",
            adapter_version="1",
            capabilities=frozenset({ToolCapability.READ_METADATA}),
            default_read_only=False,
        )


def test_tool_provider_requires_capability() -> None:
    with pytest.raises(ValueError):
        ToolProviderDescriptor(
            provider_id="empty",
            display_name="Empty",
            adapter_version="1",
            capabilities=frozenset(),
        )


def test_successful_execution_is_versioned_and_terminal() -> None:
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="ffprobe",
        tool_version="8.0",
        adapter_version="1",
        capability=ToolCapability.TECHNICAL_METADATA,
        input_identity="sha256:synthetic",
        started_at=START,
        finished_at=FINISH,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
        config_identity="default-v1",
    )
    assert execution.provider_id == "ffprobe"
    assert execution.tool_version == "8.0"


def test_terminal_execution_requires_finished_at() -> None:
    with pytest.raises(ValueError):
        ToolExecution(
            id=EntityId.new(),
            provider_id="fpcalc",
            tool_version="1.6",
            adapter_version="1",
            capability=ToolCapability.FINGERPRINT,
            input_identity="sha256:synthetic",
            started_at=START,
            status=ToolExecutionStatus.SUCCEEDED,
        )


def test_tool_result_references_exact_execution() -> None:
    execution_id = EntityId.new()
    result = ToolResult(
        id=EntityId.new(),
        execution_id=execution_id,
        result_type="technical_metadata",
        target_kind=EntityKind.FILE,
        target_id=EntityId.new(),
        key="codec_name",
        value="flac",
        confidence=1.0,
    )
    assert result.execution_id == execution_id


def test_tool_result_confidence_is_bounded() -> None:
    with pytest.raises(ValueError):
        ToolResult(
            id=EntityId.new(),
            execution_id=EntityId.new(),
            result_type="candidate",
            target_kind=EntityKind.RECORDING,
            target_id=EntityId.new(),
            key="match",
            value="synthetic",
            confidence=-0.1,
        )


def test_exact_successful_tool_identity_can_reuse_prior_analysis() -> None:
    provider = ToolProviderDescriptor(
        provider_id="tool",
        display_name="Tool",
        adapter_version="adapter/1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    previous = ToolExecution(
        id=EntityId.new(),
        provider_id="tool",
        tool_version="tool/1",
        adapter_version="adapter/1",
        capability=ToolCapability.STATUS_REPORT,
        input_identity="file-observation:1",
        config_identity="status/default/1",
        started_at=START,
        finished_at=FINISH,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )

    assert not requires_reanalysis(
        previous,
        provider,
        ToolCapability.STATUS_REPORT,
        tool_version="tool/1",
        input_identity="file-observation:1",
        config_identity="status/default/1",
    )


@pytest.mark.parametrize(
    ("adapter_version", "tool_version", "input_identity", "config_identity"),
    (
        ("adapter/2", "tool/1", "file-observation:1", "status/default/1"),
        ("adapter/1", "tool/2", "file-observation:1", "status/default/1"),
        ("adapter/1", "tool/1", "file-observation:2", "status/default/1"),
        ("adapter/1", "tool/1", "file-observation:1", "status/default/2"),
    ),
)
def test_tool_input_or_config_version_change_requires_reanalysis(
    adapter_version: str,
    tool_version: str,
    input_identity: str,
    config_identity: str,
) -> None:
    provider = ToolProviderDescriptor(
        provider_id="tool",
        display_name="Tool",
        adapter_version=adapter_version,
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    previous = ToolExecution(
        id=EntityId.new(),
        provider_id="tool",
        tool_version="tool/1",
        adapter_version="adapter/1",
        capability=ToolCapability.STATUS_REPORT,
        input_identity="file-observation:1",
        config_identity="status/default/1",
        started_at=START,
        finished_at=FINISH,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )

    assert requires_reanalysis(
        previous,
        provider,
        ToolCapability.STATUS_REPORT,
        tool_version=tool_version,
        input_identity=input_identity,
        config_identity=config_identity,
    )


def test_missing_config_identity_never_reuses_prior_analysis() -> None:
    provider = ToolProviderDescriptor(
        provider_id="tool",
        display_name="Tool",
        adapter_version="adapter/1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    previous = ToolExecution(
        id=EntityId.new(),
        provider_id="tool",
        tool_version="tool/1",
        adapter_version="adapter/1",
        capability=ToolCapability.STATUS_REPORT,
        input_identity="file-observation:1",
        config_identity="status/default/1",
        started_at=START,
        finished_at=FINISH,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )

    assert requires_reanalysis(
        previous,
        provider,
        ToolCapability.STATUS_REPORT,
        tool_version="tool/1",
        input_identity="file-observation:1",
        config_identity=None,
    )


def test_failed_tool_execution_is_never_reused() -> None:
    provider = ToolProviderDescriptor(
        provider_id="tool",
        display_name="Tool",
        adapter_version="adapter/1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    failed = ToolExecution(
        id=EntityId.new(),
        provider_id="tool",
        tool_version="tool/1",
        adapter_version="adapter/1",
        capability=ToolCapability.STATUS_REPORT,
        input_identity="file-observation:1",
        config_identity="status/default/1",
        started_at=START,
        finished_at=FINISH,
        status=ToolExecutionStatus.FAILED,
        exit_code=3,
        error_summary="synthetic failure",
    )

    assert requires_reanalysis(
        failed,
        provider,
        ToolCapability.STATUS_REPORT,
        tool_version="tool/1",
        input_identity="file-observation:1",
        config_identity="status/default/1",
    )
