"""Validation helpers shared by immutable core models."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath


def require_non_empty(value: str, field_name: str) -> str:
    """Return a stripped non-empty string or raise ValueError."""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    """Require an explicitly timezone-aware datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def require_confidence(value: float | None, field_name: str = "confidence") -> float | None:
    """Require a probability-like confidence between zero and one."""
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    return value


def require_relative_path(value: str) -> str:
    """Normalize a durable scan-root-relative path to POSIX form."""
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError("relative_path must be a safe scan-root-relative path")
    return path.as_posix()
