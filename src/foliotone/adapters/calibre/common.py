"""Shared safety contracts for calibre file-analysis adapters."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from foliotone.core import FileObservation

MINIMUM_SAFE_CALIBRE_VERSION = (9, 10, 0)

_VERSION_PATTERN = re.compile(
    r"\bcalibre\s+(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?",
    re.IGNORECASE,
)


class CalibreAdapterError(RuntimeError):
    """A safe failure shared by calibre adapters."""


def calibre_version_policy(version_text: str) -> str | None:
    """Reject unknown or vulnerable calibre versions before opening source media."""
    match = _VERSION_PATTERN.search(version_text)
    if match is None:
        return "calibre version is unrecognized; source analysis was not started"
    version = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )
    if version < MINIMUM_SAFE_CALIBRE_VERSION:
        return "calibre 9.10.0 or newer is required; source analysis was not started"
    return None


def validated_observed_file(source_root: Path, observation: FileObservation) -> Path:
    """Resolve one unchanged observation without allowing path escape or symlinks."""
    try:
        root = source_root.resolve(strict=True)
    except OSError as error:
        raise CalibreAdapterError("source root is unavailable") from error
    if not root.is_dir():
        raise CalibreAdapterError("source root is not a directory")

    relative = Path(*PurePosixPath(observation.relative_path).parts)
    source = root / relative
    try:
        if source.is_symlink():
            raise CalibreAdapterError("symbolic-link source files are not analyzed")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise CalibreAdapterError("observed source file is unavailable")
        stat = resolved.stat()
    except OSError as error:
        raise CalibreAdapterError("observed source file is unavailable") from error

    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    if stat.st_size != observation.size_bytes or modified_at != observation.modified_at:
        raise CalibreAdapterError("source file changed after its recorded observation")
    return resolved
