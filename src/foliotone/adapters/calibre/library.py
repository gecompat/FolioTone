"""Fixed read-only ``calibredb`` commands for library reconciliation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from foliotone.core import ToolCapability
from foliotone.tooling import ToolProviderDescriptor
from foliotone.tooling.runtime import LocalCommand
from foliotone.tooling.structured import StructuredOutputError, parse_json_output

from .common import calibre_version_policy

CALIBRE_LIBRARY_EXECUTABLE = "calibredb"
CALIBRE_LIBRARY_ADAPTER_VERSION = "calibredb-library/1"
CALIBRE_LIBRARY_PROFILE = "calibre-library-snapshot/v1"
CALIBRE_LIBRARY_PREFIX = "__FOLIOTONE_CALIBRE_ROOT__"
CALIBRE_LIBRARY_TIMEOUT_SECONDS = 120.0
CALIBRE_LIBRARY_MAX_PAGE_SIZE = 500
CALIBRE_LIBRARY_CONFIG_DIRECTORY = "calibre-config"

CALIBRE_LIBRARY_PROVIDER = ToolProviderDescriptor(
    provider_id="calibre-library",
    display_name="calibredb library reconciliation",
    adapter_version=CALIBRE_LIBRARY_ADAPTER_VERSION,
    capabilities=frozenset({ToolCapability.LIBRARY_READ}),
)

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
MAX_CALIBRE_RECORDS_PER_PAGE = CALIBRE_LIBRARY_MAX_PAGE_SIZE
MAX_CALIBRE_FORMATS_PER_RECORD = 256
MAX_CALIBRE_AUTHORS_PER_RECORD = 256
MAX_CALIBRE_IDENTIFIERS_PER_RECORD = 128
MAX_CALIBRE_FIELD_CHARS = 4096

_FORMAT_LABEL = re.compile(r"[A-Z0-9]{1,16}")


class CalibreLibraryParseError(ValueError):
    """A path-free failure while parsing bounded ``calibredb`` output."""


@dataclass(frozen=True, slots=True)
class ParsedCalibreLibraryFormat:
    """One normalized format locator from a machine-readable inventory page."""

    format_label: str
    relative_locator: str


@dataclass(frozen=True, slots=True)
class ParsedCalibreLibraryRecord:
    """Adapter-local record projection; canonical book identity is resolved later."""

    record_id: int
    title: str | None
    uuid: str | None
    authors: tuple[str, ...]
    identifiers: tuple[tuple[str, str], ...]
    formats: tuple[ParsedCalibreLibraryFormat, ...]


def parse_calibredb_inventory_page(data: bytes) -> tuple[ParsedCalibreLibraryRecord, ...]:
    """Parse one bounded, strictly increasing ``calibredb list`` JSON page."""
    try:
        value = parse_json_output(data, max_bytes=MAX_CALIBRE_LIST_STDOUT_BYTES)
        if not isinstance(value, list):
            raise CalibreLibraryParseError("calibre inventory page must be a JSON array")
        if len(value) > MAX_CALIBRE_RECORDS_PER_PAGE:
            raise CalibreLibraryParseError("calibre inventory page exceeds the record limit")

        records: list[ParsedCalibreLibraryRecord] = []
        previous_record_id = -1
        for raw_record in value:
            if not isinstance(raw_record, dict):
                raise CalibreLibraryParseError("calibre inventory record must be an object")
            record = _parse_record(raw_record)
            if record.record_id <= previous_record_id:
                raise CalibreLibraryParseError("calibre inventory IDs must be strictly increasing")
            previous_record_id = record.record_id
            records.append(record)
        return tuple(records)
    except StructuredOutputError as error:
        raise CalibreLibraryParseError("calibre inventory output is invalid") from error


def _parse_record(raw_record: Mapping[str, object]) -> ParsedCalibreLibraryRecord:
    record_id = _parse_record_id(raw_record.get("id"))
    if "formats" not in raw_record:
        raise CalibreLibraryParseError("calibre formats field is missing")
    formats = _parse_formats(raw_record["formats"])
    return ParsedCalibreLibraryRecord(
        record_id=record_id,
        title=_parse_optional_text(raw_record.get("title"), "title"),
        uuid=_parse_optional_text(raw_record.get("uuid"), "uuid"),
        authors=_parse_text_list(raw_record.get("authors", []), "authors"),
        identifiers=_parse_identifiers(raw_record.get("identifiers", {})),
        formats=formats,
    )


def _parse_record_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CalibreLibraryParseError("calibre inventory record ID is invalid")
    return value


def _parse_optional_text(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > MAX_CALIBRE_FIELD_CHARS:
        raise CalibreLibraryParseError(f"calibre {field_name} field is invalid")
    if any(ord(character) < 32 for character in value):
        raise CalibreLibraryParseError(f"calibre {field_name} field is invalid")
    return value


def _parse_text_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_CALIBRE_AUTHORS_PER_RECORD:
        raise CalibreLibraryParseError(f"calibre {field_name} field is invalid")
    parsed: list[str] = []
    for item in value:
        text = _parse_optional_text(item, field_name)
        if text is None:
            raise CalibreLibraryParseError(f"calibre {field_name} field is invalid")
        parsed.append(text)
    return tuple(parsed)


def _parse_identifiers(value: object) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or len(value) > MAX_CALIBRE_IDENTIFIERS_PER_RECORD:
        raise CalibreLibraryParseError("calibre identifiers field is invalid")
    parsed: list[tuple[str, str]] = []
    for namespace, identifier in value.items():
        if not isinstance(namespace, str):
            raise CalibreLibraryParseError("calibre identifier namespace is invalid")
        parsed_namespace = _parse_optional_text(namespace, "identifier namespace")
        parsed_identifier = _parse_optional_text(identifier, "identifier value")
        if parsed_namespace is None or parsed_identifier is None:
            raise CalibreLibraryParseError("calibre identifier is invalid")
        parsed.append((parsed_namespace, parsed_identifier))
    return tuple(sorted(parsed))


def _parse_formats(value: object) -> tuple[ParsedCalibreLibraryFormat, ...]:
    if not isinstance(value, list) or len(value) > MAX_CALIBRE_FORMATS_PER_RECORD:
        raise CalibreLibraryParseError("calibre formats field is invalid")
    parsed: list[ParsedCalibreLibraryFormat] = []
    for item in value:
        if not isinstance(item, str):
            raise CalibreLibraryParseError("calibre format locator is invalid")
        relative_locator = _normalize_format_locator(item)
        suffix = PurePosixPath(relative_locator).suffix
        format_label = suffix[1:].upper() if suffix else ""
        if _FORMAT_LABEL.fullmatch(format_label) is None:
            raise CalibreLibraryParseError("calibre format label is invalid")
        parsed.append(
            ParsedCalibreLibraryFormat(
                format_label=format_label,
                relative_locator=relative_locator,
            )
        )
    ordered = tuple(sorted(parsed, key=lambda item: (item.format_label, item.relative_locator)))
    if len({item.relative_locator for item in ordered}) != len(ordered):
        raise CalibreLibraryParseError("calibre format locators must be unique")
    return ordered


def _normalize_format_locator(value: str) -> str:
    if not value or len(value) > MAX_CALIBRE_FIELD_CHARS:
        raise CalibreLibraryParseError("calibre format locator is invalid")
    if any(ord(character) < 32 for character in value):
        raise CalibreLibraryParseError("calibre format locator is invalid")
    normalized = value.replace("\\", "/")
    prefix = f"{CALIBRE_LIBRARY_PREFIX}/"
    if not normalized.startswith(prefix):
        raise CalibreLibraryParseError("calibre format locator is outside the pseudo-root")
    relative = normalized[len(prefix) :]
    if not relative or relative.startswith("/") or ":" in relative:
        raise CalibreLibraryParseError("calibre format locator is unsafe")
    path = PurePosixPath(relative)
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise CalibreLibraryParseError("calibre format locator is unsafe")
    if path.is_absolute() or path.as_posix() != relative:
        raise CalibreLibraryParseError("calibre format locator is unsafe")
    return relative


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
        max_stdout_bytes={
            "--version": 64 * 1024,
            "list": MAX_CALIBRE_LIST_STDOUT_BYTES,
            "search": MAX_CALIBRE_SEARCH_STDOUT_BYTES,
            "show_metadata": MAX_CALIBRE_METADATA_STDOUT_BYTES,
            "list_categories": MAX_CALIBRE_CATEGORIES_STDOUT_BYTES,
        }[args[0]],
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
