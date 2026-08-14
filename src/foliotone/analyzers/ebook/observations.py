"""Analyzer-neutral validation of persisted e-book file observations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from foliotone.core import FileObservation


class ObservedFileError(RuntimeError):
    """A recorded file cannot be analyzed without violating its observation."""


def resolve_observed_file(source_root: Path, observation: FileObservation) -> Path:
    """Resolve one unchanged observation without allowing path escape or symlinks."""
    try:
        root = source_root.resolve(strict=True)
    except OSError as error:
        raise ObservedFileError("source root is unavailable") from error
    if not root.is_dir():
        raise ObservedFileError("source root is not a directory")

    relative = Path(*PurePosixPath(observation.relative_path).parts)
    source = root / relative
    try:
        if source.is_symlink():
            raise ObservedFileError("symbolic-link source files are not analyzed")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ObservedFileError("observed source file is unavailable")
        stat = resolved.stat()
    except OSError as error:
        raise ObservedFileError("observed source file is unavailable") from error

    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    if stat.st_size != observation.size_bytes or modified_at != observation.modified_at:
        raise ObservedFileError("source file changed after its recorded observation")
    return resolved
