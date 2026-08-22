"""Private, fail-closed runtime resolution for quarantine capabilities.

The configuration is intentionally not a project artifact: it is read only
from the environment-selected local file and none of its values are suitable
for persistence, logs, reports, or public DTOs.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from foliotone.core import EntityId

CAPABILITIES_FILE_ENV: Final = "FOLIOTONE_QUARANTINE_CAPABILITIES_FILE"
_MAX_CONFIG_BYTES: Final = 64 * 1024
_MAX_CAPABILITIES: Final = 128
_ROOT_FIELDS: Final = frozenset({"capabilities"})
_ENTRY_FIELDS: Final = frozenset(
    {
        "quarantine_capability_id",
        "scan_root_id",
        "scan_root_directory",
        "quarantine_directory",
    }
)


class QuarantineCapabilityUnavailable(RuntimeError):
    """A private runtime capability cannot be established safely."""

    def __init__(self) -> None:
        super().__init__("TOOL_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ResolvedQuarantineCapability:
    """Private runtime-only capability; paths are deliberately redacted from repr."""

    quarantine_capability_id: EntityId
    scan_root_id: EntityId
    scan_root_directory: Path = field(repr=False)
    quarantine_directory: Path = field(repr=False)


class QuarantineCapabilityResolver:
    """Resolve opaque IDs through one protected local JSON configuration file."""

    def resolve(self, quarantine_capability_id: EntityId) -> ResolvedQuarantineCapability:
        """Return exactly one private mapping or fail closed with ``TOOL_UNAVAILABLE``."""

        try:
            values = _load_configuration()
            _verify_no_overlapping_roots(values)
            for value in values:
                if value.quarantine_capability_id == quarantine_capability_id:
                    return value
        except QuarantineCapabilityUnavailable:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        raise QuarantineCapabilityUnavailable()


def _load_configuration() -> tuple[ResolvedQuarantineCapability, ...]:
    configured = os.environ.get(CAPABILITIES_FILE_ENV)
    if not configured:
        raise QuarantineCapabilityUnavailable()
    config_path = Path(configured)
    _verify_regular_path(config_path, final_directory=False)
    _verify_configuration_protection(config_path)
    raw = _read_bounded(config_path)
    document = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or set(document) != _ROOT_FIELDS:
        raise QuarantineCapabilityUnavailable()
    entries = document["capabilities"]
    if not isinstance(entries, list) or not entries or len(entries) > _MAX_CAPABILITIES:
        raise QuarantineCapabilityUnavailable()
    values = tuple(_parse_entry(entry) for entry in entries)
    if len({value.quarantine_capability_id for value in values}) != len(values):
        raise QuarantineCapabilityUnavailable()
    if len({value.scan_root_id for value in values}) != len(values):
        raise QuarantineCapabilityUnavailable()
    return values


def _parse_entry(entry: object) -> ResolvedQuarantineCapability:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
        raise QuarantineCapabilityUnavailable()
    capability_id = _parse_id(entry["quarantine_capability_id"])
    scan_root_id = _parse_id(entry["scan_root_id"])
    scan_root = _parse_directory(entry["scan_root_directory"])
    quarantine = _parse_directory(entry["quarantine_directory"])
    return ResolvedQuarantineCapability(capability_id, scan_root_id, scan_root, quarantine)


def _parse_id(value: object) -> EntityId:
    if not isinstance(value, str):
        raise QuarantineCapabilityUnavailable()
    try:
        return EntityId.parse(value)
    except (TypeError, ValueError):
        raise QuarantineCapabilityUnavailable() from None


def _parse_directory(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise QuarantineCapabilityUnavailable()
    path = Path(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise QuarantineCapabilityUnavailable()
    _verify_regular_path(path, final_directory=True)
    return path


def _verify_no_overlapping_roots(values: tuple[ResolvedQuarantineCapability, ...]) -> None:
    directories = tuple(
        directory
        for value in values
        for directory in (value.scan_root_directory, value.quarantine_directory)
    )
    for index, left in enumerate(directories):
        for right in directories[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise QuarantineCapabilityUnavailable()


def _read_bounded(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        data = os.read(descriptor, _MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES or os.read(descriptor, 1):
            raise QuarantineCapabilityUnavailable()
    finally:
        os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise QuarantineCapabilityUnavailable() from None


def _verify_regular_path(path: Path, *, final_directory: bool) -> None:
    if not path.is_absolute() or not path.anchor:
        raise QuarantineCapabilityUnavailable()
    current = Path(path.anchor)
    parts = path.parts[1:]
    if not parts:
        raise QuarantineCapabilityUnavailable()
    for index, part in enumerate(parts):
        current /= part
        try:
            details = os.lstat(current)
        except OSError:
            raise QuarantineCapabilityUnavailable() from None
        is_final = index == len(parts) - 1
        if stat.S_ISLNK(details.st_mode) or _is_reparse(details):
            raise QuarantineCapabilityUnavailable()
        if (not is_final or final_directory) and not stat.S_ISDIR(details.st_mode):
            raise QuarantineCapabilityUnavailable()
        if is_final and not final_directory and not stat.S_ISREG(details.st_mode):
            raise QuarantineCapabilityUnavailable()


def _verify_configuration_protection(path: Path) -> None:
    """Require a POSIX owner-only regular file; unsupported checks fail closed."""

    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or not callable(geteuid):
        raise QuarantineCapabilityUnavailable()
    try:
        details = os.lstat(path)
    except OSError:
        raise QuarantineCapabilityUnavailable() from None
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != geteuid()
        or _is_reparse(details)
    ):
        raise QuarantineCapabilityUnavailable()


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise QuarantineCapabilityUnavailable()
        result[key] = value
    return result
