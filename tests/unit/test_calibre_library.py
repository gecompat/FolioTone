from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import foliotone.adapters.calibre.library as calibre_library
from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.library import (
    CALIBRE_LIBRARY_CATEGORIES,
    CALIBRE_LIBRARY_CONFIG_DIRECTORY,
    CALIBRE_LIBRARY_FIELDS,
    CALIBRE_LIBRARY_PREFIX,
    CALIBRE_LIBRARY_PROVIDER,
    MAX_CALIBRE_CATEGORIES_STDOUT_BYTES,
    MAX_CALIBRE_LIST_STDOUT_BYTES,
    MAX_CALIBRE_METADATA_STDOUT_BYTES,
    MAX_CALIBRE_SEARCH_STDOUT_BYTES,
    CalibreLibraryParseError,
    build_calibredb_exact_id_command,
    build_calibredb_inventory_command,
    build_calibredb_list_categories_command,
    build_calibredb_show_metadata_command,
    build_calibredb_version_command,
    parse_calibredb_inventory_page,
)
from foliotone.core import ToolCapability
from foliotone.tooling.runtime import LocalCommand


def _library_path() -> Path:
    return Path.cwd() / "synthetic-calibre-library"


def _fixture_bytes(*parts: str) -> bytes:
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "calibre_library" / "v1"
    return fixture_root.joinpath(*parts).read_bytes()


def test_fixed_read_only_command_shapes_match_adr_0033() -> None:
    library = _library_path()

    assert build_calibredb_version_command().args == ("--version",)
    assert build_calibredb_inventory_command(
        library,
        after_record_id=42,
        limit=500,
    ).args == (
        "list",
        "--library-path",
        str(library),
        "--for-machine",
        "--fields",
        ",".join(CALIBRE_LIBRARY_FIELDS),
        "--prefix",
        CALIBRE_LIBRARY_PREFIX,
        "--sort-by",
        "id",
        "--ascending",
        "--search",
        "id:>42",
        "--limit",
        "500",
    )
    assert build_calibredb_exact_id_command(library, record_id=42).args == (
        "search",
        "--library-path",
        str(library),
        "--limit",
        "2",
        "id:=42",
    )
    assert build_calibredb_show_metadata_command(library, record_id=42).args == (
        "show_metadata",
        "--library-path",
        str(library),
        "--as-opf",
        "42",
    )
    assert build_calibredb_list_categories_command(library).args == (
        "list_categories",
        "--library-path",
        str(library),
        "--csv",
        "--dialect",
        "unix",
        "--categories",
        ",".join(CALIBRE_LIBRARY_CATEGORIES),
    )


def test_library_provider_descriptor_registers_only_read_capability() -> None:
    assert CALIBRE_LIBRARY_PROVIDER.provider_id == "calibre-library"
    assert CALIBRE_LIBRARY_PROVIDER.adapter_version == "calibredb-library/1"
    assert CALIBRE_LIBRARY_PROVIDER.capabilities == frozenset({ToolCapability.LIBRARY_READ})
    assert CALIBRE_LIBRARY_PROVIDER.default_read_only


def test_every_builder_applies_the_same_closed_read_only_runtime_policy() -> None:
    library = _library_path()
    commands = (
        build_calibredb_version_command(),
        build_calibredb_inventory_command(library, after_record_id=0, limit=1),
        build_calibredb_exact_id_command(library, record_id=0),
        build_calibredb_show_metadata_command(library, record_id=0),
        build_calibredb_list_categories_command(library),
    )

    assert all(isinstance(command, LocalCommand) for command in commands)
    assert {command.executable for command in commands} == {"calibredb"}
    assert {command.capability for command in commands} == {ToolCapability.LIBRARY_READ}
    assert {command.timeout_seconds for command in commands} == {120.0}
    assert {command.accepted_exit_codes for command in commands} == {frozenset({0})}
    assert tuple(command.max_stdout_bytes for command in commands) == (
        64 * 1024,
        MAX_CALIBRE_LIST_STDOUT_BYTES,
        MAX_CALIBRE_SEARCH_STDOUT_BYTES,
        MAX_CALIBRE_METADATA_STDOUT_BYTES,
        MAX_CALIBRE_CATEGORIES_STDOUT_BYTES,
    )
    assert {command.max_stderr_bytes for command in commands} == {1024 * 1024}
    assert {command.version_policy for command in commands} == {calibre_version_policy}
    assert all(
        command.workspace_environment
        == {"CALIBRE_CONFIG_DIRECTORY": CALIBRE_LIBRARY_CONFIG_DIRECTORY}
        for command in commands
    )
    assert all(
        command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"} for command in commands
    )


