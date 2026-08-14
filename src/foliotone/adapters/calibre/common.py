"""Shared safety contracts for calibre file-analysis adapters."""

from __future__ import annotations

import re
from pathlib import Path

from foliotone.analyzers.ebook import ObservedFileError, resolve_observed_file
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
    """Adapt the analyzer-neutral observation guard to calibre's error contract."""
    try:
        return resolve_observed_file(source_root, observation)
    except ObservedFileError as error:
        raise CalibreAdapterError(str(error)) from error
