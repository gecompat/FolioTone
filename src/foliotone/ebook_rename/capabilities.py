"""Private fail-closed capability resolution for bounded e-book rename."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from foliotone.core import EntityId
from foliotone.ebook_rename.target import EBOOK_RENAME_PROCESSOR_PROFILE

EBOOK_RENAME_CAPABILITIES_FILE_ENV: Final = (
    "FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE"
)
EBOOK_RENAME_CAPABILITY_PROFILE: Final = "ebook-file-rename-capability/v1"

_CONFIGURATION_DOMAIN: Final = b"foliotone:ebook-rename-capability-config/v1\x00"
_MAX_CONFIG_BYTES: Final = 64 * 1024
_MAX_CAPABILITIES: Final = 128
_ROOT_FIELDS: Final = frozenset({"capabilities"})
_ENTRY_FIELDS: Final = frozenset(
    {
        "ebook_rename_capability_id",
        "scan_root_id",
        "scan_root_directory",
        "probe_directory",
        "capability_profile",
        "writer_profile",
        "version",
    }
)


class EbookRenameCapabilityUnavailable(RuntimeError):
    """The requested runtime mapping cannot be proven safely."""

    def __init__(self) -> None:
        super().__init__("TOOL_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class ResolvedEbookRenameCapability:
    """Runtime-only root and probe mapping hidden from persistence and repr."""

    ebook_rename_capability_id: EntityId
    scan_root_id: EntityId
    scan_root_directory: Path = field(repr=False)
    probe_directory: Path = field(repr=False)
    version: int
    configuration_fingerprint: str = field(repr=False)
    capability_profile: str = EBOOK_RENAME_CAPABILITY_PROFILE
    writer_profile: str = EBOOK_RENAME_PROCESSOR_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ebook_rename_capability_id, EntityId)
            or not isinstance(self.scan_root_id, EntityId)
            or not isinstance(self.scan_root_directory, Path)
            or not isinstance(self.probe_directory, Path)
            or not self.scan_root_directory.is_absolute()
            or not self.probe_directory.is_absolute()
            or isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version <= 0
            or self.capability_profile != EBOOK_RENAME_CAPABILITY_PROFILE
            or self.writer_profile != EBOOK_RENAME_PROCESSOR_PROFILE
            or not _is_sha256(self.configuration_fingerprint)
        ):
            raise EbookRenameCapabilityUnavailable()


class EbookRenameCapabilityResolver:
    """Resolve one opaque capability through a protected local JSON file."""

    def __init__(self, *, protected_paths: Iterable[Path] = ()) -> None:
        try:
            self._protected_paths = tuple(_absolute_path(path) for path in protected_paths)
        except (OSError, TypeError, ValueError):
            raise EbookRenameCapabilityUnavailable() from None

    def resolve(
        self,
        ebook_rename_capability_id: EntityId,
    ) -> ResolvedEbookRenameCapability:
        try:
            if not isinstance(ebook_rename_capability_id, EntityId):
                raise EbookRenameCapabilityUnavailable()
            config_path, values = _load_configuration()
            _verify_no_overlapping_capabilities(values)
            _verify_protected_boundaries(
                values,
                (
                    config_path,
                    *_default_protected_paths(),
                    *self._protected_paths,
                ),
            )
            for value in values:
                if value.ebook_rename_capability_id == ebook_rename_capability_id:
                    return value
        except EbookRenameCapabilityUnavailable:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        raise EbookRenameCapabilityUnavailable()


def _load_configuration() -> tuple[Path, tuple[ResolvedEbookRenameCapability, ...]]:
    configured = os.environ.get(EBOOK_RENAME_CAPABILITIES_FILE_ENV)
    if not configured:
        raise EbookRenameCapabilityUnavailable()
    config_path = _absolute_path(Path(configured))
    _verify_regular_path(config_path, final_directory=False)
    _verify_configuration_protection(config_path)
    document = json.loads(_read_bounded(config_path), object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or set(document) != _ROOT_FIELDS:
        raise EbookRenameCapabilityUnavailable()
    entries = document["capabilities"]
    if not isinstance(entries, list) or not entries or len(entries) > _MAX_CAPABILITIES:
        raise EbookRenameCapabilityUnavailable()
    values = tuple(_parse_entry(entry) for entry in entries)
    if len({value.ebook_rename_capability_id for value in values}) != len(values):
        raise EbookRenameCapabilityUnavailable()
    if len({value.scan_root_id for value in values}) != len(values):
        raise EbookRenameCapabilityUnavailable()
    return config_path, values


def _parse_entry(entry: object) -> ResolvedEbookRenameCapability:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
        raise EbookRenameCapabilityUnavailable()
    capability_id = _parse_id(entry["ebook_rename_capability_id"])
    scan_root_id = _parse_id(entry["scan_root_id"])
    scan_root = _parse_directory(entry["scan_root_directory"])
    probe = _parse_directory(entry["probe_directory"])
    version = entry["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version <= 0
        or entry["capability_profile"] != EBOOK_RENAME_CAPABILITY_PROFILE
        or entry["writer_profile"] != EBOOK_RENAME_PROCESSOR_PROFILE
    ):
        raise EbookRenameCapabilityUnavailable()
    _verify_no_overlap(scan_root, probe)
    _verify_probe_directory_protection(probe)
    if not os.access(scan_root, os.W_OK):
        raise EbookRenameCapabilityUnavailable()
    try:
        if os.stat(scan_root).st_dev != os.stat(probe).st_dev:
            raise EbookRenameCapabilityUnavailable()
    except OSError:
        raise EbookRenameCapabilityUnavailable() from None
    fingerprint = _configuration_fingerprint(
        capability_id=capability_id,
        scan_root_id=scan_root_id,
        scan_root=scan_root,
        probe=probe,
        version=version,
    )
    return ResolvedEbookRenameCapability(
        ebook_rename_capability_id=capability_id,
        scan_root_id=scan_root_id,
        scan_root_directory=scan_root,
        probe_directory=probe,
        version=version,
        configuration_fingerprint=fingerprint,
    )


def _configuration_fingerprint(
    *,
    capability_id: EntityId,
    scan_root_id: EntityId,
    scan_root: Path,
    probe: Path,
    version: int,
) -> str:
    payload = {
        "capability_profile": EBOOK_RENAME_CAPABILITY_PROFILE,
        "ebook_rename_capability_id": str(capability_id),
        "probe_directory": os.fspath(probe),
        "scan_root_directory": os.fspath(scan_root),
        "scan_root_id": str(scan_root_id),
        "version": version,
        "writer_profile": EBOOK_RENAME_PROCESSOR_PROFILE,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_CONFIGURATION_DOMAIN + encoded).hexdigest()


def _parse_id(value: object) -> EntityId:
    if not isinstance(value, str):
        raise EbookRenameCapabilityUnavailable()
    try:
        return EntityId.parse(value)
    except (TypeError, ValueError):
        raise EbookRenameCapabilityUnavailable() from None


def _parse_directory(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise EbookRenameCapabilityUnavailable()
    path = _absolute_path(Path(value))
    if any(part in {".", ".."} for part in path.parts):
        raise EbookRenameCapabilityUnavailable()
    _verify_regular_path(path, final_directory=True)
    return path


def _absolute_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.anchor:
        raise EbookRenameCapabilityUnavailable()
    return path


def _verify_no_overlapping_capabilities(
    values: tuple[ResolvedEbookRenameCapability, ...],
) -> None:
    directories = tuple(
        directory
        for value in values
        for directory in (value.scan_root_directory, value.probe_directory)
    )
    for index, left in enumerate(directories):
        for right in directories[index + 1 :]:
            _verify_no_overlap(left, right)


def _verify_protected_boundaries(
    values: tuple[ResolvedEbookRenameCapability, ...],
    protected_paths: tuple[Path, ...],
) -> None:
    for value in values:
        for directory in (value.scan_root_directory, value.probe_directory):
            for protected in protected_paths:
                _verify_no_overlap(directory, protected)


def _verify_no_overlap(left: Path, right: Path) -> None:
    if left == right or left in right.parents or right in left.parents:
        raise EbookRenameCapabilityUnavailable()


def _default_protected_paths() -> tuple[Path, ...]:
    configured = (
        ("FOLIOTONE_DATABASE", "/data/foliotone.db"),
        ("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts"),
        ("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools"),
        (
            "FOLIOTONE_METADATA_WRITE_STAGE_ROOT",
            "/data/foliotone-metadata-write-stage",
        ),
    )
    paths = [Path(os.environ.get(name, default)) for name, default in configured]
    paths.append(Path(__file__).resolve().parents[3])
    dependency_scope = os.environ.get("FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE")
    if dependency_scope:
        paths.append(Path(dependency_scope))
    return tuple(path for path in paths if path.is_absolute())


def _read_bounded(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if os.name == "posix":
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if not isinstance(no_follow, int) or no_follow == 0:
            raise EbookRenameCapabilityUnavailable()
        flags |= no_follow
    descriptor = os.open(path, flags)
    try:
        _verify_open_configuration(path, descriptor)
        data = os.read(descriptor, _MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES or os.read(descriptor, 1):
            raise EbookRenameCapabilityUnavailable()
    finally:
        os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise EbookRenameCapabilityUnavailable() from None


def _verify_regular_path(path: Path, *, final_directory: bool) -> None:
    current = Path(path.anchor)
    parts = path.parts[1:]
    if not parts:
        raise EbookRenameCapabilityUnavailable()
    for index, part in enumerate(parts):
        current /= part
        try:
            details = os.lstat(current)
        except OSError:
            raise EbookRenameCapabilityUnavailable() from None
        is_final = index == len(parts) - 1
        if stat.S_ISLNK(details.st_mode) or _is_reparse(details):
            raise EbookRenameCapabilityUnavailable()
        if (not is_final or final_directory) and not stat.S_ISDIR(details.st_mode):
            raise EbookRenameCapabilityUnavailable()
        if is_final and not final_directory and not stat.S_ISREG(details.st_mode):
            raise EbookRenameCapabilityUnavailable()


def _verify_configuration_protection(path: Path) -> None:
    """Require protection support before opening the configuration."""

    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or not callable(geteuid):
        raise EbookRenameCapabilityUnavailable()


def _verify_open_configuration(path: Path, descriptor: int) -> None:
    if os.name != "posix":
        return
    geteuid = getattr(os, "geteuid", None)
    if not callable(geteuid):
        raise EbookRenameCapabilityUnavailable()
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
    except OSError:
        raise EbookRenameCapabilityUnavailable() from None
    if (
        opened.st_dev != named.st_dev
        or opened.st_ino != named.st_ino
        or not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
        or opened.st_uid != geteuid()
        or _is_reparse(opened)
    ):
        raise EbookRenameCapabilityUnavailable()


def _verify_probe_directory_protection(path: Path) -> None:
    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or not callable(geteuid):
        raise EbookRenameCapabilityUnavailable()
    try:
        details = os.stat(path, follow_symlinks=False)
    except OSError:
        raise EbookRenameCapabilityUnavailable() from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != geteuid()
        or stat.S_IMODE(details.st_mode) & 0o022
        or _is_reparse(details)
    ):
        raise EbookRenameCapabilityUnavailable()


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EbookRenameCapabilityUnavailable()
        result[key] = value
    return result


__all__ = [
    "EBOOK_RENAME_CAPABILITIES_FILE_ENV",
    "EBOOK_RENAME_CAPABILITY_PROFILE",
    "EbookRenameCapabilityResolver",
    "EbookRenameCapabilityUnavailable",
    "ResolvedEbookRenameCapability",
]
