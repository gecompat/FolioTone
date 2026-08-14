"""Bounded parsing for adapter-neutral JSON ToolProvider output."""

from __future__ import annotations

import json
from typing import Never, cast

DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES = 16 * 1024 * 1024

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class StructuredOutputError(ValueError):
    """A ToolArtifact cannot be consumed as bounded, strict JSON."""


def parse_json_output(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_STRUCTURED_OUTPUT_BYTES,
) -> JsonValue:
    """Parse bounded UTF-8 JSON without exposing malformed payload contents."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(data) > max_bytes:
        raise StructuredOutputError("structured output exceeds the configured size limit")
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(text, parse_constant=_reject_non_standard_number)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise StructuredOutputError("structured output is not valid UTF-8 JSON") from error
    return cast(JsonValue, value)


def _reject_non_standard_number(value: str) -> Never:
    raise ValueError(f"non-standard JSON number is not permitted: {value}")
