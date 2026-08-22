from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
PURE_SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/contracts.py",
    ROOT / "src/foliotone/metadata_write/epub_title.py",
)
STAGING_SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/staging.py",
    ROOT / "src/foliotone/metadata_write/validation.py",
)


def test_pure_epub_title_slice_has_no_filesystem_process_database_or_network_surface() -> None:
    forbidden_import_roots = {
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlalchemy",
        "subprocess",
        "tempfile",
        "urllib",
    }
    forbidden_name_calls = {
        "open",
    }
    forbidden_attribute_calls = {
        "remove",
        "rename",
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }

    for source_file in PURE_SOURCE_FILES:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_attributes.add(node.func.attr)
        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_names.isdisjoint(forbidden_name_calls)
        assert called_attributes.isdisjoint(forbidden_attribute_calls)


def test_private_staging_has_no_source_commit_cli_persistence_or_network_surface() -> None:
    forbidden_import_roots = {
        "socket",
        "sqlalchemy",
        "urllib",
    }
    forbidden_attribute_calls = {
        "copy2",
        "execute_container",
        "execute_local",
        "move",
        "remove",
        "rename",
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }

    for source_file in STAGING_SOURCE_FILES:
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_file))
        imported_roots: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)
        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_attributes.isdisjoint(forbidden_attribute_calls)
        assert "shutil.copy" not in source
        assert "shutil.move" not in source
        assert "foliotone.persistence" not in source
        assert "foliotone.cli" not in source


def test_private_validator_invokes_processes_without_a_shell() -> None:
    validation = STAGING_SOURCE_FILES[1]
    tree = ast.parse(validation.read_text(encoding="utf-8"), filename=str(validation))
    process_calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    )

    assert len(process_calls) == 1
    shell_keywords = tuple(
        keyword
        for keyword in process_calls[0].keywords
        if keyword.arg == "shell"
    )
    assert len(shell_keywords) == 1
    assert isinstance(shell_keywords[0].value, ast.Constant)
    assert shell_keywords[0].value.value is False


def test_pure_epub_title_slice_is_not_wired_to_cli_or_persistence() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    persistence_files = tuple((ROOT / "src/foliotone/persistence").rglob("*.py"))

    assert "foliotone.metadata_write" not in cli
    assert "epub-title-write" not in cli
    assert all(
        "foliotone.metadata_write" not in path.read_text(encoding="utf-8")
        for path in persistence_files
    )
