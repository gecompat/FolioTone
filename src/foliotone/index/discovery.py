"""Streaming filesystem discovery for configured scan roots."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from foliotone.core._validation import require_relative_path


@dataclass(frozen=True, slots=True)
class ScanRootBinding:
    """Runtime-only binding from a logical ScanRoot to a host/container path."""

    path: Path
    include_suffixes: frozenset[str] | None = None
    follow_symlinks: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path.expanduser())
        if self.include_suffixes is not None:
            normalized = frozenset(_normalize_suffix(value) for value in self.include_suffixes)
            object.__setattr__(self, "include_suffixes", normalized)


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    """One regular file discovered beneath a configured root."""

    relative_path: str
    size_bytes: int
    modified_at: datetime
    physical_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "relative_path", require_relative_path(self.relative_path))
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")


def discover_files(binding: ScanRootBinding) -> Iterator[DiscoveredFile]:
    """Yield regular files without building a collection-wide path list in memory."""
    root = binding.path
    if not root.is_dir():
        raise FileNotFoundError(f"scan root is unavailable or not a directory: {root}")

    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink() and not binding.follow_symlinks:
                    continue
                if entry.is_dir(follow_symlinks=binding.follow_symlinks):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=binding.follow_symlinks):
                    continue

                physical_path = Path(entry.path)
                if not _included(physical_path, binding.include_suffixes):
                    continue
                stat = entry.stat(follow_symlinks=binding.follow_symlinks)
                relative = physical_path.relative_to(root).as_posix()
                yield DiscoveredFile(
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    physical_path=physical_path,
                )


def _normalize_suffix(value: str) -> str:
    suffix = value.strip().lower()
    if not suffix:
        raise ValueError("include suffix must not be empty")
    return suffix if suffix.startswith(".") else f".{suffix}"


def _included(path: Path, suffixes: frozenset[str] | None) -> bool:
    return suffixes is None or path.suffix.lower() in suffixes
