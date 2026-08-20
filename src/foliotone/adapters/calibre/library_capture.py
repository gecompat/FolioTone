"""Bounded parser projections required by Calibre library capture."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath

from foliotone.tooling.structured import StructuredOutputError, parse_json_output

from .library import (
    CALIBRE_LIBRARY_CATEGORIES,
    MAX_CALIBRE_AUTHORS_PER_RECORD,
    MAX_CALIBRE_CATEGORIES_STDOUT_BYTES,
    MAX_CALIBRE_FIELD_CHARS,
    MAX_CALIBRE_FORMATS_PER_RECORD,
    MAX_CALIBRE_IDENTIFIERS_PER_RECORD,
    MAX_CALIBRE_LIST_STDOUT_BYTES,
    MAX_CALIBRE_SEARCH_STDOUT_BYTES,
    CalibreLibraryParseError,
    ParsedCalibreLibraryFormat,
    ParsedCalibreLibraryRecord,
    parse_calibredb_inventory_page,
)

CALIBRE_INVENTORY_DIGEST_PROFILE = "calibre-library-inventory-digest/v1"
MAX_CALIBRE_CATEGORIES = 100_000
MAX_CALIBRE_INTEGER = (1 << 63) - 1
_FORMAT_LABEL = re.compile(r"[A-Z0-9]{1,16}\Z")
_CANONICAL_INTEGER = re.compile(r"0|[1-9][0-9]*\Z")


@dataclass(frozen=True, slots=True)
class ParsedCalibreCaptureRecord:
    """One inventory record plus the timestamp required by the capture digest."""

    record: ParsedCalibreLibraryRecord = field(repr=False)
    last_modified_at: datetime

    def __post_init__(self) -> None:
        _validate_record(self.record)
        if not isinstance(self.last_modified_at, datetime):
            raise CalibreLibraryParseError("calibre last_modified field is invalid")
        if self.last_modified_at.tzinfo is None or self.last_modified_at.utcoffset() is None:
            raise CalibreLibraryParseError("calibre last_modified field is invalid")
        object.__setattr__(self, "last_modified_at", self.last_modified_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ParsedCalibreLibraryCategory:
    """One bounded category row whose private value is redacted from repr."""

    category: str
    name: str = field(repr=False)
    count: int

    def __post_init__(self) -> None:
        if self.category not in CALIBRE_LIBRARY_CATEGORIES:
            raise CalibreLibraryParseError("calibre category kind is invalid")
        _validate_text(self.name, "category name")
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or not 0 <= self.count <= MAX_CALIBRE_INTEGER
        ):
            raise CalibreLibraryParseError("calibre category count is invalid")


def parse_calibredb_capture_inventory_page(
    data: bytes,
) -> tuple[ParsedCalibreCaptureRecord, ...]:
    """Add the mandatory timestamp to the existing bounded inventory projection."""
    records = parse_calibredb_inventory_page(data)
    try:
        raw = parse_json_output(data, max_bytes=MAX_CALIBRE_LIST_STDOUT_BYTES)
    except StructuredOutputError as error:
        raise CalibreLibraryParseError("calibre inventory output is invalid") from error
    if not isinstance(raw, list) or len(raw) != len(records):
        raise CalibreLibraryParseError("calibre inventory output is invalid")
    captured: list[ParsedCalibreCaptureRecord] = []
    for record, raw_record in zip(records, raw, strict=True):
        if not isinstance(raw_record, dict) or raw_record.get("id") != record.record_id:
            raise CalibreLibraryParseError("calibre inventory output is invalid")
        captured.append(
            ParsedCalibreCaptureRecord(
                record=record,
                last_modified_at=_parse_timestamp(raw_record.get("last_modified")),
            )
        )
    return tuple(captured)


def parse_calibredb_exact_ids(data: bytes) -> tuple[int, ...]:
    """Parse the fixed bounded comma-separated output of ``calibredb search``."""
    if len(data) > MAX_CALIBRE_SEARCH_STDOUT_BYTES:
        raise CalibreLibraryParseError("calibre exact-ID output exceeds the configured limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CalibreLibraryParseError("calibre exact-ID output is invalid") from error
    if text == "":
        return ()
    if re.fullmatch(r"(?:0|[1-9][0-9]*)(?:,(?:0|[1-9][0-9]*))*(?:\r?\n)?", text) is None:
        raise CalibreLibraryParseError("calibre exact-ID output is invalid")
    parts = text.rstrip("\r\n").split(",")
    if len(parts) > 2 or any(len(value) > 19 for value in parts):
        raise CalibreLibraryParseError("calibre exact-ID output is invalid")
    values = tuple(int(value) for value in parts)
    if (
        any(value > MAX_CALIBRE_INTEGER for value in values)
        or values != tuple(sorted(values))
        or len(set(values)) != len(values)
    ):
        raise CalibreLibraryParseError("calibre exact-ID output is invalid")
    return values


def parse_calibredb_categories(data: bytes) -> tuple[ParsedCalibreLibraryCategory, ...]:
    """Parse the fixed category CSV projection without retaining raw output."""
    if len(data) > MAX_CALIBRE_CATEGORIES_STDOUT_BYTES:
        raise CalibreLibraryParseError("calibre category output exceeds the configured limit")
    try:
        text = data.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if reader.fieldnames != ["category", "name", "count"]:
            raise CalibreLibraryParseError("calibre category header is invalid")
        parsed: list[ParsedCalibreLibraryCategory] = []
        for raw in reader:
            if len(parsed) >= MAX_CALIBRE_CATEGORIES or None in raw:
                raise CalibreLibraryParseError("calibre category output is invalid")
            category = raw.get("category")
            name = raw.get("name")
            count = raw.get("count")
            if not isinstance(category, str) or not isinstance(name, str):
                raise CalibreLibraryParseError("calibre category row is invalid")
            if not isinstance(count, str) or _CANONICAL_INTEGER.fullmatch(count) is None:
                raise CalibreLibraryParseError("calibre category count is invalid")
            parsed_count = int(count)
            if parsed_count > MAX_CALIBRE_INTEGER:
                raise CalibreLibraryParseError("calibre category count is invalid")
            parsed.append(ParsedCalibreLibraryCategory(category, name, parsed_count))
    except (csv.Error, UnicodeDecodeError) as error:
        raise CalibreLibraryParseError("calibre category output is invalid") from error
    ordered = tuple(
        sorted(parsed, key=lambda item: (item.category, item.name.casefold(), item.name))
    )
    if len({(item.category, item.name) for item in ordered}) != len(ordered):
        raise CalibreLibraryParseError("calibre category rows must be unique")
    return ordered


def calibre_inventory_digest(records: tuple[ParsedCalibreCaptureRecord, ...]) -> str:
    """Hash exactly the ADR-0033 inventory consistency material."""
    if not isinstance(records, tuple) or any(
        not isinstance(record, ParsedCalibreCaptureRecord) for record in records
    ):
        raise TypeError("records must be a tuple of parsed Calibre capture records")
    record_ids = tuple(item.record.record_id for item in records)
    if record_ids != tuple(sorted(record_ids)) or len(set(record_ids)) != len(records):
        raise ValueError("Calibre inventory records must be strictly ordered")
    material = {
        "profile": CALIBRE_INVENTORY_DIGEST_PROFILE,
        "records": [
            {
                "formats": [
                    [item.format_label, item.relative_locator] for item in captured.record.formats
                ],
                "id": captured.record.record_id,
                "last_modified": captured.last_modified_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "uuid": captured.record.uuid,
            }
            for captured in records
        ],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise CalibreLibraryParseError("calibre last_modified field is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CalibreLibraryParseError("calibre last_modified field is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CalibreLibraryParseError("calibre last_modified field is invalid")
    return parsed.astimezone(UTC)


def _validate_record(record: ParsedCalibreLibraryRecord) -> None:
    if not isinstance(record, ParsedCalibreLibraryRecord):
        raise CalibreLibraryParseError("calibre inventory record is invalid")
    if (
        isinstance(record.record_id, bool)
        or not isinstance(record.record_id, int)
        or not 0 <= record.record_id <= MAX_CALIBRE_INTEGER
    ):
        raise CalibreLibraryParseError("calibre inventory record ID is invalid")
    for value, name, optional in (
        (record.title, "title", True),
        (record.uuid, "uuid", True),
    ):
        if value is None and optional:
            continue
        _validate_text(value, name)
    if (
        not isinstance(record.authors, tuple)
        or len(record.authors) > MAX_CALIBRE_AUTHORS_PER_RECORD
    ):
        raise CalibreLibraryParseError("calibre authors field is invalid")
    for value in record.authors:
        _validate_text(value, "author")
    if (
        not isinstance(record.identifiers, tuple)
        or len(record.identifiers) > MAX_CALIBRE_IDENTIFIERS_PER_RECORD
        or any(not isinstance(item, tuple) or len(item) != 2 for item in record.identifiers)
    ):
        raise CalibreLibraryParseError("calibre identifiers field is invalid")
    for namespace, value in record.identifiers:
        _validate_text(namespace, "identifier namespace")
        _validate_text(value, "identifier value")
    if record.identifiers != tuple(sorted(record.identifiers)) or len(
        {namespace for namespace, _value in record.identifiers}
    ) != len(record.identifiers):
        raise CalibreLibraryParseError("calibre identifiers field is invalid")
    if (
        not isinstance(record.formats, tuple)
        or len(record.formats) > MAX_CALIBRE_FORMATS_PER_RECORD
    ):
        raise CalibreLibraryParseError("calibre formats field is invalid")
    for item in record.formats:
        _validate_format(item)
    if record.formats != tuple(
        sorted(record.formats, key=lambda item: (item.format_label, item.relative_locator))
    ) or len({item.relative_locator for item in record.formats}) != len(record.formats):
        raise CalibreLibraryParseError("calibre formats field is invalid")


def _validate_format(item: ParsedCalibreLibraryFormat) -> None:
    if not isinstance(item, ParsedCalibreLibraryFormat):
        raise CalibreLibraryParseError("calibre format is invalid")
    if not isinstance(item.format_label, str) or _FORMAT_LABEL.fullmatch(item.format_label) is None:
        raise CalibreLibraryParseError("calibre format label is invalid")
    _validate_relative_locator(item.relative_locator)
    if PurePosixPath(item.relative_locator).suffix[1:].upper() != item.format_label:
        raise CalibreLibraryParseError("calibre format label is invalid")


def _validate_relative_locator(value: object) -> None:
    _validate_text(value, "format locator")
    assert isinstance(value, str)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ":" in value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise CalibreLibraryParseError("calibre format locator is invalid")


def _validate_text(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_CALIBRE_FIELD_CHARS
        or any(ord(character) < 32 for character in value)
    ):
        raise CalibreLibraryParseError(f"calibre {field_name} field is invalid")
