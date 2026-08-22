"""Private fail-closed capability resolution for the bounded metadata writer."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from foliotone.core import EntityId
from foliotone.metadata_write.contracts import EPUB_TITLE_WRITE_PROFILE

METADATA_WRITE_CAPABILITIES_FILE_ENV: Final = (
    "FOLIOTONE_METADATA_WRITE_CAPABILITIES_FILE"
)
_MAX_CONFIG_BYTES: Final = 64 * 1024
_MAX_CAPABILITIES: Final = 128
_ROOT_FIELDS: Final = frozenset({"capabilities"})
_ENTRY_FIELDS: Final = frozenset(
    {
        "metadata_write_capability_id",
        "scan_root_id",
        "scan_root_directory",
        "recovery_directory",
        "writer_profile",
    }
)


class MetadataWriteCapabilityUnavailable(RuntimeError):
    """The requested private runtime mapping cannot be proven safely."""

    def __init__(self) -> None:
        super().__init__("TOOL_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ResolvedMetadataWriteCapability:
    """Runtime-only directories hidden from repr, persistence, and reports."""

    metadata_write_capability_id: EntityId
    scan_root_id: EntityId
    scan_root_directory: Path = field(repr=False)
    recovery_directory: Path = field(repr=False)
    writer_profile: str = EPUB_TITLE_WRITE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.metadata_write_capability_id, EntityId)
            or not isinstance(self.scan_root_id, EntityId)
            or not isinstance(self.scan_root_directory, Path)
            or not isinstance(self.recovery_directory, Path)
            or not self.scan_root_directory.is_absolute()
            or not self.recovery_directory.is_absolute()
            or self.writer_profile != EPUB_TITLE_WRITE_PROFILE
        ):
            raise MetadataWriteCapabilityUnavailable()


class MetadataWriteCapabilityResolver:
    """Resolve one opaque ID through a protected local JSON file."""

    def resolve(
        self,
        metadata_write_capability_id: EntityId,
    ) -> ResolvedMetadataWriteCapability:
        try:
            if not isinstance(metadata_write_capability_id, EntityId):
                raise MetadataWriteCapabilityUnavailable()
            values = _load_configuration()
            _verify_no_overlapping_directories(values)
            for value in values:
                if value.metadata_write_capability_id == metadata_write_capability_id:
                    return value
        except MetadataWriteCapabilityUnavailable:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        raise MetadataWriteCapabilityUnavailable()


def _load_configuration() -> tuple[ResolvedMetadataWriteCapability, ...]:
    configured = os.environ.get(METADATA_WRITE_CAPABILITIES_FILE_ENV)
    if not configured:
        raise MetadataWriteCapabilityUnavailable()
    config_path = Path(configured)
    _verify_regular_path(config_path, final_directory=False)
    _verify_configuration_protection(config_path)
    document = json.loads(_read_bounded(config_path), object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or set(document) != _ROOT_FIELDS:
        raise MetadataWriteCapabilityUnavailable()
    entries = document["capabilities"]
    if not isinstance(entries, list) or not entries or len(entries) > _MAX_CAPABILITIES:
        raise MetadataWriteCapabilityUnavailable()
    values = tuple(_parse_entry(entry) for entry in entries)
    if len({value.metadata_write_capability_id for value in values}) != len(values):
        raise MetadataWriteCapabilityUnavailable()
    if len({value.scan_root_id for value in values}) != len(values):
        raise MetadataWriteCapabilityUnavailable()
    return values


def _parse_entry(entry: object) -> ResolvedMetadataWriteCapability:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
        raise MetadataWriteCapabilityUnavailable()
    capability_id = _parse_id(entry["metadata_write_capability_id"])
    scan_root_id = _parse_id(entry["scan_root_id"])
    scan_root = _parse_directory(entry["scan_root_directory"])
    recovery = _parse_directory(entry["recovery_directory"])
    writer_profile = entry["writer_profile"]
    if writer_profile != EPUB_TITLE_WRITE_PROFILE:
        raise MetadataWriteCapabilityUnavailable()
    try:
        if os.stat(scan_root).st_dev != os.stat(recovery).st_dev:
            raise MetadataWriteCapabilityUnavailable()
    except OSError:
        raise MetadataWriteCapabilityUnavailable() from None
    return ResolvedMetadataWriteCapability(
        capability_id,
        scan_root_id,
        scan_root,
        recovery,
        writer_profile,
    )


def _parse_id(value: object) -> EntityId:
    if not isinstance(value, str):
        raise MetadataWriteCapabilityUnavailable()
    try:
        return EntityId.parse(value)
    except (TypeError, ValueError):
        raise MetadataWriteCapabilityUnavailable() from None


def _parse_directory(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise MetadataWriteCapabilityUnavailable()
    path = Path(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise MetadataWriteCapabilityUnavailable()
    _verify_regular_path(path, final_directory=True)
    return path


def _verify_no_overlapping_directories(
    values: tuple[ResolvedMetadataWriteCapability, ...],
) -> None:
    directories = tuple(
        directory
        for value in values
        for directory in (value.scan_root_directory, value.recovery_directory)
    )
    for index, left in enumerate(directories):
        for right in directories[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise MetadataWriteCapabilityUnavailable()


def _read_bounded(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if os.name == "posix":
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if not isinstance(no_follow, int) or no_follow == 0:
            raise MetadataWriteCapabilityUnavailable()
        flags |= no_follow
    descriptor = os.open(path, flags)
    try:
        _verify_open_configuration(path, descriptor)
        data = os.read(descriptor, _MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES or os.read(descriptor, 1):
            raise MetadataWriteCapabilityUnavailable()
    finally:
        os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise MetadataWriteCapabilityUnavailable() from None


def _verify_regular_path(path: Path, *, final_directory: bool) -> None:
    if not path.is_absolute() or not path.anchor:
        raise MetadataWriteCapabilityUnavailable()
    current = Path(path.anchor)
    parts = path.parts[1:]
    if not parts:
        raise MetadataWriteCapabilityUnavailable()
    for index, part in enumerate(parts):
        current /= part
        try:
            details = os.lstat(current)
        except OSError:
            raise MetadataWriteCapabilityUnavailable() from None
        is_final = index == len(parts) - 1
        if stat.S_ISLNK(details.st_mode) or _is_reparse(details):
            raise MetadataWriteCapabilityUnavailable()
        if (not is_final or final_directory) and not stat.S_ISDIR(details.st_mode):
            raise MetadataWriteCapabilityUnavailable()
        if is_final and not final_directory and not stat.S_ISREG(details.st_mode):
            raise MetadataWriteCapabilityUnavailable()


def _verify_configuration_protection(path: Path) -> None:
    """Require an owner-only POSIX regular file; unsupported checks fail closed."""

    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or not callable(geteuid):
        raise MetadataWriteCapabilityUnavailable()


def _verify_open_configuration(path: Path, descriptor: int) -> None:
    """Re-check the protected inode after the no-follow open."""

    if os.name != "posix":
        return
    geteuid = getattr(os, "geteuid", None)
    if not callable(geteuid):
        raise MetadataWriteCapabilityUnavailable()
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
    except OSError:
        raise MetadataWriteCapabilityUnavailable() from None
    if (
        opened.st_dev != named.st_dev
        or opened.st_ino != named.st_ino
        or not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
        or opened.st_uid != geteuid()
        or _is_reparse(opened)
    ):
        raise MetadataWriteCapabilityUnavailable()
    try:
        details = os.lstat(path)
    except OSError:
        raise MetadataWriteCapabilityUnavailable() from None
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != geteuid()
        or _is_reparse(details)
    ):
        raise MetadataWriteCapabilityUnavailable()


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MetadataWriteCapabilityUnavailable()
        result[key] = value
    return result


__all__ = [
    "METADATA_WRITE_CAPABILITIES_FILE_ENV",
    "MetadataWriteCapabilityResolver",
    "MetadataWriteCapabilityUnavailable",
    "ResolvedMetadataWriteCapability",
]
