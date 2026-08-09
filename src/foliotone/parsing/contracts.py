"""Versioned, provenance-preserving filename and path candidates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from foliotone.core._validation import (
    require_confidence,
    require_non_empty,
    require_relative_path,
)
from foliotone.core.common import Provenance


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    field_name: str
    value: str
    source_location: str
    provenance: Provenance
    confidence: float

    def __post_init__(self) -> None:
        for name in ("field_name", "value", "source_location"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        require_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class FilenameParser:
    """Emit a low-confidence title candidate from one observed filename."""

    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))

    def parse(self, filename: str, *, observed_at: datetime) -> tuple[FieldCandidate, ...]:
        """Return a derived title candidate without interpreting filename conventions."""
        normalized_filename = require_non_empty(filename, "filename")
        if "/" in normalized_filename or "\\" in normalized_filename:
            raise ValueError("filename must not include path separators")

        stem = PurePosixPath(normalized_filename).stem
        if not stem:
            return ()
        return (
            FieldCandidate(
                field_name="title",
                value=stem,
                source_location="filename.stem",
                provenance=Provenance(
                    source_kind="derived",
                    source_name=type(self).__name__,
                    observed_at=observed_at,
                    source_version=self.version,
                ),
                confidence=0.2,
            ),
        )


@dataclass(frozen=True, slots=True)
class PathContextAnalyzer:
    """Emit a low-confidence candidate from the direct parent of a relative path."""

    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))

    def analyze(self, relative_path: str, *, observed_at: datetime) -> tuple[FieldCandidate, ...]:
        """Return a derived path-context candidate without retaining absolute path data."""
        normalized_path = require_relative_path(relative_path)
        parent = PurePosixPath(normalized_path).parent
        if parent == PurePosixPath("."):
            return ()
        return (
            FieldCandidate(
                field_name="path_context",
                value=parent.name,
                source_location="path.parent",
                provenance=Provenance(
                    source_kind="derived",
                    source_name=type(self).__name__,
                    observed_at=observed_at,
                    source_version=self.version,
                ),
                confidence=0.1,
            ),
        )
