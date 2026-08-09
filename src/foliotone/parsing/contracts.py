"""Versioned, provenance-preserving filename and path candidates."""
from __future__ import annotations

import re
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


@dataclass(frozen=True, slots=True)
class FilenameParsingRule:
    """One configurable regular-expression rule for filename candidates.

    Each named capture group becomes a derived ``FieldCandidate``. Rules are
    deliberately data-only: they neither resolve entities nor select canonical
    metadata values.
    """

    name: str
    pattern: str
    confidence: float = 0.5

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "name"))
        object.__setattr__(self, "pattern", require_non_empty(self.pattern, "pattern"))
        require_confidence(self.confidence)
        try:
            compiled = re.compile(self.pattern)
        except re.error as error:
            raise ValueError(f"pattern is not a valid regular expression: {error}") from error
        if not compiled.groupindex:
            raise ValueError("pattern must contain at least one named capture group")


@dataclass(frozen=True, slots=True)
class FilenameParsingProfile:
    """Versioned, ordered filename rules for one collection convention."""

    version: str
    rules: tuple[FilenameParsingRule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))
        if not self.rules:
            raise ValueError("rules must not be empty")
        names = [rule.name for rule in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("rule names must be unique within a profile")


@dataclass(frozen=True, slots=True)
class RuleBasedFilenameParser:
    """Emit candidates from the first matching rule in a versioned profile."""

    profile: FilenameParsingProfile

    def parse(self, filename: str, *, observed_at: datetime) -> tuple[FieldCandidate, ...]:
        normalized_filename = require_non_empty(filename, "filename")
        if "/" in normalized_filename or "\\" in normalized_filename:
            raise ValueError("filename must not include path separators")

        stem = PurePosixPath(normalized_filename).stem
        for rule in self.profile.rules:
            match = re.fullmatch(rule.pattern, stem)
            if match is None:
                continue
            candidates = tuple(
                FieldCandidate(
                    field_name=field_name,
                    value=value,
                    source_location=f"filename.rule.{rule.name}.{field_name}",
                    provenance=Provenance(
                        source_kind="derived",
                        source_name=type(self).__name__,
                        observed_at=observed_at,
                        source_version=self.profile.version,
                    ),
                    confidence=rule.confidence,
                )
                for field_name, raw_value in match.groupdict().items()
                if (value := raw_value.strip() if raw_value is not None else "")
            )
            if candidates:
                return candidates
        return ()
