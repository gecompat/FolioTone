"""Private fail-closed dependency-scope configuration for e-book rename."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import EbookOperationDependencyKind

EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV: Final = (
    "FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE"
)
EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE: Final = (
    "ebook-file-rename-dependency-scope/v1"
)

_MAX_CONFIG_BYTES: Final = 64 * 1024
_MAX_SCOPES: Final = 128
_ROOT_FIELDS: Final = frozenset({"dependency_scopes"})
_ENTRY_FIELDS: Final = frozenset(
    {
        "dependency_scope_id",
        "scan_root_id",
        "profile",
        "version",
        "axes",
    }
)


class EbookRenameDependencyScopeMode(StrEnum):
    MANAGED = "MANAGED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EbookRenameDependencySnapshotKind(StrEnum):
    ARCHIVE_COLLECTION_RUN = "ARCHIVE_COLLECTION_RUN"
    CALIBRE_SNAPSHOT = "CALIBRE_SNAPSHOT"
    TOOL_RESULT = "TOOL_RESULT"


class EbookRenameDependencyScopeUnavailable(RuntimeError):
    """The requested owner-only mapping could not be proven."""

    def __init__(self) -> None:
        super().__init__("DEPENDENCY_SCOPE_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class EbookRenameDependencyScopeAxis:
    kind: EbookOperationDependencyKind
    mode: EbookRenameDependencyScopeMode
    snapshot_kind: EbookRenameDependencySnapshotKind | None = None
    snapshot_id: EntityId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EbookOperationDependencyKind) or not isinstance(
            self.mode, EbookRenameDependencyScopeMode
        ):
            raise EbookRenameDependencyScopeUnavailable()
        managed = self.mode is EbookRenameDependencyScopeMode.MANAGED
        if managed != (self.snapshot_kind is not None and self.snapshot_id is not None):
            raise EbookRenameDependencyScopeUnavailable()
        if self.snapshot_kind is not None and not isinstance(
            self.snapshot_kind, EbookRenameDependencySnapshotKind
        ):
            raise EbookRenameDependencyScopeUnavailable()
        if self.snapshot_id is not None and not isinstance(self.snapshot_id, EntityId):
            raise EbookRenameDependencyScopeUnavailable()


@dataclass(frozen=True, slots=True)
class ResolvedEbookRenameDependencyScope:
    dependency_scope_id: EntityId
    scan_root_id: EntityId
    version: int
    axes: tuple[EbookRenameDependencyScopeAxis, ...]
    profile: str = EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dependency_scope_id, EntityId)
            or not isinstance(self.scan_root_id, EntityId)
            or isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or not 1 <= self.version <= 2_147_483_647
            or self.profile != EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE
            or tuple(value.kind for value in self.axes)
            != tuple(EbookOperationDependencyKind)
        ):
            raise EbookRenameDependencyScopeUnavailable()


class EbookRenameDependencyScopeResolver:
    """Resolve opaque scope IDs through one protected local JSON file."""

    def resolve(
        self,
        dependency_scope_id: EntityId,
    ) -> ResolvedEbookRenameDependencyScope:
        try:
            if not isinstance(dependency_scope_id, EntityId):
                raise EbookRenameDependencyScopeUnavailable()
            for value in self.all_scopes():
                if value.dependency_scope_id == dependency_scope_id:
                    return value
        except EbookRenameDependencyScopeUnavailable:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        raise EbookRenameDependencyScopeUnavailable()

    def all_scopes(self) -> tuple[ResolvedEbookRenameDependencyScope, ...]:
        try:
            return _load_configuration()
        except EbookRenameDependencyScopeUnavailable:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            raise EbookRenameDependencyScopeUnavailable() from None


def _load_configuration() -> tuple[ResolvedEbookRenameDependencyScope, ...]:
    configured = os.environ.get(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV)
    if not configured:
        raise EbookRenameDependencyScopeUnavailable()
    config_path = Path(configured)
    _verify_regular_path(config_path)
    _verify_configuration_protection(config_path)
    document = json.loads(_read_bounded(config_path), object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or set(document) != _ROOT_FIELDS:
        raise EbookRenameDependencyScopeUnavailable()
    entries = document["dependency_scopes"]
    if not isinstance(entries, list) or not entries or len(entries) > _MAX_SCOPES:
        raise EbookRenameDependencyScopeUnavailable()
    values = tuple(_parse_entry(entry) for entry in entries)
    if len({value.dependency_scope_id for value in values}) != len(values):
        raise EbookRenameDependencyScopeUnavailable()
    if len({value.scan_root_id for value in values}) != len(values):
        raise EbookRenameDependencyScopeUnavailable()
    return values


def _parse_entry(entry: object) -> ResolvedEbookRenameDependencyScope:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
        raise EbookRenameDependencyScopeUnavailable()
    if entry["profile"] != EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE:
        raise EbookRenameDependencyScopeUnavailable()
    axes = entry["axes"]
    expected_keys = {kind.value for kind in EbookOperationDependencyKind}
    if not isinstance(axes, dict) or set(axes) != expected_keys:
        raise EbookRenameDependencyScopeUnavailable()
    return ResolvedEbookRenameDependencyScope(
        dependency_scope_id=_parse_id(entry["dependency_scope_id"]),
        scan_root_id=_parse_id(entry["scan_root_id"]),
        version=_parse_version(entry["version"]),
        axes=tuple(_parse_axis(kind, axes[kind.value]) for kind in EbookOperationDependencyKind),
    )


def _parse_axis(
    kind: EbookOperationDependencyKind,
    raw: object,
) -> EbookRenameDependencyScopeAxis:
    if not isinstance(raw, dict) or "mode" not in raw:
        raise EbookRenameDependencyScopeUnavailable()
    try:
        mode = EbookRenameDependencyScopeMode(raw["mode"])
    except (TypeError, ValueError):
        raise EbookRenameDependencyScopeUnavailable() from None
    if mode is EbookRenameDependencyScopeMode.NOT_APPLICABLE:
        if set(raw) != {"mode"}:
            raise EbookRenameDependencyScopeUnavailable()
        return EbookRenameDependencyScopeAxis(kind=kind, mode=mode)
    if set(raw) != {"mode", "snapshot_kind", "snapshot_id"}:
        raise EbookRenameDependencyScopeUnavailable()
    try:
        snapshot_kind = EbookRenameDependencySnapshotKind(raw["snapshot_kind"])
    except (TypeError, ValueError):
        raise EbookRenameDependencyScopeUnavailable() from None
    return EbookRenameDependencyScopeAxis(
        kind=kind,
        mode=mode,
        snapshot_kind=snapshot_kind,
        snapshot_id=_parse_id(raw["snapshot_id"]),
    )


def _parse_id(value: object) -> EntityId:
    if not isinstance(value, str):
        raise EbookRenameDependencyScopeUnavailable()
    try:
        return EntityId.parse(value)
    except (TypeError, ValueError):
        raise EbookRenameDependencyScopeUnavailable() from None


def _parse_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2_147_483_647:
        raise EbookRenameDependencyScopeUnavailable()
    return value


def _read_bounded(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if os.name == "posix":
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if not isinstance(no_follow, int) or no_follow == 0:
            raise EbookRenameDependencyScopeUnavailable()
        flags |= no_follow
    descriptor = os.open(path, flags)
    try:
        _verify_open_configuration(path, descriptor)
        data = os.read(descriptor, _MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES or os.read(descriptor, 1):
            raise EbookRenameDependencyScopeUnavailable()
    finally:
        os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise EbookRenameDependencyScopeUnavailable() from None


def _verify_regular_path(path: Path) -> None:
    if not path.is_absolute() or not path.anchor:
        raise EbookRenameDependencyScopeUnavailable()
    current = Path(path.anchor)
    parts = path.parts[1:]
    if not parts:
        raise EbookRenameDependencyScopeUnavailable()
    for index, part in enumerate(parts):
        current /= part
        try:
            details = os.lstat(current)
        except OSError:
            raise EbookRenameDependencyScopeUnavailable() from None
        final = index == len(parts) - 1
        if stat.S_ISLNK(details.st_mode) or _is_reparse(details):
            raise EbookRenameDependencyScopeUnavailable()
        if not final and not stat.S_ISDIR(details.st_mode):
            raise EbookRenameDependencyScopeUnavailable()
        if final and not stat.S_ISREG(details.st_mode):
            raise EbookRenameDependencyScopeUnavailable()


def _verify_configuration_protection(path: Path) -> None:
    """Require owner-only POSIX protection; unsupported checks fail closed."""

    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or not callable(geteuid):
        raise EbookRenameDependencyScopeUnavailable()
    try:
        details = os.lstat(path)
    except OSError:
        raise EbookRenameDependencyScopeUnavailable() from None
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != geteuid()
        or _is_reparse(details)
    ):
        raise EbookRenameDependencyScopeUnavailable()


def _verify_open_configuration(path: Path, descriptor: int) -> None:
    if os.name != "posix":
        return
    geteuid = getattr(os, "geteuid", None)
    if not callable(geteuid):
        raise EbookRenameDependencyScopeUnavailable()
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
    except OSError:
        raise EbookRenameDependencyScopeUnavailable() from None
    if (
        opened.st_dev != named.st_dev
        or opened.st_ino != named.st_ino
        or not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
        or opened.st_uid != geteuid()
        or _is_reparse(opened)
    ):
        raise EbookRenameDependencyScopeUnavailable()


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EbookRenameDependencyScopeUnavailable()
        result[key] = value
    return result


__all__ = [
    "EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE",
    "EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV",
    "EbookRenameDependencyScopeAxis",
    "EbookRenameDependencyScopeMode",
    "EbookRenameDependencyScopeResolver",
    "EbookRenameDependencyScopeUnavailable",
    "EbookRenameDependencySnapshotKind",
    "ResolvedEbookRenameDependencyScope",
]
