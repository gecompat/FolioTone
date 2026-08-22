from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/contracts.py",
    ROOT / "src/foliotone/metadata_write/epub_title.py",
    ROOT / "src/foliotone/metadata_write/__init__.py",
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

    for source_file in SOURCE_FILES:
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


def test_pure_epub_title_slice_is_not_wired_to_cli_or_persistence() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    persistence_files = tuple((ROOT / "src/foliotone/persistence").rglob("*.py"))

    assert "foliotone.metadata_write" not in cli
    assert "epub-title-write" not in cli
    assert all(
        "foliotone.metadata_write" not in path.read_text(encoding="utf-8")
        for path in persistence_files
    )