@pytest.mark.parametrize(
    "forbidden_subcommand",
    (
        "add",
        "remove",
        "add_format",
        "remove_format",
        "set_metadata",
        "set_custom",
        "add_custom_column",
        "remove_custom_column",
        "saved_searches",
        "embed_metadata",
        "backup_metadata",
        "restore_database",
        "export",
        "catalog",
        "clone",
        "fts_index",
        "check_library",
    ),
)
def test_no_builder_exposes_write_export_backup_or_restore_subcommands(
    forbidden_subcommand: str,
) -> None:
    library = _library_path()
    commands = (
        build_calibredb_version_command(),
        build_calibredb_inventory_command(library, after_record_id=0, limit=10),
        build_calibredb_exact_id_command(library, record_id=0),
        build_calibredb_show_metadata_command(library, record_id=0),
        build_calibredb_list_categories_command(library),
    )

    assert all(command.args[:1] != (forbidden_subcommand,) for command in commands)


def test_public_builders_accept_no_subcommand_option_list_or_search_expression() -> None:
    builders = (
        build_calibredb_version_command,
        build_calibredb_inventory_command,
        build_calibredb_exact_id_command,
        build_calibredb_show_metadata_command,
        build_calibredb_list_categories_command,
    )

    forbidden_parameters = {"args", "options", "subcommand", "search", "query"}
    for builder in builders:
        assert forbidden_parameters.isdisjoint(inspect.signature(builder).parameters)


