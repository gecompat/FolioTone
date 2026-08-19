"""Static non-execution gates for the W9 consolidation package."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION_ROOT = REPOSITORY_ROOT / "src" / "foliotone" / "consolidation"
CALIBRE_LIBRARY_FILE = (
    REPOSITORY_ROOT / "src" / "foliotone" / "adapters" / "calibre" / "library.py"
)

FORBIDDEN_MODULES = frozenset({"os", "pathlib", "shutil", "subprocess"})
FORBIDDEN_CALLS = frozenset(
    {
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.replace",
        "shutil.move",
        "shutil.rmtree",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
    }
)
FORBIDDEN_PUBLIC_SURFACE = re.compile(
    r"^(execute|apply|delete|move|rename|quarantine|purge)(?:_|$)"
)
FORBIDDEN_CALIBRE_SUBCOMMANDS = frozenset(
    {
        "add",
        "add_format",
        "remove",
        "remove_format",
        "set_metadata",
        "embed_metadata",
        "backup_metadata",
        "restore_database",
        "export",
    }
)
ALLOWED_CALIBRE_SUBCOMMANDS = frozenset(
    {
        "--version",
        "list",
        "search",
        "show_metadata",
        "list_categories",
    }
)


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value, aliases)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = f"{node.module}.{alias.name}"
    return aliases


def _public_surface_names(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                names.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not child.name.startswith("_"):
                        names.append(child.name)
    return tuple(names)


def _calibre_subcommands(tree: ast.AST) -> set[str]:
    subcommands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        if func_name not in {
            "_read_command",
            "LocalCommand",
            "build_calibredb_version_command",
            "build_calibredb_inventory_command",
            "build_calibredb_exact_id_command",
            "build_calibredb_show_metadata_command",
            "build_calibredb_list_categories_command",
        }:
            continue
        for argument in node.args:
            if not isinstance(argument, ast.Tuple):
                continue
            for item in argument.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    if item.value.startswith("--"):
                        continue
                    subcommands.add(item.value)
                    break
    return subcommands


def test_consolidation_package_has_no_mutating_imports_calls_or_public_surfaces() -> None:
    files = _python_files(CONSOLIDATION_ROOT)
    assert files, "expected consolidation package sources"

    forbidden_imports: list[str] = []
    forbidden_calls: list[str] = []
    forbidden_keywords: list[str] = []
    forbidden_surfaces: list[str] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        aliases = _import_aliases(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in FORBIDDEN_MODULES:
                        forbidden_imports.append(f"{path.name}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module.split(".", 1)[0] in FORBIDDEN_MODULES:
                    forbidden_imports.append(f"{path.name}:{node.module}")
            elif isinstance(node, ast.Call):
                qualified = _qualified_name(node.func, aliases)
                if qualified in FORBIDDEN_CALLS:
                    forbidden_calls.append(f"{path.name}:{qualified}")
                if qualified is not None and qualified.endswith(".replace"):
                    # datetime.replace() is allowed; path mutations are blocked via pathlib imports.
                    continue
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    forbidden_keywords.append(f"{path.name}:shell=True")

        for name in _public_surface_names(tree):
            lowered = name.lower()
            if FORBIDDEN_PUBLIC_SURFACE.match(lowered):
                forbidden_surfaces.append(f"{path.name}:{name}")

    assert not forbidden_imports, (
        f"forbidden imports in consolidation package: {forbidden_imports}"
    )
    assert not forbidden_calls, f"forbidden calls in consolidation package: {forbidden_calls}"
    assert not forbidden_keywords, (
        "forbidden shell keywords in consolidation package: "
        f"{forbidden_keywords}"
    )
    assert not forbidden_surfaces, (
        "forbidden public surfaces in consolidation package: "
        f"{forbidden_surfaces}"
    )


def test_calibre_library_command_builders_remain_read_only() -> None:
    source = CALIBRE_LIBRARY_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CALIBRE_LIBRARY_FILE))

    subcommands = _calibre_subcommands(tree)
    assert subcommands <= ALLOWED_CALIBRE_SUBCOMMANDS, subcommands
    assert not (subcommands & FORBIDDEN_CALIBRE_SUBCOMMANDS), subcommands
