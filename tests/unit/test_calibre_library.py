from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from foliotone.adapters.calibre.common import calibre_version_policy
from foliotone.adapters.calibre.library import (
    CALIBRE_LIBRARY_CATEGORIES,
    CALIBRE_LIBRARY_CONFIG_DIRECTORY,
    CALIBRE_LIBRARY_FIELDS,
    CALIBRE_LIBRARY_PREFIX,
    MAX_CALIBRE_CATEGORIES_STDOUT_BYTES,
    MAX_CALIBRE_LIST_STDOUT_BYTES,
    MAX_CALIBRE_METADATA_STDOUT_BYTES,
    MAX_CALIBRE_SEARCH_STDOUT_BYTES,
    build_calibredb_exact_id_command,
    build_calibredb_inventory_command,
    build_calibredb_list_categories_command,
    build_calibredb_show_metadata_command,
    build_calibredb_version_command,
)
from foliotone.core import ToolCapability
from foliotone.tooling.runtime import LocalCommand


def _library_path() -> Path:
    return Path.cwd() / "synthetic-calibre-library"


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
    assert {command.version_policy for command in commands} == {calibre_version_policy}
    assert all(
        command.workspace_environment
        == {"CALIBRE_CONFIG_DIRECTORY": CALIBRE_LIBRARY_CONFIG_DIRECTORY}
        for command in commands
    )
    assert all(
        command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"}
        for command in commands
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
