"""Conservative selective re-analysis decisions for ToolProvider evidence."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from foliotone.core._validation import require_non_empty
from foliotone.core.enums import ToolCapability, ToolExecutionStatus
from foliotone.tooling.contracts import ToolExecution, ToolProviderDescriptor


def requires_reanalysis(
    previous: ToolExecution | None,
    descriptor: ToolProviderDescriptor,
    capability: ToolCapability,
    *,
    tool_version: str,
    input_identity: str,
    config_identity: str | None,
) -> bool:
    """Return whether prior tool evidence is unsafe to reuse.

    Reuse is deliberately opt-in through an explicit configuration identity.
    That identity is expected to cover the adapter operation/profile and every
    setting that can materially change the structured result.
    """
    normalized_tool_version = require_non_empty(tool_version, "tool_version")
    normalized_input_identity = require_non_empty(input_identity, "input_identity")
    if _looks_like_absolute_path(normalized_input_identity):
        raise ValueError("input_identity must not persist an absolute local path")
    if capability not in descriptor.capabilities:
        raise ValueError(f"provider does not declare capability {capability.value}")

    if config_identity is None:
        return True
    normalized_config_identity = require_non_empty(config_identity, "config_identity")
    if previous is None or previous.status is not ToolExecutionStatus.SUCCEEDED:
        return True

    return (
        previous.provider_id != descriptor.provider_id
        or previous.capability is not capability
        or previous.input_identity != normalized_input_identity
        or previous.tool_version != normalized_tool_version
        or previous.adapter_version != descriptor.adapter_version
        or previous.config_identity != normalized_config_identity
    )


def _looks_like_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