@pytest.mark.parametrize("record_id", (-1, True, 1.5, "1"))
def test_record_ids_are_nonnegative_integers(record_id: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_calibredb_exact_id_command(_library_path(), record_id=record_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", (0, 501, True, 1.5, "1"))
def test_inventory_page_size_is_a_bounded_positive_integer(limit: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_calibredb_inventory_command(
            _library_path(),
            after_record_id=0,
            limit=limit,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "library_path",
    (
        Path("relative/library"),
        Path("https://example.invalid/library"),
    ),
)
def test_library_path_must_be_absolute_and_local(library_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute local path"):
        build_calibredb_list_categories_command(library_path)


def test_runtime_output_limits_are_fixed_by_command_kind() -> None:
    assert MAX_CALIBRE_LIST_STDOUT_BYTES == 64 * 1024 * 1024
    assert MAX_CALIBRE_SEARCH_STDOUT_BYTES == 1024 * 1024
    assert MAX_CALIBRE_METADATA_STDOUT_BYTES == 4 * 1024 * 1024
    assert MAX_CALIBRE_CATEGORIES_STDOUT_BYTES == 16 * 1024 * 1024


def test_inventory_parser_projects_fixture_records_and_formats_stably() -> None:
    records = parse_calibredb_inventory_page(_fixture_bytes("cases_a_g", "list_page_1.json"))

    assert tuple(record.record_id for record in records) == tuple(range(101, 109))
    assert records[0].title == "Fixture One"
    assert records[0].authors == ("Ada Alpha",)
    assert records[0].identifiers == (("isbn", "9780000000101"),)
    assert tuple(item.format_label for item in records[4].formats) == (
        "EPUB",
        "MOBI",
        "PDF",
    )
    assert records[4].formats[0].relative_locator == (
        "Dan Delta/Multi Format (105)/Multi Format.epub"
    )


def test_inventory_parser_accepts_empty_page_and_empty_optional_fields() -> None:
    assert parse_calibredb_inventory_page(_fixture_bytes("empty", "list_page_1.json")) == ()

    payload = json.dumps(
        [
            {
                "id": 0,
                "formats": [],
                "title": "",
                "uuid": None,
                "authors": None,
                "identifiers": None,
            }
        ]
    ).encode()
    assert parse_calibredb_inventory_page(payload)[0].title is None
    assert parse_calibredb_inventory_page(payload)[0].uuid is None
    assert parse_calibredb_inventory_page(payload)[0].authors == ()
    assert parse_calibredb_inventory_page(payload)[0].identifiers == ()


def test_inventory_parser_sorts_formats_and_identifiers_deterministically() -> None:
    payload = json.dumps(
        [
            {
                "id": 1,
                "formats": [
                    f"{CALIBRE_LIBRARY_PREFIX}/Book/Book.pdf",
                    f"{CALIBRE_LIBRARY_PREFIX}\\Book\\Book.epub",
                ],
                "identifiers": {"zeta": "2", "alpha": "1"},
            }
        ]
    ).encode()

    record = parse_calibredb_inventory_page(payload)[0]
    assert tuple(item.format_label for item in record.formats) == ("EPUB", "PDF")
    assert record.identifiers == (("alpha", "1"), ("zeta", "2"))


@pytest.mark.parametrize(
    "fixture_name",
    (
        "list_invalid_json.json",
        "list_absolute_path.json",
        "list_non_monotonic.json",
    ),
)
def test_inventory_parser_rejects_malformed_fixture_pages(fixture_name: str) -> None:
    with pytest.raises(CalibreLibraryParseError):
        parse_calibredb_inventory_page(_fixture_bytes("malformed", fixture_name))


@pytest.mark.parametrize(
    "locator",
    (
        "C:/private/book.epub",
        "//server/share/book.epub",
        "https://example.invalid/book.epub",
        f"{CALIBRE_LIBRARY_PREFIX}/../book.epub",
        f"{CALIBRE_LIBRARY_PREFIX}/folder/./book.epub",
        f"{CALIBRE_LIBRARY_PREFIX}/C:/book.epub",
        f"{CALIBRE_LIBRARY_PREFIX}/folder/book.epub:stream",
        f"{CALIBRE_LIBRARY_PREFIX}/\\?\\C:\\book.epub",
        f"{CALIBRE_LIBRARY_PREFIX}/folder/book",
    ),
)
def test_inventory_parser_rejects_unsafe_format_locators(locator: str) -> None:
    payload = json.dumps([{"id": 1, "formats": [locator]}]).encode()
    with pytest.raises(CalibreLibraryParseError):
        parse_calibredb_inventory_page(payload)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        ["not-a-record"],
        [{"id": True, "formats": []}],
        [{"id": 1}],
        [{"id": 1, "formats": None}],
        [
            {"id": 1, "formats": [f"{CALIBRE_LIBRARY_PREFIX}/Book/Book.epub"]},
            {"id": 1, "formats": []},
        ],
        [{"id": 1, "formats": [f"{CALIBRE_LIBRARY_PREFIX}/Book/Book.epub"] * 2}],
    ),
)
def test_inventory_parser_rejects_invalid_shapes(payload: object) -> None:
    with pytest.raises(CalibreLibraryParseError):
        parse_calibredb_inventory_page(json.dumps(payload).encode())


def test_inventory_parser_rejects_more_than_one_bounded_page() -> None:
    payload = json.dumps([{"id": record_id, "formats": []} for record_id in range(501)]).encode()
    with pytest.raises(CalibreLibraryParseError, match="record limit"):
        parse_calibredb_inventory_page(payload)


def test_inventory_parser_enforces_utf8_and_configured_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CalibreLibraryParseError):
        parse_calibredb_inventory_page(b"[\xff]")

    monkeypatch.setattr(calibre_library, "MAX_CALIBRE_LIST_STDOUT_BYTES", 2)
    with pytest.raises(CalibreLibraryParseError):
        parse_calibredb_inventory_page(b"[ ]")


def test_inventory_parse_failures_do_not_echo_private_payloads() -> None:
    private_sentinel = "C:/private/sentinel/book.epub"
    payload = json.dumps([{"id": 1, "formats": [private_sentinel]}]).encode()
    with pytest.raises(CalibreLibraryParseError) as raised:
        parse_calibredb_inventory_page(payload)
    assert private_sentinel not in str(raised.value)
