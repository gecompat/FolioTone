from datetime import datetime, timedelta, timezone

import pytest

from foliotone.core import EntityId, EntityKind, ToolCapability, ToolExecutionStatus
from foliotone.tooling import ToolExecution, ToolProviderDescriptor, ToolResult

START = datetime(2026, 8, 8, 20, 0, tzinfo=timezone.utc)
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
