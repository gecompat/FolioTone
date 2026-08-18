"""Fixed read-only ``calibredb`` commands for library reconciliation."""

from __future__ import annotations

from pathlib import Path

from foliotone.core import ToolCapability
from foliotone.tooling.runtime import LocalCommand

from .common import calibre_version_policy

CALIBRE_LIBRARY_EXECUTABLE = "calibredb"
CALIBRE_LIBRARY_ADAPTER_VERSION = "calibredb-library/1"
CALIBRE_LIBRARY_PROFILE = "calibre-library-snapshot/v1"
CALIBRE_LIBRARY_PREFIX = "__FOLIOTONE_CALIBRE_ROOT__"
CALIBRE_LIBRARY_TIMEOUT_SECONDS = 120.0
CALIBRE_LIBRARY_MAX_PAGE_SIZE = 500
CALIBRE_LIBRARY_CONFIG_DIRECTORY = "calibre-config"

CALIBRE_LIBRARY_FIELDS = (
    "authors",
    "author_sort",
    "cover",
    "formats",
    "identifiers",
    "isbn",
    "languages",
    "last_modified",
    "pubdate",
    "publisher",
    "series",
    "series_index",
    "size",
    "tags",
    "timestamp",
    "title",
    "uuid",
)
CALIBRE_LIBRARY_CATEGORIES = (
    "authors",
    "series",
    "tags",
    "languages",
    "publisher",
)

MAX_CALIBRE_LIST_STDOUT_BYTES = 64 * 1024 * 1024
MAX_CALIBRE_SEARCH_STDOUT_BYTES = 1024 * 1024
MAX_CALIBRE_METADATA_STDOUT_BYTES = 4 * 1024 * 1024
MAX_CALIBRE_CATEGORIES_STDOUT_BYTES = 16 * 1024 * 1024


def build_calibredb_version_command() -> LocalCommand:
    """Build the only allowed version-discovery command."""
    return _read_command(("--version",))


def build_calibredb_inventory_command(
    library_path: Path,
    *,
    after_record_id: int,
    limit: int,
) -> LocalCommand:
    """Build one keyset-paginated machine-readable inventory command."""
    path = _validated_library_path(library_path)
    record_id = _validated_record_id(after_record_id, "after_record_id")
    page_size = _validated_page_size(limit)
    return _read_command(
        (
            "list",
            "--library-path",
            path,
            "--for-machine",
            "--fields",
            ",".join(CALIBRE_LIBRARY_FIELDS),
            "--prefix",
            CALIBRE_LIBRARY_PREFIX,
            "--sort-by",
            "id",
            "--ascending",
            "--search",
            f"id:>{record_id}",
            "--limit",
            str(page_size),
        )
    )


def build_calibredb_exact_id_command(
    library_path: Path,
    *,
    record_id: int,
) -> LocalCommand:
    """Build the fixed exact-ID existence check without accepting query text."""
    path = _validated_library_path(library_path)
    exact_id = _validated_record_id(record_id, "record_id")
    return _read_command(
        (
            "search",
            "--library-path",
            path,
            "--limit",
            "2",
            f"id:={exact_id}",
        )
    )


def build_calibredb_show_metadata_command(
    library_path: Path,
    *,
    record_id: int,
) -> LocalCommand:
    """Build the fixed OPF metadata command for one nonnegative record ID."""
    path = _validated_library_path(library_path)
    exact_id = _validated_record_id(record_id, "record_id")
    return _read_command(
        (
            "show_metadata",
            "--library-path",
            path,
            "--as-opf",
            str(exact_id),
        )
    )


def build_calibredb_list_categories_command(library_path: Path) -> LocalCommand:
    """Build the fixed bounded-category CSV projection command."""
    path = _validated_library_path(library_path)
    return _read_command(
        (
            "list_categories",
            "--library-path",
            path,
            "--csv",
            "--dialect",
            "unix",
            "--categories",
            ",".join(CALIBRE_LIBRARY_CATEGORIES),
        )
    )


def _read_command(args: tuple[str, ...]) -> LocalCommand:
    return LocalCommand(
        executable=CALIBRE_LIBRARY_EXECUTABLE,
        args=args,
        capability=ToolCapability.LIBRARY_READ,
        timeout_seconds=CALIBRE_LIBRARY_TIMEOUT_SECONDS,
        environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
        workspace_environment={
            "CALIBRE_CONFIG_DIRECTORY": CALIBRE_LIBRARY_CONFIG_DIRECTORY,
        },
        version_policy=calibre_version_policy,
        accepted_exit_codes=frozenset({0}),
    )


def _validated_library_path(library_path: Path) -> str:
    if not isinstance(library_path, Path):
        raise TypeError("library_path must be a Path")
    value = str(library_path)
    if not library_path.is_absolute():
        raise ValueError("library_path must be an absolute local path")
    if not value.strip() or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("library_path is invalid")
    if "://" in value:
        raise ValueError("library_path must not be a URL")
    return value


def _validated_record_id(record_id: int, field_name: str) -> int:
    if isinstance(record_id, bool) or not isinstance(record_id, int):
        raise TypeError(f"{field_name} must be an integer")
    if record_id < 0:
        raise ValueError(f"{field_name} must be nonnegative")
    return record_id


def _validated_page_size(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= CALIBRE_LIBRARY_MAX_PAGE_SIZE:
        raise ValueError("limit must be between 1 and 500")
    return limit
